"""Adversarial PostgreSQL catalog proof for Retrieval."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_locator_retrieval_indexes,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_catalog_attestation import (
    attest_locator_retrieval_catalog,
    lock_and_attest_locator_retrieval_catalog,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text

_PUBLISHED_0039_CHECKSUM = (
    "83f22c9e4087e6f4713294665a00ce99f7ffc981893702a2fbb3a575813c418d"
)


def test_exact_locator_catalog_attestation_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_catalog_attestation(database_url))


async def _assert_catalog_attestation(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_catalog", asyncpg=asyncpg
    )
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE infinity_context_schema_migrations SET checksum = :checksum "
                        "WHERE migration_id = '0039_locator_retrieval_attributes'"
                    ),
                    {"checksum": _PUBLISHED_0039_CHECKSUM},
                )
            async with engine.connect() as connection:
                before_indexes = await attest_locator_retrieval_catalog(connection)
                non_index_mismatches = tuple(
                    mismatch
                    for mismatch in before_indexes.mismatches
                    if mismatch.object_kind != "index"
                )
                assert not non_index_mismatches, _safe_mismatch_diagnostics(
                    non_index_mismatches
                )
            await build_locator_retrieval_indexes(engine)
            async with engine.connect() as connection:
                version = int(await connection.scalar(text("SHOW server_version_num")))
                assert version // 10000 in {16, 17, 18}
                assert (await attest_locator_retrieval_catalog(connection)).qualified
            session_factory = build_session_factory(engine)
            async with session_factory() as session:
                assert (await attest_locator_retrieval_catalog(session)).qualified

            original_oid = await _index_oid(engine)
            await _replace_locator_index_with_wrong_definition(engine)
            await _assert_unqualified(engine, session_factory, "index", {"keys", "predicate"})
            await build_locator_retrieval_indexes(engine)
            assert await _index_oid(engine) != original_oid
            repaired_oid = await _index_oid(engine)
            await build_locator_retrieval_indexes(engine)
            assert await _index_oid(engine) == repaired_oid

            await _replace_constraint_with_wrong_definition(engine)
            await _assert_unqualified(engine, session_factory, "constraint", {"definition"})
            with pytest.raises(RuntimeError, match="cannot be repaired"):
                await build_locator_retrieval_indexes(engine)
            await _restore_constraint(engine)

            await _replace_trigger_with_wrong_events(engine)
            await _assert_unqualified(engine, session_factory, "trigger", {"type"})
            with pytest.raises(RuntimeError, match="cannot be repaired"):
                await build_locator_retrieval_indexes(engine)
            await _restore_trigger(engine)

            await _assert_lifecycle_catalog_drift_is_rejected(engine)

            async with engine.begin() as connection:
                await lock_and_attest_locator_retrieval_catalog(connection)
            await _assert_exactly_one_locator_owner(database, engine)
            async with session_factory() as session:
                assert (await attest_locator_retrieval_catalog(session)).qualified
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_unqualified(engine, session_factory, kind: str, properties: set[str]) -> None:
    async with engine.begin() as connection:
        attestation = await attest_locator_retrieval_catalog(connection)
        assert not attestation.qualified
        relevant = {
            mismatch.property_name
            for mismatch in attestation.mismatches
            if mismatch.object_kind == kind
        }
        assert properties <= relevant
        with pytest.raises(RuntimeError, match="catalog is not exact"):
            await lock_and_attest_locator_retrieval_catalog(connection)
    async with session_factory() as session:
        assert not (await attest_locator_retrieval_catalog(session)).qualified


def _safe_mismatch_diagnostics(mismatches) -> tuple[dict[str, object], ...]:
    """Expose attested differences without dumping catalog rows or connection data."""

    return tuple(
        {
            "object_kind": mismatch.object_kind,
            "object_name": mismatch.object_name,
            "property": mismatch.property_name,
            "expected": mismatch.expected,
            "observed": mismatch.observed,
        }
        for mismatch in mismatches
    )


async def _replace_locator_index_with_wrong_definition(engine) -> None:
    connection = await engine.connect()
    connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
    try:
        await connection.execute(
            text("DROP INDEX CONCURRENTLY uq_memory_chunks_retrieval_locator_owner")
        )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_memory_chunks_retrieval_locator_owner "
                "ON memory_chunks (space_id, retrieval_locator) "
                "WHERE retrieval_locator IS NULL"
            )
        )
    finally:
        await connection.close()


async def _replace_constraint_with_wrong_definition(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE memory_chunks DROP CONSTRAINT "
                "ck_memory_chunks_retrieval_version_positive"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE memory_chunks ADD CONSTRAINT "
                "ck_memory_chunks_retrieval_version_positive "
                "CHECK (retrieval_version > 0) NOT VALID"
            )
        )


async def _restore_constraint(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE memory_chunks DROP CONSTRAINT "
                "ck_memory_chunks_retrieval_version_positive"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE memory_chunks ADD CONSTRAINT "
                "ck_memory_chunks_retrieval_version_positive "
                "CHECK (retrieval_version BETWEEN 1 AND 9007199254740991) NOT VALID"
            )
        )


async def _replace_trigger_with_wrong_events(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DROP TRIGGER trg_memory_chunk_retrieval_fence_v2 ON memory_chunks")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER trg_memory_chunk_retrieval_fence_v2 "
                "BEFORE INSERT ON memory_chunks FOR EACH ROW "
                "EXECUTE FUNCTION memory_chunk_retrieval_fence_v2()"
            )
        )


async def _restore_trigger(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DROP TRIGGER trg_memory_chunk_retrieval_fence_v2 ON memory_chunks")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER trg_memory_chunk_retrieval_fence_v2 "
                "BEFORE INSERT OR UPDATE ON memory_chunks FOR EACH ROW "
                "EXECUTE FUNCTION memory_chunk_retrieval_fence_v2()"
            )
        )


async def _assert_lifecycle_catalog_drift_is_rejected(engine) -> None:
    cases = (
        (
            """CREATE OR REPLACE FUNCTION memory_document_invalidate_locator_children_v1()
            RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = pg_catalog, public, pg_temp
            AS $$ BEGIN RETURN NEW; END; $$""",
            "function",
            "memory_document_invalidate_locator_children_v1",
            "implementation",
        ),
        (
            "ALTER FUNCTION memory_chunk_require_locator_parent_v1() SECURITY DEFINER",
            "function",
            "memory_chunk_require_locator_parent_v1",
            "security_definer",
        ),
        (
            "ALTER FUNCTION memory_chunk_retrieval_fence_v2() RESET ALL",
            "function",
            "memory_chunk_retrieval_fence_v2",
            "search_path",
        ),
        (
            "ALTER FUNCTION memory_document_lock_locator_parent_v1() "
            "OWNER TO infinity_context_canonical_writer",
            "function",
            "memory_document_lock_locator_parent_v1",
            "owner_matches_table",
        ),
        (
            "GRANT EXECUTE ON FUNCTION memory_document_invalidate_locator_children_v1() "
            "TO PUBLIC",
            "function",
            "memory_document_invalidate_locator_children_v1",
            "effective_acl",
        ),
        (
            "ALTER TABLE memory_documents DISABLE TRIGGER "
            "trg_document_invalidate_locator_children_update",
            "trigger",
            "trg_document_invalidate_locator_children_update",
            "enabled",
        ),
        (
            """CREATE OR REPLACE TRIGGER
            trg_00_document_locator_profile_evidence_update
            BEFORE UPDATE ON memory_documents FOR EACH ROW
            WHEN (OLD.retrieval_projected IS DISTINCT FROM NEW.retrieval_projected)
            EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1()""",
            "trigger",
            "trg_00_document_locator_profile_evidence_update",
            "definition",
        ),
        (
            """CREATE OR REPLACE TRIGGER
            trg_00_document_locator_profile_evidence_update
            BEFORE UPDATE ON memory_documents FOR EACH ROW
            WHEN (OLD.retrieval_projected IS DISTINCT FROM NEW.retrieval_projected)
            EXECUTE FUNCTION memory_document_lock_locator_parent_v1()""",
            "trigger",
            "trg_00_document_locator_profile_evidence_update",
            "function",
        ),
        (
            "ALTER TABLE memory_chunks ALTER COLUMN retrieval_parent_version DROP DEFAULT",
            "column",
            "memory_chunks.retrieval_parent_version",
            "default",
        ),
        (
            "ALTER TABLE memory_chunks ALTER COLUMN retrieval_parent_version DROP NOT NULL",
            "column",
            "memory_chunks.retrieval_parent_version",
            "nullable",
        ),
        (
            "ALTER TABLE memory_chunks ALTER COLUMN retrieval_parent_version TYPE numeric "
            "USING retrieval_parent_version::numeric",
            "column",
            "memory_chunks.retrieval_parent_version",
            "type",
        ),
    )
    for statement, kind, name, property_name in cases:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(statement))
                attestation = await attest_locator_retrieval_catalog(connection)
                assert not attestation.qualified
                assert any(
                    mismatch.object_kind == kind
                    and mismatch.object_name == name
                    and mismatch.property_name == property_name
                    for mismatch in attestation.mismatches
                ), attestation.mismatches
                with pytest.raises(RuntimeError, match="catalog is not exact"):
                    await lock_and_attest_locator_retrieval_catalog(connection)
            finally:
                await transaction.rollback()


async def _index_oid(engine) -> int:
    async with engine.connect() as connection:
        return int(
            await connection.scalar(
                text("SELECT 'uq_memory_chunks_retrieval_locator_owner'::regclass::oid")
            )
        )


async def _assert_exactly_one_locator_owner(database, engine) -> None:
    async with engine.begin() as connection:
        for statement in (
            """INSERT INTO memory_spaces
                (id,slug,name,status,created_at,updated_at) VALUES
                ('catalog-space','catalog-space','Catalog','active',now(),now())""",
            """INSERT INTO memory_scopes
                (id,space_id,external_ref,name,status,created_at,updated_at) VALUES
                ('catalog-scope','catalog-space','catalog-scope','Catalog','active',now(),now())""",
            """INSERT INTO memory_documents
                (id,space_id,memory_scope_id,thread_id,title,source_type,
                 source_external_id,content_hash,classification,status,
                 retrieval_projected,created_at,updated_at) VALUES
                ('catalog-doc-a','catalog-space','catalog-scope',NULL,'A','file',
                 'catalog-chunk-a',repeat('a',64),'internal','active',TRUE,now(),now()),
                ('catalog-doc-b','catalog-space','catalog-scope',NULL,'B','file',
                 'catalog-chunk-b',repeat('b',64),'internal','active',TRUE,now(),now())""",
        ):
            await connection.execute(text(statement))

    async def insert(chunk: str, document: str) -> bool:
        connection = await database.connect()
        try:
            await connection.execute(
                """INSERT INTO memory_chunks
                (id,space_id,memory_scope_id,document_id,source_type,
                 source_external_id,source_hash,kind,text,normalized_text,status,
                 sequence,char_start,char_end,token_estimate,classification,
                 created_at,updated_at,metadata_json,retrieval_locator,
                 retrieval_source_key,retrieval_projection_generation,
                 retrieval_sequence_ordinal,retrieval_kind,retrieval_category)
                VALUES ($1,'catalog-space','catalog-scope',$2,'file',$1,
                 repeat('c',64),'paragraph','text','text','active',0,0,4,1,
                 'internal',now(),now(),'{}'::jsonb,'shared-locator','source','gen',
                 0,'record','decision')""",
                chunk,
                document,
            )
            return True
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                return False
            raise
        finally:
            await connection.close()

    outcomes = await asyncio.gather(
        insert("catalog-chunk-a", "catalog-doc-a"),
        insert("catalog-chunk-b", "catalog-doc-b"),
    )
    assert sorted(outcomes) == [False, True]
    async with engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM memory_chunks WHERE retrieval_locator='shared-locator'")
            )
            == 1
        )
