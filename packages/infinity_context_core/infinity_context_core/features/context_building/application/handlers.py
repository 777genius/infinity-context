"""Concrete application handlers for prompt context building."""

from __future__ import annotations

from dataclasses import dataclass, field

from infinity_context_core.features.context_building.application.queries import (
    BuildContextQuery,
    BuildContextResult,
    PackContextQuery,
    PackContextResult,
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


@dataclass(frozen=True, slots=True)
class PackContextHandler:
    """Pack hydrated candidates with feature-owned budget and rendering policies."""

    budget_policy: ContextBudgetPolicy = field(default_factory=ContextBudgetPolicy)
    evidence_renderer: ContextEvidenceRenderer = field(
        default_factory=ContextEvidenceRenderer
    )

    async def execute(self, query: PackContextQuery) -> PackContextResult:
        plan = self.budget_policy.plan(query.candidates, query.budget)
        rendered_evidence = self.evidence_renderer.render(plan.selected_items)
        bundle = ContextBundle(
            query=query.query,
            items=plan.selected_items,
            dropped_items=plan.dropped_items,
            rendered_evidence=rendered_evidence,
            max_prompt_tokens=query.budget.max_prompt_tokens,
            total_estimated_tokens=plan.total_estimated_tokens,
        )
        return PackContextResult(bundle=bundle)


@dataclass(frozen=True, slots=True)
class BuildContextHandler:
    """Load context candidates through the feature port, then pack them safely."""

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
        pack_result = await PackContextHandler(
            budget_policy=self.budget_policy,
            evidence_renderer=self.evidence_renderer,
        ).execute(
            PackContextQuery(
                query=query.query,
                budget=query.budget,
                candidates=candidates,
                idempotency_key=query.idempotency_key,
            )
        )
        return BuildContextResult(bundle=pack_result.bundle)


__all__ = ("BuildContextHandler", "PackContextHandler")
