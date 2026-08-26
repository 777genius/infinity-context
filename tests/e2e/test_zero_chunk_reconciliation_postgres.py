from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.document_reconciliation import (
    PostgresExactDocumentObservationAdapter,
)
from infinity_context_adapters.postgres.locator_models import MemoryLocatorProfileRow
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_core.features.document_ingestion.public import (
    DocumentIngestionScope,
    ExactDocumentIdentity,
    SourceDocumentOrigin,
    reconcile_exact_document,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

NOW = datetime(2026, 8, 26, tzinfo=UTC)
ACTIVE_OUTBOX_STATUSES = ("pending", "running", "retry_pending")
TERMINAL_OUTBOX_STATUSES = ("done", "dead")
PROJECTION_EVENT_TYPES = (
    "vector.upsert_chunk",
    "vector.delete_chunks",
    "vector.upsert_locator_profile",
    "vector.delete_locator_profile",
)


def test_zero_chunk_reconciliation_outbox_matrix_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_outbox_matrix(database_url))


async def _assert_outbox_matrix(database_url: str) -> None:
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
            session.add_all(
                [
                    _profile("profile-current", "profile-1", "active"),
                    _profile("profile-other", "profile-other", "retained"),
                    _document("doc-target", "target"),
                    _document("doc-other", "other"),
                ]
            )
        async with sessions.begin() as session:
            session.add_all(
                [
                    _chunk("chunk-target", "doc-target", "target", "projection-1"),
                    _chunk("chunk-old", "doc-target", "target", "projection-old"),
                    _chunk("chunk-other", "doc-other", "other", "projection-1"),
                ]
            )

        assert await _state(observer) == ("present", "accepted")

        ordinal = 0
        for event_type in PROJECTION_EVENT_TYPES:
            for status in (*ACTIVE_OUTBOX_STATUSES, *TERMINAL_OUTBOX_STATUSES):
                ordinal += 1
                await _replace_outbox(
                    sessions,
                    _outbox(
                        ordinal,
                        event_type,
                        status,
                        document_id="doc-target",
                        chunk_id="chunk-target",
                        profile_id="profile-current",
                    ),
                )
                expected = (
                    ("processing", "processing")
                    if status in ACTIVE_OUTBOX_STATUSES
                    else ("present", "accepted")
                )
                assert await _state(observer) == expected, (event_type, status)

        async with sessions.begin() as session:
            chunk = await session.get(MemoryChunkRow, "chunk-target")
            assert chunk is not None
            chunk.status = "active"

        await _replace_outbox(
            sessions,
            _outbox(
                100,
                "vector.upsert_chunk",
                "running",
                document_id="doc-other",
                chunk_id="chunk-other",
                profile_id="profile-current",
            ),
            _outbox(
                101,
                "vector.upsert_locator_profile",
                "retry_pending",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-other",
            ),
            _outbox(
                102,
                "vector.delete_locator_profile",
                "pending",
                document_id="doc-target",
                chunk_id="chunk-old",
                profile_id="profile-current",
            ),
            _outbox(
                103,
                "vector.delete_chunks",
                "dead",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-current",
            ),
        )
        exact_generation = _identity(projection_generation="projection-1")
        assert await _state(observer, exact_generation) == ("present", "accepted")

        await _replace_outbox(
            sessions,
            _outbox(
                104,
                "vector.upsert_chunk",
                "running",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-current",
            ),
            _outbox(
                105,
                "vector.upsert_chunk",
                "done",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-current",
            ),
        )
        assert await _state(observer, exact_generation) == ("processing", "processing")

        await _replace_outbox(sessions)
        assert await _state(observer, exact_generation) == ("present", "accepted")

        writer = sessions()
        async with writer.begin():
            writer.add(
                _outbox(
                    200,
                    "vector.delete_chunks",
                    "running",
                    document_id="doc-target",
                    chunk_id="chunk-target",
                    profile_id="profile-current",
                )
            )
            await writer.flush()
            assert await _state(observer, exact_generation) == ("present", "accepted")
        await writer.close()
        assert await _state(observer, exact_generation) == ("processing", "processing")

        finisher = sessions()
        async with finisher.begin():
            row = await finisher.get(MemoryOutboxRow, 200)
            assert row is not None
            row.status = "done"
            await finisher.flush()
            assert await _state(observer, exact_generation) == ("processing", "processing")
        await finisher.close()
        assert await _state(observer, exact_generation) == ("present", "accepted")
    finally:
        await engine.dispose()
        await database.drop()


