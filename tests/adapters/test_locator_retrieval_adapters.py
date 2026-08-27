from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as core
import pytest
from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    QdrantContextCandidateProvider,
    translate_qdrant_locator_filters,
)
from infinity_context_adapters.postgres.locator_retrieval import (
    _candidate_statement,
    _canonical_rows,
)
from infinity_context_adapters.postgres.mappers import chunk_row_to_domain
from infinity_context_adapters.postgres.retrieval_projection_mapping import (
    typed_retrieval_projection,
)
from infinity_context_adapters.qdrant.locator_profile import validate_locator_payload
from infinity_context_adapters.qdrant.vector_adapter import (
    QdrantLocatorPayloadError,
    QdrantVectorMemoryAdapter,
)
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    PortStatus,
    VectorUpsertItem,
)
from sqlalchemy.dialects import postgresql


def _request() -> core.LocatorRetrievalRequest:
    interval = core.LocatorTimeInterval(
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )
    return core.LocatorRetrievalRequest(
        "context-retrieval.v2",
        "a" * 64,
        "profile",
        core.LocatorRetrievalScope("space", "scope", "thread"),
        (core.LocatorQueryVariant("q1", "bounded query"),),
        core.LocatorHardFilters(
            source_generations=(core.LocatorSourceGeneration("source", "generation"),),
            excluded_source_keys=("excluded",),
            document_keys=("document",),
            kinds=("turn",),
            category="human",
            tags_any=("decision",),
            tags_all=("accepted",),
            tags_none=("draft",),
            actor_keys=("actor",),
            time_interval=interval,
        ),
        core.LocatorSoftPreferences(),
        core.LocatorRetrievalBounds(candidate_limit=10, result_limit=5),
    )


def test_qdrant_filter_translation_covers_every_hard_filter() -> None:
    translated = translate_qdrant_locator_filters(_request())
    keys = {item["key"] for item in translated["must"]}
    excluded = {item["key"] for item in translated["must_not"]}
    assert keys == {
        "space_id",
        "memory_scope_id",
        "lifecycle_status",
        "thread_id",
        "document_key",
        "kind",
        "category",
        "tags",
        "actor_keys",
        "start_at",
        "end_at",
    }
    assert translated["minimum_should_match"] == 1
    assert translated["should"] == [
        {
            "must": [
                {"key": "source_key", "match": "source"},
                {"key": "projection_generation", "match": "generation"},
            ]
        }
    ]
    assert excluded == {"source_key", "tags"}


def test_qdrant_filter_preserves_null_thread_scope_exactly() -> None:
    request = replace(_request(), scope=core.LocatorRetrievalScope("space", "scope"))
    translated = translate_qdrant_locator_filters(request)
    thread = next(item for item in translated["must"] if item["key"] == "thread_id")
    assert thread == {"key": "thread_id", "is_null": True}


def test_postgres_array_filters_compile_to_jsonb_containment() -> None:
    statement = str(
        _candidate_statement(_request(), "bounded query").compile(dialect=postgresql.dialect())
    )

    assert "CAST(memory_chunks.retrieval_tags_json AS JSONB) @>" in statement
    assert "CAST(memory_chunks.retrieval_actor_keys_json AS JSONB) @>" in statement
    assert "memory_chunks.retrieval_tags_json LIKE" not in statement
    assert "memory_chunks.retrieval_actor_keys_json LIKE" not in statement


def test_qdrant_provider_preserves_raw_score_rank_and_version() -> None:
    search = _Search()
    result = asyncio.run(
        QdrantContextCandidateProvider(
            search=search, embedder=_Embedder()
        ).retrieve_locator_candidates(_request())
    )
    assert result.status == "available"
    assert [
        (hit.canonical_identity, hit.canonical_version, hit.provider_rank) for hit in result.hits
    ] == [("chunk-1", 7, 1)]
    assert result.hits[0].raw_score_kind == "similarity"
    assert result.hits[0].raw_score_value == 0.75
    assert search.filter_spec == translate_qdrant_locator_filters(_request())


def test_projection_attributes_are_accepted_only_through_typed_seam() -> None:
    attributes = typed_retrieval_projection(
        {
            "_retrieval_projection_contract": {
                "schema_version": "document-retrieval-projection.v1",
                "locator": "opaque-locator",
                "source_key": "opaque-source",
                "projection_generation": "generation-2",
                "sequence_ordinal": 4,
                "actor_keys": ["actor-1"],
                "time_interval": {
                    "start_at": "2026-01-01T00:00:00Z",
                    "end_at": "2026-01-01T00:01:00Z",
                },
                "relative_time_interval": None,
                "kind": "record_block",
                "category": "accepted-human",
                "tags": ["decision"],
            }
        }
    )
    assert attributes is not None
    assert attributes["locator"] == "opaque-locator"
    assert attributes["source_key"] == "opaque-source"
    assert attributes["sequence_ordinal"] == 4
    assert typed_retrieval_projection({"retrieval": {"locator": "ignored"}}) is None


