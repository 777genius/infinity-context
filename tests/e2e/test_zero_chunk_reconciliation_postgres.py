from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import infinity_context_adapters.postgres.document_reconciliation as reconciliation_adapter
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
from sqlalchemy import delete, select, text, update
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


def test_reconciliation_snapshot_is_atomic_across_commit_when_postgres_is_configured(
    monkeypatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_atomic_snapshot(database_url, monkeypatch))


def test_active_reconciliation_binding_index_is_bounded_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_indexed_lookup(database_url))


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
        exact_generation = _identity(projection_generation="projection-1")
        async with sessions.begin() as session:
            session.add_all(
                [
                    _profile("profile-current", "profile-1", "active"),
                    _document("doc-target", "target"),
                    _document("doc-other", "other"),
                ]
            )
        async with sessions.begin() as session:
            target = _chunk("chunk-target", "doc-target", "target", "projection-1")
            target.status = "active"
            session.add(target)

        # The real 0039/0051 trigger producers emit both current-version upserts.
        upserts = await _trigger_rows(sessions, "chunk-target", version=1)
        assert _shape(upserts["vector.upsert_chunk"]) == (
            "locator_chunk",
            "chunk-target",
            1,
            {"chunk_id": "chunk-target"},
        )
        assert _shape(upserts["vector.upsert_locator_profile"]) == (
            "locator_profile_chunk",
            "chunk-target",
            1,
            {"chunk_id": "chunk-target", "profile_id": "profile-current"},
        )
        for event_type in ("vector.upsert_chunk", "vector.upsert_locator_profile"):
            for status in (*ACTIVE_OUTBOX_STATUSES, *TERMINAL_OUTBOX_STATUSES):
                await _select_only_status(sessions, upserts[event_type].id, status)
                expected = (
                    ("processing", "processing")
                    if status in ACTIVE_OUTBOX_STATUSES
                    else ("present", "accepted")
                )
                assert await _state(observer, exact_generation) == expected, (event_type, status)

        async with sessions.begin() as session:
            chunk = await session.get(MemoryChunkRow, "chunk-target")
            assert chunk is not None
            chunk.status = "deleted"

        # The same real trigger chain emits the reviewed locator_chunk delete shape
        # and the profile-specific delete at the new current version.
        deletes = await _trigger_rows(sessions, "chunk-target", version=2)
        assert _shape(deletes["vector.delete_chunks"]) == (
            "locator_chunk",
            "chunk-target",
            2,
            {"chunk_ids": ["chunk-target"]},
        )
        assert _shape(deletes["vector.delete_locator_profile"]) == (
            "locator_profile_chunk",
            "chunk-target",
            2,
            {"chunk_ids": ["chunk-target"], "profile_id": "profile-current"},
        )
        for event_type in ("vector.delete_chunks", "vector.delete_locator_profile"):
            for status in (*ACTIVE_OUTBOX_STATUSES, *TERMINAL_OUTBOX_STATUSES):
                await _select_only_status(sessions, deletes[event_type].id, status)
                expected = (
                    ("processing", "processing")
                    if status in ACTIVE_OUTBOX_STATUSES
                    else ("present", "accepted")
                )
                assert await _state(observer, exact_generation) == expected, (event_type, status)

        # A stale migration version never blocks, while the application runtime's
        # deliberately unversioned chunk upsert remains independently recognized.
        await _select_only_status(sessions, upserts["vector.upsert_chunk"].id, "pending")
        assert await _state(observer, exact_generation) == ("present", "accepted")
        await _replace_outbox(
            sessions,
            _outbox(
                100,
                "vector.upsert_chunk",
                "running",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-current",
            ),
        )
        assert await _state(observer, exact_generation) == ("processing", "processing")

        # Wrong document, profile and projection generation work is excluded.
        await _replace_outbox(
            sessions,
            _outbox(
                101,
                "vector.upsert_locator_profile",
                "pending",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-other",
            ),
        )
        assert await _state(observer, exact_generation) == ("present", "accepted")
        async with sessions.begin() as session:
            session.add(_chunk("chunk-other", "doc-other", "other", "projection-other"))
        other = await _trigger_rows(sessions, "chunk-other", version=1)
        await _select_only_status(sessions, other["vector.delete_chunks"].id, "running")
        assert await _state(observer, exact_generation) == ("present", "accepted")

        # Preserve the application document-level delete binding at zero active chunks.
        await _replace_outbox(
            sessions,
            _outbox(
                102,
                "vector.delete_chunks",
                "retry_pending",
                document_id="doc-target",
                chunk_id="chunk-target",
                profile_id="profile-current",
            ),
        )
        assert await _state(observer, exact_generation) == ("processing", "processing")
        await _replace_outbox(sessions)
        assert await _state(observer, exact_generation) == ("present", "accepted")

        async with sessions() as session:
            isolation = await session.scalar(text("SHOW transaction_isolation"))
            read_only = await session.scalar(text("SHOW transaction_read_only"))
        assert isolation == "read committed"
        assert read_only == "off"
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_atomic_snapshot(database_url: str, monkeypatch) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="reconciliation_atomic_snapshot",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add_all(
                [
                    _profile("profile-current", "profile-1", "active"),
                    _document("doc-target", "target"),
                ]
            )
        async with sessions.begin() as session:
            chunk = _chunk("chunk-target", "doc-target", "target", "projection-1")
            chunk.status = "active"
            session.add(chunk)
        upserts = await _trigger_rows(sessions, "chunk-target", version=1)
        target_id = upserts["vector.upsert_chunk"].id
        await _select_only_status(sessions, target_id, "done")

        reached_after_chunk_read = asyncio.Event()
        writer_committed = asyncio.Event()
        original_profile = reconciliation_adapter._profile

        async def coordinated_profile(session, requested_generation):
            reached_after_chunk_read.set()
            await writer_committed.wait()
            return await original_profile(session, requested_generation)

        monkeypatch.setattr(reconciliation_adapter, "_profile", coordinated_profile)
        observer = PostgresExactDocumentObservationAdapter(sessions)
        observing = asyncio.create_task(
            _state(observer, _identity(projection_generation="projection-1"))
        )
        await reached_after_chunk_read.wait()
        async with sessions.begin() as writer:
            await writer.execute(
                update(MemoryOutboxRow)
                .where(MemoryOutboxRow.id == target_id)
                .values(status="pending")
            )
        writer_committed.set()

        # The overlapping observer returns the complete pre-commit snapshot. A
        # fresh observer returns the complete post-commit snapshot.
        assert await observing == ("present", "accepted")
        assert await _state(observer, _identity(projection_generation="projection-1")) == (
            "processing",
            "processing",
        )
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_indexed_lookup(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="reconciliation_binding_index",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_outbox (
                        message_key, event_type, aggregate_type, aggregate_id,
                        aggregate_version, workload_class, fairness_key, payload_json,
                        status, attempt_count, next_attempt_at, created_at, updated_at
                    )
                    SELECT
                        'reconciliation-decoy-' || ordinal,
                        'vector.upsert_chunk', 'locator_chunk', 'decoy-' || ordinal,
                        1, 'projection', 'chunk:decoy-' || ordinal,
                        jsonb_build_object('chunk_id', 'decoy-' || ordinal),
                        CASE ordinal % 3
                            WHEN 0 THEN 'pending'
                            WHEN 1 THEN 'running'
                            ELSE 'retry_pending'
                        END,
                        0, now(), now(), now()
                    FROM generate_series(1, 20000) AS ordinal
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_outbox (
                        message_key, event_type, aggregate_type, aggregate_id,
                        aggregate_version, workload_class, fairness_key, payload_json,
                        status, attempt_count, next_attempt_at, created_at, updated_at
                    ) VALUES (
                        'reconciliation-target', 'vector.delete_chunks', 'locator_chunk',
                        'chunk-target', 7, 'projection', 'chunk:chunk-target',
                        '{"chunk_ids":["chunk-target"]}'::jsonb,
                        'retry_pending', 0, now(), now(), now()
                    )
                    """
                )
            )
            await connection.execute(text("ANALYZE memory_outbox"))
            explained = await connection.scalar(
                text(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT id FROM memory_outbox
                    WHERE status IN ('pending', 'running', 'retry_pending')
                      AND aggregate_id = 'chunk-target'
                      AND event_type = 'vector.delete_chunks'
                      AND aggregate_type = 'locator_chunk'
                      AND aggregate_version = 7
                    LIMIT 1
                    """
                )
            )
        plan = explained[0]["Plan"]
        nodes = tuple(_plan_nodes(plan))
        assert "Seq Scan" not in {node["Node Type"] for node in nodes}
        assert "ix_memory_outbox_active_reconciliation_binding" in {
            node.get("Index Name") for node in nodes
        }
        assert sum(node.get("Actual Rows", 0) * node.get("Actual Loops", 1) for node in nodes) <= 4
    finally:
        await engine.dispose()
        await database.drop()


def _plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", ()):
        yield from _plan_nodes(child)


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


async def _trigger_rows(sessions, chunk_id: str, *, version: int) -> dict[str, MemoryOutboxRow]:
    async with sessions() as session:
        rows = list(
            (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.aggregate_id == chunk_id,
                        MemoryOutboxRow.aggregate_version == version,
                    )
                )
            ).scalars()
        )
    return {row.event_type: row for row in rows}


def _shape(row: MemoryOutboxRow) -> tuple[object, ...]:
    return row.aggregate_type, row.aggregate_id, row.aggregate_version, row.payload_json


async def _select_only_status(sessions, row_id: int, status: str) -> None:
    async with sessions.begin() as session:
        await session.execute(update(MemoryOutboxRow).values(status="done"))
        await session.execute(
            update(MemoryOutboxRow).where(MemoryOutboxRow.id == row_id).values(status=status)
        )


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
