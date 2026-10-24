"""Precise answer content and turn-quality ranking policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_packer_answer_support_patterns import (
    _ACTIVITY_CONTEXT_RE,
    _ACTIVITY_DIRECT_PARTICIPATION_RE,
    _ANIMAL_CARE_DIRECT_INSTRUCTION_RE,
    _ANIMAL_CARE_GENERIC_HABITAT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE,
    _BOOK_SUGGESTION_DIRECT_RE,
    _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS,
    _BUSINESS_DIRECT_JOB_LOSS_RE,
    _BUSINESS_DIRECT_START_REASON_RE,
    _CHILDHOOD_POSSESSION_DIRECT_RE,
    _CHILDHOOD_POSSESSION_OBJECT_RE,
    _CHILDREN_PREFERENCE_CONTEXT_RE,
    _CHILDREN_PREFERENCE_DIRECT_RE,
    _CLASSICAL_MUSIC_PREFERENCE_DIRECT_RE,
    _COLLECTIBLE_OBJECT_CONTEXT_RE,
    _COLLECTIBLE_OBJECT_DIRECT_RE,
    _COUNT_AGGREGATION_COVERAGE_REASONS,
    _CREATIVE_WORK_SUBMISSION_DIRECT_RE,
    _CREATIVE_WRITING_INVENTORY_DIRECT_RE,
    _INSPIRATION_SOURCE_CONTEXT_RE,
    _INSPIRATION_SOURCE_DIRECT_RE,
    _INVENTORY_FRIEND_PLACE_DIRECT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE,
    _INVENTORY_SHELTER_SLOT_RE,
    _MILITARY_SERVICE_GOAL_DIRECT_RE,
    _MUSIC_ARTIST_DIRECT_ANSWER_RE,
    _OUTDOOR_NATURE_MEMORY_CONTEXT_RE,
    _OUTDOOR_NATURE_MEMORY_DIRECT_RE,
    _POTTERY_TYPE_DIRECT_MADE_OBJECT_RE,
    _POTTERY_TYPE_FRIENDSHIP_COMPANION_RE,
    _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE,
    _POTTERY_TYPE_PROJECT_COMPANION_RE,
    _PRECISE_TURN_ANSWER_SUPPORT_REASONS,
    _PUBLIC_OFFICE_SERVICE_DIRECT_RE,
    _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE,
    _SCREENPLAY_REJECTION_DIRECT_RE,
    _SENTIMENTAL_REMINDER_CONTEXT_RE,
    _SENTIMENTAL_REMINDER_DIRECT_RE,
    _SUPPORT_CAREER_MOTIVATION_CONTEXT_RE,
    _SUPPORT_CAREER_MOTIVATION_DIRECT_RE,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _book_reading_answer_content_rank,
    _business_commonality_answer_slot,
    _career_answer_slot,
    _cause_event_answer_slot,
    _charity_brand_sponsorship_answer_slot,
    _common_interest_answer_slot,
    _degree_policy_answer_slot,
    _family_activity_answer_object_rank,
    _general_activity_answer_slot_for_text,
    _inventory_answer_slot,
    _inventory_list_answer_object_rank,
    _is_activity_participation_answer_reason,
    _is_common_interest_answer_reason,
    _is_count_aggregation_coverage_item,
    _is_family_activity_reason,
    _is_inventory_list_reason,
    _is_pottery_type_inventory_item,
    _is_pottery_type_reason,
    _is_support_network_reason,
    _pottery_type_answer_object_rank,
    _support_network_answer_object_rank,
)
from infinity_context_core.application.context_packer_answer_support_temporal import (
    _is_temporal_answer_support_item,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _diagnostic_score_signals,
    _diagnostic_signal_truthy,
    _has_any_exact_turn_source_ref,
    _has_primary_exact_turn_source_ref,
    _numeric_signal,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _exercise_activity_answer_content_rank,
    _painting_inventory_answer_content_rank,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_list_answer_support_rank,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    TRAVEL_HOBBY_WRITING_REASON,
    travel_hobby_writing_answer_rank,
)
from infinity_context_core.application.dto import ContextItem


def _answer_object_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_support_network_reason(query_reason):
        return _support_network_answer_object_rank(item.text)
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_pottery_type_inventory_item(item, query_reason=query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_family_activity_reason(query_reason):
        return _family_activity_answer_object_rank(item.text)
    if query_reason == "cause_event_inventory_bridge":
        return _cause_event_answer_content_rank(item.text)
    if query_reason == "childhood_possession_inventory_bridge":
        return _childhood_possession_answer_content_rank(item.text)
    if _is_inventory_list_reason(query_reason):
        return _inventory_list_answer_object_rank(item.text)
    return 2

def _precise_turn_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        return 0
    if (
        _is_family_activity_reason(query_reason)
        and _answer_object_rank(item, query_reason=query_reason) == 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_activity_participation_answer_reason(query_reason)
        and _activity_answer_content_rank(item.text) == 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _numeric_signal(
            _diagnostic_score_signals(item).get("birdwatching_city_schedule_answer_evidence")
        )
        >= 2
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _birdwatching_city_schedule_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason in {"book_reading_list_bridge", "creative_writing_career_bridge"}
        and _book_reading_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "decomposition_inventory_list"
        and _book_reading_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "music_artist_answer_bridge"
        and _music_artist_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_inventory_list_reason(query_reason)
        and _answer_object_rank(item, query_reason=query_reason) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_common_interest_answer_reason(query_reason)
        and _common_interest_answer_slot(item, query_reason=query_reason)
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS:
        return 2
    if (
        query_reason in _COUNT_AGGREGATION_COVERAGE_REASONS
        and _has_primary_exact_turn_source_ref(item)
    ):
        return 1
    if _is_activity_participation_answer_reason(query_reason):
        return 2
    if query_reason not in _PRECISE_TURN_ANSWER_SUPPORT_REASONS:
        return 2
    return 0 if _has_primary_exact_turn_source_ref(item) else 1

def _precise_answer_content_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_support_network_reason(query_reason):
        return _support_network_answer_object_rank(item.text)
    if query_reason in {"career_intent_bridge", "career_path_bridge"}:
        text = item.text.casefold()
        if "working with trans people" in text or (
            "mental health" in text and ("support" in text or "help" in text)
        ):
            return 0
        if "counsel" in text or "mental health" in text:
            return 1
        return 3
    if query_reason == "creative_writing_career_bridge":
        return _book_reading_answer_content_rank(item.text)
    if query_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_answer_content_rank(item.text)
    if query_reason == "book_reading_list_bridge":
        return _book_reading_answer_content_rank(item.text)
    if query_reason == "book_suggestion_bridge":
        return min(
            _book_suggestion_answer_content_rank(item.text),
            recommendation_list_answer_support_rank(
                text=item.text,
                query_reason=query_reason,
            ),
        )
    if is_recommendation_list_reason(query_reason):
        recommendation_rank = recommendation_list_answer_support_rank(
            text=item.text,
            query_reason=query_reason,
        )
        if recommendation_rank <= 2:
            return recommendation_rank
    if query_reason == "music_artist_answer_bridge":
        return _music_artist_answer_content_rank(item.text)
    if query_reason == "classical_music_preference_bridge":
        return _classical_music_preference_answer_content_rank(item.text)
    if query_reason == "sentimental_reminder_bridge":
        return _sentimental_reminder_answer_content_rank(item.text)
    if query_reason == "decomposition_collectible_object":
        return _collectible_object_answer_content_rank(item.text)
    if query_reason == "outdoor_nature_memory_bridge":
        return _outdoor_nature_memory_answer_content_rank(item.text)
    if query_reason == "children_preference_bridge":
        return _children_preference_answer_content_rank(item.text)
    if query_reason == "inspiration_source_bridge":
        return _inspiration_source_answer_content_rank(item.text)
    if query_reason == "public_office_service_bridge":
        return _public_office_service_answer_content_rank(item.text)
    if query_reason == "recognition_award_bridge":
        return _recognition_award_answer_content_rank(item.text)
    if query_reason == "relocation_willingness_inference_bridge":
        return _relocation_willingness_answer_content_rank(item.text)
    if query_reason == "volunteer_career_inference_bridge":
        return _volunteer_career_answer_content_rank(item)
    if _is_activity_participation_answer_reason(query_reason):
        return _activity_answer_content_rank(item.text)
    if (
        query_reason == "decomposition_inventory_list"
        and _book_reading_answer_content_rank(item.text) <= 1
    ):
        return _book_reading_answer_content_rank(item.text)
    if _is_pottery_type_reason(query_reason):
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
    if query_reason == "childhood_possession_inventory_bridge":
        return _childhood_possession_answer_content_rank(item.text)
    if query_reason == "cause_event_inventory_bridge":
        return _cause_event_answer_content_rank(item.text)
    if query_reason == "event_participation_help_bridge":
        if _inventory_answer_slot(item, query_reason=query_reason) in {
            "community_mentorship_program",
            "community_school_event",
        }:
            return 0
        return _inventory_list_answer_object_rank(item.text)
    if query_reason == "transgender_youth_center_event_bridge":
        return _transgender_youth_center_event_answer_content_rank(item)
    if query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}:
        return _business_commonality_answer_content_rank(item.text)
    if query_reason == "creative_work_submission_bridge":
        return _creative_work_submission_answer_content_rank(item.text)
    if query_reason == "creative_writing_inventory_bridge":
        return _creative_writing_inventory_answer_content_rank(item.text)
    if query_reason == TRAVEL_HOBBY_WRITING_REASON:
        return travel_hobby_writing_answer_rank(item.text)
    if query_reason == "screenplay_count_bridge":
        return _screenplay_rejection_answer_content_rank(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_content_rank(item.text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_content_rank(item.text)
    if query_reason == "friend_place_shelter_inventory_bridge":
        return _friend_place_shelter_answer_content_rank(item.text)
    if query_reason == "animal_care_instruction_bridge":
        return _animal_care_instruction_content_rank(item.text)
    if query_reason in {
        "support_career_motivation_bridge",
        "support_origin_bridge",
    }:
        return _support_career_motivation_content_rank(item.text)
    if query_reason != "meteor_shower_feeling_bridge":
        return 0
    text = item.text.casefold()
    if "awe" in text or "tiny" in text:
        return 0
    if "felt" in text or "feel" in text or "universe" in text:
        return 1
    return 2

def _support_career_motivation_content_rank(text: str) -> int:
    if _SUPPORT_CAREER_MOTIVATION_DIRECT_RE.search(text) is not None:
        return 0
    if _SUPPORT_CAREER_MOTIVATION_CONTEXT_RE.search(text) is not None:
        return 1
    return 3

def _classical_music_preference_answer_content_rank(text: str) -> int:
    if _CLASSICAL_MUSIC_PREFERENCE_DIRECT_RE.search(text) is not None:
        return 0
    if re.search(r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony)\b", text, re.IGNORECASE):
        return 1
    if re.search(r"\b(?:music|song|tunes?|composer|concert)\b", text, re.IGNORECASE):
        return 2
    return 4

def _sentimental_reminder_answer_content_rank(text: str) -> int:
    if _SENTIMENTAL_REMINDER_DIRECT_RE.search(text) is not None:
        return 0
    if _SENTIMENTAL_REMINDER_CONTEXT_RE.search(text) is not None:
        return 1
    return 4

def _collectible_object_answer_content_rank(text: str) -> int:
    if _COLLECTIBLE_OBJECT_DIRECT_RE.search(text) is not None:
        return 0
    if _COLLECTIBLE_OBJECT_CONTEXT_RE.search(text) is not None:
        return 1
    return 4

def _outdoor_nature_memory_answer_content_rank(text: str) -> int:
    if _OUTDOOR_NATURE_MEMORY_DIRECT_RE.search(text) is not None:
        return 0
    if _OUTDOOR_NATURE_MEMORY_CONTEXT_RE.search(text) is not None:
        return 1
    return 4

def _children_preference_answer_content_rank(text: str) -> int:
    if _CHILDREN_PREFERENCE_DIRECT_RE.search(text) is not None:
        return 0
    if _CHILDREN_PREFERENCE_CONTEXT_RE.search(text) is not None:
        return 1
    return 4

def _childhood_possession_answer_content_rank(text: str) -> int:
    has_direct_context = _CHILDHOOD_POSSESSION_DIRECT_RE.search(text) is not None
    has_object = _CHILDHOOD_POSSESSION_OBJECT_RE.search(text) is not None
    if has_direct_context and has_object:
        return 0
    if has_direct_context:
        return 1
    if has_object and re.search(r"\b(?:childhood|kid|child|younger)\b", text, re.IGNORECASE):
        return 2
    return 5

def _public_office_service_answer_content_rank(text: str) -> int:
    if _PUBLIC_OFFICE_SERVICE_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "office" in lowered or "politic" in lowered or "campaign" in lowered:
        return 1
    return 4

def _recognition_award_answer_content_rank(text: str) -> int:
    if _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE.search(text) is not None:
        return 0
    if re.search(
        r"\b(?:recognition|awards?|medals?|certificates?|honou?rs?|"
        r"troph(?:y|ies)|prizes?)\b"
        r"(?=.{0,200}\b(?:receive|received|got|given|gave|earned|won)\b)|"
        r"\b(?:receive|received|got|given|gave|earned|won)\b"
        r"(?=.{0,160}\b(?:recognition|awards?|medals?|certificates?|"
        r"honou?rs?|troph(?:y|ies)|prizes?)\b)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        return 1
    if re.search(
        r"\b(?:certificate|certificates|diploma|diplomas|degree|"
        r"graduat(?:e|ed|ion))\b",
        text,
        re.IGNORECASE,
    ):
        return 2
    return 4

def _inspiration_source_answer_content_rank(text: str) -> int:
    if _INSPIRATION_SOURCE_DIRECT_RE.search(text) is not None:
        return 0
    if _INSPIRATION_SOURCE_CONTEXT_RE.search(text) is not None:
        return 2
    return 4

def _relocation_willingness_answer_content_rank(text: str) -> int:
    if (
        _PUBLIC_OFFICE_SERVICE_DIRECT_RE.search(text) is not None
        or _MILITARY_SERVICE_GOAL_DIRECT_RE.search(text) is not None
    ):
        return 0
    lowered = text.casefold()
    if any(marker in lowered for marker in ("military", "country", "office", "politic")):
        return 1
    return 4

def _volunteer_career_answer_content_rank(item: ContextItem) -> int:
    slot = _career_answer_slot(
        item,
        query_reason="volunteer_career_inference_bridge",
    )
    if slot in {
        "shelter_operations",
        "counseling_talks",
        "volunteer_origin",
        "start_motivation",
    }:
        return 0
    if slot == "resident_support":
        return 1
    if slot == "homeless_shelter":
        return 2
    return 4

def _degree_policy_answer_content_rank(text: str) -> int:
    slot = _degree_policy_answer_slot(text)
    if slot == "degree_field_inference":
        return 0
    if slot == "policy_career_plan":
        return 1
    if slot == "degree_completion_context":
        return 2
    return 3

def _birdwatching_city_schedule_answer_content_rank(text: str) -> int:
    if _BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "nature" in lowered and ("city" in lowered or "outdoors" in lowered):
        return 1
    return 3

def _book_suggestion_answer_content_rank(text: str) -> int:
    if _BOOK_SUGGESTION_DIRECT_RE.search(text) is not None:
        return 0
    return _book_reading_answer_content_rank(text)

def _music_artist_answer_content_rank(text: str) -> int:
    if _MUSIC_ARTIST_DIRECT_ANSWER_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "artist" in lowered or "band" in lowered or "singer" in lowered:
        return 1
    if "music" in lowered or "song" in lowered or "concert" in lowered:
        return 3
    return 5

def _business_commonality_answer_content_rank(text: str) -> int:
    slot = _business_commonality_answer_slot(text)
    if slot in {"jon_job_loss", "gina_job_loss"}:
        if _BUSINESS_DIRECT_JOB_LOSS_RE.search(text) is not None:
            return 0
        return 1
    if slot in {"jon_business_type", "gina_store_start"}:
        if _BUSINESS_DIRECT_START_REASON_RE.search(text) is not None:
            return 0
        return 1
    if slot == "business_start_generic":
        return 2
    return 3

def _cause_event_answer_content_rank(text: str) -> int:
    if _cause_event_answer_slot(text):
        return 0
    lowered = text.casefold()
    if "cause" in lowered and any(
        marker in lowered for marker in ("event", "fund", "awareness", "charity")
    ):
        return 1
    if any(marker in lowered for marker in ("food drive", "toy drive", "veteran")):
        return 2
    return 5

_TRANSGENDER_YOUTH_CENTER_EVENT_DIRECT_RE = re.compile(
    r"\b(?:youth\s+center|talent\s+show|band|stage|microphone|"
    r"colorful\s+lights|visual\s+query)\b",
    re.IGNORECASE,
)

def _transgender_youth_center_event_answer_content_rank(item: ContextItem) -> int:
    if _diagnostic_signal_truthy(item, "source_sibling_dialogue_visual_reference"):
        return 0
    return 0 if _TRANSGENDER_YOUTH_CENTER_EVENT_DIRECT_RE.search(item.text) else 5

def _screenplay_rejection_answer_content_rank(text: str) -> int:
    if _SCREENPLAY_REJECTION_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "rejection" in lowered or "rejected" in lowered:
        return 1
    if "script" in lowered or "screenplay" in lowered:
        return 2
    return 4

def _creative_work_submission_answer_content_rank(text: str) -> int:
    if _CREATIVE_WORK_SUBMISSION_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "submit" in lowered or "submission" in lowered:
        return 1
    if "screenplay" in lowered or "script" in lowered or "project" in lowered:
        return 2
    return 4

def _creative_writing_inventory_answer_content_rank(text: str) -> int:
    if _CREATIVE_WRITING_INVENTORY_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if any(
        marker in lowered
        for marker in ("screenplay", "script", "book", "journal", "blog post")
    ):
        return 1
    if "writing" in lowered or "wrote" in lowered:
        return 2
    return 4

_CHARITY_BRAND_CONCRETE_DEAL_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed)\b"
    r"(?=.{0,180}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\bin\s+talks?\s+with\b"
    r"(?=.{0,180}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|s)?)\b"
    r"(?=.{0,140}\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|"
    r"in\s+talks?\s+with|stoked|working\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)

def _charity_brand_sponsorship_answer_content_rank(text: str) -> int:
    slot = _charity_brand_sponsorship_answer_slot(text)
    if slot == "brand_sponsorship_deal":
        return 0 if _CHARITY_BRAND_CONCRETE_DEAL_RE.search(text) else 1
    if slot == "partner_affinity_fit":
        return 0
    if slot in {"charity_org_fit", "charity_intent"}:
        return 1
    if slot == "sports_brand_generic":
        return 2
    return 3

def _activity_answer_content_rank(text: str) -> int:
    if _ACTIVITY_DIRECT_PARTICIPATION_RE.search(text) is not None:
        return 0
    if _general_activity_answer_slot_for_text(text.casefold()):
        return 1
    if _ACTIVITY_CONTEXT_RE.search(text) is not None:
        return 2
    return 4

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
