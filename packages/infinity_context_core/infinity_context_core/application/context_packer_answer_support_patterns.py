"""Compiled answer-support patterns for context packing."""

from __future__ import annotations

import re

from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS = 8
_MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS = 12
_MAX_ANSWER_SUPPORT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 1
_MAX_ANSWER_SUPPORT_EVENT_SLOT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 2
_MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 6
_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS = frozenset(
    {
        "adoption-current-goal-bridge",
        "adoption-current-milestone-bridge",
        "activity-aggregation-bridge",
        "activity-competition-evidence-bridge",
        "activity-visual-selfcare-bridge",
        "birdwatching-city-schedule-bridge",
        "book-reading-list-bridge",
        "board-game-inventory-bridge",
        "animal-activity-inventory-bridge",
        "book-suggestion-bridge",
        "business-commonality-bridge",
        "career-path-bridge",
        "charity-brand-sponsorship-bridge",
        "charity-tournament-count-bridge",
        "children-count-event-bridge",
        "children-count-sibling-bridge",
        "children-preference-bridge",
        "commonality-interest-bridge",
        "creative-work-submission-bridge",
        "creative-writing-inventory-bridge",
        "creative-writing-career-bridge",
        "cause-event-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
        "childhood-possession-inventory-bridge",
        "church-friend-activity-inventory-bridge",
        "classical-music-preference-bridge",
        "decomposition-activity-duration",
        "decomposition-activity-participation",
        "decomposition-attribute-aggregation",
        "decomposition-collectible-object",
        "destress-activity-bridge",
        "decomposition-frequency-recurrence",
        "decomposition-inventory-list",
        "decomposition-quantity-count",
        "degree-policy-inference-bridge",
        "event-participation-bridge",
        "event-participation-help-bridge",
        "exercise-activity-inventory-bridge",
        "family-activity-bridge",
        "family-hike-detail-bridge",
        "family-hike-activity-bridge",
        "family-museum-activity-bridge",
        "friend-place-inventory-bridge",
        "friend-place-shelter-inventory-bridge",
        "friend-place-gym-inventory-bridge",
        "friend-place-church-inventory-bridge",
        "fundraiser-event-inventory-bridge",
        "family-painting-activity-bridge",
        "family-swimming-activity-bridge",
        "game-win-count-bridge",
        "hobby-interest-bridge",
        "hike-count-activity-bridge",
        "inspiration-source-bridge",
        "item-purchase-bridge",
        "community-participation-bridge",
        "lgbtq-community-participation-bridge",
        "music-artist-band-bridge",
        "music-artist-answer-bridge",
        "music-event-inventory-bridge",
        "national-park-inference-bridge",
        "outdoor-activity-inventory-bridge",
        "painting-inventory-bridge",
        "place-area-inventory-bridge",
        "pottery-type-bridge",
        "recommendation-source-bridge",
        "repeated-test-attempt-bridge",
        "religious-inference-bridge",
        "running-reason-bridge",
        "running-reason-question-bridge",
        "pet-count-bridge",
        "skill-teaching-inventory-bridge",
        "screenplay-count-bridge",
        "symbol-importance-bridge",
        "transgender-youth-center-event-bridge",
        "tournament-count-bridge",
        "travel-country-inventory-bridge",
        "veterans-event-inventory-bridge",
        "volunteering-people-inventory-bridge",
        "volunteering-inventory-bridge",
        "volunteer-career-inference-bridge",
    }
)
_COUNT_AGGREGATION_COVERAGE_REASONS = frozenset(
    {
        "beach_count_activity_bridge",
        "hike_count_activity_bridge",
        "hiking_trail_count_bridge",
        "pet_count_bridge",
        "repeated_test_attempt_bridge",
        "tournament_count_bridge",
    }
)
_ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS = frozenset(
    {
        "inspiration_source_bridge",
    }
)
_MAX_PRECISE_ANSWER_SUPPORT_DIVERSITY_ITEMS = 8
_BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS = frozenset(
    {
        "activity_visual_selfcare_bridge",
        "birdwatching_city_schedule_bridge",
        "book_suggestion_bridge",
    }
)
_BROAD_EVIDENCE_TURN_SLOT_REASONS = frozenset(
    {
        "birdwatching_city_schedule_bridge",
        "book_suggestion_bridge",
    }
)
_COMMON_INTEREST_ANSWER_SUPPORT_REASONS = frozenset(
    {
        "commonality_interest_bridge",
        "hobby_interest_bridge",
    }
)
_EXACT_PRECISE_CONTENT_TURN_REASONS = frozenset(
    {
        "activity_visual_selfcare_bridge",
        "business_commonality_bridge",
        "business_start_reason_bridge",
        "book_suggestion_bridge",
        "children_preference_bridge",
        "cause_event_inventory_bridge",
        "childhood_possession_inventory_bridge",
        "creative_work_submission_bridge",
        "creative_writing_career_bridge",
        "creative_writing_inventory_bridge",
        "customer_experience_bridge",
        "event_participation_help_bridge",
        "grand_opening_support_bridge",
        "inspiration_source_bridge",
        "outdoor_nature_memory_bridge",
        "pet_adjustment_bridge",
        "planning_tool_use_bridge",
        "public_office_service_bridge",
        "recognition_award_bridge",
        "relocation_willingness_inference_bridge",
        "screenplay_count_bridge",
        "transgender_youth_center_event_bridge",
        "volunteer_career_inference_bridge",
    }
)
_DIRECT_EVIDENCE_QUERY_FOCUS_REASONS = frozenset(
    {
        "children_preference_bridge",
        "cause_event_inventory_bridge",
        "childhood_possession_inventory_bridge",
        "book_suggestion_bridge",
        "creative_work_submission_bridge",
        "creative_writing_inventory_bridge",
        "charity_brand_sponsorship_bridge",
        "customer_experience_bridge",
        "destress_activity_bridge",
        "grand_opening_support_bridge",
        "inspiration_source_bridge",
        "pet_adjustment_bridge",
        "planning_tool_use_bridge",
        "public_office_service_bridge",
        "recognition_award_bridge",
        "relocation_willingness_inference_bridge",
        "transgender_youth_center_event_bridge",
        "volunteer_career_inference_bridge",
    }
)
_PRECISE_TURN_ANSWER_SUPPORT_REASONS = PRECISE_TURN_SOURCE_SIBLING_REASONS | frozenset(
    {
        "activity_aggregation_bridge",
        "activity_competition_evidence_bridge",
        "animal_activity_inventory_bridge",
        "book_reading_list_bridge",
        "career_intent_bridge",
        "career_path_bridge",
        "cause_event_inventory_bridge",
        "childhood_possession_inventory_bridge",
        "creative_work_submission_bridge",
        "creative_writing_inventory_bridge",
        "creative_writing_career_bridge",
        "children_preference_bridge",
        "community_participation_bridge",
        "exercise_activity_inventory_bridge",
        "destress_activity_bridge",
        "food_recipe_recommendation_bridge",
        "lgbtq_community_participation_bridge",
        "meteor_shower_feeling_bridge",
        "music_artist_answer_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "sentimental_reminder_bridge",
        "wellness_activity_effect_bridge",
        "negative_experience_support_bridge",
        "screenplay_count_bridge",
        "support_career_motivation_bridge",
        "support_origin_bridge",
        "support_network_bridge",
        "transgender_youth_center_event_bridge",
    }
)
_DIVERSITY_PRECISE_TURN_REASONS = frozenset(
    {
        "birdwatching_city_schedule_bridge",
        "food_recipe_recommendation_bridge",
        "wellness_activity_effect_bridge",
    }
)
_BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE = re.compile(
    r"\b("
    r"busy\s+week|city\s+schedule|schedule|"
    r"binos|binoculars|notebook|log\s+them|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"birdwatching|watching\s+birds?|birds?|eagles?|soar"
    r")\b",
    re.IGNORECASE,
)
_SUPPORT_CAREER_MOTIVATION_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:support|love|acceptance)\b(?=.{0,180}\b(?:journey|pass\s+it\s+on|"
    r"supportive\s+community|hope|understanding|acceptance)\b)|"
    r"(?:made\s+a\s+huge\s+difference|made\s+.*\bdifference|"
    r"counseling\s+and\s+support\s+groups|support\s+groups\s+improved|"
    r"improved\s+my\s+life|now\s+i\s+want\s+to\s+help|safe,\s*inviting\s+place)"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_SUPPORT_CAREER_MOTIVATION_CONTEXT_RE = re.compile(
    r"\b(?:support|journey|counsel(?:ing|or)?|mental\s+health|help\s+people|"
    r"supportive\s+community|understanding|acceptance|hope)\b",
    re.IGNORECASE,
)
_SENTIMENTAL_REMINDER_DIRECT_RE = re.compile(
    r"\b(?:reminds?|reminder|sentimental\s+value|symboli[sz](?:es|ed)?|"
    r"meaning|means|stands?\s+for)\b(?=.{0,220}\b(?:art|self[-\s]?expression|"
    r"friend|birthday|gift|memory|pattern|colou?rs?|childhood|love|faith|"
    r"strength|roots?|family|keepsake)\b)|"
    r"\b(?:sentimental\s+value|hand[-\s]?painted|keepsake|gift|birthday|"
    r"pattern|colou?rs?)\b(?=.{0,220}\b(?:reminds?|reminder|symbol|meaning|"
    r"self[-\s]?expression)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SENTIMENTAL_REMINDER_CONTEXT_RE = re.compile(
    r"\b(?:reminds?|reminder|sentimental|symbol|meaning|gift|memory|keepsake|"
    r"pattern|colou?rs?|self[-\s]?expression)\b",
    re.IGNORECASE,
)
_COLLECTIBLE_OBJECT_DIRECT_RE = re.compile(
    r"\b(?:signed|autographed|autograph)\b"
    r"(?=.{0,220}\b(?:balls?|basketballs?|jerseys?|photos?|pictures?|cards?|"
    r"posters?|keepsakes?|mementos?|gifts?|presents?|possessions?|"
    r"collectibles?|memorabilia|teammates?|friends?|favorite\s+player)\b)|"
    r"\b(?:prized\s+possession|keepsakes?|mementos?|collectibles?|memorabilia|"
    r"gifts?|presents?)\b"
    r"(?=.{0,220}\b(?:signed|autographed|autograph|balls?|basketballs?|"
    r"jerseys?|photos?|pictures?|reminds?|reminder|bond|friendship|"
    r"appreciation|teammates?|favorite\s+player)\b)|"
    r"\b(?:reminds?|reminder)\b"
    r"(?=.{0,220}\b(?:bond|friendship|appreciation|teammates?|team\s+spirit|"
    r"friends?|signed|autographed|balls?|basketballs?|keepsakes?|mementos?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COLLECTIBLE_OBJECT_CONTEXT_RE = re.compile(
    r"\b(?:collectibles?|collection|memorabilia|keepsakes?|mementos?|"
    r"possessions?|signed|autographed|autograph|reminds?|reminder|bond|"
    r"friendship|appreciation)\b",
    re.IGNORECASE,
)
_CLASSICAL_MUSIC_PREFERENCE_DIRECT_RE = re.compile(
    r"\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|fav(?:orite)?|into)\b"
    r"(?=.{0,180}\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|"
    r"composer|violin|clarinet|tunes?|songs?|music)\b)|"
    r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|composer)\b"
    r"(?=.{0,180}\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|"
    r"fav(?:orite)?|tunes?|songs?|music)\b)",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_NATURE_MEMORY_DIRECT_RE = re.compile(
    r"\b(?:camp(?:ing)?\s+trip|camped|camping)\b"
    r"(?=.{0,240}\b(?:meteor\s+shower|perseid|sky|universe|"
    r"streaks?\s+of\s+light|made\s+wishes?|one\s+with)\b)|"
    r"\b(?:meteor\s+shower|perseid|sky|universe|streaks?\s+of\s+light|"
    r"made\s+wishes?|one\s+with)\b"
    r"(?=.{0,240}\b(?:camp(?:ing)?\s+trip|camped|camping|nature|outdoors?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_NATURE_MEMORY_CONTEXT_RE = re.compile(
    r"\b(?:camp(?:ing)?\s+trip|camped|camping|meteor\s+shower|perseid|"
    r"sky|universe|nature|outdoors?)\b",
    re.IGNORECASE,
)
_CHILDREN_PREFERENCE_DIRECT_RE = re.compile(
    r"\b(?:kids?|children|child|sons?|daughters?|younger\s+kids?)\b"
    r"(?=.{0,220}\b(?:likes?|loves?|enjoys?|favorite|favourite|stoked|"
    r"excited|into)\b)"
    r"(?=.{0,260}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|campfire|marshmallows?|books?|stories|"
    r"learning|pottery|clay|painting|creative|creativity)\b)|"
    r"\b(?:they|them)\b(?=.{0,140}\b(?:were\s+)?(?:stoked|excited)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)|"
    r"\b(?:they|them)\b(?=.{0,180}\b(?:likes?|loves?|enjoys?|favorite|"
    r"favourite)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHILDREN_PREFERENCE_CONTEXT_RE = re.compile(
    r"\b(?:kids?|children|child|sons?|daughters?|they|them|dinosaurs?|exhibit|"
    r"museum|animals?|bones?|nature|outdoors?|hikes?|hiking|camping|books?|"
    r"stories|learning|pottery|clay|painting)\b",
    re.IGNORECASE,
)
_CHILDHOOD_POSSESSION_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:had|owned|used\s+to\s+have)\b(?=.{0,140}\b(?:as\s+a\s+kid|"
    r"as\s+a\s+child|from\s+my\s+childhood|when\s+i\s+was\s+(?:a\s+)?kid|"
    r"when\s+i\s+was\s+(?:a\s+)?child|childhood)\b)|"
    r"(?:as\s+a\s+kid|as\s+a\s+child|from\s+my\s+childhood|childhood)\b"
    r"(?=.{0,140}\b(?:had|owned|used\s+to\s+have|reminds?\s+me\s+of)\b)|"
    r"reminds?\s+me\s+of\b(?=.{0,160}\b(?:childhood|as\s+a\s+kid|"
    r"as\s+a\s+child)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CHILDHOOD_POSSESSION_OBJECT_RE = re.compile(
    r"\b(?:dolls?|cameras?|film\s+cameras?|toys?|books?|bikes?|bicycles?|"
    r"keepsakes?|mementos?|stuffed\s+animals?|photos?|pictures?)\b",
    re.IGNORECASE,
)
_PUBLIC_OFFICE_SERVICE_DIRECT_RE = re.compile(
    r"\b(?:running|run|ran)\s+for\s+office\b|"
    r"\bpublic\s+office\b|"
    r"\bpolitics?\b(?=.{0,180}\b(?:positive\s+changes?|better\s+future|impact)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INSPIRATION_SOURCE_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:inspired|inspires|inspiring)\s+(?:by|from)\b"
    r"(?=.{0,220}\b(?:personal\s+experiences?|self[-\s]?discovery|journey|"
    r"nature|hiking|boldness|validat(?:e|ed|ing|ion)|stories?|courage|"
    r"risks?|people|imagin(?:e|ed|ation)|ideas?|vision|sunset|world)\b)|"
    r"(?:personal\s+experiences?|self[-\s]?discovery|journey|nature|hiking|"
    r"boldness|validat(?:e|ed|ing|ion)|stories?|courage|risks?|people|"
    r"imagin(?:e|ed|ation)|ideas?|vision|sunset|world)\b"
    r"(?=.{0,160}\b(?:inspired|inspires|inspiring)\s+(?:me|my|her|him|"
    r"them|us)\b)|"
    r"(?:got|gets|getting)\s+ideas?\s+from\b"
    r"(?=.{0,160}\b(?:people|saw|seen|imagined|imagination|everywhere)\b)|"
    r"validat(?:e|ed|ing|ion)\b(?=.{0,120}\b(?:hopeful|inspired)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_INSPIRATION_SOURCE_CONTEXT_RE = re.compile(
    r"\b(?:inspired|inspires|inspiring|inspiration|motivation|motivated|"
    r"ideas?|imagination|creative|creativity|stories?|courage|risks?)\b",
    re.IGNORECASE,
)
_INSPIRATION_SOURCE_QUERY_RE = re.compile(
    r"\b(?:inspired|inspires|inspiration|motivated|motivation)\b",
    re.IGNORECASE,
)
_BUSINESS_DIRECT_JOB_LOSS_RE = re.compile(
    r"\b(?:"
    r"(?:lost\s+my\s+job|also\s+lost\s+my\s+job|lost\s+his\s+job|lost\s+her\s+job)"
    r".{0,120}\b(?:door\s+dash|banker|own\s+business|business)|"
    r"(?:door\s+dash|banker).{0,120}\b(?:lost\s+(?:my|his|her)\s+job|job\s+loss)"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_BUSINESS_DIRECT_START_REASON_RE = re.compile(
    r"\b(?:"
    r"(?:i(?:'m)?|we(?:'re)?|he(?:'s)?|she(?:'s)?|they(?:'re)?|[A-Z][a-z]{2,})\s+"
    r"(?:(?:am|are|is|was|were)\s+)?"
    r"(?:starting|started|opening|opened|launch(?:ed|ing)?)\s+"
    r"(?:(?:a|an|my|his|her|their)\s+)?(?:own\s+)?"
    r"(?:dance\s+studio|clothing\s+store|online\s+(?:clothing\s+)?store|"
    r"own\s+business|business)"
    r"(?=.{0,180}\b(?:passion(?:ate)?|love|loved|share|dream(?:ed)?)\b)|"
    r"(?:passion(?:ate)?|love|loved|blend(?:ed)?\s+(?:my\s+)?love|"
    r"fashion\s+trends|unique\s+pieces)\b"
    r"(?=.{0,180}\b(?:start(?:ed|ing)?|business|store|studio|fashion|dance)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_MILITARY_SERVICE_GOAL_DIRECT_RE = re.compile(
    r"\b(?:wanted|want|goal|goals?|reminded\s+me\s+why)\b"
    r"(?=.{0,180}\b(?:join(?:ing)?\s+the\s+military|military\s+service|"
    r"serve\s+(?:the\s+)?country|service\s+to\s+the\s+country)\b)|"
    r"\b(?:join(?:ing)?\s+the\s+military|military\s+service|"
    r"service\s+to\s+the\s+country)\b"
    r"(?=.{0,180}\b(?:wanted|want|goal|goals?|resilience|hope)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DIVERSITY_FAMILY_PRIORITY = (
    "fact",
    "chunk",
    "extraction_artifact",
    "anchor",
    "suggestion",
)
_QUERY_OBJECT_TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
_TEMPORAL_ANSWER_SUPPORT_QUERY_RE = re.compile(
    r"\b(?:when|date|time|day|week|month|year|morning|afternoon|evening|"
    r"before|after|during|first|last|previous|next|recently|yesterday|today|"
    r"tomorrow|how\s+long|how\s+often|duration|frequency)\b",
    re.IGNORECASE,
)
_MUSIC_EVENT_ATTENDANCE_QUERY_RE = re.compile(
    r"\b(?:music|concerts?|live\s+music|festivals?|shows?|performances?)\b"
    r"(?=.{0,120}\b(?:events?|attend(?:ed|s|ing)?|went|joined|participated)\b)|"
    r"\b(?:events?|attend(?:ed|s|ing)?|went|joined|participated)\b"
    r"(?=.{0,120}\b(?:music|concerts?|live\s+music|festivals?|shows?|performances?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DEGREE_COMPLETION_TEMPORAL_QUERY_RE = re.compile(
    r"\b(?:when|date|time|day|month|year)\b"
    r"(?=.{0,120}\b(?:degree|diploma|certificate|graduat(?:e|ed|ion))\b)|"
    r"\b(?:degree|diploma|certificate|graduat(?:e|ed|ion))\b"
    r"(?=.{0,120}\b(?:when|date|time|day|month|year)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOGNITION_CERTIFICATE_QUERY_RE = re.compile(
    r"\b(?:certificate|certificates|diploma|diplomas|degree|graduat(?:e|ed|ion))\b",
    re.IGNORECASE,
)
_RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE = re.compile(
    r"\b(?:image\s+caption|visual\s+query|photo|picture)\b"
    r"(?=.{0,240}\b(?:certificate|certificates|diploma|diplomas)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)|"
    r"\b(?:certificate|certificates|diploma|diplomas)\b"
    r"(?=.{0,240}\b(?:image\s+caption|visual\s+query|photo|picture)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TEMPORAL_ANSWER_SUPPORT_REASONS = frozenset(
    {
        "after-event-temporal-bridge",
        "age-birthday-bridge",
        "before-event-temporal-bridge",
        "decomposition-temporal-answer",
        "pet-acquisition-date-bridge",
        "temporal-event-detail-bridge",
    }
)
_NAMED_ACQUISITION_OBJECT_QUERY_RE = re.compile(
    r"\b[Ww]hen\s+(?:did|was)\s+"
    r"[A-Z][A-Za-z._'-]{1,39}\s+"
    r"(?:get|got|buy|bought|bring|brought|give|gave|adopt(?:ed)?)\s+"
    r"(?P<object>[A-Z][A-Za-z._'-]{1,39})\b"
)
_TEMPORAL_QUERY_OBJECT_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "did",
        "do",
        "does",
        "for",
        "had",
        "has",
        "have",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
    }
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
_PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:\s+)",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_OBJECT_ANCHOR_RE = re.compile(
    r"\b(?:adopt(?:ed|ion)?|gift(?:ed)?|named|"
    r"new\s+(?:addition|pet|pup|puppy|dog)|"
    r"stuffed\s+animal|toy\s+(?:pup|dog))\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_FRIENDSHIP_COMPANION_RE = re.compile(
    r"\b(?:(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness)"
    r".{0,260}(?:values?\s+friendship|appreciat(?:e|es|ion).{0,60}friendship|"
    r"family\s+outing|planning\s+something\s+special)|(?:values?\s+friendship|appreciat(?:e|es|ion).{0,40}friendship\s+too|always\s+been\s+there))\b",
    re.IGNORECASE | re.DOTALL,
)
_POTTERY_TYPE_PROJECT_COMPANION_RE = re.compile(
    r"\b(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness|"
    r"fulfillment|sanctuary|comfort)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE = re.compile(
    r"\bused\s+to\s+(?:go|do|play|ride|visit)\b(?=.{0,180}\b"
    r"(?:dad|father|mom|mother|parent|parents?)\b)(?=.{0,220}\b"
    r"(?:kid|child|childhood|younger)\b)|"
    r"\b(?:husband|motivated|motivate|motivation)\b(?=.{0,180}\b"
    r"(?:family|kids?|children|hiking|hike|nature|waterfall|trail))|"
    r"\b(?:family|kids?|children|hiking|hike|nature|waterfall|trail)\b"
    r"(?=.{0,180}\b(?:husband|motivated|motivate|motivation))",
    re.IGNORECASE | re.DOTALL,
)
_FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE = re.compile(
    r"\b(?:swimming|swim|hiking|hike|trail|waterfall|museum|dinosaur|"
    r"pottery|clay|painting|camping|campfire|marshmallow|park|"
    r"danc(?:e|ing|ers?)|festival)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_CONTEXT_OBJECT_RE = re.compile(
    r"\b(?:family|fam|kids?|children|husband)\b",
    re.IGNORECASE,
)
_ACTIVITY_DIRECT_PARTICIPATION_RE = re.compile(
    r"\b(?:danc(?:e|ing)|dance\s+studio)\b(?=.{0,220}\b(?:destress|"
    r"de-stress|stress\s+(?:relief|fix)|escape|go-to|"
    r"worries\s+vanish|clear\s+my\s+mind))|"
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,240}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)|"
    r"\b(?:used\s+to\s+(?:go|do|play|ride|visit)\b(?=.{0,180}\b"
    r"(?:dad|father|mom|mother|parent|parents?)\b)(?=.{0,220}\b"
    r"(?:kid|child|childhood|younger)\b)|"
    r"signed\s+up\s+for|joined|started|went|go(?:ing)?|off\s+to\s+go|"
    r"took|did|finished|made|painted|pottery\s+class|workshop|"
    r"visual\s+query:\s*painting|image\s+caption:.{0,120}\bpainting)\b"
    r"(?=.{0,240}\b(?:pottery|class|camp(?:ing|ed)?|swimm(?:ing)?|swim|"
    r"painting|painted|sunrise|sunset|lake|hiking|hike|trail|workshop|clay|"
    r"creative|kids?|family|fam|danc(?:e|ing|ers?)|festival)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_CONTEXT_RE = re.compile(
    r"\b(?:pottery|class|camp(?:ing|ed)?|swimm(?:ing)?|swim|painting|painted|"
    r"sunrise|sunset|lake|hiking|hike|trail|workshop|clay|creative|kids?|"
    r"family|fam|unplug|danc(?:e|ing|ers?)|festival)\b",
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
    r"fundraiser|tournament|baked\s+goods?|dropped\s+off|"
    r"received\s+a\s+medal|front\s+desk|kids?\s+event)\b",
    re.IGNORECASE,
)
_INVENTORY_SHELTER_FOOD_DROPOFF_SLOT_RE = re.compile(
    r"\b(?:homeless\s+shelter|shelter)\b"
    r"(?=.{0,200}\b(?:drop(?:ped)?\s+off|brought|donat(?:e|ed)|"
    r"baked?|baking|cakes?|baked\s+goods?|desserts?)\b)|"
    r"\b(?:drop(?:ped)?\s+off|brought|donat(?:e|ed)|baked?|baking|"
    r"cakes?|baked\s+goods?|desserts?)\b"
    r"(?=.{0,200}\b(?:homeless\s+shelter|shelter)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_VOLUNTEER_HELPED_PERSON_SLOT_RE = re.compile(
    r"\b(?:someone|person)\s+named\s+[A-Z][a-z]+\b|"
    r"\bmet\s+(?:this\s+)?(?:amazing\s+)?(?:woman|man|person),\s+[A-Z][a-z]+\b|"
    r"\b[Oo]ne\s+of\s+the\s+(?:shelter\s+)?residents?,\s+[A-Z][a-z]+,\s+wrote\b|"
    r"\bresidents?\s+at\s+the\s+shelter,\s+[A-Z][a-z]+,\s+wrote\b|"
    r"\b[A-Z][a-z]+,\s+a\s+resident\s+at\s+the\s+shelter\b"
    r"(?=.{0,120}\b(?:gratitude|appreciation|letter|support))",
    re.DOTALL,
)
_INVENTORY_GRATITUDE_NOTE_WRITER_SLOT_RE = re.compile(
    r"\b(?:residents?|person|someone)\b"
    r"(?=.{0,180}\b(?:wrote|written|note|letter|gratitude|appreciation|"
    r"thank(?:s|ful)?)\b)|"
    r"\b(?:wrote|written|note|letter|gratitude|appreciation|thank(?:s|ful)?)\b"
    r"(?=.{0,180}\b(?:residents?|person|someone|shelter|support)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_SHELTER_SERVICE_ACTIVITY_SLOT_RE = re.compile(
    r"\b(?:homeless\s+shelter|shelter)\b(?=.{0,180}\b"
    r"(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|"
    r"donation\s+drive|toy\s+drive|kids?\s+in\s+need|"
    r"held\s+some\s+events|service\s+events?))|"
    r"\b(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|"
    r"donation\s+drive|toy\s+drive|kids?\s+in\s+need|"
    r"held\s+some\s+events|service\s+events?)\b(?=.{0,180}\b"
    r"(?:homeless\s+shelter|shelter)\b)",
    re.IGNORECASE | re.DOTALL,
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
_INVENTORY_BOOK_READING_SLOT_RE = re.compile(
    r"\b(?:loved\s+reading\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"love\s+reading\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|book\s+i\s+read\s+last\s+year|"
    r"favorite\s+book|favourite\s+book|childhood\s+book|read\s+as\s+a\s+kid|"
    r"just\s+finished\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"finished\s+(?:reading\s+)?\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"books?\s+(?:guide|motivat(?:e|es|ed|ing)|help(?:s|ed)?"
    r"(?:\s+(?:me|him|her|them|us|you))?\s+discover|"
    r"(?:are|is)\s+a\s+huge\s+part)\b"
    r"(?=.{0,180}\b(?:journey|reading|"
    r"self[-\s]?discovery|keep\s+going|motivat(?:e|es|ed|ing))\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+(?:is|are)\s+"
    r"(?:great|good|amazing|awesome)"
    r"(?=.{0,160}\b(?:books?|novel|series|worth\s+a\s+read|"
    r"world-building|character\s+development|recommend|hooked|"
    r"(?:chat|talk)\s+about\s+them|writ(?:e|ing)\s+about))|"
    r"(?-i:[A-Z])[^\"\n]{1,80}\".{0,80}\bone\s+of\s+my\s+favorites|"
    r"book\s+collection|book\s+series\s+(?:that\s+)?(?:i\s+)?love|"
    r"fan\s+of\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?(?=.{0,120}\b(?:books?|series|"
    r"magical|fantasy|novel|reading)\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+fan(?=.{0,120}\b(?:books?|series|"
    r"magical|fantasy|novel|reading)\b)|"
    r"read(?:ing)?\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?)\b",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_READING_DIRECT_ANSWER_RE = re.compile(
    r"\b(?:"
    r"loved\s+reading\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"read\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+as\s+a\s+kid|"
    r"just\s+finished\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"finished\s+(?:reading\s+)?\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"books?\s+(?:guide|motivat(?:e|es|ed|ing)|help(?:s|ed)?"
    r"(?:\s+(?:me|him|her|them|us|you))?\s+discover|"
    r"(?:are|is)\s+a\s+huge\s+part)\b"
    r"(?=.{0,180}\b(?:journey|reading|"
    r"self[-\s]?discovery|keep\s+going|motivat(?:e|es|ed|ing))\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+(?:is|are)\s+"
    r"(?:great|good|amazing|awesome)"
    r"(?=.{0,160}\b(?:books?|novel|series|worth\s+a\s+read|"
    r"world-building|character\s+development|recommend|hooked|"
    r"(?:chat|talk)\s+about\s+them|writ(?:e|ing)\s+about))|"
    r"(?-i:[A-Z])[^\"\n]{1,80}\".{0,80}\bone\s+of\s+my\s+favorites|"
    r"book\s+i\s+read\s+last\s+year|"
    r"favorite\s+book\s+(?:is|was)|"
    r"favourite\s+book\s+(?:is|was)"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_READING_CONTEXT_RE = re.compile(
    r"\b(?:book|books|reading|read)\b",
    re.IGNORECASE,
)
_INVENTORY_CHURCH_FRIEND_ACTIVITY_SLOT_RE = re.compile(
    r"\b(?:church\s+friends?|friends?\s+from\s+church)\b(?=.{0,180}\b"
    r"(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|camping|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|refreshed|rewarding)\b)|"
    r"\b(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|camping|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|refreshed|rewarding)\b"
    r"(?=.{0,180}\b(?:church\s+friends?|friends?\s+from\s+church)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_VOLUNTEER_SLOT_RE = re.compile(
    r"\b(?:volunteer|volunteers|volunteering)\b",
    re.IGNORECASE,
)
_INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE = re.compile(
    r"\b(?:education|educational|school|schools|infrastructure|"
    r"community\s+meetings?|education\s+reform|infrastructure\s+development)\b",
    re.IGNORECASE,
)
_CAUSE_EDUCATION_SLOT_RE = re.compile(
    r"\b(?:education|educational|school|schools|students?|education\s+reform)\b",
    re.IGNORECASE,
)
_CAUSE_INFRASTRUCTURE_SLOT_RE = re.compile(
    r"\binfrastructure\b",
    re.IGNORECASE,
)
_CAUSE_EVENT_SHELTER_TOY_DRIVE_SLOT_RE = re.compile(
    r"\b(?:homeless\s+shelter|shelter)\b(?=.{0,220}\b"
    r"(?:food\s+(?:and\s+)?supplies|toy\s+drive|kids?\s+in\s+need|"
    r"give\s+out|gave\s+out|organized|events?|made\s+a\s+real\s+difference)\b)|"
    r"\b(?:toy\s+drive|kids?\s+in\s+need|food\s+(?:and\s+)?supplies|"
    r"give\s+out|gave\s+out)\b(?=.{0,220}\b(?:homeless\s+shelter|shelter|"
    r"events?|made\s+a\s+real\s+difference)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CAUSE_EVENT_FOOD_DRIVE_SLOT_RE = re.compile(
    r"\b(?:community\s+food\s+drive|food\s+drive)\b|"
    r"\bunemployment\b(?=.{0,180}\b(?:neighbors?|help\s+out|food\s+drive)\b)|"
    r"\b(?:neighbors?|help\s+out)\b(?=.{0,180}\b(?:unemployment|food\s+drive)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CAUSE_EVENT_DOMESTIC_ABUSE_SLOT_RE = re.compile(
    r"\b(?:domestic\s+(?:abuse|violence)|victims?\s+of\s+domestic\s+abuse|"
    r"local\s+organization\s+that\s+helps\s+victims)\b",
    re.IGNORECASE,
)
_INVENTORY_VETERANS_SLOT_RE = re.compile(
    r"\b(?:veterans?|military|served|service\s+members?|memorial)\b",
    re.IGNORECASE,
)
_INVENTORY_VETERANS_PETITION_SLOT_RE = re.compile(
    r"\b(?:petition|signatures?)\b(?=.{0,160}\b(?:veterans?|military)\b)|"
    r"\b(?:veterans?|military)\b(?=.{0,160}\b(?:petition|signatures?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_VETERANS_RUN_SLOT_RE = re.compile(
    r"\b(?:5k|charity\s+run|run|funds?|raise(?:d)?)\b"
    r"(?=.{0,180}\b(?:veterans?|military|families)\b)|"
    r"\b(?:veterans?|military|families)\b"
    r"(?=.{0,180}\b(?:5k|charity\s+run|run|funds?|raise(?:d)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_VETERANS_MARCH_SLOT_RE = re.compile(
    r"\b(?:march(?:ing)?|parade)\b(?=.{0,160}\b(?:veterans?|military|rights?)\b)|"
    r"\b(?:veterans?|military|rights?)\b(?=.{0,160}\b(?:march(?:ing)?|parade)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_VETERANS_HOSPITAL_SLOT_RE = re.compile(
    r"\b(?:veterans?'?\s+hospital|hospital)\b(?=.{0,160}\b(?:veterans?|military)\b)|"
    r"\b(?:veterans?|military)\b(?=.{0,160}\bhospital\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_MUSIC_EVENT_SLOT_RE = re.compile(
    r"\b(?:live\s+music|violin\s+concert|concert|festival|show|performance)\b",
    re.IGNORECASE,
)
_INVENTORY_CLASSICAL_MUSIC_PREFERENCE_SLOT_RE = re.compile(
    r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|composer)\b"
    r"(?=.{0,180}\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|"
    r"fav(?:orite)?|tunes?|songs?|music)\b)|"
    r"\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|fav(?:orite)?|into)\b"
    r"(?=.{0,180}\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|"
    r"composer|tunes?|songs?|music)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_MUSIC_LIVE_EVENT_SLOT_RE = re.compile(
    r"\blive\s+music(?:\s+event)?\b",
    re.IGNORECASE,
)
_INVENTORY_MUSIC_VIOLIN_CONCERT_SLOT_RE = re.compile(
    r"\bviolin\s+concert\b",
    re.IGNORECASE,
)
_INVENTORY_STATE_PLACE_SLOT_RE = re.compile(
    r"\b(?:florida|oregon|california|texas|new\s+york|east\s+coast|"
    r"pacific\s+northwest|northwest|coast|state|states|areas?)\b",
    re.IGNORECASE,
)
_INVENTORY_STATE_CALIFORNIA_SLOT_RE = re.compile(r"\bcalifornia\b", re.IGNORECASE)
_INVENTORY_STATE_FLORIDA_SLOT_RE = re.compile(r"\bflorida\b", re.IGNORECASE)
_INVENTORY_STATE_NEW_YORK_SLOT_RE = re.compile(r"\bnew\s+york\b", re.IGNORECASE)
_INVENTORY_STATE_OREGON_SLOT_RE = re.compile(r"\boregon\b", re.IGNORECASE)
_INVENTORY_STATE_TEXAS_SLOT_RE = re.compile(r"\btexas\b", re.IGNORECASE)
_INVENTORY_STATE_EAST_COAST_SLOT_RE = re.compile(r"\beast\s+coast\b", re.IGNORECASE)
_INVENTORY_STATE_PACIFIC_NORTHWEST_SLOT_RE = re.compile(
    r"\b(?:pacific\s+northwest|northwest)\b",
    re.IGNORECASE,
)
_INVENTORY_OUTDOOR_ACTIVITY_SLOT_RE = re.compile(
    r"\b(?:hiking|hike|mountaineering|camping|trail|mountains?|park|picnic|"
    r"waterfall)\b",
    re.IGNORECASE,
)
_INVENTORY_OUTDOOR_WATERFALL_SLOT_RE = re.compile(r"\bwaterfall\b", re.IGNORECASE)
_INVENTORY_OUTDOOR_HIKING_SLOT_RE = re.compile(r"\bhik(?:e|ing)\b", re.IGNORECASE)
_INVENTORY_OUTDOOR_MOUNTAINEERING_SLOT_RE = re.compile(
    r"\bmountaineering\b",
    re.IGNORECASE,
)
_INVENTORY_OUTDOOR_PICNIC_SLOT_RE = re.compile(r"\bpicnic\b", re.IGNORECASE)
_INVENTORY_OUTDOOR_VISUAL_GROUP_SLOT_RE = re.compile(
    r"\byou\s+and\s+(?:your\s+)?"
    r"(?:friends?|colleagues?|co-?workers?|workmates?|teammates?|team|group)\b"
    r"(?=.{0,120}\b(?:look(?:s|ing)?|seem(?:s|ed)?|great|team|group)\b)|"
    r"\b(?:friends?|colleagues?|co-?workers?|workmates?|teammates?)\b"
    r"(?=.{0,120}\blook(?:s|ing)?\s+like\s+(?:a\s+)?(?:great\s+)?"
    r"(?:team|group)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_EVENT_CHILI_COOKOFF_SLOT_RE = re.compile(
    r"\bchili\s+cook[-\s]?off\b",
    re.IGNORECASE,
)
_INVENTORY_EVENT_TOURNAMENT_SLOT_RE = re.compile(
    r"\btournament\b",
    re.IGNORECASE,
)
_INVENTORY_EVENT_FUNDRAISER_SETUP_SLOT_RE = re.compile(
    r"\b(?:getting\s+ready|preparing|planning|organizing|cover\s+basic\s+needs|"
    r"raise\s+enough)\b(?=.{0,180}\b(?:fundraiser|fundraising|shelter|homeless)\b)|"
    r"\b(?:fundraiser|fundraising|shelter|homeless)\b"
    r"(?=.{0,180}\b(?:getting\s+ready|preparing|planning|organizing|"
    r"cover\s+basic\s+needs|raise\s+enough)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_ANIMAL_ACTIVITY_FEEDING_SLOT_RE = re.compile(
    r"\b(?:feed(?:ing)?|eat(?:ing)?|fruit|strawberries|snacks?)\b"
    r"(?=.{0,180}\b(?:turtles?|pets?|animals?|reptiles?)\b)|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,180}\b(?:feed(?:ing)?|eat(?:ing)?|fruit|strawberries|snacks?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_ANIMAL_ACTIVITY_HOLDING_SLOT_RE = re.compile(
    r"\bhold(?:ing)?\b(?=.{0,180}\b(?:turtles?|pets?|animals?|reptiles?)\b)|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b(?=.{0,180}\bhold(?:ing)?\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_ANIMAL_ACTIVITY_BATH_SLOT_RE = re.compile(
    r"\b(?:bath|bathe|bathing)\b(?=.{0,180}\b(?:turtles?|pets?|animals?|reptiles?)\b)|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,180}\b(?:bath|bathe|bathing)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_ANIMAL_ACTIVITY_WALK_SLOT_RE = re.compile(
    r"\bwalk(?:s|ed|ing)?\b(?=.{0,180}\b(?:turtles?|pets?|animals?|reptiles?)\b)|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b(?=.{0,180}\bwalk(?:s|ed|ing)?\b)",
    re.IGNORECASE | re.DOTALL,
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
_TRAVEL_COUNTRY_SLOT_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"europe|european|abroad)\b",
    re.IGNORECASE,
)
_TRAVEL_PLACE_DIRECT_SLOT_RE = re.compile(
    r"(?i:\b(?:been|visit(?:ed|ing)?|went|travel(?:ed|ing)?|trip|"
    r"vacation|tour(?:ed|ing)?|planning\s+a\s+trip|off\s+to|"
    r"was\s+in|were\s+in)\b)"
    r"(?=.{0,90}\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|"
    r"(?i:east\s+coast|west\s+coast|pacific\s+northwest|"
    r"smoky\s+mountains|mountains|beach|park|city|country|"
    r"abroad|european?))\b)",
    re.DOTALL,
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
_SUPPORT_NETWORK_DIRECT_ANSWER_RE = re.compile(
    r"\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|people\s+around)\b"
    r"(?=.{0,180}\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|motivat(?:e|es|ed|ing)|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?)\b)|"
    r"\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|motivat(?:e|es|ed|ing)|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?)\b"
    r"(?=.{0,180}\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|"
    r"people\s+around)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SUPPORT_NETWORK_SOCIAL_ACTOR_RE = re.compile(
    r"\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|people\s+around|"
    r"support\s+system|support\s+network)\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_SUPPORT_ACTION_RE = re.compile(
    r"\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|motivat(?:e|es|ed|ing)|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?)\b",
    re.IGNORECASE,
)
_CONVERSATIONAL_SUPPORT_TURN_RE = re.compile(
    r"\b(?:appreciat(?:e|ed|es|ing)|friendship|always\s+been\s+there|"
    r"there\s+for\s+me|support(?:s|ed|ive)?|means?\s+a\s+lot)\b",
    re.IGNORECASE,
)
_MUSIC_ARTIST_DIRECT_ANSWER_RE = re.compile(
    r"\b(?:it\s+was|artist\s+was|band\s+was|singer\s+was|performer\s+was)\s+"
    r"[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){0,3}\b|"
    r"\b[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){0,3}\b"
    r"(?=.{0,120}\b(?:talented|voice|songs?|singer|artist|performer)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TEMPORAL_DIRECT_ANSWER_RE = re.compile(
    r"\b(?:"
    r"yesterday|tomorrow|last\s+(?:night|week|month|year|mon(?:day)?|tue(?:sday)?|"
    r"wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"next\s+(?:week|month|year|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
    r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+days?\s+ago|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+weeks?\s+ago"
    r")\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_MOVIE_SLOT_RE = re.compile(
    r"\b(?:watch(?:ing)?\s+movies?|movies?|film|films|dramas?|romcoms?|"
    r"sci[-\s]?fi|action\s+movies?)\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_MOVIE_SEEN_SLOT_RE = re.compile(
    r"\b(?i:watched|seen|saw)\s+"
    r"(?:[\"'][^\"'\n]{2,90}[\"']|[A-Z][A-Za-z0-9'’-]+"
    r"(?:\s+[A-Z][A-Za-z0-9'’-]+){0,6})(?=$|[\s,.;:!?])",
)
_COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE = re.compile(
    r"\b(?:seen|watch(?:ed|ing)?)\s+any\s+good\s+movies?\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+favorite\s+(?:game\s+or\s+)?movie\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_MOVIE_SEEN_QUERY_RE = re.compile(
    r"\b(?:movies?|films?)\b(?=.{0,120}\b(?:seen|watched|saw|both)\b)|"
    r"\b(?:seen|watched|saw|both)\b(?=.{0,120}\b(?:movies?|films?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE = re.compile(
    r"\b(?:"
    r"hang(?:ing)?\s+with\s+friends|hanging\s+friends|"
    r"express\s+myself\s+through\s+stories|good\s+time\s+with\s+people"
    r")\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_ACTIVITY_SLOT_RE = re.compile(
    r"\b(?:paint(?:ing|ed)?|camp(?:ing)?|hik(?:e|es|ing)|music|books?|"
    r"read(?:ing)?|games?|art|pottery|swim(?:ming)?|running|nature|"
    r"outdoors?)\b"
    r"(?=.{0,180}\b(?:both|common|mutual|same|similar|"
    r"also|enjoys?|enjoyed|likes?|liked|loves?|interested|hobbies?|"
    r"interests?|activities)\b)|"
    r"\b(?:both|common|mutual|same|similar|also|enjoys?|"
    r"enjoyed|likes?|liked|loves?|interested|hobbies?|interests?|activities)\b"
    r"(?=.{0,180}\b(?:paint(?:ing|ed)?|camp(?:ing)?|hik(?:e|es|ing)|"
    r"music|books?|read(?:ing)?|games?|art|pottery|swim(?:ming)?|"
    r"running|nature|outdoors?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE = re.compile(
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,220}\b(?:drawn|like|likes|love|loves|enjoys?|prefer|"
    r"unique|slow\s+pace|low[-\s]?maintenance|calming|calm|peace|joy|"
    r"companion|resilien(?:ce|t)|inspir(?:e|es|ed|ing)|strength|"
    r"perseverance|motivat(?:e|es|ed|ing|ion))\b)|"
    r"\b(?:drawn|like|likes|love|loves|enjoys?|prefer|calming|calm|"
    r"peace|joy|companion|resilien(?:ce|t)|inspir(?:e|es|ed|ing)|"
    r"strength|perseverance|motivat(?:e|es|ed|ing|ion))\b"
    r"(?=.{0,220}\b(?:turtles?|pets?|animals?|reptiles?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE = re.compile(
    r"\b(?:make\s+me\s+think\s+of\s+strength\s+and\s+perseverance|"
    r"make\s+me\s+think\s+of|"
    r"help\s+motivate\s+me|helps\s+motivate\s+me|"
    r"motivate\s+me\s+in\s+tough\s+times|"
    r"glad\s+you\s+find\s+that\s+inspiring|find\s+that\s+inspiring)\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_DESSERT_RECIPE_SLOT_RE = re.compile(
    r"\b(?:dessert\s+recipes?|recipes?|dairy[-\s]?free|coconut\s+milk|"
    r"coconut\s+cream|lactose\s+intolerant|testing\s+out\s+.*recipes?)\b",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_DESSERT_BAKING_SLOT_RE = re.compile(
    r"\b(?:bak(?:e|es|ed|ing)|cooking|chef|kitchen|cupcakes?|cakes?|"
    r"frosting)\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_DESSERT_SLOT_RE = re.compile(
    r"\b(?:desserts?|ice\s*cream|icecream|sweet\s+treats?|pastr(?:y|ies))\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_SHARED_DESSERT_BRIDGE_RE = re.compile(
    r"\b(?:both|share|shared|similar|mutual|same)\b"
    r"(?=.{0,180}\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|"
    r"cakes?|ice\s*cream|icecream|sweet\s+treats?)\b)|"
    r"\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|cakes?|"
    r"ice\s*cream|icecream|sweet\s+treats?)\b"
    r"(?=.{0,180}\b(?:both|share|shared|similar|mutual|same)\b)|"
    r"\b(?:thanks|means\s+a\s+lot)\b"
    r"(?=.{0,120}\byou\s+(?:enjoy|enjoyed|like|liked|love|loved)\b)"
    r"(?=.{0,180}\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|"
    r"cakes?|ice\s*cream|icecream|sweet\s+treats?)\b)|"
    r"\byou\s+(?:enjoy|enjoyed|like|liked|love|loved)\b"
    r"(?=.{0,120}\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|"
    r"cakes?|ice\s*cream|icecream|sweet\s+treats?)\b)"
    r"(?=.{0,180}\b(?:i|we)\s+(?:bake(?:d|s|r|ing)?|make|made|making)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_SELF_DESSERT_EVIDENCE_RE = re.compile(
    r"\b(?:i|we)\b"
    r"(?=.{0,140}\b(?:discover(?:ed)?|testing|tested|trying\s+out|"
    r"revis(?:e|ed|ing)|working\s+on|lactose\s+intolerant)\b)"
    r"(?=.{0,180}\b(?:desserts?|recipes?|cakes?|ice\s*cream|icecream|"
    r"coconut\s+milk|dairy[-\s]?free|sweet\s+treats?)\b)|"
    r"\b(?:been\s+working\s+on|testing\s+out|trying\s+out)\b"
    r"(?=.{0,180}\b(?:desserts?|recipes?|cakes?|ice\s*cream|icecream|"
    r"coconut\s+milk|dairy[-\s]?free|sweet\s+treats?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_PERSONAL_DESSERT_PREFERENCE_RE = re.compile(
    r"\b(?:favorites?|favourites?|love|loved|like|liked|need\s+to\s+try|"
    r"would\s+like|send\s+it\s+to\s+you|friend|friends?)\b"
    r"(?=.{0,180}\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|"
    r"cakes?|ice\s*cream|icecream|sweet\s+treats?|dairy[-\s]?free|"
    r"coconut\s+milk)\b)|"
    r"\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|cakes?|"
    r"ice\s*cream|icecream|sweet\s+treats?|dairy[-\s]?free|coconut\s+milk)\b"
    r"(?=.{0,180}\b(?:favorites?|favourites?|love|loved|like|liked|"
    r"need\s+to\s+try|would\s+like|send\s+it\s+to\s+you|friend|friends?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SCREENPLAY_REJECTION_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:rejection|rejected|declined|turned\s+down)\b"
    r"(?=.{0,180}\b(?:scripts?|screenplays?|production\s+company|"
    r"major\s+company|company|letter|feedback)\b)|"
    r"(?:scripts?|screenplays?|production\s+company|major\s+company|"
    r"company|letter)\b"
    r"(?=.{0,180}\b(?:rejection|rejected|declined|turned\s+down)\b)|"
    r"(?:wrote|writing|written|contributed|scripts?|screenplays?|words?)\b"
    r"(?=.{0,180}\b(?:appeared|shown|made\s+it|came\s+alive|big\s+screen)\b)|"
    r"(?:appeared|shown|made\s+it|came\s+alive|big\s+screen)\b"
    r"(?=.{0,180}\b(?:wrote|writing|written|contributed|scripts?|"
    r"screenplays?|words?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WORK_SUBMISSION_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:submit|submitted|submitting|submission)\b"
    r"(?=.{0,180}\b(?:work|project|scripts?|screenplays?|film\s+festivals?|"
    r"festivals?|contests?|competitions?|producers?|directors?)\b)|"
    r"(?:work|project|scripts?|screenplays?)\b"
    r"(?=.{0,180}\b(?:submit|submitted|submitting|submission)\b)"
    r"(?=.{0,220}\b(?:film\s+festivals?|festivals?|contests?|competitions?|"
    r"producers?|directors?)\b)|"
    r"(?:film\s+festivals?|festivals?|contests?|competitions?|producers?|"
    r"directors?)\b"
    r"(?=.{0,180}\b(?:submit|submitted|submitting|submission)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WRITING_INVENTORY_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:screenplays?|scripts?|books?|journal|online\s+blog\s+posts?|"
    r"blog\s+posts?|writing\s+projects?|stories?)\b"
    r"(?=.{0,180}\b(?:writing|wrote|started|finished|printed|made|"
    r"working|projects?|recently|post)\b)|"
    r"(?:writing|wrote|started|finished|printed|made|working)\b"
    r"(?=.{0,180}\b(?:screenplays?|scripts?|books?|journal|"
    r"online\s+blog\s+posts?|blog\s+posts?|stories?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WRITING_BLOG_SLOT_RE = re.compile(
    r"\b(?:online\s+blog\s+posts?|blog\s+posts?)\b",
    re.IGNORECASE,
)
_CREATIVE_WRITING_JOURNAL_SLOT_RE = re.compile(r"\bjournal\b", re.IGNORECASE)
_CREATIVE_WRITING_BOOK_SLOT_RE = re.compile(r"\bbooks?\b", re.IGNORECASE)
_CREATIVE_WRITING_SCREENPLAY_SLOT_RE = re.compile(
    r"\b(?:screenplays?|scripts?)\b",
    re.IGNORECASE,
)
_CREATIVE_WRITING_PROJECT_SLOT_RE = re.compile(
    r"\b(?:writing\s+projects?|stories?)\b",
    re.IGNORECASE,
)
_BOOK_SUGGESTION_DIRECT_RE = re.compile(
    r"\b(?:"
    r"(?:recommend|recommended|reccomend|reccomended|suggest|suggested)\b"
    r"(?=.{0,180}\b(?:book|series|story|read|reading|movie|watched|title)\b)|"
    r"(?:must[-\s]?see|great\s+read)\b|"
    r"(?:great\s+one|let\s+me\s+know\s+what\s+you\s+think)\b"
    r"(?=.{0,160}\b(?:finished|finish|read|book|series|one)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_SKILL_TEACHING_RECIPE_SLOT_RE = re.compile(
    r"\b(?:teach(?:ing)?|taught|show(?:ed|ing)?|help(?:ed|ing)?)\b"
    r"(?=.{0,200}\b(?:how\s+to\s+make|recipes?|cooking|desserts?|baking|"
    r"make\s+this)\b)|"
    r"\b(?:recipes?|cooking|desserts?|baking|how\s+to\s+make)\b"
    r"(?=.{0,200}\b(?:teach(?:ing)?|taught|show(?:ed|ing)?|help(?:ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SKILL_TEACHING_GAME_SLOT_RE = re.compile(
    r"\b(?:tips?|coach(?:ed|ing)?|teach(?:ing)?|taught|help(?:ed|ing)?)\b"
    r"(?=.{0,200}\b(?:improve|practice|learn|skills?|game|gaming|score|"
    r"scores?|tournament)\b)|"
    r"\b(?:improve|practice|learn|skills?|game|gaming|score|scores?|tournament)\b"
    r"(?=.{0,200}\b(?:tips?|coach(?:ed|ing)?|teach(?:ing)?|taught|"
    r"help(?:ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_GAME_WIN_COUNT_SLOT_RE = re.compile(
    r"\b(?:games?|match|team|basketball|court)\b"
    r"(?=.{0,220}\b(?:won|win|winning|victor(?:y|ies)|pulled\s+off|"
    r"scored|points?|shot|basket|tight\s+score|career)\b)|"
    r"\b(?:won|win|winning|victor(?:y|ies)|pulled\s+off|scored|points?|"
    r"shot|basket|tight\s+score)\b"
    r"(?=.{0,220}\b(?:games?|match|team|basketball|court|career)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLACE_AREA_STATE_QUERY_RE = re.compile(
    r"\b(?:states?|places?|areas?|vacation(?:ed)?|visited|traveled|travelled|"
    r"trips?|road\s+trip|cities|city|countries|country|locations?|"
    r"geographical|been\s+to|coast|beach|mountains?)\b",
    re.IGNORECASE,
)
_PLACE_AREA_STATE_VISIT_RE = re.compile(
    r"\b(?:florida|oregon|east\s+coast|pacific\s+northwest)\b"
    r"(?=.{0,180}\b(?:vacation|road\s+trip|trip|went|visited|traveled|"
    r"travelled|explored|beach\s+memory|family\s+vacation|picture\s+from)\b)|"
    r"\b(?:vacation|road\s+trip|went|visited|traveled|travelled|explored|"
    r"beach\s+memory|family\s+vacation|picture\s+from)\b"
    r"(?=.{0,180}\b(?:florida|oregon|east\s+coast|pacific\s+northwest)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLACE_AREA_STATE_FUTURE_RE = re.compile(
    r"\b(?:planning|plan|hop(?:e|ing)|want|would\s+like|going\s+to)\b"
    r"(?=.{0,120}\b(?:trip|vacation|visit|travel)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLACE_AREA_DIRECT_LOCATION_RE = re.compile(
    r"(?i:\b(?:been\s+to|visit(?:ed|ing)?|went|travel(?:ed|led|ing)?|trip|"
    r"vacation|tour(?:ed|ing)?|explored|snapped|photo|picture|"
    r"chat(?:ted)?|met)\b)"
    r"(?=.{0,140}\b(?:to|in|at|from|near|on)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b)|"
    r"\b(?:to|in|at|from|near|on)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b"
    r"(?=.{0,140}(?i:\b(?:trip|vacation|tour|visited|went|travel|"
    r"photo|picture|chat|met|snapped)\b))",
    re.DOTALL,
)
_PLACE_AREA_REALIZED_LOCATION_RE = re.compile(
    r"(?i:\b(?:been\s+to|visited|went|traveled|travelled|stayed|spent|"
    r"vacationed|toured|explored)\b)"
    r"(?=.{0,150}\b(?:to|in|at|from|through|around|near|on)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b)|"
    r"(?i:\b(?:trip|vacation|tour)\b)"
    r"(?=.{0,150}\b(?:to|in|at|from|through|around|near|on)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b)|"
    r"(?i:\b(?:snapped|took|shared|saved)\b)"
    r"(?=.{0,120}\b(?:photo|pic|picture)\b)"
    r"(?=.{0,180}\b(?:in|at|from|on)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b)|"
    r"(?i:\b(?:met|meet|chat(?:ted)?)\b)"
    r"(?=.{0,140}\bin\s+(?:the\s+)?"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b)",
    re.DOTALL,
)
_PLACE_AREA_LANDMARK_LOCATION_RE = re.compile(
    r"(?i:\b(?:been\s+to|visit(?:ed|ing)?|went|travel(?:ed|led|ing)?|trip|"
    r"vacation|tour(?:ed|ing)?|explored|snapped|photo|picture|image|"
    r"caption|visual|internship|yoga)\b)"
    r"(?=.{0,180}\b(?:on\s+top\s+of|at|near|by|on)\s+"
    r"(?i:mount|mt\.?|mountain)\s+[A-Z][A-Za-z]+"
    r"(?:\s+[A-Z][A-Za-z]+){0,2}\b)|"
    r"\b(?:on\s+top\s+of|at|near|by|on)\s+"
    r"(?i:mount|mt\.?|mountain)\s+[A-Z][A-Za-z]+"
    r"(?:\s+[A-Z][A-Za-z]+){0,2}\b"
    r"(?=.{0,180}(?i:\b(?:trip|vacation|tour|visited|went|travel|"
    r"photo|picture|image|caption|visual|internship|yoga|snapped)\b))",
    re.DOTALL,
)
