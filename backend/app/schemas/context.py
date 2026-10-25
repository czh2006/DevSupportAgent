from datetime import datetime
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeEnvironment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class TroubleshootingContextUpsert(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    api_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    environment: RuntimeEnvironment | None = None
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    http_status_code: int | None = Field(
        default=None,
        ge=100,
        le=599,
    )

    @model_validator(mode="after")
    def require_at_least_one_value(self) -> Self:
        values = (
            self.api_version,
            self.environment,
            self.request_id,
            self.http_status_code,
        )

        if all(value is None for value in values):
            raise ValueError("至少需要提供一个排障上下文字段")

        return self


class TroubleshootingContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    api_version: str | None
    environment: RuntimeEnvironment | None
    request_id: str | None
    http_status_code: int | None
    updated_at: datetime