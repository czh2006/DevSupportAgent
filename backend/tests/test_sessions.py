from fastapi.testclient import TestClient
import pytest


def create_session(client: TestClient, title: str) -> dict:
    response = client.post(
        "/sessions",
        json={
            "title": title,
            "problem_description": "调用模型接口后返回错误，需要进一步排查。",
        },
    )

    assert response.status_code == 201
    return response.json()


def test_create_and_get_session(client: TestClient) -> None:
    created_session = create_session(
        client,
        title="调用模型接口返回 429",
    )

    assert created_session["title"] == "调用模型接口返回 429"
    assert created_session["status"] == "created"
    assert created_session["id"]
    assert created_session["created_at"]

    response = client.get(f"/sessions/{created_session['id']}")

    assert response.status_code == 200
    assert response.json() == created_session


def test_rejects_invalid_session_payload(client: TestClient) -> None:
    blank_title_response = client.post(
        "/sessions",
        json={
            "title": "   ",
            "problem_description": "测试空白标题。",
        },
    )

    assert blank_title_response.status_code == 422

    extra_field_response = client.post(
        "/sessions",
        json={
            "title": "测试额外字段",
            "problem_description": "测试接口是否拒绝客户端修改状态。",
            "status": "resolved",
        },
    )

    assert extra_field_response.status_code == 422


def test_messages_are_isolated_by_session(client: TestClient) -> None:
    first_session = create_session(
        client,
        title="第一个排障会话",
    )
    second_session = create_session(
        client,
        title="第二个排障会话",
    )

    first_message_response = client.post(
        f"/sessions/{first_session['id']}/messages",
        json={"content": "调用接口时返回 429。"},
    )
    second_message_response = client.post(
        f"/sessions/{first_session['id']}/messages",
        json={"content": "降低请求频率后，错误仍然存在。"},
    )

    assert first_message_response.status_code == 201
    assert second_message_response.status_code == 201

    first_session_messages_response = client.get(
        f"/sessions/{first_session['id']}/messages",
    )
    second_session_messages_response = client.get(
        f"/sessions/{second_session['id']}/messages",
    )

    assert first_session_messages_response.status_code == 200
    assert second_session_messages_response.status_code == 200

    first_session_messages = first_session_messages_response.json()
    second_session_messages = second_session_messages_response.json()

    assert len(first_session_messages) == 2
    assert first_session_messages[0]["content"] == "调用接口时返回 429。"
    assert first_session_messages[1]["content"] == "降低请求频率后，错误仍然存在。"
    assert all(
        message["session_id"] == first_session["id"]
        for message in first_session_messages
    )

    assert second_session_messages == []


def test_rejects_message_for_missing_session(client: TestClient) -> None:
    response = client.post(
        "/sessions/does-not-exist/messages",
        json={"content": "这条消息不应该被保存。"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "排障会话不存在",
    }

def test_starts_investigation_only_once(client: TestClient) -> None:
    created_session = create_session(
        client,
        title="需要开始排查的会话",
    )

    start_response = client.post(
        f"/sessions/{created_session['id']}/start",
    )

    assert start_response.status_code == 200
    assert start_response.json()["status"] == "investigating"

    duplicate_start_response = client.post(
        f"/sessions/{created_session['id']}/start",
    )

    assert duplicate_start_response.status_code == 409
    assert duplicate_start_response.json() == {
        "detail": "当前会话不能开始排查",
    }


def test_cannot_start_missing_session(client: TestClient) -> None:
    response = client.post("/sessions/does-not-exist/start")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "排障会话不存在",
    }

def test_upserts_context_without_erasing_existing_fields(
    client: TestClient,
) -> None:
    created_session = create_session(
        client,
        title="需要补充上下文的会话",
    )

    first_response = client.put(
        f"/sessions/{created_session['id']}/context",
        json={
            "api_version": "v1",
            "environment": "staging",
            "http_status_code": 429,
        },
    )

    assert first_response.status_code == 200
    assert first_response.json()["api_version"] == "v1"
    assert first_response.json()["environment"] == "staging"
    assert first_response.json()["http_status_code"] == 429
    assert first_response.json()["request_id"] is None

    second_response = client.put(
        f"/sessions/{created_session['id']}/context",
        json={
            "request_id": "req_429_demo_001",
        },
    )

    assert second_response.status_code == 200

    context = second_response.json()
    assert context["api_version"] == "v1"
    assert context["environment"] == "staging"
    assert context["http_status_code"] == 429
    assert context["request_id"] == "req_429_demo_001"


def test_rejects_empty_or_invalid_context(
    client: TestClient,
) -> None:
    created_session = create_session(
        client,
        title="验证上下文字段的会话",
    )

    empty_response = client.put(
        f"/sessions/{created_session['id']}/context",
        json={},
    )

    assert empty_response.status_code == 422

    invalid_status_code_response = client.put(
        f"/sessions/{created_session['id']}/context",
        json={
            "http_status_code": 99,
        },
    )

    assert invalid_status_code_response.status_code == 422


