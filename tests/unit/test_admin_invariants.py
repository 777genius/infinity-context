import asyncio
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import infinity_context_server.admin as admin_module
import infinity_context_server.admin_outbox as admin_outbox_module
import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryFactRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
    MemoryVectorRebuildOperationRow,
)
from infinity_context_server.admin import (
    _adapter_check,
    compact_done_outbox,
    invariant_check,
    reindex_graphiti,
    repair_projections,
    replay_outbox,
)
from infinity_context_server.admin_projection_repair import reindex_qdrant
from infinity_context_server.admin_qdrant_cli import authorize_qdrant_rebuild
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.vector_rebuild import GenericVectorRebuildProcess
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


def test_doctor_reports_openai_embedding_key_action() -> None:
    embeddings = _adapter_check(
        "embeddings",
        enabled=True,
        healthy=False,
        degraded_reason="embeddings.invalid_api_key",
    )

    assert embeddings["status"] == "degraded"
    assert embeddings["required_action"] == (
        "replace the embedding provider API key and rerun the canary"
    )


def test_doctor_reports_graphiti_provider_key_action() -> None:
    graphiti = _adapter_check(
        "graphiti",
        enabled=True,
        healthy=False,
        degraded_reason="graph.invalid_api_key",
    )

    assert graphiti["status"] == "degraded"
    assert graphiti["required_action"] == (
        "replace the Graphiti/OpenAI provider API key and rerun the canary"
    )


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
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        asyncio.run(
            _insert_broken_rows(client, space_id=space["id"], memory_scope_id=memory_scope["id"])
        )

    scoped = asyncio.run(invariant_check(space="client-app", memory_scope="default"))
    global_check = asyncio.run(invariant_check())

    assert scoped["status"] == "failed"
    assert _check_by_name(scoped, "active_fact_source_refs")["count"] == 1
    assert _check_by_name(scoped, "idempotency_results_exist")["count"] == 1
    assert "RAW_INVARIANT_SECRET" not in str(scoped)
    assert global_check["status"] == "failed"
    assert _check_by_name(global_check, "memory_scope_scoped_rows_match_memory_scope")["count"] >= 1
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
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        asyncio.run(
            _insert_orphan_projection_outbox(
                client,
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
            )
        )

    default_check = asyncio.run(invariant_check(space="client-app", memory_scope="default"))
    projection_check = asyncio.run(
        invariant_check(
            space="client-app",
            memory_scope="default",
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

    missing_scope = asyncio.run(repair_projections(space=None, memory_scope=None, dry_run=True))
    missing_dry_run = asyncio.run(
        repair_projections(space="client-app", memory_scope="default", dry_run=False)
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
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
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
                "memory_scope_id": memory_scope["id"],
                "text": "RAW_REPAIR_FACT should not appear in repair output.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "repair-fact"}],
            },
            headers=auth_headers(),
        )
        asyncio.run(_clear_outbox(client))

    result = asyncio.run(
        repair_projections(space="client-app", memory_scope="default", dry_run=True)
    )

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
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "title": "Reindex notes",
                "text": "RAW_QDRANT_REINDEX_SECRET should not appear in reindex output.",
                "source_type": "document",
                "source_external_id": "reindex-doc",
            },
            headers=auth_headers(),
        )
        other_space = client.post(
            "/v1/spaces",
            json={"slug": "other-app", "name": "Other App"},
            headers=auth_headers(),
        ).json()["data"]
        client.post(
            "/v1/memory-scopes",
            json={"space_id": other_space["id"], "external_ref": "other", "name": "Other"},
            headers=auth_headers(),
        )
        asyncio.run(_clear_outbox(client))

    dry_run = asyncio.run(reindex_qdrant(space="client-app", memory_scope="default", dry_run=True))
    refused = asyncio.run(reindex_qdrant(space="client-app", memory_scope="default", dry_run=False))
    first = asyncio.run(
        reindex_qdrant(
            space="client-app",
            memory_scope="default",
            dry_run=False,
            confirmed=True,
            operation_id="test-rebuild-001",
        )
    )
    second = asyncio.run(
        reindex_qdrant(
            space="client-app",
            memory_scope="default",
            dry_run=False,
            confirmed=True,
            operation_id="test-rebuild-001",
        )
    )
    cross_scope = asyncio.run(
        reindex_qdrant(
            space="other-app",
            memory_scope="other",
            dry_run=False,
            confirmed=True,
            operation_id="test-rebuild-001",
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
    assert second["status"] == "resumed"
    assert cross_scope["status"] == "refused"
    assert "different rebuild" in cross_scope["reason"]
    assert len(rows) == 1
    assert rows[0]["event_type"] == "vector.rebuild_scope_page"
    assert rows[0]["aggregate_type"] == "vector_rebuild"
    assert rows[0]["fairness_key"] == "vector-rebuild:test-rebuild-001"
    assert rows[0]["payload_json"]["space_id"] == space["id"]
    assert rows[0]["payload_json"]["memory_scope_id"] == memory_scope["id"]
    assert "RAW_QDRANT_REINDEX_SECRET" not in str(first)


def test_rebuild_consumes_only_watermarked_legacy_document_delete_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "legacy-delete", "name": "Legacy Delete"},
            headers=auth_headers(),
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "scope", "name": "Scope"},
            headers=auth_headers(),
        ).json()["data"]
        document = client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "title": "Legacy delete",
                "text": "Canonical ownership remains after soft delete.",
                "source_type": "document",
                "source_external_id": "legacy-delete-doc",
            },
            headers=auth_headers(),
        ).json()["data"]
        client.delete(f"/v1/documents/{document['id']}", headers=auth_headers())
        legacy_id = asyncio.run(_make_delete_event_dead_and_legacy(client, document["id"]))

        started = asyncio.run(
            reindex_qdrant(
                space="legacy-delete",
                memory_scope="scope",
                dry_run=False,
                confirmed=True,
                operation_id="legacy-delete-rebuild",
                batch_size=2,
            )
        )
        later_id = asyncio.run(_insert_later_dead_delete(client, legacy_id))
        job = asyncio.run(_rebuild_job(client, "legacy-delete-rebuild"))
        asyncio.run(GenericVectorRebuildProcess(client.app.state.container).handle_page(job))
        statuses, operation = asyncio.run(
            _delete_event_statuses(client, legacy_id=legacy_id, later_id=later_id)
        )

    assert started["dead_event_watermark"] == legacy_id
    assert statuses == ("done", "dead")
    assert operation.status == "complete"
    assert operation.processed_count == 1
    assert operation.failed_count == 0


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
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=auth_headers(),
        ).json()["data"]
        active = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
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
                "memory_scope_id": memory_scope["id"],
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
            memory_scope="default",
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

    assert first == {"replayed": 2, "from_status": "dead"}
    assert second == {"replayed": 0, "from_status": "dead"}
    assert {row["aggregate_type"] for row in rows} == {"benchmark_run", "chunk"}
    assert all(row["status"] == "pending" for row in rows)
    assert "RAW_REPLAY_SECRET" not in str(first)