def test_qdrant_locator_read_rejects_missing_identity_or_version_without_fallback() -> None:
    adapter = _QdrantRead(
        url="http://unused",
        collection_name="locator-profile",
        vector_size=2,
        projection_version="document-retrieval-projection.v1",
        index_profile_digest="a" * 64,
        index_generation="b" * 64,
    )
    with pytest.raises(QdrantLocatorPayloadError):
        asyncio.run(
            adapter.search_locator_chunks(
                space_id="space",
                memory_scope_id="scope",
                thread_id=None,
                query_vector=(0.1, 0.2),
                query_text="query",
                limit=1,
                filter_spec={"must": [], "must_not": []},
            )
        )


def test_qdrant_locator_read_enforces_scope_outside_caller_filter_spec() -> None:
    adapter = _QdrantScopeRead(
        url="http://unused",
        collection_name="locator-profile",
        vector_size=2,
        projection_version="document-retrieval-projection.v1",
        index_profile_digest="a" * 64,
        index_generation="b" * 64,
    )
    assert (
        asyncio.run(
            adapter.search_locator_chunks(
                space_id="space",
                memory_scope_id="scope",
                thread_id="thread",
                query_vector=(0.1, 0.2),
                query_text="query",
                limit=1,
                filter_spec={"must": [], "must_not": []},
            )
        )
        == ()
    )
    coordinates = {
        (condition.kwargs["key"], condition.kwargs["match"].kwargs["value"])
        for condition in adapter.query_filter.kwargs["must"]
        if "match" in condition.kwargs
    }
    assert {
        ("space_id", "space"),
        ("memory_scope_id", "scope"),
        ("thread_id", "thread"),
    } <= coordinates


def test_qdrant_locator_write_rejects_noncanonical_payload_before_mutation() -> None:
    adapter = _QdrantWrite(
        url="http://unused",
        collection_name="locator-profile",
        vector_size=2,
        projection_version="document-retrieval-projection.v1",
        index_profile_digest="a" * 64,
        index_generation="b" * 64,
    )
    result = asyncio.run(adapter.upsert_chunks((_locator_upsert_item(),)))
    assert result.status == PortStatus.DEGRADED
    assert result.affected_count == 0
    assert result.diagnostics[0].code == "qdrant.locator_profile_invalid"
    assert result.diagnostics[0].retryable is False
    assert adapter.mutated is False


def test_qdrant_locator_write_rejects_scope_metadata_conflicting_with_envelope() -> None:
    adapter = _QdrantWrite(
        url="http://unused",
        collection_name="locator-profile",
        vector_size=2,
        projection_version="document-retrieval-projection.v1",
        index_profile_digest="a" * 64,
        index_generation="b" * 64,
    )
    item = _locator_upsert_item()
    item = replace(item, metadata={**item.metadata, "space_id": "foreign-space"})
    result = asyncio.run(adapter.upsert_chunks((item,)))
    assert result.status == PortStatus.DEGRADED
    assert result.diagnostics[0].code == "qdrant.locator_profile_invalid"
    assert result.diagnostics[0].retryable is False
    assert adapter.mutated is False


def test_qdrant_typed_payload_rejects_missing_and_extra_coordinates() -> None:
    payload = {
        "actor_keys": ["actor"],
        "canonical_identity": "chunk",
        "canonical_version": 1,
        "category": "decision",
        "chunk_key": "chunk",
        "document_key": "document",
        "end_at": None,
        "index_generation": "generation",
        "index_profile_digest": "a" * 64,
        "kind": "record",
        "lifecycle_status": "active",
        "locator": "locator",
        "memory_scope_id": "scope",
        "projection_generation": "projection",
        "projection_version": "document-retrieval-projection.v1",
        "relative_end_ms": 2,
        "relative_start_ms": 1,
        "sequence_ordinal": 3,
        "source_key": "source",
        "space_id": "space",
        "start_at": None,
        "tags": ["approved"],
        "thread_id": None,
    }
    assert (
        validate_locator_payload(
            payload,
            projection_version="document-retrieval-projection.v1",
            index_profile_digest="a" * 64,
            index_generation="generation",
        )
        == payload
    )
    for malformed in (
        {key: value for key, value in payload.items() if key != "locator"},
        {**payload, "extra": "rejected"},
    ):
        with pytest.raises(QdrantLocatorPayloadError):
            validate_locator_payload(
                malformed,
                projection_version="document-retrieval-projection.v1",
                index_profile_digest="a" * 64,
                index_generation="generation",
            )


