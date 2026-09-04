"""PostgreSQL 18 regression proof for locator-child retraction."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.runtime_acl import reconcile_runtime_acl
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_locator_parent_lifecycle_postgres import (
    _assert_benchmark_fence_persistence,
    _seed_pre_0059,
)
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_locator_parent_retraction_when_postgres18_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_parent_retraction(database_url))


async def _assert_parent_retraction(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_parent_retraction_0059", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0058_")
        seed = await database.connect()
        try:
            await _seed_pre_0059(seed)
        finally:
            await seed.close()

        engine = build_async_engine(database.app_url)
        try:
            upgraded = await upgrade_schema(engine)
            assert upgraded.applied == ("0059_locator_parent_lifecycle",)
            await _assert_coordinate_edit_egress(engine)
            await _assert_classification_tightening(engine, asyncpg)
            await _assert_owner_retraction(engine, asyncpg)
            await _assert_benchmark_fence_persistence(engine, asyncpg)
            await _assert_runtime_retraction(database, engine, asyncpg)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_owner_retraction(engine, asyncpg) -> None:
    evidence_before = await _evidence_version(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_documents SET status='superseded' WHERE id='document-a'")
        )
    assert await _chunk_state(engine, "chunk-good") == ("active", 2, 2)
    assert await _profile_tombstone_version(engine, "chunk-good") == 2
    assert await _evidence_version(engine) > evidence_before
    assert await _chunk_classification_state(engine, "chunk-tightening") == (
        "internal",
        "active",
        4,
        2,
    )
    # Security tightening remains available after the exact parent becomes
    # lifecycle-ineligible; the inverse operation must not re-admit the child.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE memory_chunks SET classification='restricted' "
                "WHERE id='chunk-tightening'"
            )
        )
    assert await _chunk_classification_state(engine, "chunk-tightening") == (
        "restricted",
        "active",
        5,
        2,
    )
    assert await _profile_tombstone_version(engine, "chunk-tightening") == 5
    assert await _profile_event_exists(
        engine, "chunk-tightening", 5, "vector.delete_locator_profile"
    )
    restoration = await _rejected_update(
        engine,
        "UPDATE memory_chunks SET classification='internal' "
        "WHERE id='chunk-tightening'",
    )
    root = _root_exception(restoration)
    assert isinstance(root, asyncpg.ForeignKeyViolationError)
    assert root.sqlstate == "23503"

    # Complete internal -> restricted -> deleted egress while the exact parent
    # remains inactive. Deletion must not try to match the restricted child to
    # the still-internal parent's mutable classification.
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_chunks SET status='deleted' WHERE id='chunk-tightening'")
        )
    assert await _chunk_classification_state(engine, "chunk-tightening") == (
        "restricted",
        "deleted",
        6,
        2,
    )
    assert await _profile_tombstone_version(engine, "chunk-tightening") == 6
    assert await _profile_event_exists(
        engine, "chunk-tightening", 6, "vector.delete_locator_profile"
    )

    # A deleted transition cannot smuggle a parent, scope, source,
    # classification, or locator identity mutation.
    for assignment in (
        "document_id='document-b'",
        "space_id='space-b'",
        "memory_scope_id='scope-b'",
        "thread_id='changed-thread'",
        "source_type='changed-type'",
        "source_external_id='changed.txt'",
        "source_hash=repeat('8',64)",
        "classification='public'",
        "retrieval_locator=NULL",
        "retrieval_source_key='changed-source'",
        "retrieval_projection_generation='changed-generation'",
        "retrieval_sequence_ordinal=9",
        "retrieval_kind='changed-kind'",
        "retrieval_category='entity'",
    ):
        error = await _rejected_update(
            engine,
            f"UPDATE memory_chunks SET status='deleted', {assignment} "
            "WHERE id='chunk-good'",
        )
        root = _root_exception(error)
        assert isinstance(root, asyncpg.CheckViolationError)
        assert root.sqlstate == "23514"
        assert "retraction must preserve canonical parent identity" in str(root)

    rebind = await _rejected_update(
        engine, "UPDATE memory_chunks SET document_id='document-b' WHERE id='chunk-good'"
    )
    root = _root_exception(rebind)
    assert isinstance(root, asyncpg.ForeignKeyViolationError)
    assert root.sqlstate == "23503"

    evidence_before_retraction = await _evidence_version(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_chunks SET status='deleted' WHERE id='chunk-good'")
        )
    assert await _chunk_state(engine, "chunk-good") == ("deleted", 3, 2)
    assert await _profile_tombstone_version(engine, "chunk-good") == 3
    assert await _profile_event_exists(engine, "chunk-good", 3, "vector.delete_locator_profile")
    assert not await _legacy_event_exists(engine, "chunk-good", 3)
    assert await _evidence_version(engine) > evidence_before_retraction

    resurrection = await _rejected_update(
        engine, "UPDATE memory_chunks SET status='active' WHERE id='chunk-good'"
    )
    root = _root_exception(resurrection)
    assert isinstance(root, asyncpg.ForeignKeyViolationError)
    assert root.sqlstate == "23503"
    assert await _chunk_state(engine, "chunk-good") == ("deleted", 3, 2)

    orphan = await _rejected_update(
        engine, "UPDATE memory_chunks SET status='deleted' WHERE id='chunk-orphan'"
    )
    root = _root_exception(orphan)
    assert isinstance(root, asyncpg.ForeignKeyViolationError)
    assert root.sqlstate == "23503"
    assert await _chunk_state(engine, "chunk-orphan") == ("active", 2, 2)

    insertion = await _rejected_update(
        engine,
        """
        INSERT INTO memory_chunks
          (id,space_id,memory_scope_id,thread_id,document_id,episode_id,source_type,
           source_external_id,source_hash,kind,text,normalized_text,status,sequence,
           char_start,char_end,token_estimate,classification,created_at,updated_at,
           metadata_json,retrieval_locator,retrieval_source_key,
           retrieval_projection_generation,retrieval_sequence_ordinal,retrieval_kind,
           retrieval_category)
        VALUES ('new-active-orphan','space-a','scope-a',NULL,'missing-document',NULL,
                'file','missing.txt',repeat('9',64),'document_section','orphan','orphan',
                'active',0,0,6,1,'internal',now(),now(),'{}'::jsonb,
                'locator/new-active-orphan','missing.txt','generation',0,'record','decision')
        """,
    )
    root = _root_exception(insertion)
    assert isinstance(root, asyncpg.ForeignKeyViolationError)
    assert root.sqlstate == "23503"


async def _assert_coordinate_edit_egress(engine) -> None:
    cases = (
        ("source-delete", "source_external_id='renamed.txt'", "status='deleted'"),
        (
            "source-restrict",
            "source_external_id='renamed-2.txt'",
            "classification='restricted'",
        ),
        ("scope-delete", "memory_scope_id='scope-b'", "status='deleted'"),
        (
            "thread-restrict",
            "thread_id='changed-thread'",
            "classification='restricted'",
        ),
        ("type-delete", "source_type='changed-type'", "status='deleted'"),
    )
    async with engine.begin() as connection:
        for index, (suffix, _, _) in enumerate(cases):
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_documents
                      (id,space_id,memory_scope_id,thread_id,title,source_type,
                       source_external_id,content_hash,classification,status,
                       retrieval_projected,created_at,updated_at)
                    VALUES (:document_id,'space-a','scope-a',NULL,:suffix,'file',
                            :source_external_id,:content_hash,'internal','active',TRUE,
                            now(),now())
                    """
                ),
                {
                    "document_id": f"document-{suffix}",
                    "suffix": suffix,
                    "source_external_id": f"{suffix}.txt",
                    "content_hash": f"{index + 1:064x}",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_chunks
                      (id,space_id,memory_scope_id,thread_id,document_id,episode_id,
                       source_type,source_external_id,source_hash,kind,text,
                       normalized_text,status,sequence,char_start,char_end,
                       token_estimate,classification,created_at,updated_at,metadata_json,
                       retrieval_locator,retrieval_source_key,
                       retrieval_projection_generation,retrieval_sequence_ordinal,
                       retrieval_kind,retrieval_category)
                    VALUES (:chunk_id,'space-a','scope-a',NULL,:document_id,NULL,'file',
                            :source_external_id,:source_hash,'document_section',:suffix,
                            :suffix,'active',0,0,10,2,'internal',now(),now(),'{}'::jsonb,
                            :locator,:source_external_id,'generation',0,'record','decision')
                    """
                ),
                {
                    "chunk_id": f"chunk-{suffix}",
                    "document_id": f"document-{suffix}",
                    "suffix": suffix,
                    "source_external_id": f"{suffix}.txt",
                    "source_hash": f"{index + 101:064x}",
                    "locator": f"locator/chunk-{suffix}",
                },
            )

    for suffix, parent_edit, child_egress in cases:
        document_id = f"document-{suffix}"
        chunk_id = f"chunk-{suffix}"
        async with engine.begin() as connection:
            await connection.execute(
                text(f"UPDATE memory_documents SET {parent_edit} WHERE id=:id"),
                {"id": document_id},
            )
            await connection.execute(
                text(f"UPDATE memory_chunks SET {child_egress} WHERE id=:id"),
                {"id": chunk_id},
            )
            await connection.execute(
                text(
                    "UPDATE memory_documents SET memory_scope_id='scope-a',thread_id=NULL,"
                    "source_type='file',source_external_id=:source WHERE id=:id"
                ),
                {"id": document_id, "source": f"{suffix}.txt"},
            )

        expected_status = "deleted" if "status" in child_egress else "active"
        expected_classification = (
            "restricted" if "classification" in child_egress else "internal"
        )
        assert await _chunk_classification_state(engine, chunk_id) == (
            expected_classification,
            expected_status,
            4,
            3,
        )
        assert await _profile_tombstone_version(engine, chunk_id) == 4
        assert await _profile_event_exists(
            engine, chunk_id, 4, "vector.delete_locator_profile"
        )
        assert not await _profile_event_exists(
            engine, chunk_id, 4, "vector.upsert_locator_profile"
        )


async def _assert_classification_tightening(engine, asyncpg) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO memory_chunks
                  (id,space_id,memory_scope_id,thread_id,document_id,episode_id,
                   source_type,source_external_id,source_hash,kind,text,normalized_text,
                   status,sequence,char_start,char_end,token_estimate,classification,
                   created_at,updated_at,metadata_json,retrieval_locator,
                   retrieval_source_key,retrieval_projection_generation,
                   retrieval_sequence_ordinal,retrieval_kind,retrieval_category)
                SELECT 'chunk-tightening',space_id,memory_scope_id,thread_id,document_id,
                       episode_id,source_type,source_external_id,repeat('7',64),kind,
                       text,normalized_text,status,sequence,char_start,char_end,
                       token_estimate,classification,now(),now(),metadata_json,
                       'locator/chunk-tightening',retrieval_source_key,
                       retrieval_projection_generation,retrieval_sequence_ordinal,
                       retrieval_kind,retrieval_category
                FROM memory_chunks WHERE id='chunk-good'
                """
            )
        )
        await connection.execute(
            text(
                "UPDATE memory_chunks SET classification='restricted' "
                "WHERE id='chunk-tightening'"
            )
        )
    assert await _chunk_classification_state(engine, "chunk-tightening") == (
        "restricted",
        "active",
        2,
        1,
    )
    assert await _profile_tombstone_version(engine, "chunk-tightening") == 2
    assert await _profile_event_exists(
        engine, "chunk-tightening", 2, "vector.delete_locator_profile"
    )

    # Eligible restoration still takes the normal exact-parent admission path.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE memory_chunks SET classification='internal' "
                "WHERE id='chunk-tightening'"
            )
        )
    assert await _chunk_classification_state(engine, "chunk-tightening") == (
        "internal",
        "active",
        3,
        1,
    )
    assert await _profile_tombstone_version(engine, "chunk-tightening") is None
    assert await _profile_event_exists(
        engine, "chunk-tightening", 3, "vector.upsert_locator_profile"
    )

    # The tightening lane cannot carry a foreign canonical identity edit.
    for assignment in (
        "document_id='document-b'",
        "space_id='space-b'",
        "memory_scope_id='scope-b'",
        "source_external_id='changed.txt'",
        "retrieval_locator=NULL",
        "retrieval_source_key='changed-source'",
        "retrieval_sequence_ordinal=9",
        "retrieval_category='entity'",
    ):
        error = await _rejected_update(
            engine,
            f"UPDATE memory_chunks SET classification='restricted', {assignment} "
            "WHERE id='chunk-tightening'",
        )
        root = _root_exception(error)
        assert isinstance(root, asyncpg.CheckViolationError)
        assert root.sqlstate == "23514"
        assert "classification tightening must preserve canonical parent identity" in str(root)


