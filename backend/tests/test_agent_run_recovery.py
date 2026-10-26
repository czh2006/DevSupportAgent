from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select, update

from app.agent.runner import AgentResult
from app.api.agent_runs import get_agent
from app.main import app
from app.services.agent_run_service import AgentRunService
from app.storage.database import get_db
from app.storage.models import AgentRun, AgentRunEvent, current_utc_time


def create_session(client):
    response = client.post(
        "/sessions",
        json={
            "title": "Run recovery test",
            "problem_description": "An agent run was interrupted.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def reserve_running_run(session_id, key=None):
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        reservation = AgentRunService(db).reserve(
            session_id,
            "Investigate the failed request.",
            None,
            None,
            key,
        )
        return reservation.run.id
    finally:
        generator.close()


def age_run(run_id):
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(created_at=current_utc_time() - timedelta(minutes=5))
        )
        db.commit()
    finally:
        generator.close()


def saved_events(run_id):
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        return list(db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id)
            .order_by(AgentRunEvent.id)
        ))
    finally:
        generator.close()


def test_detail_interrupts_stale_run_and_writes_one_event(client):
    session_id = create_session(client)
    run_id = reserve_running_run(session_id)
    age_run(run_id)

    response = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "interrupted"
    assert data["error_code"] == "RUN_INTERRUPTED"
    assert data["finished_at"] is not None
    assert data["duration_ms"] is None

    first_events = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}/events"
    )
    second_detail = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}"
    )
    second_events = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}/events"
    )

    assert second_detail.json()["execution_status"] == "interrupted"
    assert [event["event_type"] for event in first_events.json()] == [
        "run_started",
        "run_interrupted",
    ]
    assert second_events.json() == first_events.json()
    assert len(saved_events(run_id)) == 2


def test_event_history_also_interrupts_stale_run(client):
    session_id = create_session(client)
    run_id = reserve_running_run(session_id)
    age_run(run_id)

    events = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}/events"
    )
    detail = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}"
    )

    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "run_interrupted"
    assert events.json()[-1]["error_code"] == "RUN_INTERRUPTED"
    assert detail.json()["execution_status"] == "interrupted"


def test_recent_running_record_remains_running(client):
    session_id = create_session(client)
    run_id = reserve_running_run(session_id)

    response = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}"
    )
    events = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}/events"
    )

    assert response.status_code == 200
    assert response.json()["execution_status"] == "running"
    assert all(
        event["event_type"] != "run_interrupted"
        for event in events.json()
    )


def test_idempotent_replay_of_stale_run_does_not_restart_agent(client):
    fake_agent = SimpleNamespace(
        run=AsyncMock(return_value=AgentResult(
            status="needs_input",
            answer="Missing context.",
        ))
    )
    app.dependency_overrides[get_agent] = lambda: fake_agent
    try:
        session_id = create_session(client)
        run_id = reserve_running_run(session_id, key="expired-run-key")
        age_run(run_id)

        response = client.post(
            f"/sessions/{session_id}/agent-runs",
            json={"question": "Investigate the failed request."},
            headers={"Idempotency-Key": "expired-run-key"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == run_id
        assert response.json()["execution_status"] == "interrupted"
        fake_agent.run.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_agent, None)
