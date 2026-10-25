import re
from typing import Protocol

from app.schemas.context import RuntimeEnvironment
from app.schemas.context_suggestion import (
    ContextCandidate,
    ExtractionSource,
)


REQUEST_ID_PATTERN = re.compile(
    r"(?i)(?:请求\s*(?:id|编号)|request\s*(?:id|identifier)|"
    r"req(?:uest)?\s*id)\s*(?:是|为|:|：|=)?\s*"
    r"([A-Za-z0-9][A-Za-z0-9_-]{2,127})"
)

REQUEST_ID_FALLBACK_PATTERN = re.compile(
    r"(?i)(?<![\w-])(req_[A-Za-z0-9_-]{3,127})(?![\w-])"
)

HTTP_STATUS_PATTERN = re.compile(
    r"(?i)(?:http\s*(?:状态码|status(?:\s*code)?)|状态码|"
    r"返回|报错|错误)\s*(?:是|为|:|：|=)?\s*"
    r"([1-5]\d{2})(?!\d)"
)

API_VERSION_PATTERN = re.compile(
    r"(?i)(?:api\s*)?(v\d+(?:\.\d+)?)(?![\w.])"
)

ENVIRONMENT_KEYWORDS: tuple[
    tuple[RuntimeEnvironment, tuple[str, ...]],
    ...,
] = (
    (
        RuntimeEnvironment.PRODUCTION,
        ("生产环境", "production"),
    ),
    (
        RuntimeEnvironment.STAGING,
        ("预发环境", "预发布环境", "staging"),
    ),
    (
        RuntimeEnvironment.LOCAL,
        ("本地环境", "本地", "local"),
    ),
)

REQUIRED_CONTEXT_FIELDS = (
    "api_version",
    "environment",
    "request_id",
    "http_status_code",
)


class ContextExtractor(Protocol):
    def extract(self, content: str) -> ContextCandidate:
        """从用户自然语言中提取排障上下文候选项。"""


class RuleContextExtractor:
    def extract(self, content: str) -> ContextCandidate:
        evidence: dict[str, str] = {}
        sources: dict[str, ExtractionSource] = {}
        confidence: dict[str, float] = {}

        request_id, request_id_evidence = self._extract_request_id(content)
        self._add_metadata(
            field_name="request_id",
            evidence_text=request_id_evidence,
            evidence=evidence,
            sources=sources,
            confidence=confidence,
        )

        http_status_code, http_status_evidence = (
            self._extract_http_status_code(content)
        )
        self._add_metadata(
            field_name="http_status_code",
            evidence_text=http_status_evidence,
            evidence=evidence,
            sources=sources,
            confidence=confidence,
        )

        api_version, api_version_evidence = self._extract_api_version(content)
        self._add_metadata(
            field_name="api_version",
            evidence_text=api_version_evidence,
            evidence=evidence,
            sources=sources,
            confidence=confidence,
        )

        environment, environment_evidence = self._extract_environment(
            content,
        )
        self._add_metadata(
            field_name="environment",
            evidence_text=environment_evidence,
            evidence=evidence,
            sources=sources,
            confidence=confidence,
        )

        values = {
            "api_version": api_version,
            "environment": environment,
            "request_id": request_id,
            "http_status_code": http_status_code,
        }

        missing_fields = [
            field_name
            for field_name in REQUIRED_CONTEXT_FIELDS
            if values[field_name] is None
        ]

        return ContextCandidate(
            api_version=api_version,
            environment=environment,
            request_id=request_id,
            http_status_code=http_status_code,
            evidence=evidence,
            sources=sources,
            confidence=confidence,
            missing_fields=missing_fields,
        )

    @staticmethod
    def _add_metadata(
        field_name: str,
        evidence_text: str | None,
        evidence: dict[str, str],
        sources: dict[str, ExtractionSource],
        confidence: dict[str, float],
    ) -> None:
        if evidence_text is None:
            return

        evidence[field_name] = evidence_text
        sources[field_name] = ExtractionSource.RULE
        confidence[field_name] = 1.0

    @staticmethod
    def _extract_request_id(
        content: str,
    ) -> tuple[str | None, str | None]:
        match = REQUEST_ID_PATTERN.search(content)

        if match is None:
            match = REQUEST_ID_FALLBACK_PATTERN.search(content)

        if match is None:
            return None, None

        return match.group(1), match.group(0)

    @staticmethod
    def _extract_http_status_code(
        content: str,
    ) -> tuple[int | None, str | None]:
        match = HTTP_STATUS_PATTERN.search(content)

        if match is None:
            return None, None

        return int(match.group(1)), match.group(0)

    @staticmethod
    def _extract_api_version(
        content: str,
    ) -> tuple[str | None, str | None]:
        match = API_VERSION_PATTERN.search(content)

        if match is None:
            return None, None

        return match.group(1).lower(), match.group(0)

    @staticmethod
    def _extract_environment(
        content: str,
    ) -> tuple[RuntimeEnvironment | None, str | None]:
        normalized_content = content.lower()

        for environment, keywords in ENVIRONMENT_KEYWORDS:
            for keyword in keywords:
                if keyword in normalized_content:
                    return environment, keyword

        return None, None


rule_context_extractor: ContextExtractor = RuleContextExtractor()


def extract_context_candidate(content: str) -> ContextCandidate:
    return rule_context_extractor.extract(content)