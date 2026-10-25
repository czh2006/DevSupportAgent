from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.context import RuntimeEnvironment


class ExtractionSource(str, Enum):
    RULE = "rule"
    LLM = "llm"


class ContextCandidate(BaseModel):
    api_version: str | None = None
    environment: RuntimeEnvironment | None = None
    request_id: str | None = None
    http_status_code: int | None = None

    evidence: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, ExtractionSource] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    rejected_fields: dict[str, str] = Field(default_factory=dict)

class LlmContextExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str | None = None
    environment: RuntimeEnvironment | None = None
    request_id: str | None = None
    http_status_code: int | None = Field(
        default=None,
        ge=100,
        le=599,
    )

    evidence: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)


class ContextSuggestionResponse(BaseModel):
    session_id: str
    message_id: int
    candidate: ContextCandidate
    requires_confirmation: bool = True