from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.schemas.agent_event import AgentEventResponse
from app.storage.models import AgentRun, AgentRunEvent


class AgentEventService:
    def __init__(self, db: Session):
        self.db = db

    def append(self, run_id: str, event: AgentEvent) -> None:
        try:
            run = self.db.get(AgentRun, run_id)
            if run is None or run.execution_status not in {
                "running",
                "cancel_requested",
            }:
                raise RuntimeError("Cannot append to an inactive run.")

            self.db.add(AgentRunEvent(
                run_id=run_id,
                **event.model_dump(),
            ))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def list(
        self,
        session_id: str,
        run_id: str,
    ) -> list[AgentEventResponse]:
        run = self.db.get(AgentRun, run_id)
        if run is None or run.session_id != session_id:
            raise HTTPException(404, "Agent run not found.")
        rows = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id)
            .order_by(AgentRunEvent.id)
        ).all()
        return [AgentEventResponse.model_validate(row) for row in rows]
