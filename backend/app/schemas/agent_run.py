from pydantic import BaseModel, ConfigDict, Field


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    question: str = Field(
        min_length=1,
        max_length=4000,
    )