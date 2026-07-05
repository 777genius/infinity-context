from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as context_building
import pytest
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    ContextBudgetDto,
)
from infinity_context_server.api.v1 import context as legacy_context_api
from infinity_context_server.features.context_building import public as server_public

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "context_building"
)
LEGACY_CONTEXT_API = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "context.py"
)


class RecordingBuildContext:
    def __init__(self) -> None:
        self.queries: list[context_building.BuildContextQuery] = []

    async def execute(
        self,
        query: context_building.BuildContextQuery,
    ) -> context_building.BuildContextResult:
        self.queries.append(query)
        source_ref = context_building.ContextSourceRef(
            source_type="document",
            source_id="doc_1",
            document_id="doc_1",
            chunk_id="chunk_1",
            char_start=0,
            char_end=37,
            quote_preview="Postgres owns canonical lifecycle.",
        )
        evidence = context_building.ContextEvidence(
            text="Postgres owns canonical lifecycle.",
            source_refs=(source_ref,),
            evidence_id="ev_1",
            trust_level="high",
            confidence="high",
            relevance_score=0.97,
        )
        item = context_building.ContextItem(
            item_id="ctx_1",
            text="Postgres owns canonical lifecycle.",
            kind="document_chunk",
            evidence=(evidence,),
            priority=5,
            score=0.97,
            estimated_tokens=8,
            tags=("architecture",),
        )
        dropped = context_building.ContextDroppedItem(
            item_id="ctx_2",
            reason="budget_exhausted",
            estimated_tokens=120,
        )
        bundle = context_building.ContextBundle(
            query=query.query,
            items=(item,),
            dropped_items=(dropped,),
            rendered_evidence="[1] Postgres owns canonical lifecycle.",
            max_prompt_tokens=query.budget.max_prompt_tokens,
            total_estimated_tokens=8,
        )
        return context_building.BuildContextResult(bundle=bundle)


def test_context_building_server_feature_public_surface_composes_router() -> None:
    recorder = RecordingBuildContext()
    feature = server_public.build_context_building_server_feature(
        context_building.ContextBuildingUseCases(build_context=recorder),
        route_prefix="/context-building",
    )

    assert feature.feature_id == "context_building"
    assert server_public.__all__ == (
        "BuildContextHttpRequest",
        "ContextBudgetHttpRequest",
        "ContextBuildingServerFeature",
        "FEATURE_ID",
        "build_context_building_server_feature",
        "build_context_query_from_contract",
        "build_context_result_to_contract",
        "create_context_building_router",
    )
    assert server_public.FEATURE_ID == "context_building"
    assert {route.path for route in feature.create_router().routes} == {
        "/context-building/context"
    }


def test_context_building_mapper_builds_feature_public_application_query() -> None:
    request = BuildContextRequestDto(
        query="What owns canonical lifecycle?",
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        budget=ContextBudgetDto(
            max_context_tokens=1200,
            reserved_response_tokens=200,
            max_items=4,
        ),
        tags=("architecture", " "),
    )

    query = server_public.build_context_query_from_contract(request)

    assert isinstance(query, context_building.BuildContextQuery)
    assert query.query.scope.space_id == "space_1"
    assert query.query.scope.memory_scope_id == "scope_1"
    assert query.query.scope.thread_id == "thread_1"
    assert query.query.text == "What owns canonical lifecycle?"
    assert query.query.tags == ("architecture",)
    assert query.budget.max_prompt_tokens == 1200
    assert query.budget.reserved_response_tokens == 200
    assert query.budget.available_evidence_tokens == 1000
    assert query.candidate_limit == 4


def test_context_building_mapper_requires_resolved_scope_ids() -> None:
    request = BuildContextRequestDto(
        query="What owns canonical lifecycle?",
        space_slug="client-app",
        memory_scope_external_ref="default",
    )

    with pytest.raises(ValueError, match="space_id is required"):
        server_public.build_context_query_from_contract(request)


