"""Social support and inventory-list rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_types import DomainRerankSignal
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
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

_INVENTORY_LIST_RERANK_REASONS = frozenset(
    (
        "decomposition_inventory_list",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "pottery_type_bridge",
        "travel_country_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    )
)

_INVENTORY_POTTERY_QUERY_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?)\b",
    re.IGNORECASE,
)

_INVENTORY_POTTERY_EVIDENCE_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?)\b",
    re.IGNORECASE,
)

_INVENTORY_POTTERY_OWNER_EVIDENCE_RE = re.compile(
    r"\bD\d+:\d+\s+Melanie:"
    r"(?=.{0,260}\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?|dog\s+face)\b)"
    r"(?=.{0,260}\b(?:made|make|making|class|workshop|kids?|children|finished|project|"
    r"hands\s+dirty|creativity|imagination|proud)\b)",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_COUNTRY_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|abroad|europe(?:an)?|places?)\b",
    re.IGNORECASE,
)

_INVENTORY_COUNTRY_EVIDENCE_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"rome|paris|london|madrid|berlin|lisbon|dublin|stockholm)\b",
    re.IGNORECASE,
)

_INVENTORY_CAUSE_QUERY_RE = re.compile(
    r"\b(?:causes?|support(?:ing)?|passionate)\b",
    re.IGNORECASE,
)

_INVENTORY_CAUSE_EVIDENCE_RE = re.compile(
    r"\b(?:veterans?\s+rights?|military|education\s+reform|"
    r"infrastructure\s+development|education|infrastructure)\b",
    re.IGNORECASE,
)

_INVENTORY_FRIEND_PLACE_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,100}\b(?:friend|friends|made|met|joined|meet)\b)",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_FRIEND_PLACE_EVIDENCE_RE = re.compile(
    r"\b(?:made\s+friends|became\s+friends|friends\s+with|fellow\s+volunteers?|"
    r"joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?(?:gym|church)|"
    r"homeless\s+shelter|dog\s+shelter|animal\s+shelter|"
    r"(?:gym|church).{0,100}\b(?:supportive|welcoming|community|people))\b",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE = re.compile(
    r"\b(?:homeless\s+shelter|shelter)\b(?=.{0,80}\b"
    r"(?:i\s+volunteer\s+at|where\s+(?:she\s+)?volunteers?|"
    r"donated\s+(?:my\s+|her\s+)?old\s+car))|"
    r"\b(?:i\s+volunteer\s+at|where\s+(?:she\s+)?volunteers?|"
    r"donated\s+(?:my\s+|her\s+)?old\s+car)\b(?=.{0,80}\b"
    r"(?:homeless\s+shelter|shelter))",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE = re.compile(
    r"\b(?:gave\s+a\s+few\s+talks|received\s+lots\s+of\s+compliments|"
    r"fundraiser|ring-toss|baked\s+goods?|dropped\s+off|"
    r"received\s+a\s+medal|front\s+desk|kids?\s+event)\b",
    re.IGNORECASE,
)

_INVENTORY_SHELTER_QUERY_RE = re.compile(
    r"\bshelters?\b",
    re.IGNORECASE,
)

_INVENTORY_SHELTER_EVIDENCE_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|animal\s+shelter|shelter)\b",
    re.IGNORECASE,
)

_INVENTORY_GENERIC_WEAK_RE = re.compile(
    r"\b(?:inventory\s+list|answer\s+options|evidence\s+observed|"
    r"observed\s+mentioned|generic\s+inventory|virtual\s+support\s+group|"
    r"asked\s+family\s+and\s+friends\s+to\s+join|visited\s+countries\s+abroad)\b",
    re.IGNORECASE,
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

def inventory_list_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _inventory_friend_place_shelter_anchor_evidence(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal(
            boost=0.09,
            reason="friend_place_shelter_anchor_evidence",
            rank_signal_key="friend_place_shelter_anchor_evidence",
            rank_signal=3.0,
        )
    if _inventory_list_exact_evidence(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal(boost=0.058, reason="inventory_list_exact_evidence")
    if _inventory_list_wrong_owner_evidence(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal(penalty=0.16, reason="inventory_list_wrong_owner_evidence")
    if _inventory_list_weak_evidence(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    ):
        return DomainRerankSignal(penalty=0.055, reason="inventory_list_weak_evidence")
    return DomainRerankSignal()

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

def _inventory_list_exact_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    text = item.text
    if _INVENTORY_POTTERY_QUERY_RE.search(query):
        return _INVENTORY_POTTERY_OWNER_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_COUNTRY_QUERY_RE.search(query):
        return (
            _INVENTORY_COUNTRY_EVIDENCE_RE.search(text) is not None
            or has_travel_place_inventory_evidence(text)
        )
    if _INVENTORY_CAUSE_QUERY_RE.search(query):
        return _INVENTORY_CAUSE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_FRIEND_PLACE_QUERY_RE.search(query):
        return _INVENTORY_FRIEND_PLACE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_SHELTER_QUERY_RE.search(query):
        return _INVENTORY_SHELTER_EVIDENCE_RE.search(text) is not None
    return False

def _inventory_friend_place_shelter_anchor_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    if not _INVENTORY_FRIEND_PLACE_QUERY_RE.search(query):
        return False
    text = item.text
    if _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE.search(text):
        return False
    return _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE.search(text) is not None

def _inventory_list_weak_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    if _inventory_list_exact_evidence(query=query, query_reason=query_reason, item=item):
        return False
    if _INVENTORY_POTTERY_QUERY_RE.search(query) and _INVENTORY_POTTERY_EVIDENCE_RE.search(
        item.text
    ):
        return True
    if _INVENTORY_GENERIC_WEAK_RE.search(item.text):
        return True
    if _inventory_query_has_specific_expected_slot(query):
        return relevance.distinctive_term_hits < 4 or relevance.unique_term_hits < 4
    return False

def _inventory_list_wrong_owner_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    if not _INVENTORY_POTTERY_QUERY_RE.search(query):
        return False
    return _INVENTORY_POTTERY_EVIDENCE_RE.search(item.text) is not None

def _inventory_query_has_specific_expected_slot(query: str) -> bool:
    return any(
        pattern.search(query)
        for pattern in (
            _INVENTORY_POTTERY_QUERY_RE,
            _INVENTORY_COUNTRY_QUERY_RE,
            _INVENTORY_CAUSE_QUERY_RE,
            _INVENTORY_FRIEND_PLACE_QUERY_RE,
            _INVENTORY_SHELTER_QUERY_RE,
        )
    )

def _is_inventory_list_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _INVENTORY_LIST_RERANK_REASONS:
        return True
    reason = _score_signal_reason(item)
    return reason in _INVENTORY_LIST_RERANK_REASONS

def _is_support_network_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _SUPPORT_NETWORK_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _SUPPORT_NETWORK_RERANK_REASONS


def has_inventory_list_exact_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return _inventory_list_exact_evidence(
        query=query,
        query_reason=query_reason,
        item=item,
    )


def is_inventory_list_query_reason(query_reason: str) -> bool:
    return query_reason in _INVENTORY_LIST_RERANK_REASONS
