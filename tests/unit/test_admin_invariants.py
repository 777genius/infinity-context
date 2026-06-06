import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryFactRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
)
from memo_stack_server.admin import (
    _adapter_check,
    compact_done_outbox,
    invariant_check,
    reindex_graphiti,
    reindex_qdrant,
    repair_projections,
    replay_outbox,
)
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
from sqlalchemy import delete, select
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


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_doctor_reports_provider_version_and_required_action() -> None:
    qdrant = _adapter_check(
        "qdrant",
        enabled=True,
        healthy=False,
        degraded_reason="qdrant.dimension_mismatch",
    )
    graphiti_disabled = _adapter_check(
        "graphiti",
        enabled=False,
        healthy=False,
        degraded_reason="disabled",
    )

    assert qdrant["status"] == "degraded"
    assert qdrant["provider_version"] == "unknown"
    assert qdrant["required_action"] == (
        "create a new projection collection or reindex Qdrant with the configured "
        "embedding dimension"
    )
    assert graphiti_disabled["status"] == "disabled"
    assert graphiti_disabled["required_action"] is None


def test_invariant_checker_is_scoped_and_omits_raw_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        ).json()["data"]
        profile = client.post(
            "/v1/profiles",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        asyncio.run(_insert_broken_rows(client, space_id=space["id"], profile_id=profile["id"]))

    scoped = asyncio.run(invariant_check(space="client-app", profile="default"))
    global_check = asyncio.run(invariant_check())

    assert scoped["status"] == "failed"
    assert _check_by_name(scoped, "active_fact_source_refs")["count"] == 1
    assert _check_by_name(scoped, "idempotency_results_exist")["count"] == 1
    assert "RAW_INVARIANT_SECRET" not in str(scoped)
    assert global_check["status"] == "failed"
    assert _check_by_name(global_check, "profile_scoped_rows_match_profile")["count"] >= 1
    assert _check_by_name(global_check, "active_chunk_parent_exists")["count"] >= 1
    assert "RAW_CHUNK_SECRET" not in str(global_check)


def test_invariant_checker_projection_mode_detects_orphan_projection_outbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        ).json()["data"]
        profile = client.post(
            "/v1/profiles",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        asyncio.run(
            _insert_orphan_projection_outbox(
                client,
                space_id=space["id"],
                profile_id=profile["id"],
            )
        )

    default_check = asyncio.run(invariant_check(space="client-app", profile="default"))
    projection_check = asyncio.run(
        invariant_check(
            space="client-app",
            profile="default",
            include_projections=True,
        )
    )

    assert default_check["status"] == "ok"
    assert _check_by_name(projection_check, "projection_outbox_aggregate_exists")["count"] == 1
    assert projection_check["status"] == "failed"
    assert "RAW_PROJECTION_SECRET" not in str(projection_check)


def test_repair_projections_requires_scope_and_dry_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        )

    missing_scope = asyncio.run(repair_projections(space=None, profile=None, dry_run=True))
    missing_dry_run = asyncio.run(
        repair_projections(space="client-app", profile="default", dry_run=False)
    )

    assert missing_scope["status"] == "refused"
    assert missing_dry_run["status"] == "refused"


def test_repair_dry_run_reports_counts_without_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        ).json()["data"]
        profile = client.post(
            "/v1/profiles",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "profile_id": profile["id"],
                "title": "Repair notes",
                "text": "RAW_REPAIR_SECRET should not appear in repair output.",
                "source_type": "document",
                "source_external_id": "repair-doc",
            },
            headers=auth_headers(),
        )
        client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "profile_id": profile["id"],
                "text": "RAW_REPAIR_FACT should not appear in repair output.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "repair-fact"}],
            },
            headers=auth_headers(),
        )
        asyncio.run(_clear_outbox(client))

    result = asyncio.run(repair_projections(space="client-app", profile="default", dry_run=True))

    with make_client(tmp_path) as client:
        rows = asyncio.run(_outbox_items(client))

    assert result["status"] == "ok"
    assert result["qdrant"]["would_upsert"] == 1
    assert result["graphiti"]["would_upsert"] == 1
    assert rows == []
    assert "RAW_REPAIR" not in str(result)


