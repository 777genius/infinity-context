"""Import and placeholder checks for context_building adapter seams."""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
from pathlib import Path

import pytest

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    BuildContextHandler,
    BuildContextQuery,
    ContextBudget,
    ContextCandidateRequest,
    ContextItem,
    ContextQuery,
    ContextScope,
    ContextSourceRef,
)


FEATURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "infinity_context_adapters"
    / "infinity_context_adapters"
    / "features"
    / "context_building"
)
ALLOWED_CORE_FEATURE_IMPORT = "infinity_context_core.features.context_building.public"
FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "graphiti",
    "graphiti_core",
    "infinity_context_core.features.context_building.application",
    "infinity_context_core.features.context_building.domain",
    "infinity_context_core.features.context_building.ports",
    "openai",
    "qdrant_client",
    "sqlalchemy",
)


def test_context_building_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.context_building")
    features = importlib.import_module("infinity_context_adapters.features")

    assert "context_building" in features.__all__
    assert module.FEATURE_ID == FEATURE_ID == "context_building"
    assert module.InMemoryContextCandidateProvider.feature_id == FEATURE_ID
    assert module.ContextCandidateProviderChain.feature_id == FEATURE_ID
    assert module.PostgresContextCandidateProvider.feature_id == FEATURE_ID
    assert module.QdrantContextCandidateProvider.feature_id == FEATURE_ID
    assert module.GraphitiContextCandidateProvider.feature_id == FEATURE_ID


def test_context_building_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "graphiti", "graphiti_core", "openai"):
        sys.modules.pop(module_name, None)

    importlib.import_module("infinity_context_adapters.features.context_building")

    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "graphiti" not in sys.modules
    assert "graphiti_core" not in sys.modules
    assert "openai" not in sys.modules


def test_context_building_adapter_imports_only_public_core_feature_api() -> None:
    violations: list[str] = []

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if imported == ALLOWED_CORE_FEATURE_IMPORT:
                continue
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


def test_in_memory_candidate_provider_maps_records_through_context_port() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.context_building"
    )
    source_ref = ContextSourceRef(
        source_type="document",
        source_id="doc-1",
        chunk_id="chunk-1",
    )
    provider = module.InMemoryContextCandidateProvider(
        records=(
            module.ContextCandidateRecord(
                item_id="other-scope",
                space_id="space-2",
                memory_scope_id="scope-1",
                text="Other scope",
                source_refs=(source_ref,),
                tags=("deploy",),
            ),
            module.ContextCandidateRecord(
                item_id="wrong-thread",
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-2",
                text="Wrong thread",
                source_refs=(source_ref,),
                priority=20,
                tags=("deploy",),
            ),
            module.ContextCandidateRecord(
                item_id="untagged",
                space_id="space-1",
                memory_scope_id="scope-1",
                text="No matching tag",
                source_refs=(source_ref,),
                priority=10,
                tags=("other",),
            ),
            module.ContextCandidateRecord(
                item_id="thread",
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-1",
                text="Run the deploy dry-run first.",
                source_refs=(source_ref,),
                priority=5,
                score=0.7,
                estimated_tokens=4,
                tags=("deploy",),
            ),
            module.ContextCandidateRecord(
                item_id="scope",
                space_id="space-1",
                memory_scope_id="scope-1",
                text="Production deploys require source evidence.",
                source_refs=(source_ref,),
                priority=3,
                score=0.9,
                tags=("deploy",),
            ),
        )
    )
    request = _request(limit=5, tags=("deploy",))

    items = asyncio.run(provider.find_candidates(request))

    assert tuple(item.item_id for item in items) == ("thread", "scope")
    assert all(isinstance(item, ContextItem) for item in items)
    assert items[0].evidence[0].source_refs == (source_ref,)
    assert items[0].evidence[0].trust_level == "untrusted"


