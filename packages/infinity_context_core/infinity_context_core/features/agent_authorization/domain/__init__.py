"""Domain exports for agent_authorization."""

from infinity_context_core.features.agent_authorization.domain.context import (
    AgentAccessPolicy,
    AgentScopeResolutionEvidence,
    AgentScopeResolutionMethod,
    AuthorizedAgentContext,
    AuthorizedAgentRequest,
)
from infinity_context_core.features.agent_authorization.domain.feature import (
    FEATURE_ID,
    AgentAuthorizationFeature,
)
from infinity_context_core.features.agent_authorization.domain.workspace_claim import (
    WORKSPACE_SCOPE_CLAIM_VERSION,
    WorkspaceScopeClaim,
    decode_workspace_scope_claim,
    encode_workspace_scope_claim,
)

__all__ = (
    "FEATURE_ID",
    "WORKSPACE_SCOPE_CLAIM_VERSION",
    "AgentAccessPolicy",
    "AgentAuthorizationFeature",
    "AgentScopeResolutionEvidence",
    "AgentScopeResolutionMethod",
    "AuthorizedAgentContext",
    "AuthorizedAgentRequest",
    "WorkspaceScopeClaim",
    "decode_workspace_scope_claim",
    "encode_workspace_scope_claim",
)