def test_reindex_qdrant_enqueues_active_chunk_projection_jobs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        ).json()["data"]
        profile = client.post(
            "/v1/profiles",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "profile_id": profile["id"],
                "title": "Reindex notes",
                "text": "RAW_QDRANT_REINDEX_SECRET should not appear in reindex output.",
                "source_type": "document",
                "source_external_id": "reindex-doc",
            },
            headers=auth_headers(),
        )
        asyncio.run(_clear_outbox(client))

    dry_run = asyncio.run(reindex_qdrant(space="client-app", profile="default", dry_run=True))
    refused = asyncio.run(reindex_qdrant(space="client-app", profile="default", dry_run=False))
    first = asyncio.run(
        reindex_qdrant(
            space="client-app",
            profile="default",
            dry_run=False,
            confirmed=True,
        )
    )
    second = asyncio.run(
        reindex_qdrant(
            space="client-app",
            profile="default",
            dry_run=False,
            confirmed=True,
        )
    )
    with make_client(tmp_path) as client:
        rows = asyncio.run(_outbox_items(client))

    assert dry_run["status"] == "ok"
    assert dry_run["qdrant"]["would_upsert"] == 1
    assert dry_run["qdrant"]["enqueued"] == 0
    assert refused["status"] == "refused"
    assert first["qdrant"]["enqueued"] == 1
    assert second["qdrant"]["enqueued"] == 0
    assert second["qdrant"]["skipped_existing_jobs"] == 1
    assert len(rows) == 1
    assert rows[0]["event_type"] == "vector.upsert_chunk"
    assert rows[0]["aggregate_type"] == "chunk"
    assert rows[0]["fairness_key"].startswith("chunk:")
    assert rows[0]["payload_json"]["space_id"] == space["id"]
    assert rows[0]["payload_json"]["profile_id"] == profile["id"]
    assert "RAW_QDRANT_REINDEX_SECRET" not in str(first)


def test_reindex_graphiti_skips_deleted_facts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        ).json()["data"]
        profile = client.post(
            "/v1/profiles",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        active = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "profile_id": profile["id"],
                "text": "Active fact should be reindexed.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "active-fact"}],
            },
            headers=auth_headers(),
        ).json()["data"]
        deleted = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "profile_id": profile["id"],
                "text": "RAW_DELETED_GRAPHITI_SECRET should not be reindexed.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "deleted-fact"}],
            },
            headers=auth_headers(),
        ).json()["data"]
        client.delete(f"/v1/facts/{deleted['id']}", headers=auth_headers())
        asyncio.run(_clear_outbox(client))

    result = asyncio.run(
        reindex_graphiti(
            space="client-app",
            profile="default",
            dry_run=False,
            confirmed=True,
        )
    )
    with make_client(tmp_path) as client:
        rows = asyncio.run(_outbox_items(client))

    assert result["status"] == "ok"
    assert result["graphiti"]["would_upsert"] == 1
    assert result["graphiti"]["enqueued"] == 1
    assert len(rows) == 1
    assert rows[0]["event_type"] == "graph.upsert_fact"
    assert rows[0]["aggregate_id"] == active["id"]
    assert rows[0]["aggregate_version"] == active["version"]
    assert "RAW_DELETED_GRAPHITI_SECRET" not in str(result)


def test_replay_dead_outbox_job_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        asyncio.run(_insert_dead_outbox(client))

    first = asyncio.run(replay_outbox(status="dead", limit=50))
    second = asyncio.run(replay_outbox(status="dead", limit=50))

    with make_client(tmp_path) as client:
        rows = asyncio.run(_outbox_items(client))

    assert first == {"replayed": 1, "from_status": "dead"}
    assert second == {"replayed": 0, "from_status": "dead"}
    assert rows[0]["status"] == "pending"
    assert "RAW_REPLAY_SECRET" not in str(first)


def test_compact_done_outbox_redacts_payload_but_keeps_audit_columns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        asyncio.run(_insert_done_outbox_with_raw_payload(client))

    dry_run = asyncio.run(compact_done_outbox(older_than_seconds=0, limit=50, dry_run=True))
    with make_client(tmp_path) as client:
        dry_run_rows = asyncio.run(_outbox_items(client))

    compacted = asyncio.run(compact_done_outbox(older_than_seconds=0, limit=50, dry_run=False))
    with make_client(tmp_path) as client:
        rows = asyncio.run(_outbox_items(client))

    assert dry_run["status"] == "ok"
    assert dry_run["dry_run"] is True
    assert dry_run["would_compact"] == 1
    assert "RAW_DONE_PAYLOAD_SECRET" in str(dry_run_rows)
    assert compacted["status"] == "ok"
    assert compacted["compacted"] == 1
    assert compacted["would_compact"] == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["event_type"] == "vector.upsert_chunk"
    assert rows[0]["aggregate_type"] == "chunk"
    assert rows[0]["aggregate_id"] == "chunk_done_compact"
    assert rows[0]["payload_json"]["compacted"] is True
    assert rows[0]["payload_json"]["preserved"] == {
        "space_id": "space_client_app",
        "profile_id": "profile_default",
        "chunk_id": "chunk_done_compact",
    }
    assert "RAW_DONE_PAYLOAD_SECRET" not in str(rows)
    assert "RAW_DONE_PAYLOAD_SECRET" not in str(compacted)


