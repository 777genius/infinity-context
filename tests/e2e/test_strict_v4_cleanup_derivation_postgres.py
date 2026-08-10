"""Fresh-PostgreSQL proof for provider-free strict-v4 cleanup derivation."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.managed_cleanup_v4_sqlite_journal import (
    SQLiteManagedCleanupV4Journal,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.strict_v4_cleanup_authority import (
    AsyncPostgresStrictV4CleanupAuthorityReader,
)
from infinity_context_adapters.postgres.strict_v4_writer_authority import (
    AsyncPostgresStrictV4WriterAuthority,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_server.memory_comparison_backend_target import FullComparisonBackendTarget
from infinity_context_server.memory_comparison_full_profiles import resolve_full_comparison_profile
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_cleanup import (
    initiate_strict_v4_cleanup,
    recover_strict_v4_cleanup,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    prepare_strict_v4_full_run,
    recover_strict_v4_full_run,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_writer_authority import (
    recover_and_seal_strict_v4_writer_authority,
)
from postgres_test_database import PostgresTestDatabase
from strict_v4_cleanup_derivation_support import (
    PREPARATION_AUTH,
    ArtifactKeys,
    preparation_inputs,
)

CLEANUP_KEY = b"strict-v4-cleanup-derivation-journal-key" * 2
CLEANUP_AUTH = ProjectionReceiptAuthenticator(CLEANUP_KEY)
CLEANUP_KEY_ID = "strict-v4-cleanup-key"


class _CleanupKeys:
    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        if purpose != "strict-v4-cleanup-journal" or key_id != CLEANUP_KEY_ID:
            raise ValueError("unexpected strict-v4 cleanup key binding")
        return CLEANUP_KEY


def test_cleanup_derivation_requires_recovered_and_sealed_evidence_when_configured(
    tmp_path: Path,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    dataset = Path("/tmp/locomo10.ingestion-manifest-r1.json")
    if not database_url or not dataset.is_file():
        pytest.skip("PostgreSQL or the staged official LoCoMo fixture is unavailable")
    asyncio.run(_assert_cleanup_derivation(database_url, dataset, tmp_path))


async def _assert_cleanup_derivation(database_url: str, dataset: Path, tmp_path: Path) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="strict_v4_cleanup_derivation", asyncpg=asyncpg
    )
    await database.recreate()
    runtime_roles: list[str] = []
    try:
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
        finally:
            await engine.dispose()
        projection, manifest, projector, run_id = _projection(dataset)
        registrar_role = await database.create_runtime_role(
            capability_role="infinity_context_strict_v4_registrar",
            suffix="registrar",
        )
        runtime_roles.append(registrar_role)
        sealer_role = await database.create_runtime_role(
            capability_role="infinity_context_strict_v4_sealer",
            suffix="sealer",
        )
        runtime_roles.append(sealer_role)
        await _install_hostile_shadows(database, runtime_roles)
        inputs = preparation_inputs(tmp_path, projection, manifest, run_id)
        await _insert_pristine_run(database, inputs, projection, run_id)

        async def registrar_connect():
            return await _connect_hostile_runtime(database, registrar_role)

        registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
            connect=registrar_connect, authenticator=PREPARATION_AUTH
        )
        registered_at = await _database_now(database)
        receipt_path = tmp_path / "receipt.sqlite3"
        store = SQLiteStrictV4PreparationReceiptStore.create(receipt_path)
        try:
            receipt = await prepare_strict_v4_full_run(
                projector=projector,
                inputs=inputs,
                registration_port=registry,
                receipt_store=store,
                key_identity_authority=ArtifactKeys(),
                authenticator=PREPARATION_AUTH,
                registered_at=registered_at,
                prepared_at=registered_at,
            )
        finally:
            store.close()
        store = SQLiteStrictV4PreparationReceiptStore.open(receipt_path)
        try:
            writer = await recover_and_seal_strict_v4_writer_authority(
                receipt_store=store,
                registration_port=registry,
                writer_authority_port=AsyncPostgresStrictV4WriterAuthority(
                    connect=lambda: _connect_hostile_runtime(database, sealer_role),
                    authenticator=PREPARATION_AUTH,
                ),
                authenticator=PREPARATION_AUTH,
                key_identity_authority=ArtifactKeys(),
                sealed_at=await _database_now(database),
            )
        finally:
            store.close()

        recovery_calls = 0

        async def recover_preparation():
            nonlocal recovery_calls
            recovery_calls += 1
            reopened = SQLiteStrictV4PreparationReceiptStore.open(receipt_path)
            try:
                return await recover_strict_v4_full_run(
                    receipt_store=reopened,
                    registration_port=registry,
                    authenticator=PREPARATION_AUTH,
                    key_identity_authority=ArtifactKeys(),
                )
            finally:
                reopened.close()

        reader = AsyncPostgresStrictV4CleanupAuthorityReader(
            connect=lambda: _connect_hostile_runtime(database, sealer_role),
            recover_preparation=recover_preparation,
            preparation_authenticator=PREPARATION_AUTH,
            readback_authenticator=CLEANUP_AUTH,
            authentication_key_id=CLEANUP_KEY_ID,
        )
        readback = await reader.read_registered_strict_v4(run_id)
        assert readback is not None
        assert (
            readback.run_id_sha256,
            readback.context_sha256,
            readback.a2_terminal_sha256,
            readback.expected_index_terminal_sha256,
        ) == (
            receipt.run_id_sha256,
            receipt.a2_context.context_sha256,
            receipt.a2_authority.terminal_commitment_sha256,
            receipt.expected_index_terminal_sha256,
        )
        assert (
            readback.preparation_receipt_sha256,
            readback.preparation_receipt_mac_sha256,
            readback.registration_sha256,
            readback.registration_mac_sha256,
            readback.writer_authority_sha256,
            readback.writer_authority_mac_sha256,
        ) == (
            receipt.receipt_sha256,
            receipt.receipt_mac_sha256,
            receipt.registration_sha256,
            receipt.registration_mac_sha256,
            writer.writer_authority_sha256,
            writer.writer_authority_mac_sha256,
        )
        row = await _writer_row(database, run_id)
        assert row["provider_calls"] == receipt.provider_calls == writer.provider_calls == 0
        assert row["paid_go_ready"] is receipt.paid_go_ready is writer.paid_go_ready is False
        assert await _registered_at(database, run_id) == receipt.registered_at

        journal = SQLiteManagedCleanupV4Journal.create(
            tmp_path / "cleanup-journal.sqlite3",
            readback=readback,
            authentication_key_id=CLEANUP_KEY_ID,
            key_identity_authority=_CleanupKeys(),
        )
        try:
            initiated = await initiate_strict_v4_cleanup(
                journal=journal, key_identity_authority=_CleanupKeys()
            )
            recovered = await recover_strict_v4_cleanup(
                journal=journal, key_identity_authority=_CleanupKeys()
            )
            assert initiated.replayed is False
            assert recovered.initiation == initiated.receipt
            assert recovered.terminal is None
        finally:
            journal.close()

        await _tamper_writer_mac(database, run_id, "0" * 64)
        with pytest.raises(ProjectionReceiptError, match="writer_authority_invalid"):
            await reader.read_registered_strict_v4(run_id)
        await _tamper_writer_mac(database, run_id, writer.writer_authority_mac_sha256)

        saved_writer = await _delete_writer(database, run_id)
        with pytest.raises(ProjectionReceiptError, match="cleanup_readback_collision"):
            await reader.read_registered_strict_v4(run_id)
        await _restore_writer(database, saved_writer)

        await _set_registered_at(database, run_id, receipt.registered_at.replace(year=2025))
        with pytest.raises(ProjectionReceiptError, match="preparation_registration_invalid"):
            await reader.read_registered_strict_v4(run_id)
        await _set_registered_at(database, run_id, receipt.registered_at)
        assert recovery_calls == 4
    finally:
        try:
            await database.drop()
        finally:
            await database.drop_runtime_roles(*runtime_roles)


def _projection(dataset: Path):
    profile = resolve_full_comparison_profile("mem0-locomo-top50-v1")
    assert profile is not None
    projection = build_managed_public_run_projection(
        run_id="strict-v4-cleanup-derivation",
        run_nonce_commitment_sha256="9" * 64,
        runtime_probe_nonce_sha256="e" * 64,
        profile=profile,
        dataset_bytes=dataset.read_bytes(),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "a" * 64),
            FullComparisonBackendTarget("mem0", "b" * 64),
        ),
        scope="full",
    )
    manifest = ManagedMem0V5ManifestProjector().project(projection.cases, current_date="2026-08-10")
    projector = ManagedV5CleanupV4OperationProjector(
        projection=projection,
        manifest_authority=manifest,
        admission_commitment_sha256="f" * 64,
        profile_id="mem0-locomo-top50-v1",
    )
    return (
        projection,
        manifest,
        projector,
        hashlib.sha256(projection.bindings.run_id.encode()).hexdigest(),
    )


async def _insert_pristine_run(database, inputs, projection, run_id: str) -> None:
    connection = await database.connect()
    try:
        await connection.execute(
            "INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at) "
            "VALUES($1,$2,'strict-v4 cleanup','active',clock_timestamp(),clock_timestamp())",
            inputs.space_id,
            inputs.space_slug,
        )
        await connection.execute(
            """INSERT INTO memory_comparison_benchmark_runs(
            run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
            space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
            state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,created_at,updated_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',clock_timestamp(),clock_timestamp())""",
            run_id,
            projection.bindings.binding_commitment_sha256,
            inputs.infinity_target_identity_sha256,
            inputs.space_id,
            inputs.space_slug,
            "c" * 64,
            "d" * 64,
        )
    finally:
        await connection.close()


