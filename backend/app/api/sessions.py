from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.session import SessionCreate, SessionResponse
from app.storage.database import get_db
from app.storage.models import TroubleshootingSession


router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: SessionCreate,
    db_session: DatabaseSession,
) -> TroubleshootingSession:
    troubleshooting_session = TroubleshootingSession(
        title=payload.title,
        problem_description=payload.problem_description,
    )

    db_session.add(troubleshooting_session)
    db_session.commit()
    db_session.refresh(troubleshooting_session)

    return troubleshooting_session


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
)
def get_session(
    session_id: str,
    db_session: DatabaseSession,
) -> TroubleshootingSession:
    troubleshooting_session = db_session.get(
        TroubleshootingSession,
        session_id,
    )

    if troubleshooting_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="排障会话不存在",
        )

    return troubleshooting_session