"""Use case boundary protocols for the memory_facts feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.memory_facts.application.commands import (
    ForgetFactCommand,
    ForgetFactResult,
    RememberFactCommand,
    RememberFactResult,
    UpdateFactCommand,
    UpdateFactResult,
)


class RememberFactUseCase(Protocol):
    async def execute(self, command: RememberFactCommand) -> RememberFactResult:
        """Remember a fact through the feature-owned application boundary."""


class UpdateFactUseCase(Protocol):
    async def execute(self, command: UpdateFactCommand) -> UpdateFactResult:
        """Update a fact through the feature-owned application boundary."""


class ForgetFactUseCase(Protocol):
    async def execute(self, command: ForgetFactCommand) -> ForgetFactResult:
        """Forget a fact through the feature-owned application boundary."""


@dataclass(frozen=True, slots=True)
class MemoryFactLifecycleUseCases:
    """Feature-owned remember/update/forget use case bundle."""

    remember_fact: RememberFactUseCase
    update_fact: UpdateFactUseCase
    forget_fact: ForgetFactUseCase


__all__ = (
    "ForgetFactUseCase",
    "MemoryFactLifecycleUseCases",
    "RememberFactUseCase",
    "UpdateFactUseCase",
)
