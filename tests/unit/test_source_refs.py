from datetime import UTC, datetime

import pytest
from infinity_context_core.application.source_refs import chunk_source_refs
from infinity_context_core.domain.entities import (
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
from infinity_context_core.domain.errors import MemoryValidationError

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
        (
            {"bbox": (-1.0, 1.0, 120.0, 80.0)},
            "bbox must be non-negative x1,y1,x2,y2",
        ),
        (
            {"bbox": (10.0, 20.0, 9.0, 80.0)},
            "bbox must be non-negative x1,y1,x2,y2",
        ),
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


def test_chunk_source_refs_sanitize_invalid_structured_metadata_coordinates() -> None:
    chunk = _chunk(
        metadata={
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "source_id": "extract-1",
                    "char_start": 90,
                    "char_end": 20,
                    "quote_preview": "Atlas screenshot text",
                    "page_number": 0,
                    "time_start_ms": 3400,
                    "time_end_ms": 1200,
                    "bbox": [-1, 2, 3, 4],
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
            quote_preview="Atlas screenshot text",
        ),
    )


def test_chunk_source_refs_skip_invalid_structured_metadata_ref() -> None:
    chunk = _chunk(
        metadata={
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "source_id": "extract-1",
                    "char_start": 20,
                    "char_end": 60,
                    "time_start_ms": 1200,
                    "time_end_ms": 3400,
                    "bbox": [1, 2, 3, 4],
                },
                {
                    "source_type": "",
                    "source_id": "missing-source-type",
                    "quote_preview": "bad provider payload",
                },
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
            quote_preview=chunk.text[:200],
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


def test_chunk_source_refs_add_dialogue_turn_refs_for_visible_session_markers() -> None:
    chunk = _chunk(
        metadata={},
        source_type="locomo_observation",
        source_external_id="locomo:conv-26:session_7:observation",
        text=(
            "D7:2 Melanie supports Caroline. "
            "D7:4 Melanie praises Caroline's drive to help. "
            "D8:1 Different session marker should not be linked."
        ),
    )

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert [ref.source_id for ref in refs] == [
        "locomo:conv-26:session_7:observation",
        "locomo:conv-26:session_7:D7:2:turn",
        "locomo:conv-26:session_7:D7:4:turn",
    ]
    assert refs[1].source_type == "locomo_observation"
    assert refs[2].quote_preview is not None
    assert refs[2].quote_preview.startswith("D7:4 Melanie praises")


def test_chunk_source_refs_canonicalize_hyphenated_dialogue_turn_markers() -> None:
    chunk = _chunk(
        metadata={},
        source_type="locomo_observation",
        source_external_id="locomo:conv-26:session_7:observation",
        text=(
            "D7-2 Melanie supports Caroline. "
            "D7-4 Melanie praises Caroline's drive to help. "
            "D8-1 Different session marker should not be linked."
        ),
    )

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert [ref.source_id for ref in refs] == [
        "locomo:conv-26:session_7:observation",
        "locomo:conv-26:session_7:D7:2:turn",
        "locomo:conv-26:session_7:D7:4:turn",
    ]
    assert refs[1].quote_preview == "D7-2 Melanie supports Caroline."


def test_chunk_source_refs_do_not_infer_dialogue_refs_over_structured_metadata() -> None:
    chunk = _chunk(
        metadata={
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "source_id": "extract-1",
                    "quote_preview": "D7:4 OCR text",
                }
            ]
        },
        source_external_id="locomo:conv-26:session_7:observation",
        text="D7:4 Melanie praises Caroline's drive.",
    )

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert refs == (
        SourceRef(
            source_type="asset_extraction",
            source_id="extract-1",
            chunk_id="chunk-1",
            char_start=10,
            char_end=80,
            quote_preview="D7:4 OCR text",
        ),
    )


def test_chunk_source_refs_add_dialogue_refs_for_same_group_structured_metadata() -> None:
    chunk = _chunk(
        metadata={
            "source_refs": [
                {
                    "source_type": "locomo_observation",
                    "source_id": "locomo:conv-26:session_6:observation",
                    "quote_preview": "session_6 observation",
                }
            ]
        },
        source_type="locomo_observation",
        source_external_id="locomo:conv-26:session_6:observation",
        text=(
            "D6:4 Melanie took the kids to the museum. "
            "D6:6 Melanie said they liked the dinosaur exhibit. "
            "D7:1 Different session marker should not be linked."
        ),
    )

    refs = chunk_source_refs(chunk, text_preview=chunk.text)

    assert [ref.source_id for ref in refs] == [
        "locomo:conv-26:session_6:observation",
        "locomo:conv-26:session_6:D6:4:turn",
        "locomo:conv-26:session_6:D6:6:turn",
    ]
    assert refs[0].quote_preview == "session_6 observation"
    assert refs[1].source_type == "locomo_observation"
    assert refs[1].quote_preview == "D6:4 Melanie took the kids to the museum."


def _chunk(
    *,
    metadata: dict[str, object],
    source_type: str = "document",
    source_external_id: str = "doc-external",
    text: str = "Atlas screenshot text for context.",
) -> MemoryChunk:
    return MemoryChunk(
        id=MemoryChunkId("chunk-1"),
        space_id=SpaceId("space-1"),
        memory_scope_id=MemoryScopeId("scope-1"),
        thread_id=ThreadId("thread-1"),
        document_id=MemoryDocumentId("doc-1"),
        episode_id=None,
        source_type=source_type,
        source_external_id=source_external_id,
        source_hash="hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
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
