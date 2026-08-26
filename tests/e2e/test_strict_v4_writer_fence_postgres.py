"""Fresh PostgreSQL 18 proof for strict-v4 writer authority and XOR fence."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from infinity_context_adapters.features.memory_facts import (
    create_memory_fact_id_adapter,
    create_postgres_memory_fact_unit_of_work_factory,
)
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_INITIAL_INSERT_TABLES,
    BENCHMARK_WRITER_FENCE_CONSTRAINT,
    BENCHMARK_WRITER_FENCE_TABLES,
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
from infinity_context_core.features.memory_facts.application.commands import (
    RememberFactCommand,
)
from infinity_context_core.features.memory_facts.domain import (
    MemoryFactScope,
    MemoryFactSourceRef,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAdmission,
    ManagedBenchmarkStrictV4DocumentClaim,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAdmission,
    ManagedBenchmarkStrictV4CorpusClaim,
    ManagedBenchmarkStrictV4FactAdmission,
    ManagedBenchmarkStrictV4FactClaim,
)
from infinity_context_server import benchmark_managed_fact_composition
from postgres_test_database import (
    STRICT_V4_TEST_ROLE_PASSWORD,
    PostgresTestDatabase,
)
from sqlalchemy.engine import make_url


def test_strict_v4_writer_authority_on_fresh_postgres_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_strict_v4_writer_authority(database_url))


def test_strict_v4_canonical_writer_executes_exact_fact_graph_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_strict_v4_canonical_fact_graph(database_url))


def test_strict_v4_canonical_writer_executes_exact_document_graph_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_strict_v4_canonical_document_graph(database_url))


class _ExactFactAuthority:
    def __init__(self) -> None:
        self.claim: ManagedBenchmarkStrictV4FactClaim | None = None

    def admit_fact(
        self, claim: ManagedBenchmarkStrictV4FactClaim
    ) -> ManagedBenchmarkStrictV4FactAdmission:
        self.claim = claim
        digest = _digest("fact", "idempotency")
        return ManagedBenchmarkStrictV4FactAdmission(
            operation_sha256=claim.operation_commitment_sha256,
            idempotency_key=f"managed-benchmark-fact-v4-{digest}",
        )

    def admit_corpus(
        self, claim: ManagedBenchmarkStrictV4CorpusClaim
    ) -> ManagedBenchmarkStrictV4CorpusAdmission:
        return ManagedBenchmarkStrictV4CorpusAdmission(
            corpus_identity_sha256=_digest(
                "corpus",
                f"{claim.memory_scope_external_ref}:{claim.thread_external_ref}",
            )
        )


class _ExactDocumentAuthority:
    def __init__(self) -> None:
        self.claim: ManagedBenchmarkStrictV4DocumentClaim | None = None

    def admit_document(
        self, claim: ManagedBenchmarkStrictV4DocumentClaim
    ) -> ManagedBenchmarkStrictV4DocumentAdmission:
        self.claim = claim
        return ManagedBenchmarkStrictV4DocumentAdmission(
            operation_sha256=claim.operation_commitment_sha256,
            idempotency_key=f"managed-benchmark-document-v4-{_digest('document', 'key')}",
        )

    def admit_corpus(
        self, claim: ManagedBenchmarkStrictV4CorpusClaim
    ) -> ManagedBenchmarkStrictV4CorpusAdmission:
        return ManagedBenchmarkStrictV4CorpusAdmission(
            corpus_identity_sha256=_digest(
                "document-corpus",
                f"{claim.memory_scope_external_ref}:{claim.thread_external_ref}",
            )
        )


async def _assert_strict_v4_canonical_document_graph(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_document_graph",
        asyncpg=asyncpg,
    )
    runtime_role = None
    engine = None
    try:
        await database.recreate()
        migration_engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(migration_engine)
            assert result.current == "0054_locator_profile_exact_delete_generation"
        finally:
            await migration_engine.dispose()

        admin = await database.connect()
        try:
            await _seed_strict_document_run(admin)
        finally:
            await admin.close()

        runtime_role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer",
            suffix="canonical_document_writer",
        )
        runtime_url = make_url(database.app_url).set(
            username=runtime_role,
            password=STRICT_V4_TEST_ROLE_PASSWORD,
        )
        engine = build_async_engine(runtime_url.render_as_string(hide_password=False))
        sessions = build_session_factory(engine)
        clock = SystemClock()
        ids = UuidIdGenerator()
        uow = PostgresUnitOfWorkFactory(session_factory=sessions, clock=clock)
        authority = _ExactDocumentAuthority()
        scope = await ManagedBenchmarkEnsureScopeAdmission(
            uow_factory=uow,
            inner=EnsureScopeUseCase(uow_factory=uow, clock=clock),
            strict_v4_authority=authority,
        ).execute(
            EnsureScopeCommand(
                space_slug="strict-v4-document-graph",
                memory_scope_external_ref="corpus-1",
                thread_external_ref="thread-1",
            )
        )
        command = IngestDocumentCommand(
            space_id=SpaceId(str(scope.space_id)),
            memory_scope_id=MemoryScopeId(str(scope.memory_scope_id)),
            thread_id=ThreadId(str(scope.thread_id)),
            title="Strict v4 document graph",
            text="The strict v4 document graph is canonical, evidenced, and replay safe.",
            source_type="memory_comparison_benchmark",
            source_external_id="longmemeval:document:1",
            classification="internal",
            chunk_metadata={"source_refs": [{"source_id": "longmemeval:document:1"}]},
        )
        ingest = IngestDocumentUseCase(
            uow_factory=uow,
            clock=clock,
            ids=ids,
            strict_v4_authority=authority,
        )

        first = await ingest.execute(command)
        replay = await ingest.execute(command)

        assert first.indexing_status == "pending"
        assert replay.indexing_status == "already_indexed_or_pending"
        assert replay.document.id == first.document.id
        assert tuple(chunk.id for chunk in replay.chunks) == tuple(
            chunk.id for chunk in first.chunks
        )
        assert authority.claim is not None
        assert authority.claim.space_id == _document_space()

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
            receipt = await admin.fetchrow(
                """
                SELECT key,fingerprint,result_type,result_id
                FROM memory_idempotency_records
                """
            )
            outbox = await admin.fetchrow(
                """
                SELECT aggregate_type,aggregate_version,event_type,status,payload_json
                FROM memory_outbox
                """
            )
        finally:
            await admin.close()

        assert tuple(counts.values()) == (1, len(first.chunks), len(first.chunks), 1)
        assert receipt["key"].startswith("managed-benchmark-document-v4-")
        assert len(receipt["key"]) == 94
        assert receipt["result_type"] == "document"
        assert receipt["result_id"] == str(first.document.id)
        assert outbox["aggregate_type"] == "chunk"
        assert outbox["aggregate_version"] is None
        assert outbox["event_type"] == "vector.upsert_chunk"
        assert outbox["status"] == "pending"
        assert json.loads(outbox["payload_json"])["chunk_id"] == str(first.chunks[0].id)

        runtime = await database.connect_as_runtime_role(runtime_role)
        try:
            await _assert_document_graph_rejects_fact_payload(
                runtime,
                chunk_id=str(first.chunks[0].id),
                fact_id="opposite-fact-payload",
            )
        finally:
            await runtime.close()
    finally:
        if engine is not None:
            await engine.dispose()
        if runtime_role is not None:
            await database.drop_runtime_roles(runtime_role)
        await database.drop()


def _document_space() -> str:
    return f"benchmark-space-{_digest('document', 'space')[:48]}"


async def _seed_strict_document_run(connection) -> None:
    space = _document_space()
    await connection.execute(
        """
        INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
        VALUES($1,$2,$2,'active',clock_timestamp(),clock_timestamp())
        """,
        space,
        "strict-v4-document-graph",
    )
    await connection.execute(
        """
        INSERT INTO memory_comparison_benchmark_runs(
          run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
          space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
          state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
          created_at,updated_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',
               clock_timestamp(),clock_timestamp())
        """,
        _digest("document", "run"),
        _digest("document", "binding"),
        _digest("document", "target"),
        space,
        "strict-v4-document-graph",
        _digest("document", "run-idempotency"),
        _digest("document", "registration"),
    )
    await _seed_context(connection, suffix="document")
    await _seal_strict(connection, suffix="document")


async def _assert_strict_v4_canonical_fact_graph(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_fact_graph",
        asyncpg=asyncpg,
    )
    runtime_role = None
    engine = None
    try:
        await database.recreate()
        migration_engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(migration_engine)
            assert result.current == "0054_locator_profile_exact_delete_generation"
        finally:
            await migration_engine.dispose()

        admin = await database.connect()
        try:
            await _seed_strict_fact_run(admin)
        finally:
            await admin.close()

        runtime_role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer",
            suffix="canonical_fact_writer",
        )
        runtime_url = make_url(database.app_url).set(
            username=runtime_role,
            password=STRICT_V4_TEST_ROLE_PASSWORD,
        )
        engine = build_async_engine(runtime_url.render_as_string(hide_password=False))
        sessions = build_session_factory(engine)
        clock = SystemClock()
        ids = create_memory_fact_id_adapter(UuidIdGenerator().new_id)
        canonical_uow = PostgresUnitOfWorkFactory(
            session_factory=sessions,
            clock=clock,
            memory_fact_ids=ids,
        )
        fact_uow = create_postgres_memory_fact_unit_of_work_factory(
            session_factory=sessions,
            clock=clock,
        )
        authority = _ExactFactAuthority()
        scope = await ManagedBenchmarkEnsureScopeAdmission(
            uow_factory=canonical_uow,
            inner=EnsureScopeUseCase(uow_factory=canonical_uow, clock=clock),
            strict_v4_authority=authority,
        ).execute(
            EnsureScopeCommand(
                space_slug="strict-v4-fact-graph",
                memory_scope_external_ref="corpus-1",
                thread_external_ref="thread-1",
            )
        )
        lifecycle, _temporal = (
            benchmark_managed_fact_composition.build_managed_memory_fact_use_cases(
                benchmark_uow_factory=canonical_uow,
                memory_fact_uow_factory=fact_uow,
                clock=clock,
                ids=ids,
                strict_v4_fact_authority=authority,
            )
        )
        command = RememberFactCommand(
            scope=MemoryFactScope(
                str(scope.space_id),
                str(scope.memory_scope_id),
                str(scope.thread_id),
            ),
            text="The strict v4 fact graph is canonical and replay safe.",
            source_refs=(
                MemoryFactSourceRef(
                    source_type="memory_comparison_benchmark",
                    source_id="source-1",
                    quote_preview="The strict v4 fact graph is canonical and replay safe.",
                ),
            ),
            kind="requirement",
            idempotency_key="caller-value-must-be-replaced",
        )

        first = await lifecycle.remember_fact.execute(command)
        replay = await lifecycle.remember_fact.execute(command)

        assert first.replayed is False
        assert replay.replayed is True
        assert first.fact.identity.fact_id == replay.fact.identity.fact_id
        assert authority.claim is not None
        assert authority.claim.space_id == _fact_space()
        assert authority.claim.memory_scope_external_ref == "corpus-1"
        assert authority.claim.thread_external_ref == "thread-1"

        admin = await database.connect()
        try:
            counts = await admin.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM memory_facts) AS facts,
                  (SELECT count(*) FROM memory_fact_versions) AS versions,
                  (SELECT count(*) FROM memory_source_refs) AS source_refs,
                  (SELECT count(*) FROM memory_outbox) AS outbox,
                  (SELECT count(*) FROM memory_fact_operation_receipts) AS receipts
                """
            )
            receipt = await admin.fetchrow(
                """
                SELECT operation, result_fact_version, idempotency_key,
                       outbox_message_ids_json
                FROM memory_fact_operation_receipts
                """
            )
            outbox = await admin.fetchrow(
                """
                SELECT aggregate_type, aggregate_version, event_type, status,
                       payload_json
                FROM memory_outbox
                """
            )
        finally:
            await admin.close()

        assert tuple(counts.values()) == (1, 1, 1, 1, 1)
        assert receipt["operation"] == "remember"
        assert receipt["result_fact_version"] == 1
        assert len(receipt["idempotency_key"]) == 90
        assert receipt["idempotency_key"].startswith("managed-benchmark-fact-v4-")
        assert len(json.loads(receipt["outbox_message_ids_json"])) == 1
        assert (
            outbox["aggregate_type"],
            outbox["aggregate_version"],
            outbox["event_type"],
            outbox["status"],
        ) == ("fact", 1, "fact.created", "pending")
        assert json.loads(outbox["payload_json"])["space_id"] == _fact_space()

        runtime = await database.connect_as_runtime_role(runtime_role)
        try:
            await _assert_fact_graph_rejects_document_payload(
                runtime,
                fact_id=str(first.fact.identity.fact_id),
                chunk_id="opposite-document-payload",
            )
        finally:
            await runtime.close()
    finally:
        if engine is not None:
            await engine.dispose()
        if runtime_role is not None:
            await database.drop_runtime_roles(runtime_role)
        await database.drop()


