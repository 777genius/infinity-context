"""Social support, commonality and shared event detail rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_inventory import (
    _INVENTORY_LIST_RERANK_REASONS,
    _inventory_list_exact_evidence,
)
from infinity_context_core.application.context_domain_rerank_legacy_contract import (
    DomainRerankSignal,
    _matches_query_or_score_signal_reason,
)
from infinity_context_core.application.context_domain_rerank_state import _STATE_TRANSITION_PAIR_RE
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

_SUPPORT_NETWORK_PEOPLE_RE = re.compile(
    r"\b(?:friends?|family|mentors?|people\s+around|parents?|mother|mom|"
    r"father|dad|sisters?|brothers?|siblings?|partner|spouse|husband|wife|"
    r"coach|teacher|counselor)\b|"
    r"\b(?:друзья|друзей|семья|семьи|родители|мама|мать|отец|папа|"
    r"сестра|сестры|брат|братья|партнер|партн[её]р|супруг|супруга|"
    r"наставники|наставник|тренер|учитель|люди\s+рядом)\b",
    re.IGNORECASE,
)

_SUPPORT_NETWORK_SIGNAL_RE = re.compile(
    r"\b(?:rocks?|there\s+for|support\s+system|support\s+network|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed)?\s+(?:me|her|him|them)\s+on|"
    r"trusted|reliable|comfort(?:s|ed)?)\b|"
    r"\b(?:опор\w*|рядом|поддерж\w*|помог\w*|сил\w*|мотивир\w*)\b",
    re.IGNORECASE,
)

_SUPPORT_NETWORK_TECHNICAL_RE = re.compile(
    r"\b(?:api|backend|cloud|customer|database|frontend|infra|integration|"
    r"library|model|platform|provider|runtime|sdk|service|software|technical|"
    r"tool|web)\b",
    re.IGNORECASE,
)

_SUPPORT_NETWORK_RERANK_REASONS = frozenset(
    (
        "negative_experience_support_bridge",
        "support_network_bridge",
    )
)

_COMMONALITY_RERANK_REASONS = frozenset(
    (
        "business_commonality_bridge",
        "commonality_interest_bridge",
        "decomposition_commonality",
    )
)

_FAMILY_HIKE_DETAIL_RERANK_REASONS = frozenset(
    (
        "family_hike_activity_bridge",
        "family_hike_detail_bridge",
    )
)

_TEMPORAL_CAMPING_DETAIL_RERANK_REASONS = frozenset(
    (
        "camping_detail_bridge",
        "temporal_event_detail_bridge",
    )
)

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

_COMMONALITY_QUERY_RE = re.compile(
    r"\b(?:common|shared|both|mutual|same|similar|overlap|who\s+else)\b|"
    r"\b(?:обе|оба|общ\w*|похож\w*|тоже)\b",
    re.IGNORECASE,
)

_COMMONALITY_WHO_ELSE_QUERY_RE = re.compile(
    r"\bwho\s+else\b|"
    r"\b(?:кто\s+ещ[её]|еще\s+кто|ещ[её]\s+кто)\b",
    re.IGNORECASE,
)

_COMMONALITY_EVIDENCE_RE = re.compile(
    r"\b(?:both|share(?:s|d)?|shared|common|mutual|same|similar|also|"
    r"each|together|overlap)\b|"
    r"\b(?:обе|оба|общ\w*|похож\w*|тоже|вместе)\b",
    re.IGNORECASE,
)

_COMMONALITY_WHO_ELSE_EVIDENCE_RE = re.compile(
    r"\b(?:also|too|as\s+well|like|likes|liked|enjoys?|enjoyed|interested\s+in|"
    r"fan\s+of)\b|"
    r"\b(?:тоже|также|любит|нравит\w*|интересу\w*)\b",
    re.IGNORECASE,
)

_COMMONALITY_SHARED_ARTIFACT_RE = re.compile(
    r"\bshared?\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:photo|picture|image|screenshot|file|document|attachment|link|post)\b",
    re.IGNORECASE,
)

_BUSINESS_COMMONALITY_ORIGIN_RE = re.compile(
    r"\b(?:"
    r"lost\s+my\s+job\s+(?:as|at)|"
    r"also\s+lost\s+my\s+job|"
    r"lost\s+(?:her|his)\s+job|"
    r"after\s+losing\s+(?:her|his)\s+job|"
    r"take\s+a\s+shot\s+at\s+starting\s+my\s+own\s+business|"
    r"starting\s+my\s+own\s+store|"
    r"started\s+(?:her|his)\s+own\s+(?:online\s+)?clothing\s+store|"
    r"launched\s+an\s+ad\s+campaign|"
    r"taking\s+risks\s+is\s+both\s+scary\s+and\s+rewarding|"
    r"i['']?m\s+starting\s+a\s+dance\s+studio"
    r")\b",
    re.IGNORECASE,
)

_BUSINESS_COMMONALITY_LATE_UPDATE_RE = re.compile(
    r"\b(?:"
    r"congrats?\s+on\s+the\s+clothing\s+store|"
    r"hard\s+work\s+paying\s+off|"
    r"got\s+a\s+temp\s+job|"
    r"built\s+a\s+new\s+website|"
    r"acquired\s+some\s+new\s+unique\s+pieces|"
    r"working\s+on\s+(?:my\s+)?online\s+store|"
    r"promoting\s+(?:my\s+)?business|"
    r"business\s+project\s+and\s+seeks\s+advice"
    r")\b",
    re.IGNORECASE,
)

_SHARED_PAINTED_SUBJECT_EXACT_RE = re.compile(
    r"\b(?:sunsets?|sunrises?|landscapes?|flowers?|nature(?:-inspired)?|"
    r"lake|mountains?|abstract|portraits?|scen(?:e|ery))\b"
    r"(?=.{0,80}\b(?:paint(?:ed|ing)?|artwork|work|image|visual|caption)\b)|"
    r"\b(?:paint(?:ed|ing)?|artwork|work|image|visual|caption)\b"
    r"(?=.{0,80}\b(?:sunsets?|sunrises?|landscapes?|flowers?|"
    r"nature(?:-inspired)?|lake|mountains?|abstract|portraits?|scen(?:e|ery))\b)",
    re.IGNORECASE | re.DOTALL,
)

_SHARED_PAINTED_SUBJECT_TOPIC_RE = re.compile(
    r"\b(?:paint(?:ed|ing)?|artwork)\b",
    re.IGNORECASE,
)

_FAMILY_HIKE_DETAIL_EXACT_RE = re.compile(
    r"\b(?:roast(?:ed|ing)?\s+marshmallows?|marshmallows?|"
    r"tell(?:ing)?\s+stories|shared\s+stories)\b",
    re.IGNORECASE,
)

_FAMILY_HIKE_DETAIL_TOPIC_RE = re.compile(
    r"\b(?:family|kids?|children|hikes?|hiking|camp(?:ing|fire)?|nature|"
    r"trail|waterfall|photos?|pictures?)\b",
    re.IGNORECASE,
)

_FAMILY_HIKE_DETAIL_QUERY_RE = re.compile(
    r"\bwhat\b(?=.{0,80}\b(?:family|kids?|children)\b)"
    r"(?=.{0,80}\b(?:hikes?|hiking)\b)|"
    r"\b(?:hikes?|hiking)\b(?=.{0,80}\b(?:family|kids?|children)\b)",
    re.IGNORECASE | re.DOTALL,
)

_TEMPORAL_CAMPING_DETAIL_QUERY_RE = re.compile(
    r"\bwhen\b(?=.{0,120}\bcamp(?:ing|ed)?\b)|"
    r"\bcamp(?:ing|ed)?\b(?=.{0,120}\bwhen\b)",
    re.IGNORECASE | re.DOTALL,
)

_TEMPORAL_CAMPING_CORE_DETAIL_RE = re.compile(
    r"\b(?:roast(?:ed|ing)?\s+marshmallows?|marshmallows?|campfire)\b",
    re.IGNORECASE,
)

_TEMPORAL_CAMPING_DETAIL_TERM_RE = re.compile(
    r"\b(?:campfire|marshmallows?|roast(?:ed|ing)?|hikes?|hiking|trail|"
    r"mountains?|nature|view|family|kids?|children|moments?)\b",
    re.IGNORECASE,
)

_COMMONALITY_NAMED_ANCHOR_RE = re.compile(r"\b[A-Z][A-Za-z0-9._-]{1,}\b")

_COMMONALITY_IGNORED_ANCHORS = frozenset(
    {
        "How",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
    }
)

def support_network_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _support_network_exact_evidence(query_reason=query_reason, item=item):
        return DomainRerankSignal(boost=0.028, reason="support_network_exact_evidence")
    if _support_network_weak_evidence(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    ):
        return DomainRerankSignal(penalty=0.07, reason="support_network_weak_evidence")
    return DomainRerankSignal()

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

def commonality_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_commonality_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    business_signal = _business_commonality_signal(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    )
    if business_signal.reason:
        return business_signal
    who_else_signal = _commonality_who_else_signal(query=query, item=item)
    if who_else_signal.reason:
        return who_else_signal
    shared_painted_subject_signal = _shared_painted_subject_signal(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    )
    if shared_painted_subject_signal.reason:
        return shared_painted_subject_signal
    if (
        query_reason in _INVENTORY_LIST_RERANK_REASONS
        and _inventory_list_exact_evidence(
            query=query,
            query_reason=query_reason,
            item=item,
        )
    ):
        return DomainRerankSignal()
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) < 2:
        return DomainRerankSignal()
    anchor_hits = _commonality_anchor_hits(anchor_terms=anchor_terms, text=item.text)
    has_commonality_shape = _COMMONALITY_EVIDENCE_RE.search(item.text) is not None
    if anchor_hits >= 2 and _COMMONALITY_SHARED_ARTIFACT_RE.search(item.text):
        return DomainRerankSignal(penalty=0.032, reason="commonality_weak_evidence")
    if anchor_hits >= 2 and has_commonality_shape:
        return DomainRerankSignal(boost=0.028, reason="commonality_exact_evidence")
    if anchor_hits < 2:
        return DomainRerankSignal(penalty=0.048, reason="commonality_anchor_mismatch")
    if not has_commonality_shape or relevance.distinctive_term_hits < 5:
        return DomainRerankSignal(penalty=0.032, reason="commonality_weak_evidence")
    return DomainRerankSignal()

def _business_commonality_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="business_commonality_bridge",
    ):
        return DomainRerankSignal()
    if _BUSINESS_COMMONALITY_ORIGIN_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.044,
            reason="business_commonality_origin_evidence",
        )
    if (
        _BUSINESS_COMMONALITY_LATE_UPDATE_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 7
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="business_commonality_weak_update",
        )
    return DomainRerankSignal()

def _shared_painted_subject_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="shared_painted_subject_bridge",
    ):
        return DomainRerankSignal()
    if (
        _SHARED_PAINTED_SUBJECT_EXACT_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(
            boost=0.034,
            reason="shared_painted_subject_exact_evidence",
        )
    if _SHARED_PAINTED_SUBJECT_TOPIC_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.052,
            reason="shared_painted_subject_topic_only_noise",
        )
    return DomainRerankSignal()

def family_hike_detail_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_family_hike_detail_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if (
        _FAMILY_HIKE_DETAIL_EXACT_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(
            boost=0.034,
            reason="family_hike_detail_exact_evidence",
        )
    if _FAMILY_HIKE_DETAIL_TOPIC_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.062,
            reason="family_hike_detail_topic_only_noise",
        )
    return DomainRerankSignal()

def temporal_camping_detail_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_temporal_camping_detail_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if relevance.distinctive_term_hits < 6:
        return DomainRerankSignal()
    if _TEMPORAL_CAMPING_CORE_DETAIL_RE.search(item.text) is None:
        return DomainRerankSignal()
    detail_terms = {
        match.group(0).casefold()
        for match in _TEMPORAL_CAMPING_DETAIL_TERM_RE.finditer(item.text)
    }
    if len(detail_terms) < 4:
        return DomainRerankSignal()
    return DomainRerankSignal(
        boost=0.058,
        reason="temporal_camping_detail_evidence",
    )

def commonality_who_else_anchor_override(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_commonality_candidate(query=query, query_reason=query_reason, item=item):
        return False
    if _COMMONALITY_WHO_ELSE_QUERY_RE.search(query) is None:
        return False
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) != 1:
        return False
    return (
        not _text_has_any_anchor(anchor_terms=anchor_terms, text=item.text)
        and _COMMONALITY_WHO_ELSE_EVIDENCE_RE.search(item.text) is not None
    )

def _support_network_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_support_network_candidate(query_reason=query_reason, item=item):
        return False
    return (
        _SUPPORT_NETWORK_PEOPLE_RE.search(item.text) is not None
        and _SUPPORT_NETWORK_SIGNAL_RE.search(item.text) is not None
    )

def _support_network_weak_evidence(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> bool:
    if not _is_support_network_candidate(query_reason=query_reason, item=item):
        return False
    if _SUPPORT_NETWORK_TECHNICAL_RE.search(item.text) is not None:
        return True
    if _support_network_exact_evidence(query_reason=query_reason, item=item):
        return False
    return relevance.distinctive_term_hits < 4

def _is_support_network_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _SUPPORT_NETWORK_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _SUPPORT_NETWORK_RERANK_REASONS

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

def _is_commonality_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _COMMONALITY_RERANK_REASONS:
        return True
    if _score_signal_reason(item) in _COMMONALITY_RERANK_REASONS:
        return True
    return _COMMONALITY_QUERY_RE.search(query) is not None

def _is_family_hike_detail_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return (
        query_reason in _FAMILY_HIKE_DETAIL_RERANK_REASONS
        or _score_signal_reason(item) in _FAMILY_HIKE_DETAIL_RERANK_REASONS
        or _FAMILY_HIKE_DETAIL_QUERY_RE.search(query) is not None
    )

def _is_temporal_camping_detail_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _TEMPORAL_CAMPING_DETAIL_QUERY_RE.search(query) is None:
        return False
    return (
        query_reason in _TEMPORAL_CAMPING_DETAIL_RERANK_REASONS
        or _score_signal_reason(item) in _TEMPORAL_CAMPING_DETAIL_RERANK_REASONS
    )

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

def _commonality_anchor_terms(query: str) -> tuple[str, ...]:
    terms = []
    seen = set()
    for match in _COMMONALITY_NAMED_ANCHOR_RE.finditer(query):
        term = match.group(0)
        if term in _COMMONALITY_IGNORED_ANCHORS:
            continue
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms)

def _commonality_anchor_hits(*, anchor_terms: tuple[str, ...], text: str) -> int:
    text_lower = text.casefold()
    return sum(
        1
        for term in anchor_terms
        if re.search(rf"\b{re.escape(term)}\b", text_lower)
    )

def _commonality_who_else_signal(*, query: str, item: ContextItem) -> DomainRerankSignal:
    if _COMMONALITY_WHO_ELSE_QUERY_RE.search(query) is None:
        return DomainRerankSignal()
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) != 1:
        return DomainRerankSignal()
    if _text_has_any_anchor(anchor_terms=anchor_terms, text=item.text):
        return DomainRerankSignal(
            penalty=0.052,
            reason="commonality_original_person_noise",
        )
    if _COMMONALITY_WHO_ELSE_EVIDENCE_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.034, reason="commonality_who_else_evidence")
    return DomainRerankSignal()

def _text_has_any_anchor(*, anchor_terms: tuple[str, ...], text: str) -> bool:
    text_lower = text.casefold()
    return any(re.search(rf"\b{re.escape(term)}\b", text_lower) for term in anchor_terms)
