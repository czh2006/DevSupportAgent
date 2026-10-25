from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.extraction.context_extractor import ContextExtractor
from app.extraction.pipeline import get_context_extractor
from app.schemas.context_suggestion import ContextSuggestionResponse
from app.services.session_service import SessionService
from app.storage.database import get_db


router = APIRouter(
    prefix="/sessions",
    tags=["context suggestions"],
)

DatabaseSession = Annotated[
    Session,
    Depends(get_db),
]

ExtractorDependency = Annotated[
    ContextExtractor,
    Depends(get_context_extractor),
]


@router.post(
    "/{session_id}/messages/{message_id}/context-suggestion",
    response_model=ContextSuggestionResponse,
)
def suggest_context(
    session_id: str,
    message_id: int,
    db_session: DatabaseSession,
    extractor: ExtractorDependency,
) -> ContextSuggestionResponse:
    session_service = SessionService(db_session)

    message = session_service.get_message(
        session_id,
        message_id,
    )

    candidate = extractor.extract(message.content)

    return ContextSuggestionResponse(
        session_id=session_id,
        message_id=message_id,
        candidate=candidate,
    )