from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from app.agent.runner import AgentResult
from app.api.agent_runs import get_agent
from app.main import app


REQUEST_ID = "req_" + "1" * 32


@pytest.fixture
def fake_agent(client):
    fake = SimpleNamespace(
        run=AsyncMock(
            return_value=AgentResult(
                status="needs_input",
                answer="请先确认并保存环境和请求编号。",
            )
        )
    )

    app.dependency_overrides[get_agent] = lambda: fake

    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_agent, None)


def create_case(client):
    response = client.post(
        "/sessions",
        json={
            "title": "Agent 测试",
            "problem_description": "调用本地网关失败",
        },
    )

    assert response.status_code == 201
    return response.json()["id"]


def test_agent_receives_saved_context(client, fake_agent):
    session_id = create_case(client)

    saved = client.put(
        f"/sessions/{session_id}/context",
        json={
            "environment": "local",
            "request_id": REQUEST_ID,
        },
    )
    assert saved.status_code == 200

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "为什么请求失败？"},
    )

    assert response.status_code == 200

    fake_agent.run.assert_awaited_once_with(
        question="为什么请求失败？",
        request_id=REQUEST_ID,
        environment="local",
        on_event=ANY,
    )


def test_missing_context_reaches_agent_as_none(
    client,
    fake_agent,
):
    session_id = create_case(client)

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "帮我排查"},
    )

    assert response.status_code == 200
    assert (
        response.json()["result"]["status"]
        == "needs_input"
    )

    fake_agent.run.assert_awaited_once_with(
        question="帮我排查",
        request_id=None,
        environment=None,
        on_event=ANY,
    )


def test_missing_session_does_not_run_agent(
    client,
    fake_agent,
):
    response = client.post(
        "/sessions/missing/agent-runs",
        json={"question": "帮我排查"},
    )

    assert response.status_code == 404
    fake_agent.run.assert_not_awaited()


def test_request_cannot_override_context(
    client,
    fake_agent,
):
    session_id = create_case(client)

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={
            "question": "帮我排查",
            "request_id": REQUEST_ID,
        },
    )

    assert response.status_code == 422
    fake_agent.run.assert_not_awaited()
