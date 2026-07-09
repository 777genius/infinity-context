"""Shared application-service context for MCP memory tools."""

from __future__ import annotations

from infinity_context_mcp.application.policy import MemoryPolicyService
from infinity_context_mcp.application.ports import MemoryGatewayPort
from infinity_context_mcp.application.service_policy import MemoryToolPolicyMixin
from infinity_context_mcp.application.service_resources import MemoryToolResourceMixin
from infinity_context_mcp.application.service_response import MemoryToolResponseMixin
from infinity_context_mcp.application.service_scope import MemoryToolScopeMixin
from infinity_context_mcp.config import MemoryMcpSettings


class MemoryToolApplicationServiceBase(
    MemoryToolResourceMixin,
    MemoryToolScopeMixin,
    MemoryToolPolicyMixin,
    MemoryToolResponseMixin,
):
    def __init__(
        self,
        *,
        gateway: MemoryGatewayPort,
        settings: MemoryMcpSettings,
        policy: MemoryPolicyService | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings
        self._policy = policy or MemoryPolicyService()
