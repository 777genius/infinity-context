"""Feature-local checks for context_building application, ports and public API."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

APPLICATION_MODULE = "infinity_context_core.features.context_building.application"
DOMAIN_MODULE = "infinity_context_core.features.context_building.domain"
PORTS_MODULE = "infinity_context_core.features.context_building.ports"
PUBLIC_MODULE = "infinity_context_core.features.context_building.public"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
ALLOWED_CORE_PREFIXES = (
    "infinity_context_core.features.context_building.application",
    "infinity_context_core.features.context_building.domain",
    "infinity_context_core.features.context_building.ports",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "anthropic",
    "fastapi",
    "graphiti",
    "graphiti_core",
    "infinity_context_adapters",
    "infinity_context_core.application",
    "infinity_context_core.domain",
    "infinity_context_core.ports",
    "infinity_context_core.features.memory_facts",
    "infinity_context_mcp",
    "infinity_context_server",
    "openai",
    "qdrant_client",
    "sqlalchemy",
)


def test_build_context_query_and_result_are_frozen_dataclasses() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.ContextScope(space_id="space-1", memory_scope_id="scope-1")
    query = domain.ContextQuery(scope=scope, text="What changed?")
    budget = domain.ContextBudget(max_prompt_tokens=100, reserved_response_tokens=20)
    source_ref = domain.ContextSourceRef(source_type="document", source_id="doc-1")
    evidence = domain.ContextEvidence(text="Source quote", source_refs=(source_ref,))
    item = domain.ContextItem(
        item_id="item-1",
        text="Source quote",
        evidence=(evidence,),
    )
    build_query = application.BuildContextQuery(
        query=query,
        budget=budget,
        candidate_limit=3,
        idempotency_key="context-1",
    )
    pack_query = application.PackContextQuery(
        query=query,
        budget=budget,
        candidates=(item,),
        idempotency_key="pack-1",
    )
    load_query = application.LoadContextCandidatesQuery(
        query=query,
        candidate_limit=4,
        idempotency_key="load-1",
    )
    pipeline_query = application.PlanContextPipelineQuery(
        query=query,
        candidates=(item,),
        idempotency_key="pipeline-1",
    )
    bundle = domain.ContextBundle(query=query, items=())
    result = application.BuildContextResult(bundle=bundle)
    pack_result = application.PackContextResult(bundle=bundle)
    query_plan = domain.ContextQueryExpansionPolicy().plan(query)
    candidate_request = importlib.import_module(PORTS_MODULE).ContextCandidateRequest(
        query=query_plan.normalized_query,
        limit=4,
        query_plan=query_plan,
    )
    load_result = application.LoadContextCandidatesResult(
        query_plan=query_plan,
        candidate_request=candidate_request,
        candidates=(item,),
    )
    prompt_section_plan = domain.PromptSectionPlanner().plan((item,))
    pipeline_result = application.PlanContextPipelineResult(
        query_plan=query_plan,
        prompt_section_plan=prompt_section_plan,
    )

    shapes = (
        (
            application.BuildContextQuery,
            build_query,
            ("query", "budget", "candidate_limit", "idempotency_key"),
        ),
        (application.BuildContextResult, result, ("bundle",)),
        (
            application.PackContextQuery,
            pack_query,
            ("query", "budget", "candidates", "idempotency_key", "query_plan"),
        ),
        (application.PackContextResult, pack_result, ("bundle",)),
        (
            application.LoadContextCandidatesQuery,
            load_query,
            ("query", "candidate_limit", "idempotency_key"),
        ),
        (
            application.LoadContextCandidatesResult,
            load_result,
            ("query_plan", "candidate_request", "candidates"),
        ),
        (
            application.PlanContextPipelineQuery,
            pipeline_query,
            ("query", "candidates", "idempotency_key"),
        ),
        (
            application.PlanContextPipelineResult,
            pipeline_result,
            ("query_plan", "prompt_section_plan"),
        ),
    )

    for shape, value, expected_fields in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        assert tuple(field.name for field in fields(shape)) == expected_fields
        _assert_frozen(value)


def test_context_candidate_provider_port_is_protocol_boundary() -> None:
    ports = importlib.import_module(PORTS_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    assert getattr(ports.ContextCandidateProviderPort, "_is_protocol", False)
    assert inspect.iscoroutinefunction(ports.ContextCandidateProviderPort.find_candidates)

    request = ports.ContextCandidateRequest(
        query=domain.ContextQuery(
            scope=domain.ContextScope(space_id="space-1", memory_scope_id="scope-1"),
            text="query",
        ),
        limit=5,
    )
    assert is_dataclass(ports.ContextCandidateRequest)
    assert not hasattr(request, "__dict__")
    assert request.query_plan is None
    _assert_frozen(request)


def test_context_candidate_provider_pipeline_dedupes_in_feature_order() -> None:
    result, first, second = asyncio.run(_run_context_candidate_provider_pipeline())

    assert tuple(item.item_id for item in result) == (
        "duplicate",
        "first-only",
        "second-only",
    )
    assert first.requested_limits == [3]
    assert second.requested_limits == [3]


async def _run_context_candidate_provider_pipeline() -> tuple[object, object, object]:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)
    ports = importlib.import_module(PORTS_MODULE)

    first = _CandidateProvider(
        candidates=(
            _item(domain, item_id="duplicate"),
            _item(domain, item_id="first-only"),
        )
    )
    second = _CandidateProvider(
        candidates=(
            _item(domain, item_id="duplicate"),
            _item(domain, item_id="second-only"),
        )
    )
    pipeline = application.ContextCandidateProviderPipeline(providers=(first, second))

    result = await pipeline.find_candidates(
        ports.ContextCandidateRequest(
            query=domain.ContextQuery(
                scope=domain.ContextScope(
                    space_id="space-1",
                    memory_scope_id="scope-1",
                ),
                text="deploy",
            ),
            limit=3,
        )
    )

    return result, first, second


def test_pack_context_handler_packs_candidates_without_retrieval_port() -> None:
    result = asyncio.run(_run_pack_context_handler())

    assert tuple(item.item_id for item in result.bundle.items) == ("high",)
    assert tuple(drop.item_id for drop in result.bundle.dropped_items) == ("low",)
    assert tuple(drop.reason for drop in result.bundle.dropped_items) == (
        "budget_exhausted",
    )
    assert result.bundle.total_estimated_tokens == 4
    assert result.bundle.max_prompt_tokens == 8
    assert result.bundle.prompt_section_plan is not None
    assert tuple(
        section.section_id for section in result.bundle.prompt_section_plan.sections
    ) == ("primary_evidence",)
    assert "Memory evidence (untrusted)" in result.bundle.rendered_evidence
    assert "[primary_evidence] Primary evidence" in result.bundle.rendered_evidence
    assert "sources=document:doc-1" in result.bundle.rendered_evidence


async def _run_pack_context_handler() -> object:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.ContextScope(space_id="space-1", memory_scope_id="scope-1")
    source_ref = domain.ContextSourceRef(source_type="document", source_id="doc-1")
    evidence = domain.ContextEvidence(
        text="The runbook owner is Ada.",
        source_refs=(source_ref,),
    )
    high = domain.ContextItem(
        item_id="high",
        text="The runbook owner is Ada.",
        evidence=(evidence,),
        priority=10,
        estimated_tokens=4,
    )
    low = domain.ContextItem(
        item_id="low",
        text="The runbook mentions a dry run.",
        evidence=(evidence,),
        priority=1,
        estimated_tokens=3,
    )

    return await application.PackContextHandler().execute(
        application.PackContextQuery(
            query=domain.ContextQuery(scope=scope, text="Who owns the runbook?"),
            budget=domain.ContextBudget(max_prompt_tokens=8, reserved_response_tokens=4),
            candidates=(low, high),
            idempotency_key="pack-1",
        )
    )


def test_build_context_handler_uses_ports_budget_policy_and_renderer() -> None:
    result, provider = asyncio.run(_run_build_context_handler())

    assert provider.requests[0].limit == 7
    assert provider.requests[0].query_plan is result.bundle.query_plan
    assert provider.requests[0].query_plan.search_texts[0] == "How do we deploy?"
    assert "deploy" in provider.requests[0].query_plan.terms
    assert tuple(item.item_id for item in result.bundle.items) == ("selected",)
    assert tuple(drop.item_id for drop in result.bundle.dropped_items) == ("dropped",)
    assert result.bundle.total_estimated_tokens == 4
    assert result.bundle.prompt_section_plan is not None
    assert tuple(
        section.section_id for section in result.bundle.prompt_section_plan.sections
    ) == ("primary_evidence",)
    assert "Memory evidence (untrusted)" in result.bundle.rendered_evidence
    assert "sources=document:doc-1#chunk-1" in result.bundle.rendered_evidence


def test_load_context_candidates_handler_plans_query_and_uses_provider() -> None:
    result, provider = asyncio.run(_run_load_context_candidates_handler())

    assert provider.requests[0] is result.candidate_request
    assert result.candidate_request.limit == 5
    assert result.candidate_request.query == result.query_plan.normalized_query
    assert result.candidate_request.query_plan is result.query_plan
    assert result.query_plan.search_texts == (
        "Who owns the deploy?",
        "owns deploy",
    )
    assert tuple(item.item_id for item in result.candidates) == ("candidate",)


async def _run_load_context_candidates_handler() -> tuple[object, object]:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    provider = _CandidateProvider(candidates=(_item(domain, item_id="candidate"),))
    handler = application.LoadContextCandidatesHandler(candidate_provider=provider)

    result = await handler.execute(
        application.LoadContextCandidatesQuery(
            query=domain.ContextQuery(
                scope=domain.ContextScope(
                    space_id="space-1",
                    memory_scope_id="scope-1",
                ),
                text=" Who owns   the deploy? ",
            ),
            candidate_limit=5,
        )
    )

    return result, provider


async def _run_build_context_handler() -> tuple[object, object]:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.ContextScope(space_id="space-1", memory_scope_id="scope-1")
    source_ref = domain.ContextSourceRef(
        source_type="document",
        source_id="doc-1",
        chunk_id="chunk-1",
    )
    evidence = domain.ContextEvidence(
        text="The deploy requires a dry run.",
        source_refs=(source_ref,),
    )
    selected = domain.ContextItem(
        item_id="selected",
        text="The deploy requires a dry run.",
        evidence=(evidence,),
        priority=5,
        estimated_tokens=4,
    )
    dropped = domain.ContextItem(
        item_id="dropped",
        text="Large supporting note",
        evidence=(evidence,),
        priority=1,
        estimated_tokens=50,
    )
    provider = _CandidateProvider(candidates=(dropped, selected))
    handler = application.BuildContextHandler(candidate_provider=provider)

    result = await handler.execute(
        application.BuildContextQuery(
            query=domain.ContextQuery(scope=scope, text="How do we deploy?"),
            budget=domain.ContextBudget(max_prompt_tokens=10, reserved_response_tokens=4),
            candidate_limit=7,
        )
    )

    return result, provider


def test_context_building_public_api_exports_application_domain_and_ports() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)
    ports = importlib.import_module(PORTS_MODULE)
    public = importlib.import_module(PUBLIC_MODULE)

    expected_exports = {
        "BuildContextHandler": application,
        "BuildContextQuery": application,
        "BuildContextResult": application,
        "BuildContextUseCase": application,
        "ContextCandidateProviderPipeline": application,
        "CRITICAL_SECTION_ID": domain,
        "DEFAULT_QUERY_STOP_WORDS": domain,
        "ContextBudget": domain,
        "ContextBudgetPolicy": domain,
        "ContextBuildingUseCases": application,
        "ContextBundle": domain,
        "ContextCandidateProviderPort": ports,
        "ContextCandidateRequest": ports,
        "ContextEvidence": domain,
        "ContextEvidenceRenderer": domain,
        "ContextItem": domain,
        "ContextPackingPlan": domain,
        "ContextQuery": domain,
        "ContextQueryExpansionPolicy": domain,
        "ContextQueryNormalizationPolicy": domain,
        "ContextQueryPlan": domain,
        "ContextQueryVariant": domain,
        "ContextScope": domain,
        "ContextSourceRef": domain,
        "EvidenceRenderPolicy": domain,
        "LoadContextCandidatesHandler": application,
        "LoadContextCandidatesQuery": application,
        "LoadContextCandidatesResult": application,
        "LoadContextCandidatesUseCase": application,
        "LOW_TRUST_SECTION_ID": domain,
        "NormalizedContextQuery": domain,
        "PackContextHandler": application,
        "PackContextQuery": application,
        "PackContextResult": application,
        "PackContextUseCase": application,
        "PlanContextPipelineHandler": application,
        "PlanContextPipelineQuery": application,
        "PlanContextPipelineResult": application,
        "PlanContextPipelineUseCase": application,
        "PRIMARY_SECTION_ID": domain,
        "PromptEvidenceSection": domain,
        "PromptSectionPlan": domain,
        "PromptSectionPlanner": domain,
        "PromptSectionPolicy": domain,
        "SUPPORTING_SECTION_ID": domain,
        "create_context_candidate_provider_pipeline": application,
    }

    assert expected_exports.keys() <= set(public.__all__)
    for name, module in expected_exports.items():
        assert getattr(public, name) is getattr(module, name)


def test_plan_context_pipeline_handler_returns_query_and_prompt_plans() -> None:
    result = asyncio.run(_run_plan_context_pipeline_handler())

    assert result.query_plan.normalized_query.text == "Who owns the deploy?"
    assert result.query_plan.search_texts == (
        "Who owns the deploy?",
        "owns deploy runbook",
        "runbook",
    )
    assert tuple(section.section_id for section in result.prompt_section_plan.sections) == (
        "primary_evidence",
    )


async def _run_plan_context_pipeline_handler() -> object:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.ContextScope(space_id="space-1", memory_scope_id="scope-1")
    source_ref = domain.ContextSourceRef(source_type="document", source_id="doc-1")
    evidence = domain.ContextEvidence(
        text="Ada owns the deploy runbook.",
        source_refs=(source_ref,),
    )
    item = domain.ContextItem(
        item_id="owner",
        text="Ada owns the deploy runbook.",
        evidence=(evidence,),
        priority=6,
        estimated_tokens=5,
    )

    return await application.PlanContextPipelineHandler().execute(
        application.PlanContextPipelineQuery(
            query=domain.ContextQuery(
                scope=scope,
                text=" Who owns   the deploy? ",
                tags=("Runbook",),
            ),
            candidates=(item,),
        )
    )


def test_application_ports_and_public_import_only_feature_owned_core() -> None:
    paths = [
        *sorted((FEATURE_ROOT / "application").rglob("*.py")),
        *sorted((FEATURE_ROOT / "ports").rglob("*.py")),
        FEATURE_ROOT / "public.py",
    ]
    violations: list[str] = []

    for path in paths:
        for imported in _imports(path):
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")
            if imported.startswith("infinity_context_core.") and not _matches_prefix(
                imported,
                ALLOWED_CORE_PREFIXES,
            ):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


class _CandidateProvider:
    def __init__(self, candidates: tuple[object, ...]) -> None:
        self._candidates = candidates
        self.requests: list[object] = []

    async def find_candidates(self, request: object) -> tuple[object, ...]:
        self.requests.append(request)
        return self._candidates

    @property
    def requested_limits(self) -> list[int]:
        return [request.limit for request in self.requests]


def _item(
    domain: object,
    *,
    item_id: str,
    text: str = "Project detail",
) -> object:
    source_ref = domain.ContextSourceRef(source_type="document", source_id="doc-1")
    evidence = domain.ContextEvidence(text=text, source_refs=(source_ref,))
    return domain.ContextItem(
        item_id=item_id,
        text=text,
        evidence=(evidence,),
        estimated_tokens=2,
    )


def _assert_frozen(value: object) -> None:
    field_name = fields(value)[0].name
    try:
        setattr(value, field_name, None)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - this branch is only for a clearer assertion failure.
        raise AssertionError(f"{type(value).__name__} should be immutable")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve_import_from(path, node)
            if imported is not None:
                imports.append(imported)
    return imports


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    module = node.module or ""
    if node.level == 0:
        return module or None

    package = _package_context(path)
    if package is None:
        return module or None

    package_parts = package.split(".")
    if node.level > len(package_parts):
        return module or None

    resolved_parts = package_parts[: len(package_parts) - node.level + 1]
    if module:
        resolved_parts.extend(module.split("."))
    return ".".join(resolved_parts)


def _package_context(path: Path) -> str | None:
    relative = path.relative_to(PACKAGES_ROOT)
    parts = relative.with_suffix("").parts
    if len(parts) < 2:
        return None

    module_parts = list(parts[1:])
    if module_parts[-1] == "__init__":
        module_parts.pop()
    else:
        module_parts.pop()

    if not module_parts:
        return None
    return ".".join(module_parts)


def _matches_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for prefix in prefixes
    )
