"""Feature metadata for agent_authorization."""

from dataclasses import dataclass

FEATURE_ID = "agent_authorization"


@dataclass(frozen=True, slots=True)
class AgentAuthorizationFeature:
    feature_id: str = FEATURE_ID


__all__ = ("FEATURE_ID", "AgentAuthorizationFeature")