def _fact_space() -> str:
    return f"benchmark-space-{_digest('fact', 'space')[:48]}"


async def _seed_strict_fact_run(connection) -> None:
    space = _fact_space()
    await connection.execute(
        """
        INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
        VALUES($1,$2,$2,'active',clock_timestamp(),clock_timestamp())
        """,
        space,
        "strict-v4-fact-graph",
    )
    await connection.execute(
        """
        INSERT INTO memory_comparison_benchmark_runs(
          run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
          space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
          state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
          created_at,updated_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',
               clock_timestamp(),clock_timestamp())
        """,
        _digest("fact", "run"),
        _digest("fact", "binding"),
        _digest("fact", "target"),
        space,
        "strict-v4-fact-graph",
        _digest("fact", "run-idempotency"),
        _digest("fact", "registration"),
    )
    await _seed_context(connection, suffix="fact")
    await _seal_strict(connection, suffix="fact")


async def _assert_fact_graph_rejects_document_payload(
    connection,
    *,
    fact_id: str,
    chunk_id: str,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    transaction = connection.transaction()
    await transaction.start()
    try:
        with pytest.raises(asyncpg.CheckViolationError) as rejected:
            await connection.execute(
                """
                INSERT INTO memory_outbox(
                  event_type,aggregate_type,aggregate_id,aggregate_version,
                  payload_json,status,attempt_count,next_attempt_at,
                  created_at,updated_at,workload_class,message_key)
                VALUES(
                  'fact.created','fact',$1,1,
                  pg_catalog.jsonb_build_object('chunk_id',$2::text),
                  'pending',0,clock_timestamp(),clock_timestamp(),clock_timestamp(),
                  'projection',$3)
                """,
                fact_id,
                chunk_id,
                f"opposite-document-{_digest('fact', 'opposite')}",
            )
        assert rejected.value.constraint_name == ("ck_memory_comparison_benchmark_run_writer_fence")
    finally:
        await transaction.rollback()


async def _assert_document_graph_rejects_fact_payload(
    connection,
    *,
    chunk_id: str,
    fact_id: str,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    transaction = connection.transaction()
    await transaction.start()
    try:
        with pytest.raises(asyncpg.CheckViolationError) as rejected:
            await connection.execute(
                """
                INSERT INTO memory_outbox(
                  event_type,aggregate_type,aggregate_id,aggregate_version,
                  payload_json,status,attempt_count,next_attempt_at,
                  created_at,updated_at,workload_class,message_key)
                VALUES(
                  'vector.upsert_chunk','chunk',$1,NULL,
                  pg_catalog.jsonb_build_object(
                    'fact_id',$2::text,'space_id',$3::text,'version',1),
                  'pending',0,clock_timestamp(),clock_timestamp(),clock_timestamp(),
                  'projection',$4)
                """,
                chunk_id,
                fact_id,
                _document_space(),
                f"opposite-fact-{_digest('document', 'opposite')}",
            )
        assert rejected.value.constraint_name == ("ck_memory_comparison_benchmark_run_writer_fence")
    finally:
        await transaction.rollback()


async def _assert_strict_v4_writer_authority(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="strict_v4_writer", asyncpg=asyncpg
    )
    canonical_role = None
    canonical_connection = None
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.current == "0054_locator_profile_exact_delete_generation"
        finally:
            await engine.dispose()
        canonical_role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer",
            suffix="canonical",
        )
        canonical_connection = await database.connect_as_runtime_role(canonical_role)
        connection = await database.connect()
        try:
            observed = await connection.fetch(
                """
                SELECT c.relname
                FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                WHERE NOT t.tgisinternal
                  AND t.tgname='trg_' || c.relname || '_benchmark_writer_fence'
                """
            )
            assert {row["relname"] for row in observed} == {
                table for table, _columns in BENCHMARK_WRITER_FENCE_TABLES
            }
            assert (
                await connection.fetchval(
                    "SELECT to_regprocedure("
                    "'public.memory_comparison_close_strict_v4_preparation()')"
                )
                is None
            )
            assert not await connection.fetchval(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_trigger
                  WHERE tgname='trg_benchmark_run_close_strict_v4_preparation'
                    AND NOT tgisinternal
                )
                """
            )

            await _seed_run(connection, suffix="strict", legacy=False)
            await _assert_fenced(
                canonical_connection,
                suffix="strict",
                key="neither-authority",
            )
            await _seed_context(connection, suffix="strict")
            await _assert_fenced(
                canonical_connection,
                suffix="strict",
                key="registration-only",
            )
            await _seal_strict(connection, suffix="strict")
            await _insert_idempotency(
                canonical_connection,
                suffix="strict",
                key="strict-sealed",
            )
            await _assert_fenced(connection, suffix="strict", key="owner-rejected")

            with pytest.raises(asyncpg.CheckViolationError) as tamper:
                await connection.execute(
                    """
                    UPDATE memory_comparison_strict_v4_preparations
                    SET writer_authority_mac_sha256=$2
                    WHERE run_id_sha256=$1
                    """,
                    _digest("strict", "run"),
                    "f" * 64,
                )
            assert tamper.value.constraint_name == (
                "ck_memory_comparison_strict_v4_preparation_immutable"
            )

            await connection.execute(
                """
                UPDATE memory_comparison_benchmark_runs
                SET cleanup_plan_json='{}'::jsonb, cleanup_plan_sha256=$2,
                    cleanup_plan_state='sealed'
                WHERE run_id_sha256=$1
                """,
                _digest("strict", "run"),
                "e" * 64,
            )
            await _assert_fenced(
                canonical_connection,
                suffix="strict",
                key="xor-both",
            )
            preparation_before_projection_cleanup = await connection.fetchrow(
                "SELECT * FROM memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1",
                _digest("strict", "run"),
            )
            assert preparation_before_projection_cleanup is not None
            await connection.execute(
                """
                UPDATE memory_comparison_benchmark_runs
                SET cleanup_plan_json=NULL, cleanup_plan_sha256=NULL,
                    cleanup_plan_state='recovery_blocked',
                    projection_manifest_json='{}'::jsonb,
                    projection_manifest_sha256=$2,
                    projection_cleanup_state='sealed', updated_at=clock_timestamp()
                WHERE run_id_sha256=$1
                """,
                _digest("strict", "run"),
                "d" * 64,
            )
            preparation_after_projection_cleanup = await connection.fetchrow(
                "SELECT * FROM memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1",
                _digest("strict", "run"),
            )
            assert preparation_after_projection_cleanup is not None
            assert dict(preparation_after_projection_cleanup) == dict(
                preparation_before_projection_cleanup
            )
            assert preparation_after_projection_cleanup["state"] == "sealed"
            await _assert_fenced(
                canonical_connection,
                suffix="strict",
                key="sealed-after-projection-cleanup",
            )

            await _seed_run(connection, suffix="legacy", legacy=True)
            await _insert_idempotency(connection, suffix="legacy", key="legacy-unchanged")

            await _seed_run(connection, suffix="invalid", legacy=False)
            await _seed_context(connection, suffix="invalid")
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await _seal_strict(
                    connection,
                    suffix="invalid",
                    terminal_override="a" * 64,
                )
            for provider_calls, paid in ((1, False), (0, True)):
                with pytest.raises(asyncpg.CheckViolationError) as invalid:
                    await _seal_strict(
                        connection,
                        suffix="invalid",
                        provider_calls=provider_calls,
                        paid_go_ready=paid,
                    )
                assert invalid.value.constraint_name == "ck_strict_v4_preparation_provider_free"
        finally:
            await connection.close()
    finally:
        if canonical_connection is not None:
            await canonical_connection.close()
        if canonical_role is not None:
            await database.drop_runtime_roles(canonical_role)
        await database.drop()


def _digest(suffix: str, field: str) -> str:
    import hashlib

    return hashlib.sha256(f"{suffix}:{field}".encode()).hexdigest()


async def _seed_run(connection, *, suffix: str, legacy: bool) -> None:
    run, space = _digest(suffix, "run"), f"strict-v4-{suffix}"
    await connection.execute(
        """
        INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
        VALUES($1,$1,$1,'active',clock_timestamp(),clock_timestamp())
        """,
        space,
    )
    await connection.execute(
        """
        INSERT INTO memory_comparison_benchmark_runs(
          run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
          space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
          state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
          created_at,updated_at)
        VALUES($1,$2,$3,$4,$4,$5,$6,'active',$7::jsonb,$8,$9,
               clock_timestamp(),clock_timestamp())
        """,
        run,
        _digest(suffix, "binding"),
        _digest(suffix, "target"),
        space,
        _digest(suffix, "idempotency"),
        _digest(suffix, "registration"),
        "{}" if legacy else None,
        _digest(suffix, "plan") if legacy else None,
        "sealed" if legacy else "recovery_blocked",
    )


async def _seed_context(connection, *, suffix: str) -> None:
    await connection.execute(
        """
        INSERT INTO memory_cleanup_v3_context_authorities(
          run_id_sha256,context_sha256,authority_terminal_sha256,
          context_json,authority_json,registration_sha256,
          registration_mac_sha256,registered_at)
        VALUES($1,$2,$3,'{}'::jsonb,'{}'::jsonb,$4,$5,clock_timestamp())
        """,
        _digest(suffix, "run"),
        _digest(suffix, "context"),
        _digest(suffix, "terminal"),
        _digest(suffix, "registration-sha"),
        _digest(suffix, "registration-mac"),
    )


async def _seal_strict(
    connection,
    *,
    suffix: str,
    provider_calls: int = 0,
    paid_go_ready: bool = False,
    terminal_override: str | None = None,
) -> None:
    run = _digest(suffix, "run")
    context = _digest(suffix, "context")
    terminal = terminal_override or _digest(suffix, "terminal")
    receipt_sha = _digest(suffix, "receipt")
    receipt_mac = _digest(suffix, "receipt-mac")
    registration_sha = _digest(suffix, "registration-sha")
    registration_mac = _digest(suffix, "registration-mac")
    writer_sha = _digest(suffix, "writer")
    writer_mac = _digest(suffix, "writer-mac")
    sealed_at = await connection.fetchval("SELECT clock_timestamp()")
    sealed_at_text = sealed_at.isoformat()
    receipt = {
        "schema_version": "memory-comparison-strict-v4-full-preparation.v1",
        "run_id_sha256": run,
        "a2_context": {"context_sha256": context},
        "a2_authority": {"terminal_commitment_sha256": terminal},
        "receipt_sha256": receipt_sha,
        "receipt_mac_sha256": receipt_mac,
        "registration_sha256": registration_sha,
        "registration_mac_sha256": registration_mac,
        "provider_calls": provider_calls,
        "paid_go_ready": paid_go_ready,
        "prepared_at": sealed_at_text,
        "registered_at": sealed_at_text,
    }
    authority = {
        "schema_version": "memory-comparison-strict-v4-writer-authority.v1",
        "run_id_sha256": run,
        "context_sha256": context,
        "authority_terminal_sha256": terminal,
        "preparation_receipt_sha256": receipt_sha,
        "preparation_receipt_mac_sha256": receipt_mac,
        "registration_sha256": registration_sha,
        "registration_mac_sha256": registration_mac,
        "a2_terminal_commitment_sha256": terminal,
        "expected_index_terminal_sha256": terminal,
        "provider_calls": provider_calls,
        "paid_go_ready": paid_go_ready,
        "writer_authority_sha256": writer_sha,
        "writer_authority_mac_sha256": writer_mac,
        "sealed_at": sealed_at_text,
    }
    await connection.execute(
        """
        INSERT INTO memory_comparison_strict_v4_preparations(
          run_id_sha256,context_sha256,authority_terminal_sha256,
          preparation_receipt_json,preparation_receipt_sha256,
          preparation_receipt_mac_sha256,writer_authority_json,
          writer_authority_sha256,writer_authority_mac_sha256,
          registration_sha256,registration_mac_sha256,
          provider_calls,paid_go_ready,state,sealed_at)
        VALUES($1,$2,$3,$4::jsonb,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,$13,
               'sealed',$14)
        """,
        run,
        context,
        terminal,
        json.dumps(receipt),
        receipt_sha,
        receipt_mac,
        json.dumps(authority),
        writer_sha,
        writer_mac,
        registration_sha,
        registration_mac,
        provider_calls,
        paid_go_ready,
        sealed_at,
    )


async def _insert_idempotency(connection, *, suffix: str, key: str) -> None:
    await connection.execute(
        """
        INSERT INTO memory_idempotency_records(
          space_id,key,fingerprint,result_type,result_id,created_at)
        VALUES($1,$2,$2,'strict-v4',$2,clock_timestamp())
        """,
        f"strict-v4-{suffix}",
        key,
    )


async def _assert_fenced(connection, *, suffix: str, key: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    with pytest.raises(asyncpg.CheckViolationError) as fenced:
        await _insert_idempotency(connection, suffix=suffix, key=key)
    assert fenced.value.constraint_name == BENCHMARK_WRITER_FENCE_CONSTRAINT


async def _assert_every_fenced_table_blocks(connection, *, suffix: str) -> None:
    for table, _columns in BENCHMARK_WRITER_FENCE_TABLES:
        await _assert_table_fence(connection, table=table, suffix=suffix)


async def _assert_non_initial_tables_stay_blocked(connection, *, suffix: str) -> None:
    for table, _columns in BENCHMARK_WRITER_FENCE_TABLES:
        if table in BENCHMARK_INITIAL_INSERT_TABLES:
            continue
        await _assert_table_fence(connection, table=table, suffix=suffix)


async def _assert_initial_tables_pass_fence(connection, *, suffix: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    space_id = f"strict-v4-{suffix}"
    for table in BENCHMARK_INITIAL_INSERT_TABLES:
        trigger = f"trg_{table}_benchmark_writer_fence"
        await connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.PostgresError) as downstream:
                await connection.execute(f"INSERT INTO {table}(space_id) VALUES($1)", space_id)
            assert downstream.value.constraint_name != BENCHMARK_WRITER_FENCE_CONSTRAINT
        finally:
            await transaction.rollback()
            await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


async def _assert_table_fence(connection, *, table: str, suffix: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    space_id = f"strict-v4-{suffix}"
    trigger = f"trg_{table}_benchmark_writer_fence"
    await connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    try:
        statement = (
            f"INSERT INTO {table}(id) VALUES($1)"
            if table == "memory_spaces"
            else f"INSERT INTO {table}(space_id) VALUES($1)"
        )
        with pytest.raises(asyncpg.CheckViolationError) as blocked:
            await connection.execute(statement, space_id)
        assert blocked.value.constraint_name == BENCHMARK_WRITER_FENCE_CONSTRAINT
    finally:
        await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
