"""PostgreSQL 18 proof for locator children governed by document lifecycle."""

from __future__ import annotations

import asyncio
import os
from hashlib import sha256

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.locator_catalog_attestation import (
    attest_locator_retrieval_catalog,
)
from infinity_context_adapters.postgres.locator_index_maintenance import (
    build_locator_retrieval_indexes,
)
from infinity_context_adapters.postgres.runtime_acl import reconcile_runtime_acl
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_locator_parent_lifecycle_upgrade_and_fresh_schema_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_upgrade_and_fresh(database_url))


async def _assert_upgrade_and_fresh(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_parent_0059", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        probe = await database.connect()
        try:
            assert int(await probe.fetchval("SHOW server_version_num")) >= 180000
        finally:
            await probe.close()
        await _install_versioned_schema_through(database, "0058_")
        connection = await database.connect()
        try:
            await _seed_unsealed_runtime(connection)
        finally:
            await connection.close()

        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(Exception, match="every prior runtime incarnation"):
                await upgrade_schema(engine)
            async with engine.connect() as check:
                assert not await check.scalar(
                    text(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM information_schema.columns
                          WHERE table_schema='public' AND table_name='memory_chunks'
                            AND column_name='retrieval_parent_version')
                        """
                    )
                )
                assert not await check.scalar(
                    text(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM information_schema.columns
                          WHERE table_schema='public'
                            AND table_name='memory_locator_runtime_incarnations'
                            AND column_name='locator_parent_capability')
                        """
                    )
                )

            connection = await database.connect()
            try:
                await connection.execute(
                    """
                    UPDATE memory_locator_runtime_incarnations
                    SET sealed_dead_generation=1,sealed_dead_proof_id='0059-drain-proof',
                        sealed_dead_proof_sha256=repeat('1',64),
                        sealed_dead_authority='0059-test-supervisor',sealed_dead_at=now()
                    WHERE instance_id='pre-0059-runtime'
                    """
                )
                await _seed_pre_0059(connection)
            finally:
                await connection.close()

            result = await upgrade_schema(engine)
            assert result.applied == ("0059_locator_parent_lifecycle",)
            await _assert_staged_repair(engine)
            await _assert_benchmark_fence_persistence(engine, asyncpg)
            await build_locator_retrieval_indexes(engine, statement_timeout_ms=30_000)
            await _assert_catalog(engine)
            await _assert_capability_fence(database, asyncpg)
            await _assert_parent_transitions(engine)
            await _assert_invalid_admission(engine, asyncpg)
            await _assert_serialized_admission(database, engine, asyncpg)
            await _assert_runtime_acl(database, engine)
        finally:
            await engine.dispose()

        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            fresh = await upgrade_schema(engine)
            assert fresh.current == "0059_locator_parent_lifecycle"
            assert fresh.applied[0] == "0001_core_facts"
            await build_locator_retrieval_indexes(engine, statement_timeout_ms=30_000)
            await _assert_catalog(engine)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _seed_unsealed_runtime(connection) -> None:
    await connection.execute(
        """
        INSERT INTO memory_locator_runtime_incarnations
          (instance_id,generation,registered_at,last_seen_at,acknowledged_generation,
           supervisor_key_id,supervisor_public_key,trust_root_sha256,
           trust_registry_generation,launch_token,process_pid,process_birth_identity,
           executable_identity,executable_sha256,launch_identity_sha256,
           release_revision,release_source_tree_sha256,
           release_installed_distribution_sha256,release_runtime_modules_sha256,
           release_identity_sha256)
        VALUES ('pre-0059-runtime','generation',now(),now(),0,'test-supervisor',
                repeat('0',64),repeat('0',64),0,'launch',1,'birth','/test/runtime',
                repeat('0',64),repeat('0',64),repeat('0',40),
                'sha256:'||repeat('0',64),'sha256:'||repeat('0',64),
                'sha256:'||repeat('0',64),repeat('0',64))
        """
    )


