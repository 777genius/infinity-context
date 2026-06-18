import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import MemoryOutboxRow, MemoryScopeRow, MemoryThreadRow
from memo_stack_core.domain.errors import MemoryConflictError
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_server.config import DeployProfile, MemoryPolicyMode, Settings
from memo_stack_server.main import create_app
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def make_client_with_settings(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-token"}
    if extra:
        headers.update(extra)
    return headers


def fact_payload(text: str = "Postgres is canonical truth.") -> dict[str, Any]:
    return {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "text": text,
        "kind": "architecture_decision",
        "source_refs": [
            {
                "source_type": "manual",
                "source_id": "manual_1",
                "quote_preview": "Postgres canonical truth",
            }
        ],
    }


async def outbox_count(client: TestClient) -> int:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        return int(await session.scalar(select(func.count()).select_from(MemoryOutboxRow)))


async def mark_scope_rows_deleted(
    client: TestClient,
    *,
    memory_scope_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        if memory_scope_id:
            memory_scope = await session.get(MemoryScopeRow, memory_scope_id)
            assert memory_scope is not None
            memory_scope.status = "deleted"
        if thread_id:
            thread = await session.get(MemoryThreadRow, thread_id)
            assert thread is not None
            thread.status = "deleted"
        await session.commit()


def test_remember_fact_requires_auth(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/v1/facts", json=fact_payload())

    assert response.status_code == 401


def test_source_preview_is_bounded_at_api_boundary(tmp_path: Path) -> None:
    payload = fact_payload()
    payload["source_refs"][0]["quote_preview"] = "x" * 241

    with make_client(tmp_path) as client:
        response = client.post("/v1/facts", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "memory.validation"


def test_remember_fact_idempotency_and_outbox(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = auth_headers({"Idempotency-Key": "fact-1"})
        created = client.post("/v1/facts", json=fact_payload(), headers=headers)
        repeated = client.post("/v1/facts", json=fact_payload(), headers=headers)
        count = asyncio.run(outbox_count(client))

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.json()["data"]["id"] == repeated.json()["data"]["id"]
    assert created.json()["data"]["version"] == 1
    assert count == 1


def test_remember_and_list_fact_support_external_scope_refs(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "thread_external_ref": "session-1",
                "text": "MCP facts can be written through external scope refs.",
                "kind": "architecture_decision",
                "source_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "external-scope-test",
                    }
                ],
            },
            headers=auth_headers({"Idempotency-Key": "external-scope-fact"}),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "status": "active",
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == created.json()["data"]["id"]
    assert listed.json()["data"][0]["thread_id"] is not None


def test_fact_multimodal_source_refs_survive_persistence_and_context(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                **fact_payload("MULTIMODAL_FACT_MARKER: Alex approved launch."),
                "source_refs": [
                    {
                        "source_type": "asset_extraction",
                        "source_id": "extract_1",
                        "chunk_id": "chunk_1",
                        "quote_preview": "Alex approved launch",
                        "page_number": 2,
                        "time_start_ms": 1000,
                        "time_end_ms": 1500,
                        "bbox": [0, 1, 120, 40],
                    }
                ],
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "MULTIMODAL_FACT_MARKER Alex approved launch",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201, created.text
    assert listed.status_code == 200, listed.text
    listed_fact = next(
        item for item in listed.json()["data"] if item["id"] == created.json()["data"]["id"]
    )
    listed_ref = listed_fact["source_refs"][0]
    assert listed_ref["page_number"] == 2
    assert listed_ref["time_start_ms"] == 1000
    assert listed_ref["time_end_ms"] == 1500
    assert listed_ref["bbox"] == [0.0, 1.0, 120.0, 40.0]

    assert context.status_code == 200, context.text
    context_fact = next(
        item for item in context.json()["data"]["items"] if item["item_id"] == listed_fact["id"]
    )
    context_ref = context_fact["source_refs"][0]
    assert context_ref["page_number"] == 2
    assert context_ref["time_start_ms"] == 1000
    assert context_ref["time_end_ms"] == 1500
    assert context_ref["bbox"] == [0.0, 1.0, 120.0, 40.0]
    context_diagnostics = context_fact["diagnostics"]
    assert context_diagnostics["retrieval_sources"] == ["postgres_facts"]
    assert context_diagnostics["retrieval_sources_total"] == 1
    assert context_diagnostics["retrieval_sources_returned"] == 1
    assert context_diagnostics["retrieval_sources_truncated"] is False
    assert context_diagnostics["source_refs_total"] == 1
    assert context_diagnostics["source_refs_returned"] == 1
    assert context_diagnostics["source_refs_truncated"] is False
    assert (
        context_diagnostics["ranking_reason"]
        == "canonical active fact matched query and filters"
    )
    assert context.json()["data"]["diagnostics"]["source_refs_with_bbox_count"] >= 1


def test_read_routes_do_not_create_missing_external_scope(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        before_spaces = client.get("/v1/spaces", headers=auth_headers())
        facts = client.get(
            "/v1/facts",
            params={
                "space_slug": "missing-read-space",
                "memory_scope_external_ref": "missing-memory_scope",
            },
            headers=auth_headers(),
        )
        suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "missing-read-space",
                "memory_scope_external_ref": "missing-memory_scope",
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_slug": "missing-read-space",
                "memory_scope_external_ref": "missing-memory_scope",
                "query": "nothing should be created",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        search = client.post(
            "/v1/search",
            json={
                "space_slug": "missing-read-space",
                "memory_scope_external_ref": "missing-memory_scope",
                "query": "nothing should be created",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        after_spaces = client.get("/v1/spaces", headers=auth_headers())

    assert before_spaces.status_code == 200
    assert before_spaces.json()["data"] == []
    assert facts.status_code == 200
    assert facts.json() == {"data": [], "next_cursor": None}
    assert suggestions.status_code == 200
    assert suggestions.json() == {"data": []}
    assert context.status_code == 200
    assert context.json()["data"]["rendered_text"] == ""
    context_diagnostics = context.json()["data"]["diagnostics"]
    assert context_diagnostics["scope_not_found"] is True
    assert context_diagnostics["context_assembly_version"] == "context-v2-hybrid-explainable"
    assert context_diagnostics["retrieval_sources_used"] == []
    assert context_diagnostics["hybrid_items_used"] == 0
    assert context_diagnostics["temporal_replacements_applied"] == 0
    assert context_diagnostics["vector_status"] == "skipped"
    assert context_diagnostics["vector_skip_reason"] == "scope_not_found"
    assert search.status_code == 200
    assert search.json()["data"]["items"] == []
    search_diagnostics = search.json()["data"]["diagnostics"]
    assert search_diagnostics["scope_not_found"] is True
    assert search_diagnostics["context_assembly_version"] == "context-v2-hybrid-explainable"
    assert search_diagnostics["retrieval_sources_used"] == []
    assert search_diagnostics["hybrid_items_used"] == 0
    assert search_diagnostics["temporal_replacements_applied"] == 0
    assert search_diagnostics["graph_status"] == "skipped"
    assert search_diagnostics["graph_skip_reason"] == "scope_not_found"
    assert after_spaces.status_code == 200
    assert after_spaces.json()["data"] == []


def test_same_idempotency_key_different_body_conflicts(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = auth_headers({"Idempotency-Key": "fact-1"})
        created = client.post("/v1/facts", json=fact_payload(), headers=headers)
        conflict = client.post(
            "/v1/facts",
            json=fact_payload("Qdrant is a derived index."),
            headers=headers,
        )

    assert created.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "memory.conflict"


def test_same_idempotency_key_is_memory_scope_scoped(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = auth_headers({"Idempotency-Key": "memory_scope-scoped-fact-key"})
        default = client.post(
            "/v1/facts",
            json=fact_payload("MEMORY_SCOPE_IDEMPOTENCY_MARKER belongs to default."),
            headers=headers,
        )
        secondary = client.post(
            "/v1/facts",
            json={
                **fact_payload("MEMORY_SCOPE_IDEMPOTENCY_MARKER belongs to default."),
                "memory_scope_id": "memory_scope_secondary",
            },
            headers=headers,
        )

    assert default.status_code == 201
    assert secondary.status_code == 201
    assert default.json()["data"]["id"] != secondary.json()["data"]["id"]
    assert default.json()["data"]["memory_scope_id"] == "memory_scope_default"
    assert secondary.json()["data"]["memory_scope_id"] == "memory_scope_secondary"


def test_idempotency_unique_violation_maps_to_domain_conflict(tmp_path: Path) -> None:
    async def run(client: TestClient) -> str:
        container = client.app.state.container
        try:
            async with container.uow_factory() as uow:
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id="space_client_app",
                        key="duplicate-commit",
                        fingerprint="first",
                        result_type="fact",
                        result_id="fact_first",
                    )
                )
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id="space_client_app",
                        key="duplicate-commit",
                        fingerprint="second",
                        result_type="fact",
                        result_id="fact_second",
                    )
                )
                await uow.commit()
        except MemoryConflictError as exc:
            return exc.code
        raise AssertionError("Expected duplicate idempotency commit to raise MemoryConflictError")

    with make_client(tmp_path) as client:
        code = asyncio.run(run(client))

    assert code == "memory.conflict"


def test_update_requires_expected_version_and_forget_hides_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        fact_id = created.json()["data"]["id"]

        stale = client.patch(
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": 2,
                "text": "Postgres remains canonical truth.",
                "reason": "Correction",
                "source_refs": [{"source_type": "manual", "source_id": "manual_2"}],
            },
            headers=auth_headers(),
        )
        updated = client.patch(
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": 1,
                "text": "Postgres remains canonical truth.",
                "reason": "Correction",
                "source_refs": [{"source_type": "manual", "source_id": "manual_2"}],
            },
            headers=auth_headers(),
        )
        deleted = client.delete(f"/v1/facts/{fact_id}", headers=auth_headers())
        versions = client.get(f"/v1/facts/{fact_id}/versions", headers=auth_headers())
        count = asyncio.run(outbox_count(client))

    assert stale.status_code == 409
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["data"]] == [1, 2, 3]
    assert count == 3


def test_repeated_forget_does_not_enqueue_duplicate_projection_delete(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        fact_id = created.json()["data"]["id"]
        first_delete = client.delete(f"/v1/facts/{fact_id}", headers=auth_headers())
        second_delete = client.delete(f"/v1/facts/{fact_id}", headers=auth_headers())
        count = asyncio.run(outbox_count(client))

    assert created.status_code == 201
    assert first_delete.status_code == 200
    assert first_delete.json()["data"]["indexing_status"] == "pending"
    assert second_delete.status_code == 200
    assert second_delete.json()["data"]["indexing_status"] == "already_deleted"
    assert second_delete.json()["data"]["version"] == first_delete.json()["data"]["version"]
    assert count == 2


def test_fact_update_context_only_renders_current_version(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json=fact_payload("FACT_UPDATE_OLD_MARKER: use pgvector for memory retrieval."),
            headers=auth_headers(),
        )
        fact_id = created.json()["data"]["id"]

        before = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "memory retrieval",
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        updated = client.patch(
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": 1,
                "text": "FACT_UPDATE_NEW_MARKER: use Qdrant for memory retrieval.",
                "reason": "Correct retrieval engine",
                "source_refs": [{"source_type": "manual", "source_id": "manual_update"}],
            },
            headers=auth_headers(),
        )
        after = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "memory retrieval pgvector Qdrant",
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        versions = client.get(f"/v1/facts/{fact_id}/versions", headers=auth_headers())

    assert created.status_code == 201
    assert before.status_code == 200
    assert "FACT_UPDATE_OLD_MARKER" in before.json()["data"]["rendered_text"]
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2
    assert after.status_code == 200
    rendered_after = after.json()["data"]["rendered_text"]
    assert "FACT_UPDATE_NEW_MARKER" in rendered_after
    assert "FACT_UPDATE_OLD_MARKER" not in rendered_after
    version_texts = [item["text"] for item in versions.json()["data"]]
    assert any("FACT_UPDATE_OLD_MARKER" in text for text in version_texts)
    assert any("FACT_UPDATE_NEW_MARKER" in text for text in version_texts)


def test_related_facts_returns_explainable_same_scope_neighbors(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        target = client.post(
            "/v1/facts",
            json={
                "space_slug": "related-space",
                "memory_scope_external_ref": "backend",
                "thread_external_ref": "thread-a",
                "text": "RELATED_TARGET: Graphiti stores temporal memory edges.",
                "kind": "architecture_decision",
                "category": "architecture",
                "tags": ["graph", "memory"],
                "source_refs": [
                    {
                        "source_type": "document",
                        "source_id": "adr-1",
                        "chunk_id": "chunk-a",
                    }
                ],
            },
            headers=auth_headers(),
        )
        same_thread = client.post(
            "/v1/facts",
            json={
                "space_slug": "related-space",
                "memory_scope_external_ref": "backend",
                "thread_external_ref": "thread-a",
                "text": "RELATED_SAME_THREAD: Qdrant handles memory vector recall.",
                "kind": "architecture_decision",
                "category": "architecture",
                "tags": ["memory"],
                "source_refs": [
                    {
                        "source_type": "document",
                        "source_id": "adr-1",
                        "chunk_id": "chunk-a",
                    }
                ],
            },
            headers=auth_headers(),
        )
        memory_scope_wide = client.post(
            "/v1/facts",
            json={
                "space_slug": "related-space",
                "memory_scope_external_ref": "backend",
                "text": "RELATED_MEMORY_SCOPE_WIDE: Postgres remains canonical memory truth.",
                "kind": "architecture_decision",
                "category": "architecture",
                "tags": ["memory"],
                "source_refs": [{"source_type": "manual", "source_id": "memory_scope-wide"}],
            },
            headers=auth_headers(),
        )
        other_thread = client.post(
            "/v1/facts",
            json={
                "space_slug": "related-space",
                "memory_scope_external_ref": "backend",
                "thread_external_ref": "thread-b",
                "text": "RELATED_OTHER_THREAD: should require explicit opt-in.",
                "kind": "architecture_decision",
                "category": "architecture",
                "tags": ["memory"],
                "source_refs": [{"source_type": "document", "source_id": "adr-1"}],
            },
            headers=auth_headers(),
        )
        client.post(
            "/v1/facts",
            json={
                "space_slug": "related-space",
                "memory_scope_external_ref": "backend",
                "text": "RELATED_RESTRICTED: should not appear in related facts.",
                "kind": "architecture_decision",
                "classification": "restricted",
                "category": "architecture",
                "tags": ["memory"],
                "source_refs": [{"source_type": "document", "source_id": "adr-1"}],
            },
            headers=auth_headers(),
        )

        default = client.get(
            f"/v1/facts/{target.json()['data']['id']}/related",
            headers=auth_headers(),
        )
        expanded = client.get(
            f"/v1/facts/{target.json()['data']['id']}/related",
            params={"include_other_threads": True},
            headers=auth_headers(),
        )

    assert target.status_code == 201
    assert default.status_code == 200
    default_items = default.json()["data"]["items"]
    default_ids = {item["id"] for item in default_items}
    assert same_thread.json()["data"]["id"] in default_ids
    assert memory_scope_wide.json()["data"]["id"] in default_ids
    assert other_thread.json()["data"]["id"] not in default_ids
    assert default_items[0]["relation_reasons"][0] == "shared_source_chunk"
    assert default.json()["data"]["diagnostics"]["include_other_threads"] is False

    expanded_ids = {item["id"] for item in expanded.json()["data"]["items"]}
    assert other_thread.json()["data"]["id"] in expanded_ids


def test_forget_fact_context_and_search_hide_deleted_fact(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json=fact_payload("FACT_FORGET_E2E_MARKER must disappear after forget."),
            headers=auth_headers(),
        )
        fact_id = created.json()["data"]["id"]
        before_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "FACT_FORGET_E2E_MARKER",
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        deleted = client.delete(f"/v1/facts/{fact_id}", headers=auth_headers())
        after_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "FACT_FORGET_E2E_MARKER",
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        after_search = client.post(
            "/v1/search",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "FACT_FORGET_E2E_MARKER",
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert before_context.status_code == 200
    assert "FACT_FORGET_E2E_MARKER" in before_context.json()["data"]["rendered_text"]
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert after_context.status_code == 200
    assert "FACT_FORGET_E2E_MARKER" not in after_context.json()["data"]["rendered_text"]
    assert after_search.status_code == 200
    assert after_search.json()["data"]["items"] == []


def test_list_facts_is_scoped_and_validates_status(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post(
            "/v1/facts",
            json=fact_payload("Scoped fact A."),
            headers=auth_headers(),
        )
        second = client.post(
            "/v1/facts",
            json={
                **fact_payload("Scoped fact B."),
                "memory_scope_id": "memory_scope_other",
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "status": "active",
            },
            headers=auth_headers(),
        )
        invalid = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "status": "typo",
            },
            headers=auth_headers(),
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert listed.status_code == 200
    assert [item["text"] for item in listed.json()["data"]] == ["Scoped fact A."]
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "memory.validation"


def test_list_facts_filters_current_thread_without_leaking_other_threads(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        current = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "thread_external_ref": "thread-current",
                "text": "THREAD_LIST_CURRENT_MARKER belongs to current thread.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "thread-current"}],
            },
            headers=auth_headers(),
        )
        other = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "thread_external_ref": "thread-other",
                "text": "THREAD_LIST_OTHER_MARKER belongs to another thread.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "thread-other"}],
            },
            headers=auth_headers(),
        )
        memory_scope_wide = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "text": "THREAD_LIST_GLOBAL_MARKER is memory_scope-wide.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "memory_scope-wide"}],
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_slug": "agents",
                "memory_scope_external_ref": "backend-team",
                "thread_external_ref": "thread-current",
                "status": "active",
            },
            headers=auth_headers(),
        )

    assert current.status_code == 201
    assert other.status_code == 201
    assert memory_scope_wide.status_code == 201
    assert listed.status_code == 200
    texts = {item["text"] for item in listed.json()["data"]}
    assert "THREAD_LIST_CURRENT_MARKER belongs to current thread." in texts
    assert "THREAD_LIST_GLOBAL_MARKER is memory_scope-wide." in texts
    assert "THREAD_LIST_OTHER_MARKER belongs to another thread." not in texts