async def _assert_runtime_retraction(database, engine, asyncpg) -> None:
    password = "locator-parent-retraction-runtime-only"
    admin = await database.connect()
    try:
        await admin.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname='infinity_context_runtime'
              ) THEN
                CREATE ROLE infinity_context_runtime LOGIN NOINHERIT NOSUPERUSER
                  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
              END IF;
              ALTER ROLE infinity_context_runtime PASSWORD '{password}';
            END $$
            """
        )
    finally:
        await admin.close()
    await reconcile_runtime_acl(engine)

    runtime = await database.asyncpg.connect(
        database.raw_dsn, user="infinity_context_runtime", password=password
    )
    try:
        assert await runtime.fetchval("SELECT current_user") == "infinity_context_runtime"
        await runtime.execute(
            "UPDATE memory_documents SET status='deleted' WHERE id='document-b'"
        )
        assert tuple(
            await runtime.fetchrow(
                "SELECT status,retrieval_version,retrieval_parent_version "
                "FROM memory_chunks WHERE id='chunk-foreign'"
            )
        ) == ("active", 2, 2)
        await runtime.execute(
            "UPDATE memory_chunks SET status='deleted' WHERE id='chunk-foreign'"
        )
        assert tuple(
            await runtime.fetchrow(
                "SELECT status,retrieval_version,retrieval_parent_version "
                "FROM memory_chunks WHERE id='chunk-foreign'"
            )
        ) == ("deleted", 3, 2)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await runtime.execute(
                "UPDATE memory_chunks SET status='active' WHERE id='chunk-foreign'"
            )
    finally:
        await runtime.close()

    assert await _profile_tombstone_version(engine, "chunk-foreign") == 3
    assert await _profile_event_exists(
        engine, "chunk-foreign", 3, "vector.delete_locator_profile"
    )


async def _rejected_update(engine, statement: str) -> BaseException:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(Exception) as raised:
                await connection.execute(text(statement))
            return raised.value
        finally:
            await transaction.rollback()


async def _chunk_state(engine, chunk_id: str) -> tuple[str, int, int]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT status,retrieval_version,retrieval_parent_version "
                    "FROM memory_chunks WHERE id=:chunk_id"
                ),
                {"chunk_id": chunk_id},
            )
        ).one()
        return str(row[0]), int(row[1]), int(row[2])


async def _chunk_classification_state(
    engine, chunk_id: str
) -> tuple[str, str, int, int]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT classification,status,retrieval_version,retrieval_parent_version "
                    "FROM memory_chunks WHERE id=:chunk_id"
                ),
                {"chunk_id": chunk_id},
            )
        ).one()
        return str(row[0]), str(row[1]), int(row[2]), int(row[3])


async def _profile_tombstone_version(engine, chunk_id: str) -> int | None:
    async with engine.connect() as connection:
        value = await connection.scalar(
            text(
                "SELECT canonical_version FROM memory_locator_profile_tombstones "
                "WHERE profile_id='profile-parent' AND chunk_id=:chunk_id"
            ),
            {"chunk_id": chunk_id},
        )
        return int(value) if value is not None else None


async def _profile_event_exists(
    engine, chunk_id: str, version: int, event_type: str
) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM memory_outbox "
                    "WHERE aggregate_id=:chunk_id AND aggregate_version=:version "
                    "AND event_type=:event_type)"
                ),
                {"chunk_id": chunk_id, "version": version, "event_type": event_type},
            )
        )


async def _legacy_event_exists(engine, chunk_id: str, version: int) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM memory_outbox "
                    "WHERE aggregate_id=:chunk_id AND aggregate_version=:version "
                    "AND event_type IN ('vector.delete_chunks','vector.upsert_chunk'))"
                ),
                {"chunk_id": chunk_id, "version": version},
            )
        )


async def _evidence_version(engine) -> int:
    async with engine.connect() as connection:
        return int(
            await connection.scalar(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton=TRUE"
                )
            )
        )


def _root_exception(error: BaseException) -> BaseException:
    current = error
    while current.__cause__ is not None:
        current = current.__cause__
    return current
