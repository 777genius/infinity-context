from datetime import UTC, datetime

import pytest
from memo_stack_core.application.source_refs import chunk_source_refs
from memo_stack_core.domain.entities import (
    LifecycleStatus,
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SourceRef,
    SpaceId,
    ThreadId,
)
from memo_stack_core.domain.errors import MemoryValidationError

NOW = datetime(2026, 6, 18, tzinfo=UTC)


def test_source_ref_accepts_multimodal_coordinates() -> None:
    ref = SourceRef(
        source_type="asset_extraction",
        source_id="extract-1",
        chunk_id="chunk-1",
        page_number=2,
        time_start_ms=1000,
        time_end_ms=2500,
        bbox=(0.0, 1.0, 120.0, 80.0),
    )

    assert ref.page_number == 2
    assert ref.time_start_ms == 1000
    assert ref.time_end_ms == 2500
    assert ref.bbox == (0.0, 1.0, 120.0, 80.0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"page_number": 0}, "page_number must be positive"),
        ({"time_start_ms": -1}, "time_start_ms must be non-negative"),
        (
            {"time_start_ms": 5000, "time_end_ms": 1000},
            "time_end_ms must be >= time_start_ms",
        ),
        ({"bbox": (0.0, 1.0, float("nan"), 2.0)}, "bbox must contain four finite numbers"),
    ),
)
def test_source_ref_rejects_invalid_multimodal_coordinates(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(MemoryValidationError, match=message):
        SourceRef(source_type="asset_extraction", source_id="extract-1", **kwargs)


def test_chunk_source_refs_hydrate_structured_metadata_refs() -> None:
    chunk = _chunk(
        metadata={
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "source_id": "extract-1",
                    "char_start": 20,
                    "char_end": 60,
                    "quote_preview": "Atlas screenshot text",
                    "page_number": 3,
                    "time_start_ms": 1200,
                    "time_end_ms": 3400,
                    "bbox": [1, 2, 3, 4],
                    "raw_private_payload": {"ignored": True},
                }
            ]
        }
    )

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert refs == (
        SourceRef(
            source_type="asset_extraction",
            source_id="extract-1",
            chunk_id="chunk-1",
            char_start=20,
            char_end=60,
            quote_preview="Atlas screenshot text",
            page_number=3,
            time_start_ms=1200,
            time_end_ms=3400,
            bbox=(1.0, 2.0, 3.0, 4.0),
        ),
    )


def test_chunk_source_refs_fall_back_for_legacy_chunk_metadata() -> None:
    chunk = _chunk(metadata={})

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert refs == (
        SourceRef(
            source_type="document",
            source_id="doc-external",
            chunk_id="chunk-1",
            char_start=10,
            char_end=80,
            quote_preview=chunk.text[:200],
        ),
    )


def _chunk(*, metadata: dict[str, object]) -> MemoryChunk:
    return MemoryChunk(
        id=MemoryChunkId("chunk-1"),
        space_id=SpaceId("space-1"),
        memory_scope_id=MemoryScopeId("scope-1"),
        thread_id=ThreadId("thread-1"),
        document_id=MemoryDocumentId("doc-1"),
        episode_id=None,
        source_type="document",
        source_external_id="doc-external",
        source_hash="hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text="Atlas screenshot text for context.",
        normalized_text="atlas screenshot text for context.",
        status=LifecycleStatus.ACTIVE,
        sequence=1,
        char_start=10,
        char_end=80,
        token_estimate=8,
        classification="internal",
        metadata=metadata,
        created_at=NOW,
        updated_at=NOW,
    )
