"""Temporal query intent and scoring helpers for context assembly."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_temporal_hints import temporal_hint_codes
from infinity_context_core.application.dto import ContextItem

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_EXCLUDE_STALE_RE = re.compile(
    r"\b(?:not\s+stale|ignore\s+(?:stale|old|outdated)|"
    r"do\s+not\s+(?:use|include)\s+(?:stale|old|outdated))\b|"
    r"(?:устаревш\w*\s+не\s+учитывать|не\s+учитывать\s+устаревш\w*)",
    re.IGNORECASE,
)
_CURRENT_TERMS = frozenset(
    {
        "active",
        "actual",
        "актуальн",
        "актуально",
        "current",
        "действует",
        "latest",
        "newest",
        "now",
        "последн",
        "последнее",
        "recent",
        "сейчас",
        "текущ",
        "текущий",
        "valid",
    }
)
_PREVIOUS_TERMS = frozenset(
    {
        "before",
        "earlier",
        "initial",
        "previous",
        "prior",
        "superseded",
        "до",
        "перед",
        "предыдущ",
        "раньше",
        "устаревш",
    }
)
_CHANGE_TERMS = frozenset(
    {
        "change",
        "changed",
        "difference",
        "replaced",
        "superseded",
        "update",
        "updated",
        "измен",
        "изменилось",
        "обновлен",
        "обновление",
        "поменялось",
    }
)
_AFTER_TERMS = frozenset({"after", "following", "later", "после", "позже", "затем"})
_BEFORE_TERMS = frozenset({"before", "earlier", "prior", "до", "перед", "раньше"})


@dataclass(frozen=True)
class TemporalQueryIntent:
    prefers_current: bool
    requests_previous: bool
    requests_change: bool
    after_event: bool
    before_event: bool
    excludes_stale: bool
    relative_time_hints: tuple[str, ...] = ()

    @property
    def include_superseded_review(self) -> bool:
        return (self.requests_previous or self.requests_change) and not self.excludes_stale

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.prefers_current,
                self.requests_previous,
                self.requests_change,
                self.after_event,
                self.before_event,
                self.excludes_stale,
                self.relative_time_hints,
            )
        )

    def diagnostics(self) -> dict[str, object]:
        reasons: list[str] = []
        if self.prefers_current:
            reasons.append("prefers_current")
        if self.requests_previous:
            reasons.append("requests_previous")
        if self.requests_change:
            reasons.append("requests_change")
        if self.after_event:
            reasons.append("after_event")
        if self.before_event:
            reasons.append("before_event")
        if self.excludes_stale:
            reasons.append("excludes_stale")
        if self.relative_time_hints:
            reasons.append("relative_time_hint")
        return {
            "temporal_query_intent_status": "empty" if self.empty else "available",
            "temporal_query_prefers_current": self.prefers_current,
            "temporal_query_requests_previous": self.requests_previous,
            "temporal_query_requests_change": self.requests_change,
            "temporal_query_after_event": self.after_event,
            "temporal_query_before_event": self.before_event,
            "temporal_query_excludes_stale": self.excludes_stale,
            "temporal_query_include_superseded_review": (
                self.include_superseded_review
            ),
            "temporal_query_relative_time_hints": list(self.relative_time_hints),
            "temporal_query_intent_reasons": reasons,
        }


def build_temporal_query_intent(query: str) -> TemporalQueryIntent:
    variants = _query_variant_set(query)
    relative_time_hints = temporal_hint_codes(query)
    excludes_stale = bool(_EXCLUDE_STALE_RE.search(query))
    requests_change = bool(variants.intersection(_CHANGE_TERMS))
    requests_previous = (
        bool(variants.intersection(_PREVIOUS_TERMS)) and not excludes_stale
    )
    prefers_current = (
        excludes_stale
        or bool(variants.intersection(_CURRENT_TERMS))
        or (requests_change and not requests_previous)
    )
    return TemporalQueryIntent(
        prefers_current=prefers_current,
        requests_previous=requests_previous,
        requests_change=requests_change,
        after_event=bool(variants.intersection(_AFTER_TERMS)),
        before_event=bool(variants.intersection(_BEFORE_TERMS)),
        excludes_stale=excludes_stale,
        relative_time_hints=relative_time_hints,
    )


def apply_temporal_query_intent_boosts(
    items: tuple[ContextItem, ...],
    *,
    intent: TemporalQueryIntent,
) -> tuple[ContextItem, ...]:
    if intent.empty:
        return items
    return tuple(_apply_temporal_query_intent(item, intent=intent) for item in items)


def _apply_temporal_query_intent(
    item: ContextItem,
    *,
    intent: TemporalQueryIntent,
) -> ContextItem:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    retrieval_source = str(diagnostics.get("retrieval_source") or "")
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    fact_status = str(provenance.get("fact_status") or diagnostics.get("fact_status") or "")
    is_review_only = diagnostics.get("review_only") is True
    is_superseded = retrieval_source == "superseded_review" or fact_status == "superseded"
    has_temporal_relation = bool(diagnostics.get("temporal_relations"))
    temporal_hint_code = _temporal_hint_code(diagnostics, provenance)
    boost = 0.0
    reason = ""
    if intent.excludes_stale and (is_review_only or is_superseded):
        boost = -0.12
        reason = "query excludes stale memory"
    elif temporal_hint_code and temporal_hint_code in set(intent.relative_time_hints):
        boost = 0.032
        reason = "query relative time matches item event window"
    elif intent.requests_change and retrieval_source == "temporal_supersedes_relation":
        boost = 0.05
        reason = "query asks what changed and item is active replacement"
    elif intent.requests_change and has_temporal_relation:
        boost = 0.035
        reason = "query asks what changed and item has temporal relation"
    elif intent.requests_change and is_superseded:
        boost = 0.035
        reason = "query asks what changed and item is previous state evidence"
    elif intent.requests_previous and is_superseded:
        boost = 0.045
        reason = "query asks for previous state evidence"
    elif intent.prefers_current and not is_review_only and not is_superseded:
        boost = 0.018
        reason = "query prefers current active memory"
    if boost == 0.0:
        return item
    return _with_temporal_query_boost(
        item,
        boost=boost,
        reason=reason,
        intent=intent,
    )


def _with_temporal_query_boost(
    item: ContextItem,
    *,
    boost: float,
    reason: str,
    intent: TemporalQueryIntent,
) -> ContextItem:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    diagnostics["temporal_query_intent_reason"] = reason
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "temporal_query_intent_boost": round(boost, 4),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "temporal_query_intent_applied": True,
        "temporal_query_intent_reasons": intent.diagnostics()[
            "temporal_query_intent_reasons"
        ],
    }
    return replace(
        item,
        score=min(0.99, max(0.0, round(item.score + boost, 4))),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _query_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=32):
        variants.update(term.variants)
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            variants.add(token)
    return frozenset(variants)


def _temporal_hint_code(
    diagnostics: Mapping[str, object],
    provenance: Mapping[str, object],
) -> str:
    for source in (diagnostics, provenance):
        value = source.get("event_temporal_hint_code")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
