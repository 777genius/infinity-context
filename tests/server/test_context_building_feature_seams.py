from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    ContextBudgetDto,
)
import infinity_context_core.features.context_building.public as context_building
from infinity_context_server.features.context_building import public as server_public
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "context_building"
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
    app = FastAPI()
    app.include_router(server_public.create_context_building_router(use_cases), prefix="/v1")
    client = TestClient(app)

    response = client.post(
        "/v1/context",
        json={
            "query": "What owns canonical lifecycle?",
            "space_id": "space_1",
            "memory_scope_id": "scope_1",
            "thread_id": "thread_1",
            "budget": {
                "max_context_tokens": 1200,
                "reserved_response_tokens": 200,
                "max_items": 4,
            },
            "tags": ["architecture"],
        },
    )

    assert response.status_code == 200
    assert len(recorder.queries) == 1
    assert recorder.queries[0].query.scope.memory_scope_id == "scope_1"
    assert recorder.queries[0].candidate_limit == 4

    body = response.json()
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
    assert item["evidence"][0] == {
        "source_type": "document",
        "source_id": "doc_1",
        "fact_id": None,
        "document_id": "doc_1",
        "chunk_id": "chunk_1",
        "quote_preview": "Postgres owns canonical lifecycle.",
        "score": 0.97,
        "trust_level": "high",
        "metadata": {
            "evidence_id": "ev_1",
            "confidence": "high",
            "temporal_label": None,
            "char_start": 0,
            "char_end": 37,
            "occurred_at": None,
        },
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
            if imported.startswith("infinity_context_core.features."):
                if not imported.endswith(".public"):
                    violations.append(f"{rel}: imports {imported}")
            if imported == "infinity_context_core" or any(
                imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes
            ):
                violations.append(f"{rel}: imports {imported}")
            elif imported in forbidden_prefixes:
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
