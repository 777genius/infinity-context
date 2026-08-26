"""Populated 0045 -> 0046 upgrade and reapplication proof."""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresRetrievalProfileRegistry,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.engine import make_url
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_populated_0045_upgrade_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_populated_upgrade(database_url))


async def _assert_populated_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_0046_populated", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0045_")
        raw = await database.connect()
        try:
            await raw.execute(
                """
                INSERT INTO memory_locator_profiles
                  (profile_id,generation,profile_digest,collection_name,state,
                   backfill_complete,canonical_watermark,projected_watermark,
                   expected_count,projected_count,created_at,activated_at,
                   activation_lease_id,activation_evidence_digest,
                   activation_lease_issued_at,activation_lease_expires_at,
                   reconciled_at,reconciliation_drifted,provider_mutation_epoch)
                VALUES
                  ('active-old','generation-active',repeat('a',64),'collection-active','active',
                   TRUE,7,7,1,1,now()-interval '1 hour',now()-interval '30 minutes',
                   'pre0046-lease',repeat('b',64),now()-interval '1 minute',
                   now()+interval '5 minutes',now()-interval '1 minute',FALSE,1),
                  ('retained-old','generation-retained',repeat('c',64),'collection-retained',
                   'retained',TRUE,7,7,1,1,now()-interval '2 hours',NULL,
                   'pre0046-retained-lease',repeat('d',64),now()-interval '2 minutes',
                   now()+interval '4 minutes',now()-interval '2 minutes',FALSE,0);
                INSERT INTO memory_locator_profile_provider_mutations
                  (profile_id,operation_id,started_epoch,started_at,expires_at)
                VALUES ('active-old','writer-old',1,now()-interval '2 minutes',
                        now()-interval '1 minute');
                INSERT INTO memory_locator_profile_cleanups
                  (profile_id,phase,attempt_count,last_error_code,requested_at,updated_at)
                VALUES ('retained-old','waiting_for_jobs',3,'old-writer',now(),now());
                INSERT INTO memory_locator_profile_attestation_checkpoints
                  (profile_id,operation_id,stage,cursor,item_count,digest_accumulator,
                   started_at,updated_at,deadline_at,complete,scan_complete,
                   scan_page_count,validation_page_number,validation_item_count,
                   validation_accumulator,provider_epoch)
                VALUES ('active-old','checkpoint-old','qdrant',NULL,0,repeat('0',64),
                        now(),now(),now()+interval '1 minute',FALSE,FALSE,0,0,0,
                        repeat('0',64),1)
                """
            )
        finally:
            await raw.close()

        sql = (
            Path(__file__).resolve().parents[2]
            / "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
            "migrations/0046_locator_profile_linearizable_fences.sql"
        ).read_text()
        raw = await database.connect()
        try:
            transaction = raw.transaction()
            await transaction.start()
            await raw.execute(sql)
            await transaction.rollback()
            assert await raw.fetchval("SELECT count(*) FROM memory_locator_profiles") == 2
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='memory_locator_profiles' "
                    "AND column_name='activation_evidence_version'"
                )
                == 0
            )
        finally:
            await raw.close()

        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == (
                "0046_locator_profile_linearizable_fences",
                "0047_locator_runtime_supervisor_proofs",
                "0048_locator_lifecycle_release_identity",
            )
            registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            blocker = await engine.connect()
            blocker_transaction = await blocker.begin()
            await blocker.execute(
                text(
                    "SELECT singleton FROM memory_locator_profile_maintenance_fence "
                    "WHERE singleton=TRUE FOR UPDATE"
                )
            )
            await blocker.execute(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton=TRUE FOR UPDATE"
                )
            )
            await blocker.execute(
                text(
                    "SELECT profile_id FROM memory_locator_profiles "
                    "WHERE profile_id='active-old' FOR UPDATE"
                )
            )
            lane_writer = asyncio.create_task(
                registry.update_lane(
                    "active-old",
                    "qdrant_dense",
                    required=True,
                    healthy=True,
                    profile_qualified=True,
                    failure_code=None,
                    checked_at=datetime.now(UTC),
                )
            )
            await asyncio.sleep(0.05)
            assert not lane_writer.done()
            await blocker.execute(
                text(
                    "INSERT INTO memory_locator_profile_lanes "
                    "(profile_id,lane_id,required,healthy,profile_qualified,failure_code,"
                    "checked_at,observed_count,observed_digest) VALUES "
                    "('active-old','rollback-lane',TRUE,TRUE,TRUE,NULL,CURRENT_TIMESTAMP,0,"
                    "repeat('0',64))"
                )
            )
            await blocker_transaction.rollback()
            await blocker.close()
            await asyncio.wait_for(lane_writer, timeout=5)
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_locator_profile_lanes "
                            "WHERE lane_id='rollback-lane'"
                        )
                    )
                    == 0
                )
                rows = (
                    await connection.execute(
                        text(
                            "SELECT profile_id,state,activation_evidence_version,"
                            "activation_mutation_epoch,reconciliation_drifted,"
                            "activation_lease_expires_at <= CURRENT_TIMESTAMP "
                            "FROM memory_locator_profiles ORDER BY profile_id"
                        )
                    )
                ).all()
                assert rows == [
                    ("active-old", "active", 0, 0, True, True),
                    ("retained-old", "retained", 0, 0, False, True),
                ]
                mutation = (
                    await connection.execute(
                        text(
                            "SELECT owner_instance_id,owner_generation "
                            "FROM memory_locator_profile_provider_mutations"
                        )
                    )
                ).one()
                assert tuple(mutation) == ("pre-0046-owner", "pre-0046-generation")
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM memory_locator_profile_attestation_checkpoints")
                    )
                    == 1
                )
                assert (
                    await connection.scalar(
                        text("SELECT phase FROM memory_locator_profile_cleanups")
                    )
                    == "waiting_for_jobs"
                )
                with pytest.raises(Exception, match="pre-0046 Retrieval V2 writers"):
                    await connection.execute(
                        text(
                            "INSERT INTO memory_locator_profile_provider_mutations "
                            "(profile_id,operation_id,started_epoch,started_at,expires_at) "
                            "VALUES ('active-old','old-binary-write',2,CURRENT_TIMESTAMP,"
                            "CURRENT_TIMESTAMP + interval '1 minute')"
                        )
                    )
            # The migration itself is safe to reapply by an operator after an
            # interrupted migration transaction; the migration ledger remains single.
            raw = await database.connect()
            try:
                await raw.execute(sql)
                assert (
                    await raw.fetchval(
                        "SELECT count(*) FROM memory_locator_profile_maintenance_fence"
                    )
                    == 1
                )
                assert (
                    await raw.fetchval(
                        "SELECT count(*) FROM memory_locator_profile_evidence_versions"
                    )
                    == 1
                )
            finally:
                await raw.close()
            with tempfile.TemporaryDirectory(prefix="locator-0046-backup-") as directory:
                backup = str(Path(directory) / "database.dump")
                await _run_pg("pg_dump", "--format=custom", "--file", backup, database.raw_dsn)
                await engine.dispose()
                await database.recreate()
                await _run_pg("pg_restore", "--no-owner", "--dbname", database.raw_dsn, backup)
                restored = await database.connect()
                try:
                    assert (
                        await restored.fetchval("SELECT count(*) FROM memory_locator_profiles") == 2
                    )
                    assert (
                        await restored.fetchval(
                            "SELECT count(*) FROM infinity_context_schema_migrations "
                            "WHERE migration_id='0046_locator_profile_linearizable_fences'"
                        )
                        == 1
                    )
                    assert (
                        await restored.fetchval(
                            "SELECT reconciliation_drifted FROM memory_locator_profiles "
                            "WHERE profile_id='active-old'"
                        )
                        is True
                    )
                finally:
                    await restored.close()
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _run_pg(*arguments: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        if b"server version mismatch" in stderr or b"unsupported version" in stderr:
            await _run_pg_in_backend_container(*arguments)
            return
        raise AssertionError(
            f"disposable PostgreSQL backup command failed ({arguments[0]}): "
            f"{stderr.decode(errors='replace')[:500]}"
        )


async def _run_pg_in_backend_container(*arguments: str) -> None:
    dump = arguments[0] == "pg_dump"
    dsn = arguments[-1] if dump else arguments[-2]
    parsed = make_url(dsn)
    listing = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "--format",
        "{{.ID}} {{.Ports}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await listing.communicate()
    marker = f"127.0.0.1:{parsed.port}->5432/tcp"
    container = next(
        (line.split()[0] for line in stdout.decode().splitlines() if marker in line), None
    )
    if container is None:
        raise AssertionError("matching disposable PostgreSQL backend container was not found")
    password = parsed.password or ""
    common = (
        "docker",
        "exec",
        "-i",
        "-e",
        f"PGPASSWORD={password}",
        container,
    )
    if dump:
        backup = arguments[arguments.index("--file") + 1]
        command = (
            *common,
            "pg_dump",
            "--format=custom",
            "--username",
            parsed.username or "",
            parsed.database or "",
        )
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        data, stderr = await process.communicate()
        if process.returncode == 0:
            Path(backup).write_bytes(data)
    else:
        backup = arguments[-1]
        command = (
            *common,
            "pg_restore",
            "--no-owner",
            "--username",
            parsed.username or "",
            "--dbname",
            parsed.database or "",
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate(Path(backup).read_bytes())
    if process.returncode != 0:
        raise AssertionError(
            f"containerized disposable PostgreSQL {arguments[0]} failed: "
            f"{stderr.decode(errors='replace')[:500]}"
        )
