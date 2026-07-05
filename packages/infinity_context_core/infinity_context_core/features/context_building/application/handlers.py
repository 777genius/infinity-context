"""Concrete application handlers for prompt context building."""

from __future__ import annotations

from dataclasses import dataclass, field

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
from infinity_context_core.features.context_building.domain import (
    ContextBudgetPolicy,
    ContextBundle,
    ContextEvidenceRenderer,
    ContextQueryExpansionPolicy,
    PromptSectionPlanner,
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
    prompt_section_planner: PromptSectionPlanner = field(
        default_factory=PromptSectionPlanner
    )

    async def execute(self, query: PackContextQuery) -> PackContextResult:
        plan = self.budget_policy.plan(query.candidates, query.budget)
        prompt_section_plan = self.prompt_section_planner.plan(plan.selected_items)
        rendered_evidence = self.evidence_renderer.render_plan(prompt_section_plan)
        bundle = ContextBundle(
            query=query.query,
            items=plan.selected_items,
            dropped_items=plan.dropped_items,
            rendered_evidence=rendered_evidence,
            max_prompt_tokens=query.budget.max_prompt_tokens,
            total_estimated_tokens=plan.total_estimated_tokens,
            query_plan=query.query_plan,
            prompt_section_plan=prompt_section_plan,
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
    query_expansion_policy: ContextQueryExpansionPolicy = field(
        default_factory=ContextQueryExpansionPolicy
    )
    prompt_section_planner: PromptSectionPlanner = field(
        default_factory=PromptSectionPlanner
    )

    async def execute(self, query: BuildContextQuery) -> BuildContextResult:
        candidate_result = await LoadContextCandidatesHandler(
            candidate_provider=self.candidate_provider,
            query_expansion_policy=self.query_expansion_policy,
        ).execute(
            LoadContextCandidatesQuery(
                query=query.query,
                candidate_limit=query.candidate_limit,
                idempotency_key=query.idempotency_key,
            )
        )
        pack_result = await PackContextHandler(
            budget_policy=self.budget_policy,
            evidence_renderer=self.evidence_renderer,
            prompt_section_planner=self.prompt_section_planner,
        ).execute(
            PackContextQuery(
                query=query.query,
                budget=query.budget,
                candidates=candidate_result.candidates,
                idempotency_key=query.idempotency_key,
                query_plan=candidate_result.query_plan,
            )
        )
        return BuildContextResult(bundle=pack_result.bundle)


@dataclass(frozen=True, slots=True)
class LoadContextCandidatesHandler:
    """Plan provider query shape and load candidates through the feature port."""

    candidate_provider: ContextCandidateProviderPort
    query_expansion_policy: ContextQueryExpansionPolicy = field(
        default_factory=ContextQueryExpansionPolicy
    )

    async def execute(
        self,
        query: LoadContextCandidatesQuery,
    ) -> LoadContextCandidatesResult:
        query_plan = self.query_expansion_policy.plan(query.query)
        request = ContextCandidateRequest(
            query=query_plan.normalized_query,
            limit=query.candidate_limit,
            query_plan=query_plan,
        )
        candidates = await self.candidate_provider.find_candidates(request)
        return LoadContextCandidatesResult(
            query_plan=query_plan,
            candidate_request=request,
            candidates=candidates,
        )


@dataclass(frozen=True, slots=True)
class PlanContextPipelineHandler:
    """Plan context retrieval query variants and prompt evidence sections."""

    query_expansion_policy: ContextQueryExpansionPolicy = field(
        default_factory=ContextQueryExpansionPolicy
    )
    prompt_section_planner: PromptSectionPlanner = field(
        default_factory=PromptSectionPlanner
    )

    async def execute(
        self,
        query: PlanContextPipelineQuery,
    ) -> PlanContextPipelineResult:
        return PlanContextPipelineResult(
            query_plan=self.query_expansion_policy.plan(query.query),
            prompt_section_plan=self.prompt_section_planner.plan(query.candidates),
        )


__all__ = (
    "BuildContextHandler",
    "LoadContextCandidatesHandler",
    "PackContextHandler",
    "PlanContextPipelineHandler",
)
