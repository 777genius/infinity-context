import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
)
from infinity_context_core.application import BuildContextQuery, BuildContextUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId
from infinity_context_sdk.context import context_bundle_from_response
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def test_context_expands_event_anchor_to_related_person_and_project(
    tmp_path: Path,
) -> None:
    with _make_client(tmp_path) as client:
        person = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "person",
                "label": "Alex",
                "confidence": "high",
                "metadata": {
                    "anchor_family": "person",
                    "canonical_key": "aleks",
                    "person_canonical_key": "aleks",
                },
                "evidence_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "person-alex-review",
                        "quote_preview": "Alex owns the launch review follow-up.",
                    }
                ],
            },
            headers=_auth_headers(),
        )
        project = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "project",
                "label": "Project Atlas",
                "aliases": ["Atlas"],
                "confidence": "high",
                "metadata": {
                    "anchor_family": "project",
                    "canonical_key": "atlas",
                    "project_canonical_key": "atlas",
                },
                "evidence_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "project-atlas-review",
                        "quote_preview": "Atlas is the project discussed in the launch review.",
                    }
                ],
            },
            headers=_auth_headers(),
        )
        event = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "event",
                "label": "Launch review",
                "confidence": "high",
                "metadata": {
                    "anchor_family": "event",
                    "event_type": "meeting",
                    "event_type_canonical": "meeting",
                    "event_participant_label": "Alex",
                    "event_participant_relation": "with",
                    "event_participant_canonical_key": "aleks",
                    "event_project_label": "Project Atlas",
                    "event_project_relation": "about",
                    "event_project_canonical_key": "atlas",
                    "event_temporal_phrase": "last week",
                    "event_temporal_hint_code": "last_week",
                    "event_identity_terms": ["meeting", "aleks", "atlas", "last_week:1:week"],
                },
                "evidence_refs": [
                    {
                        "source_type": "asset_extraction",
                        "source_id": "extract-launch-review",
                        "chunk_id": "transcript-launch-review",
                        "time_start_ms": 3000,
                        "time_end_ms": 12000,
                        "quote_preview": "Launch review happened last week.",
                    }
                ],
            },
            headers=_auth_headers(),
        )
        context = asyncio.run(_build_context(client, query="last week meeting"))

    assert person.status_code == 200, person.text
    assert project.status_code == 200, project.text
    assert event.status_code == 200, event.text
    anchor_texts = tuple(item.text for item in context.items if item.item_type == "anchor")
    assert any("event: Launch review" in text for text in anchor_texts)
    assert any("person: Alex" in text for text in anchor_texts)
    assert any("project: Project Atlas" in text for text in anchor_texts)
    related_items = [
        item
        for item in context.items
        if (item.diagnostics or {}).get("retrieval_source") == "canonical_anchor_relations"
    ]
    assert len(related_items) == 2
    assert {item.diagnostics["related_anchor_relation_type"] for item in related_items} == {
        "event_participant",
        "event_project",
    }
    assert context.diagnostics["anchor_relation_candidates_considered"] == 2
    assert context.diagnostics["anchor_relation_items_used"] == 2
    assert "canonical_anchor_relations" in context.diagnostics["retrieval_sources_used"]
    sdk_context = context_bundle_from_response(
        {
            "data": {
                "bundle_id": context.bundle_id,
                "rendered_text": context.rendered_text,
                "items": [],
                "diagnostics": context.diagnostics,
            }
        }
    )
    assert sdk_context.diagnostics.anchor_relation_candidates_considered == 2
    assert sdk_context.diagnostics.anchor_relation_items_used == 2


async def _build_context(client: TestClient, *, query: str):
    container = client.app.state.container
    use_case = BuildContextUseCase(
        uow_factory=container.uow_factory,
        ids=container.ids,
        vector_index=NoopVectorMemoryAdapter(),
        graph_index=NoopGraphMemoryAdapter(),
        embedder=NoopEmbeddingAdapter(),
    )
    return await use_case.execute(
        BuildContextQuery(
            space_id=SpaceId("space_client_app"),
            memory_scope_ids=(MemoryScopeId("memory_scope_default"),),
            query=query,
            token_budget=900,
        )
    )


def _make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}
