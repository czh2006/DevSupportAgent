from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.extraction.context_extractor import extract_context_candidate
from app.schemas.context_suggestion import ContextSuggestionResponse
from app.services.session_service import SessionService
from app.storage.database import get_db


router = APIRouter(
    prefix="/sessions",
    tags=["context suggestions"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/{session_id}/messages/{message_id}/context-suggestion",
    response_model=ContextSuggestionResponse,
)
def suggest_context(
    session_id: str,
    message_id: int,
    db_session: DatabaseSession,
) -> ContextSuggestionResponse:
    session_service = SessionService(db_session)

    message = session_service.get_message(
        session_id,
        message_id,
    )

    candidate = extract_context_candidate(message.content)

    return ContextSuggestionResponse(
        session_id=session_id,
        message_id=message_id,
        candidate=candidate,
    )