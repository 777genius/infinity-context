"""Adapt legacy canonical records to feature-owned document identity policy."""

from __future__ import annotations

import json

from infinity_context_core.application.document_fragment_metadata import (
    _chunk_metadata_for_fragment,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.dto import IngestDocumentCommand, IngestDocumentResult
from infinity_context_core.application.normalize import scoped_idempotency_key
from infinity_context_core.domain.entities import LifecycleStatus, MemoryChunk, MemoryDocument
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.features.document_ingestion.public import (
    LegacyDocumentFragmentEvidence,
    document_content_digest,
    document_fragment_span_is_valid,
    legacy_document_content_digest,
    normalize_document_text,
    proves_legacy_document_source,
)


def document_idempotency_key(command, body_hash: str, managed_key: str | None, strict: bool) -> str:
    if managed_key is not None and strict:
        return managed_key
    raw_key = (
        managed_key
        or command.idempotency_key
        or (
            f"document:{command.space_id}:{command.memory_scope_id}:"
            f"{command.source_type}:{command.source_external_id}:{body_hash}"
        )
    )
    return scoped_idempotency_key(
        "ingest_document", command.memory_scope_id, command.thread_id, raw_key
    )


def validate_document_replay(
    command: IngestDocumentCommand,
    document: MemoryDocument,
    chunks: list[MemoryChunk],
    *,
    modern: bool,
    managed: bool = False,
) -> IngestDocumentResult:
    allowed_threads = (None, command.thread_id) if command.thread_id else (None,)
    if (
        document.space_id != command.space_id
        or document.memory_scope_id != command.memory_scope_id
        or document.thread_id not in allowed_threads
        or document.status != LifecycleStatus.ACTIVE
    ):
        raise MemoryConflictError("Document replay is no longer active in the requested scope")
    ordered = sorted(chunks, key=lambda chunk: (chunk.sequence, str(chunk.id)))
    if not ordered or any(
        chunk.document_id != document.id
        or chunk.episode_id is not None
        or chunk.space_id != document.space_id
        or chunk.memory_scope_id != document.memory_scope_id
        or chunk.thread_id != document.thread_id
        or chunk.source_type != document.source_type
        or chunk.source_external_id != document.source_external_id
        or chunk.classification != document.classification
        or chunk.status != LifecycleStatus.ACTIVE
        or not document_fragment_span_is_valid(
            text=chunk.text, char_start=chunk.char_start, char_end=chunk.char_end
        )
        for chunk in ordered
    ):
        raise MemoryInvariantError("Document chunk ownership is incomplete or unrelated")
    if managed:
        _validate_managed_document_projection(command, document, ordered)
    elif modern:
        if document.content_hash != document_content_digest(command.text):
            raise MemoryConflictError("Document content differs from the stored request")
        if not _modern_projection_matches(command.text, ordered):
            raise MemoryInvariantError("Document chunk projection is incomplete or divergent")
    else:
        pieces = fragment_document_text(normalize_document_text(command.text))
        evidence = tuple(
            LegacyDocumentFragmentEvidence(
                chunk.text, chunk.sequence, chunk.char_start, chunk.char_end
            )
            for chunk in ordered
        )
        if not proves_legacy_document_source(
            text=command.text, persisted_hash=document.content_hash, fragments=evidence
        ) or not (
            len(pieces) == 1
            and ordered[0].kind == pieces[0].kind
            and pieces[0].char_start == 0
            and pieces[0].char_end == len(normalize_document_text(command.text))
        ):
            raise MemoryConflictError("Legacy document source cannot be verified exactly")
    return IngestDocumentResult(
        document=document,
        chunks=tuple(ordered),
        duplicate_chunks=len(ordered),
        indexing_status="already_indexed_or_pending",
    )


def _validate_managed_document_projection(
    command: IngestDocumentCommand,
    document: MemoryDocument,
    chunks: list[MemoryChunk],
) -> None:
    # The caller has freshly admitted this exact managed operation. Its digest
    # stays v1, but its complete authenticated projection is available for proof.
    if (
        document.content_hash != legacy_document_content_digest(command.text)
        or document.thread_id != command.thread_id
        or document.title != command.title.strip()
        or document.source_type != command.source_type.strip()
        or document.source_external_id != command.source_external_id.strip()
        or document.classification != command.classification
    ):
        raise MemoryConflictError("Managed document identity differs from the admitted request")
    pieces = fragment_document_text(command.text)
    if len(chunks) != len(pieces) or any(
        type(chunk.sequence) is not int
        or chunk.sequence != piece.sequence
        or chunk.kind != piece.kind
        or chunk.text != piece.text.strip()
        or chunk.char_start != piece.char_start
        or chunk.char_end != piece.char_end
        or not _managed_fragment_metadata_matches(command, document, chunk, piece)
        for chunk, piece in zip(chunks, pieces, strict=False)
    ):
        raise MemoryConflictError("Managed document chunk projection is incomplete or divergent")


def _managed_fragment_metadata_matches(command, document, chunk, piece) -> bool:
    expected = {
        **_chunk_metadata_for_fragment(
            command.chunk_metadata, char_start=piece.char_start, char_end=piece.char_end
        ),
        "title": document.title,
        "node_kind": piece.node_kind,
        "heading": piece.heading,
        "ordinal_in_heading": piece.ordinal_in_heading,
    }
    owned = (
        "source_refs",
        "source_ref_count",
        "title",
        "node_kind",
        "heading",
        "ordinal_in_heading",
    )
    actual = {key: chunk.metadata[key] for key in owned if key in chunk.metadata}
    expected = {key: expected[key] for key in owned if key in expected}
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
            expected, sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError):
        return False


