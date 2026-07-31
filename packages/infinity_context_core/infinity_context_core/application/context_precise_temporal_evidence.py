"""Bounded contracts for exact evidence answering direct temporal questions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from infinity_context_core.application.dto import ContextItem

_DIRECT_TEMPORAL_ANSWER_RE = re.compile(
    r"^\s*(?:"
    r"when\s+(?:did|does|do|was|were|is|are|will|would|has|have|had|"
    r"can|could|should)\b|"
    r"(?:on\s+)?(?:what|which)\s+(?:date|day|time|weekday)\b|"
    r"когда\b|"
    r"(?:на\s+)?(?:какую|какой|какое)\s+(?:дату|день|время|число)\b"
    r")",
    re.IGNORECASE,
)
_COORDINATED_TEMPORAL_ANSWER_RE = re.compile(
    r"\b(?:and|or)\s+when\s+(?:did|does|do|was|were|is|are|will|would|"
    r"has|have|had|can|could|should)\b",
    re.IGNORECASE,
)
_TEMPORAL_RANKING_CONTEXT_RE = re.compile(
    r"\b(?:how\s+long|(?:what|which)\s+(?:exact\s+)?(?:date|day|month|time)|"
    r"exact\s+time)\b|"
    r"\b(?:before|after)\b|"
    r"\b(?:next|last|previous|prior)\s+"
    r"(?:time|day|week|month|year|night|weekend|meeting|call|conversation|"
    r"chat|session|event)\b|"
    r"\b(?:какая\s+дата|в\s+какой\s+день|какого\s+числа|как\s+долго)\b",
    re.IGNORECASE,
)
_TEMPORAL_EVIDENCE_RE = re.compile(
    r"\b(?:"
    r"session_\d+\s+date|date:\s*|"
    r"yesterday|tomorrow|the\s+other\s+day|"
    r"last\s+(?:night|week|month|year|mon(?:day)?|tue(?:sday)?|"
    r"wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"next\s+(?:week|month|year|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
    r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+(?:days?|weeks?)\s+ago"
    r")\b",
    re.IGNORECASE,
)
_TYPED_TEMPORAL_REASONS = frozenset(
    {
        "decomposition_temporal_answer",
        "pet_acquisition_date_bridge",
    }
)
_TEMPORAL_ANSWER_EVIDENCE_REASON = "temporal_answer_evidence"
_OBJECT_MISMATCH_REASON = "relation_requirement_object_mismatch"
_CONTRACT_TIER = 1


def requests_temporal_answer(query: str) -> bool:
    """Return whether the interrogative head requests a temporal answer."""

    normalized = query or ""
    return _DIRECT_TEMPORAL_ANSWER_RE.search(normalized) is not None or (
        _COORDINATED_TEMPORAL_ANSWER_RE.search(normalized) is not None
    )


def requests_temporal_ranking_context(query: str) -> bool:
    """Return whether temporal evidence can rank the requested answer context."""

    return requests_temporal_answer(query) or (
        _TEMPORAL_RANKING_CONTEXT_RE.search(query or "") is not None
    )


def is_precise_temporal_answer_evidence(*, item: ContextItem, query: str) -> bool:
    """Recognize a strong exact-turn answer without resolving benchmark labels."""

    if not requests_temporal_answer(query):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    signals = _score_signals(item)
    if _query_reason(item, signals=signals) not in _TYPED_TEMPORAL_REASONS:
        return False
    reasons = _rerank_reasons(item)
    if _TEMPORAL_ANSWER_EVIDENCE_REASON not in reasons or _OBJECT_MISMATCH_REASON in reasons:
        return False
    if _TEMPORAL_EVIDENCE_RE.search(item.text) is None:
        return False
    return (
        max(
            _numeric_signal(signals.get("distinctive_term_hits")),
            _numeric_signal(signals.get("unique_term_hits")),
        )
        >= 4
    )


def with_precise_temporal_evidence_contracts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
) -> tuple[ContextItem, ...]:
    """Annotate exact direct temporal answers for bounded source-diverse priority."""

    annotated: list[ContextItem] = []
    for item in items:
        if not is_precise_temporal_answer_evidence(item=item, query=query):
            annotated.append(item)
            continue
        diagnostics = dict(item.diagnostics or {})
        signals = _score_signals(item)
        signals["application_evidence_contract_tier"] = _CONTRACT_TIER
        signals["precise_temporal_answer_evidence"] = 1
        diagnostics["score_signals"] = signals
        annotated.append(replace(item, diagnostics=diagnostics))
    return tuple(annotated)


def _query_reason(item: ContextItem, *, signals: Mapping[str, object]) -> str:
    diagnostics = item.diagnostics or {}
    return str(
        diagnostics.get("query_expansion_reason") or signals.get("query_expansion_reason") or ""
    )


def _score_signals(item: ContextItem) -> dict[str, object]:
    diagnostics = item.diagnostics or {}
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, Mapping) else {}


def _rerank_reasons(item: ContextItem) -> frozenset[str]:
    diagnostics = item.diagnostics or {}
    provenance = diagnostics.get("provenance")
    if not isinstance(provenance, Mapping):
        return frozenset()
    reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(reasons, list | tuple):
        return frozenset()
    return frozenset(str(reason) for reason in reasons)


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


__all__ = (
    "is_precise_temporal_answer_evidence",
    "requests_temporal_answer",
    "requests_temporal_ranking_context",
    "with_precise_temporal_evidence_contracts",
)
