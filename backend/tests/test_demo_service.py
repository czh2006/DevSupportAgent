import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from demo_service.config import DemoSettings
from demo_service.limiter import FixedWindowLimiter
from demo_service.main import create_app
import logging

from sqlalchemy.exc import OperationalError

@pytest.fixture
def demo(tmp_path):
    config = DemoSettings(
        _env_file=None,
        database_path=tmp_path / "requests.db",
        api_key=SecretStr("test-key"),
        project_id="test-project",
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
        upstream_url="http://upstream.test/v1/answer",
        upstream_timeout_seconds=1,
    )

    def handler(request):
        assert request.headers["X-Request-ID"].startswith(
            "req_",
        )

        return httpx.Response(
            200,
            json={"reply": "hello"},
        )

    app = create_app(
        config,
        httpx.MockTransport(handler),
    )

    with TestClient(app) as client:
        yield client


def send(
    client,
    key="test-key",
    message="hello",
):
    return client.post(
        "/v1/chat",
        json={"message": message},
        headers={"X-API-Key": key},
    )


def evidence(client, response):
    return client.app.state.log_store.get(
        "test-project",
        response.headers["X-Request-ID"],
    )

def test_success_is_recorded_without_secrets(demo):
    response = send(
        demo,
        message="private-message",
    )

    assert response.status_code == 200

    log = evidence(demo, response)

    assert log["http_status_code"] == 200
    assert log["upstream_status_code"] == 200
    assert log["source"] == "http_middleware"
    assert log["route"] == "/v1/chat"
    assert log["duration_ms"] >= 0

    assert "test-key" not in str(log)
    assert "private-message" not in str(log)

    assert demo.app.state.log_store.get(
        "another-project",
        response.headers["X-Request-ID"],
    ) is None


def test_invalid_key_does_not_consume_quota(demo):
    response = send(demo, key="wrong-key")

    assert response.status_code == 401
    assert evidence(demo, response)["error_code"] == (
        "INVALID_API_KEY"
    )

    assert send(demo).status_code == 200
    assert send(demo).status_code == 200


def test_actual_request_count_triggers_rate_limit(demo):
    assert send(demo).status_code == 200
    assert send(demo).status_code == 200

    response = send(demo)

    assert response.status_code == 429

    log = evidence(demo, response)

    assert log["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) == (
        log["retry_after_seconds"]
    )
    assert log["upstream_status_code"] is None

@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [
        ("connect", 503, "UPSTREAM_UNREACHABLE"),
        ("connect_timeout", 503, "UPSTREAM_CONNECT_TIMEOUT"),
        ("timeout", 504, "UPSTREAM_TIMEOUT"),
        ("server_error", 503, "UPSTREAM_ERROR"),
        ("invalid_body", 502, "UPSTREAM_INVALID_RESPONSE"),
        ("rejected", 502, "UPSTREAM_REJECTED"),
    ],
)
def test_upstream_failure_is_recorded(
    demo,
    monkeypatch,
    mode,
    status,
    code,
):
    async def fail(*args, **kwargs):
        if mode == "connect":
            raise httpx.ConnectError("cannot connect")

        if mode == "connect_timeout":
            raise httpx.ConnectTimeout("connection timed out")

        if mode == "timeout":
            raise httpx.ReadTimeout("timeout")

        if mode == "server_error":
            return httpx.Response(500)

        if mode == "rejected":
            return httpx.Response(401)

        return httpx.Response(
            200,
            json={"wrong": "shape"},
        )

    monkeypatch.setattr(
        demo.app.state.upstream,
        "post",
        fail,
    )

    response = send(demo)

    assert response.status_code == status
    assert evidence(demo, response)["error_code"] == code


def test_validation_error_is_recorded(demo):
    response = demo.post(
        "/v1/chat",
        json={"message": ""},
    )

    assert response.status_code == 422
    assert evidence(demo, response)["error_code"] == "HTTP_422"


def test_limiter_window_resets_without_sleep():
    clock = [0.0]

    limiter = FixedWindowLimiter(
        1,
        30,
        clock=lambda: clock[0],
    )

    assert limiter.acquire() is None
    assert limiter.acquire() == 30

    clock[0] = 30.0

    assert limiter.acquire() is None

def test_log_database_failure_is_visible(
    demo,
    monkeypatch,
    caplog,
):
    def fail(record):
        raise OperationalError(
            "insert",
            {},
            Exception("database unavailable"),
        )

    monkeypatch.setattr(
        demo.app.state.log_store,
        "write",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        response = send(demo)

    assert response.status_code == 200
    assert "request_log_write_failed" in caplog.text


def test_unexpected_error_returns_500(
    demo,
    monkeypatch,
    caplog,
):
    async def fail(*args, **kwargs):
        raise AttributeError("programming error")

    monkeypatch.setattr(
        demo.app.state.upstream,
        "post",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        response = send(demo)

    assert response.status_code == 500
    assert evidence(demo, response)["error_code"] == (
        "INTERNAL_ERROR"
    )
    assert "unhandled_request_error" in caplog.text