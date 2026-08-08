"""Resolution port for trusted server or integration adapters."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.agent_authorization.domain import (
    AuthorizedAgentContext,
)


class AuthorizedAgentContextResolverPort(Protocol):
    async def resolve(self, actor_credential: str) -> AuthorizedAgentContext:
        """Resolve an already authenticated actor into canonical locked scope."""


__all__ = ("AuthorizedAgentContextResolverPort",)
