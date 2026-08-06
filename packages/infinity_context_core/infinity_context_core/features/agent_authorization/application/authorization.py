"""Application boundary for locked agent requests."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.agent_authorization.domain import (
    AuthorizedAgentContext,
    AuthorizedAgentRequest,
)


@dataclass(frozen=True, slots=True)
class AuthorizeAgentRequestCommand:
    requested_space_id: str
    requested_memory_scope_ids: tuple[str, ...]
    required_permission: str
    requested_repository_id: str | None = None
    requested_code_scope_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizeAgentRequestHandler:
    context: AuthorizedAgentContext

    async def execute(
        self,
        command: AuthorizeAgentRequestCommand,
    ) -> AuthorizedAgentRequest:
        return self.context.authorize(
            requested_space_id=command.requested_space_id,
            requested_memory_scope_ids=command.requested_memory_scope_ids,
            required_permission=command.required_permission,
            requested_repository_id=command.requested_repository_id,
            requested_code_scope_id=command.requested_code_scope_id,
        )


__all__ = ("AuthorizeAgentRequestCommand", "AuthorizeAgentRequestHandler")
