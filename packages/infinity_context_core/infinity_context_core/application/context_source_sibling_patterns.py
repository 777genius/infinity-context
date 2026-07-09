"""Source-sibling regex and scoring constants."""

from __future__ import annotations

import re

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

_MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS = 6

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
    r"clear\s+my\s+mind|headspace|farther|longer|mood|boost))|"
    r"(?:destress|de-stress|clear\s+my\s+mind|headspace|farther|longer)\b"
    r"(?=.{0,120}\b(?:running|run|runs|ran))|"
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
    r"practice(?:d|s|ing)?|train(?:ed|s|ing)?|"
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

_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})
