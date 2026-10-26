from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
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

STALE_RUN_AFTER = timedelta(minutes=3)


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
        row = self.db.get(
            AgentRun,
            run_id,
            populate_existing=True,
        )

        if row is None or row.execution_status not in {
            "running",
            "cancel_requested",
        }:
            raise RuntimeError(
                "Agent run is missing or already finished."
            )

        session_id = row.session_id

        cancelled = row.execution_status == "cancel_requested"
        if cancelled:
            row.execution_status = "cancelled"
        else:
            row.execution_status = (
                "completed"
                if result is not None
                else "failed"
            )

        row.result_json = (
            result.model_dump_json()
            if result is not None and not cancelled
            else None
        )

        if cancelled:
            row.error_code = "RUN_CANCELLED"
            event_type = "run_cancelled"
            outcome = "cancelled"
        elif result is not None:
            row.error_code = result.error_code
            event_type = "run_finished"
            outcome = result.status
        else:
            row.error_code = "INTERNAL_ERROR"
            event_type = "run_failed"
            outcome = None

        row.duration_ms = duration_ms
        row.finished_at = current_utc_time()
        self.db.add(AgentRunEvent(
            run_id=run_id,
            event_type=event_type,
            outcome=outcome,
            error_code=row.error_code,
            duration_ms=duration_ms,
            created_at=current_utc_time(),
        ))

        self.db.commit()

        return self.get(session_id, run_id)

    def request_cancel(
        self,
        session_id: str,
        run_id: str,
    ) -> AgentRunResponse:
        current = self.get(session_id, run_id)
        if current.execution_status != "running":
            return current

        now = current_utc_time()
        changed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.session_id == session_id,
                AgentRun.execution_status == "running",
            )
            .values(execution_status="cancel_requested")
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:
            self.db.add(AgentRunEvent(
                run_id=run_id,
                event_type="run_cancel_requested",
                outcome="cancel_requested",
                created_at=now,
            ))

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.get(session_id, run_id)

    def request_cancel_by_key(
        self,
        session_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        key_hash = sha256(idempotency_key.encode("utf-8")).hexdigest()
        mapping = self.db.get(AgentRunKey, (session_id, key_hash))
        if mapping is None:
            raise HTTPException(404, "Agent run not found.")
        return self.request_cancel(session_id, mapping.run_id)

    def is_cancel_requested(self, run_id: str) -> bool:
        status = self.db.scalar(
            select(AgentRun.execution_status)
            .where(AgentRun.id == run_id)
        )
        return status == "cancel_requested"

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

        row = self._interrupt_if_stale(row)

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

    def _interrupt_if_stale(self, row: AgentRun) -> AgentRun:
        active_statuses = ("running", "cancel_requested")
        if row.execution_status not in active_statuses:
            return row

        now = current_utc_time()
        cutoff = (now - STALE_RUN_AFTER).replace(tzinfo=None)
        created_at = row.created_at
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(
                tzinfo=None,
            )
        if created_at > cutoff:
            return row

        # Update status and append its event together; the conditional update
        # ensures concurrent readers can only create one interruption event.
        changed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == row.id,
                AgentRun.execution_status.in_(active_statuses),
                AgentRun.created_at <= cutoff,
            )
            .values(
                execution_status="interrupted",
                error_code="RUN_INTERRUPTED",
                finished_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:
            self.db.add(AgentRunEvent(
                run_id=row.id,
                event_type="run_interrupted",
                outcome="interrupted",
                error_code="RUN_INTERRUPTED",
                created_at=now,
            ))

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        refreshed = self.db.get(
            AgentRun,
            row.id,
            populate_existing=True,
        )
        if refreshed is None:
            raise RuntimeError("Agent run disappeared during recovery.")
        return refreshed
