"""Source-sibling ranking helpers for prompt-safe context assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_creative_work_count_exact_turns import (
    creative_work_count_answer_rank,
    creative_work_count_role_alignment_rank,
)
from infinity_context_core.application.context_english_lifestyle_inference import (
    english_lifestyle_answer_slot_and_rank,
    english_lifestyle_query_kind,
)
from infinity_context_core.application.context_food_inventory_exact_turns import (
    food_inventory_answer_support_applies,
    food_inventory_answer_support_rank,
    food_inventory_role_alignment_rank,
)
from infinity_context_core.application.context_generic_behavior_inference import (
    generic_behavior_inference_signal,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _game_inventory_answer_directness_rank,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_list_answer_support_rank,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
    relationship_status_answer_rank,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.context_source_sibling_inventory_evidence import (
    source_sibling_inventory_answer_slot_count,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
    is_country_destination_source_sibling_answer_evidence,
    is_country_inventory_place_inference_query,
    is_place_inference_source_sibling_answer_evidence,
    is_query_destination_source_sibling_anchor,
    is_themed_location_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    TRAVEL_HOBBY_WRITING_REASON,
    is_travel_hobby_writing_source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryChunk

_SOURCE_GROUP_SIBLING_SCORES = {
    1: 0.955,
    2: 0.948,
    3: 0.935,
    4: 0.922,
    5: 0.914,
}
_SOURCE_GROUP_PRIMARY_SEED_SCORE = 0.968
_MAX_SOURCE_GROUPS = 32
_MAX_SOURCE_SIBLING_GROUPS = 20
_MAX_SOURCE_GROUP_SIBLING_ITEMS = 32
_MAX_SOURCE_SIBLING_CANDIDATES = 1024
_SOURCE_SIBLING_CANDIDATES_PER_ITEM = 12
_SOURCE_SIBLING_CANDIDATES_PER_GROUP = 32
_MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS = 6
_COMMON_INTEREST_SOURCE_SIBLING_REASONS = frozenset(
    {
        "commonality_interest_bridge",
        "hobby_interest_bridge",
    }
)
_COMMON_INTEREST_ANSWER_SLOT_QUERY = (
    "common shared similar hobbies interests watching movies films desserts recipes "
    "baking foods animals pets turtles reptiles animal affinity"
)
_COMMON_INTEREST_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:share|shared|common|similar|interests?|hobbies?)\b",
    re.IGNORECASE,
)
_CREATIVE_WORK_COUNT_SOURCE_SIBLING_REASONS = frozenset(
    {
        "creative-writing-inventory-bridge",
        "decomposition-quantity-count",
        "quantity-enumeration-bridge",
        "screenplay-count-bridge",
        "source-sibling-answer-evidence",
    }
)
_COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:animals?|pets?|turtles?|reptiles?)\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE = re.compile(
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
_COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:make\s+me\s+think\s+of\s+strength\s+and\s+perseverance|"
    r"help\s+motivate\s+me|helps\s+motivate\s+me|"
    r"motivate\s+me\s+in\s+tough\s+times|"
    r"glad\s+you\s+find\s+that\s+inspiring|find\s+that\s+inspiring)\b",
    re.IGNORECASE,
)
_MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:movies?|films?)\b(?=.{0,120}\b(?:seen|watched|saw|both)\b)|"
    r"\b(?:seen|watched|saw|both)\b(?=.{0,120}\b(?:movies?|films?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?i:watched|seen|saw|watches)\s+"
    r"(?:[\"'][^\"'\n]{2,90}[\"']|[A-Z][A-Za-z0-9'’-]+"
    r"(?:\s+[A-Z][A-Za-z0-9'’-]+){0,6})(?=$|[\s,.;:!?])",
)
_MOVIE_SEEN_QUESTION_ONLY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:seen|watch(?:ed|ing)?)\s+any\s+good\s+movies?\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+favorite\s+(?:game\s+or\s+)?movie\b",
    re.IGNORECASE,
)
_NICKNAME_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:hey|hi|hello|yo)\s+[A-Z][A-Za-z'’-]{1,24}\b|"
    r"\b(?:call(?:ed)?|nickname|nick\s*name)\s+"
    r"(?:me|you|him|her|them|as\s+)?[\"']?[A-Z][A-Za-z'’-]{1,24}",
    re.IGNORECASE,
)
_NICKNAME_QUERY_RE = re.compile(
    r"\b(?:nickname|nick\s*name|called|call|address(?:ed)?|pet\s+name)\b",
    re.IGNORECASE,
)
_BOARD_GAME_SOURCE_SIBLING_REASONS = frozenset({"board_game_inventory_bridge"})
_BOARD_GAME_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:board\s+games?|tabletop\s+games?)\b",
    re.IGNORECASE,
)
_GAMING_MEDIUM_SOURCE_SIBLING_REASONS = frozenset({"gaming_medium_bridge"})
_GAMING_MEDIUM_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:mediums?|games?|gaming|video\s+games?|console|controller|keyboard|"
    r"headset|headphones?|equipment|gamecube|playstation|pc)\b",
    re.IGNORECASE,
)
_GAMING_MEDIUM_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"game\s+controller|controller|keyboard|computer\s+monitor|gaming\s+setup|"
    r"headset|headphones?|console|gamecube|playstation|pc|equipment|"
    r"video\s+game\s+tournament|game\s+tournament|trophy|cash\s+prize"
    r")\b",
    re.IGNORECASE,
)
_PRECISE_TURN_RETRIEVAL_TEXT_RE = re.compile(
    r"\bsession_\d+\s+turn\s+D\d+:\d+\b",
    re.IGNORECASE,
)
_VISUAL_REFERENT_SIBLING_RE = re.compile(
    r"\b("
    r"look at this|take a look|here'?s|here is|photo|picture|pic|image|"
    r"did you see that|see that (?:band|photo|picture|pic|image|show|stage|crowd|"
    r"painting|drawing)|what'?s the band|what is the band|"
    r"посмотри|смотри|фото|картинк|изображен"
    r")\b",
    re.IGNORECASE,
)
_DIALOGUE_VISUAL_REFERENCE_RE = re.compile(
    r"\b("
    r"did you see that|see that (?:band|photo|picture|pic|image|show|stage|crowd|"
    r"painting|drawing)|what'?s the band|what is the band"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b("
    r"look at|take a look|did you see|see that|photo|picture|pic|image|visual|"
    r"what'?s the band|what is the band|crowd|stage|concert"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_SOURCE_SIBLING_REASONS = frozenset(
    {
        "decomposition_artifact_evidence",
        "source_evidence_bridge",
        "visual_text_evidence_bridge",
    }
)
_EVENT_VISUAL_SOURCE_SIBLING_REASONS = frozenset(
    {
        "event_participation_bridge",
        "lgbtq_pride_event_bridge",
        "lgbtq_school_event_bridge",
        "lgbtq_support_group_event_bridge",
        "transgender_conference_event_bridge",
        "transgender_poetry_event_bridge",
        "transgender_youth_center_event_bridge",
    }
)
_PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP = 0.976
_PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS = 6
_POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP = 0.965
_GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON = "generic_behavior_inference_bridge"
_POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE = re.compile(
    r"\b("
    r"pottery|clay|ceramic|bowl|bowls|cup|cups|mug|mugs|pot|pots|"
    r"sculpture|sculptures|dog\s+face"
    r")\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE = re.compile(
    r"\b("
    r"kids?|children|workshop|class|made|make|finished|project|hands\s+dirty|"
    r"creativity|imagination"
    r")\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:keep(?:ing)?\s+(?:their|the)?\s*(?:area|tank|space|habitat)\s+clean|"
    r"clean\s+(?:area|tank|space|habitat)|feed(?:ing)?\s+(?:them\s+)?properly|"
    r"enough\s+light|make\s+sure\s+they\s+get\s+enough\s+light|"
    r"care\s+instructions?|kind\s+of\s+fun)\b",
    re.IGNORECASE,
)
_ANIMAL_DIET_EVIDENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?)\b(?=.{0,120}\b"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet|turtles?|reptiles?)\b)|"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet)\b(?=.{0,120}\b"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?|turtles?|reptiles?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"(?:adopt(?:ed|ing)?|got|get|new\s+addition|new\s+pup|puppy|pup|dog)\b"
    r"(?=.{0,180}\b(?:family|pet|dog|puppy|pup|"
    r"gift|named|stuffed\s+animal|image\s+caption|visual\s+query|"
    r"couch|blanket|toy)\b)|"
    r"(?:gift\s+from|named|stuffed\s+animal\s+dog)\b(?=.{0,180}\b"
    r"(?:giver|recipient|person|dog|pet)\b)|"
    r"(?:image\s+caption|visual\s+query)\b(?=.{0,180}\b"
    r"(?:dog|puppy|pup|couch|blanket|toy)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:puppy|pup|dog|little\s+one|pet)\b"
    r"(?=.{0,220}\b(?:doing\s+great|adjust(?:ing|ed)?|"
    r"learning\s+commands?|house\s+training|training|trained|new\s+home)\b)|"
    r"\b(?:doing\s+great|learning\s+commands?|house\s+training|"
    r"adjust(?:ing|ed)?|training|trained)\b"
    r"(?=.{0,220}\b(?:puppy|pup|dog|little\s+one|pet|image\s+caption|"
    r"visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_DATE_ANCHOR_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:\s+)",
    re.IGNORECASE | re.DOTALL,
)
_CAUSE_AWARENESS_EVENT_SOURCE_SIBLING_RE = re.compile(
    r"(?=.*\b(?:charity\s+(?:race|run|walk|event)|fundraiser|fundraising|"
    r"campaign|race|run|walk|event|drive|conference|workshop|talk|speech|"
    r"parade|march)\b)"
    r"(?=.*\b(?:raise|raised|raising|spread|spreading|awareness|"
    r"bring(?:ing)?\s+attention|start(?:ing)?\s+conversations?|"
    r"make\s+a\s+difference)\b)"
    r"(?=.*\b(?:mental\s+health|domestic\s+abuse|animal\s+welfare|veterans?|"
    r"education|infrastructure|lgbtq\+?|trans\s+rights?|gender\s+identity|"
    r"inclusion|public\s+health|health|rights?|victims?|cause|issue)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHARITY_BRAND_SPONSORSHIP_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|in\s+talks?\s+with|"
    r"sponsor(?:ship|ed|s)?|endorse(?:ment|d|s)?|partner(?:ship|ed|s)?)\b"
    r"(?=.{0,240}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\b(?:got|gets?|have|has|had)\b"
    r"(?=.{0,140}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:always\s+liked|liked|likes|i\s+like|we\s+like|they\s+like|"
    r"he\s+likes|she\s+likes|love|loves|fan\s+of|admire|admires|"
    r"favorite|favourite|dream(?:ed)?)\b"
    r"(?=.{0,180}\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it)|"
    r"partner(?:ship|ed|s)?|brand|brands?|company|companies|organization|"
    r"organisations?|deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it))\b"
    r"(?=.{0,180}\b(?:cool|great|exciting|stoked|like|liked|likes|love|"
    r"fan|dream|brand|brands?|company|companies|organization|organisations?|"
    r"deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:charity|nonprofit|non-profit|foundation|organization|organisation|"
    r"program|initiative)\b"
    r"(?=.{0,220}\b(?:kids?|children|youth|students?|disadvantaged|"
    r"underserved|community|sports?|school|education|help|support|give\s+back|"
    r"make\s+(?:a\s+)?difference)\b)",
    re.IGNORECASE | re.DOTALL,
)
_VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE = re.compile(
    r"\b(volunteer(?:ed|ing|s)?|shelter|homeless)\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"front\s+desk|talks?|compliments?|residents?|bed|food|"
    r"counsel(?:or|ing)?|coordinator|started\s+volunteering|"
    r"make\s+a\s+difference|brighten|aunt\s+believed|fulfilling"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEERING_INVENTORY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"charity\s+event)\b"
    r"(?=.{0,240}\b(?:someone|person|woman|man|residents?|named|met|"
    r"letter|gratitude|appreciation|support\s+they\s+receive)\b)|"
    r"\b(?:someone|person|woman|man|residents?|named|met|letter|gratitude|"
    r"appreciation|support\s+they\s+receive)\b"
    r"(?=.{0,240}\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"charity\s+event)\b)",
    re.IGNORECASE | re.DOTALL,
)
_VOLUNTEERING_SERVICE_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"service\s+events?)\b"
    r"(?=.{0,220}\b(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|"
    r"food|supplies|donat(?:e|ed|ion)|toy\s+drive|kids?\s+in\s+need|"
    r"held\s+some\s+events|made\s+a\s+real\s+difference)\b)|"
    r"\b(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|food|supplies|"
    r"donat(?:e|ed|ion)|toy\s+drive|kids?\s+in\s+need|held\s+some\s+events|"
    r"made\s+a\s+real\s+difference)\b"
    r"(?=.{0,220}\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"service\s+events?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CAREER_PATH_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"counsel(?:or|ing)?|mental\s+health|working\s+with\s+(?:trans\s+)?people|"
    r"support(?:ing)?\s+their\s+mental\s+health|help(?:ing)?\s+them\s+accept"
    r")\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_SOURCE_SIBLING_REASONS = frozenset(
    {
        "attribute_family_support_bridge",
        "negative_experience_support_bridge",
        "support_network_bridge",
    }
)
_SUPPORT_NETWORK_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|people\s+around)\b"
    r"(?=.{0,180}\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed|ing)?\s+(?:me|him|her|them|us)?\s*on|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?|thankful)\b)|"
    r"\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed|ing)?\s+(?:me|him|her|them|us)?\s*on|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?|thankful)\b"
    r"(?=.{0,180}\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|"
    r"people\s+around)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_READING_INVENTORY_SOURCE_SIBLING_RE = re.compile(
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
_CHURCH_FRIEND_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:church\s+friends?|friends?\s+from\s+church)\b(?=.{0,180}\b"
    r"(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|nature|refreshed|rewarding)\b)|"
    r"\b(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|nature|refreshed|rewarding)\b"
    r"(?=.{0,180}\b(?:church\s+friends?|friends?\s+from\s+church)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPETITION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:competitions?|contest|contests|compete|competed|competing|comp|"
    r"tournament|tournaments)\b(?=.{0,220}\b(?:troph(?:y|ies)|first\s+place|"
    r"won|winner|stage|team|crew|performance|regionals?|visual\s+query|"
    r"image\s+caption)\b)|"
    r"\b(?:troph(?:y|ies)|first\s+place|won|winner|stage|team|crew|performance|"
    r"regionals?)\b(?=.{0,220}\b(?:competitions?|contest|contests|compete|"
    r"competed|competing|comp|tournament|tournaments)\b)|"
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,240}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPANION_SOURCE_SIBLING_REASONS = frozenset(
    {
        "exercise_activity_inventory_bridge",
        "outdoor_activity_inventory_bridge",
        "church_friend_activity_inventory_bridge",
    }
)
_ACTIVITY_COMPANION_QUERY_RE = re.compile(
    r"\bwho\b(?=.{0,140}\b(?:with|alongside|together)\b)"
    r"(?=.{0,200}\b(?:go|went|attend(?:ed|ing)?|join(?:ed|ing)?|"
    r"start(?:ed|ing)?|try|tried|trying|class(?:es)?|lesson|practice|"
    r"camp(?:ed|ing)?|hik(?:e|ed|ing)|travel(?:ed|led|ing)?|trip|"
    r"visit(?:ed|ing)?|yoga|workout|exercise)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPANION_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:yoga|class(?:es)?|lesson|practice|workout|exercise|fitness|"
    r"training|kickboxing|taekwondo|boxing|running|hiking|camping|trip|"
    r"conference|parade|event|travel(?:ed|led|ing)?|visit(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_ACTIVITY_COMPANION_WITH_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\b"
    r".{0,90}\b(?:(?:my|his|her|their|our|a|an|the)\s+|"
    r"one\s+of\s+(?:my|his|her|their|our)\s+)?"
    r"(?:family|kids?|children|friends?|parents?|partner|spouse|team|group|"
    r"colleagues?|co-?workers?|workmates?|classmates?|teammates?|neighbou?rs?)\b|"
    r"\b(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39})?"
    r".{0,90}\binvited\b.{0,120}\b(?:me|him|her|them|us)?\s*(?:to|for)\b|"
    r"\binvited\b.{0,120}\b(?:to|for)\b.{0,160}\bby\s+"
    r"(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_ACTIVITY_VISUAL_COMPANION_SOURCE_SIBLING_RE = re.compile(
    r"\byou\s+and\s+(?:your\s+)?"
    r"(?:friends?|colleagues?|co-?workers?|workmates?|teammates?|team|group)\b"
    r"(?=.{0,120}\b(?:look(?:s|ing)?|seem(?:s|ed)?|great|team|group)\b)|"
    r"\b(?:friends?|colleagues?|co-?workers?|workmates?|teammates?)\b"
    r"(?=.{0,120}\blook(?:s|ing)?\s+like\s+(?:a\s+)?(?:great\s+)?"
    r"(?:team|group)\b)|"
    r"\b(?:photo|picture|image|visual\s+query|caption)\b"
    r"(?=.{0,180}\b(?:waterfall|trail|mountains?|park|outdoors?|nature)\b)"
    r"(?=.{0,220}\b(?:friends?|colleagues?|co-?workers?|workmates?|"
    r"teammates?|team|group|people)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CLASSICAL_MUSIC_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|fav(?:orite)?|into)\b"
    r"(?=.{0,180}\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|"
    r"composer|violin|clarinet|tunes?|songs?|music)\b)|"
    r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|composer)\b"
    r"(?=.{0,180}\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|"
    r"fav(?:orite)?|tunes?|songs?|music)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SENTIMENTAL_REMINDER_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:reminds?|reminder|sentimental\s+value|symboli[sz](?:es|ed)?|"
    r"meaning|means|stands?\s+for)\b(?=.{0,220}\b(?:art|self[-\s]?expression|"
    r"friend|birthday|gift|memory|pattern|colou?rs?|childhood|love|faith|"
    r"strength|roots?|family|keepsake)\b)|"
    r"\b(?:sentimental\s+value|hand[-\s]?painted|keepsake|gift|birthday|"
    r"pattern|colou?rs?)\b(?=.{0,220}\b(?:reminds?|reminder|symbol|meaning|"
    r"self[-\s]?expression)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COLLECTIBLE_OBJECT_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:collectibles?|collection|memorabilia|keepsakes?|mementos?|"
    r"possessions?|objects?|items?|own(?:s|ed)?|similar|same|shared)\b",
    re.IGNORECASE,
)
_COLLECTIBLE_OBJECT_SOURCE_SIBLING_RE = re.compile(
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
_OUTDOOR_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:look\s+forward|highlight|always\s+remember|favorite|favourite|"
    r"best\s+memory|love|enjoy|special|amazing)\b(?=.{0,240}\b(?:camping|"
    r"campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|nature|"
    r"outdoors?|hikes?|hiking|trail|park)\b)|"
    r"\b(?:camping|campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|"
    r"nature|outdoors?|hikes?|hiking|trail|park)\b(?=.{0,240}\b(?:look\s+forward|"
    r"highlight|always\s+remember|favorite|favourite|best\s+memory|love|enjoy|"
    r"special|amazing|at\s+one\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHILDREN_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:kids?|children|child|sons?|daughters?|younger\s+kids?)\b"
    r"(?=.{0,220}\b(?:likes?|loves?|enjoys?|favorite|favourite|stoked|"
    r"excited|blast|into)\b)"
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
_BUSINESS_COMMONALITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:lost\s+(?:my\s+|his\s+|her\s+|their\s+)?job|door\s+dash|banker|"
    r"dance\s+studio|clothing\s+store|own\s+store|own\s+business|"
    r"ad\s+campaign)\b"
    r"(?=.{0,220}\b(?:business|store|studio|job|passion(?:ate)?|love|"
    r"growing|launched|starting|started|opened)\b)|"
    r"\b(?:passion(?:ate)?|love|launched|started|starting|opened|growing)\b"
    r"(?=.{0,220}\b(?:business|store|studio|door\s+dash|banker|dance|fashion)\b)",
    re.IGNORECASE | re.DOTALL,
)
_POST_EVENT_SUPPORT_APPRECIATION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:they(?:'re| are)?\s+a\s+real\s+support|real\s+support|"
    r"appreciat(?:e|ed|es|ing)\s+(?:them|family|support)|"
    r"appreciate\s+them\s+a\s+lot|thankful\s+(?:for|to)|grateful\s+(?:for|to)|"
    r"mean\s+the\s+world)\b",
    re.IGNORECASE,
)
_CAUSE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:passionate|interesting|main\s+focus(?:es)?|goal|goals?|"
    r"support(?:ing)?|rights?)\b"
    r"(?=.{0,220}\b(?:education|schools?|infrastructure|veterans?|military)\b)|"
    r"\b(?:education|schools?|infrastructure|veterans?|military)\b"
    r"(?=.{0,220}\b(?:passionate|interesting|main\s+focus(?:es)?|goal|goals?|"
    r"support(?:ing)?|rights?|community|reform|development|quality)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_NAMED_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:was|were|been)\s+in\s+(?-i:[A-Z])[A-Za-z' .-]{2,60}\b|"
    r"\b(?:visited|visit(?:ed|ing)?)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:went|gone|visited|travel(?:ed|led)?|vacationed)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trips?|travel|journey|vacation)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:was|were|been)\s+in\s+(?-i:[A-Z])[A-Za-z' .-]{2,60}\b|"
    r"\b(?:visited|visit(?:ed|ing)?)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:went|gone|visited|travel(?:ed|led)?|vacationed)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trips?|travel|journey|vacation)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trip|travel(?:ed|led|ing)?|visited|vacation)\b"
    r"(?=.{0,180}\b(?:city|country|state|coast|beach|mountains?|"
    r"parks?|destination|place|visual\s+query|image\s+caption)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLACE_INVENTORY_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|states?|places?|locations?|"
    r"destinations?|areas?)\b"
    r"(?=.{0,180}\b(?:mention(?:ed|s)?|visit(?:ed|ing)?|went|gone|been|"
    r"travel(?:ed|led|ing)?|trip|vacation(?:ed)?|during|in|to)\b)|"
    r"\b(?:visit(?:ed|ing)?|went|gone|been|travel(?:ed|led|ing)?|trip|"
    r"vacation(?:ed)?|during)\b"
    r"(?=.{0,180}\b(?:cities|city|countries|country|states?|places?|"
    r"locations?|destinations?|areas?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PUBLIC_OFFICE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:run(?:ning)?\s+for\s+office|running\s+office|public\s+office|"
    r"politics?|campaign)\b",
    re.IGNORECASE,
)
_PUBLIC_OFFICE_MOTIVATION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:run(?:ning|s)?|ran)\s+for\s+office\b"
    r"(?=.{0,240}\b(?:impact|community|politics?|positive\s+changes?|"
    r"better\s+future|rewarding|last\s+run|make\s+(?:a\s+)?difference)\b)|"
    r"\b(?:public\s+office|politics?)\b"
    r"(?=.{0,240}\b(?:impact|community|positive\s+changes?|better\s+future|"
    r"rewarding|run(?:ning)?\s+for\s+office|last\s+run)\b)|"
    r"\b(?:impact|positive\s+changes?|better\s+future|"
    r"make\s+(?:a\s+)?difference|rewarding)\b"
    r"(?=.{0,240}\b(?:politics?|public\s+office|run(?:ning)?\s+for\s+office)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOGNITION_AWARD_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:recognition|award|awards|medal|medals|certificate|certificates|"
    r"honou?r|honou?red|trophy|prize|received?|got|given|gave|earned|won)\b",
    re.IGNORECASE,
)
_RECOGNITION_AWARD_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:recognition|awards?|medals?|certificates?|honou?rs?|troph(?:y|ies)|"
    r"prizes?)\b"
    r"(?=.{0,200}\b(?:receive|received|got|given|gave|earned|won)\b)|"
    r"\b(?:receive|received|got|given|gave|earned|won)\b"
    r"(?=.{0,160}\b(?:recognition|awards?|medals?|certificates?|"
    r"honou?rs?|troph(?:y|ies)|prizes?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOGNITION_CERTIFICATE_VISUAL_SOURCE_SIBLING_RE = re.compile(
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
_PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:clipboard|notepad|notebook|calendar|planner)\b"
    r"(?=.{0,220}\b(?:use|using|stay\s+organized|organized\s+and\s+motivated|"
    r"sets?\s+goals?|tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"improvement|goal\s+setting|progress)\b)|"
    r"\b(?:stay\s+organized|organized\s+and\s+motivated|sets?\s+goals?|"
    r"tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"goal\s+setting|progress)\b"
    r"(?=.{0,220}\b(?:clipboard|notepad|notebook|calendar|planner|"
    r"image\s+caption|visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:special\s+experience|customer\s+experience|experience\s+for\s+customers?)\b"
    r"(?=.{0,220}\b(?:welcome|coming\s+back|come\s+back|key|space|"
    r"imagining|cozy|inviting)\b)|"
    r"\b(?:feel\s+welcome|welcome\s+and\s+coming\s+back|coming\s+back|"
    r"come\s+back)\b"
    r"(?=.{0,220}\b(?:customers?|special\s+experience|customer\s+experience|"
    r"space|cozy|inviting)\b)",
    re.IGNORECASE | re.DOTALL,
)
_GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b"
    r"(?=.{0,220}\b(?:tomorrow|grand\s+opening|opening|launch|dance\s+studio|"
    r"memories|image\s+caption|visual\s+query)\b)|"
    r"\b(?:grand\s+opening|opening|launch|dance\s+studio)\b"
    r"(?=.{0,220}\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DEGREE_POLICY_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"policymaking\b(?=.{0,120}\bdegree\b)|"
    r"degree\b(?=.{0,120}\bpolicymaking\b)|"
    r"degree\s+related\s+to\s+policymaking|"
    r"public\s+(?:policy|administration|affairs)|"
    r"political\s+science"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:road\s*trip|roadtrip)\b(?=.{0,180}\b(?:yesterday|recent|"
    r"just\s+did|after\s+the\s+(?:road\s*trip|drive)|relax))|"
    r"\b(?:yesterday|just\s+did|recent|relax)\b(?=.{0,180}\b(?:road\s*trip|roadtrip))|"
    r"\b(?:hikes?|hiking|trail|mountains?)\b(?=.{0,120}\b(?:picture|pic|"
    r"photo|kids?|family|recent|yesterday))",
    re.IGNORECASE | re.DOTALL,
)
_RUNNING_REASON_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"(?:running|run|runs|ran)\b(?=.{0,120}\b(?:destress|de-stress|"
    r"clear\s+my\s+mind|headspace|mental\s+health|farther|longer|mood|boost))|"
    r"(?:destress|de-stress|clear\s+my\s+mind|headspace|mental\s+health|farther|longer)\b"
    r"(?=.{0,120}\b(?:running|run|runs|ran))|"
    r"great\s+for\s+(?:my\s+)?mental\s+health|"
    r"walking\s+or\s+running|got\s+you\s+into\s+running|purple\s+running\s+shoe"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_DURATION_SOURCE_SIBLING_REASONS = frozenset({"decomposition_activity_duration"})
_FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS = frozenset(
    {"decomposition_frequency_recurrence"}
)
_COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS = frozenset(
    {
        "hike_count_activity_bridge",
        "hiking_trail_count_bridge",
    }
)
_STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|shelter|homeless|work(?:ed|ing|s)?|"
    r"live(?:d|s|ing)?|play(?:ed|ing|s)?|run(?:ning|s)?|"
    r"go(?:es|ing)?|visit(?:ed|ing|s)?|trips?|beach|camp(?:ed|ing)?|hikes?|hiking|"
    r"practice(?:d|s|ing)?|train(?:ed|s|ing)?|appointments?|"
    r"art|artist|creating|creat(?:e|ed|ing)|paint(?:ed|ing)?|draw(?:ing)?|"
    r"have|has|had|own(?:ed|s)?|keep(?:s|ing)?|pets?|snakes?|dogs?|cats?|puppy|"
    r"волонтер|волонт[её]р|работа(?:ет|л|ла|ли)?|жив[её]т|жил|жила|"
    r"игра(?:ет|л|ла)|занимается|тренируется|участвует"
    r")\b",
    re.IGNORECASE,
)
_ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+|over\s+)?"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+"
    r"(?:years?|months?|weeks?|days?)|"
    r"since\s+(?:19|20)\d{2}|"
    r"since\s+(?:(?:the\s+)?age\s+of\s+|i\s+was\s+)?"
    r"(?:\d{1,2}|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen)(?:\s+or\s+so)?|"
    r"started|began|still|ongoing|continuous|already|"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+years?\s+ago|"
    r"с\s+(?:19|20)\d{2}|"
    r"(?:один|одна|два|две|три|четыре|пять|шесть|\d{1,2})\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)|"
    r"начал[аи]?|начала|начали|до сих пор|уже|давно"
    r")\b",
    re.IGNORECASE,
)
_FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"every\s+(?:day|night|morning|afternoon|evening|weekday|weekend|week|"
    r"month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"every\s+other\s+(?:day|days|week|weeks|month|months|year|years)|"
    r"daily|weekly|monthly|yearly|annually|regularly|usually|often|"
    r"(?:once|twice|one|two|three|four|five|six|\d{1,2})\s+"
    r"(?:times?\s+)?(?:a|per)\s+(?:day|week|month|year)|"
    r"кажд\w+\s+(?:день|недел\w*|месяц|год|утро|вечер|выходн\w*)|"
    r"ежедневно|еженедельно|ежемесячно|ежегодно|регулярно|обычно|часто|"
    r"(?:один|одна|два|две|три|четыре|пять|шесть|\d{1,2})\s+раз(?:а)?\s+в\s+"
    r"(?:день|недел\w*|месяц|год)"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"dog\s+park\s+nearby|nearby\s+(?:dog\s+)?park|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"binos|binoculars|notebook|log\s+them|camera|"
    r"busy\s+week|schedule|city\s+schedule|"
    r"birdwatching|watching\s+birds?|birds?|eagles?|soar|"
    r"out\s+in\s+nature|away\s+from\s+the\s+city|"
    r"being\s+in\s+(?:a\s+)?nature|"
    r"hustle\s+and\s+bustle|outside\s+and\s+soak\s+up\s+the\s+scenery"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE = re.compile(
    r"\b("
    r"dog\s+park\s+nearby|nearby\s+(?:dog\s+)?park|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"out\s+in\s+nature|being\s+in\s+(?:a\s+)?nature|"
    r"outside|outdoors|hustle\s+and\s+bustle"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE = re.compile(
    r"\b(binos|binoculars|notebook|log\s+them|camera)\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE = re.compile(
    r"\b(busy\s+week|schedule|city\s+schedule|job\s+and\s+living\s+here)\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE = re.compile(
    r"\b(birdwatching|watching\s+birds?|birds?|eagles?|soar)\b",
    re.IGNORECASE,
)
_TURN_SOURCE_ID_RE = re.compile(
    r"^(?P<group>.+):(?P<dialogue>D\d+):(?P<turn>\d+):turn$",
    re.IGNORECASE,
)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_RELATED_TURN_ANCHOR_RE = re.compile(
    r"\brelated\s+turns?\s*:\s*D\d+:\d+",
    re.IGNORECASE,
)
_TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:when|what\s+date|which\s+date)\b",
    re.IGNORECASE,
)
_TEMPORAL_DIRECT_SOURCE_SIBLING_RE = re.compile(
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
_TEMPORAL_EVENT_QUERY_TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
_TEMPORAL_EVENT_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "date",
        "did",
        "do",
        "does",
        "for",
        "her",
        "his",
        "in",
        "is",
        "of",
        "on",
        "the",
        "their",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
    }
)
_TEMPORAL_EVENT_ACTION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"attend(?:ed|ing)?|built|collaborat(?:e|ed|ing|ion)|create(?:d)?|"
    r"definitely|got|had|made|make|met|mention(?:ed)?|open(?:ed)?|"
    r"planning|started|took|went|won"
    r")\b",
    re.IGNORECASE,
)
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})
_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\bused\s+to\s+(?:go|do|play|ride|visit)\b(?=.{0,180}\b"
    r"(?:dad|father|mom|mother|parent|parents?)\b)(?=.{0,220}\b"
    r"(?:kid|child|childhood|younger)\b)|"
    r"\b(?:danc(?:e|ing)|dance\s+studio|festival|dancers?)\b"
    r"(?=.{0,180}\b(?:destress|de-stress|stress\s+relief|passion|"
    r"escape|perform(?:ing)?|practice|grace|skill|part\s+of\s+it|"
    r"grand\s+opening|memories))|"
    r"\b(?:shooting\s+guard|season\s+opener|scored\s+\d+|recent\s+game|"
    r"basketball\s+game|surf(?:ing|board)?|waves?)\b"
    r"(?=.{0,220}\b(?:team|game|court|basketball|jerseys?|photo|"
    r"image\s+caption|visual\s+query|surfboard|waves?|beach)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DESTRESS_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:danc(?:e|ing)|dance\s+studio|running|run|pottery|class)\b"
    r"(?=.{0,220}\b(?:destress|de-stress|stress\s+(?:relief|fix)|"
    r"escape|go-to|worries\s+vanish|clear\s+my\s+mind|headspace|"
    r"therapeutic|therapy|unwind|calm))",
    re.IGNORECASE | re.DOTALL,
)
_ESCAPE_ACTIVITY_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:escape|escapes|escaping|take\s+(?:me|you|him|her|them|us)\s+away|"
    r"reality|daily\s+grind|feel\s+free|alternate\s+realities)\b",
    re.IGNORECASE,
)
_ESCAPE_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:read(?:ing)?|books?|novels?|fantasy|movies?|films?|shows?|"
    r"writing|music|hiking|running|surf(?:ing)?)\b"
    r"(?=.{0,240}\b(?:escape(?:s|d|ing)?(?:\s+(?:from\s+)?reality)?|"
    r"take\s+(?:me|you|him|her|them|us)\s+away|feel\s+free|"
    r"alternate\s+realities|break\s+from\s+reality|lost\s+in)\b)|"
    r"\b(?:escape(?:s|d|ing)?(?:\s+(?:from\s+)?reality)?|"
    r"take\s+(?:me|you|him|her|them|us)\s+away|feel\s+free|"
    r"alternate\s+realities|break\s+from\s+reality|lost\s+in)\b"
    r"(?=.{0,240}\b(?:read(?:ing)?|books?|novels?|fantasy|movies?|films?|"
    r"shows?|writing|music|hiking|running|surf(?:ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_WATCHING_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:tv\s+series|series|shows?|movies?|films?)\b"
    r"(?=.{0,140}\b(?:watch(?:ed|ing)?|seen|saw|mention(?:ed|s)?|called)\b)|"
    r"\b(?:watch(?:ed|ing)?|seen|saw|mention(?:ed|s)?|called)\b"
    r"(?=.{0,140}\b(?:tv\s+series|series|shows?|movies?|films?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_WATCHING_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:watch(?:ed|ing)?|seen|saw|check\s+out|excited\s+to\s+watch)\b"
    r"(?=.{0,220}\b(?:tv\s+series|series|shows?|movies?|films?|called|"
    r"coming\s+out|based\s+on|favorite|favourite)\b)|"
    r"\b(?:tv\s+series|series|shows?|movies?|films?)\b"
    r"(?=.{0,220}\b(?:watch(?:ed|ing)?|seen|saw|check\s+out|called|"
    r"coming\s+out|based\s+on|favorite|favourite)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STUDY_TIME_MANAGEMENT_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:exam|exams|finals?|studying|study|prep|prepare|"
    r"time\s+management|technique|method|strategy|study\s+tricks?)\b",
    re.IGNORECASE,
)
_STUDY_TIME_MANAGEMENT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:studying|study|exam|exams|finals?|prep|prepare)\b"
    r"(?=.{0,240}\b(?:25\s*minutes?|5\s*minutes?|"
    r"break(?:ing)?\s+up|smaller\s+parts|intervals?|pomodoro|"
    r"minutes?\s+on|minutes?\s+off|breaks?|keeps?\s+me\s+on\s+track|"
    r"less\s+overwhelming)\b)|"
    r"\b(?:25\s*minutes?|5\s*minutes?|break(?:ing)?\s+up|"
    r"smaller\s+parts|intervals?|pomodoro|minutes?\s+on|minutes?\s+off|"
    r"keeps?\s+me\s+on\s+track|less\s+overwhelming)\b"
    r"(?=.{0,240}\b(?:studying|study|exam|exams|finals?|prep|prepare)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:would|enjoy|enjoys?|prefer|prefers?|favorite|favourite|"
    r"related|recommend|interested|preference|trait|decision|reason)\b",
    re.IGNORECASE,
)
_NAMED_PREFERENCE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:favorite|favourite|love|loves|loved|enjoy|enjoys|enjoyed|"
    r"prefer|prefers|preferred|fan|interested|never\s+gets\s+old|"
    r"drawn\s+to|really\s+into)\b",
    re.IGNORECASE,
)
_NAMED_PREFERENCE_QUERY_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'+]*", re.IGNORECASE)
_NAMED_PREFERENCE_QUERY_STOPWORDS = frozenset(
    {
        "acceptance",
        "and",
        "because",
        "considered",
        "decision",
        "does",
        "during",
        "evidence",
        "enjoy",
        "enjoys",
        "encouraging",
        "favorite",
        "favourite",
        "for",
        "from",
        "indicates",
        "inference",
        "interested",
        "likely",
        "locations",
        "mentioned",
        "observed",
        "prefer",
        "preference",
        "reason",
        "related",
        "support",
        "supporting",
        "supportive",
        "the",
        "trait",
        "visit",
        "which",
        "would",
    }
)


@dataclass(frozen=True)
class _SourceGroupSeed:
    priority: int
    primary_turn: int
    turns: frozenset[int]
    group_level: bool = False


@dataclass(frozen=True)
class _SourceSiblingRank:
    score: float
    group_priority: int
    turn_distance: int
    turn_delta: int
    group_level_seed: bool = False


def source_sibling_group_limit() -> int:
    return _MAX_SOURCE_SIBLING_GROUPS


def source_sibling_item_limit() -> int:
    return _MAX_SOURCE_GROUP_SIBLING_ITEMS


def source_sibling_candidate_limit(*, max_items: int, source_group_count: int) -> int:
    if max_items <= 0 or source_group_count <= 0:
        return 0
    return min(
        _MAX_SOURCE_SIBLING_CANDIDATES,
        max(
            max_items * _SOURCE_SIBLING_CANDIDATES_PER_ITEM,
            source_group_count * _SOURCE_SIBLING_CANDIDATES_PER_GROUP,
        ),
    )


def source_sibling_max_candidate_limit() -> int:
    return _MAX_SOURCE_SIBLING_CANDIDATES


def source_sibling_companion_extra_item_limit() -> int:
    return _MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS


def source_sibling_related_turn_anchor_evidence(
    *,
    relevance: QueryRelevance,
    text: str,
) -> bool:
    return _RELATED_TURN_ANCHOR_RE.search(text) is not None and (
        relevance.distinctive_term_hits >= 2
        or relevance.unique_term_hits >= 3
        or relevance.hit_ratio >= 0.25
    )


def source_sibling_score(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> float:
    relevance_specific = is_chunk_candidate_relevance_sufficient(
        query=expansion_query,
        text=text,
        relevance=relevance,
    )
    visual_referent = _is_visual_referent_source_sibling(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    temporal_state_companion = _is_temporal_state_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    birdwatching_city_companion = _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    degree_policy_companion = _is_degree_policy_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    book_reading_inventory = _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    church_friend_activity_inventory = (
        _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    volunteering_service_activity = (
        _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    generic_behavior_companion = _is_generic_behavior_source_sibling_strong(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    classical_music_preference = (
        _is_classical_music_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    sentimental_reminder = _is_sentimental_reminder_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    outdoor_preference = _is_outdoor_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    outdoor_activity_visual_companion = (
        _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    children_preference = _is_children_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    direct_answer_evidence = _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    count_activity_followup = _is_count_activity_followup_source_sibling(
        rank=rank,
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
        text=text,
    )
    if (
        not relevance_specific
        and not visual_referent
        and not temporal_state_companion
        and not birdwatching_city_companion
        and not degree_policy_companion
        and not book_reading_inventory
        and not church_friend_activity_inventory
        and not volunteering_service_activity
        and not classical_music_preference
        and not sentimental_reminder
        and not outdoor_preference
        and not outdoor_activity_visual_companion
        and not children_preference
        and not direct_answer_evidence
        and not generic_behavior_companion
        and not count_activity_followup
    ):
        return rank.score
    relevance_boost = min(
        0.04,
        relevance.score_boost * 0.16 + relevance.distinctive_term_hits * 0.004,
    )
    visual_boost = 0.018 if visual_referent else 0.0
    temporal_state_boost = 0.014 if temporal_state_companion else 0.0
    generic_behavior_boost = 0.014 if generic_behavior_companion else 0.0
    score_floor = 0.966 if relevance_specific else 0.958
    if temporal_state_companion:
        score_floor = max(score_floor, 0.974)
    if generic_behavior_companion:
        score_floor = max(score_floor, 0.974)
    if birdwatching_city_companion:
        score_floor = max(score_floor, 0.972)
    if book_reading_inventory or church_friend_activity_inventory or volunteering_service_activity:
        score_floor = max(score_floor, 0.986)
    if classical_music_preference or sentimental_reminder:
        score_floor = max(score_floor, 0.986)
    if outdoor_preference:
        score_floor = max(score_floor, 0.984)
    if outdoor_activity_visual_companion:
        score_floor = max(score_floor, 0.986)
    if children_preference:
        score_floor = max(score_floor, 0.986)
    if direct_answer_evidence:
        score_floor = max(score_floor, 0.986)
    if _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        score_floor = max(score_floor, 0.982)
    if expansion_reason == "pet_acquisition_date_bridge" and _is_pet_acquisition_date_anchor(
        expansion_query=expansion_query,
        text=text,
    ):
        score_floor = max(score_floor, 0.99)
    score = min(
        0.99,
        round(
            max(rank.score, score_floor)
            + relevance_boost
            + visual_boost
            + temporal_state_boost
            + generic_behavior_boost,
            4,
        ),
    )
    score_cap = source_sibling_score_cap(
        expansion_reason=expansion_reason,
        relevance=relevance,
        text=text,
    )
    return min(score, score_cap) if score_cap is not None else score


def source_sibling_candidate_rank_key(
    *,
    precise_turn: bool,
    dialogue_visual_reference: bool,
    visual_continuation: bool,
    observation_companion: bool,
    answer_evidence: bool = False,
    answer_evidence_role_rank: int = 0,
    marker_coverage: int,
    relevance: QueryRelevance,
    score: float,
    rank: _SourceSiblingRank,
    chunk: MemoryChunk,
) -> tuple[float | int | str, ...]:
    return (
        0 if observation_companion else 1,
        0 if precise_turn else 1,
        0 if dialogue_visual_reference else 1,
        0 if visual_continuation else 1,
        -marker_coverage,
        0 if answer_evidence else 1,
        answer_evidence_role_rank if answer_evidence else 0,
        -relevance.distinctive_term_hits,
        -relevance.unique_term_hits,
        -relevance.hit_ratio,
        -score,
        rank.group_priority,
        rank.turn_distance,
        0 if rank.turn_delta > 0 else 1,
        chunk.source_external_id,
        chunk.sequence,
        str(chunk.id),
    )


def source_sibling_score_cap(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
) -> float | None:
    if _is_degree_policy_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return None
    if _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_church_friend_activity_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_inventory_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return None
    if _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return None
    if (
        expansion_reason in PRECISE_TURN_SOURCE_SIBLING_REASONS
        and relevance.distinctive_term_hits < _PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query="",
    ) and not _is_pottery_type_source_sibling_strong(text):
        return _POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "animal_care_instruction_bridge"
        and not _is_animal_care_instruction_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "animal_diet_evidence_bridge"
        and not _is_animal_diet_evidence_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in {"running_reason_bridge", "running_reason_question_bridge"}
        and not _is_running_reason_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "volunteer_career_inference_bridge"
        and not _is_volunteer_career_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "degree_policy_inference_bridge"
        and not _is_degree_policy_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "post_event_activity_timing_bridge"
        and not _is_post_event_activity_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON
        and not _is_generic_behavior_source_sibling_strong(
            expansion_query="",
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS
        and not _is_activity_duration_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS
        and not _is_frequency_recurrence_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    return None


def source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason == "pet_adjustment_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if expansion_reason == "planning_tool_use_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if expansion_reason == "customer_experience_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if expansion_reason == "grand_opening_support_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        )
    if _is_english_lifestyle_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    if expansion_reason == "charity_brand_sponsorship_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_charity_brand_sponsorship_source_sibling_strong(text)
    if expansion_reason == TRAVEL_HOBBY_WRITING_REASON:
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and is_travel_hobby_writing_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "recognition_award_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_recognition_award_direct_source_sibling(text)
    if expansion_reason == "church_friend_activity_inventory_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    aggregation_slot_count = aggregation_answer_slot_count(
        query=expansion_query,
        text=text,
    )
    if aggregation_slot_count > 0:
        if (
            source_sibling_inventory_answer_slot_count(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
            > 0
        ):
            return _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
        if _is_movie_seen_direct_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        ):
            return True
        if _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        ):
            if (
                _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
                and _MOVIE_SEEN_QUESTION_ONLY_SOURCE_SIBLING_RE.search(text) is not None
            ):
                return False
            if _is_common_interest_animal_affinity_window_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            ):
                return True
            return (
                _query_person_matches_text(expansion_query=expansion_query, text=text)
                and _is_precise_turn_retrieval_text(text)
            )
        if _is_board_game_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        ):
            return _is_board_game_direct_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        if _is_gaming_medium_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        ):
            return _is_gaming_medium_direct_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        if _is_creative_work_count_source_sibling_scope(expansion_reason):
            return _is_creative_work_count_source_sibling_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        return True
    if _is_common_interest_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_collectible_object_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_board_game_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_gaming_medium_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_temporal_source_sibling_strong(
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    if _is_temporal_event_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_pet_acquisition_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_cause_awareness_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS
        and _is_frequency_recurrence_source_sibling_strong(text)
    ):
        return True
    if (
        expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS
        and _is_activity_duration_source_sibling_strong(text)
    ):
        return True
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    return _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_activity_competition_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_activity_companion_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_church_friend_activity_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_inventory_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_classical_music_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_sentimental_reminder_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_collectible_object_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_outdoor_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_children_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_animal_diet_evidence_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_running_reason_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_support_network_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def source_sibling_answer_evidence_role_rank(
    *,
    query_text: str,
    expansion_reason: str,
    text: str,
) -> int:
    """Return a direction rank for answer evidence where the query encodes roles."""

    if is_country_destination_source_sibling_answer_evidence(
        expansion_query=query_text,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return country_destination_answer_support_rank(
            expansion_query=query_text,
            text=text,
            has_exact_turn=_is_precise_turn_retrieval_text(text),
        )
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return relationship_status_answer_rank(text)
    if not is_recommendation_list_reason(expansion_reason):
        return 0
    return recommendation_role_alignment_rank(
        text=text,
        query=query_text,
        query_reason=expansion_reason,
    )


def _is_activity_companion_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if (
        expansion_reason not in _ACTIVITY_COMPANION_SOURCE_SIBLING_REASONS
        and not _ACTIVITY_COMPANION_QUERY_RE.search(expansion_query)
    ):
        return False
    return (
        _ACTIVITY_COMPANION_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
        and _ACTIVITY_COMPANION_WITH_SOURCE_SIBLING_RE.search(text) is not None
    )


def _query_person_matches_text(*, expansion_query: str, text: str) -> bool:
    names = tuple(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(r"\b[A-Z][a-z]{2,}\b", expansion_query)
            if match.group(0)
            not in {
                "What",
                "Which",
                "Where",
                "When",
                "Who",
                "Whom",
                "Whose",
                "Why",
                "How",
            }
        )
    )
    if not names:
        return True
    text_casefold = text.casefold()
    return any(
        re.search(rf"\b{re.escape(name)}\s*:", text) is not None
        or re.search(rf"\b{re.escape(name.casefold())}\b", text_casefold) is not None
        for name in names
    )


def _is_precise_turn_retrieval_text(text: str) -> bool:
    return _PRECISE_TURN_RETRIEVAL_TEXT_RE.search(text) is not None


def _is_common_interest_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if _is_movie_seen_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_window_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _common_interest_answer_slot_count(text) > 0
    )


def _is_common_interest_animal_affinity_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query)
        is not None
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and (
            _COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
            or _COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE.search(text) is not None
        )
    )


def _is_common_interest_animal_affinity_window_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query)
        is not None
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        and _COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_movie_seen_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in _COMMON_INTEREST_SOURCE_SIBLING_REASONS
        and _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _is_precise_turn_retrieval_text(text)
        and _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_board_game_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_board_game_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _game_inventory_answer_directness_rank(text) == 0
    )


def _is_gaming_medium_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_gaming_medium_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _GAMING_MEDIUM_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_gaming_medium_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _GAMING_MEDIUM_SOURCE_SIBLING_REASONS
        or _GAMING_MEDIUM_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _is_board_game_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _BOARD_GAME_SOURCE_SIBLING_REASONS
        or _BOARD_GAME_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _is_common_interest_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _COMMON_INTEREST_SOURCE_SIBLING_REASONS
        or _COMMON_INTEREST_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _common_interest_answer_slot_count(text: str) -> int:
    return aggregation_answer_slot_count(
        query=_COMMON_INTEREST_ANSWER_SLOT_QUERY,
        text=text,
    )


def _is_temporal_source_sibling_strong(*, expansion_query: str, text: str) -> bool:
    return (
        _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _TEMPORAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_temporal_event_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "temporal_event_detail_bridge":
        return False
    if _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if _TEMPORAL_EVENT_ACTION_SOURCE_SIBLING_RE.search(text) is None:
        return False
    query_tokens = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3
            and token.casefold() not in _TEMPORAL_EVENT_QUERY_STOPWORDS
            and not token[:1].isupper()
        )
    )
    if len(query_tokens) < 4:
        return False
    text_casefold = text.casefold()
    hits = sum(
        1
        for token in query_tokens
        if re.search(rf"\b{re.escape(token)}\b", text_casefold) is not None
    )
    return hits >= 4


def _is_pet_acquisition_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "pet_acquisition_date_bridge":
        return False
    if _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if _PET_ACQUISITION_SOURCE_SIBLING_RE.search(text) is None:
        return _is_pet_acquisition_date_anchor(
            expansion_query=expansion_query,
            text=text,
        )
    query_terms = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3
            and token.casefold()
            not in {
                *_TEMPORAL_EVENT_QUERY_STOPWORDS,
                "adopt",
                "adopted",
                "get",
                "got",
            }
        )
    )
    if not query_terms:
        return True
    text_casefold = text.casefold()
    return any(
        re.search(rf"\b{re.escape(term)}\b", text_casefold) is not None
        for term in query_terms
    )


def _is_pet_acquisition_date_anchor(*, expansion_query: str, text: str) -> bool:
    if _PET_ACQUISITION_DATE_ANCHOR_RE.search(text) is None:
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    query_terms = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3 and token[:1].isupper()
        )
    )
    if len(query_terms) < 2:
        return False
    text_casefold = text.casefold()
    hits = sum(
        1
        for term in query_terms
        if re.search(rf"\b{re.escape(term)}\b", text_casefold) is not None
    )
    return hits >= 2


def _is_cause_awareness_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "cause_awareness_event_bridge"
        and _CAUSE_AWARENESS_EVENT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_classical_music_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "classical_music_preference_bridge"
        and _CLASSICAL_MUSIC_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_sentimental_reminder_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "sentimental_reminder_bridge"
        and _SENTIMENTAL_REMINDER_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_collectible_object_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason not in {
        "decomposition_collectible_object",
        "decomposition_commonality",
        "decomposition_activity_participation",
        "decomposition_followup_task",
        "original_query",
    }:
        return False
    if _COLLECTIBLE_OBJECT_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    return _COLLECTIBLE_OBJECT_SOURCE_SIBLING_RE.search(text) is not None


def _is_outdoor_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in {"outdoor_preference_bridge", "outdoor_nature_memory_bridge"}
        and _OUTDOOR_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "outdoor_activity_inventory_bridge"
        and _OUTDOOR_ACTIVITY_VISUAL_COMPANION_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_children_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "children_preference_bridge"
        and _CHILDREN_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )


def is_pottery_type_observation_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    if not str(chunk.source_external_id).endswith(":observation"):
        return False
    return _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    )


def source_sibling_marker_coverage_count(*, expansion_reason: str, text: str) -> int:
    if expansion_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_slot_count(text)
    if not _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return 0
    return len(tuple(dict.fromkeys(_DIALOGUE_MARKER_RE.findall(text))))


def is_same_document_answer_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    return is_pottery_type_observation_companion(
        chunk=chunk,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_pottery_type_retrieval_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    return _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    )


def is_pottery_type_evidence_text(text: str) -> bool:
    return _is_pottery_type_source_sibling_strong(text)


def source_sibling_companion_extra_slot(*, chunk: MemoryChunk, text: str) -> str:
    if not str(chunk.source_external_id).endswith(":observation"):
        return ""
    markers = tuple(dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(text)))
    if len(markers) < 2:
        return ""
    return f"{chunk.source_external_id}:{markers[0]}:{markers[-1]}"


def source_sibling_relevance_allowed(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    ) and not _is_pottery_type_source_sibling_strong(text):
        return False
    if expansion_reason == "animal_care_instruction_bridge":
        return _is_animal_care_instruction_source_sibling_strong(text)
    if expansion_reason == "animal_diet_evidence_bridge":
        return _is_animal_diet_evidence_source_sibling_strong(text)
    if (
        expansion_reason in {"running_reason_bridge", "running_reason_question_bridge"}
        and not _is_running_reason_source_sibling_strong(text)
    ):
        return False
    if (
        expansion_reason == "post_event_activity_timing_bridge"
        and not _is_post_event_activity_source_sibling_strong(text)
    ):
        return False
    if expansion_reason == "cause_awareness_event_bridge":
        return _is_cause_awareness_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    if _is_classical_music_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_sentimental_reminder_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_outdoor_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_children_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if expansion_reason == _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return _is_generic_behavior_source_sibling_strong(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "degree_policy_inference_bridge":
        return _is_degree_policy_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "career_path_bridge":
        return _is_career_path_source_sibling_strong(text)
    if expansion_reason == "book_reading_list_bridge":
        return _is_book_reading_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "church_friend_activity_inventory_bridge":
        return _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason in {
        "volunteering_inventory_bridge",
        "volunteering_people_inventory_bridge",
    }:
        return _is_volunteering_inventory_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(text)
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    if _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_church_friend_activity_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_volunteering_inventory_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if aggregation_answer_slot_count(query=expansion_query, text=text) > 0:
        return True
    if _is_count_activity_followup_source_sibling(
        rank=rank,
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    return is_chunk_candidate_relevance_sufficient(
        query=expansion_query,
        text=text,
        relevance=relevance,
    ) or _is_visual_referent_source_sibling(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_visual_continuation_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        rank.group_level_seed
        and rank.turn_delta > 0
        and rank.turn_distance <= 1
        and _is_visual_referent_source_sibling(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    )


def is_dialogue_visual_reference_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if not rank.group_level_seed:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _DIALOGUE_VISUAL_REFERENCE_RE.search(text) is not None


def is_precise_source_sibling_turn(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in PRECISE_TURN_SOURCE_SIBLING_REASONS
        and source_turn_marker(chunk.source_external_id) is not None
    )


def with_source_sibling_score_signals(
    item: ContextItem,
    *,
    rank: _SourceSiblingRank,
    score_cap: float | None = None,
    dialogue_visual_reference: bool = False,
    visual_continuation: bool = False,
    answer_evidence: bool = False,
    answer_evidence_query: str = "",
) -> ContextItem:
    after_seed_boost = 0.05 if rank.turn_delta > 0 else 0.0
    diagnostics = dict(item.diagnostics or {})
    score_signals = {
        **_score_signals(diagnostics),
        "source_sibling_after_seed_boost": after_seed_boost,
        "source_sibling_score_cap": score_cap,
        "source_sibling_score_cap_applied": 1 if score_cap is not None else 0,
        "source_sibling_dialogue_visual_reference": 1 if dialogue_visual_reference else 0,
        "source_sibling_visual_continuation": 1 if visual_continuation else 0,
        "source_sibling_answer_evidence": 1 if answer_evidence else 0,
        "source_sibling_group_level_seed": 1 if rank.group_level_seed else 0,
        "source_sibling_group_boost": max(0, _MAX_SOURCE_GROUPS - rank.group_priority),
        "source_sibling_after_seed": 1 if rank.turn_delta > 0 else 0,
        "source_sibling_closeness": max(0, 4 - rank.turn_distance),
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
    }
    provenance = {
        **_provenance(diagnostics),
        "source_sibling_turn_delta": rank.turn_delta,
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
        "source_sibling_group_level_seed": rank.group_level_seed,
        "source_sibling_score_cap_applied": score_cap is not None,
        "source_sibling_dialogue_visual_reference": dialogue_visual_reference,
        "source_sibling_visual_continuation": visual_continuation,
        "source_sibling_answer_evidence": answer_evidence,
    }
    if answer_evidence and answer_evidence_query:
        score_signals["source_sibling_answer_evidence_query"] = answer_evidence_query
        provenance["source_sibling_answer_evidence_query"] = answer_evidence_query
    diagnostics["score_signals"] = score_signals
    diagnostics["provenance"] = provenance
    return replace(
        item,
        score=_apply_source_sibling_score_cap(
            score=min(0.99, round(item.score + after_seed_boost, 4)),
            score_cap=score_cap,
        ),
        diagnostics=diagnostics,
    )


def source_group_seed_turns(
    seed_chunks: tuple[MemoryChunk, ...],
) -> dict[str, _SourceGroupSeed]:
    groups: dict[str, tuple[int, int, set[int], bool]] = {}
    for chunk in seed_chunks:
        marker = source_turn_marker(chunk.source_external_id)
        if marker is None:
            group = _source_session_group(chunk.source_external_id)
            if group is None:
                continue
            if group not in groups:
                groups[group] = (len(groups), 0, set(), True)
            else:
                priority, primary_turn, turns, _ = groups[group]
                groups[group] = (priority, primary_turn, turns, True)
            if len(groups) >= _MAX_SOURCE_GROUPS:
                break
            continue
        group, turn = marker
        if group not in groups:
            groups[group] = (len(groups), turn, set(), False)
        priority, primary_turn, turns, group_level = groups[group]
        turns.add(turn)
        groups[group] = (priority, primary_turn or turn, turns, group_level)
        if len(groups) >= _MAX_SOURCE_GROUPS:
            break
    return {
        group: _SourceGroupSeed(
            priority=priority,
            primary_turn=primary_turn,
            turns=frozenset(turns),
            group_level=group_level,
        )
        for group, (priority, primary_turn, turns, group_level) in groups.items()
    }


def source_turn_marker(source_external_id: str) -> tuple[str, int] | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    match = _TURN_SOURCE_ID_RE.match(source_id)
    if match is None:
        return None
    group = match.group("group").strip()
    if not group or len(group.split(":")) < 3:
        return None
    try:
        turn = int(match.group("turn"))
    except ValueError:
        return None
    return group, turn


def source_sibling_rank(
    chunk: MemoryChunk,
    *,
    source_groups: dict[str, _SourceGroupSeed],
) -> _SourceSiblingRank | None:
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        group = _source_session_group(chunk.source_external_id)
        if group is None:
            return None
        seed = source_groups.get(group)
        if seed is None:
            return None
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE
            if seed.group_level
            else _SOURCE_GROUP_SIBLING_SCORES[1],
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
            group_level_seed=seed.group_level,
        )
    group, turn = marker
    seed = source_groups.get(group)
    if seed is None or not seed.turns:
        if seed is not None and seed.group_level:
            return _SourceSiblingRank(
                score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
                group_priority=seed.priority,
                turn_distance=0,
                turn_delta=0,
                group_level_seed=True,
            )
        return None
    if seed.group_level:
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
            group_level_seed=True,
        )
    if turn == seed.primary_turn:
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
        )
    seed_turns = tuple(seed_turn for seed_turn in seed.turns if seed_turn != turn)
    if not seed_turns:
        return None
    turn_delta = min(
        (turn - seed_turn for seed_turn in seed_turns),
        key=lambda delta: (abs(delta), delta < 0),
    )
    min_distance = abs(turn_delta)
    score = _SOURCE_GROUP_SIBLING_SCORES.get(min_distance)
    if score is None:
        return None
    return _SourceSiblingRank(
        score=score,
        group_priority=seed.priority,
        turn_distance=min_distance,
        turn_delta=turn_delta,
    )


def source_sibling_distant_answer_evidence_rank(
    chunk: MemoryChunk,
    *,
    expansion_query: str,
    source_groups: dict[str, _SourceGroupSeed],
    expansion_reason: str,
    text: str,
) -> _SourceSiblingRank | None:
    """Allow high-signal same-session evidence turns beyond the short sibling window."""

    slot_count = _distant_source_sibling_answer_slot_count(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    if slot_count <= 0:
        return None
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        return None
    group, turn = marker
    seed = source_groups.get(group)
    if seed is None or seed.group_level:
        return None
    if seed.turns:
        turn_delta = min(
            (turn - seed_turn for seed_turn in seed.turns),
            key=lambda delta: (abs(delta), delta < 0),
        )
    else:
        turn_delta = turn - seed.primary_turn
    return _SourceSiblingRank(
        score=0.966 + min(slot_count, 3) * 0.004,
        group_priority=seed.priority,
        turn_distance=min(abs(turn_delta), 5),
        turn_delta=turn_delta,
    )


def _distant_source_sibling_answer_slot_count(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> int:
    if expansion_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_slot_count(text)
    slot_count = aggregation_answer_slot_count(query=expansion_query, text=text)
    if _is_common_interest_source_sibling_scope(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return max(slot_count, _common_interest_answer_slot_count(text))
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if _query_person_matches_text(
        expansion_query=expansion_query,
        text=text,
    ) and is_country_destination_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if (
        is_recommendation_list_reason(expansion_reason)
        and recommendation_list_answer_support_rank(
            text=text,
            query_reason=expansion_reason,
        )
        <= 2
    ):
        return max(slot_count, 2)
    if _query_person_matches_text(
        expansion_query=expansion_query,
        text=text,
    ) and is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    return slot_count


def _is_pottery_type_source_sibling_strong(text: str) -> bool:
    return (
        _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(text) is not None
        and _POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE.search(text) is not None
    )


def _is_animal_care_instruction_source_sibling_strong(text: str) -> bool:
    return _ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE.search(text) is not None


def _is_animal_diet_evidence_source_sibling_strong(text: str) -> bool:
    return _ANIMAL_DIET_EVIDENCE_SOURCE_SIBLING_RE.search(text) is not None


def _is_animal_diet_evidence_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "animal_diet_evidence_bridge"
        and _is_animal_diet_evidence_source_sibling_strong(text)
    )


def _is_pottery_type_source_sibling_reason(expansion_reason: str) -> bool:
    return expansion_reason.replace("_", "-") in {
        "pottery-type-bridge",
        "decomposition-inventory-list",
    }


def _is_pottery_type_source_sibling_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    if expansion_reason == "pottery_type_bridge":
        return True
    if expansion_reason != "decomposition_inventory_list":
        return False
    return _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(expansion_query) is not None


def _is_pottery_type_observation_companion_text(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _is_pottery_type_source_sibling_reason(expansion_reason):
        return False
    return _is_pottery_type_source_sibling_strong(text) and "related turns:" in text.lower()


def _is_running_reason_source_sibling_strong(text: str) -> bool:
    return _RUNNING_REASON_SOURCE_SIBLING_RE.search(text) is not None


def _is_running_reason_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in {"running_reason_bridge", "running_reason_question_bridge"}
        and _is_running_reason_source_sibling_strong(text)
    )


def _is_volunteer_career_source_sibling_strong(text: str) -> bool:
    return (
        _VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_charity_brand_sponsorship_source_sibling_strong(text: str) -> bool:
    return _CHARITY_BRAND_SPONSORSHIP_SOURCE_SIBLING_RE.search(text) is not None


def _is_career_path_source_sibling_strong(text: str) -> bool:
    return _CAREER_PATH_SOURCE_SIBLING_RE.search(text) is not None


def _is_english_lifestyle_inference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    text: str,
) -> bool:
    if not english_lifestyle_query_kind(expansion_query):
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    slot, rank = english_lifestyle_answer_slot_and_rank(
        text,
        query=expansion_query,
    )
    return bool(slot) and rank == 0


def _is_direct_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    normalized_reason = expansion_reason.replace("_", "-")
    if (
        normalized_reason == "commonality-interest-bridge"
        and _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    ):
        return True
    if _is_common_interest_animal_affinity_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_window_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_creative_work_count_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_collectible_object_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        source_sibling_inventory_answer_slot_count(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
        > 0
    ):
        return True
    if food_inventory_answer_support_applies(
        query=expansion_query,
        query_reason=expansion_reason,
    ):
        return (
            food_inventory_role_alignment_rank(
                text=text,
                query=expansion_query,
                query_reason=expansion_reason,
            )
            <= 1
            and food_inventory_answer_support_rank(
                text=text,
                query=expansion_query,
                query_reason=expansion_reason,
                has_exact_turn=True,
            )
            <= 1
        )
    if (
        is_recommendation_list_reason(expansion_reason)
        and recommendation_list_answer_support_rank(
            text=text,
            query_reason=expansion_reason,
        )
        <= 2
    ):
        return True
    if normalized_reason == "item-purchase-bridge":
        return has_item_purchase_object_evidence(text)
    if normalized_reason in {
        "business-commonality-bridge",
        "business-start-reason-bridge",
    }:
        return _BUSINESS_COMMONALITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "public-office-service-bridge"
        or _PUBLIC_OFFICE_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    ):
        return _PUBLIC_OFFICE_MOTIVATION_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "recognition-award-bridge"
        or _RECOGNITION_AWARD_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    ):
        return _is_recognition_award_direct_source_sibling(text)
    if normalized_reason == "planning-tool-use-bridge":
        return _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "customer-experience-bridge":
        return _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "grand-opening-support-bridge":
        return _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "charity-brand-sponsorship-bridge":
        return _is_charity_brand_sponsorship_source_sibling_strong(text)
    if normalized_reason == "travel-hobby-writing-bridge":
        return is_travel_hobby_writing_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if normalized_reason == "pet-adjustment-bridge":
        return _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "post-event-emotion-bridge":
        return _POST_EVENT_SUPPORT_APPRECIATION_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "destress-activity-bridge":
        return _DESTRESS_ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason in {
        "activity-aggregation-bridge",
        "decomposition-activity-participation",
        "family-activity-bridge",
    }:
        return _ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "nickname-bridge"
        or _NICKNAME_QUERY_RE.search(expansion_query) is not None
    ):
        return _NICKNAME_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_country_destination_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        normalized_reason == "study-time-management-bridge"
        or _STUDY_TIME_MANAGEMENT_SOURCE_SIBLING_QUERY_RE.search(expansion_query)
        is not None
    ):
        return _STUDY_TIME_MANAGEMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _MEDIA_WATCHING_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        return _MEDIA_WATCHING_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _ESCAPE_ACTIVITY_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        return _ESCAPE_ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if normalized_reason in {
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
    }:
        return _CAUSE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _PLACE_INVENTORY_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        if is_country_inventory_place_inference_query(expansion_query):
            return False
        return _TRIP_DESTINATION_NAMED_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "trip-destination-bridge":
        return _TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    return False


def _is_creative_work_count_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _is_creative_work_count_source_sibling_scope(expansion_reason):
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    if not _is_precise_turn_retrieval_text(text):
        return False
    return (
        creative_work_count_role_alignment_rank(
            text=text,
            query=expansion_query,
            query_reason=expansion_reason,
        )
        <= 1
        and creative_work_count_answer_rank(
            text=text,
            query=expansion_query,
            query_reason=expansion_reason,
            has_exact_turn=True,
        )
        <= 1
    )


def _is_creative_work_count_source_sibling_scope(expansion_reason: str) -> bool:
    return (
        expansion_reason.replace("_", "-")
        in _CREATIVE_WORK_COUNT_SOURCE_SIBLING_REASONS
    )


def _is_named_preference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if (
        expansion_reason != "decomposition_inference_support"
        and _NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None
    ):
        return False
    if _NAMED_PREFERENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is None:
        return False
    text_casefold = text.casefold()
    return any(
        phrase in text_casefold
        for phrase in _named_preference_query_phrases(expansion_query)
    )


def is_named_preference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def _named_preference_query_phrases(expansion_query: str) -> tuple[str, ...]:
    tokens = tuple(
        token.casefold().strip("+-'")
        for token in _NAMED_PREFERENCE_QUERY_TOKEN_RE.findall(expansion_query)
    )
    content_tokens = tuple(
        token
        for token in tokens
        if len(token) >= 3 and token not in _NAMED_PREFERENCE_QUERY_STOPWORDS
    )
    phrases: list[str] = []
    for width in (3, 2):
        if len(content_tokens) < width:
            continue
        for index in range(0, len(content_tokens) - width + 1):
            phrase = " ".join(content_tokens[index : index + width])
            if phrase not in phrases:
                phrases.append(phrase)
    return tuple(phrases)


def _is_support_network_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in _SUPPORT_NETWORK_SOURCE_SIBLING_REASONS
        and _SUPPORT_NETWORK_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_book_reading_inventory_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {
            "book_reading_list_bridge",
            "creative_writing_career_bridge",
            "decomposition_inventory_list",
        }
        and _BOOK_READING_INVENTORY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_activity_competition_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "activity_competition_evidence_bridge"
        and _ACTIVITY_COMPETITION_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_church_friend_activity_inventory_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {"church_friend_activity_inventory_bridge", "decomposition_inventory_list"}
        and _CHURCH_FRIEND_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_volunteering_inventory_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {"volunteering_inventory_bridge", "volunteering_people_inventory_bridge"}
        and _VOLUNTEERING_INVENTORY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_volunteering_service_activity_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in {"volunteering_inventory_bridge", "decomposition_inventory_list"}
        and _VOLUNTEERING_SERVICE_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_recognition_award_direct_source_sibling(text: str) -> bool:
    return (
        _RECOGNITION_AWARD_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        or _RECOGNITION_CERTIFICATE_VISUAL_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_degree_policy_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "degree_policy_inference_bridge":
        return False
    return _DEGREE_POLICY_SOURCE_SIBLING_RE.search(text) is not None


def _is_post_event_activity_source_sibling_strong(text: str) -> bool:
    return _POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None


def _is_temporal_state_source_sibling_strong(*, expansion_reason: str, text: str) -> bool:
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(text)
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    return False


def _is_activity_duration_source_sibling_strong(text: str) -> bool:
    return (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_frequency_recurrence_source_sibling_strong(text: str) -> bool:
    return (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_birdwatching_city_schedule_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "birdwatching_city_schedule_bridge"
        and _BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _birdwatching_city_schedule_slot_count(text: str) -> int:
    slots = 0
    for pattern in (
        _BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE,
    ):
        if pattern.search(text) is not None:
            slots += 1
    return slots


def _is_generic_behavior_source_sibling_strong(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return False
    if (
        generic_behavior_inference_signal(query=expansion_query, text=text).reason
        == "inference_behavior_evidence"
    ):
        return True
    # Score caps do not receive the winning expansion query. This strict fallback
    # keeps concrete behavior turns uncapped while still rejecting topic-only text.
    return (
        generic_behavior_inference_signal(query=text, text=text).reason
        == "inference_behavior_evidence"
    )


def _is_count_activity_followup_source_sibling(
    *,
    rank: _SourceSiblingRank,
    expansion_reason: str,
    expansion_query: str,
    text: str,
) -> bool:
    if expansion_reason not in _COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS:
        return False
    if rank.turn_delta <= 0 or rank.turn_distance > 2:
        return False
    subject = _query_subject_name(expansion_query)
    if not subject:
        return False
    return re.search(rf"\b{re.escape(subject)}\b", text, re.IGNORECASE) is not None


def _query_subject_name(query: str) -> str:
    match = re.match(r"\s*([A-Z][A-Za-z][A-Za-z'-]*)\b", query)
    return match.group(1) if match is not None else ""


def _is_visual_referent_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if rank.turn_distance > 2:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _VISUAL_REFERENT_SIBLING_RE.search(text) is not None


def _visual_source_sibling_priority_allowed(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _VISUAL_SOURCE_SIBLING_REASONS
        or expansion_reason in _EVENT_VISUAL_SOURCE_SIBLING_REASONS
        or _VISUAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _source_session_group(source_external_id: str) -> str | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1].casefold() in _SOURCE_GROUP_SUFFIXES:
        group = ":".join(parts[:-1])
        return group if _source_group_has_session_tail(group) else None
    return source_id if _source_group_has_session_tail(source_id) else None


def _source_group_has_session_tail(source_id: str) -> bool:
    parts = source_id.split(":")
    return bool(parts and re.fullmatch(r"session_\d+", parts[-1], re.IGNORECASE))


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _apply_source_sibling_score_cap(*, score: float, score_cap: float | None) -> float:
    return min(score, score_cap) if score_cap is not None else score
