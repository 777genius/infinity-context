"""Use case protocols for context building."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.context_building.application.handlers import (
    BuildContextHandler,
    LoadContextCandidatesHandler,
    PackContextHandler,
    PlanContextPipelineHandler,
)
from infinity_context_core.features.context_building.application.provider_pipeline import (
    ContextCandidateProviderPipeline,
    create_context_candidate_provider_pipeline,
)
from infinity_context_core.features.context_building.application.queries import (
    BuildContextQuery,
    BuildContextResult,
    LoadContextCandidatesQuery,
    LoadContextCandidatesResult,
    PackContextQuery,
    PackContextResult,
    PlanContextPipelineQuery,
    PlanContextPipelineResult,
)


class BuildContextUseCase(Protocol):
    async def execute(self, query: BuildContextQuery) -> BuildContextResult:
        """Build prompt-ready context evidence through the feature boundary."""


class PackContextUseCase(Protocol):
    async def execute(self, query: PackContextQuery) -> PackContextResult:
        """Pack hydrated context candidates without crossing feature boundaries."""


class LoadContextCandidatesUseCase(Protocol):
    async def execute(
        self,
        query: LoadContextCandidatesQuery,
    ) -> LoadContextCandidatesResult:
        """Plan provider query shape and load context candidates."""


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
    load_context_candidates: LoadContextCandidatesUseCase | None = None


__all__ = (
    "BuildContextHandler",
    "BuildContextUseCase",
    "ContextCandidateProviderPipeline",
    "ContextBuildingUseCases",
    "LoadContextCandidatesHandler",
    "LoadContextCandidatesUseCase",
    "PackContextHandler",
    "PackContextUseCase",
    "PlanContextPipelineHandler",
    "PlanContextPipelineUseCase",
    "create_context_candidate_provider_pipeline",
)