def test_canonical_scope_ids_must_belong_together(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space_a = client.post(
            "/v1/spaces",
            json={"slug": "canonical-a", "name": "Canonical A"},
            headers=auth_headers(),
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_a["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=auth_headers(),
        ).json()["data"]
        space_b = client.post(
            "/v1/spaces",
            json={"slug": "canonical-b", "name": "Canonical B"},
            headers=auth_headers(),
        ).json()["data"]
        memory_scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_b["id"], "external_ref": "beta", "name": "Beta"},
            headers=auth_headers(),
        ).json()["data"]
        deleted_memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_a["id"], "external_ref": "deleted", "name": "Deleted"},
            headers=auth_headers(),
        ).json()["data"]
        seeded_thread = client.post(
            "/v1/facts",
            json={
                "space_slug": "canonical-b",
                "memory_scope_external_ref": "beta",
                "thread_external_ref": "thread-b",
                "text": "CANONICAL_SCOPE_THREAD_SEED belongs to canonical-b.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "thread-seed"}],
            },
            headers=auth_headers(),
        ).json()["data"]
        deleted_thread = client.post(
            "/v1/facts",
            json={
                "space_slug": "canonical-a",
                "memory_scope_external_ref": "alpha",
                "thread_external_ref": "thread-deleted",
                "text": "CANONICAL_SCOPE_DELETED_THREAD_SEED belongs to a deleted thread.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "deleted-thread-seed"}],
            },
            headers=auth_headers(),
        ).json()["data"]
        asyncio.run(
            mark_scope_rows_deleted(
                client,
                memory_scope_id=deleted_memory_scope["id"],
                thread_id=deleted_thread["thread_id"],
            )
        )

        cross_memory_scope_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": memory_scope_b["id"],
                "text": "CANONICAL_SCOPE_CROSS_MEMORY_SCOPE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "cross-memory_scope"}],
            },
            headers=auth_headers(),
        )
        cross_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": memory_scope_a["id"],
                "thread_id": seeded_thread["thread_id"],
                "text": "CANONICAL_SCOPE_CROSS_THREAD must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "cross-thread"}],
            },
            headers=auth_headers(),
        )
        cross_memory_scope_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [memory_scope_b["id"]],
                "query": "CANONICAL_SCOPE_CROSS_MEMORY_SCOPE",
            },
            headers=auth_headers(),
        )
        cross_thread_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [memory_scope_a["id"]],
                "thread_id": seeded_thread["thread_id"],
                "query": "CANONICAL_SCOPE_CROSS_THREAD",
            },
            headers=auth_headers(),
        )
        orphan_memory_scope_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": "memory_scope_missing_canonical",
                "text": "CANONICAL_SCOPE_ORPHAN_MEMORY_SCOPE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "orphan-memory_scope"}],
            },
            headers=auth_headers(),
        )
        orphan_memory_scope_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [memory_scope_a["id"], "memory_scope_missing_canonical"],
                "query": "CANONICAL_SCOPE_ORPHAN_MEMORY_SCOPE",
            },
            headers=auth_headers(),
        )
        deleted_memory_scope_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": deleted_memory_scope["id"],
                "text": "CANONICAL_SCOPE_DELETED_MEMORY_SCOPE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "deleted-memory_scope"}],
            },
            headers=auth_headers(),
        )
        deleted_memory_scope_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [deleted_memory_scope["id"]],
                "query": "CANONICAL_SCOPE_DELETED_MEMORY_SCOPE",
            },
            headers=auth_headers(),
        )
        orphan_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": memory_scope_a["id"],
                "thread_id": "thread_missing_canonical",
                "text": "CANONICAL_SCOPE_ORPHAN_THREAD must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "orphan-thread"}],
            },
            headers=auth_headers(),
        )
        orphan_thread_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [memory_scope_a["id"]],
                "thread_id": "thread_missing_canonical",
                "query": "CANONICAL_SCOPE_ORPHAN_THREAD",
            },
            headers=auth_headers(),
        )
        deleted_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "memory_scope_id": memory_scope_a["id"],
                "thread_id": deleted_thread["thread_id"],
                "text": "CANONICAL_SCOPE_DELETED_THREAD must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "deleted-thread"}],
            },
            headers=auth_headers(),
        )
        deleted_thread_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "memory_scope_ids": [memory_scope_a["id"]],
                "thread_id": deleted_thread["thread_id"],
                "query": "CANONICAL_SCOPE_DELETED_THREAD",
            },
            headers=auth_headers(),
        )

    assert seeded_thread["thread_id"] is not None
    for response in (
        cross_memory_scope_fact,
        cross_thread_fact,
        cross_memory_scope_context,
        cross_thread_context,
        deleted_memory_scope_fact,
        deleted_memory_scope_context,
        orphan_memory_scope_fact,
        orphan_memory_scope_context,
        orphan_thread_fact,
        orphan_thread_context,
        deleted_thread_fact,
        deleted_thread_context,
    ):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "memory.validation"
        assert "CANONICAL_SCOPE_CROSS" not in response.text
        assert "CANONICAL_SCOPE_DELETED_MEMORY_SCOPE" not in response.text
        assert "CANONICAL_SCOPE_ORPHAN_MEMORY_SCOPE" not in response.text
        assert "CANONICAL_SCOPE_ORPHAN_THREAD" not in response.text
        assert "CANONICAL_SCOPE_DELETED_THREAD" not in response.text


def test_disabled_policy_blocks_public_writes(tmp_path: Path) -> None:
    with make_client_with_settings(tmp_path, policy_mode=MemoryPolicyMode.DISABLED) as client:
        response = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"
