"""Prompt-safe context projection for canonical memory anchors."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    query_relevance_score_signals,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import MemoryAnchor

_IDENTITY_METADATA_KEYS = (
    "anchor_family",
    "canonical_key",
    "person_canonical_key",
    "project_canonical_key",
    "organization_canonical_key",
    "event_type",
    "event_type_canonical",
    "event_participant_label",
    "event_participant_relation",
    "event_participant_canonical_key",
    "event_temporal_phrase",
    "event_temporal_hint_code",
    "event_temporal_quantity",
    "event_temporal_unit",
)
_IDENTITY_LIST_METADATA_KEYS = ("event_identity_terms",)


def anchor_retrieval_text(anchor: MemoryAnchor) -> str:
    return " ".join(
        part
        for part in (
            anchor.kind.value,
            anchor.label,
            " ".join(anchor.aliases),
            anchor.description or "",
            anchor_identity_retrieval_text(anchor),
        )
        if part
    )


def anchor_identity_retrieval_text(anchor: MemoryAnchor) -> str:
    terms: list[str] = []
    for key in _IDENTITY_METADATA_KEYS:
        terms.extend(_metadata_search_terms(anchor.metadata.get(key)))
    for key in _IDENTITY_LIST_METADATA_KEYS:
        value = anchor.metadata.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                terms.extend(_metadata_search_terms(item))
    return " ".join(_dedupe_preserve_order(tuple(terms)))


def anchor_context_item(
    anchor: MemoryAnchor,
    *,
    relevance: QueryRelevance,
    identity_relevance: QueryRelevance,
    now: datetime | None,
) -> ContextItem:
    score = _anchor_score(
        anchor,
        relevance=relevance,
        identity_relevance=identity_relevance,
        now=now,
    )
    metadata = _anchor_identity_metadata(anchor)
    ranking_reason = (
        "canonical semantic anchor matched query via structured identity metadata"
        if identity_relevance.unique_term_hits > 0
        else "canonical semantic anchor matched query"
    )
    return ContextItem(
        item_id=str(anchor.id),
        item_type="anchor",
        text=_anchor_render_text(anchor, metadata=metadata),
        score=score,
        source_refs=anchor.evidence_refs,
        diagnostics={
            "memory_scope_id": str(anchor.memory_scope_id),
            "retrieval_source": "canonical_anchors",
            "retrieval_sources": ["canonical_anchors"],
            "ranking_reason": ranking_reason,
            "score_signals": {
                "base_score": 0.72,
                "final_score": score,
                "retrieval_channel": "canonical_anchors",
                "anchor_kind": anchor.kind.value,
                "confidence": anchor.confidence.value,
                **query_relevance_score_signals(relevance),
                "identity_unique_term_hits": identity_relevance.unique_term_hits,
                "identity_hit_ratio": identity_relevance.hit_ratio,
                "identity_relevance_boost": identity_relevance.score_boost,
            },
            "provenance": {
                "retrieval_sources": ["canonical_anchors"],
                "source_ref_count": len(anchor.evidence_refs),
                "anchor_kind": anchor.kind.value,
                "anchor_status": anchor.status.value,
                "normalized_key": anchor.normalized_key,
                "observed_at": anchor.observed_at.isoformat(),
                "valid_from": anchor.valid_from.isoformat() if anchor.valid_from else None,
                "valid_to": anchor.valid_to.isoformat() if anchor.valid_to else None,
                "identity_metadata": metadata,
            },
            "anchor_kind": anchor.kind.value,
            "normalized_key": anchor.normalized_key,
            "confidence": anchor.confidence.value,
            "observed_at": anchor.observed_at.isoformat(),
            "updated_at": anchor.updated_at.isoformat(),
            "identity_metadata": metadata,
            **metadata,
        },
    )


def _anchor_render_text(anchor: MemoryAnchor, *, metadata: dict[str, object]) -> str:
    alias_text = ", ".join(alias for alias in anchor.aliases if alias != anchor.label)
    parts = [f"{anchor.kind.value}: {anchor.label}"]
    if alias_text:
        parts.append(f"aliases: {alias_text}")
    if anchor.description:
        parts.append(f"description: {anchor.description}")
    event_details = _event_render_parts(metadata)
    if event_details:
        parts.append("identity: " + "; ".join(event_details))
    elif identity_terms := _identity_terms(metadata):
        parts.append("identity: " + ", ".join(identity_terms))
    return ". ".join(parts)


def _event_render_parts(metadata: dict[str, object]) -> tuple[str, ...]:
    parts: list[str] = []
    if event_type := _metadata_text(metadata.get("event_type"), limit=80):
        parts.append(f"event_type: {event_type}")
    if participant := _metadata_text(metadata.get("event_participant_label"), limit=120):
        relation = _metadata_text(metadata.get("event_participant_relation"), limit=80) or "with"
        parts.append(f"{relation}: {participant}")
    if temporal := _metadata_text(metadata.get("event_temporal_phrase"), limit=160):
        parts.append(f"time: {temporal}")
    return tuple(parts)


def _identity_terms(metadata: dict[str, object]) -> tuple[str, ...]:
    value = metadata.get("event_identity_terms")
    if isinstance(value, list):
        return tuple(
            text
            for item in value[:6]
            if (text := _metadata_text(item, limit=120))
        )
    for key in (
        "person_canonical_key",
        "project_canonical_key",
        "organization_canonical_key",
        "canonical_key",
    ):
        if text := _metadata_text(metadata.get(key), limit=120):
            return (text,)
    return ()


def _anchor_score(
    anchor: MemoryAnchor,
    *,
    relevance: QueryRelevance,
    identity_relevance: QueryRelevance,
    now: datetime | None,
) -> float:
    confidence_boost = _level_boost(anchor.confidence.value, low=0.01, medium=0.025, high=0.045)
    freshness_boost = _freshness_boost(anchor.updated_at, now=now)
    identity_boost = min(0.035, identity_relevance.score_boost * 0.5)
    return min(
        0.94,
        round(
            0.72
            + relevance.score_boost
            + identity_boost
            + confidence_boost
            + freshness_boost,
            4,
        ),
    )


def _anchor_identity_metadata(anchor: MemoryAnchor) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in _IDENTITY_METADATA_KEYS:
        if value := _metadata_text(anchor.metadata.get(key), limit=160):
            metadata[key] = value
    for key in _IDENTITY_LIST_METADATA_KEYS:
        value = anchor.metadata.get(key)
        if isinstance(value, (list, tuple)):
            items = [
                text
                for item in value[:8]
                if (text := _metadata_text(item, limit=120))
            ]
            if items:
                metadata[key] = items
    return metadata


def _metadata_search_terms(value: object) -> tuple[str, ...]:
    text = _metadata_text(value, limit=160)
    if not text:
        return ()
    normalized = text.replace("_", " ").replace("-", " ")
    colon_parts = tuple(part for part in normalized.replace(":", " ").split() if len(part) >= 2)
    return _dedupe_preserve_order((text, normalized, *colon_parts))


def _metadata_text(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    return safe_metadata_text(str(value), limit=limit).strip()


def _dedupe_preserve_order(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.strip().split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _level_boost(value: str, *, low: float, medium: float, high: float) -> float:
    if value == "high":
        return high
    if value == "low":
        return low
    return medium


def _freshness_boost(updated_at: datetime, *, now: datetime | None) -> float:
    if now is None:
        return 0.0
    comparable_updated_at = updated_at
    comparable_now = now
    if comparable_updated_at.tzinfo is None and comparable_now.tzinfo is not None:
        comparable_updated_at = comparable_updated_at.replace(tzinfo=comparable_now.tzinfo)
    elif comparable_updated_at.tzinfo is not None and comparable_now.tzinfo is None:
        comparable_now = comparable_now.replace(tzinfo=comparable_updated_at.tzinfo)
    age_days = max(0.0, (comparable_now - comparable_updated_at).total_seconds() / 86400)
    if age_days <= 7:
        return 0.02
    if age_days <= 30:
        return 0.012
    if age_days <= 180:
        return 0.006
    return 0.0
