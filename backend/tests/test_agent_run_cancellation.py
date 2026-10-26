import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.runner import AgentResult, AgentRunCancelled, TroubleshootingAgent
from app.agent.events import AgentEvent
from app.api.agent_runs import get_agent, wait_for_agent_task
from app.main import app
from app.services.agent_event_service import AgentEventService
from app.services.agent_run_service import AgentRunService
from app.storage.database import get_db


def create_session(client):
    response = client.post(
        "/sessions",
        json={
            "title": "Cancellation test",
            "problem_description": "A request failed.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def reserve_run(session_id, question="Investigate request", key=None):
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        reservation = AgentRunService(db).reserve(
            session_id,
            question,
            None,
            None,
            key,
        )
        return reservation.run.id
    finally:
        generator.close()


def finish_run(run_id, result):
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        return AgentRunService(db).finish(run_id, 25, result)
    finally:
        generator.close()


def test_cancel_request_is_idempotent_and_wins_over_late_result(client):
    session_id = create_session(client)
    idempotency_key = "cancel-request-key"
    run_id = reserve_run(
        session_id,
        key=idempotency_key,
    )
    cancel_url = f"/sessions/{session_id}/agent-runs/cancel"
    headers = {"Idempotency-Key": idempotency_key}

    first = client.post(cancel_url, headers=headers)
    second = client.post(cancel_url, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["execution_status"] == "cancel_requested"
    assert second.json()["execution_status"] == "cancel_requested"

    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        AgentEventService(db).append(
            run_id,
            AgentEvent(
                event_type="model_finished",
                step=1,
                duration_ms=12,
            ),
        )
    finally:
        generator.close()

    completed = finish_run(
        run_id,
        AgentResult(status="answered", answer="A late result."),
    )
    assert completed.execution_status == "cancelled"
    assert completed.result is None
    assert completed.error_code == "RUN_CANCELLED"

    events = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}/events"
    )
    assert [event["event_type"] for event in events.json()] == [
        "run_started",
        "run_cancel_requested",
        "model_finished",
        "run_cancelled",
    ]


def test_cancelled_idempotent_replay_does_not_start_another_agent(client):
    fake_agent = SimpleNamespace(run=AsyncMock())
    app.dependency_overrides[get_agent] = lambda: fake_agent
    try:
        session_id = create_session(client)
        question = "Investigate request"
        run_id = reserve_run(session_id, question, "cancel-retry-key")

        client.post(
            f"/sessions/{session_id}/agent-runs/cancel",
            headers={"Idempotency-Key": "cancel-retry-key"},
        )
        finish_run(run_id, None)

        replay = client.post(
            f"/sessions/{session_id}/agent-runs",
            json={"question": question},
            headers={"Idempotency-Key": "cancel-retry-key"},
        )

        assert replay.status_code == 200
        assert replay.json()["id"] == run_id
        assert replay.json()["execution_status"] == "cancelled"
        fake_agent.run.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_agent, None)


def test_cancelled_run_does_not_execute_tool_requested_by_model():
    class Model:
        cancel_requested = False

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.cancel_requested = True
            return AIMessage(content="", tool_calls=[{
                "name": "get_request_log",
                "args": {},
                "id": "call_1",
                "type": "tool_call",
            }])

    model = Model()
    logs = SimpleNamespace(get_request_log=AsyncMock())

    async def should_cancel():
        return model.cancel_requested

    async def run():
        await TroubleshootingAgent(model, logs).run(
            "Investigate the request.",
            "req_" + "1" * 32,
            "local",
            should_cancel=should_cancel,
        )

    with pytest.raises(AgentRunCancelled):
        asyncio.run(run())

    logs.get_request_log.assert_not_awaited()


def test_cannot_cancel_run_from_another_session(client):
    owner_session = create_session(client)
    other_session = create_session(client)
    run_id = reserve_run(owner_session)

    response = client.post(
        f"/sessions/{other_session}/agent-runs/{run_id}/cancel"
    )

    assert response.status_code == 404


def test_cancelling_http_wait_does_not_cancel_agent_task():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def agent_work():
            started.set()
            await release.wait()
            return AgentResult(status="answered", answer="Saved result.")

        agent_task = asyncio.create_task(agent_work())
        request_task = asyncio.create_task(
            wait_for_agent_task(agent_task, "run-1")
        )
        await started.wait()
        request_task.cancel()
        await asyncio.sleep(0)

        assert not agent_task.cancelled()

        release.set()
        result = await request_task
        assert result.answer == "Saved result."

    asyncio.run(scenario())
