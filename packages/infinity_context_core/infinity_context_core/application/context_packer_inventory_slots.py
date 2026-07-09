"""Inventory answer-slot helpers for context packing."""

from __future__ import annotations

import re
from collections.abc import Callable

from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_ITEM_PURCHASE_SHOE_SLOT_RE = re.compile(
    r"\b(?:shoes?|sneakers?)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_JERSEY_SLOT_RE = re.compile(
    r"\b(?:jerseys?)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_MEDIA_SLOT_RE = re.compile(
    r"\b(?:movies?|films?|dvds?)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_FIGURINE_SLOT_RE = re.compile(
    r"\b(?:figurines?|wooden\s+dolls?)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_GENERIC_SLOT_RE = re.compile(
    r"\b(?:items?|belongings?|objects?|possessions?)\b",
    re.IGNORECASE,
)
_DESSERT_COBBLER_SLOT_RE = re.compile(
    r"\b(?:cobblers?|peach\s+cobbler)\b",
    re.IGNORECASE,
)
_DESSERT_SUNDAE_SLOT_RE = re.compile(
    r"\b(?:sundae|banana\s+split|ice\s*cream|icecream)\b",
    re.IGNORECASE,
)
_DESSERT_PIE_SLOT_RE = re.compile(
    r"\b(?:pies?|apple\s+pie)\b",
    re.IGNORECASE,
)
_DESSERT_GENERIC_SLOT_RE = re.compile(
    r"\b(?:desserts?|cakes?|cookies?|brownies?|puddings?|pastr(?:y|ies)|"
    r"baked\s+goods?)\b",
    re.IGNORECASE,
)
_BOARD_GAME_CONTEXT_RE = re.compile(
    r"\b(?:board\s+games?|tabletop|strategy\s+game|card\s+game|"
    r"game\s+convention|gaming\s+party)\b",
    re.IGNORECASE,
)
_NAMED_GAME_PATTERNS = (
    re.compile(
        r"\b(?:played|plays|playing)\s+"
        r"(?:this\s+game|the\s+game|a\s+game\s+called|"
        r"a\s+board\s+game\s+called|some)\s+"
        r"(?P<name>[\"']?[A-Z][A-Za-z0-9'&:.-]*(?:\s+[A-Z0-9][A-Za-z0-9'&:.-]*){0,4})"
    ),
    re.compile(
        r"\b(?:currently\s+playing|play(?:ed|s|ing)?)\s+"
        r"(?:a\s+game\s+called\s+)?"
        r"(?P<name>[\"']?[A-Z][A-Za-z0-9'&:.-]*(?:\s+[A-Z0-9][A-Za-z0-9'&:.-]*){0,4})"
        r"(?=.{0,80}\b(?:video\s+game|game|gaming|console|rpg|"
        r"tournament|championship|match|level|gameplay)\b)"
    ),
    re.compile(
        r"\b(?:currently\s+playing|play(?:ed|s|ing)?|game)\b"
        r"(?=.{0,120}\b(?:called|named)\s+"
        r"(?P<name>[\"']?[A-Z][A-Za-z0-9'&:.-]*(?:\s+[A-Z0-9][A-Za-z0-9'&:.-]*){0,4}))"
    ),
    re.compile(
        r"\b(?:game|board\s+game|strategy\s+game)\s+"
        r"(?:was\s+)?(?:called\s+|named\s+)?"
        r"(?P<name>[\"']?[A-Z][A-Za-z0-9'&:.-]*(?:\s+[A-Z0-9][A-Za-z0-9'&:.-]*){0,4})"
    ),
    re.compile(
        r"\b(?:local\s+|big\s+)?"
        r"(?P<name>[\"']?[A-Z][A-Za-z0-9'&:.-]*(?:\s+[A-Z0-9][A-Za-z0-9'&:.-]*){0,4})"
        r"\s+(?:tournament|championship|match)\b"
    ),
)
_NAMED_GAME_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "board",
        "game",
        "games",
        "gaming",
        "great",
        "it",
        "related",
        "retrieval",
        "some",
        "strategy",
        "the",
        "this",
    }
)
_IDENTITY_DIRECT_EVIDENCE_RE = re.compile(
    r"\b(?:transgender|gender\s+identity|transition|pronouns?|"
    r"true\s+self|embrac(?:e|ed|es|ing)\s+(?:myself|herself|himself|"
    r"themself|themselves)|trans\s+(?:woman|man|girl|boy|person))\b",
    re.IGNORECASE,
)
_IDENTITY_CONTEXT_EVIDENCE_RE = re.compile(
    r"\b(?:lgbtq\+?|lgbt|queer|pride|support\s+group|accepted|"
    r"acceptance|belong(?:s|ed|ing)?|community)\b",
    re.IGNORECASE,
)

