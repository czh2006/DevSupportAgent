from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class RequestLogEvidence(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
    )

    request_id: str = Field(
        pattern=r"^req_[0-9a-f]{32}$"
    )
    project_id: str
    service: str
    environment: str
    method: str
    route: str

    http_status_code: int = Field(ge=100, le=599)
    duration_ms: float = Field(ge=0)

    error_code: str | None
    upstream_status_code: int | None = Field(
        ge=100,
        le=599,
    )
    retry_after_seconds: int | None = Field(ge=0)

    created_at: str
    source: Literal["http_middleware"]


class LogEvidenceResult(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
    )

    status: Literal["found", "not_found"]
    request_id: str = Field(
        pattern=r"^req_[0-9a-f]{32}$"
    )
    record: RequestLogEvidence | None = None

    @model_validator(mode="after")
    def check_record(self) -> Self:
        if (
            self.status == "found"
        ) != (
            self.record is not None
        ):
            raise ValueError(
                "Result status and record do not match."
            )

        return self