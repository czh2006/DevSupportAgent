import logging
import re
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.orm import Session

from app.integrations.mcp_logs import (
    LogToolError,
    McpLogClient,
    get_mcp_log_client,
)
from app.schemas.log_evidence import LogEvidenceResult
from app.services.session_service import SessionService
from app.storage.database import get_db
from app.storage.models import TroubleshootingContext


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sessions",
    tags=["evidence"],
)


def get_confirmed_request_id(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> str:
    SessionService(db).get_session(session_id)

    context = db.get(
        TroubleshootingContext,
        session_id,
    )

    if context is None or not context.request_id:
        raise HTTPException(
            status_code=409,
            detail="请先确认并保存请求编号。",
        )

    if context.environment != "local":
        raise HTTPException(
            status_code=409,
            detail="当前日志工具仅支持已确认的 local 环境。",
        )

    if re.fullmatch(
        r"req_[0-9a-f]{32}",
        context.request_id,
    ) is None:
        raise HTTPException(
            status_code=422,
            detail="请求编号不符合本地网关格式，请核对完整编号。",
        )

    return context.request_id


@router.get(
    "/{session_id}/evidence/request-log",
    response_model=LogEvidenceResult,
)
async def get_request_log_evidence(
    request_id: Annotated[
        str,
        Depends(get_confirmed_request_id),
    ],
    log_client: Annotated[
        McpLogClient,
        Depends(get_mcp_log_client),
    ],
) -> LogEvidenceResult:
    try:
        return await log_client.get_request_log(
            request_id
        )

    except LogToolError as exc:
        logger.warning(
            "mcp_log_query_failed code=%s request_id=%s",
            exc.code,
            request_id,
            exc_info=True,
        )

        status_code = {
            "MCP_TIMEOUT": 504,
            "MCP_UNAVAILABLE": 503,
        }.get(exc.code, 502)

        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": "日志证据暂不可用，请稍后重试。",
            },
        ) from exc