async def _insert_broken_rows(client: TestClient, *, space_id: str, profile_id: str) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryFactRow(
                id="fact_broken_no_refs",
                space_id=space_id,
                profile_id=profile_id,
                thread_id=None,
                kind="note",
                text="RAW_INVARIANT_SECRET should never appear in invariant output.",
                status="active",
                confidence="medium",
                trust_level="medium",
                classification="internal",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MemoryChunkRow(
                id="chunk_broken_parent",
                space_id=space_id,
                profile_id="profile_missing",
                thread_id=None,
                document_id=None,
                episode_id=None,
                source_type="manual",
                source_external_id="broken",
                source_hash="broken_hash",
                kind="document_section",
                text="RAW_CHUNK_SECRET should never appear in invariant output.",
                normalized_text="raw_chunk_secret should never appear in invariant output.",
                status="active",
                sequence=0,
                char_start=0,
                char_end=58,
                token_estimate=12,
                created_at=now,
                updated_at=now,
                metadata_json={},
            )
        )
        session.add(
            MemoryIdempotencyRecordRow(
                space_id=space_id,
                key="broken-idempotency",
                fingerprint="broken",
                result_type="fact",
                result_id="fact_missing",
                created_at=now,
            )
        )
        await session.commit()


async def _insert_orphan_projection_outbox(
    client: TestClient,
    *,
    space_id: str,
    profile_id: str,
) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryOutboxRow(
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk_missing_projection",
                aggregate_version=None,
                payload_json={
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "raw": "RAW_PROJECTION_SECRET should never appear in invariant output.",
                },
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
                workload_class="projection",
                fairness_key="chunk:chunk_missing_projection",
            )
        )
        await session.commit()


async def _insert_dead_outbox(client: TestClient) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryOutboxRow(
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk_dead_replay",
                aggregate_version=None,
                payload_json={"raw": "RAW_REPLAY_SECRET should stay private"},
                status="dead",
                attempt_count=5,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
                workload_class="projection",
                fairness_key="chunk:chunk_dead_replay",
                last_safe_error="Vector write degraded",
                last_safe_diagnostic_code="qdrant.upsert_failed",
            )
        )
        await session.commit()


async def _insert_done_outbox_with_raw_payload(client: TestClient) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryOutboxRow(
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk_done_compact",
                aggregate_version=None,
                payload_json={
                    "space_id": "space_client_app",
                    "profile_id": "profile_default",
                    "chunk_id": "chunk_done_compact",
                    "raw": "RAW_DONE_PAYLOAD_SECRET should be compacted away",
                },
                status="done",
                attempt_count=1,
                next_attempt_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
                workload_class="projection",
                fairness_key="chunk:chunk_done_compact",
                last_safe_error=None,
                last_safe_diagnostic_code=None,
            )
        )
        await session.commit()


async def _clear_outbox(client: TestClient) -> None:
    async with AsyncSession(client.app.state.container.engine) as session:
        await session.execute(delete(MemoryOutboxRow))
        await session.commit()


async def _outbox_items(client: TestClient) -> list[dict[str, object]]:
    async with AsyncSession(client.app.state.container.engine) as session:
        rows = list(
            (await session.execute(select(MemoryOutboxRow).order_by(MemoryOutboxRow.id))).scalars()
        )
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "aggregate_version": row.aggregate_version,
                "fairness_key": row.fairness_key,
                "payload_json": row.payload_json,
                "status": row.status,
                "workload_class": row.workload_class,
            }
            for row in rows
        ]


def _check_by_name(result: dict[str, object], name: str) -> dict[str, object]:
    checks = result["checks"]
    assert isinstance(checks, list)
    for check in checks:
        if check["name"] == name:
            return check
    raise AssertionError(f"Missing check {name}")
