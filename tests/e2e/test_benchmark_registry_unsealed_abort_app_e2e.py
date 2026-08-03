from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpConfig,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server_harness import PROJECT_ROOT, run_infinity_context_server
from sqlalchemy.engine import make_url

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE_SLUG = "memory-comparison-app-sqlite-abort"
REGISTER_KEY = "sandbox-register-idempotency"
CLEANUP_KEY = "sandbox-cleanup-idempotency"
ABORT_KEY = "sandbox-abort-idempotency"


def test_app_postgres_registry_abort_recovers_and_replays_when_configured(
    tmp_path: Path,
) -> None:
    with _isolated_postgres_database() as database_url:
        token = "sandbox-postgres-admin-token"
        with run_infinity_context_server(
            tmp_path,
            token=token,
            extra_env={"MEMORY_DATABASE_URL": database_url},
        ) as server:
            adapter = _live_registry_adapter(server.base_url, token)
            registration = adapter.register(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                space_slug=SPACE_SLUG,
                idempotency_key=REGISTER_KEY,
            )
            cleanup = adapter.begin_cleanup(idempotency_key=CLEANUP_KEY)
            terminal = adapter.finalize_unsealed_abort(
                cleanup_initiation_receipt_sha256=cleanup.receipt_sha256,
                idempotency_key=ABORT_KEY,
            )
            assert registration.created is True
            assert cleanup.projection_cleanup == "blocked"
            assert terminal.state == "cleanup_aborted"
            assert terminal.replayed is False

            recovery = _live_registry_adapter(server.base_url, token)
            snapshot = recovery.recover_lifecycle(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                space_slug=SPACE_SLUG,
            )
            assert snapshot.state == "cleanup_aborted"
            assert snapshot.projection_cleanup_state == "unsealed_abort_complete"
            assert snapshot.completion_receipt is not None
            assert snapshot.completion_receipt.receipt_sha256 == terminal.receipt_sha256

            replay = httpx.post(
                f"{server.base_url}/v1/internal/memory-comparison/runs/"
                f"{RUN}/cleanup/abort/finalize",
                json={
                    "schema_version": "memory-comparison-run-abort-finalize.v1",
                    "binding_commitment_sha256": BINDING,
                    "infinity_target_identity_sha256": (
                        registration.infinity_target_identity_sha256
                    ),
                    "space_id": registration.space_id,
                    "space_slug": SPACE_SLUG,
                    "receipt_sha256": cleanup.receipt_sha256,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": ABORT_KEY,
                },
                timeout=10,
            )
            assert replay.status_code == 200, replay.text
            replayed = replay.json()["data"]
            assert replayed["replayed"] is True
            assert replayed["receipt_sha256"] == terminal.receipt_sha256


