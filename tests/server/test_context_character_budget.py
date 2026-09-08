"""Character limits apply to complete canonical evidence before bridge mapping."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as core
import pytest
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    ContextBudgetDto,
)
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_server.api.v1.context import _build_context_bundle
from infinity_context_server.features.context_building import public as server


def item(identity="fact-1", text='雪 café "quoted" \\ evidence', *, tokens=8, **kwargs):
    ref = core.ContextSourceRef(
        source_type="document",
        source_id="source-1",
        chunk_id="chunk-1",
        char_start=12,
        char_end=90,
        quote_preview=text,
        page_number=3,
        time_start_ms=100,
        time_end_ms=900,
        bbox=(0.1, 0.2, 0.8, 0.9),
    )
    evidence = core.ContextEvidence(
        text=text,
        source_refs=(ref,),
        evidence_id="evidence-1",
        lifecycle_label="active",
        temporal_label="current",
        canonical_version=7,
    )
    return core.ContextItem(
        item_id=identity,
        text=text,
        kind="fact",
        evidence=(evidence,),
        estimated_tokens=tokens,
        **kwargs,
    )


def pack(items, cap=None, tokens=100, **kwargs):
    return asyncio.run(
        core.PackContextHandler(**kwargs).execute(
            core.PackContextQuery(
                query=core.ContextQuery(core.ContextScope("space", "scope"), "evidence"),
                candidates=items,
                budget=core.ContextBudget(tokens, max_rendered_chars=cap),
            )
        )
    ).bundle


def assert_consistent(bundle):
    assert bundle.total_estimated_tokens == sum(i.token_cost for i in bundle.items)
    assert bundle.prompt_section_plan.total_estimated_tokens == bundle.total_estimated_tokens
    assert set(bundle.prompt_section_plan.items) == set(bundle.items)
    assert bundle.rendered_evidence == core.ContextEvidenceRenderer().render_plan(
        bundle.prompt_section_plan
    )
    assert not set(i.item_id for i in bundle.items).intersection(
        i.item_id for i in bundle.dropped_items
    )


@pytest.mark.parametrize("cap", [0, 1, 26, 80])
def test_tiny_cap_omits_whole_record_and_overhead(cap):
    bundle = pack((item(),), cap)
    assert bundle.items == ()
    assert bundle.rendered_evidence == ""
    assert bundle.dropped_items[0].reason == "rendered_character_budget_exceeded"
    assert_consistent(bundle)


def test_exact_unicode_boundary_counts_characters_and_preserves_source():
    candidate = item()
    full = pack((candidate,))
    cap = len(full.rendered_evidence)
    assert len(full.rendered_evidence.encode()) > cap
    bounded = pack((candidate,), cap)
    assert bounded == full
    assert bounded.items[0] is candidate
    assert bounded.items[0].evidence[0].source_refs[0].char_start == 12
    assert pack((candidate,), cap - 1).items == ()
    assert_consistent(bounded)


def test_rejected_large_record_does_not_consume_tokens_or_prevent_smaller_record():
    large = item("large", "x" * 2000, priority=10, tokens=90)
    small = item("small", tokens=10)
    cap = len(pack((small,)).rendered_evidence)
    bundle = pack((large, small), cap, tokens=100)
    assert bundle.items == (small,)
    assert bundle.total_estimated_tokens == 10
    assert_consistent(bundle)


@pytest.mark.parametrize("char_binding", [True, False])
def test_token_and_character_budgets_bind_independently(char_binding):
    candidates = (item("a", priority=5), item("b", priority=4))
    cap = len(pack(candidates[:1]).rendered_evidence) if char_binding else 10000
    bundle = pack(candidates, cap, tokens=100 if char_binding else 8)
    assert bundle.items == candidates[:1]
    assert bundle.dropped_items[0].reason == (
        "rendered_character_budget_exceeded" if char_binding else "budget_exhausted"
    )
    assert_consistent(bundle)


def test_reserves_remain_independent_of_characters():
    candidates = (item("a"), item("b"))
    plan = core.ContextBudgetPolicy().plan(
        candidates, core.ContextBudget(20, 5, 7, max_rendered_chars=10000)
    )
    assert plan.selected_items == candidates[:1]
    assert plan.total_estimated_tokens == 8


def test_stable_ties_sections_escaping_and_numbering_are_measured():
    candidates = tuple(item(f"fact-{i}", priority=5, score=0.5) for i in range(12))
    candidates += (item("critical", tags=("critical",)), item("low", role="low_trust_evidence"))
    complete = pack(candidates, tokens=1000)
    cap = len(complete.rendered_evidence) - 1
    bounded = pack(candidates, cap, tokens=1000)
    assert bounded.items == candidates[:-1]
    assert len(bounded.rendered_evidence) <= cap
    assert "10." in bounded.rendered_evidence
    assert bounded == pack(candidates, cap, tokens=1000)
    assert_consistent(bounded)


def test_custom_render_policy_is_used_for_admission():
    renderer = core.ContextEvidenceRenderer(core.EvidenceRenderPolicy(heading="H" * 500))
    candidate = item()
    cap = len(pack((candidate,)).rendered_evidence)
    bundle = pack((candidate,), cap, evidence_renderer=renderer)
    assert bundle.items == ()
    assert bundle.rendered_evidence == ""


@pytest.mark.parametrize("cap", [None, 0, 1, 500])
def test_contract_http_and_mapping_carry_optional_cap(cap):
    http = server.ContextBudgetHttpRequest(max_context_tokens=100, max_rendered_chars=cap)
    dto = http.to_contract()
    assert dto.max_rendered_chars == cap
    for budget in (dto, dto.to_dict()):
        query = server.build_context_query_from_contract(
            BuildContextRequestDto(
                query="evidence",
                space_id="space",
                memory_scope_id="scope",
                budget=budget,
            )
        )
        assert query.budget.max_rendered_chars == cap
    assert ("max_rendered_chars" in dto.to_dict()) == (cap is not None)


def test_old_contract_serialization_and_positional_callers_are_unchanged():
    expected = dict(
        max_context_tokens=100, reserved_response_tokens=0, max_items=None, strategy="balanced"
    )
    assert ContextBudgetDto(100, 0, None, "balanced").to_dict() == expected
    assert (
        server.ContextBudgetHttpRequest(max_context_tokens=100).to_contract().to_dict() == expected
    )
    assert (
        server.ContextBudgetHttpRequest(
            max_context_tokens=100,
            max_rendered_chars=None,
        )
        .to_contract()
        .to_dict()
        == expected
    )
    assert core.ContextBudget(100, 2, 3).available_evidence_tokens == 95


@pytest.mark.parametrize("boundary", ["http", "domain", "mapping"])
def test_negative_cap_is_rejected(boundary):
    with pytest.raises(ValueError):
        if boundary == "http":
            server.ContextBudgetHttpRequest(max_rendered_chars=-1)
        elif boundary == "domain":
            core.ContextBudget(100, max_rendered_chars=-1)
        else:
            server.build_context_query_from_contract(
                BuildContextRequestDto(
                    query="evidence",
                    space_id="space",
                    memory_scope_id="scope",
                    budget={"max_context_tokens": 100, "max_rendered_chars": -1},
                )
            )


class Candidates:
    def __init__(self, items):
        self.items = items
        self.requests = []

    async def find_candidates(self, request):
        self.requests.append(request)
        return self.items


class RecordingHandler:
    def __init__(self, candidates):
        self.handler = core.BuildContextHandler(candidate_provider=candidates)
        self.queries = []
        self.result = None

    async def execute(self, query):
        self.queries.append(query)
        self.result = await self.handler.execute(query)
        return self.result


def repository_call(candidates, *, default=10000, explicit=None, request=None):
    handler = RecordingHandler(Candidates(candidates))
    container = SimpleNamespace(
        settings=SimpleNamespace(max_context_chars=default),
        build_canonical_fact_context=handler,
    )
    request = request or server.ContextRequest(
        query="evidence",
        repository_id="repo",
        code_scope_id="code",
        token_budget=100,
    )
    result = asyncio.run(
        _build_context_bundle(
            request,
            scope=SimpleNamespace(space_id="space", memory_scope_ids=("scope",), thread_id=None),
            container=container,
            bundle_id="bundle",
            max_rendered_chars=explicit,
        )
    )
    return result, handler


@pytest.mark.parametrize("explicit", [None, 0, 1, 10000])
def test_repository_single_scope_deployment_fallback_and_explicit_override(explicit):
    candidate = item()
    cap = len(pack((candidate,)).rendered_evidence)
    legacy, handler = repository_call((candidate,), default=cap, explicit=explicit)
    effective = cap if explicit is None else explicit
    assert handler.queries[0].budget.max_rendered_chars == effective
    assert handler.queries[0].query.repository_id == "repo"
    assert handler.queries[0].query.code_scope_id == "code"
    bundle = handler.result.bundle
    assert_consistent(bundle)
    assert len(legacy.rendered_text) <= effective
    assert legacy.rendered_text == bundle.rendered_evidence
    assert legacy.token_estimate == bundle.total_estimated_tokens
    assert len(legacy.items) == len(bundle.items)
    assert legacy.diagnostics["repository_isolation_mode"] == "canonical_facts_only"
    assert legacy.diagnostics["canonical_chunk_candidate_count"] == 0
    if legacy.items:
        assert legacy.items[0].source_refs[0].char_start == 12
        assert legacy.items[0].source_refs[0].char_end == 90


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "category"),
        ("tags_any", ["tag"]),
        ("tags_all", ["tag"]),
        ("tags_none", ["tag"]),
        ("include_superseded", True),
        ("include_stale", True),
    ],
)
def test_repository_filter_restrictions_remain_closed(field, value):
    request = server.ContextRequest(query="evidence", repository_id="repo", **{field: value})
    with pytest.raises(MemoryValidationError, match="does not support filters"):
        repository_call((item(),), request=request)


def test_repository_zero_fact_limit_never_loads_candidates():
    request = server.ContextRequest(query="evidence", repository_id="repo", max_facts=0)
    legacy, handler = repository_call((item(),), default=1, request=request)
    assert handler.queries == []
    assert legacy.items == ()
    assert legacy.rendered_text == ""


def test_explicit_null_mapping_keeps_the_old_unbounded_feature_default():
    query = server.build_context_query_from_contract(
        BuildContextRequestDto(
            query="evidence",
            space_id="space",
            memory_scope_id="scope",
            budget={"max_context_tokens": 100, "max_rendered_chars": None},
        )
    )
    assert query.budget.max_rendered_chars is None
    assert server.ContextBudgetHttpRequest().model_dump(exclude_unset=True) == {}
    assert server.ContextBudgetHttpRequest(max_rendered_chars=None).model_dump(
        exclude_unset=True
    ) == {"max_rendered_chars": None}


def test_custom_section_planner_is_used_for_character_admission():
    class LongSectionPlanner:
        def plan(self, items):
            from dataclasses import replace

            plan = core.PromptSectionPlanner().plan(items)
            return core.PromptSectionPlan(
                sections=tuple(replace(s, title="Title" * 100) for s in plan.sections),
                total_estimated_tokens=plan.total_estimated_tokens,
            )

    candidate = item()
    cap = len(pack((candidate,)).rendered_evidence)
    assert pack((candidate,), cap, prompt_section_planner=LongSectionPlanner()).items == ()


def test_repository_token_binding_keeps_bridge_metadata_consistent():
    candidates = (item("a", tokens=60), item("b", tokens=60))
    legacy, handler = repository_call(candidates)
    bundle = handler.result.bundle
    assert bundle.items == candidates[:1]
    assert legacy.token_estimate == 60
    assert legacy.items[0].item_id == "a"
    assert legacy.diagnostics["dropped_item_count"] == 1
    assert_consistent(bundle)


def test_domain_policy_measures_default_rendering_for_direct_callers():
    candidate = item()
    cap = len(pack((candidate,)).rendered_evidence)
    policy = core.ContextBudgetPolicy()
    assert policy.plan(
        (candidate,), core.ContextBudget(100, max_rendered_chars=cap)
    ).selected_items == (candidate,)
    assert (
        policy.plan(
            (candidate,), core.ContextBudget(100, max_rendered_chars=cap - 1)
        ).selected_items
        == ()
    )


def test_repository_actual_deployment_default_bounds_an_overflowing_bundle():
    from infinity_context_server.config import Settings

    default = Settings.model_fields["max_context_chars"].default
    candidates = tuple(item(f"fact-{i}", "雪" * 1200, tokens=1) for i in range(20))
    assert len(pack(candidates).rendered_evidence) > default
    legacy, handler = repository_call(candidates, default=default)
    assert 0 < len(legacy.rendered_text) <= default
    assert len(legacy.items) < len(candidates)
    assert handler.queries[0].budget.max_rendered_chars == default
    assert_consistent(handler.result.bundle)
