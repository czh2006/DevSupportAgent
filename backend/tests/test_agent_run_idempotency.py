from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.runner import AgentResult
from app.api.agent_runs import get_agent
from app.main import app
from app.services.agent_run_service import AgentRunService
from app.storage.database import get_db


@pytest.fixture
def fake_agent(client):
    fake = SimpleNamespace(
        run=AsyncMock(
            return_value=AgentResult(
                status="needs_input",
                answer="Please provide the missing context.",
            )
        )
    )
    app.dependency_overrides[get_agent] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_agent, None)


def create_session(client):
    response = client.post(
        "/sessions",
        json={
            "title": "Idempotency test",
            "problem_description": "A request failed.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def run_request(client, session_id, question, key, request_id=None):
    if request_id is not None:
        context = client.put(
            f"/sessions/{session_id}/context",
            json={"environment": "local", "request_id": request_id},
        )
        assert context.status_code == 200

    return client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": question},
        headers={"Idempotency-Key": key},
    )


def test_repeated_key_reuses_completed_run(client, fake_agent):
    session_id = create_session(client)

    first = run_request(client, session_id, "Help me", "retry-001")
    second = run_request(client, session_id, "Help me", "retry-001")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["execution_status"] == "completed"
    assert fake_agent.run.await_count == 1


def test_same_key_with_different_question_returns_conflict(
    client,
    fake_agent,
):
    session_id = create_session(client)
    first = run_request(client, session_id, "First question", "retry-002")
    second = run_request(client, session_id, "Different question", "retry-002")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert fake_agent.run.await_count == 1


def test_same_key_with_changed_context_returns_conflict(
    client,
    fake_agent,
):
    session_id = create_session(client)
    run_request(
        client,
        session_id,
        "Help me",
        "retry-003",
        request_id="req_" + "1" * 32,
    )
    response = run_request(
        client,
        session_id,
        "Help me",
        "retry-003",
        request_id="req_" + "2" * 32,
    )

    assert response.status_code == 409
    assert fake_agent.run.await_count == 1


def test_same_key_is_scoped_to_session(client, fake_agent):
    first_session = create_session(client)
    second_session = create_session(client)

    first = run_request(client, first_session, "Help me", "retry-004")
    second = run_request(client, second_session, "Help me", "retry-004")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert fake_agent.run.await_count == 2


def test_replay_while_original_run_is_running(client):
    session_id = create_session(client)
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        service = AgentRunService(db)
        first = service.reserve(
            session_id,
            "Help me",
            None,
            None,
            "retry-005",
        )
        replay = service.reserve(
            session_id,
            "Help me",
            None,
            None,
            "retry-005",
        )

        assert first.created is True
        assert replay.created is False
        assert replay.run.id == first.run.id
        assert replay.run.execution_status == "running"
        assert replay.run.result is None
    finally:
        generator.close()


def test_idempotency_key_length_is_validated(client, fake_agent):
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "Help me"},
        headers={"Idempotency-Key": "k" * 129},
    )

    assert response.status_code == 422
    fake_agent.run.assert_not_awaited()
