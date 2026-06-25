"""National park inference rerank signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

NATIONAL_PARK_INFERENCE_REASON = "national_park_inference_bridge"

_NATIONAL_PARK_QUERY_RE = re.compile(
    r"\b(?:which|what)\b(?=.{0,80}\bnational\s+park\b)|"
    r"\bnational\s+park\b(?=.{0,100}\b(?:refer|referring|could|might|"
    r"talk(?:ed|ing)?|conversation|discuss(?:ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NATIONAL_PARK_EXACT_RE = re.compile(
    r"\bnational\s+park\b|"
    r"\b(?:road\s*trip|roadtrip)\b(?=.{0,160}\b(?:park|hiking|trail|map|dogs?|pup))",
    re.IGNORECASE | re.DOTALL,
)
_TRAIL_MAP_EVIDENCE_RE = re.compile(
    r"\b(?:map|route)\b(?=.{0,120}\b(?:trail|trails|hiking|park|trees|forest))|"
    r"\b(?:trail|trails|hiking)\b(?=.{0,120}\b(?:map|route|park|trees|forest))|"
    r"\bpark\b(?=.{0,120}\b(?:map|trail|trails|hiking|trees|forest))",
    re.IGNORECASE | re.DOTALL,
)
_VISUAL_EVIDENCE_MARKER_RE = re.compile(
    r"\b(?:image|photo|picture|caption|visual\s+query|query)\b",
    re.IGNORECASE,
)
_GENERIC_PARK_NOISE_RE = re.compile(
    r"\b(?:city\s+park|dog\s+park|theme\s+park|park\s+near\s+me|park\s+nearby|"
    r"play(?:ed|ing)?\s+(?:outside|in\s+the\s+park)|walks?\s+in\s+the\s+park)\b",
    re.IGNORECASE,
)


def national_park_inference_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer evidence that supports a national-park inference from multimodal clues."""

    if query_reason != NATIONAL_PARK_INFERENCE_REASON and not _NATIONAL_PARK_QUERY_RE.search(
        query
    ):
        return DomainRerankSignal()
    text = item.text
    has_exact = _NATIONAL_PARK_EXACT_RE.search(text) is not None
    has_trail_map = _TRAIL_MAP_EVIDENCE_RE.search(text) is not None
    has_visual_marker = _VISUAL_EVIDENCE_MARKER_RE.search(text) is not None
    if has_exact:
        return DomainRerankSignal(
            boost=0.064,
            reason="national_park_exact_evidence",
            rank_signal_key="national_park_inference_evidence",
            rank_signal=max(4.0, float(relevance.distinctive_term_hits)),
        )
    if has_trail_map and has_visual_marker:
        return DomainRerankSignal(
            boost=0.058,
            reason="national_park_visual_trail_map_evidence",
            rank_signal_key="national_park_inference_evidence",
            rank_signal=max(3.0, float(relevance.distinctive_term_hits)),
        )
    if _GENERIC_PARK_NOISE_RE.search(text) and not has_trail_map:
        return DomainRerankSignal(
            penalty=0.074,
            reason="national_park_generic_park_noise",
            rank_signal_key="national_park_generic_park_noise",
            rank_signal=1.0,
        )
    if "park" in text.casefold() and not has_trail_map and not has_visual_marker:
        return DomainRerankSignal(
            penalty=0.034,
            reason="national_park_topic_only_noise",
        )
    return DomainRerankSignal()