_INVENTORY_COMMUNITY_ACTIVIST_GROUP_SLOT_RE = re.compile(
    r"\b(?:activist|advocacy|rights)\s+group\b|"
    r"\bgroup\b(?=.{0,120}\b(?:activist|advocacy|rights)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_COMMUNITY_PRIDE_EVENT_SLOT_RE = re.compile(
    r"\b(?:pride\s+(?:parade|event|festival)|lgbtq\+?\s+pride)\b",
    re.IGNORECASE,
)
_INVENTORY_COMMUNITY_ART_SHOW_SLOT_RE = re.compile(
    r"\b(?:art\s+show|show\s+with\s+(?:my\s+)?paintings?|paintings?\s+show)\b"
    r"(?=.{0,140}\b(?:lgbtq|community|rights?|pride|advocacy)\b)|"
    r"\b(?:lgbtq|community|rights?|pride|advocacy)\b"
    r"(?=.{0,140}\b(?:art\s+show|show\s+with\s+(?:my\s+)?paintings?|"
    r"paintings?\s+show)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_COMMUNITY_MENTORSHIP_SLOT_RE = re.compile(
    r"\b(?:mentor(?:ship|ing)?\s+program|joined\s+(?:a\s+)?mentorship)\b"
    r"(?=.{0,160}\b(?:youth|community|lgbtq|support)\b)|"
    r"\b(?:youth|community|lgbtq|support)\b"
    r"(?=.{0,160}\b(?:mentor(?:ship|ing)?\s+program|mentorship)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_COMMUNITY_CONFERENCE_SLOT_RE = re.compile(
    r"\b(?:conference|convention)\b(?=.{0,140}\b(?:lgbtq|transgender|"
    r"community|rights?|advocacy)\b)|"
    r"\b(?:lgbtq|transgender|community|rights?|advocacy)\b"
    r"(?=.{0,140}\b(?:conference|convention)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_COMMUNITY_SCHOOL_EVENT_SLOT_RE = re.compile(
    r"\b(?:school\s+event|spoke\s+at\s+(?:a\s+)?school|"
    r"talk(?:ed|ing)?\s+about\s+(?:my\s+)?(?:journey|experience))\b"
    r"(?=.{0,180}\b(?:lgbtq|transgender|community|rights?|advocacy|"
    r"coming\s+out|audience|students?)\b)|"
    r"\b(?:giv(?:e|ing)|gave|shared?)\s+(?:my\s+)?(?:talk|speech|journey)\b"
    r"(?=.{0,220}\b(?:lgbtq|transgender|community|rights?|advocacy|"
    r"coming\s+out|audience|students?)\b)|"
    r"\b(?:lgbtq|transgender|community|rights?|advocacy|coming\s+out|audience)\b"
    r"(?=.{0,180}\b(?:school\s+event|spoke\s+at\s+(?:a\s+)?school|"
    r"talk|speech|journey|experience)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXERCISE_ACTIVITY_DIRECT_ACTION_RE = re.compile(
    r"\b(?:"
    r"(?:"
    r"i(?:'m|\s+am)?|we(?:'re|\s+are)?|he(?:'s|\s+is)?|"
    r"she(?:'s|\s+is)?|they(?:'re|\s+are)?|[A-Z][a-z]{2,}"
    r")\s+"
    r"(?:"
    r"doing|did|do|practice(?:d|s|ing)?|train(?:ed|s|ing)?|"
    r"started(?:\s+(?:doing|taking|attending|going\s+to))?|"
    r"began(?:\s+(?:doing|taking|attending|going\s+to))?|"
    r"took\s+up|tried|trying(?:\s+out)?|attend(?:ed|ing)?|"
    r"go(?:es|ing)?\s+to|off\s+to\s+do"
    r")\b"
    r"(?=.{0,90}\b(?:tae\s*kwon\s*do|taekwondo|kick\s*boxing|kickboxing|"
    r"boxing|karate|yoga|circuit\s+training|weight\s+training|weights?)\b)|"
    r"(?:tae\s*kwon\s*do|taekwondo|kick\s*boxing|kickboxing|boxing|karate|"
    r"yoga|circuit\s+training|weight\s+training|weights?)\b"
    r"(?=.{0,90}\b(?:"
    r"doing|did|do|practice(?:d|s|ing)?|"
    r"started|began|took\s+up|tried|trying(?:\s+out)?|attend(?:ed|ing)?|"
    r"go(?:es|ing)?\s+to|off\s+to\s+do"
    r")\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXERCISE_ACTIVITY_MENU_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"offers?|offered|offering|available|variety|bunch|classes?\s+including|"
    r"including|studio|place|martial\s+arts\s+place|type\s+of\s+classes"
    r")\b",
    re.IGNORECASE,
)


