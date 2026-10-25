from typing import Protocol
from app.extraction.evidence_validator import field_matches_evidence
from app.extraction.context_extractor import REQUIRED_CONTEXT_FIELDS
from app.schemas.context_suggestion import (
    ContextCandidate,
    ExtractionSource,
    LlmContextExtraction,
)


class StructuredContextModel(Protocol):
    def invoke(
        self,
        payload: dict[str, str],
    ) -> LlmContextExtraction:
        """调用模型并返回经过结构化解析的结果。"""


class LlmContextExtractor:
    def __init__(
        self,
        model: StructuredContextModel,
    ) -> None:
        self.model = model

    def extract(self, content: str) -> ContextCandidate:
        extraction = self.model.invoke(
            {
                "content": content,
            }
        )

        values = {
            "api_version": extraction.api_version,
            "environment": extraction.environment,
            "request_id": extraction.request_id,
            "http_status_code": extraction.http_status_code,
        }

        accepted_values: dict[str, object | None] = {}
        evidence: dict[str, str] = {}
        sources: dict[str, ExtractionSource] = {}
        confidence: dict[str, float] = {}
        rejected_fields: dict[str, str] = {}

        for field_name, value in values.items():
            if value is None:
                accepted_values[field_name] = None
                continue

            evidence_text = extraction.evidence.get(field_name)

            if evidence_text is None or not evidence_text.strip():
                accepted_values[field_name] = None
                rejected_fields[field_name] = "模型未提供原文依据"
                continue

            if evidence_text not in content:
                accepted_values[field_name] = None
                rejected_fields[field_name] = (
                    "模型提供的原文依据不在用户消息中"
                )
                continue
            
            if not field_matches_evidence(
                field_name,
                value,
                evidence_text,
            ):
                accepted_values[field_name] = None
                rejected_fields[field_name] = (
                    "候选值与原文依据不一致"
                )
                continue

            field_confidence = extraction.confidence.get(
                field_name,
                0.0,
            )

            if not 0.0 <= field_confidence <= 1.0:
                accepted_values[field_name] = None
                rejected_fields[field_name] = "模型置信度不在 0 到 1 范围内"
                continue

            accepted_values[field_name] = value
            evidence[field_name] = evidence_text
            sources[field_name] = ExtractionSource.LLM
            confidence[field_name] = field_confidence

        missing_fields = [
            field_name
            for field_name in REQUIRED_CONTEXT_FIELDS
            if accepted_values[field_name] is None
        ]

        return ContextCandidate(
            api_version=accepted_values["api_version"],
            environment=accepted_values["environment"],
            request_id=accepted_values["request_id"],
            http_status_code=accepted_values["http_status_code"],
            evidence=evidence,
            sources=sources,
            confidence=confidence,
            missing_fields=missing_fields,
            rejected_fields=rejected_fields,
        )