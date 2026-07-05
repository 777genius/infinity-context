"""Use case protocols and default orchestration for context building."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from infinity_context_core.features.context_building.application.queries import (
    BuildContextQuery,
    BuildContextResult,
)
from infinity_context_core.features.context_building.domain import (
    ContextBudgetPolicy,
    ContextBundle,
    ContextEvidenceRenderer,
)
from infinity_context_core.features.context_building.ports import (
    ContextCandidateProviderPort,
    ContextCandidateRequest,
)


class BuildContextUseCase(Protocol):
    async def execute(self, query: BuildContextQuery) -> BuildContextResult:
        """Build prompt-ready context evidence through the feature boundary."""


@dataclass(frozen=True, slots=True)
class BuildContextHandler:
    """Default context-building use case with feature-local policies."""

    candidate_provider: ContextCandidateProviderPort
    budget_policy: ContextBudgetPolicy = field(default_factory=ContextBudgetPolicy)
    evidence_renderer: ContextEvidenceRenderer = field(
        default_factory=ContextEvidenceRenderer
    )

    async def execute(self, query: BuildContextQuery) -> BuildContextResult:
        request = ContextCandidateRequest(
            query=query.query,
            limit=query.candidate_limit,
        )
        candidates = await self.candidate_provider.find_candidates(request)
        plan = self.budget_policy.plan(candidates, query.budget)
        rendered_evidence = self.evidence_renderer.render(plan.selected_items)
        bundle = ContextBundle(
            query=query.query,
            items=plan.selected_items,
            dropped_items=plan.dropped_items,
            rendered_evidence=rendered_evidence,
            max_prompt_tokens=query.budget.max_prompt_tokens,
            total_estimated_tokens=plan.total_estimated_tokens,
        )
        return BuildContextResult(bundle=bundle)


@dataclass(frozen=True, slots=True)
class ContextBuildingUseCases:
    """Feature-owned context building use case bundle."""

    build_context: BuildContextUseCase


__all__ = (
    "BuildContextHandler",
    "BuildContextUseCase",
    "ContextBuildingUseCases",
)
