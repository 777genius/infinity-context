"""Same person disambiguation policy; one implementation authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_profile,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    match_query_anchor_intent_to_text,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_relevance import has_project_identity_mismatch
from infinity_context_core.application.context_rerank_relevance import _non_negative_float_signal
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryAnchorKind

_SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY = 0.064


_SAME_PERSON_TOPIC_DECOY_TEXT_RE = re.compile(
    r"\b(?:about|around|regarding|topic|subject|agenda|covered|covers?|"
    r"discuss(?:ed|ion)?|mention(?:ed)?|said|told|wrote|asked|"
    r"recommended|suggested|project|plan|initiative|campaign|issue)\b",
    re.IGNORECASE,
)


_SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE = re.compile(
    r"\b(?:about|around|regarding|topic|subject)\b|"
    r"\b(?:what|which|who)\b(?=.{0,120}\b(?:ask(?:ed)?|discuss(?:ed)?|"
    r"mention(?:ed)?|recommend(?:ed)?|said|say|suggest(?:ed)?|wrote|write)\b)",
    re.IGNORECASE | re.DOTALL,
)


_SAME_PERSON_TOPIC_QUERY_STOP_TERMS = frozenset(
    {
        "about",
        "after",
        "ago",
        "and",
        "around",
        "ask",
        "asked",
        "call",
        "called",
        "chat",
        "chatted",
        "conversation",
        "day",
        "days",
        "did",
        "discuss",
        "discussed",
        "do",
        "does",
        "during",
        "hour",
        "hours",
        "latest",
        "last",
        "meeting",
        "mention",
        "mentioned",
        "message",
        "messaged",
        "recent",
        "said",
        "say",
        "sent",
        "spoke",
        "subject",
        "talk",
        "talked",
        "text",
        "texted",
        "topic",
        "was",
        "week",
        "weeks",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "write",
        "wrote",
        "о",
        "об",
        "про",
        "разговор",
        "сказал",
        "сказала",
        "созвон",
        "что",
    }
)


@dataclass(frozen=True)
class _SamePersonTopicProfile:
    item: ContextItem
    matches_query_person: bool
    has_anchor_conflict: bool
    topic_hits: int
    covers_topic: bool
    explicit_topic_decoy_shape: bool


def _apply_same_person_topic_disambiguation_penalties(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    max_penalty: float,
) -> tuple[ContextItem, ...]:
    topic_terms = _same_person_topic_terms(
        query=query,
        query_anchor_intent=query_anchor_intent,
    )
    if not topic_terms:
        return items
    support_threshold = min(2, len(topic_terms))
    profiles = tuple(
        _same_person_topic_profile(
            item,
            query=query,
            query_anchor_intent=query_anchor_intent,
            topic_terms=topic_terms,
            support_threshold=support_threshold,
        )
        for item in items
    )
    support_count = sum(
        1
        for profile in profiles
        if profile.matches_query_person and not profile.has_anchor_conflict and profile.covers_topic
    )
    if support_count <= 0:
        return items
    return tuple(
        _with_same_person_topic_disambiguation_penalty(
            profile.item,
            profile=profile,
            support_count=support_count,
            topic_term_count=len(topic_terms),
            max_penalty=max_penalty,
        )
        for profile in profiles
    )


def _same_person_topic_terms(
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
) -> tuple[LexicalQueryTerm, ...]:
    if _SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE.search(query) is None:
        return ()
    person_keys = query_anchor_intent.keys_for_kind(MemoryAnchorKind.PERSON)
    if len(person_keys) != 1:
        return ()
    terms: list[LexicalQueryTerm] = []
    seen: set[tuple[str, ...]] = set()
    for term in query_terms(query):
        variants = set(term.variants)
        if variants.intersection(person_keys):
            continue
        if variants.intersection(_SAME_PERSON_TOPIC_QUERY_STOP_TERMS):
            continue
        if not any(_same_person_topic_variant_is_specific(variant) for variant in variants):
            continue
        key = tuple(term.variants)
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return tuple(terms[:8])


def _same_person_topic_variant_is_specific(variant: str) -> bool:
    return len(variant) >= 3 and not variant.isdigit()


def _same_person_topic_profile(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    topic_terms: tuple[LexicalQueryTerm, ...],
    support_threshold: int,
) -> _SamePersonTopicProfile:
    anchor_match = match_query_anchor_intent_to_text(query_anchor_intent, item.text)
    matches_query_person = bool(
        anchor_match is not None and "query_person_identity_match" in anchor_match.reasons
    )
    has_anchor_conflict = query_anchor_intent_text_conflicts(
        query_anchor_intent, item.text
    ) or has_project_identity_mismatch(query=query, text=item.text)
    text_counts, _ = text_variant_profile(item.text)
    topic_hits = sum(1 for term in topic_terms if query_term_frequency(term, text_counts) > 0)
    return _SamePersonTopicProfile(
        item=item,
        matches_query_person=matches_query_person,
        has_anchor_conflict=has_anchor_conflict,
        topic_hits=topic_hits,
        covers_topic=topic_hits >= support_threshold,
        explicit_topic_decoy_shape=bool(_SAME_PERSON_TOPIC_DECOY_TEXT_RE.search(item.text)),
    )


def _with_same_person_topic_disambiguation_penalty(
    item: ContextItem,
    *,
    profile: _SamePersonTopicProfile,
    support_count: int,
    topic_term_count: int,
    max_penalty: float,
) -> ContextItem:
    if (
        not profile.matches_query_person
        or profile.has_anchor_conflict
        or profile.covers_topic
        or not profile.explicit_topic_decoy_shape
    ):
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    existing_penalty = (
        _non_negative_float_signal(score_signals.get("deterministic_rerank_penalty")) or 0.0
    )
    available_penalty = max(0.0, max_penalty - existing_penalty)
    penalty = min(
        available_penalty,
        _SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY,
    )
    if penalty <= 0:
        return item
    existing_boost = (
        _non_negative_float_signal(score_signals.get("deterministic_rerank_boost")) or 0.0
    )
    new_penalty = round(existing_penalty + penalty, 4)
    score_signals.update(
        {
            "deterministic_rerank_boost": round(existing_boost, 4),
            "deterministic_rerank_penalty": new_penalty,
            "deterministic_rerank_net_adjustment": round(
                existing_boost - new_penalty,
                4,
            ),
            "same_person_topic_disambiguation_penalty": round(penalty, 4),
            "same_person_topic_disambiguation_support_count": support_count,
            "same_person_topic_disambiguation_topic_hits": profile.topic_hits,
            "same_person_topic_disambiguation_topic_term_count": topic_term_count,
        }
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    reasons = list(provenance.get("deterministic_rerank_reasons") or ())
    reasons.append("same_person_wrong_topic_decoy")
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
        score=max(0.0, round(item.score - penalty, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )
