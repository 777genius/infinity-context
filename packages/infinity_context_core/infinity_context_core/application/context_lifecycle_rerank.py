"""Relationship and lifecycle-state rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_types import DomainRerankSignal
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    matches_query_or_score_signal_reason as _matches_query_or_score_signal_reason,
)
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

_RELATIONSHIP_STATUS_RERANK_REASONS = frozenset(
    (
        "relationship_status_bridge",
        "decomposition_relationship_status",
    )
)

_RELATIONSHIP_DURATION_RERANK_REASONS = frozenset(
    (
        "relationship_duration_bridge",
        "decomposition_relationship_duration",
    )
)

_RELATIONSHIP_ORIGIN_RERANK_REASONS = frozenset(("relationship_origin_bridge",))

_STATE_TRANSITION_RERANK_REASONS = frozenset(
    (
        "change_over_time_bridge",
        "decomposition_state_transition",
        "decomposition_temporal_change",
        "state_transition_bridge",
    )
)

_CURRENT_STATE_RERANK_REASONS = frozenset(
    (
        "current_recommendation_bridge",
        "current_state_temporal_bridge",
        "decomposition_knowledge_update_current",
    )
)

_STALE_STATE_RERANK_REASONS = frozenset(("stale_state_temporal_bridge",))

_EVENT_SEQUENCE_MARKER_RE = re.compile(
    r"\b(?:after|since|following|later|next|then|subsequently|before|earlier|prior)\b|"
    r"\b(?:после|с\s+тех\s+пор|затем|потом|до|перед|раньше)\b",
    re.IGNORECASE,
)

_EVENT_SEQUENCE_OUTCOME_RE = re.compile(
    r"\b(?:decid(?:e|ed|es|ing)|chang(?:e|ed|es|ing)|agreed?|promis(?:e|ed|es|ing)|"
    r"selected?|chos(?:e|en)|picked?|planned?|wait(?:ed|ing)?|follow(?:ed)?\s+up|"
    r"outcome|result|happened|response|next\s+step)\b|"
    r"\b(?:решил\w*|изменил\w*|согласил\w*|пообещал\w*|выбрал\w*|"
    r"запланировал\w*|договорил\w*|результат|следующ\w+\s+шаг)\b",
    re.IGNORECASE,
)

_EVENT_SEQUENCE_QUERY_RE = re.compile(
    r"\b(?:what|which|who|when|where|how)\b(?=.{0,120}\b(?:after|since|following|"
    r"before|prior)\b)(?=.{0,160}\b(?:talk(?:ed|ing)?|spoke|conversation|call|"
    r"meeting|chat|message|event|decid(?:e|ed)|chang(?:e|ed)|happened)\b)|"
    r"\b(?:что|кто|когда|где|как)\b(?=.{0,120}\b(?:после|до|перед|с\s+тех\s+пор)\b)",
    re.IGNORECASE | re.DOTALL,
)

_EVENT_SEQUENCE_NAMED_ANCHOR_RE = re.compile(
    r"\b[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,}\b"
)

_EVENT_SEQUENCE_IGNORED_ANCHORS = frozenset(
    {
        "After",
        "Before",
        "Following",
        "How",
        "Since",
        "The",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
        "Где",
        "До",
        "Зачем",
        "Как",
        "Какая",
        "Какие",
        "Какой",
        "Когда",
        "Кто",
        "Перед",
        "После",
        "Почему",
        "Что",
    }
)

_EVENT_SEQUENCE_MIN_QUERY_DISTINCTIVE_TERMS = 3

_EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS = 3

_RELATIONSHIP_STATUS_EXACT_RE = re.compile(
    r"\b(?:relationship\s+status|single\s+parent|single\b|not\s+dating|"
    r"dating|boyfriend|girlfriend|fianc[eé]e?|romantic\s+partner|"
    r"life\s+partner|spouse|husband|wife|married|divorced|separated|"
    r"widow(?:ed|er)?|breakup|broke\s+up|split\s+up|"
    r"in\s+a\s+relationship)\b|"
    r"\b(?:статус\s+отношений|одинок\w*|холост\w*|не\s+замужем|"
    r"не\s+женат|в\s+отношениях|парень|девушка|партн[её]р|муж|жена|"
    r"супруг|супруга|развод\w*|расстал\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_WORK_PARTNER_RE = re.compile(
    r"\b(?:accountability|business|class|cofounder|co-founder|conversation|"
    r"dance|founder|gym|lab|project|research|running|school|sparring|startup|"
    r"study|team|training|volunteer|work)\s+"
    r"partners?\b|\bpartners?\s+(?:on|for|in)\s+"
    r"(?:atlas|business|class|gym|lab|project|research|running|school|startup|"
    r"study|team|training|volunteer|work)\b|"
    r"\b(?:рабоч\w*|бизнес|проектн\w*|учебн\w*|тренировочн\w*)\s+"
    r"партн[её]р\w*\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_SOCIAL_WEAK_RE = re.compile(
    r"\b(?:friend|friends|old\s+friend|classmate|school|colleague|coworker|"
    r"mentor|coach|teacher|family|support\s+system|met\s+at|went\s+to\s+"
    r"school\s+with|knows?\s+from)\b|"
    r"\b(?:друг|друзья|подруга|одноклассник|школ\w*|коллег\w*|"
    r"наставник|учитель|семь[яи]|знаком\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_DURATION_EXACT_RE = re.compile(
    r"\b(?:for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+)?"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|several|many|a\s+couple\s+of)\s+"
    r"(?:years?|months?|weeks?|days?)|since\s+(?:\d{4}|"
    r"[A-Z][a-z]+\s+\d{4}|childhood|college|school)|anniversary|"
    r"known\s+each\s+other\s+for|have\s+been\s+(?:married|together)|"
    r"been\s+friends\s+for)\b|"
    r"\b(?:уже\s+)?(?:\d+|один|одна|два|две|три|четыре|пять|шесть|"
    r"семь|восемь|девять|десять|несколько)\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)|"
    r"\bс\s+\d{4}\b|годовщин\w*|знаком\w+\s+.*\b(?:лет|года|год)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_DURATION_WEAK_RE = re.compile(
    r"\b(?:married|husband|wife|spouse|partner|friend|friends|old\s+friend|"
    r"relationship|wedding|met|known|school|college)\b|"
    r"\b(?:женат|замужем|муж|жена|супруг|супруга|партн[её]р|друг|"
    r"друзья|отношен\w*|свадьб\w*|знаком\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ORIGIN_EXACT_RE = re.compile(
    r"\b(?:first\s+met|met\s+(?:at|in|on|during|through|via)|"
    r"introduced\s+(?:at|in|during|through|via|by)|"
    r"became\s+friends\s+(?:at|in|during|through|via)|"
    r"known\s+(?:each\s+other\s+)?since|go\s+back\s+to|"
    r"have\s+known\s+each\s+other\s+since)\b|"
    r"\b(?:впервые\s+)?(?:познакомил(?:ись|ся|ась)|встретил(?:ись|ся|ась))\s+"
    r"(?:в|на|через|во\s+время|благодаря)\b|"
    r"\bзнаком\w+\s+с\s+(?:\d{4}|детства|школ\w*|университет\w*|колледж\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ORIGIN_WEAK_RE = re.compile(
    r"\b(?:friend|friends|old\s+friend|classmate|colleague|coworker|school|"
    r"college|university|work|event|party|conference|knows?|met)\b|"
    r"\b(?:друг|друзья|подруга|одноклассник|коллег\w*|школ\w*|"
    r"университет\w*|колледж\w*|работ\w*|событи\w*|знаком\w*)\b",
    re.IGNORECASE,
)

_STATE_TRANSITION_PAIR_RE = re.compile(
    r"\b(?:changed|updated|switched|migrated|transitioned|replaced)\b"
    r"(?=.{0,120}\bfrom\b)(?=.{0,160}\bto\b)|"
    r"\bfrom\b(?=.{0,120}\bto\b)(?=.{0,180}\b(?:current|new|active|final|"
    r"replacement|provider|tool|model|plan|policy|source)\b)|"
    r"\b(?:replaced|superseded|took\s+over)\b(?=.{0,120}\b(?:by|with|current|"
    r"new|active|final)\b)|"
    r"\b(?:old|previous|stale|superseded|deprecated|no\s+longer\s+valid|"
    r"no\s+longer\s+current)\b"
    r"(?=.{0,180}\b(?:current|new|active|final|replacement|replaced\s+by|"
    r"switched\s+to|migrated\s+to|now)\b)|"
    r"\b(?:изменил\w*|обновил\w*|смени\w*|переш[её]л\w*|мигрировал\w*)\b"
    r"(?=.{0,120}\b(?:с|со)\b)(?=.{0,160}\b(?:на|в)\b)|"
    r"\b(?:заменил\w*|заменен\w*|заменён\w*)\b(?=.{0,120}\b(?:на|нов\w*|"
    r"текущ\w*|актуальн\w*)\b)|"
    r"\b(?:стар\w*|предыдущ\w*|устаревш\w*|больше\s+не\s+актуальн\w*)\b"
    r"(?=.{0,180}\b(?:нов\w*|текущ\w*|актуальн\w*|сейчас|теперь|замен\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STATE_TRANSITION_MARKER_RE = re.compile(
    r"\b(?:changed|updated|switched|migrated|transitioned|replaced|superseded|"
    r"current|active|new|old|previous|stale|deprecated|no\s+longer|now)\b|"
    r"\b(?:изменил\w*|изменилось|обновил\w*|смени\w*|переш[её]л\w*|"
    r"мигрировал\w*|заменил\w*|заменен\w*|заменён\w*|текущ\w*|"
    r"актуальн\w*|нов\w*|стар\w*|предыдущ\w*|устаревш\w*|теперь|сейчас)\b",
    re.IGNORECASE,
)

_CURRENT_STATE_EXACT_RE = re.compile(
    r"\b(?:current|active|latest|final|selected|chosen|recommended|"
    r"canonical|source\s+of\s+truth|decided\s+to\s+use|should\s+use|"
    r"using\s+now|right\s+now|remains?\s+valid|still\s+valid|"
    r"valid\s+and\s+active)\b|"
    r"\b(?:актуальн\w*|текущ\w*|финальн\w*|окончательн\w*|"
    r"выбранн\w*|рекомендованн\w*|сейчас|действу\w*)\b",
    re.IGNORECASE,
)

_STALE_STATE_EXACT_RE = re.compile(
    r"\b(?:no\s+longer\s+(?:valid|current|active|used?|using)|"
    r"not\s+current|not\s+valid|stale|outdated|deprecated|superseded|"
    r"replaced\s+by|switched\s+away|previous(?:ly)?\s+valid|former|"
    r"old\s+(?:provider|tool|model|plan|policy|decision|source))\b|"
    r"\b(?:устаревш\w*|больше\s+не\s+(?:актуальн\w*|использ\w*)|"
    r"не\s+актуальн\w*|предыдущ\w*|замен[её]н\w*)\b",
    re.IGNORECASE,
)

_CURRENT_STATE_QUERY_RE = re.compile(
    r"\b(?:current|currently|latest|active|final|selected|chosen|recommended|"
    r"canonical|source\s+of\s+truth|still\s+valid|should\s+(?:i\s+)?use|"
    r"what\s+did\s+i\s+decide\s+to\s+use)\b|"
    r"\b(?:актуальн\w*|текущ\w*|финальн\w*|окончательн\w*|"
    r"выбранн\w*|рекомендованн\w*)\b",
    re.IGNORECASE,
)

_STALE_STATE_QUERY_RE = re.compile(
    r"\b(?:no\s+longer\s+(?:valid|current|active|used?|using)|not\s+current|"
    r"not\s+valid|stale|outdated|deprecated|"
    r"(?:previous|former|old)\s+"
    r"(?:provider|tool|model|plan|policy|decision|source|state|option)|"
    r"should\s+(?:i\s+)?no\s+longer\s+use)\b|"
    r"\b(?:устаревш\w*|больше\s+не\s+(?:актуальн\w*|использ\w*)|"
    r"не\s+актуальн\w*|предыдущ\w*)\b",
    re.IGNORECASE,
)

def event_sequence_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_event_sequence_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if relevance.distinctive_term_count < _EVENT_SEQUENCE_MIN_QUERY_DISTINCTIVE_TERMS:
        return DomainRerankSignal()
    has_sequence_shape = (
        _EVENT_SEQUENCE_MARKER_RE.search(item.text) is not None
        and (
            _EVENT_SEQUENCE_OUTCOME_RE.search(item.text) is not None
            or _STATE_TRANSITION_PAIR_RE.search(item.text) is not None
        )
    )
    anchor_terms = _event_sequence_anchor_terms(query)
    anchor_hits = _event_sequence_anchor_hits(anchor_terms=anchor_terms, text=item.text)
    required_anchor_hits = min(3, len(anchor_terms))
    has_required_anchors = required_anchor_hits <= 0 or anchor_hits >= required_anchor_hits
    if (
        has_sequence_shape
        and relevance.distinctive_term_hits >= _EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS
        and has_required_anchors
    ):
        return DomainRerankSignal(boost=0.034, reason="event_sequence_exact_evidence")
    if required_anchor_hits > 0 and anchor_hits < required_anchor_hits:
        return DomainRerankSignal(penalty=0.06, reason="event_sequence_anchor_mismatch")
    if relevance.distinctive_term_hits < _EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS:
        return DomainRerankSignal(penalty=0.06, reason="event_sequence_weak_evidence")
    if not has_sequence_shape:
        return DomainRerankSignal(penalty=0.075, reason="event_sequence_shape_missing")
    return DomainRerankSignal()

def relationship_status_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_status_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RELATIONSHIP_STATUS_WORK_PARTNER_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.055,
            reason="relationship_status_weak_evidence",
        )
    if _RELATIONSHIP_STATUS_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_status_exact_evidence",
        )
    if (
        _RELATIONSHIP_STATUS_SOCIAL_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="relationship_status_weak_evidence",
        )
    return DomainRerankSignal()

def relationship_duration_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_duration_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RELATIONSHIP_DURATION_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_duration_exact_evidence",
        )
    if (
        _RELATIONSHIP_DURATION_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.05,
            reason="relationship_duration_weak_evidence",
        )
    return DomainRerankSignal()

def relationship_origin_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_origin_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RELATIONSHIP_ORIGIN_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_origin_exact_evidence",
        )
    if (
        _RELATIONSHIP_ORIGIN_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.05,
            reason="relationship_origin_weak_evidence",
        )
    return DomainRerankSignal()

def state_transition_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_state_transition_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _STATE_TRANSITION_PAIR_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.03,
            reason="state_transition_exact_evidence",
        )
    if _STATE_TRANSITION_MARKER_RE.search(item.text) is not None:
        return DomainRerankSignal()
    if relevance.distinctive_term_hits < 4:
        return DomainRerankSignal(
            penalty=0.055,
            reason="state_transition_weak_evidence",
        )
    return DomainRerankSignal(
        penalty=0.035,
        reason="state_transition_weak_evidence",
    )

def current_state_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _is_stale_state_candidate(query=query, query_reason=query_reason, item=item):
        if _STALE_STATE_EXACT_RE.search(item.text) is not None:
            return DomainRerankSignal(boost=0.032, reason="stale_state_exact_evidence")
        if _CURRENT_STATE_EXACT_RE.search(item.text) is not None:
            return DomainRerankSignal(
                penalty=0.045,
                reason="stale_state_current_conflict",
            )
        if relevance.distinctive_term_hits < 4:
            return DomainRerankSignal(penalty=0.035, reason="stale_state_weak_evidence")
        return DomainRerankSignal()
    if not _is_current_state_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _STALE_STATE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.055,
            reason="current_state_stale_conflict",
        )
    if _CURRENT_STATE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.028, reason="current_state_exact_evidence")
    if relevance.distinctive_term_hits < 3:
        return DomainRerankSignal(penalty=0.026, reason="current_state_weak_evidence")
    return DomainRerankSignal()

def _is_event_sequence_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="decomposition_event_sequence",
    ) or _EVENT_SEQUENCE_QUERY_RE.search(query) is not None

def _is_relationship_status_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_STATUS_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_STATUS_RERANK_REASONS

def _is_relationship_duration_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_DURATION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_DURATION_RERANK_REASONS

def _is_relationship_origin_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_ORIGIN_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_ORIGIN_RERANK_REASONS

def _is_state_transition_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _STATE_TRANSITION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _STATE_TRANSITION_RERANK_REASONS

def _is_current_state_candidate(*, query: str, query_reason: str, item: ContextItem) -> bool:
    if _CURRENT_STATE_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _CURRENT_STATE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _CURRENT_STATE_RERANK_REASONS

def _is_stale_state_candidate(*, query: str, query_reason: str, item: ContextItem) -> bool:
    if _STALE_STATE_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _STALE_STATE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _STALE_STATE_RERANK_REASONS


def has_current_state_correction_evidence(text: str) -> bool:
    has_current_state = _CURRENT_STATE_EXACT_RE.search(text) is not None
    has_stale_context = _STALE_STATE_EXACT_RE.search(text) is not None
    has_transition = _STATE_TRANSITION_PAIR_RE.search(text) is not None
    return has_current_state and (has_stale_context or has_transition)


def _event_sequence_anchor_terms(query: str) -> tuple[str, ...]:
    terms = []
    seen = set()
    for match in _EVENT_SEQUENCE_NAMED_ANCHOR_RE.finditer(query):
        term = match.group(0)
        if term in _EVENT_SEQUENCE_IGNORED_ANCHORS:
            continue
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms)

def _event_sequence_anchor_hits(*, anchor_terms: tuple[str, ...], text: str) -> int:
    text_lower = text.casefold()
    return sum(
        1
        for term in anchor_terms
        if re.search(rf"\b{re.escape(term)}\b", text_lower)
    )
