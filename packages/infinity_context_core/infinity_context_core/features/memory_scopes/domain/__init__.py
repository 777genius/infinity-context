"""Domain model owned by the memory_scopes feature."""

from infinity_context_core.features.memory_scopes.domain.errors import (
    MemoryScopeDomainError,
    MemoryScopeOwnershipError,
)
from infinity_context_core.features.memory_scopes.domain.feature import (
    FEATURE_ID,
    MemoryScopesFeature,
)
from infinity_context_core.features.memory_scopes.domain.policies import (
    MEMORY_SCOPE_ADMIN_CAPABILITY,
    MEMORY_SCOPE_TRANSFER_CAPABILITY,
    MemoryScopeOwnershipDecision,
    MemoryScopeOwnershipPolicy,
)
from infinity_context_core.features.memory_scopes.domain.scope import (
    MEMORY_SCOPE_STATUS_ACTIVE,
    MEMORY_SCOPE_STATUS_ARCHIVED,
    MEMORY_SCOPE_STATUS_DELETED,
    VALID_MEMORY_SCOPE_STATUSES,
    MemoryScopeActor,
    MemoryScopeCapability,
    MemoryScopeIdentity,
    MemoryScopeOwner,
    MemoryScopePrincipalKind,
    MemoryScopeSnapshot,
    MemoryScopeStatus,
)

__all__ = (
    "FEATURE_ID",
    "MEMORY_SCOPE_ADMIN_CAPABILITY",
    "MEMORY_SCOPE_STATUS_ACTIVE",
    "MEMORY_SCOPE_STATUS_ARCHIVED",
    "MEMORY_SCOPE_STATUS_DELETED",
    "MEMORY_SCOPE_TRANSFER_CAPABILITY",
    "MemoryScopeActor",
    "MemoryScopeCapability",
    "MemoryScopeDomainError",
    "MemoryScopeIdentity",
    "MemoryScopeOwner",
    "MemoryScopeOwnershipDecision",
    "MemoryScopeOwnershipError",
    "MemoryScopeOwnershipPolicy",
    "MemoryScopePrincipalKind",
    "MemoryScopeSnapshot",
    "MemoryScopeStatus",
    "MemoryScopesFeature",
    "VALID_MEMORY_SCOPE_STATUSES",
)
