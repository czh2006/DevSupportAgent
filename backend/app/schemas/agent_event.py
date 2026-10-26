from pydantic import ConfigDict

from app.agent.events import AgentEvent


class AgentEventResponse(AgentEvent):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str