async def _state(
    observer: PostgresExactDocumentObservationAdapter,
    identity: ExactDocumentIdentity | None = None,
) -> tuple[str, str]:
    exact = identity or _identity()
    observations = await observer.observe_exact_document(exact)
    result = reconcile_exact_document(exact, observations)
    return result.state, result.visibility


async def _replace_outbox(sessions: async_sessionmaker, *rows: MemoryOutboxRow) -> None:
    async with sessions.begin() as session:
        await session.execute(delete(MemoryOutboxRow))
        session.add_all(rows)


def _identity(**changes: str) -> ExactDocumentIdentity:
    values = {
        "scope": DocumentIngestionScope("space", "scope", "thread"),
        "origin": SourceDocumentOrigin("opaque-kind", "target"),
        "profile_generation": "profile-1",
    }
    values.update(changes)
    return ExactDocumentIdentity(**values)


def _profile(profile_id: str, generation: str, state: str) -> MemoryLocatorProfileRow:
    return MemoryLocatorProfileRow(
        profile_id=profile_id,
        generation=generation,
        profile_digest=("a" if state == "active" else "b") * 64,
        collection_name=f"collection-{profile_id}",
        state=state,
        backfill_complete=False,
        canonical_watermark=0,
        projected_watermark=0,
        expected_count=0,
        projected_count=0,
        expected_digest="c" * 64,
        projected_digest="c" * 64,
        created_at=NOW,
        reconciliation_drifted=True,
    )


def _document(document_id: str, source_external_id: str) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=document_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        title=f"Zero chunk {source_external_id}",
        source_type="opaque-kind",
        source_external_id=source_external_id,
        content_hash=f"hash-{document_id}",
        classification="internal",
        status="active",
        retrieval_projected=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk(
    chunk_id: str,
    document_id: str,
    source_external_id: str,
    projection_generation: str,
) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id=document_id,
        episode_id=None,
        source_type="opaque-kind",
        source_external_id=source_external_id,
        source_hash=f"source-{chunk_id}",
        kind="paragraph",
        text="evidence",
        normalized_text="evidence",
        status="deleted",
        sequence=0,
        char_start=0,
        char_end=8,
        token_estimate=2,
        classification="internal",
        created_at=NOW,
        updated_at=NOW,
        metadata_json={},
        retrieval_locator=f"locator-{chunk_id}",
        retrieval_source_key="source",
        retrieval_projection_generation=projection_generation,
        retrieval_sequence_ordinal=0,
        retrieval_kind="document",
        retrieval_version=1,
        retrieval_actor_keys_json=[],
        retrieval_category="document",
        retrieval_tags_json=[],
        retrieval_commit_watermark=1,
    )


def _outbox(
    row_id: int,
    event_type: str,
    status: str,
    *,
    document_id: str,
    chunk_id: str,
    profile_id: str,
) -> MemoryOutboxRow:
    aggregate_type = "locator_profile_chunk"
    aggregate_id = chunk_id
    aggregate_version = 1
    payload: dict[str, object] = {"chunk_id": chunk_id, "profile_id": profile_id}
    if event_type == "vector.upsert_chunk":
        aggregate_type = "chunk"
        aggregate_version = None
        payload = {"chunk_id": chunk_id}
    elif event_type == "vector.delete_chunks":
        aggregate_type = "document"
        aggregate_id = document_id
        aggregate_version = None
        payload = {"document_id": document_id, "chunk_ids": [chunk_id]}
    elif event_type == "vector.delete_locator_profile":
        payload = {"chunk_ids": [chunk_id], "profile_id": profile_id}
    return MemoryOutboxRow(
        id=row_id,
        message_key=f"zero-chunk-{row_id}",
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        workload_class="projection",
        fairness_key=f"profile:{profile_id}" if "locator_profile" in event_type else document_id,
        payload_json=payload,
        status=status,
        attempt_count=0,
        next_attempt_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