def test_in_memory_provider_can_drive_core_build_context_handler() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.context_building"
    )
    source_ref = ContextSourceRef(
        source_type="document",
        source_id="doc-1",
        chunk_id="chunk-1",
    )
    provider = module.create_in_memory_context_candidate_provider(
        (
            module.ContextCandidateRecord(
                item_id="selected",
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-1",
                text="The release plan requires a dry run.",
                source_refs=(source_ref,),
                estimated_tokens=5,
            ),
        )
    )
    handler = BuildContextHandler(candidate_provider=provider)

    result = asyncio.run(
        handler.execute(
            BuildContextQuery(
                query=_query(),
                budget=ContextBudget(
                    max_prompt_tokens=12,
                    reserved_response_tokens=4,
                ),
            )
        )
    )

    assert tuple(item.item_id for item in result.bundle.items) == ("selected",)
    assert "Memory evidence (untrusted)" in result.bundle.rendered_evidence
    assert "sources=document:doc-1#chunk-1" in result.bundle.rendered_evidence


def test_candidate_provider_chain_deduplicates_and_respects_limit() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.context_building"
    )
    first = _StaticProvider(
        (
            _item(module, "duplicate"),
            _item(module, "first-only"),
        )
    )
    second = _StaticProvider(
        (
            _item(module, "duplicate"),
            _item(module, "second-only"),
        )
    )
    chain = module.ContextCandidateProviderChain(providers=(first, second))

    items = asyncio.run(chain.find_candidates(_request(limit=3)))

    assert tuple(item.item_id for item in items) == (
        "duplicate",
        "first-only",
        "second-only",
    )
    assert first.requested_limits == [3]
    assert second.requested_limits == [3]


def test_placeholder_candidate_providers_are_explicit_deferred_seams() -> None:
    request = _request()
    placeholders = (
        (
            "postgres_candidate_provider",
            "PostgresContextCandidateProvider",
            "create_postgres_context_candidate_provider",
            "canonical query wiring is deferred",
        ),
        (
            "qdrant_candidate_provider",
            "QdrantContextCandidateProvider",
            "create_qdrant_context_candidate_provider",
            "Qdrant RAG wiring is deferred",
        ),
        (
            "graphiti_candidate_provider",
            "GraphitiContextCandidateProvider",
            "create_graphiti_context_candidate_provider",
            "Graphiti graph recall wiring is deferred",
        ),
    )

    for module_name, class_name, factory_name, message in placeholders:
        module = importlib.import_module(
            f"infinity_context_adapters.features.context_building.{module_name}"
        )
        provider = getattr(module, class_name)()
        factory_provider = getattr(module, factory_name)()

        assert provider.feature_id == FEATURE_ID
        assert factory_provider.feature_id == FEATURE_ID
        with pytest.raises(NotImplementedError, match=message):
            asyncio.run(provider.find_candidates(request))


class _StaticProvider:
    def __init__(self, items: tuple[ContextItem, ...]) -> None:
        self._items = items
        self.requested_limits: list[int] = []

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        self.requested_limits.append(request.limit)
        return self._items[: request.limit]


def _item(module: object, item_id: str) -> ContextItem:
    record = module.ContextCandidateRecord(
        item_id=item_id,
        space_id="space-1",
        memory_scope_id="scope-1",
        text=f"Evidence for {item_id}",
        source_refs=(
            ContextSourceRef(source_type="document", source_id=f"doc-{item_id}"),
        ),
    )
    return record.to_context_item()


def _request(
    *,
    limit: int = 20,
    tags: tuple[str, ...] = (),
) -> ContextCandidateRequest:
    return ContextCandidateRequest(query=_query(tags=tags), limit=limit)


def _query(tags: tuple[str, ...] = ()) -> ContextQuery:
    return ContextQuery(
        scope=ContextScope(
            space_id="space-1",
            memory_scope_id="scope-1",
            thread_id="thread-1",
        ),
        text="How should we deploy?",
        tags=tags,
    )


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _matches_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)
