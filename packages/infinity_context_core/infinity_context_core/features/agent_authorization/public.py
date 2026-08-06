"""Public feature boundary for agent authorization."""

from infinity_context_core.features.agent_authorization.application import (
    AuthorizeAgentRequestCommand,
    AuthorizeAgentRequestHandler,
)
from infinity_context_core.features.agent_authorization.domain import (
    FEATURE_ID,
    WORKSPACE_SCOPE_CLAIM_VERSION,
    AgentAccessPolicy,
    AgentAuthorizationFeature,
    AgentScopeResolutionEvidence,
    AgentScopeResolutionMethod,
    AuthorizedAgentContext,
    AuthorizedAgentRequest,
    WorkspaceScopeClaim,
    decode_workspace_scope_claim,
    encode_workspace_scope_claim,
)
from infinity_context_core.features.agent_authorization.ports import (
    AuthorizedAgentContextResolverPort,
)

__all__ = (
    "FEATURE_ID",
    "WORKSPACE_SCOPE_CLAIM_VERSION",
    "AgentAccessPolicy",
    "AgentAuthorizationFeature",
    "AgentScopeResolutionEvidence",
    "AgentScopeResolutionMethod",
    "AuthorizeAgentRequestCommand",
    "AuthorizeAgentRequestHandler",
    "AuthorizedAgentContext",
    "AuthorizedAgentContextResolverPort",
    "AuthorizedAgentRequest",
    "WorkspaceScopeClaim",
    "decode_workspace_scope_claim",
    "encode_workspace_scope_claim",
)
