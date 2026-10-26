from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.runner import AgentResult
from app.api.agent_runs import get_agent
from app.main import app
from app.services.agent_run_service import AgentRunService
from app.storage.database import Base, get_db
from app.storage.models import (
    AgentRun,
    TroubleshootingSession,
)


REQUEST_ID = "req_" + "1" * 32


@pytest.fixture
def fake_agent(client):
    fake = SimpleNamespace(
        run=AsyncMock(
            return_value=AgentResult(
                status="needs_input",
                answer="请补充上下文。",
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
            "title": "运行记录测试",
            "problem_description": "请求失败",
        },
    )

    assert response.status_code == 201
    return response.json()["id"]


def saved_rows():
    generator = app.dependency_overrides[get_db]()

    try:
        db = next(generator)
        return list(
            db.scalars(select(AgentRun))
        )
    finally:
        generator.close()


def test_run_can_be_queried_after_context_changes(
    client,
    fake_agent,
):
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
        json={"question": "帮我排查"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["execution_status"] == "completed"
    assert data["duration_ms"] >= 0
    assert data["finished_at"] is not None

    updated = client.put(
        f"/sessions/{session_id}/context",
        json={
            "request_id": "req_" + "2" * 32,
        },
    )
    assert updated.status_code == 200

    run_id = data["id"]

    loaded = client.get(
        f"/sessions/{session_id}/agent-runs/{run_id}"
    )

    assert loaded.status_code == 200
    assert loaded.json() == data
    assert loaded.json()["request_id"] == REQUEST_ID

    # 查询历史不应该重新调用 Agent。
    assert fake_agent.run.await_count == 1


def test_two_runs_have_different_ids(
    client,
    fake_agent,
):
    session_id = create_case(client)

    first = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "第一次排查"},
    )

    second = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "第二次排查"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert len(saved_rows()) == 2


def test_wrong_session_cannot_read_run(
    client,
    fake_agent,
):
    first_session = create_case(client)
    second_session = create_case(client)

    response = client.post(
        f"/sessions/{first_session}/agent-runs",
        json={"question": "帮我排查"},
    )
    run_id = response.json()["id"]

    response = client.get(
        f"/sessions/{second_session}/agent-runs/{run_id}"
    )

    assert response.status_code == 404


def test_tool_failure_is_saved_as_completed_result(
    client,
    fake_agent,
):
    session_id = create_case(client)

    fake_agent.run.return_value = AgentResult(
        status="tool_error",
        answer="日志服务不可用。",
        error_code="MCP_UNAVAILABLE",
    )

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "帮我排查"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["execution_status"] == "completed"
    assert data["result"]["status"] == "tool_error"
    assert data["error_code"] == "MCP_UNAVAILABLE"


def test_unexpected_exception_is_saved_and_reraised(
    client,
    fake_agent,
):
    session_id = create_case(client)

    fake_agent.run.side_effect = RuntimeError(
        "private internal detail"
    )

    with pytest.raises(
        RuntimeError,
        match="private internal detail",
    ):
        client.post(
            f"/sessions/{session_id}/agent-runs",
            json={"question": "帮我排查"},
        )

    row, = saved_rows()

    response = client.get(
        f"/sessions/{session_id}/agent-runs/{row.id}"
    )

    assert response.status_code == 200

    data = response.json()
    assert data["execution_status"] == "failed"
    assert data["error_code"] == "INTERNAL_ERROR"
    assert data["result"] is None

    assert "private internal detail" not in response.text


def test_running_record_exists_before_agent_execution(
    client,
    fake_agent,
):
    session_id = create_case(client)

    async def inspect(**kwargs):
        row, = saved_rows()

        assert row.execution_status == "running"
        assert row.result_json is None

        return AgentResult(
            status="needs_input",
            answer="请补充上下文。",
        )

    fake_agent.run.side_effect = inspect

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": "帮我排查"},
    )

    assert response.status_code == 200


def test_invalid_body_does_not_create_run(
    client,
    fake_agent,
):
    session_id = create_case(client)

    response = client.post(
        f"/sessions/{session_id}/agent-runs",
        json={"question": " "},
    )

    assert response.status_code == 422
    assert saved_rows() == []
    fake_agent.run.assert_not_awaited()


def test_records_survive_new_database_engine(tmp_path):
    database_path = tmp_path / "runs.db"
    url = f"sqlite:///{database_path.as_posix()}"

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            TroubleshootingSession(
                id="case-1",
                title="测试",
                problem_description="请求失败",
            )
        )
        db.commit()

        service = AgentRunService(db)

        run_id = service.start(
            "case-1",
            "帮我排查",
            REQUEST_ID,
            "local",
        )

        service.finish(
            run_id,
            12,
            AgentResult(
                status="needs_input",
                answer="请补充上下文。",
            ),
        )

    engine.dispose()

    # 重新创建引擎，不能依赖之前的连接或 ORM 对象。
    new_engine = create_engine(url)

    try:
        with Session(new_engine) as db:
            data = AgentRunService(db).get(
                "case-1",
                run_id,
            )

            assert data.result is not None
            assert data.result.status == "needs_input"
            assert data.duration_ms == 12
    finally:
        new_engine.dispose()