"""Domain exports for code_identity."""

from infinity_context_core.features.code_identity.domain.authorization import (
    CodeScopeAuthorization,
    CodeScopeAuthorizationStatus,
)
from infinity_context_core.features.code_identity.domain.feature import (
    FEATURE_ID,
    CodeIdentityFeature,
)
from infinity_context_core.features.code_identity.domain.repository import (
    CodeRepository,
    CodeRepositoryProvider,
    CodeRepositoryStatus,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
)
from infinity_context_core.features.code_identity.domain.scope import (
    CodeScope,
    CodeScopeDescriptor,
    CodeScopeEnvironment,
    CodeScopeLevel,
    CodeWorktreeState,
)

__all__ = (
    "FEATURE_ID",
    "CodeIdentityFeature",
    "CodeRepository",
    "CodeRepositoryProvider",
    "CodeRepositoryStatus",
    "CodeScope",
    "CodeScopeDescriptor",
    "CodeScopeAuthorization",
    "CodeScopeAuthorizationStatus",
    "CodeScopeEnvironment",
    "CodeScopeLevel",
    "CodeWorktreeState",
    "RepositoryEvidenceKind",
    "RepositoryIdentityEvidence",
)
