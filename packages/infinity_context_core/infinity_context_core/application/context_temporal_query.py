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
from infinity_context_core.application.context_lexical import date_tokens, query_terms
from infinity_context_core.application.context_query_state_transition import (
    state_transition_query_variants,
)
from infinity_context_core.application.context_state_evidence import state_evidence_markers
from infinity_context_core.application.context_temporal_hints import temporal_hint_codes
from infinity_context_core.application.context_temporal_metadata import (
    temporal_hint_code_from_metadata,
)
from infinity_context_core.application.context_temporal_session_order import (
    temporal_session_earliest_boost,
    temporal_session_orders,
    temporal_session_orders_from_query,
    temporal_session_recency_boost,
)
from infinity_context_core.application.dto import ContextItem

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_EXCLUDE_STALE_RE = re.compile(
    r"\b(?:not\s+(?:stale|old|outdated|obsolete|deprecated|expired)|"
    r"ignore\s+(?:stale|old|outdated|obsolete|deprecated|expired)|"
    r"do\s+not\s+(?:use|include)\s+"
    r"(?:stale|old|outdated|obsolete|deprecated|expired))\b|"
    r"(?:устаревш\w*\s+не\s+учитывать|не\s+учитывать\s+устаревш\w*)",
    re.IGNORECASE,
)
_AGE_QUERY_RE = re.compile(r"\bhow\s+old\b", re.IGNORECASE)
_OLD_SOCIAL_RELATION_RE = re.compile(
    r"\bold\s+(?:friend|friends|buddy|buddies|classmate|classmates|"
    r"roommate|roommates|colleague|colleagues|coworker|coworkers|"
    r"teammate|teammates)\b",
    re.IGNORECASE,
)
_OLD_PREVIOUS_STATE_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+(?:was|were|is|are)\s+(?:the\s+)?old\b",
    re.IGNORECASE,
)
_PREVIOUS_RELATIVE_TIME_RE = re.compile(
    r"\b(?:previous|prior)\s+"
    r"(?:day|night|morning|afternoon|evening|week|weekend|month|quarter|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_ORDERED_EVENT_REQUEST_RE = re.compile(
    r"\b(?:last|previous|prior|next|upcoming)\s+"
    r"(?:conversation|call|meeting|chat|dm|message|discussion|sync|review|demo|"
    r"interview|workshop|session)\b|"
    r"\b(?:последн\w*|предыдущ\w*|следующ\w*)\s+"
    r"(?:разговор\w*|созвон\w*|встреч\w*|переписк\w*|чат\w*|"
    r"обсуждени\w*|ревью)\b",
    re.IGNORECASE,
)
_UPCOMING_EVENT_REQUEST_RE = re.compile(
    r"\b(?:next|upcoming)\s+"
    r"(?:conversation|call|meeting|chat|dm|message|discussion|sync|review|demo|"
    r"interview|workshop|session)\b|"
    r"\b(?:следующ\w*|предстоящ\w*)\s+"
    r"(?:разговор\w*|созвон\w*|встреч\w*|переписк\w*|чат\w*|"
    r"обсуждени\w*|ревью)\b",
    re.IGNORECASE,
)
_CURRENT_PHRASE_RE = re.compile(
    r"\b(?:right\s+now|as\s+of\s+now|at\s+the\s+moment|for\s+now)\b|"
    r"\b(?:прямо\s+сейчас|на\s+данный\s+момент|в\s+данный\s+момент)\b",
    re.IGNORECASE,
)
_RECENT_EVENT_REQUEST_RE = re.compile(
    r"\b(?:latest|newest|recent|most\s+recent|last|previous|prior)\s+"
    r"(?:conversation|call|meeting|chat|dm|message|discussion|sync|review|demo|"
    r"interview|workshop|session)\b|"
    r"\b(?:последн\w*|недавн\w*|свеж\w*)\s+"
    r"(?:разговор\w*|созвон\w*|встреч\w*|переписк\w*|чат\w*|"
    r"обсуждени\w*)\b",
    re.IGNORECASE,
)
_EARLIEST_EVENT_REQUEST_RE = re.compile(
    r"\b(?:first|earliest|oldest|initial)\s+"
    r"(?:conversation|call|meeting|chat|dm|message|discussion|sync|review|demo|"
    r"interview|workshop|session)\b|"
    r"\b(?:conversation|call|meeting|chat|dm|message|discussion|sync|review|demo|"
    r"interview|workshop|session)\b"
    r"(?=.{0,60}\b(?:first|earliest|oldest|initial)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_RECOMMENDATION_RE = re.compile(
    r"\bshould\s+(?:(?:i|we)\s+)?(?:use|choose|pick)\b|"
    r"\b(?:recommended|preferred|best)\s+"
    r"(?:provider|tool|model|option|engine|database|service)\b|"
    r"\b(?:provider|tool|model|option|engine|database|service)\b"
    r"(?=.{0,50}\b(?:recommended|preferred|best)\b)|"
    r"\b(?:какой|какую|какое|какие)\s+"
    r"(?:провайдер|инструмент|модель|вариант|движок|сервис)\b"
    r"(?=.{0,60}\b(?:использовать|выбрать|лучше|рекоменд))",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_DECISION_RE = re.compile(
    r"\b(?:provider|tool|model|option|engine|database|service)\b"
    r"(?=.{0,70}\b(?:decid(?:e|ed)|chose|chosen|choose|picked|selected|use)\b)|"
    r"\b(?:decid(?:e|ed)|chose|chosen|choose|picked|selected)\b"
    r"(?=.{0,70}\b(?:provider|tool|model|option|engine|database|service)\b)|"
    r"\b(?:final|canonical|source\s+of\s+truth|settled)\b"
    r"(?=.{0,90}\b(?:decision|provider|tool|model|option|plan|policy|source)\b)|"
    r"\b(?:decision|provider|tool|model|option|plan|policy|source)\b"
    r"(?=.{0,90}\b(?:final|canonical|source\s+of\s+truth|settled)\b)|"
    r"\b(?:провайдер|инструмент|модель|вариант|движок|сервис)\b"
    r"(?=.{0,70}\b(?:решил\w*|выбрал\w*|использовать)\b)|"
    r"\b(?:решил\w*|выбрал\w*)\b"
    r"(?=.{0,70}\b(?:провайдер|инструмент|модель|вариант|движок|сервис)\b)|"
    r"\b(?:финальн\w*|окончательн\w*|выбранн\w*)\b"
    r"(?=.{0,90}\b(?:решени\w*|провайдер|инструмент|модель|вариант|план)\b)|"
    r"\b(?:решени\w*|провайдер|инструмент|модель|вариант|план)\b"
    r"(?=.{0,90}\b(?:финальн\w*|окончательн\w*|выбранн\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_DECISION_PROMPT_RE = re.compile(
    r"\b(?:what|which)\b"
    r"(?=.{0,90}\b(?:decid(?:e|ed)|chose|chosen|choose|picked|selected)\b)"
    r"(?=.{0,110}\b(?:use|choose|pick|select|selected|choice|option)\b)|"
    r"\b(?:что|какой|какую|какое|какие)\b"
    r"(?=.{0,90}\b(?:решил\w*|выбрал\w*)\b)"
    r"(?=.{0,110}\b(?:использовать|выбрать|вариант)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STILL_CURRENT_STATE_RE = re.compile(
    r"\b(?:still|remain(?:s|ed)?|kept)\b"
    r"(?=.{0,80}\b(?:valid|active|current|recommended|preferred|use|using|"
    r"works?|available|chosen|selected|option|plan|provider|tool|model|policy)\b)|"
    r"\b(?:valid|active|current|recommended|preferred|available|chosen|selected)\b"
    r"(?=.{0,80}\b(?:still|remain(?:s|ed)?)\b)|"
    r"\b(?:все\s+еще|всё\s+ещ[её]|по-прежнему|остается|остался|осталась|остались)\b"
    r"(?=.{0,80}\b(?:актуал|действует|валидн|использовать|выбран|вариант|"
    r"план|провайдер|инструмент|модель|политик)\w*)",
    re.IGNORECASE | re.DOTALL,
)
_NO_LONGER_CURRENT_STATE_RE = re.compile(
    r"\b(?:no\s+longer|anymore|any\s+longer|stopped)\b"
    r"(?=.{0,80}\b(?:valid|active|current|recommended|preferred|use|using|"
    r"works?|available|chosen|selected|option|plan|provider|tool|model|policy)\b)|"
    r"\b(?:valid|active|current|recommended|preferred|available|chosen|selected)\b"
    r"(?=.{0,80}\b(?:no\s+longer|anymore|any\s+longer)\b)|"
    r"\b(?:больше\s+не|уже\s+не|перестал\w*)\b"
    r"(?=.{0,80}\b(?:актуал|действует|валидн|использовать|выбран|вариант|"
    r"план|провайдер|инструмент|модель|политик)\w*)",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_TERMS = frozenset(
    {
        "active",
        "actual",
        "актуальн",
        "актуально",
        "current",
        "currently",
        "действует",
        "latest",
        "newest",
        "now",
        "nowadays",
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
        "deprecated",
        "earlier",
        "expired",
        "initial",
        "obsolete",
        "old",
        "outdated",
        "previous",
        "prior",
        "stale",
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
_DURING_TERMS = frozenset({"during", "while"})
_EVENT_SEQUENCE_CONTEXT_TERMS = frozenset(
    {
        "call",
        "chat",
        "conversation",
        "demo",
        "dm",
        "interview",
        "interviews",
        "meeting",
        "message",
        "messaged",
        "messaging",
        "meetup",
        "review",
        "roadtrip",
        "speak",
        "speaking",
        "spoke",
        "sync",
        "trip",
        "talk",
        "talked",
        "talking",
        "texted",
        "texting",
        "workshop",
        "встреча",
        "демо",
        "интервью",
        "митап",
        "переписк",
        "переписка",
        "поездка",
        "разговор",
        "разговора",
        "разговоре",
        "разговором",
        "ревью",
        "роудтрип",
        "созвон",
        "чат",
    }
)
_EVENT_SEQUENCE_ANCHOR_STOP_VARIANTS = frozenset(
    {
        *_AFTER_TERMS,
        *_BEFORE_TERMS,
        *_CHANGE_TERMS,
        *_CURRENT_TERMS,
        *_DURING_TERMS,
        *_EVENT_SEQUENCE_CONTEXT_TERMS,
        *_PREVIOUS_TERMS,
        "about",
        "and",
        "did",
        "does",
        "during",
        "for",
        "from",
        "happen",
        "happened",
        "has",
        "have",
        "into",
        "over",
        "that",
        "the",
        "then",
        "this",
        "what",
        "when",
        "which",
        "with",
        "без",
        "было",
        "был",
        "была",
        "были",
        "для",
        "как",
        "какой",
        "какую",
        "какие",
        "котор",
        "момент",
        "над",
        "после",
        "при",
        "про",
        "что",
    }
)
_SINCE_EVENT_RE = re.compile(
    r"\b(?:since|right\s+after|immediately\s+after|shortly\s+after)\b|"
    r"\b(?:с\s+момента|сразу\s+после|прямо\s+после)\b",
    re.IGNORECASE,
)
_UNTIL_EVENT_RE = re.compile(
    r"\b(?:until|up\s+to|right\s+before|immediately\s+before|shortly\s+before)\b|"
    r"\b(?:вплоть\s+до|сразу\s+до|прямо\s+перед)\b",
    re.IGNORECASE,
)
_DURING_EVENT_RE = re.compile(
    r"\b(?:during|while)\b|"
    r"\b(?:во\s+время|в\s+ходе)\b",
    re.IGNORECASE,
)
_EVENT_SEQUENCE_ANCHOR_RE = re.compile(
    r"\b(?:right\s+after|immediately\s+after|shortly\s+after|after|following|since|"
    r"right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to|until|"
    r"up\s+to|during|while)\b\s+(?P<tail>[^?.!,;:\n]{0,96})|"
    r"\b(?:с\s+момента|сразу\s+после|прямо\s+после|после|позже|затем|"
    r"вплоть\s+до|сразу\s+до|прямо\s+перед|перед|раньше|до|во\s+время|в\s+ходе)\b"
    r"\s+(?P<ru_tail>[^?.!,;:\n]{0,96})",
    re.IGNORECASE,
)
_LAST_WEEK_CHILD_HINTS = frozenset(
    {
        "last_monday",
        "last_tuesday",
        "last_wednesday",
        "last_thursday",
        "last_friday",
        "last_saturday",
        "last_sunday",
        "last_weekend",
    }
)
_CURRENT_DAY_CHILD_HINTS = frozenset(
    {
        "earlier_today",
        "hour_ago",
        "hours_ago",
        "today_afternoon",
        "today_evening",
        "today_morning",
    }
)
_THIS_WEEK_CHILD_HINTS = frozenset(
    {
        *_CURRENT_DAY_CHILD_HINTS,
        "days_ago",
        "last_night",
        "this_weekend",
        "today",
        "yesterday",
    }
)
_THIS_MONTH_CHILD_HINTS = frozenset(
    {
        *_THIS_WEEK_CHILD_HINTS,
        "this_week",
    }
)
_THIS_QUARTER_CHILD_HINTS = frozenset(
    {
        *_THIS_MONTH_CHILD_HINTS,
        "this_month",
    }
)
_THIS_YEAR_CHILD_HINTS = frozenset(
    {
        *_THIS_QUARTER_CHILD_HINTS,
        *_LAST_WEEK_CHILD_HINTS,
        "last_month",
        "last_week",
        "months_ago",
        "this_quarter",
        "weekends_ago",
        "weeks_ago",
    }
)
_TEMPORAL_HINT_CHILDREN: Mapping[str, frozenset[str]] = {
    "this_month": _THIS_MONTH_CHILD_HINTS,
    "this_quarter": _THIS_QUARTER_CHILD_HINTS,
    "this_week": _THIS_WEEK_CHILD_HINTS,
    "this_year": _THIS_YEAR_CHILD_HINTS,
    "today": _CURRENT_DAY_CHILD_HINTS,
    "last_week": _LAST_WEEK_CHILD_HINTS,
    "weeks_ago": frozenset({"weekends_ago"}),
}
_TEMPORAL_HINT_PARENTS: Mapping[str, str] = {
    child: parent for parent, children in _TEMPORAL_HINT_CHILDREN.items() for child in children
}


@dataclass(frozen=True)
class TemporalQueryIntent:
    prefers_current: bool
    requests_previous: bool
    requests_change: bool
    after_event: bool
    before_event: bool
    during_event: bool
    requests_upcoming: bool
    requests_recent_event: bool
    requests_earliest_event: bool
    excludes_stale: bool
    session_ordinals: tuple[int, ...] = ()
    relative_time_hints: tuple[str, ...] = ()
    event_sequence_terms: tuple[str, ...] = ()

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
                self.during_event,
                self.requests_upcoming,
                self.requests_recent_event,
                self.requests_earliest_event,
                self.excludes_stale,
                self.session_ordinals,
                self.relative_time_hints,
                self.event_sequence_terms,
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
        if self.during_event:
            reasons.append("during_event")
        if self.requests_upcoming:
            reasons.append("requests_upcoming")
        if self.requests_recent_event:
            reasons.append("requests_recent_event")
        if self.requests_earliest_event:
            reasons.append("requests_earliest_event")
        if self.excludes_stale:
            reasons.append("excludes_stale")
        if self.session_ordinals:
            reasons.append("session_order_hint")
        if self.relative_time_hints:
            reasons.append("relative_time_hint")
        return {
            "temporal_query_intent_status": "empty" if self.empty else "available",
            "temporal_query_prefers_current": self.prefers_current,
            "temporal_query_requests_previous": self.requests_previous,
            "temporal_query_requests_change": self.requests_change,
            "temporal_query_after_event": self.after_event,
            "temporal_query_before_event": self.before_event,
            "temporal_query_during_event": self.during_event,
            "temporal_query_requests_upcoming": self.requests_upcoming,
            "temporal_query_requests_recent_event": self.requests_recent_event,
            "temporal_query_requests_earliest_event": self.requests_earliest_event,
            "temporal_query_excludes_stale": self.excludes_stale,
            "temporal_query_include_superseded_review": (self.include_superseded_review),
            "temporal_query_session_ordinals": list(self.session_ordinals),
            "temporal_query_relative_time_hints": list(self.relative_time_hints),
            "temporal_query_event_sequence_terms": list(self.event_sequence_terms),
            "temporal_query_intent_reasons": reasons,
        }


@dataclass(frozen=True)
class TemporalQueryBoostSignal:
    boost: float = 0.0
    reason: str = ""
    code: str = ""

    @property
    def empty(self) -> bool:
        return self.boost == 0.0


def build_temporal_query_intent(query: str) -> TemporalQueryIntent:
    variants = _query_variant_set(query)
    variants = frozenset((*variants, *state_transition_query_variants(query)))
    session_ordinals = temporal_session_orders_from_query(query)
    relative_time_hints = _query_temporal_hint_codes(query)
    excludes_stale = bool(_EXCLUDE_STALE_RE.search(query))
    still_current_state = bool(_STILL_CURRENT_STATE_RE.search(query))
    no_longer_current_state = bool(_NO_LONGER_CURRENT_STATE_RE.search(query))
    requests_change = bool(
        variants.intersection(_CHANGE_TERMS) or "state_transition_request" in variants
    )
    previous_terms = variants.intersection(_PREVIOUS_TERMS)
    if _PREVIOUS_RELATIVE_TIME_RE.search(query):
        previous_terms = previous_terms.difference({"previous", "prior"})
    if _ORDERED_EVENT_REQUEST_RE.search(query):
        previous_terms = previous_terms.difference({"previous", "prior"})
    if (
        _AGE_QUERY_RE.search(query)
        or _OLD_SOCIAL_RELATION_RE.search(query)
        or not _OLD_PREVIOUS_STATE_QUERY_RE.search(query)
    ):
        previous_terms = previous_terms.difference({"old"})
    requests_upcoming = bool(_UPCOMING_EVENT_REQUEST_RE.search(query))
    requests_earliest_event = bool(_EARLIEST_EVENT_REQUEST_RE.search(query))
    requests_recent_event = (
        bool(_RECENT_EVENT_REQUEST_RE.search(query)) and not requests_upcoming
    )
    requests_previous = (bool(previous_terms) or no_longer_current_state) and not excludes_stale
    prefers_current = (
        excludes_stale
        or still_current_state
        or bool(variants.intersection(_CURRENT_TERMS))
        or bool(_CURRENT_PHRASE_RE.search(query))
        or (requests_recent_event and not requests_earliest_event)
        or bool(_CURRENT_RECOMMENDATION_RE.search(query))
        or (requests_change and not requests_previous)
    ) and not no_longer_current_state
    after_event = _has_after_event_context(
        query,
        variants,
    ) or _has_since_relative_time_context(query, relative_time_hints)
    before_event = _has_before_event_context(
        query,
        variants,
    ) or _has_until_relative_time_context(query, relative_time_hints)
    during_event = _has_during_event_context(query, variants)
    event_sequence_terms = (
        _event_sequence_anchor_terms(query)
        if after_event or before_event or during_event
        else ()
    )
    current_decision = (
        bool(_CURRENT_DECISION_RE.search(query))
        or bool(_CURRENT_DECISION_PROMPT_RE.search(query))
    ) and not (
        after_event
        or before_event
        or during_event
        or bool(relative_time_hints)
        or requests_previous
        or requests_earliest_event
    )
    prefers_current = prefers_current or current_decision
    return TemporalQueryIntent(
        prefers_current=prefers_current,
        requests_previous=requests_previous,
        requests_change=requests_change,
        after_event=after_event,
        before_event=before_event,
        during_event=during_event,
        requests_upcoming=requests_upcoming,
        requests_recent_event=requests_recent_event,
        requests_earliest_event=requests_earliest_event,
        excludes_stale=excludes_stale,
        session_ordinals=session_ordinals,
        relative_time_hints=relative_time_hints,
        event_sequence_terms=event_sequence_terms,
    )


def _query_temporal_hint_codes(query: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for code in (*temporal_hint_codes(query), *date_tokens(query)):
        if code not in seen:
            seen[code] = None
    return tuple(seen)


def apply_temporal_query_intent_boosts(
    items: tuple[ContextItem, ...],
    *,
    intent: TemporalQueryIntent,
) -> tuple[ContextItem, ...]:
    if intent.empty:
        return items
    return tuple(_apply_temporal_query_intent(item, intent=intent) for item in items)


def temporal_query_boost_signal(
    item: ContextItem,
    *,
    intent: TemporalQueryIntent,
) -> TemporalQueryBoostSignal:
    if intent.empty:
        return TemporalQueryBoostSignal()
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    state_markers = state_evidence_markers(item)
    retrieval_source = str(diagnostics.get("retrieval_source") or "")
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    fact_status = str(provenance.get("fact_status") or diagnostics.get("fact_status") or "")
    is_review_only = state_markers.review_only
    is_superseded = (
        retrieval_source == "superseded_review"
        or fact_status == "superseded"
        or state_markers.metadata_stale
    )
    has_temporal_relation = bool(diagnostics.get("temporal_relations"))
    temporal_hint_code = _temporal_hint_code(diagnostics, provenance)
    if intent.excludes_stale and (
        is_review_only or is_superseded or state_markers.stale_only
    ):
        return TemporalQueryBoostSignal(
            boost=-0.12,
            reason="query excludes stale memory",
            code="excludes_stale",
        )
    if intent.session_ordinals:
        item_session_orders = set(temporal_session_orders(item))
        query_session_orders = set(intent.session_ordinals)
        if item_session_orders.intersection(query_session_orders):
            return TemporalQueryBoostSignal(
                boost=0.034,
                reason="query asks for an explicit session and item matches it",
                code="exact_session_order_match",
            )
        if item_session_orders:
            return TemporalQueryBoostSignal(
                boost=-0.018,
                reason="query asks for an explicit session and item has a different session",
                code="exact_session_order_conflict",
            )
    if direction_boost := _event_sequence_direction_boost(
        intent=intent,
        text=item.text,
    ):
        return TemporalQueryBoostSignal(
            boost=direction_boost,
            reason=_event_sequence_direction_reason(intent=intent, boost=direction_boost),
            code=_event_sequence_direction_code(intent=intent, boost=direction_boost),
        )
    if boundary_conflict := _relative_time_boundary_conflict_signal(
        intent=intent,
        temporal_hint_code=temporal_hint_code,
    ):
        return boundary_conflict
    if _temporal_hint_matches(intent=intent, temporal_hint_code=temporal_hint_code):
        return TemporalQueryBoostSignal(
            boost=0.032,
            reason="query relative time matches item event window",
            code="relative_time_match",
        )
    if _temporal_hint_is_contained_by_query(
        intent=intent,
        temporal_hint_code=temporal_hint_code,
    ):
        return TemporalQueryBoostSignal(
            boost=0.018,
            reason="query relative time contains item event window",
            code="relative_time_contains",
        )
    if _temporal_hint_conflicts(intent=intent, temporal_hint_code=temporal_hint_code):
        return TemporalQueryBoostSignal(
            boost=-0.026,
            reason="query relative time conflicts with item event window",
            code="relative_time_conflict",
        )
    if intent.requests_upcoming and _is_future_temporal_hint(temporal_hint_code):
        return TemporalQueryBoostSignal(
            boost=0.03,
            reason="query asks for upcoming event and item has future event window",
            code="upcoming_event_future_temporal_hint",
        )
    if intent.requests_upcoming and _is_past_temporal_hint(temporal_hint_code):
        return TemporalQueryBoostSignal(
            boost=-0.022,
            reason="query asks for upcoming event and item has past event window",
            code="upcoming_event_past_temporal_hint_conflict",
        )
    if (
        intent.requests_recent_event
        and not _is_future_temporal_hint(temporal_hint_code)
        and not is_review_only
        and not is_superseded
        and not state_markers.stale_only
        and (session_recency_boost := temporal_session_recency_boost(item))
    ):
        return TemporalQueryBoostSignal(
            boost=session_recency_boost,
            reason="query asks for recent event and item has session-order evidence",
            code="recent_event_session_order",
        )
    if (
        intent.requests_earliest_event
        and not _is_future_temporal_hint(temporal_hint_code)
        and not is_review_only
        and not is_superseded
        and not state_markers.stale_only
        and (session_earliest_boost := temporal_session_earliest_boost(item))
    ):
        return TemporalQueryBoostSignal(
            boost=session_earliest_boost,
            reason="query asks for earliest event and item has session-order evidence",
            code="earliest_event_session_order",
        )
    if intent.requests_change and retrieval_source == "temporal_supersedes_relation":
        return TemporalQueryBoostSignal(
            boost=0.05,
            reason="query asks what changed and item is active replacement",
            code="change_active_replacement",
        )
    if intent.requests_change and has_temporal_relation:
        return TemporalQueryBoostSignal(
            boost=0.035,
            reason="query asks what changed and item has temporal relation",
            code="change_temporal_relation",
        )
    if intent.requests_change and state_markers.text_transition:
        return TemporalQueryBoostSignal(
            boost=0.04,
            reason="query asks what changed and item has state transition text",
            code="change_state_transition_text",
        )
    if intent.requests_change and is_superseded:
        return TemporalQueryBoostSignal(
            boost=0.035,
            reason="query asks what changed and item is previous state evidence",
            code="change_previous_state",
        )
    if during_boost := _event_sequence_during_boost(intent=intent, text=item.text):
        return TemporalQueryBoostSignal(
            boost=during_boost,
            reason="query asks for during-event context and item matches event",
            code="during_event_sequence_match",
        )
    if intent.requests_previous and is_superseded:
        return TemporalQueryBoostSignal(
            boost=0.045,
            reason="query asks for previous state evidence",
            code="previous_state_evidence",
        )
    if intent.requests_previous and state_markers.has_previous_state:
        return TemporalQueryBoostSignal(
            boost=0.042,
            reason="query asks for previous state evidence",
            code="previous_state_text_evidence",
        )
    if intent.prefers_current and (is_review_only or is_superseded):
        return TemporalQueryBoostSignal(
            boost=-0.024,
            reason="query prefers current active memory and item is superseded",
            code="current_superseded_conflict",
        )
    if intent.prefers_current and state_markers.stale_only:
        return TemporalQueryBoostSignal(
            boost=-0.028,
            reason="query prefers current active memory and item has stale state markers",
            code="current_stale_text_conflict",
        )
    if intent.prefers_current and not is_review_only and not is_superseded:
        return TemporalQueryBoostSignal(
            boost=0.018,
            reason="query prefers current active memory",
            code="current_active_match",
        )
    return TemporalQueryBoostSignal()


def _apply_temporal_query_intent(
    item: ContextItem,
    *,
    intent: TemporalQueryIntent,
) -> ContextItem:
    signal = temporal_query_boost_signal(item, intent=intent)
    if signal.empty:
        return item
    return _with_temporal_query_boost(
        item,
        boost=signal.boost,
        reason=signal.reason,
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
        "temporal_query_intent_reasons": intent.diagnostics()["temporal_query_intent_reasons"],
    }
    return replace(
        item,
        score=min(0.99, max(0.0, round(item.score + boost, 4))),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _event_sequence_direction_boost(*, intent: TemporalQueryIntent, text: str) -> float:
    if intent.after_event == intent.before_event:
        return 0.0
    variants = _query_variant_set(text)
    has_after = bool(variants.intersection(_AFTER_TERMS)) or _has_since_event_context(
        text,
        variants,
    ) or _has_matching_since_relative_time_context(
        text,
        intent,
    )
    has_before = bool(variants.intersection(_BEFORE_TERMS)) or _has_until_event_context(
        text,
        variants,
    ) or _has_matching_until_relative_time_context(
        text,
        intent,
    )
    has_same_event = _event_sequence_terms_match(text, intent.event_sequence_terms)
    if intent.after_event:
        if has_after and has_same_event:
            return 0.026
        if has_before and has_same_event and not intent.requests_change:
            return -0.024
    if intent.before_event:
        if has_before and has_same_event:
            return 0.026
        if has_after and has_same_event and not intent.requests_change:
            return -0.024
    return 0.0


def _relative_time_boundary_conflict_signal(
    *,
    intent: TemporalQueryIntent,
    temporal_hint_code: str,
) -> TemporalQueryBoostSignal | None:
    if intent.after_event == intent.before_event:
        return None
    if not temporal_hint_code or not intent.relative_time_hints:
        return None
    if not _temporal_hint_overlaps(intent=intent, temporal_hint_code=temporal_hint_code):
        return None
    direction = "after" if intent.after_event else "before"
    return TemporalQueryBoostSignal(
        boost=-0.014,
        reason=(
            f"query asks for {direction}-event sequence and item only matches "
            "the boundary window"
        ),
        code=f"{direction}_event_boundary_window_conflict",
    )


def _event_sequence_during_boost(*, intent: TemporalQueryIntent, text: str) -> float:
    if not intent.during_event:
        return 0.0
    variants = _query_variant_set(text)
    has_during = bool(_DURING_EVENT_RE.search(text)) or bool(
        variants.intersection(_DURING_TERMS)
    )
    has_same_event = _event_sequence_terms_match(text, intent.event_sequence_terms)
    return 0.024 if has_during and has_same_event else 0.0


def _event_sequence_direction_reason(*, intent: TemporalQueryIntent, boost: float) -> str:
    direction = "after" if intent.after_event else "before"
    if boost > 0:
        return f"query asks for {direction}-event sequence and item matches direction"
    return f"query asks for {direction}-event sequence and item conflicts with direction"


def _event_sequence_direction_code(*, intent: TemporalQueryIntent, boost: float) -> str:
    direction = "after" if intent.after_event else "before"
    suffix = "match" if boost > 0 else "conflict"
    return f"{direction}_event_sequence_{suffix}"


def _query_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=32):
        variants.update(term.variants)
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            variants.add(token)
    return frozenset(variants)


def _event_sequence_anchor_terms(query: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for match in _EVENT_SEQUENCE_ANCHOR_RE.finditer(query):
        tail = (match.group("tail") or match.group("ru_tail") or "").strip()
        if not tail:
            continue
        for term in query_terms(tail, min_chars=3, max_terms=8):
            if set(term.variants).intersection(_EVENT_SEQUENCE_ANCHOR_STOP_VARIANTS):
                continue
            seen.setdefault(term.raw, None)
            if len(seen) >= 5:
                return tuple(seen)
    return tuple(seen)


def _event_sequence_terms_match(text: str, event_terms: tuple[str, ...]) -> bool:
    if not event_terms:
        return True
    variants = _query_variant_set(text)
    if not variants:
        return False
    for term in query_terms(" ".join(event_terms), min_chars=3, max_terms=8):
        if not variants.intersection(term.variants):
            return False
    return True


def _has_after_event_context(text: str, variants: frozenset[str]) -> bool:
    if _has_since_event_context(text, variants):
        return True
    return bool(variants.intersection(_AFTER_TERMS)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    )


def _has_before_event_context(text: str, variants: frozenset[str]) -> bool:
    if _has_until_event_context(text, variants):
        return True
    return bool(variants.intersection(_BEFORE_TERMS)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    )


def _has_during_event_context(text: str, variants: frozenset[str]) -> bool:
    if bool(_DURING_EVENT_RE.search(text)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    ):
        return True
    return bool(variants.intersection(_DURING_TERMS)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    )


def _has_since_event_context(text: str, variants: frozenset[str]) -> bool:
    return bool(_SINCE_EVENT_RE.search(text)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    )


def _has_until_event_context(text: str, variants: frozenset[str]) -> bool:
    return bool(_UNTIL_EVENT_RE.search(text)) and bool(
        variants.intersection(_EVENT_SEQUENCE_CONTEXT_TERMS)
    )


def _has_since_relative_time_context(
    text: str,
    relative_time_hints: tuple[str, ...],
) -> bool:
    return bool(relative_time_hints) and bool(_SINCE_EVENT_RE.search(text))


def _has_until_relative_time_context(
    text: str,
    relative_time_hints: tuple[str, ...],
) -> bool:
    return bool(relative_time_hints) and bool(_UNTIL_EVENT_RE.search(text))


def _has_matching_since_relative_time_context(
    text: str,
    intent: TemporalQueryIntent,
) -> bool:
    return (
        bool(_SINCE_EVENT_RE.search(text))
        and bool(intent.relative_time_hints)
        and _text_has_overlapping_relative_hint(text, intent)
    )


def _has_matching_until_relative_time_context(
    text: str,
    intent: TemporalQueryIntent,
) -> bool:
    return (
        bool(_UNTIL_EVENT_RE.search(text))
        and bool(intent.relative_time_hints)
        and _text_has_overlapping_relative_hint(text, intent)
    )


def _text_has_overlapping_relative_hint(text: str, intent: TemporalQueryIntent) -> bool:
    return any(
        _temporal_hint_overlaps(intent=intent, temporal_hint_code=hint)
        for hint in _query_temporal_hint_codes(text)
    )


def _temporal_hint_conflicts(
    *,
    intent: TemporalQueryIntent,
    temporal_hint_code: str,
) -> bool:
    if not temporal_hint_code or not intent.relative_time_hints:
        return False
    query_exact_dates = {
        hint for hint in intent.relative_time_hints if _is_exact_date_temporal_hint(hint)
    }
    if query_exact_dates:
        return _is_exact_date_temporal_hint(temporal_hint_code) and (
            temporal_hint_code not in query_exact_dates
        )
    if _is_exact_date_temporal_hint(temporal_hint_code):
        return False
    return not _temporal_hint_overlaps(intent=intent, temporal_hint_code=temporal_hint_code)


def _temporal_hint_matches(
    *,
    intent: TemporalQueryIntent,
    temporal_hint_code: str,
) -> bool:
    return bool(temporal_hint_code and temporal_hint_code in set(intent.relative_time_hints))


def _temporal_hint_is_contained_by_query(
    *,
    intent: TemporalQueryIntent,
    temporal_hint_code: str,
) -> bool:
    if not temporal_hint_code:
        return False
    query_hints = set(intent.relative_time_hints)
    return any(temporal_hint_code in _TEMPORAL_HINT_CHILDREN.get(hint, ()) for hint in query_hints)


def _temporal_hint_overlaps(
    *,
    intent: TemporalQueryIntent,
    temporal_hint_code: str,
) -> bool:
    if _temporal_hint_matches(intent=intent, temporal_hint_code=temporal_hint_code):
        return True
    if _temporal_hint_is_contained_by_query(
        intent=intent,
        temporal_hint_code=temporal_hint_code,
    ):
        return True
    parent = _TEMPORAL_HINT_PARENTS.get(temporal_hint_code)
    if parent is not None and parent in set(intent.relative_time_hints):
        return True
    return any(
        _TEMPORAL_HINT_PARENTS.get(hint) == temporal_hint_code
        for hint in intent.relative_time_hints
    )


def _is_exact_date_temporal_hint(code: str) -> bool:
    return code.startswith("date_")


def _is_future_temporal_hint(code: str) -> bool:
    return code in {
        "next_month",
        "next_quarter",
        "next_week",
        "next_year",
        "this_weekend",
        "tomorrow",
    }


def _is_past_temporal_hint(code: str) -> bool:
    return bool(
        code == "yesterday"
        or code.startswith("last_")
        or code.endswith("_ago")
        or code in {
            "earlier_today",
            "last_night",
            "today_morning",
            "weekends_ago",
        }
    )


def _temporal_hint_code(
    diagnostics: Mapping[str, object],
    provenance: Mapping[str, object],
) -> str:
    return temporal_hint_code_from_metadata(diagnostics, provenance)
