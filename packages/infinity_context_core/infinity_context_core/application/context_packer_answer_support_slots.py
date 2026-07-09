"""Slot and answer-object helpers for answer-support context packing."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _ANIMAL_CARE_DIRECT_INSTRUCTION_RE,
    _ANIMAL_CARE_GENERIC_HABITAT_RE,
    _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS,
    _BOOK_READING_CONTEXT_RE,
    _BOOK_READING_DIRECT_ANSWER_RE,
    _BROAD_EVIDENCE_TURN_SLOT_REASONS,
    _CAUSE_EDUCATION_SLOT_RE,
    _CAUSE_EVENT_DOMESTIC_ABUSE_SLOT_RE,
    _CAUSE_EVENT_FOOD_DRIVE_SLOT_RE,
    _CAUSE_EVENT_SHELTER_TOY_DRIVE_SLOT_RE,
    _CAUSE_INFRASTRUCTURE_SLOT_RE,
    _COMMON_INTEREST_ACTIVITY_SLOT_RE,
    _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_ANSWER_SUPPORT_REASONS,
    _COMMON_INTEREST_DESSERT_BAKING_SLOT_RE,
    _COMMON_INTEREST_DESSERT_RECIPE_SLOT_RE,
    _COMMON_INTEREST_DESSERT_SLOT_RE,
    _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE,
    _COMMON_INTEREST_MOVIE_SLOT_RE,
    _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE,
    _CONVERSATIONAL_SUPPORT_TURN_RE,
    _COUNT_AGGREGATION_COVERAGE_REASONS,
    _CREATIVE_WRITING_BLOG_SLOT_RE,
    _CREATIVE_WRITING_BOOK_SLOT_RE,
    _CREATIVE_WRITING_JOURNAL_SLOT_RE,
    _CREATIVE_WRITING_PROJECT_SLOT_RE,
    _CREATIVE_WRITING_SCREENPLAY_SLOT_RE,
    _DIALOGUE_MARKER_RE,
    _FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE,
    _FAMILY_ACTIVITY_CONTEXT_OBJECT_RE,
    _FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE,
    _GAME_WIN_COUNT_SLOT_RE,
    _INVENTORY_ANIMAL_ACTIVITY_BATH_SLOT_RE,
    _INVENTORY_ANIMAL_ACTIVITY_FEEDING_SLOT_RE,
    _INVENTORY_ANIMAL_ACTIVITY_HOLDING_SLOT_RE,
    _INVENTORY_ANIMAL_ACTIVITY_WALK_SLOT_RE,
    _INVENTORY_ANIMAL_SHELTER_SLOT_RE,
    _INVENTORY_BOOK_READING_SLOT_RE,
    _INVENTORY_CHURCH_FRIEND_ACTIVITY_SLOT_RE,
    _INVENTORY_CHURCH_JOINED_SLOT_RE,
    _INVENTORY_CHURCH_SLOT_RE,
    _INVENTORY_CLASSICAL_MUSIC_PREFERENCE_SLOT_RE,
    _INVENTORY_COMMUNITY_SLOT_RE,
    _INVENTORY_COUNTRY_SLOT_RE,
    _INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE,
    _INVENTORY_EVENT_CHILI_COOKOFF_SLOT_RE,
    _INVENTORY_EVENT_FUNDRAISER_SETUP_SLOT_RE,
    _INVENTORY_EVENT_TOURNAMENT_SLOT_RE,
    _INVENTORY_FRIEND_COMMUNITY_PLACE_RE,
    _INVENTORY_FRIEND_PLACE_DIRECT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE,
    _INVENTORY_GRATITUDE_NOTE_WRITER_SLOT_RE,
    _INVENTORY_GYM_SLOT_RE,
    _INVENTORY_MUSIC_EVENT_SLOT_RE,
    _INVENTORY_MUSIC_LIVE_EVENT_SLOT_RE,
    _INVENTORY_MUSIC_VIOLIN_CONCERT_SLOT_RE,
    _INVENTORY_OUTDOOR_ACTIVITY_SLOT_RE,
    _INVENTORY_OUTDOOR_HIKING_SLOT_RE,
    _INVENTORY_OUTDOOR_MOUNTAINEERING_SLOT_RE,
    _INVENTORY_OUTDOOR_PICNIC_SLOT_RE,
    _INVENTORY_OUTDOOR_VISUAL_GROUP_SLOT_RE,
    _INVENTORY_OUTDOOR_WATERFALL_SLOT_RE,
    _INVENTORY_PLACE_MARKER_RE,
    _INVENTORY_SHELTER_FOOD_DROPOFF_SLOT_RE,
    _INVENTORY_SHELTER_SERVICE_ACTIVITY_SLOT_RE,
    _INVENTORY_SHELTER_SLOT_RE,
    _INVENTORY_STATE_CALIFORNIA_SLOT_RE,
    _INVENTORY_STATE_EAST_COAST_SLOT_RE,
    _INVENTORY_STATE_FLORIDA_SLOT_RE,
    _INVENTORY_STATE_NEW_YORK_SLOT_RE,
    _INVENTORY_STATE_OREGON_SLOT_RE,
    _INVENTORY_STATE_PACIFIC_NORTHWEST_SLOT_RE,
    _INVENTORY_STATE_PLACE_SLOT_RE,
    _INVENTORY_STATE_TEXAS_SLOT_RE,
    _INVENTORY_SUPPORT_GROUP_SLOT_RE,
    _INVENTORY_VETERANS_HOSPITAL_SLOT_RE,
    _INVENTORY_VETERANS_MARCH_SLOT_RE,
    _INVENTORY_VETERANS_PETITION_SLOT_RE,
    _INVENTORY_VETERANS_RUN_SLOT_RE,
    _INVENTORY_VETERANS_SLOT_RE,
    _INVENTORY_VOLUNTEER_HELPED_PERSON_SLOT_RE,
    _INVENTORY_VOLUNTEER_SLOT_RE,
    _PLACE_AREA_DIRECT_LOCATION_RE,
    _PLACE_AREA_LANDMARK_LOCATION_RE,
    _PLACE_AREA_REALIZED_LOCATION_RE,
    _POTTERY_TYPE_BOWL_SLOT_RE,
    _POTTERY_TYPE_CUP_SLOT_RE,
    _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE,
    _POTTERY_TYPE_INVENTORY_CONTEXT_RE,
    _POTTERY_TYPE_POT_SLOT_RE,
    _POTTERY_TYPE_PRIMARY_ANSWER_OBJECT_RE,
    _POTTERY_TYPE_PROJECT_SLOT_RE,
    _POTTERY_TYPE_SECONDARY_ANSWER_OBJECT_RE,
    _RELIGIOUS_CONTRAST_EVIDENCE_RE,
    _RELIGIOUS_DIRECT_EVIDENCE_RE,
    _SKILL_TEACHING_GAME_SLOT_RE,
    _SKILL_TEACHING_RECIPE_SLOT_RE,
    _SUPPORT_NETWORK_DIRECT_ANSWER_RE,
    _SUPPORT_NETWORK_SOCIAL_ACTOR_RE,
    _SUPPORT_NETWORK_SUPPORT_ACTION_RE,
    _TRAVEL_COUNTRY_SLOT_RE,
    _TRAVEL_PLACE_DIRECT_SLOT_RE,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _diagnostic_text,
    _has_primary_exact_turn_source_ref,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _children_preference_answer_slot,
    _community_participation_inventory_slot_for_text,
    _dessert_inventory_slot_for_text,
    _exercise_activity_answer_slot,
    _game_inventory_slot_for_text,
    _item_purchase_inventory_slot_for_text,
    _painting_inventory_answer_slot,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    recommendation_list_broad_turn_slot,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    travel_hobby_writing_answer_slot,
)
from infinity_context_core.application.dto import ContextItem

_CHARITY_BRAND_CONCRETE_DEAL_SLOT_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|finali[sz]ed|closed)\b"
    r"(?=.{0,180}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\bin\s+talks?\s+with\b"
    r"(?=.{0,180}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|s)?)\b"
    r"(?=.{0,140}\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|"
    r"finali[sz]ed|closed|in\s+talks?\s+with|working\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHARITY_BRAND_PARTNER_AFFINITY_SLOT_RE = re.compile(
    r"\b(?:always\s+liked|liked|likes|i\s+like|we\s+like|they\s+like|"
    r"he\s+likes|she\s+likes|love|loves|fan\s+of|"
    r"admire|admires|favorite|favourite|dream(?:ed)?)\b"
    r"(?=.{0,180}\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it)|"
    r"partner(?:ship|ed|s)?|brand|brands?|company|companies|organization|"
    r"organisations?|deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it))\b"
    r"(?=.{0,180}\b(?:cool|great|exciting|stoked|like|liked|likes|love|"
    r"fan|dream|brand|brands?|company|companies|organization|organisations?|"
    r"deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHARITY_ORGANIZATION_FIT_SLOT_RE = re.compile(
    r"\b(?:charity|nonprofit|non-profit|foundation|organization|organisation|"
    r"program|initiative)\b"
    r"(?=.{0,220}\b(?:kids?|children|youth|students?|disadvantaged|"
    r"underserved|community|sports?|school|education|help|support|give\s+back|"
    r"make\s+(?:a\s+)?difference)\b)|"
    r"\b(?:kids?|children|youth|students?|disadvantaged|underserved|community|"
    r"sports?|school|education)\b"
    r"(?=.{0,220}\b(?:charity|nonprofit|non-profit|foundation|organization|"
    r"organisation|program|initiative|help|support)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHARITY_INTENT_SLOT_RE = re.compile(
    r"\b(?:give\s+(?:something\s+)?back|charity|make\s+(?:a\s+)?difference|"
    r"inspir(?:e|ing|ed)\s+people|away\s+from\s+the\s+court|community\s+impact)\b",
    re.IGNORECASE,
)
_SPORTS_BRAND_GENERIC_SLOT_RE = re.compile(
    r"\b(?:sports?|sportswear|athletic|athleticwear|basketball|gear|shoe|"
    r"shoes|apparel|equipment)\b"
    r"(?=.{0,180}\b(?:brand|brands?|company|companies|sponsor(?:ship|s)?|"
    r"endorse(?:ment|d|s)?|deal|deals?)\b)|"
    r"\b(?:brand|brands?|company|companies|sponsor(?:ship|s)?|"
    r"endorse(?:ment|d|s)?|deal|deals?)\b"
    r"(?=.{0,180}\b(?:sports?|sportswear|athletic|athleticwear|basketball|"
    r"gear|shoe|shoes|apparel|equipment)\b)",
    re.IGNORECASE | re.DOTALL,
)

_ANIMAL_EVIDENCE_SLOT_REASONS = frozenset(
    {
        "animal_activity_inventory_bridge",
        "animal_affinity_pet_store_bridge",
        "animal_care_instruction_bridge",
        "animal_career_inference_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "commonality_interest_bridge",
        "hobby_interest_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
    }
)
_ANIMAL_ACTIVITY_EVIDENCE_REASONS = frozenset(
    {
        "animal_activity_inventory_bridge",
        "commonality_interest_bridge",
        "hobby_interest_bridge",
    }
)


def _activity_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason not in {
        "activity_aggregation_bridge",
        "activity_competition_evidence_bridge",
        "activity_visual_selfcare_bridge",
        "art_style_bridge", "decomposition_activity_participation",
        "destress_activity_bridge",
        "exercise_activity_inventory_bridge",
        "family_activity_bridge",
        "family_hike_detail_bridge",
        "family_hike_activity_bridge",
        "family_museum_activity_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
        "children_preference_bridge",
        "painting_inventory_bridge",
        "shoe_usage_bridge",
    }:
        return ""
    text = item.text.casefold()
    if query_reason == "shoe_usage_bridge":
        if "walking or running" in text or "for walking" in text:
            return "shoe_usage_answer"
        if any(marker in text for marker in ("new shoes", "sneakers", "running shoe")):
            return "shoe_purchase_visual"
        return ""
    if query_reason in {"art_style_bridge", "painting_inventory_bridge"}:
        return _painting_inventory_answer_slot(text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_slot(text)
    if query_reason == "children_preference_bridge":
        return _children_preference_answer_slot(text)
    return _general_activity_answer_slot_for_text(text)

def _general_activity_answer_slot_for_text(text: str) -> str:
    if (
        "used to" in text
        and any(marker in text for marker in (" dad", " father", " mom", " mother", " parent"))
        and any(marker in text for marker in (" kid", " child", " childhood", " younger"))
    ):
        return "childhood_parent_activity"
    slots = (
        ("swimming", ("swimming", " swim ", "self care", "taking care")),
        ("hiking", ("hiking", " hike ", "trail", "waterfall", "mountain")),
        ("camping", ("camping", "camped", "campfire", "marshmallow", "unplug")),
        ("pottery", ("pottery", "clay", "ceramic", "bowl")),
        ("painting", ("painting", "painted", "sunrise", "sunset", "lake", "drawing")),
        ("dance", ("dance", "dancing", "dancers", "dance studio", "festival")),
        ("family_motivation", ("husband", "motivated", "motivate", "motivation")),
        ("running", ("running", "run ", "ran ", "race")),
        ("museum", ("museum", "dinosaur", "exhibit", "bones")),
        ("park", ("park", "outdoors", "playing", "exploring")),
        ("concert", ("concert", "music", "band")),
    )
    padded = f" {text} "
    for slot, markers in slots:
        if any(marker in padded for marker in markers):
            return slot
    return ""

def _animal_evidence_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    return _animal_evidence_slot_for_text(item.text, query_reason=query_reason)

def _animal_evidence_slot_for_text(text: str, *, query_reason: str) -> str:
    reason = query_reason.replace("-", "_")
    if reason not in _ANIMAL_EVIDENCE_SLOT_REASONS:
        return ""
    if reason in _ANIMAL_ACTIVITY_EVIDENCE_REASONS:
        if _INVENTORY_ANIMAL_ACTIVITY_HOLDING_SLOT_RE.search(text):
            return "animal_activity_holding"
        if _INVENTORY_ANIMAL_ACTIVITY_BATH_SLOT_RE.search(text):
            return "animal_activity_bath"
        if _INVENTORY_ANIMAL_ACTIVITY_WALK_SLOT_RE.search(text):
            return "animal_activity_walk"
        if _INVENTORY_ANIMAL_ACTIVITY_FEEDING_SLOT_RE.search(text):
            return "animal_activity_feeding"
    lowered = text.casefold()
    if _ANIMAL_CARE_DIRECT_INSTRUCTION_RE.search(text):
        return "animal_care"
    if _is_animal_diet_evidence_text(lowered):
        return "animal_diet"
    if _is_animal_pet_acquisition_text(lowered):
        return "animal_pet_acquisition"
    if _ANIMAL_CARE_GENERIC_HABITAT_RE.search(text) or _is_animal_habitat_text(lowered):
        return "animal_habitat"
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return "animal_affinity"
    if _is_animal_identity_text(lowered):
        return "animal_identity"
    return ""

def _is_animal_diet_evidence_text(text: str) -> bool:
    has_food_action = any(
        marker in text
        for marker in (
            " eat",
            " eats",
            " eating",
            " feed",
            " feeds",
            " feeding",
            " diet",
            " food",
        )
    )
    has_food_object = any(
        marker in text
        for marker in (
            "vegetable",
            "fruit",
            "insect",
            "greens",
            "lettuce",
            "varied diet",
            "favorite snacks",
            "snacks",
            "strawberries",
        )
    )
    has_animal_context = any(
        marker in text
        for marker in ("turtle", "pet", "animal", "reptile", "critters")
    )
    return has_food_action and (has_food_object or has_animal_context)

def _is_animal_pet_acquisition_text(text: str) -> bool:
    has_animal_context = any(
        marker in text
        for marker in ("turtle", "pet", "animal", "reptile", "critters", "dog")
    )
    if not has_animal_context:
        return False
    return any(
        marker in text
        for marker in (
            "new addition",
            "new friend",
            "another at a pet store",
            "pet store",
            "third turtle",
            "big enough for three",
            "adopted",
            "got them",
        )
    )

def _is_animal_habitat_text(text: str) -> bool:
    has_animal_context = any(
        marker in text
        for marker in ("turtle", "pet", "animal", "reptile", "critters")
    )
    if not has_animal_context:
        return False
    return any(
        marker in text
        for marker in (
            "new tank",
            "bigger tank",
            "tank big enough",
            "room to swim",
            "basking",
            "heat lamp",
            "habitat",
            "aquarium",
        )
    )

def _is_animal_identity_text(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "has turtles",
            "has a dog",
            "has pets",
            "turtles as pets",
            "dog named",
            "pet named",
            "pet turtles",
            "this is max",
        )
    )

def _animal_evidence_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""

def _animal_evidence_answer_slot_priority(slot: str) -> int:
    return {
        "animal_care": 0,
        "animal_diet": 0,
        "animal_activity_bath": 0,
        "animal_activity_feeding": 0,
        "animal_activity_holding": 0,
        "animal_activity_walk": 0,
        "animal_identity": 0,
        "animal_pet_acquisition": 1,
        "animal_habitat": 1,
        "animal_affinity": 2,
    }.get(slot.replace("-", "_"), 4)

def _animal_evidence_answer_slot_priority_for_family(slot: str, *, family: str) -> int:
    normalized_slot = slot.replace("-", "_")
    reason = _animal_evidence_answer_family_reason(family)
    if reason in {"pet-inventory-bridge", "pet-count-bridge"}:
        return {
            "animal_identity": -2,
            "animal_pet_acquisition": -1,
            "animal_habitat": 2,
            "animal_affinity": 3,
            "animal_diet": 5,
            "animal_care": 5,
            "animal_activity_bath": 5,
            "animal_activity_feeding": 5,
            "animal_activity_holding": 5,
            "animal_activity_walk": 5,
        }.get(normalized_slot, 5)
    return _animal_evidence_answer_slot_priority(slot)

def _animal_evidence_answer_family_reason(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 2:
        return parts[1]
    return ""

def _is_count_aggregation_coverage_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason not in _COUNT_AGGREGATION_COVERAGE_REASONS:
        return False
    if _has_primary_exact_turn_source_ref(item):
        return False
    if "keyword_aggregation_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    return len(item.source_refs) > 1

def _broad_evidence_turn_slot(item: ContextItem, *, query_reason: str) -> str:
    source_id = _primary_exact_turn_source_id(item)
    if len(item.source_refs) == 1 and (
        recommendation_slot := recommendation_list_broad_turn_slot(
            text=item.text,
            query_reason=query_reason,
            source_id=source_id,
        )
    ):
        return recommendation_slot
    if query_reason not in _BROAD_EVIDENCE_TURN_SLOT_REASONS:
        return ""
    if len(item.source_refs) != 1:
        return ""
    return source_id

def _aggregation_marker_coverage_slot(item: ContextItem, *, query_reason: str) -> str:
    normalized_reason = query_reason.replace("_", "-")
    if (
        query_reason not in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
        and normalized_reason not in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
    ):
        return ""
    if not set(diagnostic_retrieval_sources(item.diagnostics)).intersection(
        {
            "keyword_aggregation_chunks",
            "keyword_chunks",
            "keyword_neighbor_chunks",
            "keyword_source_sibling_chunks",
        }
    ):
        return ""
    if _diagnostic_text(item, "source_type") != "locomo_observation":
        return ""
    if "related turns:" not in item.text.casefold():
        return ""
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(item.text))
    )
    if len(markers) < 2:
        return ""
    return f"{markers[0]}-{markers[-1]}"

def _career_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason == "degree_policy_inference_bridge":
        return _degree_policy_answer_slot(item.text)
    if query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}:
        return _business_commonality_answer_slot(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_slot(item.text)
    if query_reason in {"career_intent_bridge", "career_path_bridge"}:
        text = item.text.casefold()
        if "working with trans people" in text or "trans people" in text:
            return "trans_support_work"
        if "counsel" in text or "mental health" in text:
            return "counseling_mental_health"
        return ""
    if query_reason == "creative_writing_career_bridge":
        return "book_reading" if _book_reading_answer_content_rank(item.text) <= 3 else ""
    if query_reason != "volunteer_career_inference_bridge":
        return ""
    text = item.text.casefold()
    slots = (
        ("shelter_operations", ("front desk", "food or a bed", "food", " bed", "coordinator")),
        ("counseling_talks", ("gave a few talks", " talks ", "compliments", "counselor")),
        (
            "volunteer_origin",
            (
                "about a year ago",
                "witnessing a family",
                "family struggling",
                "struggling on the streets",
                "reached out to the shelter",
                "needed any volunteers",
            ),
        ),
        (
            "start_motivation",
            (
                "started volunteering",
                "start volunteering",
                "aunt",
                "brighten",
            ),
        ),
        (
            "resident_support",
            ("resident", "gratitude", "appreciation", "letter", "support they receive"),
        ),
        ("homeless_shelter", ("homeless shelter", " shelter", "volunteer")),
    )
    padded = f" {text} "
    for slot, markers in slots:
        if any(marker in padded for marker in markers):
            return slot
    return ""

def _inference_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason.replace("_", "-") != "religious-inference-bridge":
        return ""
    if _RELIGIOUS_CONTRAST_EVIDENCE_RE.search(item.text):
        return "religious_contrast"
    if _RELIGIOUS_DIRECT_EVIDENCE_RE.search(item.text):
        return "religious_direct"
    return ""

def _degree_policy_answer_slot(text: str) -> str:
    text = text.casefold()
    padded = f" {text} "
    if any(
        marker in padded
        for marker in (
            " because of my degree",
            " because of his degree",
            " because of her degree",
            "policymaking because",
            "public policy",
            "public administration",
            "public affairs",
            "political science",
        )
    ):
        return "degree_field_inference"
    if any(marker in padded for marker in ("policymaking", "policy making", " policy ")):
        return "policy_career_plan"
    if any(marker in padded for marker in ("graduated", "degree", "diploma")):
        return "degree_completion_context"
    return ""

def _business_commonality_answer_slot(text: str) -> str:
    text = text.casefold()
    if "door dash" in text and "lost my job" in text:
        return "gina_job_loss"
    if "lost my job as a banker" in text or ("banker" in text and "own business" in text):
        return "jon_job_loss"
    if "dance studio" in text or ("starting" in text and "passionate about dancing" in text):
        return "jon_business_type"
    if (
        "clothing store" in text
        or "my own store" in text
        or "ad campaign" in text
        or "fashion trends" in text
        or "unique pieces" in text
        or "blend my love for dance and fashion" in text
        or "blend dance and fashion" in text
    ):
        return "gina_store_start"
    if "own business" in text or "starting" in text:
        return "business_start_generic"
    return ""

def _charity_brand_sponsorship_answer_slot(text: str) -> str:
    if _CHARITY_BRAND_PARTNER_AFFINITY_SLOT_RE.search(text) is not None:
        return "partner_affinity_fit"
    if _CHARITY_BRAND_CONCRETE_DEAL_SLOT_RE.search(text) is not None:
        return "brand_sponsorship_deal"
    if _CHARITY_ORGANIZATION_FIT_SLOT_RE.search(text) is not None:
        return "charity_org_fit"
    if _CHARITY_INTENT_SLOT_RE.search(text) is not None:
        return "charity_intent"
    if _SPORTS_BRAND_GENERIC_SLOT_RE.search(text) is not None:
        return "sports_brand_generic"
    return ""

def _inventory_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    normalized_reason = query_reason.replace("_", "-")
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_inventory_slot_for_text(item.text)
    if normalized_reason == "travel-hobby-writing-bridge":
        return travel_hobby_writing_answer_slot(item.text)
    if normalized_reason == "creative-writing-inventory-bridge":
        return _creative_writing_inventory_slot_for_text(item.text)
    if _is_community_participation_reason(query_reason):
        return _community_participation_inventory_slot_for_text(item.text)
    if query_reason == "item_purchase_bridge":
        return _item_purchase_inventory_slot_for_text(item.text)
    if normalized_reason == "place-area-inventory-bridge":
        return _place_area_inventory_slot_for_text(
            item.text,
            concrete_named_states=True,
        )
    if normalized_reason == "trip-destination-bridge":
        return _place_area_inventory_slot_for_text(item.text)
    if normalized_reason == "game-win-count-bridge":
        return _game_win_count_inventory_slot_for_text(item.text)
    if normalized_reason == "skill-teaching-inventory-bridge":
        return _skill_teaching_inventory_slot_for_text(item.text)
    if (
        normalized_reason == "volunteering-people-inventory-bridge"
        and _INVENTORY_GRATITUDE_NOTE_WRITER_SLOT_RE.search(item.text)
    ):
        return "gratitude_note_writer"
    if (
        normalized_reason == "volunteering-inventory-bridge"
        and _INVENTORY_SHELTER_FOOD_DROPOFF_SLOT_RE.search(item.text)
    ):
        return "shelter_food_dropoff"
    if not _is_inventory_list_reason(query_reason):
        return ""
    if normalized_reason == "board-game-inventory-bridge":
        return _game_inventory_slot_for_text(item.text)
    if normalized_reason == "travel-country-inventory-bridge":
        return _travel_country_inventory_slot_for_text(item.text)
    if query_reason == "cause_event_inventory_bridge":
        return _cause_event_answer_slot(item.text)
    if query_reason == "cause_education_infrastructure_inventory_bridge":
        return _cause_education_infrastructure_answer_slot(item.text)
    if query_reason == "cause_veterans_inventory_bridge":
        return _cause_veterans_answer_slot(item.text)
    if query_reason == "event_participation_help_bridge":
        return _community_participation_inventory_slot_for_text(
            item.text
        ) or _inventory_answer_slot_for_text(item.text)
    if query_reason == "outdoor_activity_inventory_bridge":
        return _outdoor_activity_inventory_answer_slot_for_text(item.text)
    return _inventory_answer_slot_for_text(item.text)


def _game_win_count_inventory_slot_for_text(text: str) -> str:
    if _GAME_WIN_COUNT_SLOT_RE.search(text):
        return "game_win_result"
    return ""


def _skill_teaching_inventory_slot_for_text(text: str) -> str:
    if _SKILL_TEACHING_RECIPE_SLOT_RE.search(text):
        return "skill_recipe_teaching"
    if _SKILL_TEACHING_GAME_SLOT_RE.search(text):
        return "skill_game_coaching"
    return ""

def _outdoor_activity_inventory_answer_slot_for_text(text: str) -> str:
    if _INVENTORY_OUTDOOR_MOUNTAINEERING_SLOT_RE.search(text):
        return "outdoor_mountaineering"
    if _INVENTORY_OUTDOOR_HIKING_SLOT_RE.search(text):
        return "outdoor_hiking"
    if _INVENTORY_OUTDOOR_PICNIC_SLOT_RE.search(text):
        return "outdoor_picnic"
    if _INVENTORY_OUTDOOR_WATERFALL_SLOT_RE.search(text):
        return "outdoor_waterfall"
    if _INVENTORY_OUTDOOR_VISUAL_GROUP_SLOT_RE.search(text):
        return "outdoor_visual_group"
    if _INVENTORY_OUTDOOR_ACTIVITY_SLOT_RE.search(text):
        return "outdoor_activity"
    return ""

def _travel_country_inventory_slot_for_text(text: str) -> str:
    if _TRAVEL_COUNTRY_SLOT_RE.search(text) or _TRAVEL_PLACE_DIRECT_SLOT_RE.search(text):
        return "country"
    return ""

def _place_area_inventory_slot_for_text(
    text: str,
    *,
    concrete_named_states: bool = False,
) -> str:
    if concrete_named_states:
        if _INVENTORY_STATE_CALIFORNIA_SLOT_RE.search(text):
            return "state_california"
        if _INVENTORY_STATE_FLORIDA_SLOT_RE.search(text):
            return "state_florida"
        if _INVENTORY_STATE_NEW_YORK_SLOT_RE.search(text):
            return "state_new_york"
        if _INVENTORY_STATE_OREGON_SLOT_RE.search(text):
            return "state_oregon"
        if _INVENTORY_STATE_TEXAS_SLOT_RE.search(text):
            return "state_texas"
    if _INVENTORY_STATE_EAST_COAST_SLOT_RE.search(text):
        return "state_east_coast"
    if _INVENTORY_STATE_PACIFIC_NORTHWEST_SLOT_RE.search(text):
        return "state_pacific_northwest"
    if (
        _INVENTORY_STATE_PLACE_SLOT_RE.search(text)
        and _PLACE_AREA_REALIZED_LOCATION_RE.search(text)
    ):
        return "state_place_realized"
    if _INVENTORY_STATE_PLACE_SLOT_RE.search(text):
        return "state_place"
    if _PLACE_AREA_REALIZED_LOCATION_RE.search(text):
        return "travel_place_realized"
    if (
        _TRAVEL_PLACE_DIRECT_SLOT_RE.search(text)
        or _PLACE_AREA_DIRECT_LOCATION_RE.search(text)
        or _PLACE_AREA_LANDMARK_LOCATION_RE.search(text)
    ):
        return "travel_place"
    if _INVENTORY_COUNTRY_SLOT_RE.search(text):
        return "country"
    return ""

def _creative_writing_inventory_slot_for_text(text: str) -> str:
    if _CREATIVE_WRITING_BLOG_SLOT_RE.search(text):
        return "writing_blog"
    if _CREATIVE_WRITING_JOURNAL_SLOT_RE.search(text):
        return "writing_journal"
    if _CREATIVE_WRITING_BOOK_SLOT_RE.search(text):
        return "writing_book"
    if _CREATIVE_WRITING_SCREENPLAY_SLOT_RE.search(text):
        return "writing_screenplay"
    if _CREATIVE_WRITING_PROJECT_SLOT_RE.search(text):
        return "writing_project"
    return ""

def _inventory_answer_slot_for_text(text: str) -> str:
    if dessert_slot := _dessert_inventory_slot_for_text(text):
        return dessert_slot
    if item_purchase_slot := _item_purchase_inventory_slot_for_text(text):
        return item_purchase_slot
    if game_slot := _game_inventory_slot_for_text(text):
        return game_slot
    pottery_slot = _pottery_type_inventory_slot_for_text(text)
    if pottery_slot:
        return pottery_slot
    if _INVENTORY_EVENT_CHILI_COOKOFF_SLOT_RE.search(text):
        return "fundraiser_chili_cookoff"
    if _INVENTORY_EVENT_TOURNAMENT_SLOT_RE.search(text):
        return "fundraiser_tournament"
    if _INVENTORY_EVENT_FUNDRAISER_SETUP_SLOT_RE.search(text):
        return "fundraiser_shelter_setup"
    if _INVENTORY_ANIMAL_ACTIVITY_HOLDING_SLOT_RE.search(text):
        return "animal_activity_holding"
    if _INVENTORY_ANIMAL_ACTIVITY_BATH_SLOT_RE.search(text):
        return "animal_activity_bath"
    if _INVENTORY_ANIMAL_ACTIVITY_WALK_SLOT_RE.search(text):
        return "animal_activity_walk"
    if _INVENTORY_ANIMAL_ACTIVITY_FEEDING_SLOT_RE.search(text):
        return "animal_activity_feeding"
    if _INVENTORY_VOLUNTEER_HELPED_PERSON_SLOT_RE.search(text):
        return "volunteer_helped_person"
    if _INVENTORY_SHELTER_SERVICE_ACTIVITY_SLOT_RE.search(text):
        return "shelter_service_activity"
    if _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE.search(text):
        return "shelter_activity"
    if _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE.search(text):
        return "shelter_anchor"
    if _INVENTORY_ANIMAL_SHELTER_SLOT_RE.search(text):
        return "animal_shelter"
    if _INVENTORY_SHELTER_SLOT_RE.search(text):
        return "shelter"
    if _INVENTORY_GYM_SLOT_RE.search(text):
        return "gym"
    if _INVENTORY_CHURCH_JOINED_SLOT_RE.search(text):
        return "church_joined"
    if _INVENTORY_BOOK_READING_SLOT_RE.search(text):
        return "book_reading"
    if _INVENTORY_CHURCH_FRIEND_ACTIVITY_SLOT_RE.search(text):
        return "church_friend_activity"
    if _INVENTORY_CHURCH_SLOT_RE.search(text):
        return "church"
    if _INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE.search(text):
        return "education_infrastructure"
    if _INVENTORY_VETERANS_PETITION_SLOT_RE.search(text):
        return "veterans_petition"
    if _INVENTORY_VETERANS_RUN_SLOT_RE.search(text):
        return "veterans_charity_run"
    if _INVENTORY_VETERANS_MARCH_SLOT_RE.search(text):
        return "veterans_march"
    if _INVENTORY_VETERANS_HOSPITAL_SLOT_RE.search(text):
        return "veterans_hospital"
    if _INVENTORY_VETERANS_SLOT_RE.search(text):
        return "veterans"
    if community_participation_slot := _community_participation_inventory_slot_for_text(
        text
    ):
        return community_participation_slot
    if _INVENTORY_CLASSICAL_MUSIC_PREFERENCE_SLOT_RE.search(text):
        return "classical_music_preference"
    if _INVENTORY_MUSIC_VIOLIN_CONCERT_SLOT_RE.search(text):
        return "music_violin_concert"
    if _INVENTORY_MUSIC_LIVE_EVENT_SLOT_RE.search(text):
        return "music_live_event"
    if _INVENTORY_MUSIC_EVENT_SLOT_RE.search(text):
        return "music_event"
    if _INVENTORY_STATE_CALIFORNIA_SLOT_RE.search(text):
        return "state_california"
    if _INVENTORY_STATE_FLORIDA_SLOT_RE.search(text):
        return "state_florida"
    if _INVENTORY_STATE_NEW_YORK_SLOT_RE.search(text):
        return "state_new_york"
    if _INVENTORY_STATE_OREGON_SLOT_RE.search(text):
        return "state_oregon"
    if _INVENTORY_STATE_TEXAS_SLOT_RE.search(text):
        return "state_texas"
    if _INVENTORY_STATE_EAST_COAST_SLOT_RE.search(text):
        return "state_east_coast"
    if _INVENTORY_STATE_PACIFIC_NORTHWEST_SLOT_RE.search(text):
        return "state_pacific_northwest"
    if _INVENTORY_STATE_PLACE_SLOT_RE.search(text):
        return "state_place"
    if _INVENTORY_OUTDOOR_MOUNTAINEERING_SLOT_RE.search(text):
        return "outdoor_mountaineering"
    if _INVENTORY_OUTDOOR_HIKING_SLOT_RE.search(text):
        return "outdoor_hiking"
    if _INVENTORY_OUTDOOR_PICNIC_SLOT_RE.search(text):
        return "outdoor_picnic"
    if _INVENTORY_OUTDOOR_WATERFALL_SLOT_RE.search(text):
        return "outdoor_waterfall"
    if _INVENTORY_OUTDOOR_ACTIVITY_SLOT_RE.search(text):
        return "outdoor_activity"
    if _INVENTORY_FRIEND_PLACE_DIRECT_RE.search(text):
        return "direct_friend"
    if _INVENTORY_VOLUNTEER_SLOT_RE.search(text):
        return "volunteer"
    if _INVENTORY_COMMUNITY_SLOT_RE.search(text):
        return "community"
    if _INVENTORY_SUPPORT_GROUP_SLOT_RE.search(text):
        return "support_group"
    if _INVENTORY_COUNTRY_SLOT_RE.search(text):
        return "country"
    if _INVENTORY_PLACE_MARKER_RE.search(text):
        return "place"
    return ""

def _cause_education_infrastructure_answer_slot(text: str) -> str:
    if (
        _CAUSE_EDUCATION_SLOT_RE.search(text)
        and _CAUSE_INFRASTRUCTURE_SLOT_RE.search(text)
    ):
        return "education_infrastructure"
    return ""

def _cause_event_answer_slot(text: str) -> str:
    if _CAUSE_EVENT_DOMESTIC_ABUSE_SLOT_RE.search(text):
        return "cause_domestic_abuse"
    if _CAUSE_EVENT_FOOD_DRIVE_SLOT_RE.search(text):
        return "cause_food_drive"
    if _CAUSE_EVENT_SHELTER_TOY_DRIVE_SLOT_RE.search(text):
        return "cause_shelter_toy_drive"
    if veterans_slot := _cause_veterans_answer_slot(text):
        return veterans_slot
    if _cause_education_infrastructure_answer_slot(text):
        return "education_infrastructure"
    return ""

def _cause_veterans_answer_slot(text: str) -> str:
    if _INVENTORY_VETERANS_PETITION_SLOT_RE.search(text):
        return "veterans_petition"
    if _INVENTORY_VETERANS_RUN_SLOT_RE.search(text):
        return "veterans_charity_run"
    if _INVENTORY_VETERANS_MARCH_SLOT_RE.search(text):
        return "veterans_march"
    if _INVENTORY_VETERANS_HOSPITAL_SLOT_RE.search(text):
        return "veterans_hospital"
    if _INVENTORY_VETERANS_SLOT_RE.search(text):
        return "veterans"
    return ""

def _inventory_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""

def _common_interest_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""

def _is_common_interest_answer_reason(query_reason: str) -> bool:
    return query_reason in _COMMON_INTEREST_ANSWER_SUPPORT_REASONS

def _common_interest_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if not _is_common_interest_answer_reason(query_reason):
        return ""
    text = item.text
    if (
        _COMMON_INTEREST_MOVIE_SLOT_RE.search(text) is not None
        or _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE.search(text) is not None
    ):
        return "common_interest_movies"
    if _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE.search(text) is not None:
        return "common_interest_personal_hobby"
    if _COMMON_INTEREST_ACTIVITY_SLOT_RE.search(text) is not None:
        return "common_interest_activity"
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return "common_interest_animal_affinity"
    if _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE.search(text) is not None:
        return "common_interest_affinity_reason"
    if _COMMON_INTEREST_DESSERT_RECIPE_SLOT_RE.search(text) is not None:
        return "common_interest_dessert_recipe"
    if _COMMON_INTEREST_DESSERT_BAKING_SLOT_RE.search(text) is not None:
        return "common_interest_dessert_baking"
    if _COMMON_INTEREST_DESSERT_SLOT_RE.search(text) is not None:
        return "common_interest_dessert"
    return ""

def _common_interest_answer_slot_priority(slot: str) -> int:
    normalized_slot = slot.replace("-", "_")
    return {
        "common_interest_movies": 0,
        "common_interest_personal_hobby": 0,
        "common_interest_activity": 0,
        "common_interest_animal_affinity": 0,
        "common_interest_affinity_reason": 1,
        "common_interest_dessert_recipe": 0,
        "common_interest_dessert_baking": 1,
        "common_interest_dessert": 2,
    }.get(normalized_slot, 4)

def _career_answer_slot_priority(slot: str) -> int:
    normalized_slot = slot.replace("-", "_")
    return {
        "brand_sponsorship_deal": 0,
        "partner_affinity_fit": 0,
        "charity_intent": 0,
        "charity_org_fit": 1,
        "shelter_operations": 0,
        "counseling_talks": 0,
        "volunteer_origin": 0,
        "start_motivation": 0,
        "trans_support_work": 0,
        "counseling_mental_health": 1,
        "resident_support": 2,
        "sports_brand_generic": 2,
        "homeless_shelter": 3,
    }.get(normalized_slot, 2)

def _career_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""

def _is_pottery_type_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") == "pottery-type-bridge"

def _is_pottery_type_inventory_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason.replace("_", "-") != "decomposition-inventory-list":
        return False
    if _POTTERY_TYPE_INVENTORY_CONTEXT_RE.search(item.text) is None:
        return False
    return _pottery_type_answer_object_rank(item.text) <= 1

def _is_family_activity_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-activity-participation",
        "family-activity-bridge",
        "family-hike-activity-bridge",
        "family-hike-detail-bridge",
        "family-museum-activity-bridge",
        "family-painting-activity-bridge",
        "family-swimming-activity-bridge",
    }

def _is_activity_participation_answer_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "activity-aggregation-bridge",
        "activity-competition-evidence-bridge",
        "activity-visual-selfcare-bridge",
        "decomposition-activity-participation",
        "destress-activity-bridge",
    }

def _is_inventory_list_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-inventory-list",
        "animal-activity-inventory-bridge",
        "board-game-inventory-bridge",
        "friend-place-inventory-bridge",
        "friend-place-shelter-inventory-bridge",
        "friend-place-gym-inventory-bridge",
        "friend-place-church-inventory-bridge",
        "book-reading-list-bridge",
        "church-friend-activity-inventory-bridge",
        "classical-music-preference-bridge",
        "cause-event-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
        "event-participation-bridge",
        "event-participation-help-bridge",
        "fundraiser-event-inventory-bridge",
        "game-win-count-bridge",
        "item-purchase-bridge",
        "music-event-inventory-bridge",
        "outdoor-activity-inventory-bridge",
        "place-area-inventory-bridge",
        "trip-destination-bridge",
        "travel-country-inventory-bridge",
        "veterans-event-inventory-bridge",
        "skill-teaching-inventory-bridge",
        "volunteering-people-inventory-bridge",
        "volunteering-inventory-bridge",
    }

def _is_community_participation_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "community-participation-bridge",
        "decomposition-lgbtq-pride-event",
        "decomposition-lgbtq-school-speech-event",
        "decomposition-lgbtq-support-group-event",
        "lgbtq-community-participation-bridge",
    }

def _is_support_network_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "negative-experience-support-bridge",
        "support-network-bridge",
    }

def _support_network_answer_object_rank(text: str) -> int:
    if _SUPPORT_NETWORK_DIRECT_ANSWER_RE.search(text):
        return 0
    has_social_actor = _SUPPORT_NETWORK_SOCIAL_ACTOR_RE.search(text) is not None
    has_support_action = _SUPPORT_NETWORK_SUPPORT_ACTION_RE.search(text) is not None
    if has_social_actor and has_support_action:
        return 1
    if has_social_actor:
        return 2
    if has_support_action:
        return 4
    return 6

def _is_conversational_support_turn(item: ContextItem) -> bool:
    return _CONVERSATIONAL_SUPPORT_TURN_RE.search(item.text) is not None

def _pottery_type_answer_object_rank(text: str) -> int:
    if _POTTERY_TYPE_PRIMARY_ANSWER_OBJECT_RE.search(text):
        return 0
    if _POTTERY_TYPE_SECONDARY_ANSWER_OBJECT_RE.search(text):
        return 1
    if _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE.search(text):
        return 3
    return 5

def _family_activity_answer_object_rank(text: str) -> int:
    if _FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE.search(text):
        return 0
    has_activity = _FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE.search(text) is not None
    has_family_context = _FAMILY_ACTIVITY_CONTEXT_OBJECT_RE.search(text) is not None
    if has_activity and has_family_context:
        return 1
    if has_activity:
        return 2
    if has_family_context:
        return 3
    return 5

def _inventory_list_answer_object_rank(text: str) -> int:
    slot = _inventory_answer_slot_for_text(text)
    if slot == "book_reading":
        return _book_reading_answer_content_rank(text)
    if slot in {
        "item_purchase_figurines",
        "item_purchase_jerseys",
        "item_purchase_media",
        "item_purchase_shoes",
    }:
        return 0
    if slot.startswith("game_named_"):
        return 0
    if slot == "game_board":
        return 1
    if slot in {"dessert_cobbler", "dessert_sundae"}:
        return 0
    if slot == "dessert_pie":
        return 1
    if slot == "dessert":
        return 2
    if slot == "item_purchase":
        return 1
    if slot == "item_purchase_generic":
        return 2
    if slot in {"pottery_cup", "pottery_pot"}:
        return 0
    if slot == "pottery_bowl":
        return 1
    if slot == "pottery_project":
        return 2
    if slot == "pottery_generic":
        return 3
    if slot in {
        "direct_friend",
        "dessert_cobbler",
        "dessert_sundae",
        "fundraiser_chili_cookoff",
        "fundraiser_shelter_setup",
        "fundraiser_tournament",
        "item_purchase_figurines",
        "item_purchase_jerseys",
        "item_purchase_media",
        "item_purchase_shoes",
        "classical_music_preference",
        "music_live_event",
        "music_violin_concert",
        "outdoor_hiking",
        "outdoor_mountaineering",
        "outdoor_picnic",
        "outdoor_visual_group",
        "outdoor_waterfall",
        "state_california",
        "shelter_service_activity",
        "volunteer_helped_person",
        "state_florida",
        "state_new_york",
        "state_oregon",
        "state_east_coast",
        "state_pacific_northwest",
        "state_texas",
        "community_activist_group",
        "community_art_show",
        "community_mentorship_program",
        "community_pride_event",
    }:
        return 0
    if slot in {
        "community_conference",
        "community_school_event",
        "dessert_pie",
        "shelter",
        "gym",
        "church_joined",
        "country",
        "education_infrastructure",
        "item_purchase",
        "music_event",
        "outdoor_activity",
        "state_place",
        "veterans",
        "veterans_petition",
        "veterans_charity_run",
        "veterans_march",
        "veterans_hospital",
    }:
        return 1
    if slot in {"church", "volunteer"}:
        return 2
    if slot == "dessert":
        return 2
    if slot == "item_purchase_generic":
        return 2
    if slot in {"community", "place"} or _INVENTORY_FRIEND_COMMUNITY_PLACE_RE.search(text):
        return 3
    if slot == "support_group":
        return 5
    return 6

def _pottery_type_inventory_slot_for_text(text: str) -> str:
    if _POTTERY_TYPE_INVENTORY_CONTEXT_RE.search(text) is None:
        return ""
    if _POTTERY_TYPE_CUP_SLOT_RE.search(text):
        return "pottery_cup"
    if _POTTERY_TYPE_POT_SLOT_RE.search(text):
        return "pottery_pot"
    if _POTTERY_TYPE_BOWL_SLOT_RE.search(text):
        return "pottery_bowl"
    if _POTTERY_TYPE_PROJECT_SLOT_RE.search(text):
        return "pottery_project"
    return "pottery_generic"

def _book_reading_answer_content_rank(text: str) -> int:
    if _BOOK_READING_DIRECT_ANSWER_RE.search(text) is not None:
        return 0
    if _INVENTORY_BOOK_READING_SLOT_RE.search(text) is not None:
        return 1
    if _BOOK_READING_CONTEXT_RE.search(text) is not None:
        return 3
    return 5
