from app.extraction.context_extractor import (
    REQUIRED_CONTEXT_FIELDS,
    ContextExtractor,
)
from app.extraction.errors import LlmExtractionError
from app.schemas.context_suggestion import ContextCandidate


class HybridContextExtractor:
    def __init__(
        self,
        rule_extractor: ContextExtractor,
        llm_extractor: ContextExtractor,
    ) -> None:
        self.rule_extractor = rule_extractor
        self.llm_extractor = llm_extractor

    def extract(self, content: str) -> ContextCandidate:
        rule_candidate = self.rule_extractor.extract(content)

        merged = rule_candidate.model_copy(deep=True)

        try:
            llm_candidate = self.llm_extractor.extract(content)
        except LlmExtractionError as exc:
            merged.extraction_warnings.append(exc.code)
            return merged

        merged.extraction_warnings.extend(
            llm_candidate.extraction_warnings,
        )

        for field_name in REQUIRED_CONTEXT_FIELDS:
            rule_value = getattr(rule_candidate, field_name)
            llm_value = getattr(llm_candidate, field_name)

            if rule_value is not None and llm_value is not None:
                if rule_value != llm_value:
                    merged.conflicts[field_name] = {
                        "rule": rule_value,
                        "llm": llm_value,
                    }

                    setattr(merged, field_name, None)

                    merged.evidence.pop(field_name, None)
                    merged.sources.pop(field_name, None)
                    merged.confidence.pop(field_name, None)

                    merged.rejected_fields[field_name] = (
                        "规则与模型不一致，需用户确认"
                    )

                continue

            if rule_value is not None:
                continue

            if llm_value is None:
                reason = llm_candidate.rejected_fields.get(
                    field_name,
                )

                if reason is not None:
                    merged.rejected_fields[field_name] = reason

                continue

            setattr(merged, field_name, llm_value)
            merged.rejected_fields.pop(field_name, None)

            for metadata_name in (
                "evidence",
                "sources",
                "confidence",
            ):
                source = getattr(llm_candidate, metadata_name)
                target = getattr(merged, metadata_name)

                if field_name in source:
                    target[field_name] = source[field_name]

            if field_name in llm_candidate.unverified_fields:
                merged.unverified_fields.append(field_name)

        merged.missing_fields = [
            field_name
            for field_name in REQUIRED_CONTEXT_FIELDS
            if getattr(merged, field_name) is None
        ]

        return merged