import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.agent.runner import TroubleshootingAgent
from app.api.agent_runs import get_agent
from app.core.config import settings
from app.integrations import agent_model
from app.main import app
from app.schemas.log_evidence import LogEvidenceResult
from app.storage.database import get_db
from app.storage.models import TroubleshootingSession


def test_adapter_sends_tools_and_consumes_result(monkeypatch):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)

        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_request_log",
                            "arguments": "{}",
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {
                "role": "assistant",
                "content": (
                    "日志显示下游不可达，建议检查下游进程。"
                    "尚未执行修复。"
                ),
            }
            finish_reason = "stop"

        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    real_client = httpx.AsyncClient
    clients = []

    class MockModelClient(real_client):
        def __init__(self, **kwargs):
            super().__init__(
                transport=httpx.MockTransport(respond),
                **kwargs,
            )
            clients.append(self)

    monkeypatch.setattr(
        agent_model,
        "settings",
        SimpleNamespace(
            llm_enabled=True,
            llm_api_key=SecretStr("fake-key"),
            llm_base_url="https://model.test/v1",
            llm_model="test-model",
        ),
    )
    monkeypatch.setattr(
        agent_model.httpx,
        "AsyncClient",
        MockModelClient,
    )

    request_id = "req_" + "1" * 32

    evidence = LogEvidenceResult.model_validate(
        {
            "status": "found",
            "request_id": request_id,
            "record": {
                "request_id": request_id,
                "project_id": "demo-project",
                "service": "demo-api",
                "environment": "local",
                "method": "POST",
                "route": "/v1/chat",
                "http_status_code": 503,
                "duration_ms": 2.5,
                "error_code": "UPSTREAM_UNREACHABLE",
                "upstream_status_code": None,
                "retry_after_seconds": None,
                "created_at": "2026-10-26T00:00:00+00:00",
                "source": "http_middleware",
            },
        }
    )

    logs = SimpleNamespace(
        get_request_log=AsyncMock(return_value=evidence)
    )

    async def run():
        async with agent_model.open_agent_model() as model:
            agent = TroubleshootingAgent(model, logs)
            return await agent.run(
                question="请求失败，帮我排查。",
                request_id=request_id,
                environment="local",
            )

    result = asyncio.run(run())

    assert result.status == "answered"
    assert len(requests) == 2

    tool = requests[0]["tools"][0]["function"]
    assert tool["name"] == "get_request_log"
    assert tool["parameters"]["properties"] == {}

    tool_message = requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"

    returned_evidence = json.loads(tool_message["content"])
    assert (
        returned_evidence["record"]["error_code"]
        == "UPSTREAM_UNREACHABLE"
    )

    logs.get_request_log.assert_awaited_once_with(request_id)
    assert clients[0].is_closed


def test_disabled_model_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)

    response = client.post(
        "/sessions",
        json={
            "title": "模型关闭测试",
            "problem_description": "请求失败",
        },
    )
    session_id = response.json()["id"]

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "帮我排查"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LLM_DISABLED"


@pytest.mark.parametrize(
    "status",
    ["resolved", "handed_off"],
)
def test_closed_session_rejected(client, status):
    fake = SimpleNamespace(run=AsyncMock())
    app.dependency_overrides[get_agent] = lambda: fake

    try:
        response = client.post(
            "/sessions",
            json={
                "title": "结束会话测试",
                "problem_description": "请求失败",
            },
        )
        session_id = response.json()["id"]

        db_generator = app.dependency_overrides[get_db]()

        try:
            db = next(db_generator)
            session = db.get(
                TroubleshootingSession,
                session_id,
            )
            session.status = status
            db.commit()
        finally:
            db_generator.close()

        response = client.post(
            f"/sessions/{session_id}/agent-runs",
            json={"question": "帮我排查"},
        )

        assert response.status_code == 409
        fake.run.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_agent, None)