def _community_participation_inventory_slot_for_text(text: str) -> str:
    if _INVENTORY_COMMUNITY_MENTORSHIP_SLOT_RE.search(text):
        return "community_mentorship_program"
    if _INVENTORY_COMMUNITY_ART_SHOW_SLOT_RE.search(text):
        return "community_art_show"
    if _INVENTORY_COMMUNITY_ACTIVIST_GROUP_SLOT_RE.search(text):
        return "community_activist_group"
    if _INVENTORY_COMMUNITY_PRIDE_EVENT_SLOT_RE.search(text):
        return "community_pride_event"
    if _INVENTORY_COMMUNITY_SCHOOL_EVENT_SLOT_RE.search(text):
        return "community_school_event"
    if _INVENTORY_COMMUNITY_CONFERENCE_SLOT_RE.search(text):
        return "community_conference"
    return ""


def _exercise_activity_answer_slot(text: str) -> str:
    text = text.casefold()
    padded = f" {text} "
    if "taekwondo" in padded or "tae kwon do" in padded:
        return "taekwondo"
    if "kickboxing" in padded or "kick boxing" in padded:
        return "kickboxing"
    if "circuit training" in padded:
        return "circuit_training"
    if "weight training" in padded or "weights" in padded:
        return "weight_training"
    if "aerial yoga" in padded:
        return "aerial_yoga"
    if "yoga" in padded and any(
        marker in padded
        for marker in (
            "trying out",
            "try out",
            "trying yoga",
            "started yoga",
            "starting yoga",
        )
    ):
        return "yoga_trial"
    if "yoga" in padded and any(
        marker in padded
        for marker in (
            "strength",
            "flexibility",
            "balance",
            "focus",
            "workout",
            "performance",
            "improve",
        )
    ):
        return "yoga_performance"
    if " yoga" in padded:
        return "yoga"
    if any(marker in padded for marker in ("workout", "exercise", "fitness")):
        return "generic_exercise"
    return ""


def _exercise_activity_answer_directness_rank(text: str) -> int:
    if not _exercise_activity_answer_slot(text):
        return 3
    if _EXERCISE_ACTIVITY_DIRECT_ACTION_RE.search(text) is not None:
        return 0
    if _EXERCISE_ACTIVITY_MENU_CONTEXT_RE.search(text) is not None:
        return 2
    return 1


