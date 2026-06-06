"""Context dedupe and ranking helpers."""

from __future__ import annotations

from dataclasses import replace

from memo_stack_core.application.dto import ContextItem
from memo_stack_core.domain.entities import SourceRef


def dedupe_rank_items(items: tuple[ContextItem, ...]) -> tuple[ContextItem, ...]:
    by_key: dict[tuple[str, str], ContextItem] = {}
    for item in items:
        key = (item.item_type, item.item_id)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
        elif item.score > existing.score:
            by_key[key] = _merge_context_items(primary=item, secondary=existing)
        else:
            by_key[key] = _merge_context_items(primary=existing, secondary=item)
    return tuple(by_key.values())


def _merge_context_items(*, primary: ContextItem, secondary: ContextItem) -> ContextItem:
    return replace(
        primary,
        source_refs=_merge_source_refs(primary.source_refs, secondary.source_refs),
    )


def _merge_source_refs(
    primary: tuple[SourceRef, ...],
    secondary: tuple[SourceRef, ...],
) -> tuple[SourceRef, ...]:
    refs: list[SourceRef] = []
    seen: set[tuple[str, str, str | None, int | None, int | None, str | None]] = set()
    for ref in (*primary, *secondary):
        key = (
            ref.source_type,
            ref.source_id,
            ref.chunk_id,
            ref.char_start,
            ref.char_end,
            ref.quote_preview,
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return tuple(refs)