def _modern_projection_matches(text: str, chunks: list[MemoryChunk]) -> bool:
    # Keep original chunk/source-ref offsets at write time. Equivalent line
    # endings can produce different long-chunk boundaries, so validate against
    # the bounded original/LF/CRLF/CR plans for this already verified v2 body.
    canonical = normalize_document_text(text)
    layouts = dict.fromkeys(
        (text, canonical, canonical.replace("\n", "\r\n"), canonical.replace("\n", "\r"))
    )
    for layout in layouts:
        pieces = fragment_document_text(layout)
        if len(pieces) == len(chunks) and all(
            chunk.sequence == piece.sequence
            and chunk.kind == piece.kind
            and normalize_document_text(chunk.text) == normalize_document_text(piece.text)
            for chunk, piece in zip(chunks, pieces, strict=False)
        ):
            return True
    return False


async def replay_document_receipt(
    uow, command, record: IdempotencyRecord, *, modern_hash: str, managed: bool = False
):
    legacy_hash = legacy_document_content_digest(command.text)
    fingerprints = (legacy_hash,) if managed else (modern_hash, legacy_hash)
    if record.fingerprint not in fingerprints:
        raise MemoryConflictError("Idempotency key was used with different document")
    if record.result_type != "document":
        raise MemoryInvariantError("Idempotency result has unexpected type for document")
    document = await uow.documents.get_by_id(record.result_id)
    if document is None:
        raise MemoryInvariantError("Idempotency result points to missing document")
    return validate_document_replay(
        command,
        document,
        await uow.documents.list_chunks(str(document.id)),
        modern=document.content_hash == modern_hash,
        managed=managed,
    )


async def find_document_duplicate(uow, command, *, body_hash: str, managed: bool):
    legacy_hash = legacy_document_content_digest(command.text)
    for candidate_hash in dict.fromkeys((body_hash, legacy_hash)):
        document = await uow.documents.find_active_by_content_hash(
            space_id=str(command.space_id),
            memory_scope_id=str(command.memory_scope_id),
            thread_id=str(command.thread_id) if command.thread_id else None,
            content_hash=candidate_hash,
        )
        if document is None:
            continue
        try:
            return validate_document_replay(
                command,
                document,
                await uow.documents.list_chunks(str(document.id)),
                modern=not managed and document.content_hash == body_hash,
                managed=managed,
            )
        except MemoryConflictError:
            if managed or candidate_hash == body_hash:
                raise
            # Different or unprovable legacy content is not a v2 duplicate.
    return None
