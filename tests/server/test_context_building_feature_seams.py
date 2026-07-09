from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import infinity_context_core.features.context_building.public as context_building
import pytest
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    ContextBudgetDto,
)
from infinity_context_server.features.context_building import public as server_public

MemoryInsightsResponseMapper = server_public.LegacyMemoryInsightsApiResponseMapper
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
LEGACY_DIGEST_API = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "digest.py"
)
LEGACY_INSIGHTS_API = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "insights.py"
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
        "BenchmarkContextRequest",
        "BuildContextHttpRequest",
        "ContextBudgetHttpRequest",
        "ContextRequest",
        "DigestRequest",
        "MemoryInsightsHttpRequest",
        "ContextBuildingServerFeature",
        "FEATURE_ID",
        "LegacyContextApiResponseMapper",
        "LegacyDigestApiResponseMapper",
        "LegacyMemoryInsightsApiResponseMapper",
        "build_context_building_server_feature",
        "build_context_query_from_contract",
        "build_context_result_to_contract",
        "build_legacy_context_query_from_request",
        "build_legacy_digest_query_from_request",
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


def test_context_building_public_seam_exports_memory_insights_http_request() -> None:
    request = server_public.MemoryInsightsHttpRequest(
        space_slug="client-app",
        memory_scope_external_refs=["default"],
        thread_external_ref="thread-1",
        max_activity=7,
    )

    assert request.space_id is None
    assert request.memory_scope_external_refs == ["default"]
    assert request.max_facts == 200
    assert request.max_activity == 7


def test_context_building_legacy_response_mapper_shapes_context_and_search_payloads() -> None:
    mapper = _legacy_response_mapper_for_tests()
    source_ref = SimpleNamespace(
        source_type="document",
        source_id="doc_1",
        chunk_id="chunk_1",
        char_start=0,
        char_end=37,
        quote_preview="Postgres owns canonical lifecycle.",
        page_number=None,
        time_start_ms=None,
        time_end_ms=None,
        bbox=None,
    )
    item = SimpleNamespace(
        item_id="ctx 1",
        item_type="document chunk",
        text="Postgres owns canonical lifecycle.",
        score=0.97,
        source_refs=(source_ref,),
        is_instruction=False,
        diagnostics={
            "memory_scope_id": "scope_1",
            "retrieval_source": "keyword_chunks",
            "evidence_kind": "source_quote",
            "evidence_confidence": 0.9,
        },
    )
    bundle = SimpleNamespace(
        bundle_id="bundle_1",
        rendered_text="[1] Postgres owns canonical lifecycle.",
        items=(item,),
        diagnostics={"items_used": 1},
    )

    context_response = mapper.context_response_from_bundle(
        bundle,
        request_id="req_context",
    )
    search_response = mapper.search_response_from_bundle(
        bundle,
        request_id="req_search",
    )
    disabled_search = mapper.empty_search_response(
        policy_mode="disabled",
        request_id="req_disabled",
        consistency_mode="best_effort",
        include_answer_support=False,
    )

    context_data = context_response["data"]
    assert context_data["bundle_id"] == "bundle_1"
    assert context_data["rendered_text"] == "[1] Postgres owns canonical lifecycle."
    assert context_data["items"][0]["source_refs"][0]["quote_preview"] == (
        "Postgres owns canonical lifecycle."
    )
    assert context_data["items"][0]["citations"][0]["citation_id"] == (
        "document_chunk:ctx_1:citation:1"
    )
    assert context_data["items"][0]["citations"][0]["char_range"] == {
        "start": 0,
        "end": 37,
    }
    assert context_data["top_evidence"][0]["reasons"] == [
        "high_context_score",
        "retrieved_by:keyword_chunks",
        "quote_preview",
        "kind:source_quote",
    ]
    assert context_data["answer_support"]["status"] == "strong"
    assert context_data["diagnostics"]["source_refs_total"] == 1
    assert context_data["diagnostics"]["answer_support_cited_count"] == 1

    assert search_response["data"]["next_cursor"] is None
    assert search_response["data"]["items"] == context_data["items"]
    assert "answer_support" not in disabled_search["data"]


