"""Helpers for provider-neutral source reference hydration."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from memo_stack_core.application.safe_payload import safe_metadata_text
from memo_stack_core.domain.entities import MAX_SOURCE_REFS_PER_ITEM, MemoryChunk, SourceRef


def chunk_source_refs(chunk: MemoryChunk, *, text_preview: str) -> tuple[SourceRef, ...]:
    metadata_refs = _source_refs_from_metadata(chunk.metadata)
    if not metadata_refs:
        return (_fallback_chunk_source_ref(chunk, text_preview=text_preview),)
    refs: list[SourceRef] = []
    for item in metadata_refs:
        ref = _source_ref_from_metadata_item(
            item,
            chunk=chunk,
            text_preview=text_preview,
        )
        if ref is not None:
            refs.append(ref)
        if len(refs) >= MAX_SOURCE_REFS_PER_ITEM:
            break
    return tuple(refs) or (_fallback_chunk_source_ref(chunk, text_preview=text_preview),)


def _source_refs_from_metadata(metadata: Mapping[str, object]) -> list[Mapping[str, object]]:
    refs = metadata.get("source_refs")
    if not isinstance(refs, list):
        return []
    return [item for item in refs if isinstance(item, Mapping)]


def _source_ref_from_metadata_item(
    item: Mapping[str, object],
    *,
    chunk: MemoryChunk,
    text_preview: str,
) -> SourceRef | None:
    source_type = safe_metadata_text(str(item.get("source_type") or ""), limit=80).strip()
    source_id = safe_metadata_text(str(item.get("source_id") or ""), limit=160).strip()
    if not source_type or not source_id:
        return None
    return SourceRef(
        source_type=source_type,
        source_id=source_id,
        chunk_id=str(chunk.id),
        char_start=_optional_int(item.get("char_start"), default=chunk.char_start),
        char_end=_optional_int(item.get("char_end"), default=chunk.char_end),
        quote_preview=_quote_preview(item, text_preview=text_preview),
        page_number=_optional_positive_int(item.get("page_number")),
        time_start_ms=_optional_int(item.get("time_start_ms")),
        time_end_ms=_optional_int(item.get("time_end_ms")),
        bbox=_optional_bbox(item.get("bbox")),
    )


def _fallback_chunk_source_ref(chunk: MemoryChunk, *, text_preview: str) -> SourceRef:
    return SourceRef(
        source_type=chunk.source_type,
        source_id=chunk.source_external_id,
        chunk_id=str(chunk.id),
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        quote_preview=text_preview[:200],
    )


def _quote_preview(item: Mapping[str, object], *, text_preview: str) -> str:
    raw = item.get("quote_preview")
    if isinstance(raw, str) and raw.strip():
        return safe_metadata_text(raw, limit=240)
    return safe_metadata_text(text_preview[:200], limit=240)


def _optional_int(value: object, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _optional_positive_int(value: object) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed >= 1 else None


def _optional_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    items: list[float] = []
    for raw in value:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if not isfinite(number):
            return None
        items.append(number)
    return (items[0], items[1], items[2], items[3])
