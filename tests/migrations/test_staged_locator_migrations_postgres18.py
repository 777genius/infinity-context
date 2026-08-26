"""Disposable PostgreSQL 18 populated upgrade coverage for locator staging."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

import asyncpg
import pytest
from infinity_context_adapters.postgres.migration_runner import (
    _load_migrations,
    upgrade_schema,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_CONTAINER = "infinity-context-pr57-staged-migrations-pg18"
_PASSWORD = "pr57-disposable-only"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("docker", *args), check=check, capture_output=True, text=True, timeout=120
    )


@pytest.mark.skipif(
    os.environ.get("INFINITY_CONTEXT_RUN_POSTGRES18_MIGRATION_TEST") != "1",
    reason="set INFINITY_CONTEXT_RUN_POSTGRES18_MIGRATION_TEST=1 for disposable Docker test",
)
def test_populated_0038_upgrade_stages_0039_and_0040_on_postgresql_18() -> None:
    """Use only the exact disposable container name and remove only what we create."""

    if shutil.which("docker") is None:
        pytest.skip("docker is unavailable")
    existing = _docker("container", "inspect", _CONTAINER, check=False)
    assert existing.returncode != 0, f"refusing to touch existing container {_CONTAINER}"
    owned = False
    try:
        _docker(
            "run",
            "--detach",
            "--name",
            _CONTAINER,
            "--env",
            f"POSTGRES_PASSWORD={_PASSWORD}",
            "--publish",
            "127.0.0.1::5432",
            "postgres:18.4-bookworm",
        )
        owned = True
        for _ in range(60):
            ready = _docker(
                "exec", _CONTAINER, "pg_isready", "-U", "postgres", check=False
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail("disposable PostgreSQL 18 container did not become ready")
        published = _docker("port", _CONTAINER, "5432/tcp").stdout.strip()
        port = int(published.rsplit(":", 1)[1])
        asyncio.run(_exercise_populated_upgrade(port))
    finally:
        if owned:
            _docker("rm", "--force", _CONTAINER, check=False)


async def _exercise_populated_upgrade(port: int) -> None:
    dsn = f"postgresql://postgres:{_PASSWORD}@127.0.0.1:{port}/postgres"
    connection = await asyncpg.connect(dsn)
    try:
        root = Path(__file__).resolve().parents[2]
        provisioning = root / (
            "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
            "provisioning/strict_v4_roles.sql"
        )
        await connection.execute(provisioning.read_text())
        migrations = _load_migrations()
        prefix = tuple(
            migration
            for migration in migrations
            if migration.migration_id <= "0038_strict_v4_document_writer"
        )
        expected_suffix = tuple(
            migration.migration_id for migration in migrations[len(prefix) :]
        )
        for migration in prefix:
            await connection.execute(migration.sql)
        await connection.execute(
            """
            INSERT INTO memory_spaces VALUES (
                'space-stage', 'space-stage', 'Stage', 'active', now(), now()
            );
            INSERT INTO memory_scopes VALUES (
                'scope-stage', 'space-stage', 'scope-stage', 'Stage', 'active', now(), now()
            );
            INSERT INTO memory_documents (
                id, space_id, memory_scope_id, title, source_type, source_external_id,
                content_hash, classification, status, created_at, updated_at
            ) VALUES (
                'document-stage', 'space-stage', 'scope-stage', 'Stage', 'file',
                'stage.txt', 'document-hash', 'internal', 'active', now(), now()
            );
            INSERT INTO memory_chunks (
                id, space_id, memory_scope_id, document_id, source_type,
                source_external_id, source_hash, kind, text, normalized_text,
                status, sequence, char_start, char_end, token_estimate,
                classification, created_at, updated_at, metadata_json
            ) SELECT
                'chunk-' || value, 'space-stage', 'scope-stage', 'document-stage',
                'file', 'stage.txt', 'chunk-hash-' || value, 'text',
                'seed ' || value, 'seed ' || value, 'active', value,
                value * 10, value * 10 + 5, 2, 'internal', now(), now(), '{}'::jsonb
            FROM generate_series(0, 2000) AS value;
            INSERT INTO memory_outbox (
                event_type, aggregate_type, aggregate_id, aggregate_version,
                payload_json, status, attempt_count, next_attempt_at, created_at, updated_at
            ) SELECT
                'vector.upsert_chunk', 'chunk', 'chunk-' || value, 2147483647 - value,
                jsonb_build_object('chunk_id', 'chunk-' || value),
                'pending', 0, now(), now(), now()
            FROM generate_series(0, 2000) AS value;
            INSERT INTO memory_comparison_benchmark_runs (
                run_id_sha256, binding_commitment_sha256,
                infinity_target_identity_sha256, space_id, space_slug,
                idempotency_key_sha256, registration_fingerprint_sha256,
                state, created_at, updated_at
            ) VALUES (
                repeat('a', 64), repeat('b', 64), repeat('c', 64),
                'space-stage', 'space-stage', repeat('d', 64), repeat('e', 64),
                'active', now(), now()
            );
            INSERT INTO memory_cleanup_v3_context_authorities (
                run_id_sha256, context_sha256, authority_terminal_sha256,
                context_json, authority_json, registration_sha256,
                registration_mac_sha256, registered_at
            ) VALUES (
                repeat('a', 64), repeat('b', 64), repeat('c', 64),
                '{}'::jsonb, '{}'::jsonb, repeat('d', 64), repeat('e', 64), now()
            );
            INSERT INTO memory_projection_result_receipts (
                outbox_id, run_id_sha256, context_sha256, lane, operation,
                result_state, space_id, memory_scope_id, aggregate_type,
                aggregate_id, aggregate_version, target_authority_sha256,
                worker_authority_sha256, outbox_event_commitment_sha256,
                identity_count, ordered_identity_root_sha256, lineage_root_sha256,
                provider_completed_at, persisted_at, receipt_sha256, receipt_mac_sha256
            ) VALUES (
                (SELECT id FROM memory_outbox WHERE aggregate_id = 'chunk-0'),
                repeat('a', 64), repeat('b', 64), 'qdrant', 'upsert', 'present',
                'space-stage', 'scope-stage', 'chunk', 'chunk-0', 2147483647,
                repeat('c', 64), repeat('d', 64), repeat('e', 64), 1,
                repeat('a', 64), repeat('b', 64), now(), now(),
                repeat('c', 64), repeat('d', 64)
            );
            CREATE TABLE public.infinity_context_schema_migrations (
                migration_id VARCHAR(160) PRIMARY KEY,
                checksum VARCHAR(64) NOT NULL,
                execution_kind VARCHAR(32) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_infinity_context_schema_migration_kind
                    CHECK (execution_kind IN ('applied', 'legacy_baseline'))
            );
            """
        )
        await connection.executemany(
            """
            INSERT INTO public.infinity_context_schema_migrations
                (migration_id, checksum, execution_kind)
            VALUES ($1, $2, 'applied')
            """,
            [(migration.migration_id, migration.checksum) for migration in prefix],
        )
    finally:
        await connection.close()

    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        result = await upgrade_schema(engine)
        assert result.applied[0:2] == (
            "0039_locator_retrieval_attributes",
            "0040_locator_profile_lifecycle",
        )
        assert result.applied == expected_suffix
        assert result.current == migrations[-1].migration_id
        assert result.applied[-1] == result.current
        async with engine.connect() as verification:
            shape = {
                name: (data_type, is_nullable)
                for name, data_type, is_nullable in (
                    (
                        await verification.execute(
                            text(
                                """
                                SELECT table_name || '.' || column_name,
                                       data_type, is_nullable
                                FROM information_schema.columns
                                WHERE table_schema = 'public' AND (
                                    (table_name = 'memory_outbox'
                                     AND column_name = 'aggregate_version') OR
                                    (table_name = 'memory_projection_result_receipts'
                                     AND column_name = 'aggregate_version') OR
                                    (table_name = 'memory_chunks'
                                     AND column_name = 'retrieval_commit_watermark')
                                )
                                """
                            )
                        )
                    ).all()
                )
            }
            assert shape == {
                "memory_outbox.aggregate_version": ("bigint", "YES"),
                "memory_projection_result_receipts.aggregate_version": ("bigint", "YES"),
                "memory_chunks.retrieval_commit_watermark": ("bigint", "NO"),
            }
            outbox_shape = (
                await verification.execute(
                    text(
                        """
                        SELECT count(*), min(aggregate_version), max(aggregate_version)
                        FROM memory_outbox
                        """
                    )
                )
            ).one()
            receipt_version = await verification.scalar(
                text(
                    """
                    SELECT aggregate_version FROM memory_projection_result_receipts
                    WHERE aggregate_id = 'chunk-0'
                    """
                )
            )
            chunk_shape = (
                await verification.execute(
                    text(
                        """
                        SELECT count(*), count(retrieval_commit_watermark),
                               min(char_start), max(char_end)
                        FROM memory_chunks
                        """
                    )
                )
            ).one()
            transient_columns = await verification.scalar(
                text(
                    """
                    SELECT count(*) FROM information_schema.columns
                    WHERE table_schema='public' AND (
                        column_name = 'aggregate_version_bigint'
                        OR column_name = 'aggregate_version_integer_old'
                    )
                    """
                )
            )
            receipt_constraint = await verification.scalar(
                text(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname = 'uq_projection_receipt_canonical_job'
                      AND conrelid = 'public.memory_projection_result_receipts'::regclass
                    """
                )
            )
            staged_index = await verification.scalar(
                text(
                    """
                    SELECT to_regclass(
                        'public.uq_projection_receipt_canonical_job_bigint_stage'
                    )
                    """
                )
            )
        assert outbox_shape == (2001, 2_147_481_647, 2_147_483_647)
        assert receipt_version == 2_147_483_647
        assert chunk_shape == (2001, 2001, 0, 20005)
        assert transient_columns == 0
        assert receipt_constraint is not None
        assert "aggregate_version" in receipt_constraint
        assert "NULLS NOT DISTINCT" in receipt_constraint
        assert staged_index is None
    finally:
        await engine.dispose()
