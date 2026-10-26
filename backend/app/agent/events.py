from collections.abc import Awaitable, Callable
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter
from typing import Literal

import httpx
from openai import APIError, APITimeoutError
from pydantic import BaseModel, Field

from app.integrations.mcp_logs import LogToolError


class AgentEvent(BaseModel):
    event_type: Literal[
        "run_started",
        "model_started",
        "model_finished",
        "model_failed",
        "tool_started",
        "tool_finished",
        "tool_failed",
        "run_finished",
        "run_failed",
        "run_interrupted",
        "run_cancel_requested",
        "run_cancelled",
    ]
    step: int | None = Field(default=None, ge=1)
    operation: str | None = None
    outcome: str | None = None
    error_code: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


EventSink = Callable[[AgentEvent], Awaitable[None]]
logger = logging.getLogger(__name__)


@asynccontextmanager
async def observe_call(
    stage: Literal["model", "tool"],
    step: int,
    sink: EventSink | None,
    operation: str | None = None,
):
    if sink is None:
        yield
        return

    await sink(AgentEvent(
        event_type=f"{stage}_started",
        step=step,
        operation=operation,
    ))
    started = perf_counter()

    try:
        yield
    except Exception as exc:
        if isinstance(exc, LogToolError):
            error_code = exc.code
        elif isinstance(exc, (APITimeoutError, httpx.TimeoutException)):
            error_code = "LLM_TIMEOUT"
        elif isinstance(exc, TimeoutError):
            error_code = "AGENT_TIMEOUT"
        elif isinstance(exc, (APIError, httpx.HTTPError)):
            error_code = "LLM_UNAVAILABLE"
        else:
            error_code = "INTERNAL_ERROR"

        try:
            await sink(AgentEvent(
                event_type=f"{stage}_failed",
                step=step,
            operation=operation,
                error_code=error_code,
                duration_ms=round(
                    (perf_counter() - started) * 1000
                ),
            ))
        except Exception:
            logger.exception("agent_failure_event_save_failed stage=%s", stage)
        raise
    else:
        await sink(AgentEvent(
            event_type=f"{stage}_finished",
            step=step,
            operation=operation,
            duration_ms=round(
                (perf_counter() - started) * 1000
            ),
        ))
