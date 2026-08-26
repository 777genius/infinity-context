from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.document_reconciliation import (
    PostgresExactDocumentObservationAdapter,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_core.features.document_ingestion.public import (
    DocumentIngestionScope,
    ExactDocumentIdentity,
    SourceDocumentOrigin,
    reconcile_exact_document,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

NOW = datetime(2026, 8, 26, tzinfo=UTC)
ACTIVE_OUTBOX_STATUSES = ("pending", "running", "retry_pending")
TERMINAL_OUTBOX_STATUSES = ("done", "dead")


def test_zero_chunk_reconciliation_lifecycle_and_races_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_lifecycle_and_races(database_url))


async def _assert_lifecycle_and_races(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="zero_chunk_reconciliation",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        observer = PostgresExactDocumentObservationAdapter(sessions)
        async with sessions.begin() as session:
            session.add(_document())

        assert await _state(observer) == ("present", "accepted")

        writer = sessions()
        async with writer.begin():
            writer.add(_chunk())
            await writer.flush()
            assert await _state(observer) == ("present", "accepted")
        await writer.close()

        assert await _state(observer) == ("processing", "processing")
        outbox_id = await _projection_outbox_id(sessions)

        for status in ACTIVE_OUTBOX_STATUSES:
            await _set_outbox_status(sessions, outbox_id, status)
            assert await _state(observer) == ("processing", "processing")

        for status in TERMINAL_OUTBOX_STATUSES:
            await _set_outbox_status(sessions, outbox_id, status)
            assert await _state(observer) == ("present", "accepted")

        await _set_outbox_status(sessions, outbox_id, "running")
        finisher = sessions()
        async with finisher.begin():
            row = await finisher.get(MemoryOutboxRow, outbox_id)
            assert row is not None
            row.status = "done"
            await finisher.flush()
            assert await _state(observer) == ("processing", "processing")
        await finisher.close()

        assert await _state(observer) == ("present", "accepted")
    finally:
        await engine.dispose()
        await database.drop()


async def _state(
    observer: PostgresExactDocumentObservationAdapter,
) -> tuple[str, str]:
    identity = _identity()
    observations = await observer.observe_exact_document(identity)
    result = reconcile_exact_document(identity, observations)
    return result.state, result.visibility


async def _projection_outbox_id(sessions: async_sessionmaker) -> int:
    async with sessions() as session:
        result = await session.scalar(
            select(MemoryOutboxRow.id).where(
                MemoryOutboxRow.aggregate_id == "chunk-1",
                MemoryOutboxRow.event_type == "vector.upsert_chunk",
            )
        )
    assert result is not None
    return result


async def _set_outbox_status(sessions: async_sessionmaker, outbox_id: int, status: str) -> None:
    async with sessions.begin() as session:
        row = await session.get(MemoryOutboxRow, outbox_id)
        assert row is not None
        row.status = status


def _identity() -> ExactDocumentIdentity:
    return ExactDocumentIdentity(
        scope=DocumentIngestionScope("space", "scope", "thread"),
        origin=SourceDocumentOrigin("opaque-kind", "target"),
    )


def _document() -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="doc-1",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        title="Zero chunk lifecycle",
        source_type="opaque-kind",
        source_external_id="target",
        content_hash="hash-1",
        classification="internal",
        status="active",
        retrieval_projected=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk() -> MemoryChunkRow:
    return MemoryChunkRow(
        id="chunk-1",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id="doc-1",
        episode_id=None,
        source_type="opaque-kind",
        source_external_id="target",
        source_hash="source-1",
        kind="paragraph",
        text="evidence",
        normalized_text="evidence",
        status="active",
        sequence=0,
        char_start=0,
        char_end=8,
        token_estimate=2,
        classification="internal",
        created_at=NOW,
        updated_at=NOW,
        metadata_json={},
        retrieval_locator="locator-1",
        retrieval_source_key="source",
        retrieval_projection_generation="projection-1",
        retrieval_sequence_ordinal=0,
        retrieval_kind="document",
        retrieval_version=1,
        retrieval_actor_keys_json=[],
        retrieval_category="document",
        retrieval_tags_json=[],
        retrieval_commit_watermark=1,
    )
