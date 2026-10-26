from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.runner import AgentResult
from app.schemas.agent_run import AgentRunResponse
from app.storage.models import (
    AgentRun,
    AgentRunEvent,
    AgentRunKey,
    current_utc_time,
)


@dataclass(frozen=True)
class RunReservation:
    run: AgentRunResponse
    created: bool


class AgentRunService:
    def __init__(self, db: Session):
        self.db = db

    def start(
        self,
        session_id: str,
        question: str,
        request_id: str | None,
        environment: str | None,
    ) -> str:
        return self.reserve(
            session_id, question, request_id, environment,
        ).run.id

    def reserve(
        self,
        session_id: str,
        question: str,
        request_id: str | None,
        environment: str | None,
        idempotency_key: str | None = None,
    ) -> RunReservation:
        fingerprint = sha256(json.dumps(
            {
                "question": question,
                "request_id": request_id,
                "environment": environment,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key_hash = (
            sha256(idempotency_key.encode("utf-8")).hexdigest()
            if idempotency_key is not None
            else None
        )

        if idempotency_key is not None:
            existing = self.db.get(AgentRunKey, (session_id, key_hash))
            if existing is not None:
                return self._replay(existing, fingerprint)

        run_id = str(uuid4())
        self.db.add(
            AgentRun(
                id=run_id,
                session_id=session_id,
                execution_status="running",
                question=question,
                request_id=request_id,
                environment=environment,
                created_at=current_utc_time(),
            )
        )
        try:
            self.db.flush()
            self.db.add(AgentRunEvent(
                run_id=run_id,
                event_type="run_started",
                created_at=current_utc_time(),
            ))
            if idempotency_key is not None:
                self.db.add(AgentRunKey(
                    session_id=session_id,
                    key_hash=key_hash,
                    fingerprint=fingerprint,
                    run_id=run_id,
                ))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if idempotency_key is not None:
                existing = self.db.get(AgentRunKey, (session_id, key_hash))
                if existing is not None:
                    return self._replay(existing, fingerprint)
            raise
        except Exception:
            self.db.rollback()
            raise

        return RunReservation(self.get(session_id, run_id), created=True)

    def _replay(self, existing: AgentRunKey, fingerprint: str) -> RunReservation:
        if existing.fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "同一个幂等键不能用于不同的问题或排障上下文。",
                },
            )
        return RunReservation(
            self.get(existing.session_id, existing.run_id), created=False,
        )

    def finish(
        self,
        run_id: str,
        duration_ms: int,
        result: AgentResult | None,
    ) -> AgentRunResponse:
        row = self.db.get(AgentRun, run_id)

        if row is None or row.execution_status != "running":
            raise RuntimeError(
                "Agent run is missing or already finished."
            )

        session_id = row.session_id

        row.execution_status = (
            "completed"
            if result is not None
            else "failed"
        )

        row.result_json = (
            result.model_dump_json()
            if result is not None
            else None
        )

        row.error_code = (
            result.error_code
            if result is not None
            else "INTERNAL_ERROR"
        )

        row.duration_ms = duration_ms
        row.finished_at = current_utc_time()
        self.db.add(AgentRunEvent(
            run_id=run_id,
            event_type=(
                "run_finished"
                if result is not None
                else "run_failed"
            ),
            outcome=result.status if result is not None else None,
            error_code=row.error_code,
            duration_ms=duration_ms,
            created_at=current_utc_time(),
        ))

        self.db.commit()

        return self.get(session_id, run_id)

    def get(
        self,
        session_id: str,
        run_id: str,
    ) -> AgentRunResponse:
        row = self.db.get(AgentRun, run_id)

        if row is None or row.session_id != session_id:
            raise HTTPException(
                status_code=404,
                detail="Agent run not found.",
            )

        return AgentRunResponse(
            id=row.id,
            session_id=row.session_id,
            execution_status=row.execution_status,
            question=row.question,
            request_id=row.request_id,
            environment=row.environment,
            result=(
                AgentResult.model_validate_json(
                    row.result_json
                )
                if row.result_json is not None
                else None
            ),
            error_code=row.error_code,
            duration_ms=row.duration_ms,
            created_at=row.created_at,
            finished_at=row.finished_at,
        )
