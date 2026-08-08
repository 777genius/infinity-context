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
from infinity_context_core.features.memory_facts.application.conflicts import (
    DisputeFactsCommand,
    DisputeFactsResult,
)
from infinity_context_core.features.memory_facts.application.supersession import (
    ReinstateSupersededFactCommand,
    ReinstateSupersededFactResult,
    SupersedeFactCommand,
    SupersedeFactResult,
)
from infinity_context_core.features.memory_facts.application.temporal_mutations import (
    ConfirmFactCommand,
    ConfirmFactResult,
    EndFactValidityCommand,
    EndFactValidityResult,
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


class ConfirmFactUseCase(Protocol):
    async def execute(self, command: ConfirmFactCommand) -> ConfirmFactResult: ...


class EndFactValidityUseCase(Protocol):
    async def execute(self, command: EndFactValidityCommand) -> EndFactValidityResult: ...


class SupersedeFactUseCase(Protocol):
    async def execute(self, command: SupersedeFactCommand) -> SupersedeFactResult: ...


class DisputeFactsUseCase(Protocol):
    async def execute(self, command: DisputeFactsCommand) -> DisputeFactsResult: ...


class ReinstateSupersededFactUseCase(Protocol):
    async def execute(
        self,
        command: ReinstateSupersededFactCommand,
    ) -> ReinstateSupersededFactResult: ...


@dataclass(frozen=True, slots=True)
class MemoryFactLifecycleUseCases:
    """Feature-owned remember/update/forget use case bundle."""

    remember_fact: RememberFactUseCase
    update_fact: UpdateFactUseCase
    forget_fact: ForgetFactUseCase


@dataclass(frozen=True, slots=True)
class MemoryFactTemporalUseCases:
    """Audited temporal decisions exposed as one application capability."""

    confirm_fact: ConfirmFactUseCase
    end_validity: EndFactValidityUseCase
    supersede_fact: SupersedeFactUseCase
    dispute_facts: DisputeFactsUseCase
    reinstate_supersession: ReinstateSupersededFactUseCase


__all__ = (
    "ForgetFactUseCase",
    "MemoryFactLifecycleUseCases",
    "MemoryFactTemporalUseCases",
    "RememberFactUseCase",
    "UpdateFactUseCase",
)
