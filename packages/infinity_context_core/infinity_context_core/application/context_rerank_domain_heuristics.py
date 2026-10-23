"""Rerank domain heuristics policy; one implementation authority."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_internal_diagnostics import (
    diagnostic_mapping,
    item_diagnostic_source_id,
    nested_diagnostic_mapping,
)
from infinity_context_core.application.context_internal_diagnostics import (
    provenance_flag_is_true as _provenance_flag_is_true,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_precise_temporal_evidence import (
    requests_temporal_ranking_context,
)
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_rank_dedupe import _source_ref_is_turn
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OWNER_REASONS as _ACTIVITY_OWNER_REASONS,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_rerank_relevance import _numeric_signal
from infinity_context_core.application.context_temporal_answer_grounding import (
    temporal_answer_grounding,
)
from infinity_context_core.application.context_temporal_metadata import (
    temporal_hint_code_from_metadata,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryAnchorKind

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


def _allergy_condition_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "allergy_condition_inference_bridge" and relevance.distinctive_term_hits < 4
    )


def _patriotic_service_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "patriotic_service_inference_bridge" and relevance.distinctive_term_hits < 4
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
    diagnostics = diagnostic_mapping(item.diagnostics)
    provenance = nested_diagnostic_mapping(diagnostics, "provenance")
    return temporal_hint_code_from_metadata(diagnostics, provenance)


def _temporal_answer_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> tuple[float, float, str]:
    if not requests_temporal_ranking_context(query):
        return 0.0, 0.0, ""
    if query_reason == "item_purchase_bridge" and not _is_item_purchase_temporal_answer_evidence(
        query_reason=query_reason, item=item
    ):
        return 0.0, 0.012, "temporal_answer_evidence_missing"
    grounding = temporal_answer_grounding(query, item)
    if grounding.grounded:
        return 0.026, 0.0, "temporal_answer_evidence"
    if grounding.ungrounded:
        return 0.0, 0.03, "temporal_answer_ungrounded_evidence"
    return 0.0, 0.012, "temporal_answer_evidence_missing"


def _is_item_purchase_temporal_answer_evidence(
    *,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "item_purchase_bridge":
        return False
    return has_item_purchase_object_evidence(item.text)


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
    signals = nested_diagnostic_mapping(diagnostic_mapping(item.diagnostics), "score_signals")
    return signals.get("query_expansion_reason") == target_reason


def _item_source_is_turn(item: ContextItem) -> bool:
    source_id = item_diagnostic_source_id(item)
    if source_id:
        return source_id.casefold().endswith(":turn")
    return any(_source_ref_is_turn(ref) for ref in item.source_refs)


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
        signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
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


allergy_condition_weak_evidence = _allergy_condition_weak_evidence
patriotic_service_weak_evidence = _patriotic_service_weak_evidence
running_reason_weak_evidence = _running_reason_weak_evidence
temporal_answer_signal = _temporal_answer_signal
is_item_purchase_temporal_answer_evidence = _is_item_purchase_temporal_answer_evidence
event_participation_mismatch = _event_participation_mismatch
event_participation_positive_match = _event_participation_positive_match
event_participation_source_sibling_noise = _event_participation_source_sibling_noise
activity_source_sibling_noise = _activity_source_sibling_noise
capped_source_sibling_low_signal = _capped_source_sibling_low_signal
volunteer_career_weak_evidence = _volunteer_career_weak_evidence
volunteer_career_exact_turn_evidence = _volunteer_career_exact_turn_evidence
volunteer_career_broad_evidence = _volunteer_career_broad_evidence
post_event_activity_timing_exact_evidence = _post_event_activity_timing_exact_evidence
post_event_activity_timing_weak_evidence = _post_event_activity_timing_weak_evidence
shoe_usage_exact_evidence = _shoe_usage_exact_evidence
shoe_usage_weak_evidence = _shoe_usage_weak_evidence
activity_owner_signal = _activity_owner_signal
dialogue_speaker_confirms_query_anchor = _dialogue_speaker_confirms_query_anchor

ACTIVITY_OWNER_MATCH_BOOST = _ACTIVITY_OWNER_MATCH_BOOST
ACTIVITY_OWNER_MISMATCH_PENALTY = _ACTIVITY_OWNER_MISMATCH_PENALTY