async def _seed_pre_0059(connection) -> None:
    await connection.execute(
        """
        INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at) VALUES
          ('space-a', 'parent-a', 'A', 'active', now(), now()),
          ('space-b', 'parent-b', 'B', 'active', now(), now());
        INSERT INTO memory_scopes
          (id, space_id, external_ref, name, status, created_at, updated_at) VALUES
          ('scope-a', 'space-a', 'a', 'A', 'active', now(), now()),
          ('scope-b', 'space-b', 'b', 'B', 'active', now(), now());
        INSERT INTO memory_documents
          (id, space_id, memory_scope_id, thread_id, title, source_type,
           source_external_id, content_hash, classification, status,
           retrieval_projected, created_at, updated_at) VALUES
          ('document-a', 'space-a', 'scope-a', NULL, 'A', 'file', 'a.txt',
           repeat('a',64), 'internal', 'active', TRUE, now(), now()),
          ('document-b', 'space-b', 'scope-b', NULL, 'B', 'file', 'b.txt',
           repeat('b',64), 'internal', 'active', TRUE, now(), now());
        INSERT INTO memory_locator_profiles
          (profile_id, generation, profile_digest, collection_name, state,
           backfill_complete, canonical_watermark, projected_watermark,
           expected_count, projected_count, expected_digest, projected_digest, created_at)
        VALUES ('profile-parent', 'generation-parent', repeat('c',64),
                'locator_parent', 'building', FALSE, 0, 0, 0, 0,
                repeat('0',64), repeat('0',64), now());
        """
    )
    for chunk_id, document_id, space_id, scope_id, source in (
        ("chunk-good", "document-a", "space-a", "scope-a", "a.txt"),
        ("chunk-cross", "document-b", "space-a", "scope-a", "b.txt"),
        ("chunk-orphan", "document-later", "space-a", "scope-a", "later.txt"),
        ("chunk-foreign", "document-b", "space-b", "scope-b", "b.txt"),
    ):
        if chunk_id == "chunk-orphan":
            await connection.execute("SET session_replication_role = replica")
        try:
            await connection.execute(
                """
                INSERT INTO memory_chunks
                  (id, space_id, memory_scope_id, thread_id, document_id, episode_id,
                   source_type, source_external_id, source_hash, kind, text, normalized_text,
                   status, sequence, char_start, char_end, token_estimate, classification,
                   created_at, updated_at, metadata_json, retrieval_locator,
                   retrieval_source_key, retrieval_projection_generation,
                   retrieval_sequence_ordinal, retrieval_kind, retrieval_category)
                VALUES ($1::varchar(80),$2,$3,NULL,$4,NULL,'file',$5,$6::char(64),
                        'document_section',$1::text,$1::text,'active',0,0,10,2,'internal',now(),now(),
                        '{}'::jsonb,'locator/' || $1::text,$5,'generation',0,
                        'record','decision')
                """,
                chunk_id,
                space_id,
                scope_id,
                document_id,
                source,
                sha256(chunk_id.encode()).hexdigest(),
            )
        finally:
            if chunk_id == "chunk-orphan":
                await connection.execute("SET session_replication_role = origin")


async def _assert_staged_repair(engine) -> None:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT id,retrieval_version,retrieval_parent_version "
                    "FROM memory_chunks ORDER BY id"
                )
            )
        ).all()
        tombstones = (
            await connection.execute(
                text(
                    "SELECT chunk_id,canonical_version FROM memory_locator_profile_tombstones "
                    "WHERE profile_id='profile-parent' ORDER BY chunk_id"
                )
            )
        ).all()
        cleanup = (
            await connection.execute(
                text(
                    "SELECT aggregate_id,aggregate_version FROM memory_outbox "
                    "WHERE event_type='vector.delete_locator_profile' ORDER BY aggregate_id"
                )
            )
        ).all()
    assert rows == [
        ("chunk-cross", 2, 2),
        ("chunk-foreign", 1, 1),
        ("chunk-good", 1, 1),
        ("chunk-orphan", 2, 2),
    ]
    assert tombstones == [("chunk-cross", 2), ("chunk-orphan", 2)]
    assert cleanup == [("chunk-cross", 2), ("chunk-orphan", 2)]