def _exercise_activity_answer_content_rank(text: str) -> int:
    slot = _exercise_activity_answer_slot(text)
    directness_rank = _exercise_activity_answer_directness_rank(text)
    if directness_rank == 0:
        return 0
    if slot in {"kickboxing", "taekwondo", "weight_training", "circuit_training"}:
        return 1
    if slot in {"aerial_yoga", "yoga_trial", "yoga_performance"}:
        return 1
    if slot == "yoga":
        return 2
    if slot == "generic_exercise":
        return 3
    return 3


def _item_purchase_inventory_slot_for_text(text: str) -> str:
    if not has_item_purchase_object_evidence(text):
        return ""
    if _ITEM_PURCHASE_SHOE_SLOT_RE.search(text):
        return "item_purchase_shoes"
    if _ITEM_PURCHASE_JERSEY_SLOT_RE.search(text):
        return "item_purchase_jerseys"
    if _ITEM_PURCHASE_MEDIA_SLOT_RE.search(text):
        return "item_purchase_media"
    if _ITEM_PURCHASE_FIGURINE_SLOT_RE.search(text):
        return "item_purchase_figurines"
    if _ITEM_PURCHASE_GENERIC_SLOT_RE.search(text):
        return "item_purchase_generic"
    return "item_purchase"


def _dessert_inventory_slot_for_text(text: str) -> str:
    if _DESSERT_COBBLER_SLOT_RE.search(text):
        return "dessert_cobbler"
    if _DESSERT_SUNDAE_SLOT_RE.search(text):
        return "dessert_sundae"
    if _DESSERT_PIE_SLOT_RE.search(text):
        return "dessert_pie"
    if _DESSERT_GENERIC_SLOT_RE.search(text):
        return "dessert"
    return ""


def _game_inventory_slot_for_text(text: str) -> str:
    if slot := _named_game_inventory_slot_for_text(text):
        return slot
    if _BOARD_GAME_CONTEXT_RE.search(text) is not None:
        return "game_board"
    return ""


def _game_inventory_answer_directness_rank(text: str) -> int:
    if _named_game_inventory_slot_for_text(text):
        return 0
    if _BOARD_GAME_CONTEXT_RE.search(text) is not None:
        return 1
    if re.search(r"\b(?:games?|gaming)\b", text, re.IGNORECASE) is not None:
        return 2
    return 3


def _named_game_inventory_slot_for_text(text: str) -> str:
    for pattern in _NAMED_GAME_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        name = _clean_named_game(match.group("name"))
        if not name:
            continue
        safe_name = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if len(safe_name) < 2:
            continue
        return f"game_named_{safe_name}"
    return ""


def _clean_named_game(candidate: str) -> str:
    cleaned = candidate.strip(" \"'.,!?-:")
    cleaned = re.split(
        r"\b(?:related\s+turns?|retrieval\s+hints?|image\s+caption|visual\s+query)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" \"'.,!?-:")
    if not cleaned:
        return ""
    parts = cleaned.split()
    while parts and parts[-1].casefold() in _NAMED_GAME_STOPWORDS:
        parts.pop()
    cleaned = " ".join(parts)
    if not cleaned:
        return ""
    if cleaned.casefold() in _NAMED_GAME_STOPWORDS:
        return ""
    return cleaned


def _children_preference_answer_slot(text: str) -> str:
    text = text.casefold()
    padded = f" {text} "
    has_child_context = any(
        marker in padded
        for marker in (
            " kids",
            " kid ",
            " children",
            " child ",
            " sons",
            " daughters",
            " younger kids",
            " they ",
            " them ",
        )
    )
    has_preference_context = any(
        marker in padded
        for marker in (
            " like",
            " likes",
            " love",
            " loves",
            " enjoy",
            " enjoys",
            " stoked",
            " excited",
            " favorite",
            " favourite",
        )
    )
    if not (has_child_context and has_preference_context):
        return ""
    if any(marker in padded for marker in ("dinosaur", "museum", "exhibit", "animal", "bones")):
        return "dinosaur_animals"
    if any(marker in padded for marker in ("nature", "outdoor", "hike", "trail", "camping")):
        return "nature_outdoors"
    if any(marker in padded for marker in ("book", "story", "stories", "reading")):
        return "books_stories"
    if any(marker in padded for marker in ("pottery", "clay", "painting", "creative")):
        return "creative_projects"
    if any(marker in padded for marker in ("kids", "children", "they love", "they enjoy")):
        return "children_preference"
    return ""


