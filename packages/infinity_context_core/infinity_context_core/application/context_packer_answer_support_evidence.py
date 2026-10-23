"""Exact answer predicates and domain evidence ranking policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_packer_answer_support_content import (
    _business_commonality_answer_content_rank,
    _inspiration_source_answer_content_rank,
    _precise_answer_content_rank,
    _screenplay_rejection_answer_content_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE,
    _COMMON_INTEREST_MOVIE_SEEN_QUERY_RE,
    _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE,
    _COMMON_INTEREST_MOVIE_SLOT_RE,
    _COMMON_INTEREST_PERSONAL_DESSERT_PREFERENCE_RE,
    _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE,
    _COMMON_INTEREST_SELF_DESSERT_EVIDENCE_RE,
    _COMMON_INTEREST_SHARED_DESSERT_BRIDGE_RE,
    _DIALOGUE_MARKER_RE,
    _EXACT_PRECISE_CONTENT_TURN_REASONS,
    _INSPIRATION_SOURCE_QUERY_RE,
    _RECOGNITION_CERTIFICATE_QUERY_RE,
    _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _aggregation_marker_coverage_slot,
    _animal_evidence_answer_slot_from_family,
    _career_answer_slot,
    _career_answer_slot_from_family,
    _common_interest_answer_slot,
    _common_interest_answer_slot_from_family,
    _common_interest_answer_slot_priority,
    _general_activity_answer_slot_for_text,
    _inventory_answer_slot,
    _inventory_answer_slot_from_family,
    _is_common_interest_answer_reason,
    _is_conversational_support_turn,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_query_reason,
    _diagnostic_score_signals,
    _diversity_family_base,
    _has_any_exact_turn_source_ref,
    _has_primary_exact_turn_source_ref,
    _inventory_first_mention_rank,
    _is_business_commonality_reason,
    _numeric_signal,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
    relationship_status_answer_rank,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    is_themed_location_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_source_siblings import (
    _query_person_matches_text as _source_sibling_query_person_matches_text,
)
from infinity_context_core.application.context_source_siblings import (
    is_named_preference_source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem

_EN_SHARED_VOLUNTEERING_QUERY_RE = re.compile(
    r"\b(?:both|common|shared|mutual)\b(?=.{0,160}\bvolunteer(?:ed|ing|s)?\b)|"
    r"\bvolunteer(?:ed|ing|s)?\b(?=.{0,160}\b(?:both|common|shared|mutual)\b)|"
    r"\bwhat\s+type\s+of\s+volunteering\b",
    re.IGNORECASE | re.DOTALL,
)

_SHARED_VOLUNTEERING_QUERY_REASONS = frozenset(
    {
        "decomposition-inventory-list",
        "volunteering-inventory-bridge",
    }
)

_SHARED_VOLUNTEERING_FIRST_MENTION_SLOTS = frozenset(
    {
        "shelter",
        "shelter_activity",
        "shelter_anchor",
        "shelter_service_activity",
    }
)

_RELATIONSHIP_STATUS_SELF_DISCLOSURE_RE = re.compile(
    r"\b(?:my|our)\s+(?:husband|wife|spouse|boyfriend|girlfriend|fianc[eé]e?|"
    r"romantic\s+partner|life\s+partner)\b|"
    r"\b(?:i|we)\s+(?:got\s+married|am\s+married|are\s+married|was\s+married|"
    r"were\s+married)\b|"
    r"\b(?:i'm|we're)\s+married\b|"
    r"\bwhere\s+i\s+got\s+married\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_QUESTION_ONLY_RE = re.compile(
    r"\b(?:are\s+you\s+married|have\s+you\s+been\s+married|"
    r"how\s+long\s+have\s+you\s+been\s+married|"
    r"what\s+do\s+you\s+value\s+in\s+your\s+relationship|"
    r"do\s+you\s+have\s+(?:a\s+)?(?:husband|wife|spouse|partner))\?",
    re.IGNORECASE,
)

_NEUTRAL_FIRST_MENTION_RANK = (9999, 9999)

def _answer_support_inventory_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return ""
    return _inventory_answer_slot_from_family(family)

def _answer_support_animal_evidence_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_animal_evidence_slot",
        "query_reason_animal_evidence_slot_source_group",
    }:
        return ""
    return _animal_evidence_answer_slot_from_family(family)

def _answer_support_career_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_career_slot",
        "query_reason_career_slot_marker_source_group",
        "query_reason_career_slot_source_group",
    }:
        return ""
    return _career_answer_slot_from_family(family)

def _answer_support_common_interest_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_common_interest_slot",
        "query_reason_common_interest_slot_source_group",
        "query_reason_common_interest_slot_marker_source_group",
    }:
        return ""
    return _common_interest_answer_slot_from_family(family)

def _relationship_status_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not is_relationship_status_answer_evidence(
        expansion_reason=query_reason,
        text=item.text,
    ):
        return 9
    if query and not _source_sibling_query_person_matches_text(
        expansion_query=query,
        text=item.text,
    ):
        return 8
    answer_rank = relationship_status_answer_rank(item.text)
    if answer_rank >= 9:
        return answer_rank
    if _RELATIONSHIP_STATUS_SELF_DISCLOSURE_RE.search(item.text) is not None:
        return answer_rank
    if _RELATIONSHIP_STATUS_QUESTION_ONLY_RE.search(item.text) is not None:
        return min(8, answer_rank + 5)
    if _has_any_exact_turn_source_ref(item):
        return min(8, answer_rank + 1)
    return min(8, answer_rank + 2)

def _is_relationship_status_direct_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    return (
        _relationship_status_answer_support_rank(
            item,
            query=query,
            query_reason=_answer_support_query_reason(item),
        )
        <= 1
    )

def _is_exact_conversational_support_family(family: str, *, item: ContextItem) -> bool:
    return (
        _diversity_family_base(family) == "query_reason_exact_marker_source_group"
        and _is_conversational_support_turn(item)
    )

def _is_exact_named_game_inventory_answer_support_item(
    family: str,
    *,
    item: ContextItem,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason != "board_game_inventory_bridge":
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    return (
        _inventory_answer_slot(item, query_reason=query_reason).startswith("game_named_")
        and _has_any_exact_turn_source_ref(item)
    )

def _is_exact_animal_evidence_answer_family(
    family: str,
    *,
    item: ContextItem,
) -> bool:
    return bool(_answer_support_animal_evidence_family_slot(family)) and (
        _has_any_exact_turn_source_ref(item)
    )

def _is_exact_precise_content_answer_support_item(item: ContextItem) -> bool:
    if not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    if query_reason not in _EXACT_PRECISE_CONTENT_TURN_REASONS:
        return False
    return _precise_answer_content_rank(item, query_reason=query_reason) == 0

def _is_exact_named_preference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    if query_reason.replace("_", "-") not in {
        "decomposition-inference-support",
        "original-query",
    }:
        return False
    if (
        _numeric_signal(_diagnostic_score_signals(item).get("source_sibling_answer_evidence"))
        <= 0
    ):
        return False
    return is_named_preference_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )

def _is_exact_themed_location_inference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    return is_themed_location_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )

def _is_exact_business_direct_answer_support_item(item: ContextItem) -> bool:
    return (
        _answer_support_query_reason(item)
        in {"business_commonality_bridge", "business_start_reason_bridge"}
        and _has_any_exact_turn_source_ref(item)
        and _business_commonality_answer_content_rank(item.text) == 0
    )

def _is_exact_screenplay_rejection_answer_support_item(item: ContextItem) -> bool:
    return (
        _answer_support_query_reason(item) == "screenplay_count_bridge"
        and _has_any_exact_turn_source_ref(item)
        and _screenplay_rejection_answer_content_rank(item.text) == 0
    )

def _is_exact_common_interest_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    return (
        _is_common_interest_answer_reason(query_reason)
        and _has_primary_exact_turn_source_ref(item)
        and bool(_common_interest_answer_slot(item, query_reason=query_reason))
    )

def _is_exact_inspiration_source_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    return (
        bool(query and _INSPIRATION_SOURCE_QUERY_RE.search(query))
        and _has_any_exact_turn_source_ref(item)
        and _inspiration_source_answer_content_rank(item.text) == 0
    )

def _is_exact_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    if not _has_any_exact_turn_source_ref(item):
        return False
    return _is_cause_inventory_answer_support_item(item)

def _is_single_exact_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    return (
        len(item.source_refs) == 1
        and _has_primary_exact_turn_source_ref(item)
        and _is_cause_inventory_answer_support_item(item)
    )

def _is_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason not in {
        "cause_event_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    }:
        return False
    return bool(_inventory_answer_slot(item, query_reason=query_reason))

def _common_interest_first_mention_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> tuple[int, int]:
    return _inventory_first_mention_rank(
        source_id=_primary_exact_turn_source_id(item),
        query=query,
        enabled=(
            _is_common_interest_answer_reason(query_reason)
            and _is_exact_common_interest_answer_support_item(item)
        ),
    )

def _shared_volunteering_first_mention_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> tuple[int, int]:
    if (
        query_reason.replace("_", "-") not in _SHARED_VOLUNTEERING_QUERY_REASONS
        or _EN_SHARED_VOLUNTEERING_QUERY_RE.search(query) is None
    ):
        return _NEUTRAL_FIRST_MENTION_RANK
    slot = _inventory_answer_slot(item, query_reason=query_reason).replace("-", "_")
    if slot not in _SHARED_VOLUNTEERING_FIRST_MENTION_SLOTS:
        return _NEUTRAL_FIRST_MENTION_RANK
    return _inventory_first_mention_rank(
        source_id=_primary_exact_turn_source_id(item),
        query=query,
        enabled=True,
    )

def _career_exact_turn_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not _career_answer_slot(item, query_reason=query_reason):
        return 0
    if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    if _has_any_exact_turn_source_ref(item):
        return 1
    return 2

def _recognition_award_visual_answer_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "recognition_award_bridge":
        return 1
    if _RECOGNITION_CERTIFICATE_QUERY_RE.search(query) is None:
        return 1
    if not _has_any_exact_turn_source_ref(item):
        return 1
    return 0 if _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE.search(item.text) else 1

def _common_interest_movie_seen_query_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and _COMMON_INTEREST_MOVIE_SEEN_QUERY_RE.search(query) is not None
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE.search(text) is not None:
        return 4
    if _COMMON_INTEREST_MOVIE_SLOT_RE.search(text) is not None:
        return 2
    return 5

_COMMON_INTEREST_ANIMAL_ANSWER_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+animals?\b|"
    r"\banimals?\b(?=.{0,140}\b(?:both|same|shared|share|like|likes|"
    r"love|loves|enjoy|enjoys|prefer|prefers)\b)|"
    r"\b(?:both|same|shared|share|like|likes|love|loves|enjoy|enjoys|"
    r"prefer|prefers)\b(?=.{0,140}\banimals?\b)",
    re.IGNORECASE | re.DOTALL,
)

_COMMON_INTEREST_EXPLICIT_ANIMAL_CHOICE_RE = re.compile(
    r"\b(?:drawn\s+to|chose|choose|chooses|like|likes|love|loves|"
    r"enjoy|enjoys|prefer|prefers)\s+(?:the\s+|these\s+|those\s+|my\s+|"
    r"their\s+|a\s+|an\s+)?(?:turtles?|pets?|animals?|reptiles?)\b|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,180}\b(?:drawn|unique|slow\s+pace|low[-\s]?maintenance|"
    r"calming|calm|love|loves|like|likes|enjoy|enjoys|prefer|prefers)\b)",
    re.IGNORECASE | re.DOTALL,
)

_COMMON_INTEREST_ANIMAL_FALSE_FRIEND_RE = re.compile(
    r"\banimals?\s+like\b|"
    r"\bother\s+animals?\b(?=.{0,120}\b(?:consider|allerg(?:y|ic)|"
    r"pictures?|pics?)\b)|"
    r"\b(?:send|sending)\s+(?:you\s+)?(?:pictures?|pics?)\b",
    re.IGNORECASE | re.DOTALL,
)

def _common_interest_animal_answer_shape_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and query
        and _COMMON_INTEREST_ANIMAL_ANSWER_QUERY_RE.search(query) is not None
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_ANIMAL_FALSE_FRIEND_RE.search(text) is not None:
        return 4
    if _COMMON_INTEREST_EXPLICIT_ANIMAL_CHOICE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 1
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 2
    return 5

_ACTIVITY_COMPETITION_VISUAL_QUERY_RE = re.compile(
    r"\b(?:dancers?|photo|picture|image|dance\s+festival|festival|"
    r"attitude|participat(?:e|ing)|part\s+of)\b",
    re.IGNORECASE,
)

_ACTIVITY_COMPETITION_ATTITUDE_QUERY_RE = re.compile(
    r"\b(?:attitude|participat(?:e|ing)|part\s+of)\b",
    re.IGNORECASE,
)

_ACTIVITY_COMPETITION_DANCER_REPLY_RE = re.compile(
    r"\b(?:dancers?|they(?:'re| are)|ones?)\b"
    r"(?=.{0,220}\b(?:perform(?:ing|ance)?|grace|graceful|"
    r"skill|practic(?:e|ed|ing)|impress)\b)",
    re.IGNORECASE | re.DOTALL,
)

_ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE = re.compile(
    r"\b(?:glad\s+to\s+be\s+part\s+of\s+it|part\s+of\s+it|"
    r"awesome|excited)\b",
    re.IGNORECASE | re.DOTALL,
)

_ACTIVITY_COMPETITION_VISUAL_ANSWER_RE = re.compile(
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,260}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)",
    re.IGNORECASE | re.DOTALL,
)

def _activity_competition_visual_answer_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "activity_competition_evidence_bridge":
        return 0
    if not query or _ACTIVITY_COMPETITION_VISUAL_QUERY_RE.search(query) is None:
        return 0
    if _ACTIVITY_COMPETITION_ATTITUDE_QUERY_RE.search(query) is not None:
        if _ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE.search(item.text) is not None:
            return 0
        if _ACTIVITY_COMPETITION_VISUAL_ANSWER_RE.search(item.text) is not None:
            return 2
        if _general_activity_answer_slot_for_text(item.text.casefold()):
            return 3
        return 5
    if _ACTIVITY_COMPETITION_DANCER_REPLY_RE.search(item.text) is not None:
        return 0
    if _ACTIVITY_COMPETITION_VISUAL_ANSWER_RE.search(item.text) is not None:
        return 1
    if _ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE.search(item.text) is not None:
        return 2
    if _general_activity_answer_slot_for_text(item.text.casefold()):
        return 3
    return 5

def _common_interest_direct_evidence_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and _is_exact_common_interest_answer_support_item(item)
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_MOVIE_SLOT_RE.search(text) is not None:
        if _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE.search(text) is not None:
            return 2
        return 0
    if _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_SHARED_DESSERT_BRIDGE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_SELF_DESSERT_EVIDENCE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_PERSONAL_DESSERT_PREFERENCE_RE.search(text) is not None:
        return 2
    return 1

def _common_interest_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _is_common_interest_answer_reason(query_reason):
        return 0
    slot = _common_interest_answer_slot(item, query_reason=query_reason)
    if not slot:
        return 5
    slot_priority = _common_interest_answer_slot_priority(slot)
    if _has_any_exact_turn_source_ref(item):
        return slot_priority
    return min(slot_priority + 1, 4)

def _is_direct_outdoor_activity_answer_support_item(
    item: ContextItem,
    *,
    query: str,
    family: str,
) -> bool:
    if not query or not re.search(
        r"\b(?:outdoor|outdoors|hiking|hike|mountaineering|picnic|"
        r"waterfall|colleagues?|workmates?|friends?)\b",
        query,
        re.IGNORECASE,
    ):
        return False
    if _answer_support_query_reason(item) != "outdoor_activity_inventory_bridge":
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    slot = _inventory_answer_slot(item, query_reason="outdoor_activity_inventory_bridge")
    return slot in {
        "outdoor_visual_group",
        "outdoor_mountaineering",
        "outdoor_hiking",
        "outdoor_picnic",
        "outdoor_waterfall",
    }

def _birdwatching_city_schedule_exact_turn_rank(item: ContextItem, *, query_reason: str) -> int:
    if query_reason != "birdwatching_city_schedule_bridge":
        return 0
    if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    return 1

def _marker_coverage_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _aggregation_marker_coverage_slot(item, query_reason=query_reason):
        return 0
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(item.text))
    )
    return -len(markers)

def _business_dialogue_marker_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not _is_business_commonality_reason(query_reason):
        return 0
    if _business_commonality_answer_content_rank(item.text) > 1:
        return 1
    return 0 if _DIALOGUE_MARKER_RE.search(item.text) is not None else 1
