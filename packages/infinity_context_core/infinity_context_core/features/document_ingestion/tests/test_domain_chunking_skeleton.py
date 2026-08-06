"""Feature-local checks for document_ingestion chunking policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from infinity_context_core.features.document_ingestion import public


def test_chunking_policy_creates_stable_ordered_chunk_drafts() -> None:
    text = (
        "First paragraph has enough words to make the first chunk useful. "
        "It also has a sentence boundary. "
        "\n\n"
        "Second paragraph continues the same document with more material. "
        "It should appear in another chunk with overlap."
    )
    policy = public.ChunkingPolicy(
        target_chars=95,
        overlap_chars=18,
        min_chars=35,
        boundary_scan_chars=60,
    )

    chunks = policy.plan_chunks(text)

    assert len(chunks) >= 2
    assert tuple(chunk.sequence for chunk in chunks) == tuple(range(len(chunks)))
    assert all(chunk.text for chunk in chunks)
    assert all(chunk.token_estimate > 0 for chunk in chunks)
    assert all(chunk.content_hash == public.content_hash_for_text(chunk.text) for chunk in chunks)
    assert chunks[0].text_range.char_start == 0
    assert chunks[1].text_range.char_start < chunks[0].text_range.char_end
    assert chunks[-1].text_range.char_end == len(public.normalize_document_text(text))
    _assert_frozen(chunks[0])


def test_document_chunk_snapshot_is_created_from_chunk_draft() -> None:
    scope = public.DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    draft = public.ChunkingPolicy(target_chars=200).plan_chunks("Short document text.")[0]

    chunk = public.DocumentChunk.from_draft(
        chunk_id="chunk-1",
        document_id="doc-1",
        scope=scope,
        draft=draft,
    )

    assert chunk.identity.chunk_id == "chunk-1"
    assert chunk.identity.document_id == "doc-1"
    assert chunk.identity.scope is scope
    assert chunk.sequence == draft.sequence
    assert chunk.text == draft.text
    assert chunk.content_hash == draft.content_hash
    assert chunk.source_hash == public.content_hash_for_text("doc-1:0:Short document text.")
    assert chunk.status == "active"
    _assert_frozen(chunk)


def test_chunking_policy_rejects_invalid_window_options() -> None:
    with pytest.raises(public.DocumentIngestionValidationError):
        public.ChunkingPolicy(target_chars=0)

    with pytest.raises(public.DocumentIngestionValidationError):
        public.ChunkingPolicy(target_chars=100, overlap_chars=100)

    with pytest.raises(public.DocumentIngestionValidationError):
        public.ChunkingPolicy(target_chars=100, min_chars=101)


def _assert_frozen(value: object) -> None:
    field_name = fields(value)[0].name
    try:
        setattr(value, field_name, None)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - clearer assertion failure only.
        raise AssertionError(f"{type(value).__name__} should be immutable")