def test_context_building_legacy_digest_mapper_shapes_digest_payloads() -> None:
    mapper = _legacy_digest_response_mapper_for_tests()
    source_ref = SimpleNamespace(
        source_type="document",
        source_id="doc_1",
        chunk_id="chunk_1",
        char_start=0,
        char_end=37,
        quote_preview="Postgres owns canonical lifecycle.",
        page_number=2,
        time_start_ms=None,
        time_end_ms=None,
        bbox=None,
    )
    item = SimpleNamespace(
        item_id="ctx 1",
        item_type="document chunk",
        text="Postgres owns canonical lifecycle.",
        score=0.97,
        source_refs=(source_ref,),
        is_instruction=False,
        diagnostics={
            "memory_scope_id": "scope_1",
            "retrieval_source": "keyword_chunks",
            "evidence_kind": "source_quote",
            "evidence_confidence": 0.9,
        },
    )
    digest = SimpleNamespace(
        digest_id="dig_1",
        topic="Canonical lifecycle",
        rendered_markdown="# Active facts",
        sections=(
            SimpleNamespace(
                title="Active facts",
                items=(item,),
                truncated=False,
            ),
        ),
        source_refs=(source_ref,),
        token_estimate=64,
        diagnostics={
            "evidence_only": True,
            "context_items_used": 1,
            "provider_response": "not public",
        },
    )

    response = mapper.digest_to_response(digest)
    disabled_response = mapper.empty_digest_response(
        topic="Canonical lifecycle",
        policy_mode="disabled",
        request_id="req_disabled",
    )
    scope_not_found_response = mapper.empty_digest_response(
        topic="Canonical lifecycle",
        policy_mode="enabled",
        request_id="req_missing",
        scope_not_found=True,
    )

    assert response["digest_id"] == "dig_1"
    assert response["topic"] == "Canonical lifecycle"
    assert response["rendered_markdown"] == "# Active facts"
    assert response["sections"][0]["title"] == "Active facts"
    assert response["sections"][0]["truncated"] is False
    assert response["sections"][0]["items"][0]["item_id"] == "ctx 1"
    assert response["sections"][0]["items"][0]["citations"][0]["citation_id"] == (
        "document_chunk:ctx_1:citation:1"
    )
    assert response["source_refs"][0]["page_number"] == 2
    assert response["token_estimate"] == 64
    assert response["diagnostics"]["evidence_only"] is True
    assert response["diagnostics"]["context_items_used"] == 1
    assert response["diagnostics"]["provider_response"] == "not public"
    assert disabled_response["meta"]["request_id"] == "req_disabled"
    assert disabled_response["data"]["digest_id"] == "dig_disabled"
    assert disabled_response["data"]["diagnostics"]["retrieval_disabled"] is True
    assert scope_not_found_response["data"]["digest_id"] == "dig_scope_not_found"
    assert scope_not_found_response["data"]["diagnostics"]["scope_not_found"] is True


