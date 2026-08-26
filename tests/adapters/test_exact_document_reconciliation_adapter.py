from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_adapters.postgres import feature_models as _feature_models  # noqa: F401
from infinity_context_adapters.postgres.document_reconciliation import (
    PostgresExactDocumentObservationAdapter,
)
from infinity_context_adapters.postgres.locator_models import (
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileRow,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.orm import Base
from infinity_context_core.features.document_ingestion.public import (
    DocumentIngestionScope,
    ExactDocumentIdentity,
    SourceDocumentOrigin,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _identity(**changes):
    values = dict(
        scope=DocumentIngestionScope("space", "scope", "thread"),
        origin=SourceDocumentOrigin("opaque-kind", "target"),
        projection_generation="projection-1",
        profile_generation="profile-1",
    )
    values.update(changes)
    return ExactDocumentIdentity(**values)


def _document(index: int, source_external_id: str) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=f"doc-{index}",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        title=f"Document {index}",
        source_type="opaque-kind",
        source_external_id=source_external_id,
        content_hash=f"hash-{index}",
        classification="internal",
        status="active",
        retrieval_projected=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk(document_id: str) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=f"chunk-{document_id}",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id=document_id,
        episode_id=None,
        source_type="opaque-kind",
        source_external_id="target",
        source_hash=f"source-{document_id}",
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
        retrieval_locator=f"locator-{document_id}",
        retrieval_source_key="source",
        retrieval_projection_generation="projection-1",
        retrieval_sequence_ordinal=0,
        retrieval_kind="document",
        retrieval_version=3,
        retrieval_actor_keys_json=[],
        retrieval_category="document",
        retrieval_tags_json=[],
        retrieval_commit_watermark=3,
    )


def test_exact_lookup_finds_item_after_more_than_one_hundred_decoys_and_proves_indexed() -> None:
    asyncio.run(_indexed_scenario())


async def _indexed_scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all([_document(index, f"decoy-{index}") for index in range(101)])
        target = _document(999, "target")
        chunk = _chunk(target.id)
        session.add_all(
            [
                target,
                chunk,
                MemoryLocatorProfileRow(
                    profile_id="profile-id",
                    generation="profile-1",
                    profile_digest="a" * 64,
                    collection_name="collection",
                    state="active",
                    backfill_complete=True,
                    canonical_watermark=3,
                    projected_watermark=3,
                    expected_count=1,
                    projected_count=1,
                    expected_digest="b" * 64,
                    projected_digest="b" * 64,
                    created_at=NOW,
                    reconciliation_drifted=False,
                ),
                MemoryLocatorProfileProjectionReceiptRow(
                    profile_id="profile-id",
                    chunk_id=chunk.id,
                    canonical_version=3,
                    canonical_watermark=3,
                    payload_digest="c" * 64,
                    projected_at=NOW,
                ),
            ]
        )
    observations = await PostgresExactDocumentObservationAdapter(sessions).observe_exact_document(
        _identity()
    )
    assert len(observations) == 1
    assert observations[0].document_id == "doc-999"
    assert observations[0].visibility == "indexed"
    async with sessions.begin() as session:
        stored = await session.get(MemoryChunkRow, chunk.id)
        assert stored is not None
        stored.retrieval_version = 4
    stale = await PostgresExactDocumentObservationAdapter(sessions).observe_exact_document(
        _identity()
    )
    assert stale[0].visibility == "accepted"
    await engine.dispose()


def test_exact_lookup_returns_two_for_ambiguous_duplicates_and_never_weakens_scope() -> None:
    asyncio.run(_duplicate_scenario())


async def _duplicate_scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all([_document(1, "target"), _document(2, "target")])
    adapter = PostgresExactDocumentObservationAdapter(sessions)
    assert len(await adapter.observe_exact_document(_identity())) == 2
    wrong = _identity(scope=DocumentIngestionScope("space", "wrong-scope", "thread"))
    assert await adapter.observe_exact_document(wrong) == ()
    await engine.dispose()
