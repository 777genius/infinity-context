"""Application boundary for the memory_scopes feature."""

from infinity_context_core.features.memory_scopes.application.commands import (
    CreateMemoryScopeCommand,
    CreateMemoryScopeResult,
    TransferMemoryScopeOwnershipCommand,
    TransferMemoryScopeOwnershipResult,
)
from infinity_context_core.features.memory_scopes.application.errors import (
    DuplicateMemoryScopeExternalRefError,
    MemoryScopeApplicationError,
    MemoryScopeConflictError,
    MemoryScopeNotFoundError,
)
from infinity_context_core.features.memory_scopes.application.handlers import (
    CreateMemoryScopeHandler,
    TransferMemoryScopeOwnershipHandler,
)
from infinity_context_core.features.memory_scopes.application.use_cases import (
    CreateMemoryScopeUseCase,
    MemoryScopeUseCases,
    TransferMemoryScopeOwnershipUseCase,
)

__all__ = (
    "CreateMemoryScopeCommand",
    "CreateMemoryScopeHandler",
    "CreateMemoryScopeResult",
    "CreateMemoryScopeUseCase",
    "DuplicateMemoryScopeExternalRefError",
    "MemoryScopeApplicationError",
    "MemoryScopeConflictError",
    "MemoryScopeNotFoundError",
    "MemoryScopeUseCases",
    "TransferMemoryScopeOwnershipCommand",
    "TransferMemoryScopeOwnershipHandler",
    "TransferMemoryScopeOwnershipResult",
    "TransferMemoryScopeOwnershipUseCase",
)
