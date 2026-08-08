"""Adapters for canonical code identity."""

from infinity_context_core.features.code_identity.public import FEATURE_ID

from infinity_context_adapters.features.code_identity.postgres_repository import (
    PostgresCodeRepository,
)
from infinity_context_adapters.features.code_identity.postgres_scope_authorization import (
    PostgresCodeScopeAuthorization,
)
from infinity_context_adapters.features.code_identity.postgres_workspace_binding import (
    PostgresWorkspaceBindingReader,
)

__all__ = (
    "FEATURE_ID",
    "PostgresCodeRepository",
    "PostgresCodeScopeAuthorization",
    "PostgresWorkspaceBindingReader",
)