def test_canonical_snapshot_projects_exact_persisted_retrieval_version() -> None:
    row = SimpleNamespace(
        retrieval_locator="locator",
        retrieval_source_key="source",
        retrieval_projection_generation="generation",
        retrieval_sequence_ordinal=3,
        retrieval_kind="paragraph",
        retrieval_version=7,
        retrieval_tags_json=[],
        retrieval_actor_keys_json=[],
        retrieval_start_at=None,
        retrieval_end_at=None,
        retrieval_relative_start_ms=None,
        retrieval_relative_end_ms=None,
        retrieval_category=None,
        document_id="document",
        id="chunk",
        status="active",
        classification="internal",
        space_id="space",
        memory_scope_id="scope",
        thread_id=None,
        kind="paragraph",
        sequence=0,
    )
    projected = _canonical_rows((row,), "postgres:snapshot-a")
    assert projected[0].canonical_version == 7
    assert projected[0].read_snapshot == "postgres:snapshot-a"


def test_legacy_chunk_mapping_does_not_invent_retrieval_projection() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(
        id="chunk",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id=None,
        episode_id="episode",
        source_type="document",
        source_external_id="source",
        source_hash="hash",
        kind="document_section",
        text="text",
        normalized_text="text",
        status="active",
        sequence=0,
        char_start=0,
        char_end=4,
        token_estimate=1,
        classification="unknown",
        created_at=now,
        updated_at=now,
        metadata_json={"language": "", "source": "document"},
        retrieval_locator=None,
        retrieval_source_key=None,
        retrieval_projection_generation=None,
        retrieval_sequence_ordinal=None,
        retrieval_kind=None,
        retrieval_version=1,
        retrieval_actor_keys_json=[],
        retrieval_start_at=None,
        retrieval_end_at=None,
        retrieval_relative_start_ms=None,
        retrieval_relative_end_ms=None,
        retrieval_category=None,
        retrieval_tags_json=[],
    )

    mapped = chunk_row_to_domain(row)

    assert mapped.metadata == {"language": "", "source": "document"}
    assert mapped.canonical_version == 1
    assert "_canonical_retrieval_projection" not in mapped.metadata


class _Search:
    filter_spec = None

    async def search_locator_chunks(self, **kwargs):
        self.filter_spec = kwargs["filter_spec"]
        return ({"canonical_identity": "chunk-1", "canonical_version": 7, "score": 0.75},)


class _Embedder:
    async def capabilities(self):
        return AdapterCapabilities("embedder", True, True, False, False, True, False)

    async def embed_texts(self, texts):
        return EmbeddingResult(PortStatus.OK, tuple((0.1, 0.2) for _ in texts))


class _Model:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _Models:
    FieldCondition = MatchValue = MatchAny = Filter = Range = DatetimeRange = _Model
    IsNullCondition = PayloadField = _Model
    PointStruct = _Model


class _QdrantRead(QdrantVectorMemoryAdapter):
    async def _client(self):
        return SimpleNamespace(), _Models

    async def _require_collection(self, client) -> None:
        return None

    async def _search(self, client, models, *args):
        return (SimpleNamespace(payload={"chunk_id": "legacy"}, score=0.7),)


class _QdrantScopeRead(_QdrantRead):
    query_filter = None

    async def _search(self, client, models, query_vector, query_text, query_filter, limit):
        self.query_filter = query_filter
        return ()


class _QdrantWrite(_QdrantRead):
    mutated = False

    async def _client(self):
        return self, _Models

    async def upsert(self, **kwargs):
        self.mutated = True


def _locator_upsert_item() -> VectorUpsertItem:
    return VectorUpsertItem(
        chunk_id="chunk",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        text="text",
        vector=(0.1, 0.2),
        projection_version="document-retrieval-projection.v1",
        metadata={
            "locator": "locator",
            "source_key": "source",
            "projection_generation": "generation",
            "sequence_ordinal": "1",
            "actor_keys": "actor",
            "start_at": None,
            "end_at": None,
            "relative_start_ms": "1",
            "relative_end_ms": "2",
            "kind": "record_block",
            "category": "human",
            "tags": "decision\u001faccepted",
            "canonical_identity": "chunk",
            "canonical_version": "1",
            "lifecycle_status": "active",
            "document_key": "document",
            "chunk_key": "chunk",
        },
    )
