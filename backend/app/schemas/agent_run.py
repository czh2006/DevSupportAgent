from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.runner import AgentResult


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    question: str = Field(
        min_length=1,
        max_length=4000,
    )


class AgentRunResponse(BaseModel):
    id: str
    session_id: str

    execution_status: Literal[
        "running",
        "completed",
        "failed",
        "interrupted",
        "cancel_requested",
        "cancelled",
    ]

    question: str
    request_id: str | None
    environment: str | None

    result: AgentResult | None
    error_code: str | None
    duration_ms: int | None

    created_at: datetime
    finished_at: datetime | None
