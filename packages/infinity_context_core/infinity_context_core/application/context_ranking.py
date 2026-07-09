"""Context dedupe, rank fusion and deterministic ranking helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache

import infinity_context_core.application.context_anchor_intent_ranking as _anchor_intent_ranking
import infinity_context_core.application.context_bm25_ranking as _bm25_ranking
import infinity_context_core.application.context_keyword_ranking as _keyword_ranking
import infinity_context_core.application.context_query_relevance_ranking as _query_relevance_ranking
import infinity_context_core.application.context_rank_dedupe as _rank_dedupe
import infinity_context_core.application.context_requirement_ranking as _requirement_ranking
import infinity_context_core.application.context_requirement_signals as _requirement_signals
import infinity_context_core.application.context_rerank_evidence_signals as _evidence_signals
from infinity_context_core.application.context_action_roles import action_role_rerank_signal
from infinity_context_core.application.context_activity_companion import (
    activity_companion_signal,
)
from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_conversation_counterparty import (
    conversation_counterparty_evidence_signal,
    conversation_recency_evidence_signal,
    conversation_recency_missing_temporal_signal,
    conversation_recency_temporal_hint_signal,
    conversation_topic_evidence_signal,
)
from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
    normalize_context_diagnostics,
    normalize_context_item_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_domain_rerank_apply import (
    apply_domain_rerank_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    commonality_who_else_anchor_override,
    has_multi_evidence_aggregation_candidate,
)
from infinity_context_core.application.context_inference_evidence import (
    answer_evidence_rerank_signal,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_profile,
)
from infinity_context_core.application.context_object_mismatch import (
    object_kind_mismatch_signal,
)
from infinity_context_core.application.context_polarity_rerank import (
    absence_contrast_signal,
    negative_preference_signal,
    status_polarity_signal,
)
from infinity_context_core.application.context_possession_source import (
    possession_source_signal,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    match_query_anchor_intent_to_text,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_rank_fusion import (
    apply_rank_fusion_boosts as apply_rank_fusion_boosts,
)
from infinity_context_core.application.context_rank_fusion import (
    reciprocal_rank_fusion_scores as reciprocal_rank_fusion_scores,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OWNER_REASONS as _ACTIVITY_OWNER_REASONS,
)
from infinity_context_core.application.context_relation_requirement import (
    relation_requirement_signal,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_query_relevance_sufficient,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_speaker_attribution import (
    speaker_attribution_signal,
)
from infinity_context_core.application.context_temporal_metadata import (
    temporal_hint_code_from_metadata,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
    temporal_query_boost_signal,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import (
    MemoryAnchorKind,
    SourceRef,
)

_QueryExpansionTerms = tuple[tuple[str, str, tuple[LexicalQueryTerm, ...]], ...]
_QUERY_ANCHOR_INTENT_MAX_BOOST = _anchor_intent_ranking.QUERY_ANCHOR_INTENT_MAX_BOOST
_CONTEXT_REQUIREMENT_MAX_BOOST = _requirement_ranking.CONTEXT_REQUIREMENT_MAX_BOOST
_GENERIC_BOOSTABLE_ANSWER_SHAPES = _requirement_ranking.GENERIC_BOOSTABLE_ANSWER_SHAPES
_RequirementCoverageSignals = _requirement_signals.RequirementCoverageSignals
_DETERMINISTIC_RERANK_MAX_BOOST = 0.055
_DETERMINISTIC_RERANK_MAX_PENALTY = 0.11
_STRONG_EVIDENCE_RERANK_SOURCES = frozenset(
    {
        "approved_context_linked_anchors",
        "approved_context_linked_asset_manifest_evidence",
        "approved_context_linked_assets",
        "approved_context_linked_chunks",
        "approved_context_linked_extraction_artifacts",
        "approved_context_linked_facts",
        "artifact_evidence",
        "canonical_anchor_relations",
        "canonical_anchors",
        "temporal_supersedes_relation",
    }
)
_ACTIVITY_OWNER_MATCH_BOOST = 0.012
_ACTIVITY_OWNER_MISMATCH_PENALTY = 0.042
_VOLUNTEER_CAREER_EVIDENCE_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|front\s+desk|"
    r"food|bed|talks?|compliments?|fulfilling|make\s+a\s+difference|"
    r"brighten|aunt|struggling|residents?|social\s+work|"
    r"counsel(?:or|ing)?|coordinator"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_CONTEXT_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|front\s+desk|"
    r"food|bed|talks?|compliments?|residents?|social\s+work|"
    r"counsel(?:or|ing)?|coordinator"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE = re.compile(
    r"\b("
    r"front\s+desk|talks?|compliments?|residents?|bed|food|"
    r"counsel(?:or|ing)?|coordinator|started\s+volunteering"
    r")\b",
    re.IGNORECASE,
)
_POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE = re.compile(
    r"\b(?:road\s*trip|roadtrip)\b(?=.{0,180}\b(?:yesterday|recent|"
    r"just\s+did|after\s+the\s+(?:road\s*trip|drive)|relax))|"
    r"\b(?:yesterday|just\s+did|recent|relax)\b(?=.{0,180}\b(?:road\s*trip|roadtrip))",
    re.IGNORECASE | re.DOTALL,
)
_SHOE_USAGE_CONTEXT_RE = re.compile(
    r"\b(?:shoes?|sneakers?)\b|walking\s+or\s+running|for\s+running|"
    r"purple\s+running\s+shoe",
    re.IGNORECASE,
)
_EVENT_PARTICIPATION_QUERY_RE = re.compile(
    r"\b(attend(?:ed|ing)?|participat(?:e|ed|ing)|partook|joined|went)\b",
    re.IGNORECASE,
)
_EVENT_TERM_QUERY_RE = re.compile(r"\b(events?|parade|conference|group|program)\b", re.IGNORECASE)
_TEMPORAL_ANSWER_QUERY_RE = re.compile(
    r"\b(?:when|what\s+date|what\s+day|which\s+day|how\s+long)\b|"
    r"\b(?:когда|какая\s+дата|в\s+какой\s+день|какого\s+числа|как\s+долго)\b",
    re.IGNORECASE,
)
_TEMPORAL_ANSWER_EVIDENCE_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:|today|yesterday|tomorrow|recently|ago|"
    r"last\s+(?:week|month|year|night|weekend|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"сегодня|вчера|завтра|неделю\s+назад|месяц\s+назад|год\s+назад|"
    r"прошл\w+\s+(?:недел\w+|месяц\w+|год\w+|ноч\w+)|"
    r"следующ\w+\s+(?:недел\w+|месяц\w+|год\w+))\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|"
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|"
    r"\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)(?:,?\s+\d{2,4})?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{2,4})?\b",
    re.IGNORECASE,
)
_MISSED_EVENT_TEXT_RE = re.compile(r"\bmissed\s+(?:it|the|that)?\b", re.IGNORECASE)
_SELF_MISSED_EVENT_TEXT_RE = re.compile(r"\b(?:i|we)\s+missed\s+(?:it|the|that)?\b", re.IGNORECASE)
_POSITIVE_EVENT_TEXT_RE = re.compile(
    r"\b(attended|participated|joined|went|marched|took part)\b",
    re.IGNORECASE,
)
_POSITIVE_EVENT_PARTICIPATION_TEXT_RE = re.compile(
    r"\b(?:i|we)\s+(?:recently\s+|also\s+|just\s+|last\s+\w+\s+)?"
    r"(?:went|attended|participated|joined|marched|took\s+part)\b|"
    r"\b(?:went\s+to|attended|participated\s+in|joined)\b.{0,80}"
    r"\b(?:events?|parade|conference|group|program|campaign)\b",
    re.IGNORECASE | re.DOTALL,
)
_POSITIVE_ACTIVITY_TEXT_RE = re.compile(
    r"\b(?:hikes?|hiking|camp(?:ing|fire|ed)?|marshmallows?|forest|trail|"
    r"outdoors?|nature|museum|dinosaur|exhibit|park|playground|pottery|"
    r"workshop|clay|pots?|painting|painted|swimm(?:ing)?|swam|beach|"
    r"waterfall|mountains?|concert|running|race)\b",
    re.IGNORECASE,
)
_SPEAKER_LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_SPEAKER_LABEL_RE}):",
    re.IGNORECASE,
)


def dedupe_rank_items(items: tuple[ContextItem, ...]) -> tuple[ContextItem, ...]:
    return _rank_dedupe.dedupe_rank_items(items)


def apply_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    k1: float = 1.2,
    b: float = 0.75,
    max_boost: float = 0.035,
) -> tuple[ContextItem, ...]:
    return _bm25_ranking.apply_bm25_lexical_boosts(
        items,
        query=query,
        k1=k1,
        b=b,
        max_boost=max_boost,
        query_terms_fn=query_terms,
        query_term_frequency_fn=query_term_frequency,
    )


def apply_query_plan_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    plan: QueryExpansionPlan,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
    k1: float = 1.2,
    b: float = 0.75,
    max_boost: float = 0.035,
) -> tuple[ContextItem, ...]:
    return _bm25_ranking.apply_query_plan_bm25_lexical_boosts(
        items,
        plan=plan,
        bm25_text_stats_cache=bm25_text_stats_cache,
        k1=k1,
        b=b,
        max_boost=max_boost,
        query_expansion_terms_fn=_query_expansion_terms,
        query_term_frequency_fn=query_term_frequency,
    )


def apply_query_anchor_intent_boosts(
    items: tuple[ContextItem, ...],
    *,
    intent: QueryAnchorIntent,
    max_boost: float = _QUERY_ANCHOR_INTENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    return _anchor_intent_ranking.apply_query_anchor_intent_boosts(
        items,
        intent=intent,
        max_boost=max_boost,
    )


def apply_context_requirement_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    max_boost: float = _CONTEXT_REQUIREMENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    return _requirement_ranking.apply_context_requirement_boosts(
        items,
        query=query,
        query_anchor_intent=query_anchor_intent,
        max_boost=max_boost,
    )


def apply_deterministic_rerank_adjustments(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
    max_boost: float = _DETERMINISTIC_RERANK_MAX_BOOST,
    max_penalty: float = _DETERMINISTIC_RERANK_MAX_PENALTY,
) -> tuple[ContextItem, ...]:
    if not items or (max_boost <= 0 and max_penalty <= 0):
        return items
    requested_coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(),
    )
    temporal_query_intent = build_temporal_query_intent(query)
    requested_total = _coverage_int(requested_coverage.get("requested_total"))
    has_multi_aggregation_candidate = has_multi_evidence_aggregation_candidate(
        query=query,
        items=items,
    )
    return tuple(
        _with_deterministic_rerank_adjustment(
            item,
            query=query,
            plan=plan,
            query_anchor_intent=query_anchor_intent,
            temporal_query_intent=temporal_query_intent,
            requested_total=requested_total,
            has_multi_evidence_aggregation_candidate=has_multi_aggregation_candidate,
            query_relevance_cache=query_relevance_cache,
            max_boost=max_boost,
            max_penalty=max_penalty,
        )
        for item in items
    )


@lru_cache(maxsize=512)
def _query_expansion_terms_for_signature(
    signature: tuple[tuple[str, str], ...],
) -> _QueryExpansionTerms:
    return tuple((query, reason, query_terms(query)) for query, reason in signature)


def _query_expansion_terms(plan: QueryExpansionPlan) -> _QueryExpansionTerms:
    return _query_expansion_terms_for_signature(
        tuple((expansion.query, expansion.reason) for expansion in plan.retrieval_queries)
    )


def best_query_relevance(
    plan: QueryExpansionPlan,
    *,
    text: str,
) -> tuple[str, str, QueryRelevance]:
    return _query_relevance_ranking.best_query_relevance(
        plan,
        text=text,
        query_expansion_terms_fn=_query_expansion_terms,
        query_relevance_rank_key_fn=query_relevance_rank_key,
        text_variant_profile_fn=text_variant_profile,
    )


def query_relevance_rank_key(
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    return _query_relevance_ranking.query_relevance_rank_key(item)


def _query_reason_priority_for_relevance(
    reason: str,
    relevance: QueryRelevance,
) -> int:
    return _query_relevance_ranking.query_reason_priority_for_relevance(reason, relevance)


def keyword_chunk_score(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
) -> float:
    return _keyword_ranking.keyword_chunk_score(
        relevance,
        query_expansion_reason=query_expansion_reason,
    )


def keyword_chunk_source_score_boost(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> float:
    return _keyword_ranking.keyword_chunk_source_score_boost(
        relevance,
        query_expansion_reason=query_expansion_reason,
        source_external_id=source_external_id,
    )


def query_expansion_reason_priority(reason: str) -> int:
    return _keyword_ranking.query_expansion_reason_priority(reason)


def apply_keyword_chunk_source_score_boost(
    score: float,
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> tuple[float, float]:
    return _keyword_ranking.apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=query_expansion_reason,
        source_external_id=source_external_id,
    )


@dataclass(frozen=True)
class _DeterministicRerankSignals:
    boost: float
    penalty: float
    reasons: tuple[str, ...]
    rank_signals: tuple[tuple[str, float], ...]
    source_count: int
    strong_source_count: int
    coverage_ratio: float
    anchor_conflict: bool
    query_reason: str

    @property
    def net_adjustment(self) -> float:
        return round(self.boost - self.penalty, 4)


def _with_deterministic_rerank_adjustment(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
) -> ContextItem:
    normalized_item = normalize_context_item_diagnostics(item)
    if _deterministic_rerank_already_applied_in_diagnostics(normalized_item.diagnostics):
        return item
    signals = _deterministic_rerank_signals(
        normalized_item,
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        temporal_query_intent=temporal_query_intent,
        requested_total=requested_total,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
        query_relevance_cache=query_relevance_cache,
        max_boost=max_boost,
        max_penalty=max_penalty,
    )
    if signals.net_adjustment == 0 and not signals.rank_signals:
        return item
    diagnostics = normalize_context_diagnostics(normalized_item.diagnostics)
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "deterministic_rerank_boost": signals.boost,
        "deterministic_rerank_penalty": signals.penalty,
        "deterministic_rerank_net_adjustment": signals.net_adjustment,
        "deterministic_rerank_source_count": signals.source_count,
        "deterministic_rerank_strong_source_count": signals.strong_source_count,
        "deterministic_rerank_requirement_coverage": signals.coverage_ratio,
        "deterministic_rerank_query_reason": signals.query_reason,
        **{key: value for key, value in signals.rank_signals},
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(signals.reasons[:8]),
        "deterministic_rerank_anchor_conflict": signals.anchor_conflict,
    }
    return replace(
        normalized_item,
        score=min(0.99, max(0.0, round(normalized_item.score + signals.net_adjustment, 4))),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _deterministic_rerank_signals(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
) -> _DeterministicRerankSignals:
    sources = diagnostic_retrieval_sources(item.diagnostics)
    strong_source_count = len(set(sources).intersection(_STRONG_EVIDENCE_RERANK_SOURCES))
    query_text, query_reason, relevance = _best_query_relevance_for_rerank(
        plan,
        item=item,
        cache=query_relevance_cache,
    )
    del query_text
    coverage = _requirement_signals.item_requirement_coverage_signals(
        item,
        query=query,
        query_anchor_intent=query_anchor_intent,
        requested_total=requested_total,
    )
    coverage_ratio = coverage.ratio
    anchor_match = match_query_anchor_intent_to_text(query_anchor_intent, item.text)
    text_anchor_conflict = query_anchor_intent_text_conflicts(
        query_anchor_intent,
        item.text,
    )
    project_identity_conflict = has_project_identity_mismatch(query=query, text=item.text)
    anchor_conflict = text_anchor_conflict or project_identity_conflict
    source_speaker_anchor_override = (
        text_anchor_conflict
        and not project_identity_conflict
        and _dialogue_speaker_confirms_query_anchor(
            item=item,
            query_anchor_intent=query_anchor_intent,
            relevance=relevance,
        )
    )
    commonality_anchor_override = (
        text_anchor_conflict
        and not project_identity_conflict
        and commonality_who_else_anchor_override(
            query=query,
            query_reason=query_reason,
            item=item,
        )
    )
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []
    rank_signals: dict[str, float] = {}
    if len(sources) >= 2:
        boost += min(0.018, 0.006 * len(sources))
        reasons.append("hybrid_source_diversity")
    if strong_source_count:
        boost += min(0.018, 0.008 * strong_source_count)
        reasons.append("strong_evidence_source")
    if anchor_match is not None:
        boost += min(0.018, max(0.0, anchor_match.score_boost) * 0.35)
        reasons.append("query_anchor_match")
    if requested_total > 0 and coverage_ratio > 0:
        boost += 0.014 * coverage_ratio
        reasons.append("explicit_requirement_covered")
    answer_shape_boost = 0.0
    boostable_requested_answer_shapes = (
        coverage.requested_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    boostable_covered_answer_shapes = (
        coverage.covered_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    if boostable_requested_answer_shapes and boostable_covered_answer_shapes:
        answer_shape_boost = 0.018 * (
            len(boostable_covered_answer_shapes) / len(boostable_requested_answer_shapes)
        )
    if "speaker" in coverage.covered_answer_shapes:
        boost += 0.018
        reasons.append("speaker_answer_shape_covered")
    if is_query_relevance_sufficient(relevance):
        relevance_boost = min(
            0.012,
            relevance.score_boost * 0.1 + relevance.distinctive_term_hits * 0.003,
        )
        if relevance_boost > 0:
            boost += relevance_boost
            reasons.append("query_relevance_supported")
    localized_evidence_boost, localized_evidence_reason = (
        _evidence_signals.localized_evidence_support_signal(
            item=item,
            relevance=relevance,
            coverage_ratio=coverage_ratio,
            anchor_matched=anchor_match is not None,
            strong_source_count=strong_source_count,
        )
    )
    if localized_evidence_boost > 0:
        boost += localized_evidence_boost
        reasons.append(localized_evidence_reason)
    decomposition_boost, decomposition_reason, decomposition_signals = (
        _evidence_signals.decomposition_coverage_support_signal(
            plan=plan,
            text=item.text,
            query_reason=query_reason,
        )
    )
    if decomposition_boost > 0:
        boost += decomposition_boost
        reasons.append(decomposition_reason)
        rank_signals.update(decomposition_signals)
    canonical_summary_boost, canonical_summary_reason = (
        _evidence_signals.canonical_anchor_summary_support_signal(
            item=item,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None,
            anchor_conflict=anchor_conflict,
            sources=sources,
            strong_source_count=strong_source_count,
        )
    )
    if canonical_summary_boost > 0:
        boost += canonical_summary_boost
        reasons.append(canonical_summary_reason)
    citation_evidence_boost, citation_evidence_reason = (
        _evidence_signals.citation_evidence_support_signal(
            item=item,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None,
            strong_source_count=strong_source_count,
        )
    )
    if citation_evidence_boost > 0:
        boost += citation_evidence_boost
        reasons.append(citation_evidence_reason)
    (
        artifact_inventory_boost,
        artifact_inventory_penalty,
        artifact_inventory_reason,
        artifact_inventory_signals,
    ) = _evidence_signals.artifact_inventory_evidence_support_signal(
        item=item,
        plan=plan,
        query_reason=query_reason,
        relevance=relevance,
        coverage_ratio=coverage_ratio,
        anchor_matched=anchor_match is not None,
    )
    if artifact_inventory_boost > 0:
        boost += artifact_inventory_boost
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
    if artifact_inventory_penalty > 0:
        penalty += artifact_inventory_penalty
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
    owner_boost, owner_penalty, owner_reason = _activity_owner_signal(
        query_anchor_intent=query_anchor_intent,
        query_reason=query_reason,
        text=item.text,
    )
    if owner_boost > 0:
        boost += owner_boost
        reasons.append(owner_reason)
    if owner_penalty > 0:
        penalty += owner_penalty
        reasons.append(owner_reason)
    speaker_boost, speaker_penalty, speaker_reason = speaker_attribution_signal(
        query=query,
        text=item.text,
    )
    if speaker_boost > 0:
        boost += speaker_boost
        reasons.append(speaker_reason)
    if speaker_penalty > 0:
        penalty += speaker_penalty
        reasons.append(speaker_reason)
    if (
        answer_shape_boost > 0
        and owner_penalty <= 0
        and speaker_penalty <= 0
        and not anchor_conflict
    ):
        boost += answer_shape_boost
        reasons.append("explicit_answer_shape_covered")
    action_signal = action_role_rerank_signal(query=query, text=item.text)
    if action_signal.boost > 0:
        boost += action_signal.boost
        reasons.append(action_signal.reason)
    if action_signal.penalty > 0:
        penalty += action_signal.penalty
        reasons.append(action_signal.reason)
    possession_boost, possession_penalty, possession_reason = possession_source_signal(
        query=query,
        item=item,
    )
    if possession_boost > 0:
        boost += possession_boost
        reasons.append(possession_reason)
    if possession_penalty > 0:
        penalty += possession_penalty
        reasons.append(possession_reason)
    inference_signal = answer_evidence_rerank_signal(query=query, text=item.text)
    if inference_signal.boost > 0:
        boost += inference_signal.boost
        reasons.append(inference_signal.reason)
    if inference_signal.penalty > 0:
        penalty += inference_signal.penalty
        reasons.append(inference_signal.reason)
    polarity_boost, polarity_penalty, polarity_reason = status_polarity_signal(
        query=query,
        text=item.text,
    )
    if polarity_boost > 0:
        boost += polarity_boost
        reasons.append(polarity_reason)
    if polarity_penalty > 0:
        penalty += polarity_penalty
        reasons.append(polarity_reason)
    negative_boost, negative_penalty, negative_reason = negative_preference_signal(
        query=query,
        text=item.text,
    )
    if negative_boost > 0:
        boost += negative_boost
        reasons.append(negative_reason)
    if negative_penalty > 0:
        penalty += negative_penalty
        reasons.append(negative_reason)
    contrast_boost, contrast_penalty, contrast_reason = absence_contrast_signal(
        query=query,
        text=item.text,
    )
    if contrast_boost > 0:
        boost += contrast_boost
        reasons.append(contrast_reason)
    if contrast_penalty > 0:
        penalty += contrast_penalty
        reasons.append(contrast_reason)
    object_boost, object_penalty, object_reason = object_kind_mismatch_signal(
        query=query,
        text=item.text,
    )
    if object_boost > 0:
        boost += object_boost
        reasons.append(object_reason)
    if object_penalty > 0:
        penalty += object_penalty
        reasons.append(object_reason)
    relation_signal = relation_requirement_signal(query=query, text=item.text)
    if relation_signal.boost > 0:
        boost += relation_signal.boost
        reasons.append(relation_signal.reason)
    if (
        relation_signal.penalty > 0
        and not _is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        penalty += relation_signal.penalty
        reasons.append(relation_signal.reason)
    conversation_boost, conversation_penalty, conversation_reason = (
        conversation_counterparty_evidence_signal(
            query=query,
            text=item.text,
        )
    )
    if conversation_boost > 0:
        boost += conversation_boost
        reasons.append(conversation_reason)
    if conversation_penalty > 0:
        penalty += conversation_penalty
        reasons.append(conversation_reason)
    topic_boost, topic_penalty, topic_reason = conversation_topic_evidence_signal(
        query=query,
        text=item.text,
    )
    if topic_boost > 0:
        boost += topic_boost
        reasons.append(topic_reason)
    if topic_penalty > 0:
        penalty += topic_penalty
        reasons.append(topic_reason)
    recency_boost, recency_penalty, recency_reason = conversation_recency_evidence_signal(
        query=query,
        text=item.text,
    )
    if recency_boost > 0:
        boost += recency_boost
        reasons.append(recency_reason)
    if recency_penalty > 0:
        penalty += recency_penalty
        reasons.append(recency_reason)
    temporal_hint_code = _item_temporal_hint_code(item)
    recency_hint_boost, recency_hint_reason = conversation_recency_temporal_hint_signal(
        query=query,
        temporal_hint_code=temporal_hint_code,
    )
    if recency_hint_boost > 0:
        boost += recency_hint_boost
        reasons.append(recency_hint_reason)
    recency_missing_time_penalty, recency_missing_time_reason = (
        conversation_recency_missing_temporal_signal(
            query=query,
            text=item.text,
            temporal_hint_code=temporal_hint_code,
        )
    )
    if recency_missing_time_penalty > 0:
        penalty += recency_missing_time_penalty
        reasons.append(recency_missing_time_reason)
    if not _temporal_query_signal_already_applied(item):
        temporal_signal = temporal_query_boost_signal(
            item,
            intent=temporal_query_intent,
        )
        if temporal_signal.boost > 0:
            boost += temporal_signal.boost
            reasons.append(f"temporal_query_{temporal_signal.code}")
        if temporal_signal.boost < 0:
            penalty += abs(temporal_signal.boost)
            reasons.append(f"temporal_query_{temporal_signal.code}")
    temporal_answer_boost, temporal_answer_penalty, temporal_answer_reason = (
        _temporal_answer_signal(query=query, query_reason=query_reason, item=item)
    )
    if temporal_answer_boost > 0:
        boost += temporal_answer_boost
        reasons.append(temporal_answer_reason)
    if temporal_answer_penalty > 0:
        penalty += temporal_answer_penalty
        reasons.append(temporal_answer_reason)
    if source_speaker_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_source_speaker")
    elif commonality_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_commonality_who_else")
    elif anchor_conflict and not _action_role_confirms_requested_relation(action_signal.reason):
        penalty += 0.07
        reasons.append("query_anchor_conflict")
    elif anchor_conflict:
        reasons.append("query_anchor_conflict_overridden_by_action_role")
    if _event_participation_mismatch(query=query, text=item.text):
        penalty += 0.075
        reasons.append("event_participation_mismatch")
    elif _event_participation_positive_match(query=query, text=item.text):
        boost += 0.018
        reasons.append("event_participation_positive_match")
    elif _event_participation_source_sibling_noise(query=query, item=item):
        penalty += 0.07
        reasons.append("event_participation_source_sibling_noise")
    companion_boost, companion_penalty, companion_reason = activity_companion_signal(
        query=query,
        item=item,
        query_anchor_intent=query_anchor_intent,
    )
    if companion_boost > 0:
        boost += companion_boost
        reasons.append(companion_reason)
    if companion_penalty > 0:
        penalty += companion_penalty
        reasons.append(companion_reason)
    if _activity_source_sibling_noise(item=item):
        penalty += 0.04
        reasons.append("activity_source_sibling_noise")
    if _capped_source_sibling_low_signal(item=item):
        penalty += 0.06
        reasons.append("capped_source_sibling_low_signal")
    if _allergy_condition_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.07
        reasons.append("allergy_condition_weak_evidence")
    if _patriotic_service_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("patriotic_service_weak_evidence")
    if _running_reason_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("running_reason_weak_evidence")
    if _volunteer_career_exact_turn_evidence(query_reason=query_reason, item=item):
        boost += 0.028
        reasons.append("volunteer_career_exact_turn_evidence")
    if _volunteer_career_weak_evidence(
        query_anchor_intent=query_anchor_intent,
        query_reason=query_reason,
        item=item,
    ):
        penalty += 0.07
        reasons.append("volunteer_career_weak_evidence")
    if _volunteer_career_broad_evidence(query_reason=query_reason, item=item):
        penalty += 0.07
        reasons.append("volunteer_career_broad_evidence")
    if _post_event_activity_timing_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.032
        reasons.append("post_event_activity_timing_exact_evidence")
    if _post_event_activity_timing_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("post_event_activity_timing_weak_evidence")
    if _shoe_usage_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.024
        reasons.append("shoe_usage_exact_evidence")
    if _shoe_usage_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("shoe_usage_weak_evidence")
    domain_adjustment = apply_domain_rerank_signals(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
    )
    boost += domain_adjustment.boost
    penalty += domain_adjustment.penalty
    reasons.extend(domain_adjustment.reasons)
    rank_signals.update(domain_adjustment.rank_signals)
    slot_diverse_aggregation = aggregation_answer_slot_count(query=query, text=item.text) >= 2
    event_detail_requirement_support = "temporal_camping_detail_evidence" in reasons
    artifact_inventory_requirement_support = (
        "artifact_inventory_first_party_evidence" in reasons
    )
    if requested_total > 0:
        if coverage_ratio <= 0 and (
            event_detail_requirement_support or artifact_inventory_requirement_support
        ):
            if event_detail_requirement_support:
                reasons.append("explicit_requirement_supported_by_event_detail")
            if artifact_inventory_requirement_support:
                reasons.append("explicit_requirement_supported_by_artifact_inventory")
        elif coverage_ratio <= 0:
            penalty += 0.025
            reasons.append("explicit_requirement_missing")
        elif coverage_ratio < 0.5 and not slot_diverse_aggregation:
            penalty += 0.012
            reasons.append("explicit_requirement_partial")
    if coverage.missing_answer_shapes and not slot_diverse_aggregation:
        penalty += min(
            0.02,
            0.014 * len(coverage.missing_answer_shapes),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_answer_shape_missing")
    if coverage.missing_modalities and not artifact_inventory_requirement_support:
        penalty += min(
            0.032,
            0.024 * len(coverage.missing_modalities),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_modality_missing")
    if (
        coverage.missing_evidence_features
        and not slot_diverse_aggregation
        and not artifact_inventory_requirement_support
    ):
        penalty += min(
            0.028,
            0.02 * len(coverage.missing_evidence_features),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_evidence_feature_missing")
    if (
        not is_query_relevance_sufficient(relevance)
        and anchor_match is None
        and coverage_ratio <= 0
    ):
        penalty += 0.018
        reasons.append("weak_query_relevance")
    elif (
        _is_long_query_weak_overlap(relevance)
        and anchor_match is None
        and coverage_ratio <= 0
        and strong_source_count <= 0
        and len(sources) <= 1
    ):
        penalty += 0.016
        reasons.append("weak_long_query_overlap")
    return _DeterministicRerankSignals(
        boost=round(min(max_boost, boost), 4),
        penalty=round(min(max_penalty, penalty), 4),
        reasons=tuple(dict.fromkeys(reasons)),
        rank_signals=tuple(sorted(rank_signals.items())),
        source_count=len(sources),
        strong_source_count=strong_source_count,
        coverage_ratio=round(coverage_ratio, 4),
        anchor_conflict=anchor_conflict,
        query_reason=query_reason,
    )


def _is_long_query_weak_overlap(relevance: QueryRelevance) -> bool:
    if relevance.query_term_count < 6:
        return False
    if relevance.phrase_bigram_hits > 0:
        return False
    return relevance.distinctive_term_hits <= 1 and relevance.unique_term_hits <= 2


def _best_query_relevance_for_rerank(
    plan: QueryExpansionPlan,
    *,
    item: ContextItem,
    cache: dict[str, tuple[str, str, QueryRelevance]] | None,
) -> tuple[str, str, QueryRelevance]:
    diagnostics_relevance = _query_relevance_from_item_diagnostics(plan, item)
    if diagnostics_relevance is not None:
        return diagnostics_relevance
    text = item.text
    if cache is None:
        return best_query_relevance(plan, text=text)
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance(plan, text=text)
    cache[text] = result
    return result


def _query_relevance_from_item_diagnostics(
    plan: QueryExpansionPlan,
    item: ContextItem,
) -> tuple[str, str, QueryRelevance] | None:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    reason_value = signals.get("query_expansion_reason") or diagnostics.get(
        "query_expansion_reason"
    )
    if not isinstance(reason_value, str) or not reason_value:
        return None
    query_text = _query_text_for_expansion_reason(plan, reason_value)
    if query_text is None:
        return None
    relevance = _query_relevance_from_score_signals(signals)
    if relevance is None:
        return None
    return query_text, reason_value, relevance


def _query_text_for_expansion_reason(
    plan: QueryExpansionPlan,
    reason: str,
) -> str | None:
    for expansion in plan.retrieval_queries:
        if expansion.reason == reason:
            return expansion.query
    return None


def _query_relevance_from_score_signals(
    signals: Mapping[str, object],
) -> QueryRelevance | None:
    query_term_count = _non_negative_int_signal(signals.get("query_term_count"))
    unique_term_hits = _non_negative_int_signal(signals.get("unique_term_hits"))
    capped_frequency_hits = _non_negative_int_signal(signals.get("capped_frequency_hits"))
    distinctive_term_count = _non_negative_int_signal(signals.get("distinctive_term_count"))
    distinctive_term_hits = _non_negative_int_signal(signals.get("distinctive_term_hits"))
    phrase_bigram_count = _non_negative_int_signal(signals.get("phrase_bigram_count"))
    phrase_bigram_hits = _non_negative_int_signal(signals.get("phrase_bigram_hits"))
    if (
        query_term_count is None
        or unique_term_hits is None
        or capped_frequency_hits is None
        or distinctive_term_count is None
        or distinctive_term_hits is None
        or phrase_bigram_count is None
        or phrase_bigram_hits is None
    ):
        return None
    hit_ratio = _non_negative_float_signal(signals.get("hit_ratio"))
    score_boost = _non_negative_float_signal(signals.get("query_relevance_boost"))
    phrase_boost = _non_negative_float_signal(signals.get("phrase_boost"))
    if hit_ratio is None or score_boost is None or phrase_boost is None:
        return None
    return QueryRelevance(
        score_boost=score_boost,
        query_term_count=query_term_count,
        unique_term_hits=unique_term_hits,
        capped_frequency_hits=capped_frequency_hits,
        hit_ratio=hit_ratio,
        distinctive_term_count=distinctive_term_count,
        distinctive_term_hits=distinctive_term_hits,
        phrase_bigram_count=phrase_bigram_count,
        phrase_bigram_hits=phrase_bigram_hits,
        phrase_boost=phrase_boost,
    )


def _non_negative_int_signal(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return None


def _non_negative_float_signal(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return None


def _allergy_condition_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "allergy_condition_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def _patriotic_service_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "patriotic_service_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def _running_reason_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return query_reason == "running_reason_bridge" and relevance.distinctive_term_hits < 3


def _temporal_query_signal_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "temporal_query_intent_applied")


def _item_temporal_hint_code(item: ContextItem) -> str:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return temporal_hint_code_from_metadata(diagnostics, provenance)


def _temporal_answer_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> tuple[float, float, str]:
    if not _TEMPORAL_ANSWER_QUERY_RE.search(query):
        return 0.0, 0.0, ""
    if (
        query_reason == "item_purchase_bridge"
        and not _is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        return 0.0, 0.012, "temporal_answer_evidence_missing"
    if _item_has_temporal_answer_evidence(item):
        return 0.026, 0.0, "temporal_answer_evidence"
    return 0.0, 0.012, "temporal_answer_evidence_missing"


def _is_item_purchase_temporal_answer_evidence(
    *,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "item_purchase_bridge":
        return False
    return has_item_purchase_object_evidence(item.text)


def _item_has_temporal_answer_evidence(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    for metadata in (diagnostics, provenance):
        if any(
            metadata.get(key)
            for key in (
                "temporal_hint_code",
                "event_temporal_hint_code",
                "event_valid_from",
                "event_valid_to",
                "valid_from",
                "valid_to",
            )
        ):
            return True
    if any(
        ref.time_start_ms is not None
        or ref.time_end_ms is not None
        or _TEMPORAL_ANSWER_EVIDENCE_RE.search(ref.quote_preview or "")
        for ref in item.source_refs
    ):
        return True
    return bool(_TEMPORAL_ANSWER_EVIDENCE_RE.search(item.text))


def _event_participation_mismatch(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    if _SELF_MISSED_EVENT_TEXT_RE.search(text):
        return True
    if not _MISSED_EVENT_TEXT_RE.search(text):
        return False
    return not _POSITIVE_EVENT_TEXT_RE.search(text)


def _event_participation_positive_match(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    return bool(_POSITIVE_EVENT_PARTICIPATION_TEXT_RE.search(text))


def _event_participation_source_sibling_noise(*, query: str, item: ContextItem) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    if str(signals.get("source_sibling_dialogue_visual_reference") or "").casefold() in {
        "1",
        "true",
    }:
        return False
    return not _POSITIVE_EVENT_TEXT_RE.search(item.text)


def _activity_source_sibling_noise(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    reason = str(signals.get("query_expansion_reason") or "").strip()
    if reason not in _ACTIVITY_OBSERVATION_SOURCE_REASONS.union(_ACTIVITY_OWNER_REASONS):
        return False
    return not _POSITIVE_ACTIVITY_TEXT_RE.search(item.text)


def _capped_source_sibling_low_signal(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    return _positive_signal(signals.get("source_sibling_score_cap_applied"))


def _volunteer_career_weak_evidence(
    *,
    query_anchor_intent: QueryAnchorIntent,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is None:
        return True
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return False
    speakers = _dialogue_speaker_labels(item.text)
    return bool(speakers and not speakers.intersection(query_people))


def _volunteer_career_exact_turn_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _volunteer_career_broad_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _item_source_is_turn(item):
        return False
    if _VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE.search(item.text) is not None:
        return False
    return _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is not None


def _post_event_activity_timing_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    if _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _post_event_activity_timing_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    return _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None


def _is_post_event_activity_timing_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="post_event_activity_timing_bridge",
    )


def _shoe_usage_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    if _SHOE_USAGE_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _shoe_usage_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    return _SHOE_USAGE_CONTEXT_RE.search(item.text) is None


def _is_shoe_usage_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="shoe_usage_bridge",
    )


def _matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    if query_reason == target_reason:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return str(signals.get("query_expansion_reason") or "") == target_reason


def _item_source_is_turn(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    source_id = str(diagnostics.get("source_id") or "").strip()
    if not source_id:
        provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
        source_id = str(provenance.get("source_id") or "").strip()
    if source_id:
        return source_id.casefold().endswith(":turn")
    return any(_source_ref_is_turn(ref) for ref in item.source_refs)


def _source_ref_is_turn(ref: SourceRef) -> bool:
    return str(ref.source_id).casefold().endswith(":turn")


def _action_role_confirms_requested_relation(reason: str) -> bool:
    return reason in {
        "action_role_actor_recipient_match",
        "action_role_actor_to_recipient_evidence",
        "action_role_information_source_evidence",
        "action_role_recipient_match",
    }


def _dialogue_speaker_confirms_query_anchor(
    *,
    item: ContextItem,
    query_anchor_intent: QueryAnchorIntent,
    relevance: QueryRelevance,
) -> bool:
    sources = diagnostic_retrieval_sources(item.diagnostics)
    if "keyword_source_sibling_chunks" in sources:
        signals = safe_score_signals(
            safe_diagnostic_mapping(item.diagnostics).get("score_signals")
        )
        if not _positive_signal(signals.get("source_sibling_group_level_seed")):
            return False
        if _numeric_signal(signals.get("query_expansion_reason_priority")) < 3:
            return False
    if relevance.distinctive_term_hits < 4 or relevance.unique_term_hits < 4:
        return False
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return False
    speakers = _dialogue_speaker_labels(item.text)
    return bool(speakers.intersection(query_people))


def _positive_signal(value: object) -> bool:
    return _numeric_signal(value) > 0


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _activity_owner_signal(
    *,
    query_anchor_intent: QueryAnchorIntent,
    query_reason: str,
    text: str,
) -> tuple[float, float, str]:
    if query_reason not in _ACTIVITY_OWNER_REASONS:
        return 0.0, 0.0, ""
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return 0.0, 0.0, ""
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return 0.0, 0.0, ""
    if speakers.intersection(query_people):
        return _ACTIVITY_OWNER_MATCH_BOOST, 0.0, "activity_owner_speaker_match"
    return 0.0, _ACTIVITY_OWNER_MISMATCH_PENALTY, "activity_owner_speaker_mismatch"


def _query_person_labels(query_anchor_intent: QueryAnchorIntent) -> frozenset[str]:
    labels: set[str] = set()
    for hint in query_anchor_intent.hints:
        if hint.kind != MemoryAnchorKind.PERSON:
            continue
        label = _normalized_dialogue_label(hint.label)
        if label:
            labels.add(label)
        canonical = _normalized_dialogue_label(hint.canonical_key)
        if canonical:
            labels.add(canonical)
    return frozenset(labels)


def _dialogue_speaker_labels(text: str) -> frozenset[str]:
    return frozenset(
        label
        for label in (
            _normalized_dialogue_label(match.group("speaker"))
            for match in _DIALOGUE_SPEAKER_RE.finditer(text)
        )
        if label
    )


def _normalized_dialogue_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _coverage_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _deterministic_rerank_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "deterministic_rerank_applied")


def _deterministic_rerank_already_applied_in_diagnostics(
    diagnostics: object,
) -> bool:
    return _provenance_flag_is_true(
        diagnostics,
        "deterministic_rerank_applied",
        normalized=True,
    )


def _provenance_flag_is_true(
    diagnostics: object,
    flag: str,
    *,
    normalized: bool = False,
) -> bool:
    diagnostics = (
        safe_diagnostic_mapping(diagnostics)
        if normalized
        else normalize_context_diagnostics(diagnostics)
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get(flag) is True