def test_app_sqlite_registry_unsealed_abort_persists_and_replays(tmp_path: Path) -> None:
    database_name = "benchmark-registry-abort.db"
    token = "sandbox-admin-token"
    headers = {"Authorization": f"Bearer {token}"}
    registration_payload = {
        "schema_version": "memory-comparison-run-registration.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_slug": SPACE_SLUG,
    }

    with (
        run_infinity_context_server(
            tmp_path,
            token=token,
            database_name=database_name,
        ) as server,
        httpx.Client(base_url=server.base_url, headers=headers, timeout=10) as client,
    ):
        registered = client.post(
            "/v1/internal/memory-comparison/runs",
            json=registration_payload,
            headers={"Idempotency-Key": REGISTER_KEY},
        )
        assert registered.status_code == 201, registered.text
        registration = registered.json()["data"]
        assert registration["created"] is True
        assert registration["state"] == "active"
        assert registration["run_id_sha256"] == RUN
        assert registration["binding_commitment_sha256"] == BINDING
        assert registration["infinity_target_identity_sha256"] == TARGET

        space_id = registration["space_id"]
        cleanup = client.request(
            "DELETE",
            f"/v1/internal/memory-comparison/runs/{RUN}",
            json={
                "schema_version": "memory-comparison-run-cleanup.v1",
                "binding_commitment_sha256": BINDING,
                "infinity_target_identity_sha256": TARGET,
                "space_id": space_id,
                "space_slug": SPACE_SLUG,
            },
            headers={"Idempotency-Key": CLEANUP_KEY},
        )
        assert cleanup.status_code == 200, cleanup.text
        initiation = cleanup.json()["data"]
        assert initiation["state"] == "cleanup_pending"
        assert initiation["projection_cleanup"] == "blocked"
        assert all(value == 0 for value in initiation["counts"].values())
        assert initiation["vector_delete_outbox_ids"] == []
        assert initiation["graph_delete_outbox_ids"] == []
        assert initiation["cognee_delete_outbox_ids"] == []

        abort_payload = {
            "schema_version": "memory-comparison-run-abort-finalize.v1",
            "binding_commitment_sha256": BINDING,
            "infinity_target_identity_sha256": TARGET,
            "space_id": space_id,
            "space_slug": SPACE_SLUG,
            "receipt_sha256": initiation["receipt_sha256"],
        }
        aborted = client.post(
            f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
            json=abort_payload,
            headers={"Idempotency-Key": ABORT_KEY},
        )
        assert aborted.status_code == 200, aborted.text
        terminal = aborted.json()["data"]
        assert terminal["state"] == "cleanup_aborted"
        assert terminal["disposition"] == "abort_complete"
        assert terminal["projection_cleanup"] == "unsealed_abort_complete"
        assert terminal["binding_commitment_sha256"] == BINDING
        assert terminal["infinity_target_identity_sha256"] == TARGET
        assert terminal["cleanup_initiation_receipt_sha256"] == initiation["receipt_sha256"]
        assert terminal["replayed"] is False

    with (
        run_infinity_context_server(
            tmp_path,
            token=token,
            database_name=database_name,
        ) as restarted,
        httpx.Client(
            base_url=restarted.base_url,
            headers=headers,
            timeout=10,
        ) as client,
    ):
        lifecycle_response = client.get(f"/v1/internal/memory-comparison/runs/{RUN}/cleanup")
        assert lifecycle_response.status_code == 200, lifecycle_response.text
        lifecycle = lifecycle_response.json()["data"]
        assert lifecycle["state"] == "cleanup_aborted"
        assert lifecycle["projection_cleanup_state"] == "unsealed_abort_complete"
        assert lifecycle["projection_manifest_sha256"] is None
        assert lifecycle["cleanup_receipt"]["receipt_sha256"] == initiation["receipt_sha256"]
        assert lifecycle["completion_receipt"]["receipt_sha256"] == terminal["receipt_sha256"]

        replay = client.post(
            f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
            json=abort_payload,
            headers={"Idempotency-Key": ABORT_KEY},
        )
        assert replay.status_code == 200, replay.text
        replayed = replay.json()["data"]
        assert replayed["replayed"] is True
        assert replayed["receipt_sha256"] == terminal["receipt_sha256"]
        assert replayed["completed_at"] == terminal["completed_at"]


def test_postgres_unsealed_abort_migration_contract_is_explicit() -> None:
    migration = (
        PROJECT_ROOT
        / "packages"
        / "infinity_context_adapters"
        / "infinity_context_adapters"
        / "postgres"
        / "migrations"
        / "0021_benchmark_unsealed_abort.sql"
    ).read_text()

    assert (
        "state IN ('active', 'cleanup_pending', 'cleanup_complete', 'cleanup_aborted')" in migration
    )
    assert "projection_cleanup_state = 'unsealed_abort_complete'" in migration
    assert "projection_manifest_json IS NULL" in migration
    assert migration.count(") NOT VALID") == 4
    assert migration.count("VALIDATE CONSTRAINT") == 4


def _live_registry_adapter(
    base_url: str,
    token: str,
) -> ManagedBenchmarkRegistryHttpAdapter:
    return ManagedBenchmarkRegistryHttpAdapter(
        ManagedBenchmarkRegistryHttpConfig(
            base_url=base_url,
            admin_bearer_token=token,
            target_identity_sha256=managed_backend_target_identity_sha256(
                backend_role="infinity-context",
                base_url=base_url,
            ),
            timeout_seconds=10,
            benchmark_deadline=datetime.now(UTC) + timedelta(seconds=30),
            cleanup_recovery_timeout_seconds=10,
        )
    )


@contextmanager
def _isolated_postgres_database() -> Iterator[str]:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    database_name = f"abort_e2e_{uuid.uuid4().hex}"
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    app_url = parsed.set(
        drivername="postgresql+asyncpg",
        database=database_name,
    ).render_as_string(hide_password=False)

    async def create_database() -> None:
        connection = await asyncpg.connect(admin_dsn)
        try:
            await connection.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await connection.close()

    async def drop_database() -> None:
        connection = await asyncpg.connect(admin_dsn)
        try:
            await connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            await connection.close()

    asyncio.run(create_database())
    try:
        yield app_url
    finally:
        asyncio.run(drop_database())
