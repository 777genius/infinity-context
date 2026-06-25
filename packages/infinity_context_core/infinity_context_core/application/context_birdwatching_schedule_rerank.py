"""Birdwatching city-schedule rerank signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_REASON = "birdwatching_city_schedule_bridge"
_BROAD_ACTIVITY_REASON = "decomposition_activity_participation"
_QUERY_INTENT_RE = re.compile(
    r"\b(birdwatching|bird\s+watching|watching\s+birds?|birds?)\b",
    re.IGNORECASE,
)
_CORE_EVIDENCE_RE = re.compile(
    r"\b("
    r"birdwatching|bird\s+watching|watching\s+birds?|birds?|binoculars|binos|"
    r"notebook|log\s+them|bird\s+feeder|feeder|soar|eagles?|fly\s+around"
    r")\b",
    re.IGNORECASE,
)
_CITY_SCHEDULE_RE = re.compile(
    r"\b("
    r"busy\s+week|city\s+schedule|schedule|job\s+and\s+living\s+here|"
    r"city\s+living|hard(?:er)?\s+to\s+find\s+open\s+spaces|"
    r"without\s+going\s+outdoors|from\s+(?:his|her|their)\s+window"
    r")\b",
    re.IGNORECASE,
)
_LOCAL_NATURE_ACCESS_RE = re.compile(
    r"\b("
    r"dog\s+park\s+nearby|nearby\s+(?:dog\s+)?park|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"outside|outdoors|out\s+in\s+nature|being\s+in\s+(?:a\s+)?nature|"
    r"hustle\s+and\s+bustle|park\s+on\s+the\s+weekends?"
    r")\b",
    re.IGNORECASE,
)


def birdwatching_city_schedule_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer exact evidence that bridges birdwatching, schedule and local access."""

    if _is_noisy_broad_activity_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal(
            penalty=0.16,
            reason="birdwatching_city_schedule_broad_activity_noise",
        )
    if not _is_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    evidence_score = _evidence_score(item.text)
    if evidence_score <= 0:
        return DomainRerankSignal()
    if not _item_source_is_turn(item):
        return DomainRerankSignal(
            boost=0.012,
            reason="birdwatching_city_schedule_broad_evidence",
            rank_signal_key="birdwatching_city_schedule_answer_evidence",
            rank_signal=1.0,
        )
    if relevance.distinctive_term_hits < 2:
        return DomainRerankSignal()
    return DomainRerankSignal(
        boost=min(0.045, 0.018 + evidence_score * 0.009),
        reason="birdwatching_city_schedule_exact_evidence",
        rank_signal_key="birdwatching_city_schedule_answer_evidence",
        rank_signal=float(evidence_score + 1),
    )


def _is_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason == _REASON:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return signals.get("query_expansion_reason") == _REASON


def _is_noisy_broad_activity_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _QUERY_INTENT_RE.search(query) is None:
        return False
    if query_reason != _BROAD_ACTIVITY_REASON:
        return False
    return _evidence_score(item.text) <= 0


def _evidence_score(text: str) -> int:
    score = 0
    if _CORE_EVIDENCE_RE.search(text) is not None:
        score += 1
    if _CITY_SCHEDULE_RE.search(text) is not None:
        score += 1
    if _LOCAL_NATURE_ACCESS_RE.search(text) is not None:
        score += 1
    return score


def _item_source_is_turn(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    source_id = str(diagnostics.get("source_id") or "").strip()
    if not source_id:
        provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
        source_id = str(provenance.get("source_id") or "").strip()
    if source_id.casefold().endswith(":turn"):
        return True
    return any(_source_ref_is_turn(ref) for ref in item.source_refs)


def _source_ref_is_turn(ref: SourceRef) -> bool:
    return str(ref.source_id).casefold().endswith(":turn")
