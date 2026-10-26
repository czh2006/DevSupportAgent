import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent.events import AgentEvent
from app.agent.runner import AgentResult, TroubleshootingAgent
from app.api.agent_runs import get_agent
from app.integrations.mcp_logs import LogToolError
from app.main import app
from app.schemas.log_evidence import LogEvidenceResult


REQUEST_ID = "req_" + "1" * 32


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def create_case(client):
    response = client.post("/sessions", json={
        "title": "Event test",
        "problem_description": "Request failed",
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_events_are_persisted_and_ordered(client):
    fake = SimpleNamespace(run=AsyncMock(
        return_value=AgentResult(
            status="answered",
            answer="Evidence-backed answer.",
        )
    ))
    app.dependency_overrides[get_agent] = lambda: fake

    async def emit(on_event):
        await on_event(AgentEvent(
            event_type="model_started",
            step=1,
        ))
        await on_event(AgentEvent(
            event_type="model_finished",
            step=1,
            duration_ms=4,
        ))
        return AgentResult(status="answered", answer="Done")

    async def run(**kwargs):
        return await emit(kwargs["on_event"])

    fake.run.side_effect = run
    try:
        session_id = create_case(client)
        response = client.post(
            f"/sessions/{session_id}/agent-runs",
            json={"question": "Why?"},
        )
        assert response.status_code == 200
        run_id = response.json()["id"]

        events = client.get(
            f"/sessions/{session_id}/agent-runs/{run_id}/events"
        )
        assert events.status_code == 200
        data = events.json()
        assert [item["event_type"] for item in data] == [
            "run_started",
            "model_started",
            "model_finished",
            "run_finished",
        ]
        assert [item["id"] for item in data] == sorted(
            item["id"] for item in data
        )
        assert data[2]["duration_ms"] == 4
    finally:
        app.dependency_overrides.pop(get_agent, None)


def test_events_cannot_cross_session_boundary(client):
    fake = SimpleNamespace(run=AsyncMock(
        return_value=AgentResult(status="needs_input", answer="Need context.")
    ))
    app.dependency_overrides[get_agent] = lambda: fake
    try:
        first = create_case(client)
        second = create_case(client)
        run_id = client.post(
            f"/sessions/{first}/agent-runs",
            json={"question": "Help"},
        ).json()["id"]
        response = client.get(
            f"/sessions/{second}/agent-runs/{run_id}/events"
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_agent, None)


def test_unexpected_failure_is_visible_in_event_history(client):
    fake = SimpleNamespace(run=AsyncMock(
        side_effect=RuntimeError("private internal detail")
    ))
    app.dependency_overrides[get_agent] = lambda: fake
    try:
        session_id = create_case(client)
        try:
            client.post(
                f"/sessions/{session_id}/agent-runs",
                json={"question": "Help"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected the original exception to propagate.")

        history = client.get(
            f"/sessions/{session_id}/agent-runs/{_latest_run_id(client)}/events"
        )
        assert history.status_code == 200
        assert history.json()[-1]["event_type"] == "run_failed"
        assert history.json()[-1]["error_code"] == "INTERNAL_ERROR"
        assert "private internal detail" not in history.text
    finally:
        app.dependency_overrides.pop(get_agent, None)


def _latest_run_id(client):
    from sqlalchemy import select

    from app.storage.database import get_db
    from app.storage.models import AgentRun

    generator = app.dependency_overrides[get_db]()
    try:
        db = next(generator)
        return db.scalar(select(AgentRun.id))
    finally:
        generator.close()


def test_runner_emits_model_and_tool_events():
    from langchain_core.messages import AIMessage

    model = FakeModel([
        AIMessage(content="", tool_calls=[{
            "name": "get_request_log",
            "args": {},
            "id": "call_1",
            "type": "tool_call",
        }]),
        AIMessage(content="The gateway rejected authentication."),
    ])
    evidence = LogEvidenceResult.model_validate({
        "status": "found",
        "request_id": REQUEST_ID,
        "record": {
            "request_id": REQUEST_ID,
            "project_id": "demo-project",
            "service": "demo-api",
            "environment": "local",
            "method": "POST",
            "route": "/v1/chat",
            "http_status_code": 401,
            "duration_ms": 1.2,
            "error_code": "INVALID_API_KEY",
            "upstream_status_code": None,
            "retry_after_seconds": None,
            "created_at": "2026-10-26T00:00:00+00:00",
            "source": "http_middleware",
        },
    })
    logs = SimpleNamespace(get_request_log=AsyncMock(return_value=evidence))
    events = []

    async def record(event):
        events.append(event)

    async def run():
        return await TroubleshootingAgent(model, logs).run(
            "Why did this fail?",
            REQUEST_ID,
            "local",
            on_event=record,
        )

    result = asyncio.run(run())
    assert result.status == "answered"
    assert [event.event_type for event in events] == [
        "model_started",
        "model_finished",
        "tool_started",
        "tool_finished",
        "model_started",
        "model_finished",
    ]
    assert events[2].operation == "get_request_log"
    assert events[1].duration_ms is not None
    logs.get_request_log.assert_awaited_once_with(REQUEST_ID)


def test_runner_emits_tool_failure_code():
    from langchain_core.messages import AIMessage

    model = FakeModel([AIMessage(content="", tool_calls=[{
        "name": "get_request_log",
        "args": {},
        "id": "call_1",
        "type": "tool_call",
    }])])
    logs = SimpleNamespace(get_request_log=AsyncMock(
        side_effect=LogToolError("MCP_UNAVAILABLE")
    ))
    events = []

    async def record(event):
        events.append(event)

    async def run():
        return await TroubleshootingAgent(model, logs).run(
            "Why did this fail?",
            REQUEST_ID,
            "local",
            on_event=record,
        )

    result = asyncio.run(run())
    assert result.status == "tool_error"
    failure, = [event for event in events if event.event_type == "tool_failed"]
    assert failure.error_code == "MCP_UNAVAILABLE"


def test_model_failure_event_keeps_error_code_sanitized():
    from openai import APITimeoutError

    model = FakeModel([APITimeoutError(request=None)])
    logs = SimpleNamespace(get_request_log=AsyncMock())
    events = []

    async def record(event):
        events.append(event)

    async def run():
        return await TroubleshootingAgent(model, logs).run(
            "Why did this fail?",
            REQUEST_ID,
            "local",
            on_event=record,
        )

    result = asyncio.run(run())
    assert result.status == "model_error"
    failure, = [event for event in events if event.event_type == "model_failed"]
    assert failure.error_code == "LLM_TIMEOUT"
    assert failure.outcome is None
    logs.get_request_log.assert_not_awaited()
