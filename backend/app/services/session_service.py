from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.session import SessionCreate, SessionStatus
from app.storage.models import TroubleshootingSession


class SessionService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def create_session(
        self,
        payload: SessionCreate,
    ) -> TroubleshootingSession:
        troubleshooting_session = TroubleshootingSession(
            title=payload.title,
            problem_description=payload.problem_description,
            status=SessionStatus.CREATED.value,
        )

        self.db_session.add(troubleshooting_session)
        self.db_session.commit()
        self.db_session.refresh(troubleshooting_session)

        return troubleshooting_session

    def get_session(
        self,
        session_id: str,
    ) -> TroubleshootingSession:
        troubleshooting_session = self.db_session.get(
            TroubleshootingSession,
            session_id,
        )

        if troubleshooting_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="排障会话不存在",
            )

        return troubleshooting_session

    def start_investigation(
        self,
        session_id: str,
    ) -> TroubleshootingSession:
        troubleshooting_session = self.get_session(session_id)

        if troubleshooting_session.status != SessionStatus.CREATED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前会话不能开始排查",
            )

        troubleshooting_session.status = SessionStatus.INVESTIGATING.value

        self.db_session.commit()
        self.db_session.refresh(troubleshooting_session)

        return troubleshooting_session