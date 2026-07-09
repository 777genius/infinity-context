"""Identity fact, object, and emotion rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_types import DomainRerankSignal
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
    has_item_purchase_object_marker,
    has_item_purchase_temporal_or_media_marker,
    has_item_purchase_verb_marker,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

_AGE_BIRTHDAY_RERANK_REASONS = frozenset(("age_birthday_bridge",))

_BIRTHPLACE_RERANK_REASONS = frozenset(("birthplace_origin_bridge",))

_BEACH_OR_MOUNTAINS_RERANK_REASONS = frozenset(("beach_or_mountains_inference_bridge",))

_ITEM_PURCHASE_RERANK_REASONS = frozenset(("item_purchase_bridge",))

_SYMBOL_IMPORTANCE_RERANK_REASONS = frozenset(("symbol_importance_bridge",))

_POST_EVENT_EMOTION_RERANK_REASONS = frozenset(("post_event_emotion_bridge",))

_AGE_BIRTHDAY_EXACT_RE = re.compile(
    r"\b(?:born\s+in\s+\d{4}|born\s+on\b|date\s+of\s+birth|birthdate|"
    r"birthday|age\s+(?:is\s+)?\d{1,3}|\d{1,3}\s+years?\s+old)\b|"
    r"\b(?:родил(?:ся|ась|ись)\s+в\s+\d{4}|дата\s+рождения|"
    r"день\s+рождения|возраст\s+\d{1,3}|\d{1,3}\s+лет)\b",
    re.IGNORECASE,
)

_AGE_BIRTHDAY_WEAK_OLD_RE = re.compile(
    r"\bold\s+(?:friend|plan|state|policy|note|home|school|job)\b|"
    r"\b(?:стар(?:ый|ая|ое|ые)\s+(?:друг|план|политик\w*|заметк\w*))\b",
    re.IGNORECASE,
)

_BIRTHPLACE_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,80}\bborn\b)|\bborn\b(?=.{0,80}\bwhere\b)|"
    r"\b(?:где|откуда)\b(?=.{0,80}\bродил)",
    re.IGNORECASE | re.DOTALL,
)

_BIRTHPLACE_EXACT_RE = re.compile(
    r"\b(?:birthplace|born\s+in\s+(?!\d{4}\b)[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?|"
    r"born\s+near\s+[A-Z][A-Za-z]+|home\s+country\s+is\s+[A-Z][A-Za-z]+)\b|"
    r"\b(?:место\s+рождения|родил(?:ся|ась|ись)\s+в\s+(?!\d{4}\b)[А-ЯЁA-Z]"
    r"[\wА-Яа-яЁё-]+)\b",
    re.IGNORECASE,
)

_BIRTHPLACE_BIRTHDATE_NOISE_RE = re.compile(
    r"\bborn\s+in\s+\d{4}\b|\b(?:birthday|date\s+of\s+birth|birthdate)\b|"
    r"\bродил(?:ся|ась|ись)\s+в\s+\d{4}\b|\b(?:дата\s+рождения|день\s+рождения)\b",
    re.IGNORECASE,
)

_BEACH_OR_MOUNTAINS_QUERY_RE = re.compile(
    r"\b(?:beach|beaches|ocean|shore|coast|mountain|mountains)\b"
    r"(?=.{0,120}\b(?:close|near|nearby|live|lives|living|by|next\s+to)\b)|"
    r"\b(?:close|near|nearby|live|lives|living|by|next\s+to)\b"
    r"(?=.{0,120}\b(?:beach|beaches|ocean|shore|coast|mountain|mountains)\b)",
    re.IGNORECASE | re.DOTALL,
)

_BEACH_OR_MOUNTAINS_DOMAIN_RE = re.compile(
    r"\b(?:beach|beaches|ocean|shore|coast|coastal|sailboat|sand|sunset|"
    r"mountain|mountains|trail|hiking|hike)\b",
    re.IGNORECASE,
)

_BEACH_OR_MOUNTAINS_PROXIMITY_RE = re.compile(
    r"\b(?:close|near|nearby|by|next\s+to|weekly\s+walks?|walks?|goes?\s+on\s+"
    r"walks?|lives?\s+close|lives?\s+near|from\s+home|local)\b",
    re.IGNORECASE,
)

_BEACH_OR_MOUNTAINS_TOPIC_ONLY_RE = re.compile(
    r"\b(?:whether|sounded\s+nice|someday|maybe|vacation|wallpaper|poster|"
    r"preference|would\s+like|dream(?:ed)?\s+of)\b"
    r"(?=.{0,120}\b(?:beach|beaches|ocean|mountains?)\b)|"
    r"\b(?:beach|beaches|ocean|mountains?)\b"
    r"(?=.{0,120}\b(?:whether|sounded\s+nice|someday|maybe|vacation|"
    r"wallpaper|poster|preference|would\s+like|dream(?:ed)?\s+of)\b)",
    re.IGNORECASE | re.DOTALL,
)

_SYMBOL_IMPORTANCE_EXACT_RE = re.compile(
    r"\b(?:symboli[sz](?:e|es|ed|ing)|represents?|meaning|means|stands?\s+for|"
    r"important|reminds?\s+(?:me|her|him|them)\s+of|pride|freedom|courage|"
    r"resilience|identity|acceptance)\b|"
    r"\b(?:символизир\w*|значит|значение|важн\w*|напомина\w*|гордост\w*|"
    r"свобод\w*|смелост\w*|идентичност\w*|приняти\w*)\b",
    re.IGNORECASE,
)

_SYMBOL_IMPORTANCE_MEANING_RE = re.compile(
    r"\b(?:symboli[sz](?:e|es|ed|ing)|represents?|meaning|means|stands?\s+for|"
    r"reminds?\s+(?:me|her|him|them)\s+of|pride|freedom|courage|resilience|"
    r"identity|acceptance)\b|"
    r"\b(?:символизир\w*|значит|значение|напомина\w*|гордост\w*|свобод\w*|"
    r"смелост\w*|идентичност\w*|приняти\w*)\b",
    re.IGNORECASE,
)

_SYMBOL_IMPORTANCE_OBJECT_RE = re.compile(
    r"\b(?:rainbow\s+flag|flag|mural|eagle|pendant|necklace|"
    r"transgender\s+symbol|cross|heart|symbol|symbols)\b|"
    r"\b(?:радужн\w+\s+флаг|флаг|орел|орёл|кулон|ожерелье|крест|"
    r"сердце|символ\w*)\b",
    re.IGNORECASE,
)

_SYMBOL_IMPORTANCE_PERSONAL_OBJECT_RE = re.compile(
    r"\b(?:pendant|necklace)\b(?=.{0,100}\b(?:symbol|cross|heart|transgender)\b)|"
    r"\b(?:symbol|cross|heart|transgender)\b(?=.{0,100}\b(?:pendant|necklace)\b)",
    re.IGNORECASE | re.DOTALL,
)

_SYMBOL_IMPORTANCE_VISUAL_OBJECT_RE = re.compile(
    r"\b(?:visual\s+query|image\s+caption|caption)\b"
    r"(?=.{0,140}\b(?:pendant|necklace)\b)"
    r"(?=.{0,140}\b(?:transgender\s+symbol|cross|heart|symbol)\b)",
    re.IGNORECASE | re.DOTALL,
)

_SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE = re.compile(
    r"\b(?:unicode|currency|math(?:ematical)?|keyboard|font|icon|icons|"
    r"svg|css|ui|interface|variable|operator|code|programming)\b",
    re.IGNORECASE,
)

_POST_EVENT_EMOTION_EXACT_RE = re.compile(
    r"\b(?:felt|feel|feeling|grateful|thankful|relieved|lucky|scared|"
    r"freaked|inspired|proud|happy|sad|upset|awe|means?\s+the\s+world|"
    r"meaningful)\b",
    re.IGNORECASE,
)

_POST_EVENT_FAMILY_APPRECIATION_RE = re.compile(
    r"\b(?:i|i'm|i've|me|my|we|our)\b"
    r"(?=.{0,220}\b(?:family|fam|loved\s+ones|them|they)\b)"
    r"(?=.{0,180}\b(?:super\s+important|important\s+to\s+me|"
    r"mean\s+the\s+world|means\s+the\s+world|need\s+them|"
    r"thankful\s+to\s+have|grateful\s+to\s+have|cherish|"
    r"biggest\s+motivation|support|rock)\b)|"
    r"\b(?:super\s+important|important\s+to\s+me|mean\s+the\s+world|"
    r"means\s+the\s+world|need\s+them|thankful\s+to\s+have|"
    r"grateful\s+to\s+have|cherish|biggest\s+motivation|support|rock)\b"
    r"(?=.{0,180}\b(?:family|fam|loved\s+ones|them|they)\b)"
    r"(?=.{0,220}\b(?:i|i'm|i've|me|my|we|our)\b)",
    re.IGNORECASE | re.DOTALL,
)

_POST_EVENT_EMOTION_EVENT_ONLY_RE = re.compile(
    r"\b(?:accident|roadtrip|trip|event|happened|mentioned|talked|family)\b",
    re.IGNORECASE,
)

def age_birthday_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_age_birthday_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if (
        _BIRTHPLACE_QUERY_RE.search(query) is not None
        and _AGE_BIRTHDAY_EXACT_RE.search(item.text) is not None
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="age_birthday_birthplace_query_noise",
        )
    if _AGE_BIRTHDAY_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="age_birthday_exact_evidence")
    if (
        _AGE_BIRTHDAY_WEAK_OLD_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.05, reason="age_birthday_weak_evidence")
    return DomainRerankSignal()

def birthplace_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_birthplace_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _BIRTHPLACE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="birthplace_exact_evidence")
    if (
        _BIRTHPLACE_BIRTHDATE_NOISE_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.052, reason="birthplace_birthdate_noise")
    return DomainRerankSignal()

def beach_or_mountains_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_beach_or_mountains_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    has_domain = _BEACH_OR_MOUNTAINS_DOMAIN_RE.search(item.text) is not None
    has_proximity = _BEACH_OR_MOUNTAINS_PROXIMITY_RE.search(item.text) is not None
    if has_domain and has_proximity:
        return DomainRerankSignal(
            boost=0.026,
            reason="beach_mountains_proximity_evidence",
        )
    if (
        _BEACH_OR_MOUNTAINS_TOPIC_ONLY_RE.search(item.text) is not None
        or not has_domain
        or relevance.distinctive_term_hits < 3
    ):
        return DomainRerankSignal(
            penalty=0.038,
            reason="beach_mountains_topic_only_noise",
        )
    return DomainRerankSignal()

def item_purchase_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_item_purchase_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if has_item_purchase_object_evidence(item.text):
        return DomainRerankSignal(
            boost=0.055,
            reason="item_purchase_object_evidence",
            rank_signal_key="item_purchase_object_evidence",
            rank_signal=3.0,
        )
    if (
        has_item_purchase_temporal_or_media_marker(item.text)
        or not has_item_purchase_object_marker(item.text)
        or not has_item_purchase_verb_marker(item.text)
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.11,
            reason="item_purchase_temporal_weak_evidence",
        )
    return DomainRerankSignal()

def symbol_importance_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_symbol_importance_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    has_symbol_object = _SYMBOL_IMPORTANCE_OBJECT_RE.search(item.text) is not None
    has_personal_object = _SYMBOL_IMPORTANCE_PERSONAL_OBJECT_RE.search(item.text) is not None
    if _SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE.search(item.text) is not None:
        return DomainRerankSignal(penalty=0.042, reason="symbol_importance_weak_evidence")
    if has_personal_object and _SYMBOL_IMPORTANCE_VISUAL_OBJECT_RE.search(item.text):
        return DomainRerankSignal(
            boost=0.036,
            reason="symbol_importance_visual_object",
            rank_signal_key="symbol_importance_visual_evidence",
            rank_signal=3.0,
        )
    if has_symbol_object and _SYMBOL_IMPORTANCE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="symbol_importance_exact_evidence",
            rank_signal_key="symbol_importance_visual_evidence",
            rank_signal=1.0 if has_personal_object else 0.0,
        )
    if has_personal_object:
        return DomainRerankSignal(boost=0.02, reason="symbol_importance_personal_object")
    if (
        _SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE.search(item.text) is not None
        or not has_symbol_object
        or relevance.distinctive_term_hits < 3
    ):
        return DomainRerankSignal(penalty=0.042, reason="symbol_importance_weak_evidence")
    return DomainRerankSignal()

def post_event_emotion_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_post_event_emotion_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _POST_EVENT_FAMILY_APPRECIATION_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.052,
            reason="post_event_family_appreciation_evidence",
        )
    if _POST_EVENT_EMOTION_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="post_event_emotion_exact_evidence")
    if (
        _POST_EVENT_EMOTION_EVENT_ONLY_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.038, reason="post_event_emotion_weak_evidence")
    return DomainRerankSignal()

def _is_age_birthday_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _AGE_BIRTHDAY_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _AGE_BIRTHDAY_RERANK_REASONS

def _is_birthplace_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _BIRTHPLACE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _BIRTHPLACE_RERANK_REASONS

def _is_beach_or_mountains_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _BEACH_OR_MOUNTAINS_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _BEACH_OR_MOUNTAINS_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _BEACH_OR_MOUNTAINS_RERANK_REASONS

def _is_symbol_importance_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _SYMBOL_IMPORTANCE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _SYMBOL_IMPORTANCE_RERANK_REASONS

def _is_item_purchase_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _ITEM_PURCHASE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _ITEM_PURCHASE_RERANK_REASONS

def _is_post_event_emotion_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _POST_EVENT_EMOTION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _POST_EVENT_EMOTION_RERANK_REASONS
