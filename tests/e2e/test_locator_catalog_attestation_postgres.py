"""Adversarial PostgreSQL catalog proof for Retrieval V2."""

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
    attest_locator_retrieval_v2_catalog,
    lock_and_attest_locator_retrieval_v2_catalog,
)
from infinity_context_server.retrieval_composition import (
    _postgres_profile_qualified,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


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
            await build_locator_retrieval_indexes(engine)
            async with engine.connect() as connection:
                version = int(await connection.scalar(text("SHOW server_version_num")))
                assert version // 10000 in {16, 17, 18}
                assert (await attest_locator_retrieval_v2_catalog(connection)).qualified
            session_factory = build_session_factory(engine)
            assert await _postgres_profile_qualified(session_factory)

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

            async with engine.begin() as connection:
                await lock_and_attest_locator_retrieval_v2_catalog(connection)
            await _assert_exactly_one_locator_owner(database, engine)
            assert await _postgres_profile_qualified(session_factory)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_unqualified(engine, session_factory, kind: str, properties: set[str]) -> None:
    async with engine.begin() as connection:
        attestation = await attest_locator_retrieval_v2_catalog(connection)
        assert not attestation.qualified
        relevant = {
            mismatch.property_name
            for mismatch in attestation.mismatches
            if mismatch.object_kind == kind
        }
        assert properties <= relevant
        with pytest.raises(RuntimeError, match="catalog is not exact"):
            await lock_and_attest_locator_retrieval_v2_catalog(connection)
    assert not await _postgres_profile_qualified(session_factory)


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
                (id,space_id,memory_scope_id,title,source_type,source_external_id,
                 content_hash,classification,status,created_at,updated_at) VALUES
                ('catalog-doc-a','catalog-space','catalog-scope','A','file','a',
                 repeat('a',64),'internal','active',now(),now()),
                ('catalog-doc-b','catalog-space','catalog-scope','B','file','b',
                 repeat('b',64),'internal','active',now(),now())""",
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
