from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.message import MessageCreate, MessageResponse
from app.storage.database import get_db
from app.storage.models import Message, TroubleshootingSession


router = APIRouter(
    prefix="/sessions",
    tags=["messages"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


def require_session(
    session_id: str,
    db_session: Session,
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


@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    session_id: str,
    payload: MessageCreate,
    db_session: DatabaseSession,
) -> Message:
    require_session(session_id, db_session)

    message = Message(
        session_id=session_id,
        role="user",
        content=payload.content,
    )

    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)

    return message


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
)
def list_messages(
    session_id: str,
    db_session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Message]:
    require_session(session_id, db_session)

    statement = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.asc())
        .offset(offset)
        .limit(limit)
    )

    return list(db_session.scalars(statement).all())