async def _assert_benchmark_fence_persistence(engine, asyncpg) -> None:
    """Only the 0059 maintenance column escapes the strict document fence."""

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(Exception) as raised:
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET text='forbidden-content-change' "
                        "WHERE id='chunk-orphan'"
                    )
                )
        finally:
            await transaction.rollback()
    root = _root_exception(raised.value)
    assert isinstance(root, asyncpg.CheckViolationError)
    assert "benchmark document child parent is missing" in str(root)
    assert root.constraint_name == "ck_memory_comparison_benchmark_run_writer_fence"
    assert await _version(engine, "chunk-orphan") == (2, 2)


async def _assert_parent_transitions(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_documents SET status='superseded' WHERE id='document-a'")
        )
    assert await _canonical_ids(engine, "space-a", "scope-a") == ()
    assert await _version(engine, "chunk-good") == (2, 2)
    assert await _tombstone(engine, "chunk-good") == 2

    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_documents SET status='active' WHERE id='document-a'")
        )
    assert await _canonical_ids(engine, "space-a", "scope-a") == ("chunk-good",)
    assert await _version(engine, "chunk-good") == (3, 3)
    assert await _tombstone(engine, "chunk-good") is None
    assert await _event_exists(engine, "chunk-good", 3, "vector.upsert_locator_profile")

    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO memory_documents
                  (id,space_id,memory_scope_id,thread_id,title,source_type,
                   source_external_id,content_hash,classification,status,
                   retrieval_projected,created_at,updated_at)
                VALUES ('document-later','space-a','scope-a',NULL,'Later','file',
                        'later.txt',repeat('e',64),'internal','active',TRUE,now(),now())
                """
            )
        )
    assert await _version(engine, "chunk-orphan") == (3, 3)
    assert await _tombstone(engine, "chunk-orphan") is None
    assert await _canonical_ids(engine, "space-a", "scope-a") == (
        "chunk-good",
        "chunk-orphan",
    )

    async with engine.begin() as connection:
        with pytest.raises(Exception, match="canonical document identity is immutable"):
            await connection.execute(
                text("UPDATE memory_documents SET id='document-renamed' WHERE id='document-a'")
            )


async def _assert_invalid_admission(engine, asyncpg) -> None:
    for chunk_id, document_id, space_id, scope_id, source in (
        ("missing-new", "missing-document", "space-a", "scope-a", "missing.txt"),
        ("mismatch-new", "document-b", "space-a", "scope-a", "b.txt"),
    ):
        async with engine.begin() as connection:
            with pytest.raises(Exception) as raised:
                await connection.execute(
                    text(_CHUNK_INSERT),
                    {
                        "chunk_id": chunk_id,
                        "document_id": document_id,
                        "space_id": space_id,
                        "scope_id": scope_id,
                        "source": source,
                    },
                )
        assert isinstance(_root_exception(raised.value), asyncpg.ForeignKeyViolationError)
    assert await _canonical_ids(engine, "space-b", "scope-b") == ("chunk-foreign",)


async def _assert_serialized_admission(database, engine, asyncpg) -> None:
    parent = await database.connect()
    await parent.execute("BEGIN")
    try:
        await parent.execute(
            "UPDATE memory_documents SET status='superseded' WHERE id='document-b'"
        )

        # Use native positional SQL for the concurrent connection.
        async def native_insert() -> None:
            contender = await database.connect()
            try:
                await contender.execute(
                    _NATIVE_CHUNK_INSERT,
                    "concurrent-child",
                    "space-b",
                    "scope-b",
                    "document-b",
                    "b.txt",
                )
            finally:
                await contender.close()

        task = asyncio.create_task(native_insert())
        await asyncio.sleep(0.1)
        assert not task.done()
        await parent.execute("COMMIT")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await task
    finally:
        if parent.is_in_transaction():
            await parent.execute("ROLLBACK")
        await parent.close()
    assert not await _event_exists(engine, "concurrent-child", 1, "vector.upsert_locator_profile")

    # A currently mismatched row must wait for the lifecycle update that makes
    # it eligible instead of observing and rejecting a stale parent shape.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE memory_documents SET status='active', classification='public' "
                "WHERE id='document-b'"
            )
        )
    parent = await database.connect()
    await parent.execute("BEGIN")
    try:
        await parent.execute(
            "UPDATE memory_documents SET classification='internal' WHERE id='document-b'"
        )
        task = asyncio.create_task(
            _native_insert(
                database,
                "concurrent-mismatch",
                "space-b",
                "scope-b",
                "document-b",
                "b.txt",
            )
        )
        await asyncio.sleep(0.1)
        assert not task.done()
        await parent.execute("COMMIT")
        await task
    finally:
        if parent.is_in_transaction():
            await parent.execute("ROLLBACK")
        await parent.close()
    assert await _event_exists(
        engine, "concurrent-mismatch", 1, "vector.upsert_locator_profile"
    )

    # The lock identity exists before its parent row, so creation and admission
    # of a formerly missing parent also have a deterministic commit order.
    parent = await database.connect()
    await parent.execute("BEGIN")
    try:
        await parent.execute(
            """
            INSERT INTO memory_documents
              (id,space_id,memory_scope_id,thread_id,title,source_type,
               source_external_id,content_hash,classification,status,
               retrieval_projected,created_at,updated_at)
            VALUES ('document-concurrent-new','space-a','scope-a',NULL,'New','file',
                    'new.txt',repeat('9',64),'internal','active',TRUE,now(),now())
            """
        )
        task = asyncio.create_task(
            _native_insert(
                database,
                "concurrent-missing",
                "space-a",
                "scope-a",
                "document-concurrent-new",
                "new.txt",
            )
        )
        await asyncio.sleep(0.1)
        assert not task.done()
        await parent.execute("COMMIT")
        await task
    finally:
        if parent.is_in_transaction():
            await parent.execute("ROLLBACK")
        await parent.close()
    assert await _event_exists(
        engine, "concurrent-missing", 1, "vector.upsert_locator_profile"
    )


async def _native_insert(database, *parameters: str) -> None:
    contender = await database.connect()
    try:
        await contender.execute(_NATIVE_CHUNK_INSERT, *parameters)
    finally:
        await contender.close()


async def _assert_runtime_acl(database, engine) -> None:
    runtime_password = "locator-parent-runtime-test-only"
    admin = await database.connect()
    try:
        await admin.execute(
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='infinity_context_runtime') THEN
                CREATE ROLE infinity_context_runtime LOGIN NOINHERIT NOSUPERUSER
                  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
              END IF;
              ALTER ROLE infinity_context_runtime PASSWORD
                'locator-parent-runtime-test-only';
            END $$
            """
        )
    finally:
        await admin.close()
    await reconcile_runtime_acl(engine)
    runtime = await database.asyncpg.connect(
        database.raw_dsn,
        user="infinity_context_runtime",
        password=runtime_password,
    )
    try:
        assert await runtime.fetchval("SELECT current_user") == "infinity_context_runtime"
        assert not await runtime.fetchval(
            "SELECT has_function_privilege(current_user, "
            "'public.memory_document_invalidate_locator_children_v1()', 'EXECUTE')"
        )
        await runtime.execute(
            "UPDATE memory_documents SET status='superseded' WHERE id='document-a'"
        )
        assert (
            await runtime.fetchval(
                "SELECT retrieval_version FROM memory_chunks WHERE id='chunk-good'"
            )
            == 4
        )
        await runtime.execute("UPDATE memory_documents SET status='active' WHERE id='document-a'")
        assert (
            await runtime.fetchval(
                "SELECT retrieval_version FROM memory_chunks WHERE id='chunk-good'"
            )
            == 5
        )
        with pytest.raises(Exception, match="eligible exact canonical document parent"):
            await runtime.execute(
                _NATIVE_CHUNK_INSERT,
                "runtime-missing",
                "space-a",
                "scope-a",
                "missing-document",
                "missing.txt",
            )
    finally:
        await runtime.close()


