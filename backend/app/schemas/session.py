from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

class SessionStatus(str, Enum):
    CREATED = "created"
    INVESTIGATING = "investigating"
    AWAITING_USER = "awaiting_user"
    RESOLVED = "resolved"
    HANDED_OFF = "handed_off"

class SessionCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    title: str = Field(min_length=1, max_length=200)
    problem_description: str = Field(min_length=1, max_length=10000)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    problem_description: str
    status: SessionStatus
    created_at: datetime 