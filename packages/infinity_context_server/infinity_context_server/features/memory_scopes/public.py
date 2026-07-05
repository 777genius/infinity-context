"""Public server seam for the memory_scopes feature mirror."""

from __future__ import annotations

import infinity_context_core.features.memory_scopes.public as memory_scopes

from infinity_context_server.features.memory_scopes.composition import (
    MemoryScopesServerFeature,
    build_memory_scopes_server_feature,
)
from infinity_context_server.features.memory_scopes.contracts import (
    ArchiveMemoryScopeHttpRequest,
    CreateMemoryScopeHttpRequest,
    MemoryScopeActorHttpRequest,
    MemoryScopeLifecycleHttpRequest,
    MemoryScopeOwnerHttpRequest,
    RestoreMemoryScopeHttpRequest,
    TransferMemoryScopeOwnershipHttpRequest,
)
from infinity_context_server.features.memory_scopes.mappers import (
    archive_memory_scope_command_from_http,
    archive_memory_scope_result_to_response,
    create_memory_scope_command_from_contract,
    create_memory_scope_contract_from_http_request,
    create_memory_scope_result_to_contract,
    memory_scope_actor_from_http,
    memory_scope_owner_from_http,
    memory_scope_snapshot_to_contract,
    memory_scope_to_response,
    restore_memory_scope_command_from_http,
    restore_memory_scope_result_to_response,
    transfer_memory_scope_ownership_command_from_http,
    transfer_memory_scope_ownership_result_to_response,
)
from infinity_context_server.features.memory_scopes.routes import (
    create_memory_scopes_router,
)

FEATURE_ID = memory_scopes.FEATURE_ID

__all__ = (
    "ArchiveMemoryScopeHttpRequest",
    "CreateMemoryScopeHttpRequest",
    "MemoryScopeActorHttpRequest",
    "MemoryScopeLifecycleHttpRequest",
    "MemoryScopeOwnerHttpRequest",
    "MemoryScopesServerFeature",
    "RestoreMemoryScopeHttpRequest",
    "TransferMemoryScopeOwnershipHttpRequest",
    "FEATURE_ID",
    "archive_memory_scope_command_from_http",
    "archive_memory_scope_result_to_response",
    "build_memory_scopes_server_feature",
    "create_memory_scope_command_from_contract",
    "create_memory_scope_contract_from_http_request",
    "create_memory_scope_result_to_contract",
    "create_memory_scopes_router",
    "memory_scope_actor_from_http",
    "memory_scope_owner_from_http",
    "memory_scope_snapshot_to_contract",
    "memory_scope_to_response",
    "restore_memory_scope_command_from_http",
    "restore_memory_scope_result_to_response",
    "transfer_memory_scope_ownership_command_from_http",
    "transfer_memory_scope_ownership_result_to_response",
)
