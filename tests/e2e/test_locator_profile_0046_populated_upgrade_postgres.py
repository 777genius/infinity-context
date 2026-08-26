"""Populated 0045 -> 0046 upgrade and reapplication proof."""

from __future__ import annotations

import asyncio
import os
import re
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
                "0049_reconciliation_runtime_generation",
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
            await _assert_outbox_evidence_invalidation(engine)
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
                client_image = await _run_pg(
                    "pg_dump", "--format=custom", "--file", backup, database.raw_dsn
                )
                await engine.dispose()
                await database.recreate()
                await _run_pg(
                    "pg_restore",
                    "--no-owner",
                    "--dbname",
                    database.raw_dsn,
                    backup,
                    client_image=client_image,
                )
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


async def _assert_outbox_evidence_invalidation(engine) -> None:
    async def snapshot() -> tuple[int, bool, datetime]:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT evidence.aggregate_version, profile.reconciliation_drifted, "
                        "profile.activation_lease_expires_at "
                        "FROM memory_locator_profile_evidence_versions AS evidence "
                        "CROSS JOIN memory_locator_profiles AS profile "
                        "WHERE evidence.singleton=TRUE AND profile.profile_id='active-old'"
                    )
                )
            ).one()
            return row[0], row[1], row[2]

    async def arm_future_lease() -> tuple[int, bool, datetime]:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE memory_locator_profiles "
                    "SET reconciliation_drifted=FALSE, "
                    "activation_lease_issued_at=clock_timestamp()-interval '1 minute', "
                    "activation_lease_expires_at=clock_timestamp()+interval '1 hour' "
                    "WHERE profile_id='active-old'"
                )
            )
        before = await snapshot()
        assert before[1] is False
        return before

    async def assert_invalidates(statement: str) -> None:
        before = await arm_future_lease()
        async with engine.begin() as connection:
            await connection.execute(text(statement))
        # Read through a new committed transaction: the proof is a durable
        # shortening relative to the saved future deadline, not a comparison
        # against transaction-local CURRENT_TIMESTAMP plus one microsecond.
        after = await snapshot()
        assert after[0] == before[0] + 1
        assert after[1] is True
        assert after[2] < before[2]

    unrelated_insert = """
        INSERT INTO memory_outbox
          (message_key,event_type,aggregate_type,aggregate_id,aggregate_version,
           workload_class,fairness_key,payload_json,status,attempt_count,
           next_attempt_at,created_at,updated_at)
        VALUES
          ('profile-evidence-unrelated','probe.unrelated','probe','unrelated-probe',1,
           'projection','probe:unrelated','{}'::jsonb,'pending',0,
           clock_timestamp(),clock_timestamp(),clock_timestamp())
    """
    baseline = await arm_future_lease()
    async with engine.begin() as connection:
        await connection.execute(text(unrelated_insert))
    assert await snapshot() == baseline
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE memory_outbox SET attempt_count=attempt_count+1 "
                "WHERE message_key='profile-evidence-unrelated'"
            )
        )
    assert await snapshot() == baseline
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM memory_outbox WHERE message_key='profile-evidence-unrelated'")
        )
    assert await snapshot() == baseline

    await assert_invalidates(
        """
        INSERT INTO memory_outbox
          (message_key,event_type,aggregate_type,aggregate_id,aggregate_version,
           workload_class,fairness_key,payload_json,status,attempt_count,
           next_attempt_at,created_at,updated_at)
        VALUES
          ('profile-evidence-relevant','vector.upsert_locator_profile','probe',
           'relevant-probe',1,'projection','probe:relevant','{}'::jsonb,'pending',0,
           clock_timestamp(),clock_timestamp(),clock_timestamp())
        """
    )
    await assert_invalidates(
        "UPDATE memory_outbox SET event_type='probe.unrelated' "
        "WHERE message_key='profile-evidence-relevant'"
    )
    await assert_invalidates(
        "UPDATE memory_outbox SET event_type='vector.delete_locator_profile' "
        "WHERE message_key='profile-evidence-relevant'"
    )
    await assert_invalidates(
        "DELETE FROM memory_outbox WHERE message_key='profile-evidence-relevant'"
    )


async def _run_pg(*arguments: str, client_image: str | None = None) -> str | None:
    if client_image is not None:
        await _run_pg_in_client_container(*arguments, client_image=client_image)
        return client_image
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        if b"server version mismatch" in stderr or b"unsupported version" in stderr:
            match = re.search(rb"server version:\s*(\d+)", stderr)
            if match is not None:
                client_image = f"postgres:{match.group(1).decode()}"
                await _run_pg_in_client_container(*arguments, client_image=client_image)
                return client_image
        raise AssertionError(
            f"disposable PostgreSQL backup command failed ({arguments[0]}): "
            f"{stderr.decode(errors='replace')[:500]}"
        )
    return None


async def _run_pg_in_client_container(*arguments: str, client_image: str) -> None:
    dump = arguments[0] == "pg_dump"
    dsn = arguments[-1] if dump else arguments[-2]
    parsed = make_url(dsn)
    container_arguments = list(arguments[1:])
    if dump:
        file_index = container_arguments.index("--file")
        backup = container_arguments[file_index + 1]
        del container_arguments[file_index : file_index + 2]
    else:
        backup = container_arguments.pop()
    container_arguments[-1] = parsed.set(password=None).render_as_string(hide_password=False)
    process_environment = os.environ.copy()
    process_environment["PGPASSWORD"] = parsed.password or ""
    command = (
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "-i",
        "-e",
        "PGPASSWORD",
        client_image,
        arguments[0],
        *container_arguments,
    )
    if dump:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_environment,
        )
        data, stderr = await process.communicate()
        if process.returncode == 0:
            Path(backup).write_bytes(data)
    else:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=process_environment,
        )
        _, stderr = await process.communicate(Path(backup).read_bytes())
    if process.returncode != 0:
        raise AssertionError(
            f"containerized PostgreSQL client {arguments[0]} failed: "
            f"{stderr.decode(errors='replace')[:500]}"
        )
