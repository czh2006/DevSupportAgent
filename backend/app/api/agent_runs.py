from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.runner import (
    AgentResult,
    TroubleshootingAgent,
)
from app.core.config import settings
from app.integrations.agent_model import open_agent_model
from app.integrations.mcp_logs import (
    McpLogClient,
    get_mcp_log_client,
)
from app.schemas.agent_run import AgentRunCreate
from app.schemas.session import SessionStatus
from app.services.session_service import SessionService
from app.storage.database import get_db
from app.storage.models import TroubleshootingContext

import logging
from time import perf_counter

from starlette.concurrency import run_in_threadpool

from app.schemas.agent_run import AgentRunResponse
from app.services.agent_run_service import AgentRunService


router = APIRouter(
    prefix="/sessions",
    tags=["agent"],
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    request_id: str | None
    environment: str | None


def get_agent_context(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> AgentContext:
    session = SessionService(db).get_session(session_id)

    if session.status in {
        SessionStatus.RESOLVED.value,
        SessionStatus.HANDED_OFF.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="已结束的会话不能发起新的诊断。",
        )

    context = db.get(
        TroubleshootingContext,
        session_id,
    )

    return AgentContext(
        request_id=context.request_id if context else None,
        environment=context.environment if context else None,
    )


async def get_agent(
    log_client: Annotated[
        McpLogClient,
        Depends(get_mcp_log_client),
    ],
):
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LLM_DISABLED",
                "message": "请先配置并启用模型。",
            },
        )

    async with open_agent_model() as model:
        yield TroubleshootingAgent(
            model,
            log_client,
            timeout_seconds=30,
        )


@router.post(
    "/{session_id}/agent-runs",
    response_model=AgentRunResponse,
)
async def run_agent(
    session_id: str,
    payload: AgentRunCreate,
    context: Annotated[
        AgentContext,
        Depends(get_agent_context),
    ],
    agent: Annotated[
        TroubleshootingAgent,
        Depends(get_agent),
    ],
    db: Annotated[
        Session,
        Depends(get_db),
    ],
) -> AgentRunResponse:
    service = AgentRunService(db)

    run_id = await run_in_threadpool(
        service.start,
        session_id,
        payload.question,
        context.request_id,
        context.environment,
    )

    started = perf_counter()

    try:
        result = await agent.run(
            question=payload.question,
            request_id=context.request_id,
            environment=context.environment,
        )

    except Exception:
        try:
            await run_in_threadpool(
                service.finish,
                run_id,
                round(
                    (perf_counter() - started) * 1000
                ),
                None,
            )
        except Exception:
            logger.exception(
                "agent_run_failure_save_failed run_id=%s",
                run_id,
            )

        raise

    return await run_in_threadpool(
        service.finish,
        run_id,
        round(
            (perf_counter() - started) * 1000
        ),
        result,
    )


@router.get(
    "/{session_id}/agent-runs/{run_id}",
    response_model=AgentRunResponse,
)
def get_agent_run(
    session_id: str,
    run_id: str,
    db: Annotated[
        Session,
        Depends(get_db),
    ],
) -> AgentRunResponse:
    return AgentRunService(db).get(
        session_id,
        run_id,
    )