def test_context_building_route_maps_http_contract_to_feature_use_case() -> None:
    recorder = RecordingBuildContext()
    use_cases = context_building.ContextBuildingUseCases(build_context=recorder)
    router = server_public.create_context_building_router(use_cases)
    endpoint = next(
        route.endpoint for route in router.routes if getattr(route, "path", None) == "/context"
    )
    response = asyncio.run(
        endpoint(
            server_public.BuildContextHttpRequest(
                query="What owns canonical lifecycle?",
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                budget=server_public.ContextBudgetHttpRequest(
                    max_context_tokens=1200,
                    reserved_response_tokens=200,
                    max_items=4,
                ),
                tags=["architecture"],
            )
        )
    )

    assert len(recorder.queries) == 1
    assert recorder.queries[0].query.scope.memory_scope_id == "scope_1"
    assert recorder.queries[0].candidate_limit == 4

    body = response
    assert body["data"]["rendered_context"] == "[1] Postgres owns canonical lifecycle."
    assert body["data"]["budget"]["max_context_tokens"] == 1200
    assert body["data"]["total_tokens"] == 8
    assert body["data"]["diagnostics"] == {
        "feature_id": "context_building",
        "item_count": 1,
        "dropped_items": [
            {
                "id": "ctx_2",
                "reason": "budget_exhausted",
                "estimated_tokens": 120,
            }
        ],
    }
    item = body["data"]["items"][0]
    assert item["id"] == "ctx_1"
    assert item["kind"] == "document_chunk"
    assert item["trust_level"] == "high"
    evidence = item["evidence"][0]
    assert evidence["source_type"] == "document"
    assert evidence["source_id"] == "doc_1"
    assert evidence["fact_id"] is None
    assert evidence["document_id"] == "doc_1"
    assert evidence["chunk_id"] == "chunk_1"
    assert evidence["quote_preview"] == "Postgres owns canonical lifecycle."
    assert evidence["score"] == 0.97
    assert evidence["trust_level"] == "high"
    assert evidence["metadata"] == {
        "evidence_id": "ev_1",
        "confidence": "high",
        "temporal_label": None,
        "char_start": 0,
        "char_end": 37,
        "occurred_at": None,
    }


def test_context_building_server_slice_uses_only_public_feature_boundaries() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "infinity_context_adapters",
        "infinity_context_core.application",
        "infinity_context_core.domain",
        "infinity_context_core.ports",
        "infinity_context_server.api.v1.context",
        "infinity_context_server.composition",
        "graphiti",
        "openai",
        "qdrant_client",
        "sqlalchemy",
    )

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            rel = path.relative_to(REPO_ROOT)
            if imported.startswith(
                "infinity_context_core.features."
            ) and not imported.endswith(".public"):
                violations.append(f"{rel}: imports {imported}")
            if (
                imported == "infinity_context_core"
                or imported in forbidden_prefixes
                or any(
                    imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes
                )
            ):
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_legacy_context_api_uses_context_building_server_public_seam_only() -> None:
    source = LEGACY_CONTEXT_API.read_text(encoding="utf-8")
    assert (
        "from infinity_context_server.features.context_building "
        "import public as context_building_server"
    ) in source
    assert "context_building_server.build_context_query_from_contract" in source

    violations: list[str] = []
    for imported in _imports(LEGACY_CONTEXT_API):
        if imported.startswith("infinity_context_server.features.context_building."):
            violations.append(f"{LEGACY_CONTEXT_API.relative_to(REPO_ROOT)}: imports {imported}")
        if imported.startswith("infinity_context_core.features.context_building."):
            violations.append(f"{LEGACY_CONTEXT_API.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_legacy_context_query_builder_delegates_to_server_public_mapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[BuildContextRequestDto] = []
    original_mapper = legacy_context_api.context_building_server.build_context_query_from_contract

    def record_mapper(request: BuildContextRequestDto) -> context_building.BuildContextQuery:
        calls.append(request)
        return original_mapper(request)

    monkeypatch.setattr(
        legacy_context_api.context_building_server,
        "build_context_query_from_contract",
        record_mapper,
    )
    scope = SimpleNamespace(
        space_id="space_1",
        memory_scope_ids=("scope_1", "scope_2"),
        thread_id="thread_1",
    )
    request = legacy_context_api.ContextRequest(
        query="  keep the legacy query text  ",
        token_budget=777,
        max_facts=3,
        max_chunks=4,
        max_evidence_items=5,
        max_conflicting_suggestions=2,
        include_superseded=True,
        include_stale=True,
        category="Project Notes!",
        tags_any=[" Architecture ", " "],
        tags_all=["Core-Lite"],
        tags_none=["draft only"],
    )

    query = legacy_context_api._legacy_build_context_query_from_feature_seam(
        request,
        scope=scope,
        max_rendered_chars=1234,
    )

    assert len(calls) == 1
    assert calls[0].space_id == "space_1"
    assert calls[0].memory_scope_id == "scope_1"
    assert calls[0].thread_id == "thread_1"
    assert calls[0].budget is not None
    assert calls[0].budget.max_context_tokens == 777

    assert query.space_id == "space_1"
    assert query.memory_scope_ids == ("scope_1", "scope_2")
    assert query.thread_id == "thread_1"
    assert query.query == "  keep the legacy query text  "
    assert query.token_budget == 777
    assert query.max_rendered_chars == 1234
    assert query.max_facts == 3
    assert query.max_chunks == 4
    assert query.max_evidence_items == 5
    assert query.max_conflicting_suggestions == 2
    assert query.include_superseded is True
    assert query.include_stale is True
    assert query.category == "project_notes"
    assert query.tags_any == ("architecture",)
    assert query.tags_all == ("core-lite",)
    assert query.tags_none == ("draft_only",)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
