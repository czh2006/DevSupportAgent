import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from app.agent.runner import TroubleshootingAgent
from app.schemas.log_evidence import LogEvidenceResult


REQUEST_ID = "req_" + "1" * 32


class FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return self.reply


def test_missing_context_does_not_call_model_or_tool():
    model = FakeModel(
        AIMessage(content="unused")
    )
    logs = SimpleNamespace(
        get_request_log=AsyncMock()
    )
    agent = TroubleshootingAgent(model, logs)

    result = asyncio.run(
        agent.run("接口失败了", None, None)
    )

    assert result.status == "needs_input"
    assert model.calls == 0
    logs.get_request_log.assert_not_awaited()


def test_answer_without_evidence_is_blocked():
    model = FakeModel(
        AIMessage(content="肯定是限流。")
    )
    logs = SimpleNamespace(
        get_request_log=AsyncMock()
    )
    agent = TroubleshootingAgent(model, logs)

    result = asyncio.run(
        agent.run(
            "为什么失败",
            REQUEST_ID,
            "local",
        )
    )

    assert result.status == "no_evidence"
    assert "肯定是限流" not in result.answer
    logs.get_request_log.assert_not_awaited()


def test_model_can_request_tool_and_stop_on_missing_log():
    reply = AIMessage(
        content="",
        tool_calls=[{
            "name": "get_request_log",
            "args": {},
            "id": "call_1",
            "type": "tool_call",
        }],
    )

    model = FakeModel(reply)
    logs = SimpleNamespace(
        get_request_log=AsyncMock(
            return_value=LogEvidenceResult(
                status="not_found",
                request_id=REQUEST_ID,
            )
        )
    )
    agent = TroubleshootingAgent(model, logs)

    result = asyncio.run(
        agent.run(
            "为什么失败",
            REQUEST_ID,
            "local",
        )
    )

    assert result.status == "no_evidence"
    assert result.tool_calls == 1
    assert model.calls == 1

    logs.get_request_log.assert_awaited_once_with(
        REQUEST_ID
    )