"""Live PostgreSQL proofs for coordinated snapshot fact imports."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryScopeRow,
    MemorySourceRefRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server.memory_scope_transfer import import_memory_scope_payload
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def test_postgres_test_database_name_respects_identifier_byte_limit() -> None:
    database = PostgresTestDatabase.from_url(
        "postgresql://user:password@localhost/postgres",
        prefix="snapshot_fence_" + "м" * 80,
        asyncpg=object(),
    )

    assert len(database.database_name.encode("utf-8")) <= 63
    assert database.database_name in database.raw_dsn


@pytest.mark.parametrize("case", ("remap", "external_id", "missing_chunk"))
def test_snapshot_import_remaps_and_validates_document_refs(case: str) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_snapshot_import(database_url, case=case))


@pytest.mark.parametrize("case", ("active_thread", "skipped_evidence", "deleted_thread"))
def test_snapshot_import_fences_threads_and_closes_skipped_evidence(case: str) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_snapshot_thread_fence(database_url, case=case))


async def _assert_snapshot_thread_fence(database_url: str, *, case: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"snapshot_fence_{case}",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        async with AsyncSession(engine) as session:
            session.add(
                MemorySpaceRow(
                    id="space-import",
                    slug="space-import",
                    name="Import space",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                MemoryScopeRow(
                    id="scope-base",
                    space_id="space-import",
                    external_ref="base",
                    name="Base",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                MemoryThreadRow(
                    id="thread-source",
                    space_id="space-import",
                    memory_scope_id="scope-base",
                    external_ref="thread-source",
                    status="deleted" if case == "deleted_thread" else "active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            if case == "skipped_evidence":
                session.add(
                    MemoryDocumentRow(
                        id="document-source",
                        space_id="space-import",
                        memory_scope_id="scope-base",
                        thread_id="thread-source",
                        title="Existing document",
                        source_type="text",
                        source_external_id="existing",
                        content_hash="existing-document-hash",
                        classification="unknown",
                        status="active",
                        retrieval_projected=False,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            await session.commit()

        payload = _snapshot(source_document_id="document-source")
        payload["threads"] = []
        if case == "deleted_thread":
            payload["facts"] = []
            payload["chunks"] = []
            payload["source_refs"] = []
            with pytest.raises(MemoryConflictError, match="neither active nor created"):
                await import_memory_scope_payload(
                    engine=engine,
                    now=NOW,
                    space_id="space-import",
                    memory_scope_id="scope-base",
                    payload=payload,
                    dry_run=False,
                    merge_strategy="skip_existing",
                )
        elif case == "skipped_evidence":
            result = await import_memory_scope_payload(
                engine=engine,
                now=NOW,
                space_id="space-import",
                memory_scope_id="scope-base",
                payload=payload,
                dry_run=False,
                merge_strategy="skip_existing",
            )
            assert result["status"] == "ok"
            assert result["imported"]["facts"] == 0
            assert result["imported"]["chunks"] == 0
            assert result["imported"]["source_refs"] == 0
            async with AsyncSession(engine) as session:
                assert await session.scalar(select(func.count()).select_from(MemoryFactRow)) == 0
                assert (
                    await session.scalar(select(func.count()).select_from(MemorySourceRefRow)) == 0
                )
        else:
            result = await import_memory_scope_payload(
                engine=engine,
                now=NOW,
                space_id="space-import",
                memory_scope_id="scope-base",
                payload=payload,
                dry_run=False,
                merge_strategy="skip_existing",
            )
            assert result["status"] == "ok"
            async with AsyncSession(engine) as session:
                document = await session.get(MemoryDocumentRow, "document-source")
                fact = await session.get(MemoryFactRow, "fact-source")
            assert document is not None and document.thread_id == "thread-source"
            assert fact is not None and fact.thread_id == "thread-source"
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_snapshot_import(database_url: str, *, case: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"snapshot_ref_{case}",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        async with AsyncSession(engine) as session:
            session.add(
                MemorySpaceRow(
                    id="space-import",
                    slug="space-import",
                    name="Import space",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                MemoryScopeRow(
                    id="scope-base",
                    space_id="space-import",
                    external_ref="base",
                    name="Base",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()

        if case == "missing_chunk":
            with pytest.raises(MemoryConflictError):
                await import_memory_scope_payload(
                    engine=engine,
                    now=NOW,
                    space_id="space-import",
                    memory_scope_id="scope-base",
                    payload=_snapshot(
                        source_document_id="document-source",
                        source_chunk_id="missing-chunk",
                    ),
                    dry_run=False,
                    merge_strategy="create_new_memory_scope",
                )
            async with AsyncSession(engine) as session:
                assert await session.scalar(select(func.count()).select_from(MemoryFactRow)) == 0
                assert (
                    await session.scalar(select(func.count()).select_from(MemoryDocumentRow)) == 0
                )
                assert await session.scalar(select(func.count()).select_from(MemoryChunkRow)) == 0
                assert await session.scalar(select(func.count()).select_from(MemoryScopeRow)) == 1
            return

        result = await import_memory_scope_payload(
            engine=engine,
            now=NOW,
            space_id="space-import",
            memory_scope_id="scope-base",
            payload=_snapshot(
                source_document_id=(
                    "external-document-ref" if case == "external_id" else "document-source"
                )
            ),
            dry_run=False,
            merge_strategy="create_new_memory_scope",
        )
        assert result["status"] == "ok", result
        target_scope_id = str(result["created_memory_scope"]["id"])
        async with AsyncSession(engine) as session:
            document = (
                await session.execute(
                    select(MemoryDocumentRow).where(
                        MemoryDocumentRow.memory_scope_id == target_scope_id
                    )
                )
            ).scalar_one()
            chunk = (
                await session.execute(
                    select(MemoryChunkRow).where(MemoryChunkRow.memory_scope_id == target_scope_id)
                )
            ).scalar_one()
            fact = (
                await session.execute(
                    select(MemoryFactRow).where(MemoryFactRow.memory_scope_id == target_scope_id)
                )
            ).scalar_one()
            ref = (
                await session.execute(
                    select(MemorySourceRefRow).where(MemorySourceRefRow.fact_id == fact.id)
                )
            ).scalar_one()
        assert document.id != "document-source"
        assert chunk.id != "chunk-source"
        expected_source_id = (
            "external-document-ref" if case == "external_id" else document.id
        )
        assert (ref.source_id, ref.chunk_id) == (expected_source_id, chunk.id)
        assert (document.thread_id, chunk.thread_id, fact.thread_id) != (
            "thread-source",
            "thread-source",
            "thread-source",
        )
        assert document.thread_id == chunk.thread_id == fact.thread_id
    finally:
        await engine.dispose()
        await database.drop()


def _snapshot(
    *,
    source_document_id: str,
    source_chunk_id: str = "chunk-source",
) -> dict[str, object]:
    timestamp = NOW.isoformat()
    return {
        "schema_version": 9,
        "redacted": False,
        "threads": [
            {
                "id": "thread-source",
                "external_ref": "thread-source",
                "status": "active",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
        "facts": [
            {
                "id": "fact-source",
                "thread_id": "thread-source",
                "text": "Imported fact with canonical evidence.",
                "status": "active",
                "version": 1,
            }
        ],
        "documents": [
            {
                "id": "document-source",
                "thread_id": "thread-source",
                "title": "Imported document",
                "status": "active",
            }
        ],
        "chunks": [
            {
                "id": "chunk-source",
                "document_id": "document-source",
                "thread_id": "thread-source",
                "text": "Canonical imported evidence.",
                "normalized_text": "canonical imported evidence.",
                "status": "active",
            }
        ],
        "source_refs": [
            {
                "fact_id": "fact-source",
                "fact_version": 1,
                "source_type": "document",
                "source_id": source_document_id,
                "chunk_id": source_chunk_id,
            }
        ],
    }