async def _assert_capability_fence(database, asyncpg) -> None:
    connection = await database.connect()
    await connection.execute("BEGIN")
    try:
        with pytest.raises(
            asyncpg.ObjectNotInPrerequisiteStateError,
            match="lacks locator parent lifecycle capability 0059",
        ):
            await connection.execute(_RUNTIME_CLONE_INSERT)
        await connection.execute("ROLLBACK")
        await connection.execute("BEGIN")
        await connection.execute(
            "SELECT set_config('infinity_context.locator_parent_capability','0059',true)"
        )
        await connection.execute(
            _RUNTIME_CLONE_INSERT.replace(
                "release_identity_sha256)",
                "release_identity_sha256,locator_parent_capability)",
            ).replace("repeat('0',64)\nFROM", "repeat('0',64),1\nFROM"),
        )
        await connection.execute(
            "SELECT set_config('infinity_context.locator_parent_capability','',true)"
        )
        await connection.execute(
            "UPDATE memory_locator_runtime_incarnations SET last_seen_at=now() "
            "WHERE instance_id='post-0059-runtime'"
        )
    finally:
        if connection.is_in_transaction():
            await connection.execute("ROLLBACK")
        await connection.close()


async def _assert_catalog(engine) -> None:
    async with engine.connect() as connection:
        attestation = await attest_locator_retrieval_catalog(connection)
        assert attestation.qualified, "\n".join(map(str, attestation.mismatches))
        column = (
            await connection.execute(
                text(
                    """
                    SELECT data_type,is_nullable,column_default
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='memory_chunks'
                      AND column_name='retrieval_parent_version'
                    """
                )
            )
        ).one()
        capability_column = (
            await connection.execute(
                text(
                    """
                    SELECT data_type,is_nullable,column_default
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='memory_locator_runtime_incarnations'
                      AND column_name='locator_parent_capability'
                    """
                )
            )
        ).one()
        constraints = (
            await connection.execute(
                text(
                    """
                    SELECT convalidated,pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname IN (
                      'ck_locator_runtime_parent_capability',
                      'ck_memory_chunks_retrieval_parent_version_positive')
                    ORDER BY conname
                    """
                )
            )
        ).all()
        function_rows = (
            await connection.execute(
                text(
                    """
                    SELECT proname,pg_get_functiondef(procedure.oid),owner.rolname,
                           prosecdef,proconfig
                    FROM pg_proc AS procedure JOIN pg_namespace AS namespace
                      ON namespace.oid=procedure.pronamespace
                    JOIN pg_roles AS owner ON owner.oid=procedure.proowner
                    WHERE namespace.nspname='public' AND proname IN (
                      'memory_chunk_require_locator_parent_v1',
                      'memory_chunk_locator_profile_events_v2',
                      'memory_document_lock_locator_parent_v1',
                      'memory_document_invalidate_locator_children_v1',
                      'memory_locator_require_parent_capability_v1')
                    """
                )
            )
        ).all()
        functions = {row[0]: row for row in function_rows}
        triggers = dict(
            (
                await connection.execute(
                    text(
                        """
                        SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger
                        WHERE NOT tgisinternal AND tgrelid IN (
                          'public.memory_chunks'::regclass,
                          'public.memory_documents'::regclass,
                          'public.memory_locator_runtime_incarnations'::regclass)
                        """
                    )
                )
            ).all()
        )
        definer_acl = (
            await connection.execute(
                text(
                    """
                    SELECT acl.grantee,acl.privilege_type
                    FROM pg_proc AS procedure
                    CROSS JOIN LATERAL aclexplode(COALESCE(
                      procedure.proacl,acldefault('f',procedure.proowner))) AS acl
                    WHERE procedure.oid=
                      'public.memory_document_invalidate_locator_children_v1()'::regprocedure
                    ORDER BY acl.grantee,acl.privilege_type
                    """
                )
            )
        ).all()
        retired = await connection.scalar(
            text(
                """
                SELECT count(*) FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
                WHERE namespace.nspname='public'
                  AND proname IN ('memory_locator_chunk_parent_eligible_v1',
                                  'memory_chunk_locator_projection_events_v2')
                """
            )
        )
        retired_table = await connection.scalar(
            text("SELECT to_regclass('public.memory_locator_projection_tombstones')")
        )
    assert tuple(column) == ("bigint", "NO", "1")
    assert tuple(capability_column) == ("bigint", "NO", "0")
    assert len(constraints) == 2
    assert all(row[0] is True for row in constraints)
    assert "locator_parent_capability" in constraints[0][1]
    assert "ARRAY[(0)::bigint, (1)::bigint]" in constraints[0][1]
    assert "retrieval_parent_version >= 1" in constraints[1][1]
    assert "9007199254740991" in constraints[1][1]
    assert set(functions) == {
        "memory_chunk_require_locator_parent_v1",
        "memory_chunk_locator_profile_events_v2",
        "memory_document_lock_locator_parent_v1",
        "memory_document_invalidate_locator_children_v1",
        "memory_locator_require_parent_capability_v1",
    }
    assert all(
        "SET search_path TO 'pg_catalog', 'public', 'pg_temp'" in body
        for _name, body, _owner, _definer, _config in functions.values()
    )
    assert all(row[2] != "infinity_context_runtime" for row in functions.values())
    assert functions["memory_chunk_require_locator_parent_v1"][3] is False
    assert functions["memory_chunk_locator_profile_events_v2"][3] is False
    assert functions["memory_document_lock_locator_parent_v1"][3] is False
    assert functions["memory_document_invalidate_locator_children_v1"][3] is True
    assert all(grantee != 0 for grantee, _privilege in definer_acl)
    assert "FOR NO KEY UPDATE OF document" in functions["memory_chunk_require_locator_parent_v1"][1]
    assert "EXISTS (" in functions["memory_chunk_locator_profile_events_v2"][1]
    assert "trg_00_memory_chunk_require_locator_parent" in triggers
    assert "trg_01_document_locator_parent_lock_insert" in triggers
    assert "trg_document_invalidate_locator_children_insert" in triggers
    assert "trg_00_locator_runtime_parent_capability" in triggers
    assert "BEFORE INSERT OR UPDATE" in triggers["trg_00_memory_chunk_require_locator_parent"]
    assert "AFTER INSERT" in triggers["trg_document_invalidate_locator_children_insert"]
    for trigger_name in (
        "trg_00_memory_chunks_benchmark_document_child_lock",
        "trg_memory_chunks_benchmark_document_child_fence",
    ):
        definition = triggers[trigger_name]
        assert "BEFORE INSERT OR DELETE OR UPDATE OF" in definition
        assert "retrieval_parent_version" not in definition
        assert "text" in definition
        assert "document_id" in definition
        assert "retrieval_locator" in definition
    assert retired == 0
    assert retired_table is None


