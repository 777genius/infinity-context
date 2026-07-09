"""Domain-specific deterministic rerank heuristics."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS,
    ACTIVITY_OWNER_REASONS,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryAnchorKind, SourceRef

ACTIVITY_OWNER_MATCH_BOOST = 0.012
ACTIVITY_OWNER_MISMATCH_PENALTY = 0.042
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
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}(?:,?\s+\d{2,4})?\b|"
    r"\b(?:jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\.\s+\d{1,2}(?:,?\s+\d{2,4})?\b",
    re.IGNORECASE,
)
_MISSED_EVENT_TEXT_RE = re.compile(r"\bmissed\s+(?:it|the|that)?\b", re.IGNORECASE)
_SELF_MISSED_EVENT_TEXT_RE = re.compile(r"\b(?:i|we)\s+missed\s+(?:it|the|that)?\b", re.IGNORECASE)
_POSITIVE_EVENT_TEXT_RE = re.compile(
    r"\b(?:attended|went|joined|participated|partook|took\s+part|was\s+at|"
    r"showed\s+up|helped|volunteered|hosted|organized|performed)\b",
    re.IGNORECASE,
)
_POSITIVE_EVENT_PARTICIPATION_TEXT_RE = re.compile(
    r"\b(?:attended|went|joined|participated|partook|took\s+part|was\s+at|"
    r"showed\s+up|helped|volunteered|hosted|organized|performed)\b",
    re.IGNORECASE,
)
_POSITIVE_ACTIVITY_TEXT_RE = re.compile(
    r"\b(?:did|went|joined|participated|completed|ran|hiked|walked|swam|"
    r"played|practiced|trained|attended|visited|watched|saw|painted|made|"
    r"built|cooked|baked|gardened|camped|traveled|volunteered)\b",
    re.IGNORECASE,
)
_SPEAKER_LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_SPEAKER_LABEL_RE}):",
    re.IGNORECASE,
)


def allergy_condition_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "allergy_condition_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def patriotic_service_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "patriotic_service_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def running_reason_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return query_reason == "running_reason_bridge" and relevance.distinctive_term_hits < 3


def temporal_answer_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> tuple[float, float, str]:
    if not _TEMPORAL_ANSWER_QUERY_RE.search(query):
        return 0.0, 0.0, ""
    if (
        query_reason == "item_purchase_bridge"
        and not is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        return 0.0, 0.012, "temporal_answer_evidence_missing"
    if _item_has_temporal_answer_evidence(item):
        return 0.026, 0.0, "temporal_answer_evidence"
    return 0.0, 0.012, "temporal_answer_evidence_missing"


def is_item_purchase_temporal_answer_evidence(
    *,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "item_purchase_bridge":
        return False
    return has_item_purchase_object_evidence(item.text)


def event_participation_mismatch(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    if _SELF_MISSED_EVENT_TEXT_RE.search(text):
        return True
    if not _MISSED_EVENT_TEXT_RE.search(text):
        return False
    return not _POSITIVE_EVENT_TEXT_RE.search(text)


def event_participation_positive_match(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    return bool(_POSITIVE_EVENT_PARTICIPATION_TEXT_RE.search(text))


def event_participation_source_sibling_noise(*, query: str, item: ContextItem) -> bool:
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


def activity_source_sibling_noise(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    reason = str(signals.get("query_expansion_reason") or "").strip()
    if reason not in ACTIVITY_OBSERVATION_SOURCE_REASONS.union(ACTIVITY_OWNER_REASONS):
        return False
    return not _POSITIVE_ACTIVITY_TEXT_RE.search(item.text)


def capped_source_sibling_low_signal(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    return _positive_signal(signals.get("source_sibling_score_cap_applied"))


def volunteer_career_weak_evidence(
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


def volunteer_career_exact_turn_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def volunteer_career_broad_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _item_source_is_turn(item):
        return False
    if _VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE.search(item.text) is not None:
        return False
    return _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is not None


def post_event_activity_timing_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    if _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def post_event_activity_timing_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    return _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None


def shoe_usage_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    if _SHOE_USAGE_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def shoe_usage_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    return _SHOE_USAGE_CONTEXT_RE.search(item.text) is None


def activity_owner_signal(
    *,
    query_anchor_intent: QueryAnchorIntent,
    query_reason: str,
    text: str,
) -> tuple[float, float, str]:
    if query_reason not in ACTIVITY_OWNER_REASONS:
        return 0.0, 0.0, ""
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return 0.0, 0.0, ""
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return 0.0, 0.0, ""
    if speakers.intersection(query_people):
        return ACTIVITY_OWNER_MATCH_BOOST, 0.0, "activity_owner_speaker_match"
    return 0.0, ACTIVITY_OWNER_MISMATCH_PENALTY, "activity_owner_speaker_mismatch"


def dialogue_speaker_confirms_query_anchor(
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


def _is_post_event_activity_timing_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="post_event_activity_timing_bridge",
    )


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


def _positive_signal(value: object) -> bool:
    return _numeric_signal(value) > 0


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0
