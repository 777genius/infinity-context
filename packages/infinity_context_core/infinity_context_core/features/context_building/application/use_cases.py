"""Use case protocols for context building."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.context_building.application.queries import (
    BuildContextQuery,
    BuildContextResult,
    PackContextQuery,
    PackContextResult,
    PlanContextPipelineQuery,
    PlanContextPipelineResult,
)
from infinity_context_core.features.context_building.application.handlers import (
    BuildContextHandler,
    PackContextHandler,
    PlanContextPipelineHandler,
)


class BuildContextUseCase(Protocol):
    async def execute(self, query: BuildContextQuery) -> BuildContextResult:
        """Build prompt-ready context evidence through the feature boundary."""


class PackContextUseCase(Protocol):
    async def execute(self, query: PackContextQuery) -> PackContextResult:
        """Pack hydrated context candidates without crossing feature boundaries."""


class PlanContextPipelineUseCase(Protocol):
    async def execute(
        self,
        query: PlanContextPipelineQuery,
    ) -> PlanContextPipelineResult:
        """Plan query expansion and prompt sections through the feature boundary."""


@dataclass(frozen=True, slots=True)
class ContextBuildingUseCases:
    """Feature-owned context building use case bundle."""

    build_context: BuildContextUseCase
    pack_context: PackContextUseCase | None = None
    plan_context_pipeline: PlanContextPipelineUseCase | None = None


__all__ = (
    "BuildContextHandler",
    "BuildContextUseCase",
    "ContextBuildingUseCases",
    "PackContextHandler",
    "PackContextUseCase",
    "PlanContextPipelineHandler",
    "PlanContextPipelineUseCase",
)
