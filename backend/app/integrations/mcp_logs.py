import asyncio

import anyio
import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import (
    StreamableHTTPError,
    streamable_http_client,
)
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.log_evidence import LogEvidenceResult


TIMEOUT_ERRORS = (
    TimeoutError,
    httpx2.TimeoutException,
)

CONNECTION_ERRORS = (
    httpx2.HTTPError,
    MCPError,
    StreamableHTTPError,
    anyio.EndOfStream,
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
)


class LogToolError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class McpLogClient:
    def __init__(
        self,
        url: str,
        project_id: str,
        timeout: float,
    ):
        self.url = url
        self.project_id = project_id
        self.timeout = timeout

    async def _call(self, request_id: str):
        async with asyncio.timeout(self.timeout):
            async with httpx2.AsyncClient(
                trust_env=False,
                timeout=self.timeout,
            ) as http:
                transport = streamable_http_client(
                    self.url,
                    http_client=http,
                )

                async with Client(transport) as client:
                    return await client.call_tool(
                        "get_request_log",
                        {"request_id": request_id},
                    )

    async def get_request_log(
        self,
        request_id: str,
    ) -> LogEvidenceResult:
        try:
            result = await self._call(request_id)

        except TIMEOUT_ERRORS as exc:
            raise LogToolError(
                "MCP_TIMEOUT"
            ) from exc

        except CONNECTION_ERRORS as exc:
            raise LogToolError(
                "MCP_UNAVAILABLE"
            ) from exc

        except ExceptionGroup as exc:
            _, unexpected = exc.split(
                TIMEOUT_ERRORS + CONNECTION_ERRORS
            )

            if unexpected is not None:
                raise

            code = (
                "MCP_TIMEOUT"
                if exc.subgroup(TIMEOUT_ERRORS)
                else "MCP_UNAVAILABLE"
            )

            raise LogToolError(code) from exc

        if result.is_error:
            raise LogToolError("MCP_TOOL_ERROR")

        try:
            data = LogEvidenceResult.model_validate(
                result.structured_content
            )
        except ValidationError as exc:
            raise LogToolError(
                "MCP_INVALID_RESPONSE"
            ) from exc

        if data.request_id != request_id:
            raise LogToolError("MCP_INVALID_RESPONSE")

        if data.record is not None:
            record = data.record

            if (
                record.request_id != request_id
                or record.project_id != self.project_id
                or record.environment != "local"
            ):
                raise LogToolError(
                    "MCP_INVALID_RESPONSE"
                )

        return data


def get_mcp_log_client() -> McpLogClient:
    return McpLogClient(
        url=settings.mcp_log_url,
        project_id=settings.mcp_log_project_id,
        timeout=settings.mcp_log_timeout_seconds,
    )