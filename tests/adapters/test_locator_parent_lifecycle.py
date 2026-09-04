from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import infinity_context_core.features.context_building.public as core
from infinity_context_adapters.postgres import feature_models as _feature_models  # noqa: F401
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresCanonicalProjectionSource,
)
from infinity_context_adapters.postgres.locator_retrieval import (
    PostgresCanonicalLocatorReader,
    PostgresLocatorCandidateProvider,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.orm import Base
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

NOW = datetime(2026, 9, 4, tzinfo=UTC)


def test_parent_lifecycle_and_binding_are_canonical_for_every_locator_read() -> None:
    asyncio.run(_assert_parent_authority())


async def _assert_parent_authority() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cases = (
        ("eligible", {}, {}),
        ("deleted-parent", {"status": "deleted"}, {}),
        ("superseded-parent", {"status": "superseded"}, {}),
        ("restricted-parent", {"classification": "restricted"}, {"classification": "restricted"}),
        ("profile-mismatch", {"retrieval_projected": False}, {}),
        ("classification-divergence", {"classification": "public"}, {}),
        ("space-divergence", {"space_id": "other-space"}, {}),
        ("scope-divergence", {"memory_scope_id": "other-scope"}, {}),
        ("thread-divergence", {"thread_id": "other-thread"}, {}),
        ("source-type-divergence", {"source_type": "other-type"}, {}),
        ("source-divergence", {"source_external_id": "other-source"}, {}),
        ("missing-parent", None, {}),
    )
    async with sessions.begin() as session:
        for ordinal, (name, parent_changes, chunk_changes) in enumerate(cases):
            if parent_changes is not None:
                session.add(_document(name, **parent_changes))
            session.add(_chunk(name, ordinal, **chunk_changes))

    request = _request()
    provider = PostgresLocatorCandidateProvider(sessions)
    result = await provider.retrieve_locator_candidates(request)
    assert [hit.canonical_identity for hit in result.hits] == ["chunk-eligible"]

    identities = tuple(f"chunk-{name}" for name, _, _ in cases)
    reader = PostgresCanonicalLocatorReader(sessions)
    hydrated = await reader.hydrate_locator_candidates(request, identities)
    assert [item.canonical_identity for item in hydrated] == ["chunk-eligible"]

    page = await PostgresCanonicalProjectionSource(sessions).page_eligible(after=None, limit=100)
    assert [item.canonical_identity for item in page.items] == ["chunk-eligible"]
    await engine.dispose()


def _request() -> core.LocatorRetrievalRequest:
    return core.LocatorRetrievalRequest(
        "context-retrieval.v2",
        "a" * 64,
        "profile",
        core.LocatorRetrievalScope("space", "scope", "thread"),
        (core.LocatorQueryVariant("q1", "evidence"),),
        core.LocatorHardFilters(
            source_generations=(core.LocatorSourceGeneration("source", "generation"),)
        ),
        core.LocatorSoftPreferences(),
        core.LocatorRetrievalBounds(candidate_limit=100, result_limit=50),
    )


def _document(name: str, **changes: object) -> MemoryDocumentRow:
    values: dict[str, object] = {
        "id": f"doc-{name}",
        "space_id": "space",
        "memory_scope_id": "scope",
        "thread_id": "thread",
        "title": name,
        "source_type": "test",
        "source_external_id": name,
        "content_hash": f"hash-{name}",
        "classification": "internal",
        "status": "active",
        "retrieval_projected": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return MemoryDocumentRow(**values)


def _chunk(name: str, ordinal: int, **changes: object) -> MemoryChunkRow:
    values: dict[str, object] = {
        "id": f"chunk-{name}",
        "space_id": "space",
        "memory_scope_id": "scope",
        "thread_id": "thread",
        "document_id": f"doc-{name}",
        "episode_id": None,
        "source_type": "test",
        "source_external_id": name,
        "source_hash": f"source-hash-{name}",
        "kind": "paragraph",
        "text": "evidence",
        "normalized_text": "evidence",
        "status": "active",
        "sequence": 0,
        "char_start": 0,
        "char_end": 8,
        "token_estimate": 2,
        "classification": "internal",
        "created_at": NOW,
        "updated_at": NOW,
        "metadata_json": {},
        "retrieval_locator": f"locator-{name}",
        "retrieval_source_key": "source",
        "retrieval_projection_generation": "generation",
        "retrieval_sequence_ordinal": ordinal,
        "retrieval_kind": "document",
        "retrieval_version": 1,
        "retrieval_actor_keys_json": [],
        "retrieval_category": "document",
        "retrieval_tags_json": [],
        "retrieval_commit_watermark": ordinal + 1,
        "retrieval_parent_version": 1,
    }
    values.update(changes)
    return MemoryChunkRow(**values)
