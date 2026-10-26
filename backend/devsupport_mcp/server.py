import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from demo_service.config import DemoSettings
from demo_service.storage import LogStore


logger = logging.getLogger(__name__)

RequestId = Annotated[
    str,
    Field(pattern=r"^req_[0-9a-f]{32}$"),
]


class LogQueryResult(BaseModel):
    status: Literal["found", "not_found"]
    request_id: str
    record: dict[str, Any] | None = None


@dataclass
class LogContext:
    store: LogStore
    project_id: str


def create_server(
    config: DemoSettings | None = None,
) -> MCPServer:
    config = config or DemoSettings()

    @asynccontextmanager
    async def lifespan(server):
        store = LogStore(
            config.database_path,
            read_only=True,
        )

        try:
            yield LogContext(
                store=store,
                project_id=config.project_id,
            )
        finally:
            await asyncio.to_thread(store.close)

    server = MCPServer(
        "DevSupport Logs",
        lifespan=lifespan,
    )

    @server.tool()
    async def get_request_log(
        request_id: RequestId,
        ctx: Context[LogContext],
    ) -> LogQueryResult:
        """按请求编号查询当前配置项目的单条日志，返回排障证据，不推断根因。"""
        state = ctx.request_context.lifespan_context

        try:
            record = await asyncio.to_thread(
                state.store.get,
                state.project_id,
                request_id,
            )
        except SQLAlchemyError as exc:
            logger.exception("request_log_query_failed")

            raise ToolError(
                "LOG_QUERY_FAILED: "
                "日志查询失败，请检查日志库是否存在且可读。"
            ) from exc

        if record is None:
            return LogQueryResult(
                status="not_found",
                request_id=request_id,
            )

        return LogQueryResult(
            status="found",
            request_id=request_id,
            record=record,
        )

    return server


if __name__ == "__main__":
    create_server().run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8012,
        json_response=True,
    )