def test_replay_rejects_done_before_container_and_preserves_all_done_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        asyncio.run(_insert_done_outbox_with_raw_payload(client))
        before = asyncio.run(_outbox_items(client))

        def fail_build_container(_settings: Settings) -> None:
            raise AssertionError("container must not be built for a forbidden replay status")

        monkeypatch.setattr(admin_outbox_module, "build_container", fail_build_container)
        with pytest.raises(ValueError, match="status must be exactly 'dead'"):
            asyncio.run(replay_outbox(status="done", limit=50))

        after = asyncio.run(_outbox_items(client))

    assert {row["aggregate_type"] for row in before} == {"benchmark_run", "chunk"}
    assert all(row["status"] == "done" for row in before)
    assert after == before


def test_replay_cli_rejects_done_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["infinity-context-admin", "replay-outbox", "--status", "done"],
    )

    with pytest.raises(SystemExit) as error:
        admin_module.main()

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_installed_admin_help_publishes_bounded_qdrant_rebuild_flags() -> None:
    sibling_executable = Path(sys.executable).with_name("infinity-context-admin")
    executable = shutil.which("infinity-context-admin") or (
        str(sibling_executable) if sibling_executable.is_file() else None
    )
    assert executable is not None
    result = subprocess.run(
        [executable, "reindex-qdrant", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    for flag in (
        "--auth-token-env",
        "--preflight-only",
        "--batch-size",
        "--deadline-seconds",
        "--operation-id",
    ):
        assert flag in result.stdout


def test_qdrant_rebuild_auth_uses_separate_environment_credential(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "configured-secret")
    monkeypatch.setenv("INFINITY_CONTEXT_ADMIN_TOKEN", "wrong-secret")
    refused = authorize_qdrant_rebuild("INFINITY_CONTEXT_ADMIN_TOKEN")
    assert refused is not None
    assert refused["status"] == "refused"

    monkeypatch.setenv("INFINITY_CONTEXT_ADMIN_TOKEN", "configured-secret")
    assert authorize_qdrant_rebuild("INFINITY_CONTEXT_ADMIN_TOKEN") is None
    assert authorize_qdrant_rebuild("invalid-name") == {
        "status": "refused",
        "operation": "reindex-qdrant",
        "reason": "auth token environment variable name is invalid",
    }


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
        "memory_scope_id": "memory_scope_default",
        "chunk_id": "chunk_done_compact",
    }
    assert rows[1]["aggregate_type"] == "benchmark_run"
    assert rows[1]["payload_json"] == {
        "space_id": "space_client_app",
        "cleanup_run_id_sha256": "benchmark-run-evidence",
        "raw": "IMMUTABLE_BENCHMARK_CLEANUP_EVIDENCE",
    }
    assert "RAW_DONE_PAYLOAD_SECRET" not in str(rows)
    assert "RAW_DONE_PAYLOAD_SECRET" not in str(compacted)


async def _insert_broken_rows(client: TestClient, *, space_id: str, memory_scope_id: str) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryFactRow(
                id="fact_broken_no_refs",
                space_id=space_id,
                memory_scope_id=memory_scope_id,
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
                memory_scope_id="memory_scope_missing",
                thread_id=None,
                document_id="document_missing",
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
    memory_scope_id: str,
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
                    "memory_scope_id": memory_scope_id,
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
        session.add(
            MemoryOutboxRow(
                event_type="vector.delete_chunks",
                aggregate_type="benchmark_run",
                aggregate_id="benchmark_dead_replay",
                aggregate_version=None,
                payload_json={"raw": "RAW_REPLAY_SECRET benchmark cleanup evidence"},
                status="dead",
                attempt_count=5,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
                workload_class="projection",
                fairness_key="benchmark_run:benchmark_dead_replay",
                last_safe_error="Vector delete degraded",
                last_safe_diagnostic_code="qdrant.delete_failed",
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
                    "memory_scope_id": "memory_scope_default",
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
        session.add(
            MemoryOutboxRow(
                event_type="vector.delete_chunks",
                aggregate_type="benchmark_run",
                aggregate_id="benchmark-run-evidence",
                aggregate_version=None,
                payload_json={
                    "space_id": "space_client_app",
                    "cleanup_run_id_sha256": "benchmark-run-evidence",
                    "raw": "IMMUTABLE_BENCHMARK_CLEANUP_EVIDENCE",
                },
                status="done",
                attempt_count=1,
                next_attempt_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
                workload_class="projection",
                fairness_key="benchmark_run:benchmark-run-evidence",
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


async def _make_delete_event_dead_and_legacy(client: TestClient, document_id: str) -> int:
    async with AsyncSession(client.app.state.container.engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.event_type == "vector.delete_chunks",
                    MemoryOutboxRow.aggregate_id == document_id,
                )
                .order_by(MemoryOutboxRow.id.desc())
                .limit(1)
            )
        ).scalar_one()
        row.payload_json = {
            key: value
            for key, value in row.payload_json.items()
            if key not in {"space_id", "memory_scope_id"}
        }
        row.status = "dead"
        row.last_safe_diagnostic_code = "qdrant.delete_rebuild_required"
        row_id = row.id
        await session.commit()
        return row_id


async def _insert_later_dead_delete(client: TestClient, legacy_id: int) -> int:
    async with AsyncSession(client.app.state.container.engine, expire_on_commit=False) as session:
        legacy = await session.get(MemoryOutboxRow, legacy_id)
        assert legacy is not None
        later = MemoryOutboxRow(
            event_type=legacy.event_type,
            aggregate_type=legacy.aggregate_type,
            aggregate_id=legacy.aggregate_id,
            aggregate_version=legacy.aggregate_version,
            workload_class=legacy.workload_class,
            fairness_key=f"later:{legacy.fairness_key}",
            payload_json=dict(legacy.payload_json),
            status="dead",
            attempt_count=5,
            next_attempt_at=legacy.next_attempt_at,
            last_safe_error="redacted",
            last_safe_diagnostic_code="qdrant.delete_rebuild_required",
            created_at=legacy.created_at,
            updated_at=legacy.updated_at,
        )
        session.add(later)
        await session.commit()
        return later.id


async def _rebuild_job(client: TestClient, operation_id: str) -> ClaimedOutboxJob:
    async with AsyncSession(client.app.state.container.engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.event_type == "vector.rebuild_scope_page",
                    MemoryOutboxRow.aggregate_id == operation_id,
                )
                .order_by(MemoryOutboxRow.id.desc())
                .limit(1)
            )
        ).scalar_one()
        return ClaimedOutboxJob(
            id=row.id,
            event_type=row.event_type,
            aggregate_type=row.aggregate_type,
            aggregate_id=row.aggregate_id,
            aggregate_version=row.aggregate_version,
            attempt_count=row.attempt_count,
            workload_class=row.workload_class,
            fairness_key=row.fairness_key,
            payload_json=dict(row.payload_json),
        )


async def _delete_event_statuses(
    client: TestClient,
    *,
    legacy_id: int,
    later_id: int,
) -> tuple[tuple[str, str], MemoryVectorRebuildOperationRow]:
    async with AsyncSession(client.app.state.container.engine) as session:
        legacy = await session.get(MemoryOutboxRow, legacy_id)
        later = await session.get(MemoryOutboxRow, later_id)
        operation = await session.get(
            MemoryVectorRebuildOperationRow,
            "legacy-delete-rebuild",
        )
        assert legacy is not None and later is not None and operation is not None
        session.expunge(operation)
        return (legacy.status, later.status), operation


def _check_by_name(result: dict[str, object], name: str) -> dict[str, object]:
    checks = result["checks"]
    assert isinstance(checks, list)
    for check in checks:
        if check["name"] == name:
            return check
    raise AssertionError(f"Missing check {name}")
