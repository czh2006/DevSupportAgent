from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas.context import (
    TroubleshootingContextResponse,
    TroubleshootingContextUpsert,
)
from app.services.session_service import SessionService
from app.storage.database import get_db
from app.storage.models import TroubleshootingContext


router = APIRouter(
    prefix="/sessions",
    tags=["context"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.put(
    "/{session_id}/context",
    response_model=TroubleshootingContextResponse,
)
def upsert_context(
    session_id: str,
    payload: TroubleshootingContextUpsert,
    db_session: DatabaseSession,
) -> TroubleshootingContext:
    session_service = SessionService(db_session)

    return session_service.upsert_context(
        session_id,
        payload,
    )


@router.get(
    "/{session_id}/context",
    response_model=TroubleshootingContextResponse,
)
def get_context(
    session_id: str,
    db_session: DatabaseSession,
) -> TroubleshootingContext:
    session_service = SessionService(db_session)

    return session_service.get_context(session_id)