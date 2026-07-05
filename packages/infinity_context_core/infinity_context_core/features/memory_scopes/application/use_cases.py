"""Use case boundary protocols for the memory_scopes feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.memory_scopes.application.commands import (
    CreateMemoryScopeCommand,
    CreateMemoryScopeResult,
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


@dataclass(frozen=True, slots=True)
class MemoryScopeUseCases:
    """Feature-owned memory scope use case bundle."""

    create_memory_scope: CreateMemoryScopeUseCase
    transfer_memory_scope_ownership: TransferMemoryScopeOwnershipUseCase


__all__ = (
    "CreateMemoryScopeUseCase",
    "MemoryScopeUseCases",
    "TransferMemoryScopeOwnershipUseCase",
)
