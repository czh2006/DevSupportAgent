import pytest

from app.extraction.errors import LlmExtractionError
from app.extraction.hybrid_context_extractor import (
    HybridContextExtractor,
)
from app.schemas.context import RuntimeEnvironment
from app.schemas.context_suggestion import (
    ContextCandidate,
    ExtractionSource,
)


class StubExtractor:
    def __init__(self, result: ContextCandidate) -> None:
        self.result = result

    def extract(self, content: str) -> ContextCandidate:
        return self.result

def test_supplements_missing_rule_fields() -> None:
    rule_result = ContextCandidate(
        request_id="req_demo_001",
        sources={"request_id": ExtractionSource.RULE},
    )

    llm_result = ContextCandidate(
        environment=RuntimeEnvironment.PRODUCTION,
        evidence={"environment": "正式服"},
        sources={"environment": ExtractionSource.LLM},
        unverified_fields=["environment"],
    )

    extractor = HybridContextExtractor(
        StubExtractor(rule_result),
        StubExtractor(llm_result),
    )

    result = extractor.extract(
        "正式服出错，请求号 req_demo_001",
    )

    assert result.request_id == "req_demo_001"
    assert result.environment == RuntimeEnvironment.PRODUCTION
    assert result.evidence["environment"] == "正式服"
    assert result.unverified_fields == ["environment"]

    assert result.sources["request_id"] == ExtractionSource.RULE
    assert result.sources["environment"] == ExtractionSource.LLM

    assert set(result.missing_fields) == {
        "api_version",
        "http_status_code",
    }

    assert rule_result.environment is None

def test_conflicting_values_are_not_silently_selected() -> None:
    extractor = HybridContextExtractor(
        StubExtractor(
            ContextCandidate(
                http_status_code=401,
                evidence={"http_status_code": "返回401"},
                sources={
                    "http_status_code": ExtractionSource.RULE,
                },
                confidence={"http_status_code": 1.0},
            ),
        ),
        StubExtractor(
            ContextCandidate(http_status_code=429),
        ),
    )

    result = extractor.extract("之前返回401，现在返回429")

    assert result.http_status_code is None

    assert result.conflicts["http_status_code"] == {
        "rule": 401,
        "llm": 429,
    }

    assert "http_status_code" in result.missing_fields
    assert "http_status_code" not in result.evidence
    assert "http_status_code" not in result.sources
    assert "http_status_code" not in result.confidence

def test_matching_values_keep_rule_source() -> None:
    extractor = HybridContextExtractor(
        StubExtractor(
            ContextCandidate(
                http_status_code=429,
                sources={
                    "http_status_code": ExtractionSource.RULE,
                },
            ),
        ),
        StubExtractor(
            ContextCandidate(
                http_status_code=429,
                sources={
                    "http_status_code": ExtractionSource.LLM,
                },
            ),
        ),
    )

    result = extractor.extract("返回429")

    assert result.http_status_code == 429
    assert result.conflicts == {}
    assert result.sources["http_status_code"] == (
        ExtractionSource.RULE
    )

def test_known_model_failure_degrades_to_rules() -> None:
    class UnavailableExtractor:
        def extract(self, content: str) -> ContextCandidate:
            raise LlmExtractionError("llm_timeout")

    rule_result = ContextCandidate(http_status_code=429)

    extractor = HybridContextExtractor(
        StubExtractor(rule_result),
        UnavailableExtractor(),
    )

    result = extractor.extract("返回429")

    assert result.http_status_code == 429
    assert result.extraction_warnings == ["llm_timeout"]
    assert rule_result.extraction_warnings == []

def test_programming_error_is_not_hidden_as_fallback() -> None:
    class BrokenExtractor:
        def extract(self, content: str) -> ContextCandidate:
            raise AttributeError("implementation bug")

    extractor = HybridContextExtractor(
        StubExtractor(ContextCandidate()),
        BrokenExtractor(),
    )

    with pytest.raises(
        AttributeError,
        match="implementation bug",
    ):
        extractor.extract("接口异常")