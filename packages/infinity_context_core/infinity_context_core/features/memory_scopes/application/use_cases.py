"""Use case boundary protocols for the memory_scopes feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


class CreateMemoryScopeUseCase(Protocol):
    async def execute(
        self,
        command: CreateMemoryScopeCommand,
    ) -> CreateMemoryScopeResult:
        """Create a memory scope through the feature-owned application boundary."""


class TransferMemoryScopeOwnershipUseCase(Protocol):
    async def execute(
        self,
        command: TransferMemoryScopeOwnershipCommand,
    ) -> TransferMemoryScopeOwnershipResult:
        """Transfer ownership through the feature-owned application boundary."""


class ArchiveMemoryScopeUseCase(Protocol):
    async def execute(
        self,
        command: ArchiveMemoryScopeCommand,
    ) -> ArchiveMemoryScopeResult:
        """Archive a memory scope through the feature-owned application boundary."""


class RestoreMemoryScopeUseCase(Protocol):
    async def execute(
        self,
        command: RestoreMemoryScopeCommand,
    ) -> RestoreMemoryScopeResult:
        """Restore a memory scope through the feature-owned application boundary."""


@dataclass(frozen=True, slots=True)
class MemoryScopeUseCases:
    """Feature-owned memory scope use case bundle."""

    create_memory_scope: CreateMemoryScopeUseCase
    transfer_memory_scope_ownership: TransferMemoryScopeOwnershipUseCase
    archive_memory_scope: ArchiveMemoryScopeUseCase
    restore_memory_scope: RestoreMemoryScopeUseCase


__all__ = (
    "ArchiveMemoryScopeUseCase",
    "CreateMemoryScopeUseCase",
    "MemoryScopeUseCases",
    "RestoreMemoryScopeUseCase",
    "TransferMemoryScopeOwnershipUseCase",
)
