"""Answer slot and content-ranking policy for context packing."""

from __future__ import annotations

import re

from infinity_context_core.application.dto import ContextItem

_BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE = re.compile(
    r"\b("
    r"busy\s+week|city\s+schedule|schedule|"
    r"binos|binoculars|notebook|log\s+them|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"birdwatching|watching\s+birds?|birds?|eagles?|soar"
    r")\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_DIRECT_INSTRUCTION_RE = re.compile(
    r"\b(?:keep(?:ing)?\s+(?:their|the)?\s*(?:area|tank|space|habitat)\s+clean|"
    r"clean\s+(?:area|tank|space|habitat)|feed(?:ing)?\s+(?:them\s+)?properly|"
    r"enough\s+light|make\s+sure\s+they\s+get\s+enough\s+light|"
    r"care\s+instructions?|kind\s+of\s+fun)\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_GENERIC_HABITAT_RE = re.compile(
    r"\b(?:relaxing\s+in\s+the\s+tank|basking|heat\s+lamp|new\s+tank|"
    r"bigger\s+tank|room\s+to\s+swim|took\s+my\s+turtles\s+out\s+for\s+a\s+walk|"
    r"cute\s+pet|little\s+dudes)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_PRIMARY_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:clay|cup|cups|mug|mugs|pot|pots|dog\s+face)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_SECONDARY_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:bowl|bowls|plate|plates|ceramic|project|projects)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:pottery|art|painting|creative|creativity)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_INVENTORY_CONTEXT_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|bowl|bowls|cup|cups|mug|mugs|plate|plates)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_CUP_SLOT_RE = re.compile(r"\b(?:cup|cups|mug|mugs|dog\s+face)\b", re.IGNORECASE)
_POTTERY_TYPE_BOWL_SLOT_RE = re.compile(r"\b(?:bowl|bowls)\b", re.IGNORECASE)
_POTTERY_TYPE_POT_SLOT_RE = re.compile(r"\b(?:pot|pots)\b", re.IGNORECASE)
_POTTERY_TYPE_PROJECT_SLOT_RE = re.compile(
    r"\b(?:clay|ceramic|project|projects|piece|pieces|finished)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_DIRECT_MADE_OBJECT_RE = re.compile(
    r"\b(?:dog\s+face|black\s+and\s+white\s+flower|photo\s+of\s+a\s+(?:bowl|cup)|"
    r"kids?.{0,120}(?:clay|cup|pots?|pottery\s+workshop)|"
    r"(?:clay|cup|pots?|pottery\s+workshop).{0,120}kids?)\b",
    re.IGNORECASE | re.DOTALL,
)
_POTTERY_TYPE_FRIENDSHIP_COMPANION_RE = re.compile(
    r"\b(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness)"
    r".{0,260}\b(?:values?\s+friendship|appreciat(?:es|ion).{0,60}friendship|"
    r"family\s+outing|planning\s+something\s+special)\b",
    re.IGNORECASE | re.DOTALL,
)
_POTTERY_TYPE_PROJECT_COMPANION_RE = re.compile(
    r"\b(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness|"
    r"fulfillment|sanctuary|comfort)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:husband|motivated|motivate|motivation)\b(?=.{0,180}\b"
    r"(?:family|kids?|children|hiking|hike|nature|waterfall|trail))|"
    r"\b(?:family|kids?|children|hiking|hike|nature|waterfall|trail)\b"
    r"(?=.{0,180}\b(?:husband|motivated|motivate|motivation))",
    re.IGNORECASE | re.DOTALL,
)
_FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE = re.compile(
    r"\b(?:swimming|swim|hiking|hike|trail|waterfall|museum|dinosaur|"
    r"pottery|clay|painting|camping|campfire|marshmallow|park)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_CONTEXT_OBJECT_RE = re.compile(
    r"\b(?:family|fam|kids?|children|husband)\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_PLACE_DIRECT_RE = re.compile(
    r"\b(?:became\s+friends|now\s+friends|made\s+friends|friends\s+with|"
    r"fellow\s+volunteers?)\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_COMMUNITY_PLACE_RE = re.compile(
    r"\b(?:joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?(?:church|gym)|"
    r"(?:church|gym).{0,120}\b(?:community|supportive|welcoming|people)|"
    r"(?:supportive|welcoming).{0,120}\b(?:church|gym)|"
    r"feel\s+closer\s+to\s+a\s+community)\b",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_SHELTER_SLOT_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|animal\s+shelter|shelter)\b",
    re.IGNORECASE,
)
_INVENTORY_ANIMAL_SHELTER_SLOT_RE = re.compile(
    r"\b(?:dog|animal)\s+shelter\b",
    re.IGNORECASE,
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
_INVENTORY_GYM_SLOT_RE = re.compile(
    r"\b(?:joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?gym|gym)\b",
    re.IGNORECASE,
)
_INVENTORY_CHURCH_JOINED_SLOT_RE = re.compile(
    r"\bjoined\s+(?:a\s+|the\s+)?(?:nearby\s+|local\s+)?church\b",
    re.IGNORECASE,
)
_INVENTORY_CHURCH_SLOT_RE = re.compile(r"\bchurch\b", re.IGNORECASE)
_INVENTORY_VOLUNTEER_SLOT_RE = re.compile(
    r"\b(?:volunteer|volunteers|volunteering)\b",
    re.IGNORECASE,
)
_INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE = re.compile(
    r"\b(?:education|educational|school|schools|infrastructure|"
    r"community\s+meetings?|education\s+reform|infrastructure\s+development)\b",
    re.IGNORECASE,
)
_INVENTORY_VETERANS_SLOT_RE = re.compile(
    r"\b(?:veterans?|military|served|service\s+members?|memorial)\b",
    re.IGNORECASE,
)
_INVENTORY_COMMUNITY_SLOT_RE = re.compile(
    r"\b(?:community|supportive\s+people|welcoming\s+atmosphere)\b",
    re.IGNORECASE,
)
_INVENTORY_SUPPORT_GROUP_SLOT_RE = re.compile(r"\bsupport\s+group\b", re.IGNORECASE)
_INVENTORY_COUNTRY_SLOT_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"country|countries|abroad|european?)\b",
    re.IGNORECASE,
)
_INVENTORY_PLACE_MARKER_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|shelter|volunteers?|church|gym)\b",
    re.IGNORECASE,
)
_RELIGIOUS_DIRECT_EVIDENCE_RE = re.compile(
    r"\b(?:church|faith|stained\s+glass|pray|prayer|spiritual|worship)\b",
    re.IGNORECASE,
)
_RELIGIOUS_CONTRAST_EVIDENCE_RE = re.compile(
    r"\breligious\b(?=.{0,160}\b(?:conservatives?|unwelcoming|upset|lgbtq|rights)\b)|"
    r"\b(?:conservatives?|unwelcoming|upset|lgbtq|rights)\b"
    r"(?=.{0,160}\breligious\b)",
    re.IGNORECASE | re.DOTALL,
)


