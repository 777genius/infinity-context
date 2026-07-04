"""Narrow current-answer rerank for conflicting memory evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.dto import ContextItem

_CURRENT_ANSWER_QUERY_RE = re.compile(
    r"\b(?:current|currently|latest|newest|final|canonical|source\s+of\s+truth|"
    r"settled|authoritative|active|right\s+now|now|still\s+valid|"
    r"what\s+(?:is|was)\s+the\s+final|what\s+should\s+(?:i|we)?\s*use)\b",
    re.IGNORECASE,
)
_HISTORICAL_QUERY_RE = re.compile(
    r"\b(?:previous|previously|former|old|earlier|initially|originally|"
    r"no\s+longer|not\s+current|stale|outdated|history|what\s+changed)\b",
    re.IGNORECASE,
)
_FINALITY_EVIDENCE_RE = re.compile(
    r"\b(?:correction|corrected|update|updated|actually|final(?:\s+answer|"
    r"\s+decision)?|latest|newest|current|currently|canonical|"
    r"source\s+of\s+truth|settled|authoritative|active|right\s+now|now\s+using|"
    r"should\s+use|use\s+this|remains?\s+valid|still\s+valid|replaced\s+by|"
    r"superseded\s+by|switched\s+to|changed\s+to)\b",
    re.IGNORECASE,
)
_STRONG_FINALITY_EVIDENCE_RE = re.compile(
    r"\b(?:correction|corrected|final(?:\s+answer|\s+decision)?|canonical|"
    r"source\s+of\s+truth|settled|authoritative|use\s+this|should\s+use|"
    r"replaced\s+by|superseded\s+by|switched\s+to|changed\s+to)\b",
    re.IGNORECASE,
)
_EARLIER_ASSERTION_RE = re.compile(
    r"\b(?:earlier|previously|initially|originally|at\s+first|prior|before|"
    r"used\s+to|former|old|stale|outdated|deprecated|no\s+longer|"
    r"not\s+current|superseded|was\s+using|had\s+said|first\s+said)\b",
    re.IGNORECASE,
)
_ASSERTION_SHAPE_RE = re.compile(
    r"\b(?:is|are|was|were|works?|lives?|uses?|using|prefers?|likes?|"
    r"selected|chosen|chose|decided|provider|tool|model|plan|policy|source)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}")
_STOPWORDS = frozenset(
    {
        "about",
        "active",
        "actually",
        "answer",
        "are",
        "authoritative",
        "canonical",
        "changed",
        "chosen",
        "corrected",
        "correction",
        "current",
        "currently",
        "decided",
        "decision",
        "did",
        "does",
        "evidence",
        "final",
        "for",
        "from",
        "latest",
        "memory",
        "newest",
        "now",
        "provider",
        "right",
        "said",
        "selected",
        "settled",
        "should",
        "source",
        "still",
        "the",
        "this",
        "truth",
        "updated",
        "use",
        "using",
        "valid",
        "was",
        "what",
        "which",
        "with",
    }
)


@dataclass(frozen=True)
class _ConflictProfile:
    item: ContextItem
    query_hits: int
    finality_strength: int
    earlier_assertion: bool
    assertion_shape: bool
    answer_terms: frozenset[str]


def apply_conflicting_evidence_currentness_rerank(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    max_boost: float = 0.05,
    max_penalty: float = 0.075,
) -> tuple[ContextItem, ...]:
    """Prefer explicit final/current evidence over earlier competing assertions."""
    if len(items) <= 1 or max_boost <= 0 or max_penalty <= 0:
        return items
    if not _query_asks_for_current_answer(query):
        return items
    query_terms = _content_terms(query)
    profiles = tuple(_conflict_profile(item, query_terms=query_terms) for item in items)
    final_profiles = tuple(profile for profile in profiles if profile.finality_strength > 0)
    if not final_profiles:
        return items
    competing_ids: set[int] = set()
    supported_final_ids: set[int] = set()
    for profile in profiles:
        if profile.finality_strength > 0:
            continue
        if not _can_compete_with_final_evidence(profile):
            continue
        for final_profile in final_profiles:
            if _has_distinct_answer_terms(profile, final_profile):
                competing_ids.add(id(profile.item))
                supported_final_ids.add(id(final_profile.item))
    if not competing_ids:
        return items
    return tuple(
        _with_conflict_currentness_adjustment(
            profile.item,
            boost=(
                _profile_boost(profile, max_boost=max_boost)
                if id(profile.item) in supported_final_ids
                else 0.0
            ),
            penalty=(
                _profile_penalty(profile, max_penalty=max_penalty)
                if id(profile.item) in competing_ids
                else 0.0
            ),
        )
        for profile in profiles
    )


def _query_asks_for_current_answer(query: str) -> bool:
    return (
        _CURRENT_ANSWER_QUERY_RE.search(query) is not None
        and _HISTORICAL_QUERY_RE.search(query) is None
    )


def _conflict_profile(
    item: ContextItem,
    *,
    query_terms: frozenset[str],
) -> _ConflictProfile:
    item_terms = _content_terms(item.text)
    finality_strength = 0
    if _FINALITY_EVIDENCE_RE.search(item.text) is not None:
        finality_strength = 1
    if _STRONG_FINALITY_EVIDENCE_RE.search(item.text) is not None:
        finality_strength = 2
    return _ConflictProfile(
        item=item,
        query_hits=len(query_terms & item_terms),
        finality_strength=finality_strength,
        earlier_assertion=_EARLIER_ASSERTION_RE.search(item.text) is not None,
        assertion_shape=_ASSERTION_SHAPE_RE.search(item.text) is not None,
        answer_terms=item_terms - query_terms,
    )


def _can_compete_with_final_evidence(profile: _ConflictProfile) -> bool:
    if not profile.answer_terms or not profile.assertion_shape:
        return False
    return profile.query_hits > 0 or profile.earlier_assertion


def _has_distinct_answer_terms(
    profile: _ConflictProfile,
    final_profile: _ConflictProfile,
) -> bool:
    if not final_profile.answer_terms:
        return False
    profile_only_terms = profile.answer_terms - final_profile.answer_terms
    final_only_terms = final_profile.answer_terms - profile.answer_terms
    if not profile_only_terms or not final_only_terms:
        return False
    return bool(profile.query_hits or final_profile.query_hits or profile.earlier_assertion)


def _profile_boost(profile: _ConflictProfile, *, max_boost: float) -> float:
    if profile.finality_strength <= 0:
        return 0.0
    boost = 0.032 if profile.finality_strength == 1 else 0.046
    if profile.query_hits > 0:
        boost += 0.004
    return round(min(max_boost, boost), 4)


def _profile_penalty(profile: _ConflictProfile, *, max_penalty: float) -> float:
    penalty = 0.045
    if profile.earlier_assertion:
        penalty += 0.02
    return round(min(max_penalty, penalty), 4)


def _with_conflict_currentness_adjustment(
    item: ContextItem,
    *,
    boost: float,
    penalty: float,
) -> ContextItem:
    if boost <= 0 and penalty <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    existing_boost = _numeric_signal(score_signals.get("deterministic_rerank_boost"))
    existing_penalty = _numeric_signal(score_signals.get("deterministic_rerank_penalty"))
    new_boost = round(existing_boost + boost, 4)
    new_penalty = round(existing_penalty + penalty, 4)
    score_signals.update(
        {
            "deterministic_rerank_boost": new_boost,
            "deterministic_rerank_penalty": new_penalty,
            "deterministic_rerank_net_adjustment": round(new_boost - new_penalty, 4),
            "current_conflict_finality_boost": boost,
            "current_conflict_earlier_assertion_penalty": penalty,
        }
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    reasons: list[str] = []
    if boost > 0:
        reasons.append("current_conflict_finality_evidence")
    if penalty > 0:
        reasons.append("current_conflict_earlier_assertion")
    reasons.extend(provenance.get("deterministic_rerank_reasons") or ())
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = score_signals
    diagnostics["provenance"] = {
        **provenance,
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(dict.fromkeys(reasons))[:8],
    }
    return replace(
        item,
        score=min(0.99, max(0.0, round(item.score + boost - penalty, 4))),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _content_terms(text: str) -> frozenset[str]:
    return frozenset(
        term
        for term in (match.group(0).casefold() for match in _WORD_RE.finditer(text))
        if len(term) >= 3 and term not in _STOPWORDS
    )


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return 0.0
