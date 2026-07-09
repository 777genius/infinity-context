"""Helpers for provider-neutral source reference hydration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from math import isfinite

from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import MAX_SOURCE_REFS_PER_ITEM, MemoryChunk, SourceRef
from infinity_context_core.domain.errors import MemoryValidationError

_DIALOGUE_MARKER_RE = re.compile(r"\bD(?P<dialogue>\d+)[:-](?P<turn>\d+)\b")
_SESSION_ID_RE = re.compile(r"(?:^|:)session_(?P<session>\d+)(?::|$)", re.IGNORECASE)
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})


def chunk_source_refs(chunk: MemoryChunk, *, text_preview: str) -> tuple[SourceRef, ...]:
    metadata_refs = _source_refs_from_metadata(chunk.metadata)
    if not metadata_refs:
        fallback = _fallback_chunk_source_ref(chunk, text_preview=text_preview)
        return (fallback, *_dialogue_turn_source_refs(chunk, text_preview=text_preview))
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
    if refs:
        refs.extend(
            _dialogue_turn_source_refs_for_structured_metadata(
                chunk,
                source_refs=tuple(refs),
                text_preview=text_preview,
            )
        )
    return tuple(refs[:MAX_SOURCE_REFS_PER_ITEM]) or (
        _fallback_chunk_source_ref(chunk, text_preview=text_preview),
    )


def source_ref_location_summary(source_refs: tuple[SourceRef, ...]) -> dict[str, object]:
    return {
        "source_refs_with_page_count": sum(1 for ref in source_refs if ref.page_number is not None),
        "source_refs_with_bbox_count": sum(1 for ref in source_refs if ref.bbox is not None),
        "source_refs_with_time_range_count": sum(
            1
            for ref in source_refs
            if ref.time_start_ms is not None or ref.time_end_ms is not None
        ),
    }


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
    char_start, char_end = _metadata_char_range(item, chunk=chunk)
    time_start_ms, time_end_ms = _metadata_time_range(item)
    try:
        return SourceRef(
            source_type=source_type,
            source_id=source_id,
            chunk_id=str(chunk.id),
            char_start=char_start,
            char_end=char_end,
            quote_preview=_quote_preview(item, text_preview=text_preview),
            page_number=_optional_positive_int(item.get("page_number")),
            time_start_ms=time_start_ms,
            time_end_ms=time_end_ms,
            bbox=_optional_bbox(item.get("bbox")),
        )
    except MemoryValidationError:
        return None


def _fallback_chunk_source_ref(chunk: MemoryChunk, *, text_preview: str) -> SourceRef:
    return SourceRef(
        source_type=chunk.source_type,
        source_id=chunk.source_external_id,
        chunk_id=str(chunk.id),
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        quote_preview=text_preview[:200],
    )


def _dialogue_turn_source_refs(
    chunk: MemoryChunk,
    *,
    text_preview: str,
) -> tuple[SourceRef, ...]:
    base_source_id = _dialogue_turn_base_source_id(chunk.source_external_id)
    if not base_source_id:
        return ()
    session_number = _session_number(base_source_id)
    refs: list[SourceRef] = []
    seen: set[str] = {chunk.source_external_id}
    matches = tuple(_DIALOGUE_MARKER_RE.finditer(text_preview))
    for index, match in enumerate(matches):
        if session_number and match.group("dialogue") != session_number:
            continue
        source_id = f"{base_source_id}:D{match.group('dialogue')}:{match.group('turn')}:turn"
        if source_id in seen:
            continue
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text_preview)
        quote_preview = safe_metadata_text(
            text_preview[match.start() : segment_end].strip()[:240],
            limit=240,
        )
        try:
            refs.append(
                SourceRef(
                    source_type=chunk.source_type,
                    source_id=source_id,
                    chunk_id=str(chunk.id),
                    quote_preview=quote_preview or text_preview[:200],
                )
            )
        except MemoryValidationError:
            continue
        seen.add(source_id)
        if len(refs) >= MAX_SOURCE_REFS_PER_ITEM - 1:
            break
    return tuple(refs)


def _dialogue_turn_source_refs_for_structured_metadata(
    chunk: MemoryChunk,
    *,
    source_refs: tuple[SourceRef, ...],
    text_preview: str,
) -> tuple[SourceRef, ...]:
    base_source_id = _dialogue_turn_base_source_id(chunk.source_external_id)
    if not base_source_id or not _structured_refs_belong_to_source_group(
        source_refs,
        base_source_id=base_source_id,
    ):
        return ()
    inferred = _dialogue_turn_source_refs(chunk, text_preview=text_preview)
    if not inferred:
        return ()
    seen = {ref.source_id for ref in source_refs}
    return tuple(ref for ref in inferred if ref.source_id not in seen)


def _structured_refs_belong_to_source_group(
    source_refs: tuple[SourceRef, ...],
    *,
    base_source_id: str,
) -> bool:
    for ref in source_refs:
        source_id = " ".join(str(ref.source_id).split())
        if source_id == base_source_id or source_id.startswith(f"{base_source_id}:"):
            return True
    return False


def _dialogue_turn_base_source_id(source_external_id: str) -> str:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return ""
    parts = source_id.split(":")
    if len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D"):
        return ":".join(parts[:-3])
    if len(parts) >= 4 and parts[-1] in _SOURCE_GROUP_SUFFIXES:
        base = ":".join(parts[:-1])
        return base if _session_number(base) else ""
    return source_id if _session_number(source_id) else ""


def _session_number(source_id: str) -> str:
    match = _SESSION_ID_RE.search(source_id)
    return match.group("session") if match else ""


def _quote_preview(item: Mapping[str, object], *, text_preview: str) -> str:
    raw = item.get("quote_preview")
    if isinstance(raw, str) and raw.strip():
        return safe_metadata_text(raw, limit=240)
    return safe_metadata_text(text_preview[:200], limit=240)


def _metadata_char_range(
    item: Mapping[str, object],
    *,
    chunk: MemoryChunk,
) -> tuple[int | None, int | None]:
    start_present = "char_start" in item
    end_present = "char_end" in item
    start = _optional_int(item.get("char_start") if start_present else chunk.char_start)
    end = _optional_int(item.get("char_end") if end_present else chunk.char_end)
    if (start_present and start is None) or (end_present and end is None):
        return None, None
    if start is not None and end is not None and end < start:
        return None, None
    return start, end


def _metadata_time_range(item: Mapping[str, object]) -> tuple[int | None, int | None]:
    start_present = "time_start_ms" in item
    end_present = "time_end_ms" in item
    start = _optional_int(item.get("time_start_ms"))
    end = _optional_int(item.get("time_end_ms"))
    if (start_present and start is None) or (end_present and end is None):
        return None, None
    if start is not None and end is not None and end < start:
        return None, None
    return start, end


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_positive_int(value: object) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed >= 1 else None


def _optional_bbox(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
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
    if any(number < 0 for number in items) or items[2] <= items[0] or items[3] <= items[1]:
        return None
    return (items[0], items[1], items[2], items[3])
