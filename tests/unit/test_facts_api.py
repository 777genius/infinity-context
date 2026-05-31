import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memory_adapters.postgres.models import MemoryOutboxRow, MemoryProfileRow, MemoryThreadRow
from memory_core.domain.errors import MemoryConflictError
from memory_core.domain.idempotency import IdempotencyRecord
from memory_server.config import DeployProfile, MemoryPolicyMode, Settings
from memory_server.main import create_app
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
        "space_id": "space_hackinterview",
        "profile_id": "profile_default",
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
    profile_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        if profile_id:
            profile = await session.get(MemoryProfileRow, profile_id)
            assert profile is not None
            profile.status = "deleted"
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
                "profile_external_ref": "backend-team",
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
                "profile_external_ref": "backend-team",
                "status": "active",
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == created.json()["data"]["id"]
    assert listed.json()["data"][0]["thread_id"] is not None


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


def test_same_idempotency_key_is_profile_scoped(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = auth_headers({"Idempotency-Key": "profile-scoped-fact-key"})
        default = client.post(
            "/v1/facts",
            json=fact_payload("PROFILE_IDEMPOTENCY_MARKER belongs to default."),
            headers=headers,
        )
        secondary = client.post(
            "/v1/facts",
            json={
                **fact_payload("PROFILE_IDEMPOTENCY_MARKER belongs to default."),
                "profile_id": "profile_secondary",
            },
            headers=headers,
        )

    assert default.status_code == 201
    assert secondary.status_code == 201
    assert default.json()["data"]["id"] != secondary.json()["data"]["id"]
    assert default.json()["data"]["profile_id"] == "profile_default"
    assert secondary.json()["data"]["profile_id"] == "profile_secondary"


def test_idempotency_unique_violation_maps_to_domain_conflict(tmp_path: Path) -> None:
    async def run(client: TestClient) -> str:
        container = client.app.state.container
        try:
            async with container.uow_factory() as uow:
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id="space_hackinterview",
                        key="duplicate-commit",
                        fingerprint="first",
                        result_type="fact",
                        result_id="fact_first",
                    )
                )
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id="space_hackinterview",
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
                "space_id": "space_hackinterview",
                "profile_ids": ["profile_default"],
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
                "space_id": "space_hackinterview",
                "profile_ids": ["profile_default"],
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
                "space_id": "space_hackinterview",
                "profile_ids": ["profile_default"],
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
                "space_id": "space_hackinterview",
                "profile_ids": ["profile_default"],
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
                "space_id": "space_hackinterview",
                "profile_ids": ["profile_default"],
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
                "profile_id": "profile_other",
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_id": "space_hackinterview",
                "profile_id": "profile_default",
                "status": "active",
            },
            headers=auth_headers(),
        )
        invalid = client.get(
            "/v1/facts",
            params={
                "space_id": "space_hackinterview",
                "profile_id": "profile_default",
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
                "profile_external_ref": "backend-team",
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
                "profile_external_ref": "backend-team",
                "thread_external_ref": "thread-other",
                "text": "THREAD_LIST_OTHER_MARKER belongs to another thread.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "thread-other"}],
            },
            headers=auth_headers(),
        )
        profile_wide = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "profile_external_ref": "backend-team",
                "text": "THREAD_LIST_GLOBAL_MARKER is profile-wide.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "profile-wide"}],
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_slug": "agents",
                "profile_external_ref": "backend-team",
                "thread_external_ref": "thread-current",
                "status": "active",
            },
            headers=auth_headers(),
        )

    assert current.status_code == 201
    assert other.status_code == 201
    assert profile_wide.status_code == 201
    assert listed.status_code == 200
    texts = {item["text"] for item in listed.json()["data"]}
    assert "THREAD_LIST_CURRENT_MARKER belongs to current thread." in texts
    assert "THREAD_LIST_GLOBAL_MARKER is profile-wide." in texts
    assert "THREAD_LIST_OTHER_MARKER belongs to another thread." not in texts


