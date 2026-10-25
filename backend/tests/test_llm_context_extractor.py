from app.extraction.llm_context_extractor import LlmContextExtractor
from app.schemas.context import RuntimeEnvironment
from app.schemas.context_suggestion import LlmContextExtraction
import pytest

class FakeStructuredContextModel:
    def __init__(
        self,
        response: LlmContextExtraction,
    ) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def invoke(
        self,
        payload: dict[str, str],
    ) -> LlmContextExtraction:
        self.calls.append(payload)

        return self.response


def test_accepts_llm_fields_with_valid_evidence() -> None:
    content = (
        "线上调用模型接口返回 429，"
        "请求编号为 req_429_demo_001。"
    )

    fake_model = FakeStructuredContextModel(
        response=LlmContextExtraction(
            environment=RuntimeEnvironment.PRODUCTION,
            request_id="req_429_demo_001",
            http_status_code=429,
            evidence={
                "environment": "线上",
                "request_id": "请求编号为 req_429_demo_001",
                "http_status_code": "返回 429",
            },
            confidence={
                "environment": 0.91,
                "request_id": 0.99,
                "http_status_code": 0.98,
            },
        )
    )

    extractor = LlmContextExtractor(fake_model)

    candidate = extractor.extract(content)

    assert fake_model.calls == [{"content": content}]
    assert candidate.environment == RuntimeEnvironment.PRODUCTION
    assert candidate.request_id == "req_429_demo_001"
    assert candidate.http_status_code == 429
    assert candidate.api_version is None

    assert candidate.sources == {
        "environment": "llm",
        "request_id": "llm",
        "http_status_code": "llm",
    }

    assert candidate.rejected_fields == {}
    assert candidate.missing_fields == ["api_version"]


def test_rejects_llm_output_without_message_evidence() -> None:
    content = "模型服务提示请求太频繁。"

    fake_model = FakeStructuredContextModel(
        response=LlmContextExtraction(
            http_status_code=429,
            evidence={
                "http_status_code": "HTTP 429",
            },
            confidence={
                "http_status_code": 0.95,
            },
        )
    )

    extractor = LlmContextExtractor(fake_model)

    candidate = extractor.extract(content)

    assert candidate.http_status_code is None
    assert candidate.sources == {}
    assert candidate.confidence == {}
    assert candidate.rejected_fields == {
        "http_status_code": "模型提供的原文依据不在用户消息中",
    }

    assert set(candidate.missing_fields) == {
        "api_version",
        "environment",
        "request_id",
        "http_status_code",
    }


def test_rejects_llm_value_without_evidence() -> None:
    content = "prod 环境的接口出现异常。"

    fake_model = FakeStructuredContextModel(
        response=LlmContextExtraction(
            environment=RuntimeEnvironment.PRODUCTION,
            confidence={
                "environment": 0.9,
            },
        )
    )

    extractor = LlmContextExtractor(fake_model)

    candidate = extractor.extract(content)

    assert candidate.environment is None
    assert candidate.rejected_fields == {
        "environment": "模型未提供原文依据",
    }

@pytest.mark.parametrize(
    ("field_name", "value", "evidence"),
    [
        (
            "http_status_code",
            429,
            "返回 401",
        ),
        (
            "http_status_code",
            429,
            "调用超时",
        ),
        (
            "request_id",
            "req_001",
            "请求编号为 req_001_extra",
        ),
        (
            "api_version",
            "v2",
            "API v1",
        ),
        (
            "environment",
            RuntimeEnvironment.PRODUCTION,
            "预发环境",
        ),
        (
            "http_status_code",
            429,
            "第一次返回 401，第二次返回 429",
        ),
    ],
)
def test_rejects_value_not_supported_by_real_evidence(
    field_name: str,
    value: object,
    evidence: str,
) -> None:
    content = f"用户描述：{evidence}。"

    response = LlmContextExtraction(
        **{field_name: value},
        evidence={field_name: evidence},
        confidence={field_name: 0.99},
    )

    fake_model = FakeStructuredContextModel(response=response)
    extractor = LlmContextExtractor(fake_model)

    candidate = extractor.extract(content)

    assert getattr(candidate, field_name) is None
    assert candidate.rejected_fields[field_name] == (
        "候选值与原文依据不一致"
    )
    assert field_name in candidate.missing_fields
    assert field_name not in candidate.sources
    assert field_name not in candidate.confidence


@pytest.mark.parametrize("evidence", ["", "   "])
def test_rejects_blank_evidence(evidence: str) -> None:
    fake_model = FakeStructuredContextModel(
        response=LlmContextExtraction(
            http_status_code=429,
            evidence={"http_status_code": evidence},
            confidence={"http_status_code": 0.99},
        )
    )

    extractor = LlmContextExtractor(fake_model)

    candidate = extractor.extract("接口返回 429，   请检查。")

    assert candidate.http_status_code is None
    assert candidate.rejected_fields == {
        "http_status_code": "模型未提供原文依据",
    }