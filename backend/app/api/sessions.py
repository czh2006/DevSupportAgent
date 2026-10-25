from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.session import SessionCreate, SessionResponse
from app.storage.database import get_db
from app.services.session_service import SessionService
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
    session_service = SessionService(db_session)

    return session_service.create_session(payload)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
)
def get_session(
    session_id: str,
    db_session: DatabaseSession,
) -> TroubleshootingSession:
    session_service = SessionService(db_session)

    return session_service.get_session(session_id)

@router.post(
    "/{session_id}/start",
    response_model=SessionResponse,
)
def start_investigation(
    session_id: str,
    db_session: DatabaseSession,
) -> TroubleshootingSession:
    session_service = SessionService(db_session)

    return session_service.start_investigation(session_id)