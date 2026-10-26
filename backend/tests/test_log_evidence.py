import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest

from app.integrations.mcp_logs import (
    LogToolError,
    McpLogClient,
    get_mcp_log_client,
)
from app.main import app
from app.schemas.log_evidence import LogEvidenceResult


REQUEST_ID = "req_" + "1" * 32


def evidence_data():
    return {
        "status": "found",
        "request_id": REQUEST_ID,
        "record": {
            "request_id": REQUEST_ID,
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


@pytest.fixture
def adapter():
    instance = McpLogClient(
        "http://unused.test/mcp",
        "demo-project",
        1,
    )

    instance._call = AsyncMock(
        return_value=SimpleNamespace(
            is_error=False,
            structured_content=evidence_data(),
        )
    )

    return instance

def test_client_accepts_matching_evidence(adapter):
    result = asyncio.run(
        adapter.get_request_log(REQUEST_ID)
    )

    assert result.status == "found"
    assert result.record is not None
    assert result.record.http_status_code == 503

    adapter._call.assert_awaited_once_with(REQUEST_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "req_" + "2" * 32),
        ("project_id", "another-project"),
        ("environment", "production"),
        ("http_status_code", "503"),
    ],
)
def test_client_rejects_invalid_record(
    adapter,
    field,
    value,
):
    data = evidence_data()
    data["record"][field] = value

    adapter._call.return_value.structured_content = data

    with pytest.raises(
        LogToolError,
        match="MCP_INVALID_RESPONSE",
    ):
        asyncio.run(
            adapter.get_request_log(REQUEST_ID)
        )


def test_client_rejects_found_without_record(adapter):
    data = evidence_data()
    data["record"] = None

    adapter._call.return_value.structured_content = data

    with pytest.raises(
        LogToolError,
        match="MCP_INVALID_RESPONSE",
    ):
        asyncio.run(
            adapter.get_request_log(REQUEST_ID)
        )


def test_client_rejects_tool_error(adapter):
    adapter._call.return_value.is_error = True

    with pytest.raises(
        LogToolError,
        match="MCP_TOOL_ERROR",
    ):
        asyncio.run(
            adapter.get_request_log(REQUEST_ID)
        )

@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            TimeoutError(),
            "MCP_TIMEOUT",
        ),
        (
            httpx2.ConnectError("offline"),
            "MCP_UNAVAILABLE",
        ),
        (
            ExceptionGroup(
                "network",
                [httpx2.ConnectError("offline")],
            ),
            "MCP_UNAVAILABLE",
        ),
        (
            ExceptionGroup(
                "timeout",
                [TimeoutError()],
            ),
            "MCP_TIMEOUT",
        ),
    ],
)
def test_client_normalizes_expected_errors(
    adapter,
    error,
    code,
):
    adapter._call.side_effect = error

    with pytest.raises(LogToolError, match=code):
        asyncio.run(
            adapter.get_request_log(REQUEST_ID)
        )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("programming bug"),
        ExceptionGroup(
            "mixed",
            [
                httpx2.ConnectError("offline"),
                RuntimeError("programming bug"),
            ],
        ),
    ],
)
def test_client_preserves_programming_errors(
    adapter,
    error,
):
    adapter._call.side_effect = error

    with pytest.raises(type(error)) as caught:
        asyncio.run(
            adapter.get_request_log(REQUEST_ID)
        )

    assert caught.value is error

@pytest.fixture
def fake_logs(client):
    fake = SimpleNamespace(
        get_request_log=AsyncMock(
            return_value=LogEvidenceResult.model_validate(
                evidence_data()
            )
        )
    )

    app.dependency_overrides[
        get_mcp_log_client
    ] = lambda: fake

    try:
        yield fake
    finally:
        app.dependency_overrides.pop(
            get_mcp_log_client,
            None,
        )


def create_case(client, context=None):
    response = client.post(
        "/sessions",
        json={
            "title": "查询日志证据",
            "problem_description": "本地网关调用失败",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["id"]

    if context is not None:
        response = client.put(
            f"/sessions/{session_id}/context",
            json=context,
        )

        assert response.status_code == 200

    return (
        f"/sessions/{session_id}"
        "/evidence/request-log"
    )


def confirmed_context():
    return {
        "environment": "local",
        "request_id": REQUEST_ID,
    }

@pytest.mark.parametrize(
    ("context", "status_code"),
    [
        (None, 409),
        (
            {"environment": "local"},
            409,
        ),
        (
            {
                "environment": "production",
                "request_id": REQUEST_ID,
            },
            409,
        ),
        (
            {
                "environment": "local",
                "request_id": "bad-id",
            },
            422,
        ),
    ],
)
def test_api_blocks_invalid_context(
    client,
    fake_logs,
    context,
    status_code,
):
    url = create_case(client, context)

    assert client.get(url).status_code == status_code
    fake_logs.get_request_log.assert_not_awaited()


def test_api_rejects_unknown_session(
    client,
    fake_logs,
):
    response = client.get(
        "/sessions/missing/evidence/request-log"
    )

    assert response.status_code == 404
    fake_logs.get_request_log.assert_not_awaited()

def test_api_uses_saved_request_id(
    client,
    fake_logs,
):
    url = create_case(
        client,
        confirmed_context(),
    )

    response = client.get(
        url,
        params={"request_id": "another-id"},
    )

    assert response.status_code == 200
    assert (
        response.json()["record"]["http_status_code"]
        == 503
    )

    fake_logs.get_request_log.assert_awaited_once_with(
        REQUEST_ID
    )


def test_api_returns_not_found_without_failure(
    client,
    fake_logs,
):
    fake_logs.get_request_log.return_value = (
        LogEvidenceResult(
            status="not_found",
            request_id=REQUEST_ID,
        )
    )

    url = create_case(
        client,
        confirmed_context(),
    )
    response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_found",
        "request_id": REQUEST_ID,
        "record": None,
    }


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("MCP_TIMEOUT", 504),
        ("MCP_UNAVAILABLE", 503),
        ("MCP_TOOL_ERROR", 502),
        ("MCP_INVALID_RESPONSE", 502),
    ],
)
def test_api_maps_tool_failures(
    client,
    fake_logs,
    code,
    status_code,
):
    fake_logs.get_request_log.side_effect = (
        LogToolError(code)
    )

    url = create_case(
        client,
        confirmed_context(),
    )
    response = client.get(url)

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code