def test_returns_404_when_context_is_missing(
    client: TestClient,
) -> None:
    created_session = create_session(
        client,
        title="尚未填写上下文的会话",
    )

    response = client.get(
        f"/sessions/{created_session['id']}/context",
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "排障上下文尚未填写",
    }

def test_extracts_context_candidate_from_natural_language(
    client: TestClient,
) -> None:
    created_session = create_session(
        client,
        title="从自然语言中提取排障上下文",
    )

    message_response = client.post(
        f"/sessions/{created_session['id']}/messages",
        json={
            "content": (
                "我在生产环境调用 v1 接口，返回 429，"
                "请求 ID 是 req_429_demo_001。"
            ),
        },
    )

    assert message_response.status_code == 201

    message_id = message_response.json()["id"]

    suggestion_response = client.post(
        f"/sessions/{created_session['id']}/messages/"
        f"{message_id}/context-suggestion",
    )

    assert suggestion_response.status_code == 200

    suggestion = suggestion_response.json()
    candidate = suggestion["candidate"]

    assert suggestion["requires_confirmation"] is True
    assert candidate["api_version"] == "v1"
    assert candidate["environment"] == "production"
    assert candidate["request_id"] == "req_429_demo_001"
    assert candidate["http_status_code"] == 429
    assert candidate["missing_fields"] == []

    context_response = client.get(
        f"/sessions/{created_session['id']}/context",
    )

    assert context_response.status_code == 404
    assert candidate["sources"] == {
        "api_version": "rule",
        "environment": "rule",
        "request_id": "rule",
        "http_status_code": "rule",
    }

    assert candidate["confidence"] == {
        "api_version": 1.0,
        "environment": 1.0,
        "request_id": 1.0,
        "http_status_code": 1.0,
    }


def test_returns_missing_fields_for_ambiguous_message(
    client: TestClient,
) -> None:
    created_session = create_session(
        client,
        title="信息不足的自然语言消息",
    )

    message_response = client.post(
        f"/sessions/{created_session['id']}/messages",
        json={
            "content": "接口似乎异常了，麻烦帮我看看。",
        },
    )

    assert message_response.status_code == 201

    message_id = message_response.json()["id"]

    suggestion_response = client.post(
        f"/sessions/{created_session['id']}/messages/"
        f"{message_id}/context-suggestion",
    )

    assert suggestion_response.status_code == 200

    candidate = suggestion_response.json()["candidate"]

    assert candidate["api_version"] is None
    assert candidate["environment"] is None
    assert candidate["request_id"] is None
    assert candidate["http_status_code"] is None
    assert candidate["sources"] == {}
    assert candidate["confidence"] == {}

    assert set(candidate["missing_fields"]) == {
        "api_version",
        "environment",
        "request_id",
        "http_status_code",
    }


def test_cannot_extract_message_from_another_session(
    client: TestClient,
) -> None:
    first_session = create_session(
        client,
        title="第一个会话",
    )
    second_session = create_session(
        client,
        title="第二个会话",
    )

    message_response = client.post(
        f"/sessions/{first_session['id']}/messages",
        json={
            "content": "生产环境返回 429。",
        },
    )

    assert message_response.status_code == 201

    message_id = message_response.json()["id"]

    response = client.post(
        f"/sessions/{second_session['id']}/messages/"
        f"{message_id}/context-suggestion",
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "会话消息不存在",
    }

@pytest.mark.parametrize(
    ("content", "expected_request_id", "expected_status_code"),
    [
        (
            "调用失败，trace 是 req_429_demo_001。",
            "req_429_demo_001",
            None,
        ),
        (
            "接口报错 429，请求编号为 req_rate_limit_002。",
            "req_rate_limit_002",
            429,
        ),
        (
            "HTTP status code: 503，request id=req_gateway_003",
            "req_gateway_003",
            503,
        ),
    ],
)
def test_extracts_stable_identifiers_from_multiple_phrasings(
    client: TestClient,
    content: str,
    expected_request_id: str,
    expected_status_code: int | None,
) -> None:
    created_session = create_session(
        client,
        title="验证多种自然语言表达",
    )

    message_response = client.post(
        f"/sessions/{created_session['id']}/messages",
        json={"content": content},
    )

    message_id = message_response.json()["id"]

    suggestion_response = client.post(
        f"/sessions/{created_session['id']}/messages/"
        f"{message_id}/context-suggestion",
    )

    assert suggestion_response.status_code == 200

    candidate = suggestion_response.json()["candidate"]

    assert candidate["request_id"] == expected_request_id
    assert candidate["http_status_code"] == expected_status_code
    assert candidate["sources"]["request_id"] == "rule"
    assert candidate["confidence"]["request_id"] == 1.0