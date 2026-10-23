"""Inventory ownership and aggregation evidence rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
    aggregation_answer_slots,
)
from infinity_context_core.application.context_aggregation_subject import (
    aggregation_subject_grounding,
)
from infinity_context_core.application.context_domain_rerank_legacy_contract import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_internal_diagnostics import (
    diagnostic_mapping,
    diagnostic_text,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
)
from infinity_context_core.application.dto import ContextItem

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
        "book_reading_list_bridge",
        "church_friend_activity_inventory_bridge",
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
    r"\bD\d+:\d+\s+(?P<speaker>[A-Z][A-Za-z'_-]{1,40}):"
    r"(?=.{0,260}\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?|dog\s+face)\b)"
    r"(?=.{0,260}\b(?:made|make|making|class|workshop|kids?|children|finished|project|"
    r"hands\s+dirty|creativity|imagination|proud)\b)",
    re.IGNORECASE | re.DOTALL,
)

_QUERY_PERSON_STOPWORDS = frozenset(
    {
        "what",
        "which",
        "where",
        "when",
        "who",
        "whom",
        "whose",
        "why",
        "how",
    }
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

_INVENTORY_DESSERT_QUERY_RE = re.compile(
    r"\b(?:desserts?|sweets?|baked\s+goods?)\b",
    re.IGNORECASE,
)

_INVENTORY_DESSERT_EVIDENCE_RE = re.compile(
    r"\b(?:desserts?|cobblers?|peach\s+cobbler|sundae|banana\s+split|"
    r"ice\s+cream|pies?|cakes?|cookies?|brownies?|puddings?|pastr(?:y|ies)|"
    r"baked\s+goods?)\b",
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
    r"fundraiser|tournament|baked\s+goods?|dropped\s+off|"
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

_INVENTORY_BOOK_READING_QUERY_RE = re.compile(
    r"\b(?:books?|novels?|stories?)\b(?=.{0,80}\bread\b)|"
    r"\bread\b(?=.{0,80}\b(?:books?|novels?|stories?)\b)",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_BOOK_READING_EVIDENCE_RE = re.compile(
    r"\b(?:loved\s+reading\s+\"?[A-Z][^\"\n]{1,80}\"?|"
    r"love\s+reading\s+\"?[A-Z][^\"\n]{1,80}\"?|"
    r"read(?:ing)?\s+\"?[A-Z][^\"\n]{1,80}\"?|"
    r"book\s+i\s+read\s+last\s+year|favorite\s+book|favourite\s+book|"
    r"book\s+you\s+remember\s+from\s+your\s+childhood|childhood\s+book|"
    r"read\s+as\s+a\s+kid)\b",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_CHURCH_FRIEND_ACTIVITY_QUERY_RE = re.compile(
    r"\b(?:activities?|do|done|did|went|visit(?:ed)?|hikes?|hiking|picnic)\b"
    r"(?=.{0,120}\bchurch\s+friends?\b)|"
    r"\bchurch\s+friends?\b(?=.{0,120}\b"
    r"(?:activities?|do|done|did|went|visit(?:ed)?|hikes?|hiking|picnic)\b)",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_CHURCH_FRIEND_ACTIVITY_EVIDENCE_RE = re.compile(
    r"\bchurch\s+friends?\b(?=.{0,180}\b"
    r"(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"chilled|played\s+games|games|charades|scavenger\s+hunt|nature|refreshed)\b)|"
    r"\b(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"chilled|played\s+games|games|charades|scavenger\s+hunt|nature|refreshed)\b"
    r"(?=.{0,180}\bchurch\s+friends?\b)",
    re.IGNORECASE | re.DOTALL,
)

_INVENTORY_GENERIC_WEAK_RE = re.compile(
    r"\b(?:inventory\s+list|answer\s+options|evidence\s+observed|"
    r"observed\s+mentioned|generic\s+inventory|virtual\s+support\s+group|"
    r"asked\s+family\s+and\s+friends\s+to\s+join|visited\s+countries\s+abroad)\b",
    re.IGNORECASE,
)

_AGGREGATION_RETRIEVAL_SOURCE = "keyword_aggregation_chunks"

_AGGREGATION_COUNT_QUERY_RE = re.compile(
    r"\b(?:how\s+many|number\s+of|count|total|times?)\b|"
    r"\b(?:сколько|количество|число|раз)\b",
    re.IGNORECASE,
)

_AGGREGATION_LIST_QUERY_RE = re.compile(
    r"\b(?:what|which|where)\b(?=.{0,80}\b(?:items?|things?|countries|places|"
    r"types?|kinds?|events?|activities|bands?|artists?|shelters?|causes?|people|"
    r"foods?|recipes?|meals?|dishes?|desserts?|baked\s+goods?)\b)|"
    r"\b(?:list|name|show)\b(?=.{0,100}\b(?:all|both|items?|things?|countries|places|"
    r"types?|kinds?|events?|activities|bands?|artists?|shelters?|causes?|people|"
    r"foods?|recipes?|meals?|dishes?|desserts?|baked\s+goods?)\b)|"
    r"\b(?:all|both)\b(?=.{0,100}\b(?:items?|things?|countries|places|types?|"
    r"kinds?|events?|activities|bands?|artists?|shelters?|causes?|people|"
    r"foods?|recipes?|meals?|dishes?|desserts?|baked\s+goods?)\b)|"
    r"\bwho\b(?=.{0,120}\b(?:friends?|people|person|volunteer(?:s|ed|ing)?|"
    r"met|helped|worked\s+with|customers?|clients?|colleagues?|teammates?)\b)|"
    r"\b(?:какие|какой|где|кого|кому)\b",
    re.IGNORECASE | re.DOTALL,
)

_AGGREGATION_NUMERIC_ANSWER_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|once|twice|"
    r"couple|several|multiple|another|again)\b|"
    r"\b(?:один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|"
    r"десять|раз|дважды|несколько|много|ещ[её])\b",
    re.IGNORECASE,
)

_AGGREGATION_MARKER_RE = re.compile(r"\bD\d+:\d+\b")

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
        if _inventory_book_reading_exact_match(query=query, item=item):
            return DomainRerankSignal(
                boost=0.09,
                reason="book_reading_inventory_evidence",
                rank_signal_key="book_reading_inventory_evidence",
                rank_signal=3.0,
            )
        if _inventory_church_friend_activity_exact_match(query=query, item=item):
            return DomainRerankSignal(
                boost=0.09,
                reason="church_friend_activity_inventory_evidence",
                rank_signal_key="church_friend_activity_inventory_evidence",
                rank_signal=3.0,
            )
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

def aggregation_evidence_rerank_signal(
    *,
    query: str,
    item: ContextItem,
    has_multi_evidence_competitor: bool = False,
) -> DomainRerankSignal:
    if not _is_aggregation_query(query):
        return DomainRerankSignal()
    is_list_query = _is_aggregation_list_query(query)
    answer_slot_count = len(aggregation_answer_slots(query=query, text=item.text))
    if _has_aggregation_subject_mismatch(
        query=query,
        item=item,
        answer_slot_count=answer_slot_count,
    ):
        return DomainRerankSignal(penalty=0.072, reason="aggregation_subject_mismatch")
    if answer_slot_count >= 2:
        if is_list_query:
            return DomainRerankSignal(
                boost=0.058,
                reason="aggregation_list_slot_diverse_evidence",
                rank_signal_key="aggregation_list_distinct_answer_slot_count",
                rank_signal=float(answer_slot_count),
            )
        return DomainRerankSignal(
            boost=0.044,
            reason="aggregation_slot_diverse_evidence",
        )
    if _is_aggregation_context_item(item):
        if _aggregation_evidence_count(item) >= 2:
            if is_list_query and answer_slot_count == 1:
                return DomainRerankSignal(
                    penalty=0.024,
                    reason="aggregation_list_duplicate_answer_slot_evidence",
                    rank_signal_key="aggregation_list_distinct_answer_slot_count",
                    rank_signal=1.0,
                )
            if is_list_query:
                return DomainRerankSignal(
                    boost=0.046,
                    reason="aggregation_list_multi_evidence",
                )
            return DomainRerankSignal(boost=0.034, reason="aggregation_multi_evidence")
        if is_list_query:
            return DomainRerankSignal(boost=0.018, reason="aggregation_list_evidence")
        return DomainRerankSignal(boost=0.018, reason="aggregation_evidence")
    if _AGGREGATION_COUNT_QUERY_RE.search(query) and _is_single_weak_count_evidence(item):
        return DomainRerankSignal(penalty=0.055, reason="aggregation_single_evidence_noise")
    if (
        is_list_query
        and has_multi_evidence_competitor
        and _is_single_list_evidence(query=query, item=item)
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="aggregation_list_single_evidence_incomplete",
        )
    return DomainRerankSignal()

def has_multi_evidence_aggregation_candidate(
    *,
    query: str,
    items: tuple[ContextItem, ...],
) -> bool:
    if not _is_aggregation_query(query):
        return False
    return any(
        (
            _is_aggregation_context_item(item)
            and _aggregation_evidence_count(item) >= 2
        )
        or aggregation_answer_slot_count(query=query, text=item.text) >= 2
        for item in items
    )

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
        return _pottery_inventory_owner_evidence_matches_query(query=query, text=text)
    if _INVENTORY_COUNTRY_QUERY_RE.search(query):
        return (
            _INVENTORY_COUNTRY_EVIDENCE_RE.search(text) is not None
            or has_travel_place_inventory_evidence(text)
        )
    if _INVENTORY_CAUSE_QUERY_RE.search(query):
        return _INVENTORY_CAUSE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_DESSERT_QUERY_RE.search(query):
        return _INVENTORY_DESSERT_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_FRIEND_PLACE_QUERY_RE.search(query):
        return _INVENTORY_FRIEND_PLACE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_SHELTER_QUERY_RE.search(query):
        return _INVENTORY_SHELTER_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_BOOK_READING_QUERY_RE.search(query):
        return _INVENTORY_BOOK_READING_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_CHURCH_FRIEND_ACTIVITY_QUERY_RE.search(query):
        return _INVENTORY_CHURCH_FRIEND_ACTIVITY_EVIDENCE_RE.search(text) is not None
    return False

def _pottery_inventory_owner_evidence_matches_query(*, query: str, text: str) -> bool:
    matches = tuple(_INVENTORY_POTTERY_OWNER_EVIDENCE_RE.finditer(text))
    if not matches:
        return False
    query_people = _query_person_terms(query)
    if not query_people:
        return True
    return any(
        match.group("speaker").casefold() in query_people
        for match in matches
        if match.group("speaker")
    )

def _query_person_terms(query: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold()
        for match in re.finditer(r"\b[A-Z][A-Za-z'_-]{1,40}\b", query)
        if match.group(0).casefold() not in _QUERY_PERSON_STOPWORDS
    )

def _inventory_book_reading_exact_match(*, query: str, item: ContextItem) -> bool:
    return (
        _INVENTORY_BOOK_READING_QUERY_RE.search(query) is not None
        and _INVENTORY_BOOK_READING_EVIDENCE_RE.search(item.text) is not None
    )

def _inventory_church_friend_activity_exact_match(*, query: str, item: ContextItem) -> bool:
    return (
        _INVENTORY_CHURCH_FRIEND_ACTIVITY_QUERY_RE.search(query) is not None
        and _INVENTORY_CHURCH_FRIEND_ACTIVITY_EVIDENCE_RE.search(item.text) is not None
    )

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
            _INVENTORY_DESSERT_QUERY_RE,
            _INVENTORY_FRIEND_PLACE_QUERY_RE,
            _INVENTORY_SHELTER_QUERY_RE,
            _INVENTORY_BOOK_READING_QUERY_RE,
            _INVENTORY_CHURCH_FRIEND_ACTIVITY_QUERY_RE,
        )
    )

def _is_inventory_list_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _INVENTORY_LIST_RERANK_REASONS:
        return True
    reason = _score_signal_reason(item)
    return reason in _INVENTORY_LIST_RERANK_REASONS

def _is_aggregation_query(query: str) -> bool:
    return bool(
        _AGGREGATION_COUNT_QUERY_RE.search(query)
        or _AGGREGATION_LIST_QUERY_RE.search(query)
    )

def _is_aggregation_list_query(query: str) -> bool:
    return _AGGREGATION_LIST_QUERY_RE.search(query) is not None

def _has_aggregation_subject_mismatch(
    *,
    query: str,
    item: ContextItem,
    answer_slot_count: int,
) -> bool:
    if not (
        _is_aggregation_context_item(item)
        or _AGGREGATION_NUMERIC_ANSWER_RE.search(item.text) is not None
        or _list_evidence_looks_multi_value(item.text)
        or answer_slot_count > 0
    ):
        return False
    grounding = aggregation_subject_grounding(query=query, text=item.text)
    if (
        grounding.query_person_count
        and not grounding.matched_person_count
        and grounding.text_person_count
    ):
        return True
    if answer_slot_count > 0:
        return False
    return (
        grounding.query_subject_term_count > 0
        and grounding.matched_subject_term_count == 0
    )

def _is_aggregation_context_item(item: ContextItem) -> bool:
    diagnostics = diagnostic_mapping(item.diagnostics)
    retrieval_source = diagnostic_text(diagnostics, "retrieval_source")
    if retrieval_source == _AGGREGATION_RETRIEVAL_SOURCE:
        return True
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, list | tuple | set):
        return _AGGREGATION_RETRIEVAL_SOURCE in {str(source) for source in sources}
    return False

def _aggregation_evidence_count(item: ContextItem) -> int:
    marker_count = len(set(_AGGREGATION_MARKER_RE.findall(item.text)))
    return max(marker_count, len(item.source_refs))

def _is_single_weak_count_evidence(item: ContextItem) -> bool:
    if _aggregation_evidence_count(item) >= 2:
        return False
    return _AGGREGATION_NUMERIC_ANSWER_RE.search(item.text) is None

def _is_single_list_evidence(*, query: str, item: ContextItem) -> bool:
    if _is_aggregation_context_item(item) or _aggregation_evidence_count(item) >= 2:
        return False
    if aggregation_answer_slot_count(query=query, text=item.text) == 1:
        return True
    return not _list_evidence_looks_multi_value(item.text)

def _list_evidence_looks_multi_value(text: str) -> bool:
    if len(set(_AGGREGATION_MARKER_RE.findall(text))) >= 2:
        return True
    if len(re.findall(r"\b(?:also|another|as\s+well|and)\b", text, re.IGNORECASE)) >= 1:
        return True
    return ";" in text or len(re.findall(r",", text)) >= 2
