from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.session import SessionCreate, SessionStatus
from app.storage.models import TroubleshootingContext, TroubleshootingSession
from app.schemas.context import TroubleshootingContextUpsert
from app.storage.models import TroubleshootingContext


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

    def get_context(
        self,
        session_id: str,
    ) -> TroubleshootingContext:
        self.get_session(session_id)

        troubleshooting_context = self.db_session.get(
            TroubleshootingContext,
            session_id,
        )

        if troubleshooting_context is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="排障上下文尚未填写",
            )

        return troubleshooting_context

    def upsert_context(
        self,
        session_id: str,
        payload: TroubleshootingContextUpsert,
    ) -> TroubleshootingContext:
        troubleshooting_session = self.get_session(session_id)

        final_statuses = {
            SessionStatus.RESOLVED.value,
            SessionStatus.HANDED_OFF.value,
        }

        if troubleshooting_session.status in final_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="已结束的会话不能修改排障上下文",
            )

        troubleshooting_context = self.db_session.get(
            TroubleshootingContext,
            session_id,
        )

        if troubleshooting_context is None:
            troubleshooting_context = TroubleshootingContext(
                session_id=session_id,
            )
            self.db_session.add(troubleshooting_context)

        updates = payload.model_dump(
            exclude_unset=True,
            exclude_none=True,
            mode="json",
        )

        for field_name, value in updates.items():
            setattr(troubleshooting_context, field_name, value)

        self.db_session.commit()
        self.db_session.refresh(troubleshooting_context)

        return troubleshooting_context