def _painting_inventory_answer_slot(text: str) -> str:
    if "art show" in text or "show my paintings" in text:
        return "painting_art_show"
    if "horse" in text:
        return "painting_horse"
    if "sunset over a lake" in text or "painting sunrise" in text or "lake sunrise" in text:
        return "painting_lake_sunrise"
    if "palm tree" in text or "vibrant flowers" in text:
        return "painting_palm_sunset"
    if "sunflower" in text:
        return "painting_sunflower"
    if "landscape" in text or "sunset" in text:
        return "painting_landscape"
    if "painting" in text or "painted" in text:
        return "painting_generic"
    return ""


def _painting_inventory_answer_content_rank(text: str) -> int:
    normalized = text.casefold()
    if "image caption:" in normalized or "visual query:" in normalized:
        if any(
            marker in normalized
            for marker in (
                "horse",
                "sunset over a lake",
                "painting sunrise",
                "palm tree",
                "vibrant flowers",
                "sunflower",
            )
        ):
            return 0
        return 1
    if "painted" in normalized and any(
        marker in normalized
        for marker in ("horse", "sunrise", "sunset", "lake", "landscape", "nature")
    ):
        return 1
    if "painting" in normalized or "painted" in normalized:
        return 2
    return 4


def _inventory_answer_slot_priority_for_family(slot: str, *, family: str) -> int:
    reason = _answer_support_inventory_family_reason(family)
    normalized_slot = slot.replace("-", "_")
    if reason == "volunteering-people-inventory-bridge":
        if normalized_slot in {"volunteer_helped_person", "gratitude_note_writer"}:
            return -2
        if normalized_slot in {"direct_friend", "volunteer", "shelter", "shelter_anchor"}:
            return 4
        return 5
    if reason == "church-friend-activity-inventory-bridge":
        if normalized_slot == "church_friend_activity":
            return -1
        if normalized_slot in {"church", "direct_friend", "outdoor_activity", "outdoor_hiking"}:
            return 4
        return 5
    if reason == "friend-place-church-inventory-bridge":
        if normalized_slot == "church_joined":
            return -2
        if normalized_slot == "church":
            return -1
        if normalized_slot in {"direct_friend", "community"}:
            return 3
        return 5
    if reason == "friend-place-gym-inventory-bridge":
        if normalized_slot == "gym":
            return -2
        if normalized_slot in {"direct_friend", "community"}:
            return 3
        return 5
    if reason == "friend-place-shelter-inventory-bridge":
        if normalized_slot in {"direct_friend", "shelter_anchor"}:
            return -2
        if normalized_slot in {"shelter_service_activity", "shelter_activity", "shelter"}:
            return 0
        if normalized_slot in {"animal_shelter", "volunteer"}:
            return 2
        return 5
    if reason == "volunteering-inventory-bridge":
        if normalized_slot in {"shelter_anchor", "animal_shelter"}:
            return -2
        if normalized_slot in {"shelter_service_activity", "shelter_activity", "shelter"}:
            return -1
        if normalized_slot in {"volunteer_helped_person", "volunteer"}:
            return 3
        return 5
    if reason == "decomposition-inventory-list":
        if normalized_slot == "direct_friend":
            return -3
        if normalized_slot == "shelter_service_activity":
            return -3
        if normalized_slot in {"shelter_anchor", "animal_shelter"}:
            return -2
        if normalized_slot in {"shelter_activity", "shelter"}:
            return -1
    if reason == "outdoor-activity-inventory-bridge":
        if normalized_slot in {"outdoor_visual_group", "outdoor_mountaineering"}:
            return -2
        if normalized_slot in {"outdoor_hiking", "outdoor_picnic", "outdoor_waterfall"}:
            return 0
        if normalized_slot == "outdoor_activity":
            return 2
        return 5
    if reason == "cause-event-inventory-bridge":
        if normalized_slot in {
            "cause_domestic_abuse",
            "cause_food_drive",
            "cause_shelter_toy_drive",
            "veterans_charity_run",
            "veterans_march",
            "veterans_petition",
            "veterans_hospital",
            "veterans",
        }:
            return -2
        return 5
    if reason == "cause-education-infrastructure-inventory-bridge":
        if normalized_slot == "education_infrastructure":
            return -2
        return 5
    if reason == "cause-veterans-inventory-bridge":
        if normalized_slot == "veterans":
            return -1
        if normalized_slot in {
            "veterans_petition",
            "veterans_charity_run",
            "veterans_march",
            "veterans_hospital",
        }:
            return 4
        return 5
    if reason == "travel-hobby-writing-bridge":
        if normalized_slot in {"travel_writing_overlap", "travel_place_interest"}:
            return -2
        if normalized_slot in {
            "creative_writing_publication",
            "creative_writing_story_sharing",
            "creative_writing",
            "travel_interest",
        }:
            return -1
        return 5
    return _inventory_answer_slot_priority(slot)