def test_canonical_scope_ids_must_belong_together(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space_a = client.post(
            "/v1/spaces",
            json={"slug": "canonical-a", "name": "Canonical A"},
            headers=auth_headers(),
        ).json()["data"]
        profile_a = client.post(
            "/v1/profiles",
            json={"space_id": space_a["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=auth_headers(),
        ).json()["data"]
        space_b = client.post(
            "/v1/spaces",
            json={"slug": "canonical-b", "name": "Canonical B"},
            headers=auth_headers(),
        ).json()["data"]
        profile_b = client.post(
            "/v1/profiles",
            json={"space_id": space_b["id"], "external_ref": "beta", "name": "Beta"},
            headers=auth_headers(),
        ).json()["data"]
        deleted_profile = client.post(
            "/v1/profiles",
            json={"space_id": space_a["id"], "external_ref": "deleted", "name": "Deleted"},
            headers=auth_headers(),
        ).json()["data"]
        seeded_thread = client.post(
            "/v1/facts",
            json={
                "space_slug": "canonical-b",
                "profile_external_ref": "beta",
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
                "profile_external_ref": "alpha",
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
                profile_id=deleted_profile["id"],
                thread_id=deleted_thread["thread_id"],
            )
        )

        cross_profile_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": profile_b["id"],
                "text": "CANONICAL_SCOPE_CROSS_PROFILE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "cross-profile"}],
            },
            headers=auth_headers(),
        )
        cross_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": profile_a["id"],
                "thread_id": seeded_thread["thread_id"],
                "text": "CANONICAL_SCOPE_CROSS_THREAD must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "cross-thread"}],
            },
            headers=auth_headers(),
        )
        cross_profile_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "profile_ids": [profile_b["id"]],
                "query": "CANONICAL_SCOPE_CROSS_PROFILE",
            },
            headers=auth_headers(),
        )
        cross_thread_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "profile_ids": [profile_a["id"]],
                "thread_id": seeded_thread["thread_id"],
                "query": "CANONICAL_SCOPE_CROSS_THREAD",
            },
            headers=auth_headers(),
        )
        orphan_profile_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": "profile_missing_canonical",
                "text": "CANONICAL_SCOPE_ORPHAN_PROFILE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "orphan-profile"}],
            },
            headers=auth_headers(),
        )
        orphan_profile_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "profile_ids": [profile_a["id"], "profile_missing_canonical"],
                "query": "CANONICAL_SCOPE_ORPHAN_PROFILE",
            },
            headers=auth_headers(),
        )
        deleted_profile_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": deleted_profile["id"],
                "text": "CANONICAL_SCOPE_DELETED_PROFILE must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "deleted-profile"}],
            },
            headers=auth_headers(),
        )
        deleted_profile_context = client.post(
            "/v1/context",
            json={
                "space_id": space_a["id"],
                "profile_ids": [deleted_profile["id"]],
                "query": "CANONICAL_SCOPE_DELETED_PROFILE",
            },
            headers=auth_headers(),
        )
        orphan_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": profile_a["id"],
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
                "profile_ids": [profile_a["id"]],
                "thread_id": "thread_missing_canonical",
                "query": "CANONICAL_SCOPE_ORPHAN_THREAD",
            },
            headers=auth_headers(),
        )
        deleted_thread_fact = client.post(
            "/v1/facts",
            json={
                "space_id": space_a["id"],
                "profile_id": profile_a["id"],
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
                "profile_ids": [profile_a["id"]],
                "thread_id": deleted_thread["thread_id"],
                "query": "CANONICAL_SCOPE_DELETED_THREAD",
            },
            headers=auth_headers(),
        )

    assert seeded_thread["thread_id"] is not None
    for response in (
        cross_profile_fact,
        cross_thread_fact,
        cross_profile_context,
        cross_thread_context,
        deleted_profile_fact,
        deleted_profile_context,
        orphan_profile_fact,
        orphan_profile_context,
        orphan_thread_fact,
        orphan_thread_context,
        deleted_thread_fact,
        deleted_thread_context,
    ):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "memory.validation"
        assert "CANONICAL_SCOPE_CROSS" not in response.text
        assert "CANONICAL_SCOPE_DELETED_PROFILE" not in response.text
        assert "CANONICAL_SCOPE_ORPHAN_PROFILE" not in response.text
        assert "CANONICAL_SCOPE_ORPHAN_THREAD" not in response.text
        assert "CANONICAL_SCOPE_DELETED_THREAD" not in response.text


def test_disabled_policy_blocks_public_writes(tmp_path: Path) -> None:
    with make_client_with_settings(tmp_path, policy_mode=MemoryPolicyMode.DISABLED) as client:
        response = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"
