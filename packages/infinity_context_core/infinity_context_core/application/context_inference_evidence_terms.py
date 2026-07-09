"""Term and regex catalogs for inference evidence reranking."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_INFERENCE_QUERY_TERMS = frozenset(
    {
        "could",
        "infer",
        "inference",
        "likely",
        "may",
        "might",
        "probably",
        "should",
        "would",
        "вероятно",
        "может",
        "похоже",
    }
)

_CAUSAL_QUERY_TERMS = frozenset(
    {
        "because",
        "belonging",
        "cause",
        "caused",
        "gave",
        "reason",
        "why",
        "почему",
        "причина",
        "принадлежность",
        "принадлежности",
        "чувство",
        "ощущение",
        "дал",
        "дала",
        "дало",
    }
)

_SUPPORT_ROLE_ACTION_TERMS = frozenset(
    {
        "advise",
        "advised",
        "advising",
        "care",
        "cared",
        "coach",
        "coached",
        "comfort",
        "comforted",
        "confide",
        "confided",
        "confides",
        "confiding",
        "counsel",
        "counseled",
        "counseling",
        "empathy",
        "empathetic",
        "guide",
        "guided",
        "guidance",
        "help",
        "helped",
        "helping",
        "listen",
        "listened",
        "mentor",
        "mentored",
        "mentoring",
        "mentorship",
        "open",
        "opened",
        "opening",
        "patient",
        "reliable",
        "responsible",
        "support",
        "supported",
        "supporting",
        "trust",
        "trusted",
        "trusting",
        "volunteer",
        "volunteered",
        "volunteering",
    }
)

_GENERIC_SUPPORT_ACTION_TERMS = frozenset(
    {
        "support",
        "supported",
        "supporting",
    }
)

_SUPPORT_ROLE_SCENARIO_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "ally",
        "allies",
        "anxiety",
        "children",
        "community",
        "group",
        "health",
        "issue",
        "kids",
        "lgbtq",
        "people",
        "personal",
        "pride",
        "private",
        "problem",
        "problems",
        "secret",
        "sensitive",
        "safe",
        "shelter",
        "similar",
        "struggle",
        "struggles",
        "trans",
        "transgender",
        "youth",
    }
)

_INTERPERSONAL_SUPPORT_ACTION_TERMS = _SUPPORT_ROLE_ACTION_TERMS - frozenset(
    {
        "reliable",
        "responsible",
        "support",
        "supported",
        "supporting",
        "volunteer",
        "volunteered",
        "volunteering",
    }
)

_SUPPORT_ROLE_OPERATIONAL_NOISE_RE = re.compile(
    r"\b(?:backend|provider|technical|customer|ticket|tickets?|issue\s+tracker|"
    r"support\s+notes?|support\s+queue|support\s+desk|help\s+desk)\b",
    re.IGNORECASE,
)

_COUNTERFACTUAL_SUPPORT_QUERY_TERMS = frozenset(
    {
        "accept",
        "accepted",
        "ally",
        "confide",
        "confided",
        "confiding",
        "encourage",
        "encouraging",
        "help",
        "helping",
        "join",
        "joining",
        "safe",
        "support",
        "supporting",
        "trust",
        "trusted",
        "trusting",
        "welcome",
        "союзник",
        "поможет",
        "помог",
        "помогла",
        "поддержит",
        "поддержал",
        "поддержала",
        "примет",
    }
)

_COUNTERFACTUAL_SUPPORT_EVIDENCE_TERMS = frozenset(
    {
        "accepted",
        "accepting",
        "acceptance",
        "ally",
        "comforted",
        "confided",
        "confide",
        "confiding",
        "encourage",
        "encouraged",
        "encouraging",
        "helped",
        "listened",
        "opened",
        "private",
        "safe",
        "supportive",
        "trusted",
        "trusting",
        "welcomed",
        "welcome",
        "безопасно",
        "выслушал",
        "выслушала",
        "помог",
        "помогла",
        "помогал",
        "помогала",
        "поддержал",
        "поддержала",
        "поддерживал",
        "поддерживала",
        "принял",
        "приняла",
    }
)

_COUNTERFACTUAL_SUPPORT_DOMAIN_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "community",
        "group",
        "lgbt",
        "lgbtq",
        "pride",
        "queer",
        "safe",
        "trans",
        "transgender",
        "welcome",
        "youth",
        "группа",
        "группу",
        "квир",
        "лгбт",
        "прайд",
        "сообщество",
        "транс",
    }
)

_WILLINGNESS_QUERY_TERMS = frozenset(
    {
        "consider",
        "considered",
        "considering",
        "open",
        "ready",
        "willing",
        "would",
    }
)

_WILLINGNESS_MARKER_TERMS = frozenset(
    {
        "consider",
        "considered",
        "considering",
        "excited",
        "hope",
        "hopeful",
        "hopes",
        "interested",
        "join",
        "joined",
        "joining",
        "open",
        "plan",
        "planned",
        "planning",
        "ready",
        "want",
        "wanted",
        "wants",
        "willing",
    }
)

_RELOCATION_WILLINGNESS_QUERY_TERMS = frozenset(
    {
        "abroad",
        "another",
        "country",
        "international",
        "move",
        "moving",
        "relocate",
        "relocation",
    }
)

_WILLINGNESS_TEXT_DOMAIN_TERMS = frozenset(
    {
        "abroad",
        "campaign",
        "country",
        "international",
        "military",
        "mission",
        "move",
        "moving",
        "office",
        "politics",
        "public",
        "relocate",
        "relocation",
        "service",
        "veteran",
    }
)

_PUBLIC_OFFICE_SERVICE_TEXT_TERMS = frozenset(
    {
        "campaign",
        "civic",
        "elected",
        "election",
        "office",
        "politics",
        "public",
        "running",
    }
)

_CAREER_INFERENCE_QUERY_TERMS = frozenset(
    {
        "career",
        "field",
        "future",
        "job",
        "jobs",
        "occupation",
        "path",
        "pursue",
        "work",
    }
)

_ANIMAL_CAREER_QUERY_TERMS = frozenset(
    {
        "alternative",
        "career",
        "gaming",
    }
)

_CAREER_DECISION_QUERY_TERMS = frozenset(
    {
        "choose",
        "chooses",
        "chose",
        "chosen",
        "decide",
        "decided",
        "education",
        "educaton",
        "edu",
        "field",
        "fields",
        "option",
        "options",
        "persue",
        "pursue",
    }
)

_CAREER_DOMAIN_TEXT_TERMS = frozenset(
    {
        "bed",
        "counseling",
        "counselor",
        "desk",
        "food",
        "front",
        "health",
        "homeless",
        "mental",
        "residents",
        "shelter",
        "social",
        "talks",
        "volunteer",
        "volunteered",
        "volunteering",
        "work",
    }
)

_CAREER_FIELD_TEXT_TERMS = frozenset(
    {
        "counseling",
        "counselor",
        "health",
        "mental",
        "psychology",
        "social",
        "therapy",
        "therapist",
        "work",
    }
)

_CAREER_INTENT_TEXT_TERMS = frozenset(
    {
        "compliments",
        "connecting",
        "difference",
        "fulfilled",
        "fulfilling",
        "helping",
        "interested",
        "looking",
        "meaningful",
        "purpose",
        "pursue",
        "rewarding",
        "wanted",
        "wants",
    }
)

_CAREER_DECISION_TEXT_TERMS = frozenset(
    {
        "choose",
        "choosing",
        "chose",
        "chosen",
        "considering",
        "decided",
        "interested",
        "keen",
        "looking",
        "love",
        "pursue",
        "pursuing",
        "support",
        "want",
        "wanted",
        "wants",
    }
)

_CAREER_TOPIC_ONLY_TERMS = frozenset(
    {
        "career",
        "fair",
        "future",
        "job",
        "jobs",
        "occupation",
        "path",
        "work",
    }
)

_CAREER_NEGATED_DECISION_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|would\s+not|won't|never)\s+"
    r"(?:decide|decided|choose|chose|want|wanted|pursue|pursued|consider|"
    r"considered|look|looked|looking)\b|"
    r"\b(?:decided|chose)\s+not\s+to\s+(?:pursue|choose|work|study)\b|"
    r"\bno\s+longer\s+(?:pursuing|interested|considering)\b",
    re.IGNORECASE,
)

_ANIMAL_CARE_TEXT_TERMS = frozenset(
    {
        "animal",
        "animals",
        "care",
        "clean",
        "cute",
        "diet",
        "feed",
        "fruits",
        "habitat",
        "insects",
        "joy",
        "light",
        "pet",
        "pets",
        "store",
        "tank",
        "turtle",
        "turtles",
        "vegetables",
    }
)

_ANIMAL_CARE_TOPIC_NOISE_TERMS = frozenset(
    {
        "console",
        "game",
        "games",
        "gaming",
        "tournament",
        "tournaments",
    }
)

_MILITARY_SERVICE_TEXT_TERMS = frozenset(
    {
        "military",
        "mission",
        "service",
        "veteran",
    }
)

_PATRIOTIC_QUERY_TERMS = frozenset(
    {
        "patriot",
        "patriotic",
        "patriotism",
    }
)

_PATRIOTIC_SERVICE_TEXT_TERMS = frozenset(
    {
        "aptitude",
        "military",
        "mission",
        "serve",
        "serving",
        "service",
        "volunteer",
        "volunteering",
    }
)

_PATRIOTIC_MOTIVE_TEXT_TERMS = frozenset(
    {
        "country",
        "duty",
        "eagle",
        "flag",
        "honor",
        "honour",
        "patriotic",
        "pride",
        "proud",
    }
)

_CHILDREN_BOOKS_QUERY_TERMS = frozenset(
    {
        "book",
        "books",
        "bookshelf",
        "childrens",
        "dr",
        "seuss",
    }
)

_CHILDREN_BOOKS_TEXT_TERMS = frozenset(
    {
        "children",
        "childrens",
        "classics",
        "classic",
        "cultures",
        "educational",
        "kids",
        "stories",
    }
)

_BOOK_TOPIC_TEXT_TERMS = frozenset(
    {
        "book",
        "books",
        "bookshelf",
        "collection",
        "fantasy",
        "novel",
        "read",
        "series",
    }
)

_RELIGIOUS_QUERY_TERMS = frozenset(
    {
        "religion",
        "religious",
        "faith",
    }
)

_RELIGIOUS_TEXT_TERMS = frozenset(
    {
        "church",
        "faith",
        "glass",
        "pray",
        "prayer",
        "prayers",
        "prays",
        "religious",
        "spiritual",
        "stained",
        "worship",
        "worships",
    }
)

_RELIGIOUS_STRONG_TEXT_TERMS = frozenset(
    {
        "church",
        "faith",
        "glass",
        "pray",
        "prayer",
        "prayers",
        "prays",
        "spiritual",
        "stained",
        "worship",
        "worships",
    }
)

_RELIGIOUS_TOPIC_NOISE_TERMS = frozenset(
    {
        "acceptance",
        "accept",
        "conservative",
        "conservatives",
        "growth",
        "journey",
        "transgender",
        "transition",
        "unwelcoming",
    }
)

_RELIGIOUS_CONTRAST_CONTEXT_TERMS = frozenset(
    {
        "conservative",
        "conservatives",
        "unwelcoming",
        "upset",
        "lgbtq",
        "rights",
    }
)

_CAUSAL_TEXT_RE = re.compile(
    r"\b(?:because|so|since|therefore|reason|caused|led\s+to|inspired|"
    r"motivated|made\s+(?:me|her|him|them)\s+feel|gave\s+(?:me|her|him|them)|"
    r"source\s+of|helped\s+(?:me|her|him|them)\s+feel|feel\s+at\s+home|"
    r"sense\s+of\s+belonging|belonged|belonging)\b|"
    r"\b(?:потому|поэтому|причин\w*|из-за|вдохнов\w*|мотивир\w*|"
    r"дал[оаи]?|помогл?[оаи]?\s+почувствовать|почувств\w+\s+себя\s+дома|"
    r"ощущени\w+\s+принадлежност\w*)\b",
    re.IGNORECASE,
)

_CAUSAL_EFFECT_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "belong",
        "belonged",
        "belonging",
        "community",
        "fulfilling",
        "happiness",
        "happy",
        "home",
        "inspired",
        "motivated",
        "powerful",
        "pride",
        "proud",
        "purpose",
        "safe",
        "welcomed",
        "дома",
        "принадлежность",
        "принадлежности",
        "сообщество",
        "своим",
        "своей",
    }
)

_CAUSAL_QUERY_STOP_TERMS = frozenset(
    {
        "did",
        "does",
        "gave",
        "give",
        "is",
        "of",
        "sense",
        "the",
        "to",
        "was",
        "what",
        "when",
        "who",
        "why",
    }
)

_EMOTION_CAUSE_QUERY_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "belong",
        "belonging",
        "feel",
        "feeling",
        "fulfilled",
        "happy",
        "happiness",
        "home",
        "proud",
        "sense",
        "дома",
        "принадлежность",
        "принадлежности",
        "чувство",
        "ощущение",
    }
)

_GENERIC_SUPPORT_NOISE_RE = re.compile(
    r"\b(?:friends?|family|mentors?|parents?|people\s+around|support\s+system|rocks)\b"
    r".{0,100}\b(?:support|there\s+for|encourage|motivate|strength)\b|"
    r"\b(?:supportive|support|supported)\b.{0,80}\b(?:friend|family|mentor|parent)\b",
    re.IGNORECASE | re.DOTALL,
)