async def _canonical_ids(engine, space_id: str, scope_id: str) -> tuple[str, ...]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT chunk.id FROM memory_chunks AS chunk
                    WHERE chunk.space_id=:space_id AND chunk.memory_scope_id=:scope_id
                      AND chunk.status='active' AND chunk.retrieval_locator IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM memory_documents AS document
                        WHERE document.id=chunk.document_id
                          AND document.space_id=chunk.space_id
                          AND document.memory_scope_id=chunk.memory_scope_id
                          AND document.thread_id IS NOT DISTINCT FROM chunk.thread_id
                          AND document.source_type=chunk.source_type
                          AND document.source_external_id=chunk.source_external_id
                          AND document.classification=chunk.classification
                          AND document.status='active' AND document.retrieval_projected)
                    ORDER BY chunk.id
                    """
                ),
                {"space_id": space_id, "scope_id": scope_id},
            )
        ).scalars()
        return tuple(rows)


async def _version(engine, chunk_id: str) -> tuple[int, int]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT retrieval_version,retrieval_parent_version "
                    "FROM memory_chunks WHERE id=:chunk_id"
                ),
                {"chunk_id": chunk_id},
            )
        ).one()
        return int(row[0]), int(row[1])


async def _tombstone(engine, chunk_id: str) -> int | None:
    async with engine.connect() as connection:
        value = await connection.scalar(
            text(
                "SELECT canonical_version FROM memory_locator_profile_tombstones "
                "WHERE profile_id='profile-parent' AND chunk_id=:chunk_id"
            ),
            {"chunk_id": chunk_id},
        )
        return int(value) if value is not None else None


async def _event_exists(engine, chunk_id: str, version: int, event_type: str) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM memory_outbox WHERE aggregate_id=:chunk_id "
                    "AND aggregate_version=:version AND event_type=:event_type)"
                ),
                {"chunk_id": chunk_id, "version": version, "event_type": event_type},
            )
        )


def _root_exception(error: BaseException) -> BaseException:
    current = error
    while current.__cause__ is not None:
        current = current.__cause__
    return current


_CHUNK_INSERT = """
INSERT INTO memory_chunks
  (id,space_id,memory_scope_id,thread_id,document_id,episode_id,source_type,
   source_external_id,source_hash,kind,text,normalized_text,status,sequence,
   char_start,char_end,token_estimate,classification,created_at,updated_at,
   metadata_json,retrieval_locator,retrieval_source_key,
   retrieval_projection_generation,retrieval_sequence_ordinal,retrieval_kind,
   retrieval_category)
