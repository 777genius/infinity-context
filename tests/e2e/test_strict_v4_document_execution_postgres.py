"""Authenticated LongMemEval preparation to one canonical document write."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.strict_v4_writer_authority import (
    AsyncPostgresStrictV4WriterAuthority,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkEnsureScopeAdmission,
)
from infinity_context_core.application.dto import EnsureScopeCommand, IngestDocumentCommand
from infinity_context_core.application.use_cases.ensure_scope import EnsureScopeUseCase
from infinity_context_core.application.use_cases.ingest_document import IngestDocumentUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentWriteError,
)
from infinity_context_server.memory_comparison_backend_target import FullComparisonBackendTarget
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
    sanitize_source_refs,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_document_execution import (
    recover_strict_v4_document_authority,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    prepare_strict_v4_full_run,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_writer_authority import (
    recover_and_seal_strict_v4_writer_authority,
)
from infinity_context_server.original_pair_identity_authority import (
    SQLiteOriginalPairIdentityAuthority,
)
from postgres_test_database import (
    STRICT_V4_TEST_ROLE_PASSWORD,
    PostgresTestDatabase,
)
from sqlalchemy.engine import make_url
from strict_v4_cleanup_derivation_support import (
    ARTIFACT_KEY,
    PREPARATION_AUTH,
    ArtifactKeys,
    preparation_inputs,
)


def test_authenticated_longmemeval_document_execution_when_configured(tmp_path: Path) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    dataset = Path("/tmp/infinity_context_longmemeval_s_cleaned.json")
    if not database_url or not dataset.is_file():
        pytest.skip("PostgreSQL or the staged official LongMemEval fixture is unavailable")
    asyncio.run(_assert_authenticated_document_execution(database_url, dataset, tmp_path))


async def _assert_authenticated_document_execution(
    database_url: str,
    dataset: Path,
    tmp_path: Path,
) -> None:
    started = time.monotonic()

    def phase(name: str) -> None:
        print(
            f"strict-v4-document phase={name} elapsed={time.monotonic() - started:.2f}s", flush=True
        )

    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_document_execution",
        asyncpg=asyncpg,
    )
    runtime_roles: list[str] = []
    pair_authority = None
    runtime_engine = None
    await database.recreate()
    phase("database-recreated")
    try:
        migration_engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(migration_engine)
            assert result.current == "0054_locator_profile_exact_delete_generation"
        finally:
            await migration_engine.dispose()
        phase("schema-upgraded")

        dataset_bytes = dataset.read_bytes()
        projection, manifest = _projection(dataset_bytes)
        phase("projection-built")
        pair_path = tmp_path / "original-pairs.sqlite3"
        pair_authority = SQLiteOriginalPairIdentityAuthority.create(
            pair_path,
            dataset_bytes=dataset_bytes,
            authentication_key=ARTIFACT_KEY,
        )
        phase("original-pair-built")
        projector = ManagedV5CleanupV4OperationProjector(
            projection=projection,
            manifest_authority=manifest,
            admission_commitment_sha256="f" * 64,
            profile_id="mem0-longmemeval-top50-v1",
            original_pair_authority=pair_authority,
        )
        run_id = hashlib.sha256(projection.bindings.run_id.encode()).hexdigest()
        inputs = replace(
            preparation_inputs(tmp_path, projection, manifest, run_id),
            original_pair_path=str(pair_path),
            original_pair_key_id="pair-key",
            space_slug="strict-v4-document-execution",
        )

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
        canonical_writer_role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer",
            suffix="canonical_writer",
        )
        runtime_roles.append(canonical_writer_role)
        await _insert_pristine_run(database, inputs, projection, run_id)
        phase("runtime-roles-and-run-ready")

        async def registrar_connect():
            return await database.connect_as_runtime_role(registrar_role)

        registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
            connect=registrar_connect,
            authenticator=PREPARATION_AUTH,
        )
        registered_at = await _database_now(database)
        receipt_path = tmp_path / "receipt.sqlite3"
        receipt_store = SQLiteStrictV4PreparationReceiptStore.create(receipt_path)
        try:
            receipt = await prepare_strict_v4_full_run(
                projector=projector,
                inputs=inputs,
                registration_port=registry,
                receipt_store=receipt_store,
                key_identity_authority=ArtifactKeys(),
                authenticator=PREPARATION_AUTH,
                registered_at=registered_at,
                prepared_at=registered_at,
            )
        finally:
            receipt_store.close()
        phase("full-preparation-committed")
        assert receipt.profile_id == "mem0-longmemeval-top50-v1"
        assert receipt.a2_authority.operation_count == 124_344
        assert receipt.provider_calls == 0
        assert receipt.paid_go_ready is False

        receipt_store = SQLiteStrictV4PreparationReceiptStore.open(receipt_path)
        try:
            writer = await recover_and_seal_strict_v4_writer_authority(
                receipt_store=receipt_store,
                registration_port=registry,
                writer_authority_port=AsyncPostgresStrictV4WriterAuthority(
                    connect=lambda: database.connect_as_runtime_role(sealer_role),
                    authenticator=PREPARATION_AUTH,
                ),
                authenticator=PREPARATION_AUTH,
                key_identity_authority=ArtifactKeys(),
                sealed_at=await _database_now(database),
            )
        finally:
            receipt_store.close()
        phase("writer-authority-sealed")
        assert writer.provider_calls == 0
        assert writer.paid_go_ready is False

        receipt_store = SQLiteStrictV4PreparationReceiptStore.open(receipt_path)
        authority = await recover_strict_v4_document_authority(
            receipt_store=receipt_store,
            registration_port=registry,
            authenticator=PREPARATION_AUTH,
            key_identity_authority=ArtifactKeys(),
            expected_projector=projector,
        )
        receipt_store.close()
        phase("document-authority-recovered")
        try:
            runtime_url = make_url(database.app_url).set(
                username=canonical_writer_role,
                password=STRICT_V4_TEST_ROLE_PASSWORD,
            )
            runtime_engine = build_async_engine(runtime_url.render_as_string(hide_password=False))
            clock = SystemClock()
            uow = PostgresUnitOfWorkFactory(
                session_factory=build_session_factory(runtime_engine),
                clock=clock,
            )
            corpus = next(projector.iter_reconstructed_corpora())
            document = next(iter(conversation_documents(corpus)))
            scope = await ManagedBenchmarkEnsureScopeAdmission(
                uow_factory=uow,
                inner=EnsureScopeUseCase(uow_factory=uow, clock=clock),
                strict_v4_authority=authority,
            ).execute(
                EnsureScopeCommand(
                    space_slug=inputs.space_slug,
                    memory_scope_external_ref=corpus.memory_scope_external_ref,
                    thread_external_ref=corpus.thread_external_ref,
                )
            )
            command = IngestDocumentCommand(
                space_id=SpaceId(str(scope.space_id)),
                memory_scope_id=MemoryScopeId(str(scope.memory_scope_id)),
                thread_id=ThreadId(str(scope.thread_id)),
                title=document.title,
                text=document.text,
                source_type=document.source_type,
                source_external_id=document.source_external_id,
                classification=document.classification,
                chunk_metadata={"source_refs": list(sanitize_source_refs(document.source_refs))},
            )
            ingest = IngestDocumentUseCase(
                uow_factory=uow,
                clock=clock,
                ids=UuidIdGenerator(),
                strict_v4_authority=authority,
            )
            first = await ingest.execute(command)
            replay = await ingest.execute(command)
            assert first.indexing_status == "pending"
            assert replay.indexing_status == "already_indexed_or_pending"
            assert replay.document.id == first.document.id
            with pytest.raises(
                ManagedBenchmarkStrictV4DocumentWriteError,
                match="managed_benchmark_strict_v4_document_write_operation_invalid",
            ):
                await ingest.execute(replace(command, text=command.text + " tampered"))
            phase("document-ingested-replayed-and-tamper-rejected")
        finally:
            authority.close()

        admin = await database.connect()
        try:
            counts = await admin.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM memory_documents) AS documents,
                  (SELECT count(*) FROM memory_chunks) AS chunks,
                  (SELECT count(*) FROM memory_outbox) AS outbox,
                  (SELECT count(*) FROM memory_idempotency_records) AS receipts
                """
            )
        finally:
            await admin.close()
        assert tuple(counts.values()) == (1, len(first.chunks), len(first.chunks), 1)
        phase("canonical-counts-verified")
    finally:
        if runtime_engine is not None:
            await runtime_engine.dispose()
        if pair_authority is not None:
            pair_authority.close()
        try:
            await database.drop()
        finally:
            await database.drop_runtime_roles(*runtime_roles)


def _projection(dataset_bytes: bytes):
    profile = resolve_full_comparison_profile("mem0-longmemeval-top50-v1")
    assert profile is not None
    projection = build_managed_public_run_projection(
        run_id="strict-v4-document-execution",
        run_nonce_commitment_sha256="9" * 64,
        runtime_probe_nonce_sha256="e" * 64,
        profile=profile,
        dataset_bytes=dataset_bytes,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "a" * 64),
            FullComparisonBackendTarget("mem0", "b" * 64),
        ),
        scope="full",
    )
    manifest = ManagedMem0V5ManifestProjector().project(
        projection.cases,
        current_date="2026-08-10",
    )
    return projection, manifest


async def _insert_pristine_run(database, inputs, projection, run_id: str) -> None:
    connection = await database.connect()
    try:
        await connection.execute(
            "INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at) "
            "VALUES($1,$2,'strict-v4 document','active',clock_timestamp(),clock_timestamp())",
            inputs.space_id,
            inputs.space_slug,
        )
        await connection.execute(
            """INSERT INTO memory_comparison_benchmark_runs(
            run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
            space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
            state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,created_at,updated_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',
                   clock_timestamp(),clock_timestamp())""",
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
