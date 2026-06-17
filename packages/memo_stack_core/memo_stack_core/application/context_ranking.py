"""Context dedupe and ranking helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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
    source_refs = _merge_source_refs(primary.source_refs, secondary.source_refs)
    primary_diagnostics = _diagnostics(primary)
    secondary_diagnostics = _diagnostics(secondary)
    if not (
        _diagnostic_retrieval_sources(primary_diagnostics)
        or _diagnostic_retrieval_sources(secondary_diagnostics)
    ):
        return replace(primary, source_refs=source_refs)

    retrieval_sources = _ordered_unique(
        (
            *_diagnostic_retrieval_sources(primary_diagnostics),
            *_diagnostic_retrieval_sources(secondary_diagnostics),
        )
    )
    hybrid_boost = _hybrid_boost(
        retrieval_source_count=len(retrieval_sources),
        source_ref_count=len(source_refs),
    )
    score = min(0.99, round(max(primary.score, secondary.score) + hybrid_boost, 4))
    return replace(
        primary,
        score=score,
        source_refs=source_refs,
        diagnostics=_merge_diagnostics(
            primary=primary_diagnostics,
            secondary=secondary_diagnostics,
            retrieval_sources=retrieval_sources,
            source_ref_count=len(source_refs),
            primary_score=primary.score,
            secondary_score=secondary.score,
            hybrid_boost=hybrid_boost,
        ),
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


def _diagnostics(item: ContextItem) -> dict[str, Any]:
    return dict(item.diagnostics or {})


def _diagnostic_retrieval_sources(diagnostics: dict[str, Any]) -> tuple[str, ...]:
    raw_sources = diagnostics.get("retrieval_sources")
    values: list[str] = []
    if isinstance(raw_sources, (list, tuple)):
        values.extend(str(value).strip() for value in raw_sources)
    raw_source = diagnostics.get("retrieval_source")
    if raw_source:
        values.append(str(raw_source).strip())
    return tuple(value for value in values if value)


def _merge_diagnostics(
    *,
    primary: dict[str, Any],
    secondary: dict[str, Any],
    retrieval_sources: tuple[str, ...],
    source_ref_count: int,
    primary_score: float,
    secondary_score: float,
    hybrid_boost: float,
) -> dict[str, Any]:
    merged = {**secondary, **primary}
    merged["retrieval_sources"] = list(retrieval_sources)
    merged["merged_candidate_count"] = _candidate_count(primary) + _candidate_count(secondary)
    merged["ranking_reason"] = _ranking_reason(retrieval_sources)
    merged["score_signals"] = {
        **_safe_score_signals(secondary.get("score_signals")),
        **_safe_score_signals(primary.get("score_signals")),
        "dedupe_primary_score": round(primary_score, 4),
        "dedupe_secondary_score": round(secondary_score, 4),
        "hybrid_source_count": len(retrieval_sources),
        "hybrid_boost": round(hybrid_boost, 4),
        "source_ref_count": source_ref_count,
    }
    merged["provenance"] = {
        **_safe_mapping(secondary.get("provenance")),
        **_safe_mapping(primary.get("provenance")),
        "retrieval_sources": list(retrieval_sources),
        "source_ref_count": source_ref_count,
        "selected_retrieval_source": str(
            primary.get("retrieval_source")
            or (retrieval_sources[0] if retrieval_sources else "unknown")
        ),
    }
    return merged


def _candidate_count(diagnostics: dict[str, Any]) -> int:
    value = diagnostics.get("merged_candidate_count")
    return value if isinstance(value, int) and value > 0 else 1


def _safe_score_signals(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float, str, bool)) or item is None
    }


def _safe_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float, str, bool, list, tuple)) or item is None
    }


def _ranking_reason(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        return f"hybrid match via {', '.join(retrieval_sources)}"
    if retrieval_sources:
        return f"matched via {retrieval_sources[0]}"
    return "matched without retrieval channel diagnostics"


def _hybrid_boost(*, retrieval_source_count: int, source_ref_count: int) -> float:
    if retrieval_source_count <= 1:
        return 0.0
    source_boost = 0.035 * (retrieval_source_count - 1)
    provenance_boost = 0.01 * min(3, max(0, source_ref_count - 1))
    return min(0.08, source_boost + provenance_boost)


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