def test_context_building_legacy_insights_mapper_shapes_insights_payloads() -> None:
    mapper = _legacy_memory_insights_response_mapper_for_tests()
    insights = SimpleNamespace(
        insights_id="ins_1",
        generated_at=datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        scope={"space_id": "space_1", "memory_scope_ids": ("scope_1",)},
        health_score=87.5,
        metrics={"suggestions": {"pending": 1}},
        taxonomy={"top_tags": [{"value": "memory", "count": 2}]},
        action_items=(
            SimpleNamespace(
                id="mai_1",
                severity="warning",
                action="review_pending_suggestions",
                target_type="suggestion_queue",
                target_id=None,
                memory_scope_id="scope_1",
                reason="1 pending suggestions need review.",
                preview="Review pending memory.",
                metadata={"match_type": "pending_suggestion_count"},
            ),
        ),
        recent_activity=(
            SimpleNamespace(
                id="act_1",
                occurred_at=datetime(2026, 6, 7, 10, 1, tzinfo=UTC),
                event_type="suggestion_created",
                entity_type="suggestion",
                entity_id="sug_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                status="pending",
                preview="Review pending memory.",
                metadata={"source": "suggestion_queue"},
            ),
        ),
        consolidation_plan=(
            SimpleNamespace(
                id="mplan_1",
                plan_type="similar_fact_review",
                memory_scope_id="scope_1",
                confidence="medium",
                canonical_candidate_id="fact_1",
                candidate_fact_ids=("fact_2",),
                recommended_steps=("Inspect both facts and source refs.",),
                reason="Two active facts look similar.",
                preview="Infinity Context should use Graphiti.",
                metadata={"similarity": 0.84},
            ),
        ),
        diagnostics={"evidence_only": True, "read_only": True},
    )

    response = mapper.insights_response_from_result(insights, request_id="req_insights")
    disabled_response = mapper.empty_insights_response(
        request_id="req_disabled",
        policy_mode="disabled",
    )
    scope_not_found_response = mapper.empty_insights_response(
        request_id="req_missing",
        policy_mode="enabled",
        scope_not_found=True,
    )

    assert response["meta"]["request_id"] == "req_insights"
    assert response["data"]["generated_at"] == "2026-06-07T10:00:00+00:00"
    assert response["data"]["action_items"][0]["metadata"] == {
        "match_type": "pending_suggestion_count"
    }
    assert response["data"]["recent_activity"][0]["occurred_at"] == (
        "2026-06-07T10:01:00+00:00"
    )
    assert response["data"]["consolidation_plan"][0]["candidate_fact_ids"] == [
        "fact_2"
    ]
    assert disabled_response["meta"]["request_id"] == "req_disabled"
    assert disabled_response["data"]["insights_id"] == "ins_disabled"
    assert disabled_response["data"]["diagnostics"]["retrieval_disabled"] is True
    assert scope_not_found_response["data"]["insights_id"] == "ins_scope_not_found"
    assert scope_not_found_response["data"]["diagnostics"]["scope_not_found"] is True
    assert scope_not_found_response["data"]["diagnostics"]["retrieval_disabled"] is False


def _legacy_response_mapper_for_tests() -> server_public.LegacyContextApiResponseMapper:
    def normalize_context_diagnostics(diagnostics: object) -> dict[str, object]:
        return dict(diagnostics) if isinstance(diagnostics, dict) else {}

    def normalize_context_bundle_diagnostics(
        diagnostics: dict[str, Any],
        *,
        items: object,
    ) -> dict[str, object]:
        normalized = dict(diagnostics)
        normalized["items_used"] = len(tuple(items))
        normalized.setdefault("retrieval_sources_used", [])
        normalized.setdefault("hybrid_items_used", 0)
        normalized.setdefault("temporal_replacements_applied", 0)
        return normalized

    def safe_public_metadata(
        metadata: object,
        *,
        max_items: int = 260,
    ) -> dict[str, Any]:
        return dict(metadata) if isinstance(metadata, dict) else {}

    def safe_public_text(value: str, *, limit: int = 500) -> str:
        return str(value)[:limit]

    def source_ref_to_response(ref: object) -> dict[str, Any]:
        return {
            "source_type": safe_public_text(str(ref.source_type), limit=80),
            "source_id": safe_public_text(str(ref.source_id), limit=160),
            "chunk_id": ref.chunk_id,
            "char_start": ref.char_start,
            "char_end": ref.char_end,
            "quote_preview": ref.quote_preview,
            "page_number": ref.page_number,
            "time_start_ms": ref.time_start_ms,
            "time_end_ms": ref.time_end_ms,
            "bbox": ref.bbox,
        }

    return server_public.LegacyContextApiResponseMapper(
        normalize_context_diagnostics=normalize_context_diagnostics,
        normalize_context_bundle_diagnostics=normalize_context_bundle_diagnostics,
        safe_public_metadata=safe_public_metadata,
        safe_public_text=safe_public_text,
        source_ref_to_response=source_ref_to_response,
    )