async def _database_now(database):
    connection = await database.connect()
    try:
        return await connection.fetchval("SELECT clock_timestamp()")
    finally:
        await connection.close()


async def _install_hostile_shadows(database, runtime_roles: list[str]) -> None:
    connection = await database.connect()
    try:
        await connection.execute("CREATE SCHEMA hostile")
        await connection.execute(
            "CREATE TABLE hostile.memory_cleanup_v3_context_authorities "
            "(LIKE public.memory_cleanup_v3_context_authorities INCLUDING ALL)"
        )
        await connection.execute(
            "CREATE TABLE hostile.memory_comparison_strict_v4_preparations "
            "(LIKE public.memory_comparison_strict_v4_preparations INCLUDING ALL)"
        )
        for role in runtime_roles:
            await connection.execute(f'GRANT USAGE ON SCHEMA hostile TO "{role}"')
    finally:
        await connection.close()


async def _connect_hostile_runtime(database, role: str):
    connection = await database.connect_as_runtime_role(role)
    try:
        await connection.execute(
            "CREATE TEMP TABLE memory_cleanup_v3_context_authorities (shadow text)"
        )
        await connection.execute(
            "CREATE TEMP TABLE memory_comparison_strict_v4_preparations (shadow text)"
        )
        await connection.execute("SET search_path=pg_temp,hostile,public")
    except BaseException:
        await connection.close()
        raise
    return connection