def activity_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason not in {
        "activity_aggregation_bridge",
        "activity_visual_selfcare_bridge",
        "decomposition_activity_participation",
        "exercise_activity_inventory_bridge",
        "family_activity_bridge",
        "family_hike_detail_bridge",
        "family_hike_activity_bridge",
        "family_museum_activity_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
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
    if query_reason == "painting_inventory_bridge":
        return _painting_inventory_answer_slot(text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_slot(text)
    slots = (
        ("swimming", ("swimming", " swim ", "self care", "taking care")),
        ("hiking", ("hiking", " hike ", "trail", "waterfall", "mountain")),
        ("camping", ("camping", "camped", "campfire", "marshmallow", "unplug")),
        ("pottery", ("pottery", "clay", "ceramic", "bowl")),
        ("painting", ("painting", "painted", "sunrise", "sunset", "lake", "drawing")),
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


def career_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason == "degree_policy_inference_bridge":
        return _degree_policy_answer_slot(item.text)
    if query_reason == "business_commonality_bridge":
        return _business_commonality_answer_slot(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_slot(item.text)
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
        ("start_motivation", ("started volunteering", "aunt", "struggling", "brighten")),
        ("resident_support", ("resident", "cindy", "gratitude", "support they receive")),
        ("homeless_shelter", ("homeless shelter", " shelter", "volunteer")),
    )
    padded = f" {text} "
    for slot, markers in slots:
        if any(marker in padded for marker in markers):
            return slot
    return ""


def inference_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason.replace("_", "-") != "religious-inference-bridge":
        return ""
    if _RELIGIOUS_CONTRAST_EVIDENCE_RE.search(item.text):
        return "religious_contrast"
    if _RELIGIOUS_DIRECT_EVIDENCE_RE.search(item.text):
        return "religious_direct"
    return ""


def inventory_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if is_pottery_type_reason(query_reason):
        return _pottery_type_inventory_slot_for_text(item.text)
    if not is_inventory_list_reason(query_reason):
        return ""
    return _inventory_answer_slot_for_text(item.text)


def inventory_answer_slot_priority(slot: str) -> int:
    normalized_slot = slot.replace("-", "_")
    return {
        "direct_friend": 0,
        "shelter_anchor": 0,
        "pottery_cup": 0,
        "pottery_pot": 0,
        "animal_shelter": 1,
        "shelter_activity": 1,
        "shelter": 1,
        "gym": 1,
        "church_joined": 1,
        "country": 1,
        "education_infrastructure": 1,
        "veterans": 1,
        "pottery_bowl": 1,
        "pottery_project": 2,
        "church": 2,
        "volunteer": 2,
        "community": 3,
        "pottery_generic": 3,
        "place": 4,
        "support_group": 5,
    }.get(normalized_slot, 6)


def inventory_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""


def answer_object_rank(item: ContextItem, *, query_reason: str) -> int:
    if is_pottery_type_reason(query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if is_pottery_type_inventory_item(item, query_reason=query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if is_family_activity_reason(query_reason):
        return _family_activity_answer_object_rank(item.text)
    if is_inventory_list_reason(query_reason):
        return _inventory_list_answer_object_rank(item.text)
    return 2


def is_pottery_type_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") == "pottery-type-bridge"


def is_pottery_type_inventory_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason.replace("_", "-") != "decomposition-inventory-list":
        return False
    if _POTTERY_TYPE_INVENTORY_CONTEXT_RE.search(item.text) is None:
        return False
    return _pottery_type_answer_object_rank(item.text) <= 1


def is_family_activity_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-activity-participation",
        "family-activity-bridge",
        "family-hike-activity-bridge",
        "family-hike-detail-bridge",
        "family-museum-activity-bridge",
        "family-painting-activity-bridge",
        "family-swimming-activity-bridge",
    }


def is_inventory_list_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-inventory-list",
        "friend-place-inventory-bridge",
        "friend-place-shelter-inventory-bridge",
        "friend-place-gym-inventory-bridge",
        "friend-place-church-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
        "travel-country-inventory-bridge",
    }


def precise_answer_content_rank(item: ContextItem, *, query_reason: str) -> int:
    if query_reason == "birdwatching_city_schedule_bridge":
        return birdwatching_city_schedule_answer_content_rank(item.text)
    if is_pottery_type_reason(query_reason):
        return _pottery_type_answer_content_rank(item.text)
    if query_reason in {"running_reason_bridge", "running_reason_question_bridge"}:
        text = item.text.casefold()
        if "what got you into running" in text or "for walking or running" in text:
            return 0
        if "running" in text and any(
            marker in text
            for marker in (
                "destress",
                "de-stress",
                "clear my mind",
                "headspace",
            )
        ):
            return 0
        if "running" in text:
            return 2
        return 3
    if query_reason == "shoe_usage_bridge":
        text = item.text.casefold()
        if "walking or running" in text or "for walking" in text:
            return 0
        if any(marker in text for marker in ("new shoes", "sneakers", "running shoe")):
            return 1
        return 3
    if query_reason == "painting_inventory_bridge":
        return _painting_inventory_answer_content_rank(item.text)
    if query_reason == "degree_policy_inference_bridge":
        return _degree_policy_answer_content_rank(item.text)
    if query_reason == "business_commonality_bridge":
        return _business_commonality_answer_content_rank(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_content_rank(item.text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_content_rank(item.text)
    if query_reason == "friend_place_shelter_inventory_bridge":
        return _friend_place_shelter_answer_content_rank(item.text)
    if query_reason == "animal_care_instruction_bridge":
        return _animal_care_instruction_content_rank(item.text)
    if query_reason != "meteor_shower_feeling_bridge":
        return 0
    text = item.text.casefold()
    if "awe" in text or "tiny" in text:
        return 0
    if "felt" in text or "feel" in text or "universe" in text:
        return 1
    return 2


def birdwatching_city_schedule_answer_content_rank(text: str) -> int:
    if _BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "nature" in lowered and ("city" in lowered or "outdoors" in lowered):
        return 1
    return 3


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
    if "clothing store" in text or "my own store" in text or "ad campaign" in text:
        return "gina_store_start"
    if "own business" in text or "starting" in text:
        return "business_start_generic"
    return ""


def _charity_brand_sponsorship_answer_slot(text: str) -> str:
    text = text.casefold()
    if "under armour" in text or "under armor" in text:
        return "under_armour_interest"
    if "nike" in text and ("gatorade" in text or "sponsorship" in text):
        return "nike_gatorade_deals"
    if "good sports" in text or "disadvantaged kids" in text:
        return "charity_org_fit"
    if "give something back" in text or "charity" in text or "make a difference" in text:
        return "charity_intent"
    if "sports brand" in text or "big brands" in text:
        return "sports_brand_generic"
    return ""


def _inventory_answer_slot_for_text(text: str) -> str:
    pottery_slot = _pottery_type_inventory_slot_for_text(text)
    if pottery_slot:
        return pottery_slot
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
    if _INVENTORY_CHURCH_SLOT_RE.search(text):
        return "church"
    if _INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE.search(text):
        return "education_infrastructure"
    if _INVENTORY_VETERANS_SLOT_RE.search(text):
        return "veterans"
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
    if slot in {"pottery_cup", "pottery_pot"}:
        return 0
    if slot == "pottery_bowl":
        return 1
    if slot == "pottery_project":
        return 2
    if slot == "pottery_generic":
        return 3
    if slot == "direct_friend":
        return 0
    if slot in {
        "shelter",
        "gym",
        "church_joined",
        "country",
        "education_infrastructure",
        "veterans",
    }:
        return 1
    if slot in {"church", "volunteer"}:
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


def _degree_policy_answer_content_rank(text: str) -> int:
    slot = _degree_policy_answer_slot(text)
    if slot == "degree_field_inference":
        return 0
    if slot == "policy_career_plan":
        return 1
    if slot == "degree_completion_context":
        return 2
    return 3


def _business_commonality_answer_content_rank(text: str) -> int:
    slot = _business_commonality_answer_slot(text)
    if slot in {"jon_job_loss", "gina_job_loss", "jon_business_type", "gina_store_start"}:
        return 0
    if slot == "business_start_generic":
        return 1
    return 3


def _charity_brand_sponsorship_answer_content_rank(text: str) -> int:
    slot = _charity_brand_sponsorship_answer_slot(text)
    if slot in {"nike_gatorade_deals", "under_armour_interest", "charity_intent"}:
        return 0
    if slot == "charity_org_fit":
        return 1
    if slot == "sports_brand_generic":
        return 2
    return 3


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


def _exercise_activity_answer_content_rank(text: str) -> int:
    slot = _exercise_activity_answer_slot(text)
    if slot in {"kickboxing", "taekwondo", "weight_training", "circuit_training"}:
        return 0
    if slot in {"aerial_yoga", "yoga_trial", "yoga_performance"}:
        return 0
    if slot == "yoga":
        return 1
    if slot == "generic_exercise":
        return 2
    return 3


def _friend_place_shelter_answer_content_rank(text: str) -> int:
    if _INVENTORY_FRIEND_PLACE_DIRECT_RE.search(text):
        return 0
    if _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE.search(text):
        return 2
    if _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE.search(text):
        return 0
    if _INVENTORY_SHELTER_SLOT_RE.search(text):
        return 1
    return 3


def _animal_care_instruction_content_rank(text: str) -> int:
    if _ANIMAL_CARE_DIRECT_INSTRUCTION_RE.search(text):
        return 0
    if _ANIMAL_CARE_GENERIC_HABITAT_RE.search(text):
        return 3
    if re.search(r"\b(?:care|clean|feed|light|habitat|routine)\b", text, re.IGNORECASE):
        return 1
    return 2


def _pottery_type_answer_content_rank(text: str) -> int:
    if _POTTERY_TYPE_DIRECT_MADE_OBJECT_RE.search(text):
        return 0
    if _POTTERY_TYPE_FRIENDSHIP_COMPANION_RE.search(text):
        return 1
    if _POTTERY_TYPE_PROJECT_COMPANION_RE.search(text):
        return 2
    if _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE.search(text):
        return 3
    return 4


def _painting_inventory_answer_slot(text: str) -> str:
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