def _legacy_digest_response_mapper_for_tests() -> server_public.LegacyDigestApiResponseMapper:
    def normalize_context_diagnostics(diagnostics: object) -> dict[str, object]:
        return dict(diagnostics) if isinstance(diagnostics, dict) else {}

    def safe_public_metadata(
        metadata: object,
        *,
        max_items: int = 260,
    ) -> dict[str, Any]:
        del max_items
        return dict(metadata) if isinstance(metadata, dict) else {}

    def safe_public_text(value: str, *, limit: int = 500) -> str:
        return str(value)[:limit]

    return server_public.LegacyDigestApiResponseMapper(
        normalize_context_diagnostics=normalize_context_diagnostics,
        safe_public_metadata=safe_public_metadata,
        safe_public_text=safe_public_text,
    )


def _legacy_memory_insights_response_mapper_for_tests() -> MemoryInsightsResponseMapper:
    def safe_public_metadata(
        metadata: object,
        *,
        max_items: int = 120,
    ) -> dict[str, Any]:
        del max_items
        return dict(metadata) if isinstance(metadata, dict) else {}

    return server_public.LegacyMemoryInsightsApiResponseMapper(
        safe_public_metadata=safe_public_metadata,
    )


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
            if path in {
                FEATURE_ROOT / "context_requests.py",
                FEATURE_ROOT / "digest_requests.py",
            } and imported == "infinity_context_core.application":
                continue
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
    assert "request: context_building_server.ContextRequest" in source
    assert "request: context_building_server.BenchmarkContextRequest" in source
    assert "context_building_server.build_legacy_context_query_from_request" in source
    assert "context_building_server.LegacyContextApiResponseMapper" in source
    assert (
        "return _LEGACY_CONTEXT_API_RESPONSES.context_item_to_response(item)"
    ) in source
    assert "class ContextRequest" not in source
    assert "class BenchmarkContextRequest" not in source
    assert "def _normalize_label(" not in source
    assert "def _normalize_tags(" not in source
    assert "def _source_ref_to_citation(" not in source
    assert "def _answer_support_coverage(" not in source
    assert "def _top_evidence_candidate(" not in source

    violations: list[str] = []
    for imported in _imports(LEGACY_CONTEXT_API):
        if imported.startswith("infinity_context_server.features.context_building."):
            violations.append(f"{LEGACY_CONTEXT_API.relative_to(REPO_ROOT)}: imports {imported}")
        if imported.startswith("infinity_context_core.features.context_building."):
            violations.append(f"{LEGACY_CONTEXT_API.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_legacy_digest_api_uses_context_building_server_public_seam_only() -> None:
    source = LEGACY_DIGEST_API.read_text(encoding="utf-8")
    assert (
        "from infinity_context_server.features.context_building "
        "import public as context_building_server"
    ) in source
    assert "request: context_building_server.DigestRequest" in source
    assert "context_building_server.LegacyDigestApiResponseMapper" in source
    assert "context_building_server.build_legacy_digest_query_from_request" in source
    assert "_LEGACY_DIGEST_API_RESPONSES.digest_to_response(digest)" in source
    assert "_LEGACY_DIGEST_API_RESPONSES.empty_digest_response" in source
    assert "class DigestRequest" not in source
    assert "BuildMemoryDigestQuery" not in source
    assert "def digest_to_response(" not in source
    assert "def _empty_digest_response(" not in source
    assert "def _digest_diagnostics_to_response(" not in source
    assert "def _digest_section_to_response(" not in source
    assert "def _digest_context_item_to_response(" not in source
    assert "def _digest_source_ref_to_response(" not in source
    assert "from infinity_context_server.api.v1.context import" not in source
    assert "from infinity_context_server.api.v1.source_refs import" not in source

    violations: list[str] = []
    for imported in _imports(LEGACY_DIGEST_API):
        if imported.startswith("infinity_context_server.features.context_building."):
            violations.append(f"{LEGACY_DIGEST_API.relative_to(REPO_ROOT)}: imports {imported}")
        if imported.startswith("infinity_context_core.features.context_building."):
            violations.append(f"{LEGACY_DIGEST_API.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_legacy_insights_api_uses_context_building_server_public_seam_only() -> None:
    source = LEGACY_INSIGHTS_API.read_text(encoding="utf-8")
    assert (
        "from infinity_context_server.features.context_building "
        "import public as context_building_server"
    ) in source
    assert "context_building_server.LegacyMemoryInsightsApiResponseMapper" in source
    assert "_LEGACY_MEMORY_INSIGHTS_API_RESPONSES.empty_insights_response" in source
    assert (
        "_LEGACY_MEMORY_INSIGHTS_API_RESPONSES.insights_response_from_result"
        in source
    )
    assert "context_building_server.MemoryInsightsHttpRequest" in source
    assert "class InsightsRequest" not in source
    assert "def insights_to_response(" not in source
    assert "def _empty_insights_response(" not in source
    assert "def _action_item_to_response(" not in source
    assert "def _activity_item_to_response(" not in source
    assert "def _consolidation_plan_item_to_response(" not in source
    assert "MemoryInsightActionItem" not in source
    assert "MemoryActivityItem" not in source
    assert "MemoryConsolidationPlanItem" not in source
    assert "MemoryInsightsResult" not in source

    violations: list[str] = []
    for imported in _imports(LEGACY_INSIGHTS_API):
        if imported.startswith("infinity_context_server.features.context_building."):
            violations.append(f"{LEGACY_INSIGHTS_API.relative_to(REPO_ROOT)}: imports {imported}")
        if imported.startswith("infinity_context_core.features.context_building."):
            violations.append(f"{LEGACY_INSIGHTS_API.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_legacy_context_query_builder_is_owned_by_server_public_seam() -> None:
    scope = SimpleNamespace(
        space_id="space_1",
        memory_scope_ids=("scope_1", "scope_2"),
        thread_id="thread_1",
    )
    request = server_public.ContextRequest(
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

    query = server_public.build_legacy_context_query_from_request(
        request,
        scope=scope,
        max_rendered_chars=1234,
    )

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


def test_legacy_digest_query_builder_is_owned_by_server_public_seam() -> None:
    scope = SimpleNamespace(
        space_id="space_1",
        memory_scope_ids=("scope_1", "scope_2"),
        thread_id="thread_1",
    )
    request = server_public.DigestRequest(
        topic="  keep the legacy digest topic  ",
        token_budget=777,
        max_facts=3,
        max_chunks=4,
        max_suggestions=5,
        include_pending_suggestions=False,
        include_superseded=True,
        include_related=False,
    )

    query = server_public.build_legacy_digest_query_from_request(
        request,
        scope=scope,
        max_rendered_chars=1234,
    )

    assert query.space_id == "space_1"
    assert query.memory_scope_ids == ("scope_1", "scope_2")
    assert query.thread_id == "thread_1"
    assert query.topic == "  keep the legacy digest topic  "
    assert query.token_budget == 777
    assert query.max_rendered_chars == 1234
    assert query.max_facts == 3
    assert query.max_chunks == 4
    assert query.max_suggestions == 5
    assert query.include_pending_suggestions is False
    assert query.include_superseded is True
    assert query.include_related is False


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