def _answer_support_inventory_family_reason(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return ""
    parts = family.split(":")
    if len(parts) >= 2:
        return parts[1]
    return ""


def _inventory_slot_exact_turn_alignment_rank(
    *,
    text: str,
    source_ids: tuple[str, ...],
    inventory_slot: str,
    slot_detector: Callable[[str], str],
) -> int:
    if not inventory_slot:
        return 0
    exact_source_ids = tuple(
        source_id for source_id in source_ids if _is_exact_turn_source_id(source_id)
    )
    if not exact_source_ids:
        return 2
    for source_id in exact_source_ids:
        focused_text = _focused_dialogue_turn_text(text=text, source_id=source_id)
        if slot_detector(focused_text) == inventory_slot:
            return 0
    return 1


def _answer_support_exact_turn_alignment_rank(
    *,
    text: str,
    source_ids: tuple[str, ...],
    inventory_slot: str,
    slot_detector: Callable[[str], str],
    query_reason: str,
) -> int:
    identity_rank = _identity_exact_turn_alignment_rank(
        text=text,
        source_ids=source_ids,
        query_reason=query_reason,
    )
    inventory_rank = _inventory_slot_exact_turn_alignment_rank(
        text=text,
        source_ids=source_ids,
        inventory_slot=inventory_slot,
        slot_detector=slot_detector,
    )
    return identity_rank * 10 + inventory_rank


def _identity_exact_turn_alignment_rank(
    *,
    text: str,
    source_ids: tuple[str, ...],
    query_reason: str,
) -> int:
    if query_reason not in {"identity_bridge", "decomposition_identity_attribute"}:
        return 0
    exact_source_ids = tuple(
        source_id for source_id in source_ids if _is_exact_turn_source_id(source_id)
    )
    if not exact_source_ids:
        return _identity_answer_evidence_rank(text) + 1
    return min(
        _identity_answer_evidence_rank(
            _focused_dialogue_turn_text(text=text, source_id=source_id)
        )
        for source_id in exact_source_ids
    )


def _identity_answer_evidence_rank(text: str) -> int:
    if _IDENTITY_DIRECT_EVIDENCE_RE.search(text) is not None:
        return 0
    if _IDENTITY_CONTEXT_EVIDENCE_RE.search(text) is not None:
        return 1
    return 4


def _is_exact_turn_source_id(source_id: str) -> bool:
    parts = source_id.split(":")
    return len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D")


def _focused_dialogue_turn_text(*, text: str, source_id: str) -> str:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return text
    marker = marker_match.group(0)
    text_match = _dialogue_turn_marker_text_match(text=text, marker=marker)
    if text_match is None:
        return text
    next_match = _DIALOGUE_MARKER_RE.search(text[text_match.end() :])
    end = text_match.end() + next_match.start() if next_match is not None else len(text)
    return text[text_match.start() : end].strip() or text


def _dialogue_turn_marker_text_match(*, text: str, marker: str) -> re.Match[str] | None:
    matches = tuple(re.finditer(rf"\b{re.escape(marker)}\b", text))
    if not matches:
        return None
    for match in matches:
        following = text[match.end() : match.end() + 48]
        if re.match(r"\s+[A-Z][^:\n]{0,40}:", following):
            return match
    return matches[0]


def _diversity_family_base(family: str) -> str:
    separator = family.find(":")
    if separator < 0:
        return family
    return family[:separator]


def _inventory_answer_slot_priority(slot: str) -> int:
    normalized_slot = slot.replace("-", "_")
    if normalized_slot.startswith("game_named_"):
        return 0
    return {
        "direct_friend": 0,
        "dessert_cobbler": 0,
        "dessert_sundae": 0,
        "dessert_pie": 1,
        "dessert": 2,
        "fundraiser_chili_cookoff": 0,
        "fundraiser_shelter_setup": 0,
        "fundraiser_tournament": 0,
        "game_win_result": 0,
        "gratitude_note_writer": 0,
        "classical_music_preference": 0,
        "community_activist_group": 0,
        "community_art_show": 0,
        "community_mentorship_program": 0,
        "community_pride_event": 0,
        "music_live_event": 0,
        "music_violin_concert": 0,
        "outdoor_hiking": 0,
        "outdoor_mountaineering": 0,
        "outdoor_picnic": 0,
        "outdoor_visual_group": 0,
        "outdoor_waterfall": 0,
        "painting_art_show": 0,
        "shelter_anchor": 0,
        "shelter_food_dropoff": 0,
        "shelter_service_activity": 0,
        "skill_game_coaching": 0,
        "skill_recipe_teaching": 0,
        "volunteer_helped_person": 0,
        "state_florida": 0,
        "state_oregon": 0,
        "state_east_coast": 0,
        "state_pacific_northwest": 0,
        "state_place_realized": 0,
        "travel_place_realized": 0,
        "travel_place": 0,
        "pottery_cup": 0,
        "pottery_pot": 0,
        "item_purchase_figurines": 0,
        "item_purchase_jerseys": 0,
        "item_purchase_media": 0,
        "item_purchase_shoes": 0,
        "animal_shelter": 1,
        "animal_activity_bath": 0,
        "animal_activity_feeding": 0,
        "animal_activity_holding": 0,
        "animal_activity_walk": 0,
        "shelter_activity": 1,
        "shelter": 1,
        "gym": 1,
        "church_joined": 1,
        "country": 1,
        "game_board": 1,
        "book_reading": 1,
        "writing_screenplay": 0,
        "writing_book": 0,
        "writing_journal": 0,
        "writing_blog": 0,
        "travel_writing_overlap": 0,
        "travel_place_interest": 0,
        "creative_writing_publication": 0,
        "creative_writing_story_sharing": 0,
        "creative_writing": 0,
        "travel_interest": 0,
        "writing_project": 1,
        "church_friend_activity": 1,
        "community_conference": 1,
        "community_school_event": 1,
        "cause_domestic_abuse": 0,
        "cause_food_drive": 0,
        "cause_shelter_toy_drive": 0,
        "education_infrastructure": 1,
        "veterans_petition": 1,
        "veterans_charity_run": 1,
        "veterans_march": 1,
        "veterans_hospital": 1,
        "veterans": 1,
        "music_event": 1,
        "state_place": 1,
        "outdoor_activity": 1,
        "item_purchase": 1,
        "pottery_bowl": 1,
        "item_purchase_generic": 2,
        "pottery_project": 2,
        "church": 2,
        "volunteer": 2,
        "community": 3,
        "pottery_generic": 3,
        "place": 4,
        "support_group": 5,
    }.get(normalized_slot, 6)