async def _writer_row(database, run_id: str):
    connection = await database.connect()
    try:
        row = await connection.fetchrow(
            "SELECT * FROM memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1", run_id
        )
        assert row is not None
        return row
    finally:
        await connection.close()


async def _registered_at(database, run_id: str):
    connection = await database.connect()
    try:
        return await connection.fetchval(
            "SELECT registered_at FROM memory_cleanup_v3_context_authorities WHERE run_id_sha256=$1",
            run_id,
        )
    finally:
        await connection.close()


async def _tamper_writer_mac(database, run_id: str, value: str) -> None:
    connection = await database.connect()
    try:
        await connection.execute(
            "ALTER TABLE memory_comparison_strict_v4_preparations DISABLE TRIGGER trg_strict_v4_preparation_immutable"
        )
        await connection.execute(
            """UPDATE memory_comparison_strict_v4_preparations
            SET writer_authority_json=jsonb_set(writer_authority_json,'{writer_authority_mac_sha256}',to_jsonb($2::text)),
                writer_authority_mac_sha256=$2 WHERE run_id_sha256=$1""",
            run_id,
            value,
        )
        await connection.execute(
            "ALTER TABLE memory_comparison_strict_v4_preparations ENABLE TRIGGER trg_strict_v4_preparation_immutable"
        )
    finally:
        await connection.close()


async def _delete_writer(database, run_id: str):
    connection = await database.connect()
    try:
        row = await connection.fetchrow(
            "SELECT * FROM memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1", run_id
        )
        assert row is not None
        await connection.execute(
            "ALTER TABLE memory_comparison_strict_v4_preparations DISABLE TRIGGER trg_strict_v4_preparation_immutable"
        )
        await connection.execute(
            "DELETE FROM memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1", run_id
        )
        await connection.execute(
            "ALTER TABLE memory_comparison_strict_v4_preparations ENABLE TRIGGER trg_strict_v4_preparation_immutable"
        )
        return row
    finally:
        await connection.close()


async def _restore_writer(database, row) -> None:
    connection = await database.connect()
    try:
        columns = tuple(row.keys())
        placeholders = ",".join(f"${index}" for index in range(1, len(columns) + 1))
        await connection.execute(
            f"INSERT INTO memory_comparison_strict_v4_preparations ({','.join(columns)}) VALUES({placeholders})",
            *(row[column] for column in columns),
        )
    finally:
        await connection.close()


async def _set_registered_at(database, run_id: str, value) -> None:
    connection = await database.connect()
    try:
        await connection.execute(
            "ALTER TABLE memory_cleanup_v3_context_authorities DISABLE TRIGGER trg_cleanup_v3_context_authority_immutable"
        )
        await connection.execute(
            "UPDATE memory_cleanup_v3_context_authorities SET registered_at=$2 WHERE run_id_sha256=$1",
            run_id,
            value,
        )
        await connection.execute(
            "ALTER TABLE memory_cleanup_v3_context_authorities ENABLE TRIGGER trg_cleanup_v3_context_authority_immutable"
        )
    finally:
        await connection.close()
