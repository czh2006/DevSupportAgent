from fastapi.testclient import TestClient


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