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
    bundle = domain.ContextBundle(query=query, items=())
    result = application.BuildContextResult(bundle=bundle)
    pack_result = application.PackContextResult(bundle=bundle)

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
            ("query", "budget", "candidates", "idempotency_key"),
        ),
        (application.PackContextResult, pack_result, ("bundle",)),
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
    _assert_frozen(request)


def test_pack_context_handler_packs_candidates_without_retrieval_port() -> None:
    result = asyncio.run(_run_pack_context_handler())

    assert tuple(item.item_id for item in result.bundle.items) == ("high",)
    assert tuple(drop.item_id for drop in result.bundle.dropped_items) == ("low",)
    assert tuple(drop.reason for drop in result.bundle.dropped_items) == (
        "budget_exhausted",
    )
    assert result.bundle.total_estimated_tokens == 4
    assert result.bundle.max_prompt_tokens == 8
    assert "Memory evidence (untrusted)" in result.bundle.rendered_evidence
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
    assert tuple(item.item_id for item in result.bundle.items) == ("selected",)
    assert tuple(drop.item_id for drop in result.bundle.dropped_items) == ("dropped",)
    assert result.bundle.total_estimated_tokens == 4
    assert "Memory evidence (untrusted)" in result.bundle.rendered_evidence
    assert "sources=document:doc-1#chunk-1" in result.bundle.rendered_evidence


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
        "ContextScope": domain,
        "ContextSourceRef": domain,
        "EvidenceRenderPolicy": domain,
        "PackContextHandler": application,
        "PackContextQuery": application,
        "PackContextResult": application,
        "PackContextUseCase": application,
    }

    assert expected_exports.keys() <= set(public.__all__)
    for name, module in expected_exports.items():
        assert getattr(public, name) is getattr(module, name)


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
