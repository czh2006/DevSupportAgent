from functools import lru_cache

from app.core.config import settings
from app.extraction.context_extractor import (
    ContextExtractor,
    RuleContextExtractor,
)


@lru_cache(maxsize=1)
def get_context_extractor() -> ContextExtractor:
    rule_extractor = RuleContextExtractor()

    if not settings.llm_enabled:
        return rule_extractor

    from app.extraction.hybrid_context_extractor import (
        HybridContextExtractor,
    )
    from app.extraction.llm_context_extractor import (
        LlmContextExtractor,
    )
    from app.integrations.llm import create_llm_context_model

    return HybridContextExtractor(
        rule_extractor=rule_extractor,
        llm_extractor=LlmContextExtractor(
            create_llm_context_model(),
        ),
    )