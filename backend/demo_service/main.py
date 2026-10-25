import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from secrets import compare_digest
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from demo_service.config import DemoSettings
from demo_service.limiter import FixedWindowLimiter
from demo_service.storage import LogStore

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    message: str = Field(
        min_length=1,
        max_length=1000,
    )


class UpstreamAnswer(BaseModel):
    reply: str


def failure(
    request,
    status,
    code,
    message,
    retry_after=None,
):
    request.state.error_code = code
    request.state.retry_after_seconds = retry_after

    headers = {}

    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)

    return JSONResponse(
        status_code=status,
        content={
            "request_id": request.state.request_id,
            "error": {
                "code": code,
                "message": message,
            },
        },
        headers=headers,
    )

def create_app(config=None, upstream_transport=None):
    config = config or DemoSettings()

    @asynccontextmanager
    async def lifespan(app):
        store = await asyncio.to_thread(
            LogStore,
            config.database_path,
        )

        app.state.log_store = store

        app.state.limiter = FixedWindowLimiter(
            config.rate_limit_requests,
            config.rate_limit_window_seconds,
        )

        try:
            async with httpx.AsyncClient(
                timeout=config.upstream_timeout_seconds,
                transport=upstream_transport,
            ) as client:
                app.state.upstream = client
                yield
        finally:
            await asyncio.to_thread(store.close)

    app = FastAPI(
        title="Demo API Gateway",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def capture_request(
        request: Request,
        call_next,
    ):
        request.state.request_id = f"req_{uuid4().hex}"
        request.state.error_code = None
        request.state.upstream_status_code = None
        request.state.retry_after_seconds = None

        created_at = datetime.now(timezone.utc).isoformat()
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled_request_error request_id=%s",
                request.state.request_id,
            )

            response = failure(
                request,
                500,
                "INTERNAL_ERROR",
                "Internal server error.",
            )

        route = request.scope.get("route")

        record = {
            "request_id": request.state.request_id,
            "project_id": config.project_id,
            "service": "demo-api",
            "environment": "local",
            "method": request.method,
            "route": getattr(route, "path", "unmatched"),
            "http_status_code": response.status_code,
            "duration_ms": round(
                (perf_counter() - started_at) * 1000,
                3,
            ),
            "error_code": request.state.error_code or (
                f"HTTP_{response.status_code}"
                if response.status_code >= 400
                else None
            ),
            "upstream_status_code": (
                request.state.upstream_status_code
            ),
            "retry_after_seconds": (
                request.state.retry_after_seconds
            ),
            "created_at": created_at,
            "source": "http_middleware",
        }

        try:
            await asyncio.to_thread(
                app.state.log_store.write,
                record,
            )
        except SQLAlchemyError:
            logger.exception(
                "request_log_write_failed request_id=%s",
                request.state.request_id,
            )

        response.headers["X-Request-ID"] = (
            request.state.request_id
        )

        return response

    @app.post("/v1/chat")
    async def chat(
        payload: ChatRequest,
        request: Request,
        x_api_key: str | None = Header(default=None),
    ):
        expected_key = config.api_key.get_secret_value()

        if x_api_key is None or not compare_digest(
            x_api_key.encode(),
            expected_key.encode(),
        ):
            return failure(
                request,
                401,
                "INVALID_API_KEY",
                "API key is invalid.",
            )

        retry_after = app.state.limiter.acquire()

        if retry_after is not None:
            return failure(
                request,
                429,
                "RATE_LIMIT_EXCEEDED",
                "Request limit exceeded.",
                retry_after,
            )

        try:
            upstream = await app.state.upstream.post(
                config.upstream_url,
                json=payload.model_dump(),
                headers={
                    "X-Request-ID": request.state.request_id,
                },
            )

        except httpx.ConnectTimeout:
            return failure(
                request,
                503,
                "UPSTREAM_CONNECT_TIMEOUT",
                "Cannot establish an upstream connection in time.",
            )

        except httpx.TimeoutException:
            return failure(
                request,
                504,
                "UPSTREAM_TIMEOUT",
                "Upstream timed out.",
            )

        except httpx.RequestError:
            return failure(
                request,
                503,
                "UPSTREAM_UNREACHABLE",
                "Cannot connect to upstream.",
            )

        request.state.upstream_status_code = (
            upstream.status_code
        )

        if upstream.status_code >= 500:
            return failure(
                request,
                503,
                "UPSTREAM_ERROR",
                "Upstream failed.",
            )

        if upstream.status_code >= 300:
            return failure(
                request,
                502,
                "UPSTREAM_REJECTED",
                "Upstream returned an unexpected status.",
            )

        try:
            answer = UpstreamAnswer.model_validate(
                upstream.json(),
            )
        except ValueError:
            return failure(
                request,
                502,
                "UPSTREAM_INVALID_RESPONSE",
                "Upstream response is invalid.",
            )

        return {
            "request_id": request.state.request_id,
            "reply": answer.reply,
        }

    return app
app = create_app()