VALUES (CAST(:chunk_id AS varchar(80)),:space_id,:scope_id,NULL,:document_id,NULL,'file',:source,
        repeat('f',64),'document_section',CAST(:chunk_id AS text),CAST(:chunk_id AS text),
        'active',0,0,10,2,'internal',now(),now(),'{}'::jsonb,'locator/' || CAST(:chunk_id AS text),
        'source-' || CAST(:chunk_id AS text),
        'generation',0,'record','decision')
"""

_NATIVE_CHUNK_INSERT = (
    _CHUNK_INSERT.replace(":chunk_id", "$1")
    .replace(":space_id", "$2")
    .replace(":scope_id", "$3")
    .replace(":document_id", "$4")
    .replace(":source", "$5")
)

_RUNTIME_CLONE_INSERT = """
INSERT INTO memory_locator_runtime_incarnations
  (instance_id,generation,registered_at,last_seen_at,acknowledged_generation,
   supervisor_key_id,supervisor_public_key,trust_root_sha256,
   trust_registry_generation,launch_token,process_pid,process_birth_identity,
   executable_identity,executable_sha256,launch_identity_sha256,
   release_revision,release_source_tree_sha256,
   release_installed_distribution_sha256,release_runtime_modules_sha256,
   release_identity_sha256)
SELECT 'post-0059-runtime','generation',now(),now(),0,supervisor_key_id,
       supervisor_public_key,trust_root_sha256,trust_registry_generation,
       'post-0059-launch',process_pid,process_birth_identity,executable_identity,
       executable_sha256,launch_identity_sha256,release_revision,
       release_source_tree_sha256,release_installed_distribution_sha256,
       release_runtime_modules_sha256,repeat('0',64)
FROM memory_locator_runtime_incarnations WHERE instance_id='pre-0059-runtime'
"""
