import asyncio

import pytest
from mcp import Client
from sqlalchemy.exc import OperationalError

from demo_service.config import DemoSettings
from demo_service.storage import LogStore
from devsupport_mcp.server import create_server


OWN_ID = "req_" + "1" * 32
OTHER_ID = "req_" + "2" * 32
MISSING_ID = "req_" + "3" * 32


@pytest.fixture
def log_config(tmp_path):
    config = DemoSettings(
        _env_file=None,
        database_path=tmp_path / "requests.db",
        project_id="test-project",
    )
    store = LogStore(config.database_path)

    try:
        for request_id, project_id in [
            (OWN_ID, "test-project"),
            (OTHER_ID, "another-project"),
        ]:
            store.write({
                "request_id": request_id,
                "project_id": project_id,
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
            })
    finally:
        store.close()

    return config

def query_tool(config, request_id):
    async def run():
        async with asyncio.timeout(5):
            async with Client(create_server(config)) as client:
                return await client.call_tool(
                    "get_request_log",
                    {"request_id": request_id},
                )

    return asyncio.run(run())

def test_tool_exposes_only_request_id(log_config):
    async def run():
        async with asyncio.timeout(5):
            async with Client(create_server(log_config)) as client:
                return await client.list_tools()

    result = asyncio.run(run())

    assert [tool.name for tool in result.tools] == [
        "get_request_log"
    ]

    schema = result.tools[0].input_schema

    assert set(schema["properties"]) == {"request_id"}
    assert schema["required"] == ["request_id"]


def test_query_returns_matching_evidence(log_config):
    result = query_tool(log_config, OWN_ID)

    assert result.is_error is False

    data = result.structured_content
    assert data is not None
    assert data["status"] == "found"
    assert data["request_id"] == OWN_ID

    record = data["record"]
    assert record["request_id"] == OWN_ID
    assert record["project_id"] == "test-project"
    assert record["http_status_code"] == 503
    assert record["error_code"] == "UPSTREAM_UNREACHABLE"

@pytest.mark.parametrize(
    "request_id",
    [MISSING_ID, OTHER_ID],
)
def test_missing_or_foreign_record_is_not_returned(
    log_config,
    request_id,
):
    result = query_tool(log_config, request_id)

    assert result.is_error is False
    assert result.structured_content == {
        "status": "not_found",
        "request_id": request_id,
        "record": None,
    }

@pytest.mark.parametrize(
    "request_id",
    [
        "bad-id",
        "req_" + "a" * 31,
        "req_" + "a" * 33,
    ],
)
def test_invalid_id_is_rejected_before_query(
    log_config,
    monkeypatch,
    request_id,
):
    calls = []

    def forbidden_query(*args, **kwargs):
        calls.append(True)
        raise AssertionError(
            "Invalid IDs must not reach the database."
        )

    monkeypatch.setattr(
        LogStore,
        "get",
        forbidden_query,
    )

    result = query_tool(log_config, request_id)

    assert result.is_error is True
    assert calls == []

def test_missing_database_is_error_and_is_not_created(
    tmp_path,
):
    path = tmp_path / "does-not-exist.db"

    config = DemoSettings(
        _env_file=None,
        database_path=path,
        project_id="test-project",
    )

    result = query_tool(config, OWN_ID)

    assert result.is_error is True

    text = "\n".join(
        block.text
        for block in result.content
        if block.type == "text"
    )

    assert "LOG_QUERY_FAILED" in text
    assert not path.exists()


def test_read_only_store_rejects_writes(log_config):
    store = LogStore(
        log_config.database_path,
        read_only=True,
    )

    try:
        with pytest.raises(PermissionError):
            store.write({})

        with pytest.raises(
            OperationalError,
            match="readonly",
        ):
            with store.engine.begin() as connection:
                connection.exec_driver_sql(
                    "DELETE FROM service_request_logs"
                )

        assert store.get("test-project", OWN_ID) is not None
    finally:
        store.close()