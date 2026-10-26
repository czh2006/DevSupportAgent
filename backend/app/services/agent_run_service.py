from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agent.runner import AgentResult
from app.schemas.agent_run import AgentRunResponse
from app.storage.models import AgentRun, current_utc_time


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

        self.db.commit()
        return run_id

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