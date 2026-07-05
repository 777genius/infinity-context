"""Application boundary for the memory_scopes feature."""

from infinity_context_core.features.memory_scopes.application.commands import (
    ArchiveMemoryScopeCommand,
    ArchiveMemoryScopeResult,
    CreateMemoryScopeCommand,
    CreateMemoryScopeResult,
    RestoreMemoryScopeCommand,
    RestoreMemoryScopeResult,
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
    ArchiveMemoryScopeHandler,
    CreateMemoryScopeHandler,
    RestoreMemoryScopeHandler,
    TransferMemoryScopeOwnershipHandler,
)
from infinity_context_core.features.memory_scopes.application.use_cases import (
    ArchiveMemoryScopeUseCase,
    CreateMemoryScopeUseCase,
    MemoryScopeUseCases,
    RestoreMemoryScopeUseCase,
    TransferMemoryScopeOwnershipUseCase,
)

__all__ = (
    "ArchiveMemoryScopeCommand",
    "ArchiveMemoryScopeHandler",
    "ArchiveMemoryScopeResult",
    "ArchiveMemoryScopeUseCase",
    "CreateMemoryScopeCommand",
    "CreateMemoryScopeHandler",
    "CreateMemoryScopeResult",
    "CreateMemoryScopeUseCase",
    "DuplicateMemoryScopeExternalRefError",
    "MemoryScopeApplicationError",
    "MemoryScopeConflictError",
    "MemoryScopeNotFoundError",
    "MemoryScopeUseCases",
    "RestoreMemoryScopeCommand",
    "RestoreMemoryScopeHandler",
    "RestoreMemoryScopeResult",
    "RestoreMemoryScopeUseCase",
    "TransferMemoryScopeOwnershipCommand",
    "TransferMemoryScopeOwnershipHandler",
    "TransferMemoryScopeOwnershipResult",
    "TransferMemoryScopeOwnershipUseCase",
)
