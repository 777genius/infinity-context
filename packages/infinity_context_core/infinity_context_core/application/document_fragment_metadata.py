"""Canonical source-reference metadata projection for document fragments."""

from __future__ import annotations


def _chunk_metadata_for_fragment(
    metadata: dict[str, object] | None,
    *,
    char_start: int,
    char_end: int,
) -> dict[str, object]:
    safe = dict(metadata or {})
    refs = _source_refs_for_fragment(
        safe.get("source_refs"),
        char_start=char_start,
        char_end=char_end,
    )
    if refs:
        safe["source_refs"] = refs
        safe["source_ref_count"] = len(refs)
    else:
        safe.pop("source_refs", None)
        safe.pop("source_ref_count", None)
    return safe


def _source_refs_for_fragment(
    value: object,
    *,
    char_start: int,
    char_end: int,
) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    refs: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ref_start = _optional_int(item.get("char_start"))
        ref_end = _optional_int(item.get("char_end"))
        if ref_start is None or ref_end is None:
            if char_start != 0:
                continue
            refs.append(dict(item))
        elif ref_start <= char_end and ref_end >= char_start:
            ref = dict(item)
            ref["chunk_char_start"] = max(ref_start, char_start) - char_start
            ref["chunk_char_end"] = max(min(ref_end, char_end) - char_start, 0)
            refs.append(ref)
        if len(refs) >= 24:
            break
    return refs


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None
