"""Personal fact query expansion rules for evidence-oriented retrieval."""

from __future__ import annotations

import re

_AGE_BIRTHDAY_EXPANSION = "age years old born birthday date of birth birth year dob"
_BORN_BIRTHDAY_EXPANSION = "born birthday date of birth birth year age years old dob"
_BIRTH_DATE_EXPANSION = "birth date of birth born birthday birth year age years old dob"
_BIRTHDAY_EXPANSION = "birthday born date of birth birth year age years old dob"
_BIRTHPLACE_EXPANSION = (
    "birthplace born in from origin hometown home country city country native roots grew up"
)
_CURRENT_RESIDENCE_EXPANSION = (
    "currently lives living residence home address city country now moved to located based in"
)
_STATE_RESIDENCE_INFERENCE_EXPANSION = (
    "us state hiking trails map trail route park national park state park "
    "city county minnesota voyageurs"
)
_CURRENT_OCCUPATION_EXPANSION = (
    "current job work occupation profession role title position works as employed company"
)
_RELOCATION_DESTINATION_EXPANSION = (
    "moved to relocated to destination new city new country current home lives now settled"
)
_RU_AGE_BIRTHDAY_EXPANSION = (
    "возраст лет родился родилась дата рождения день рождения age born birthday"
)
_RU_BIRTHPLACE_EXPANSION = (
    "где родился родилась место рождения родной город страна откуда birthplace born origin hometown"
)
_RU_CURRENT_RESIDENCE_EXPANSION = (
    "где живет живёт сейчас проживает дом город страна текущий адрес "
    "lives currently residence home city"
)
_RU_CURRENT_OCCUPATION_EXPANSION = (
    "кем работает работа профессия должность роль текущая работа компания "
    "job occupation profession works as"
)
_RU_RELOCATION_DESTINATION_EXPANSION = (
    "куда переехал переехала переехали переезжает переезд новый город новая страна "
    "теперь живет живёт relocated moved destination"
)

_AGE_QUERY_RE = re.compile(r"\bhow\s+old\b", re.IGNORECASE)
_RU_AGE_QUERY_RE = re.compile(r"\bсколько\s+лет\b", re.IGNORECASE)
_CURRENT_OCCUPATION_QUERY_RE = re.compile(
    r"\b(?:what\s+(?:does|do)\s+.+?\s+do\s+for\s+work|"
    r"what\s+is\s+.+?\s+(?:job|occupation|profession)|"
    r"what\s+.+?\s+work\s+as|.+?\s+works?\s+as)\b",
    re.IGNORECASE,
)
_ORIGIN_FROM_QUERY_RE = re.compile(
    r"\bwhere\s+(?:is|are|was|were)\s+.+?\s+from\b",
    re.IGNORECASE,
)
_RU_CURRENT_OCCUPATION_QUERY_RE = re.compile(
    r"\b(?:кем\s+работа(?:ет|ют)|какая\s+работа|"
    r"что\s+.+?\s+дела(?:ет|ют)\s+по\s+работе|профессия|должность)\b",
    re.IGNORECASE,
)

PERSONAL_FACT_QUESTION_STOPWORDS = frozenset(
    {
        "Кем",
        "Куда",
    }
)

PERSONAL_FACT_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"where", "born"}),
        _BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"birthplace"}),
        _BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"origin_from_query"}),
        _BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"where", "live"}),
        _CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"where", "lives"}),
        _CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"live", "now"}),
        _CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"lives", "now"}),
        _CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"state", "live"}),
        _STATE_RESIDENCE_INFERENCE_EXPANSION,
        "state_residence_inference_bridge",
    ),
    (
        frozenset({"state", "lives"}),
        _STATE_RESIDENCE_INFERENCE_EXPANSION,
        "state_residence_inference_bridge",
    ),
    (
        frozenset({"current_occupation_query"}),
        _CURRENT_OCCUPATION_EXPANSION,
        "current_occupation_bridge",
    ),
    (
        frozenset({"where", "move", "to"}),
        _RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"where", "moved", "to"}),
        _RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"where", "moving", "to"}),
        _RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"где", "родился"}),
        _RU_BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"где", "родилась"}),
        _RU_BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"место", "рождения"}),
        _RU_BIRTHPLACE_EXPANSION,
        "birthplace_origin_bridge",
    ),
    (
        frozenset({"где", "живет"}),
        _RU_CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"где", "живёт"}),
        _RU_CURRENT_RESIDENCE_EXPANSION,
        "current_residence_bridge",
    ),
    (
        frozenset({"ru_current_occupation_query"}),
        _RU_CURRENT_OCCUPATION_EXPANSION,
        "current_occupation_bridge",
    ),
    (
        frozenset({"куда", "переехал"}),
        _RU_RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"куда", "переехала"}),
        _RU_RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"куда", "переехали"}),
        _RU_RELOCATION_DESTINATION_EXPANSION,
        "relocation_destination_bridge",
    ),
    (
        frozenset({"age_query"}),
        _AGE_BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"ru_age_query"}),
        _RU_AGE_BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"age"}),
        _AGE_BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"born"}),
        _BORN_BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"birth"}),
        _BIRTH_DATE_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"birthday"}),
        _BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"dob"}),
        "dob date of birth born birthday birth year age years old",
        "age_birthday_bridge",
    ),
    (
        frozenset({"возраст"}),
        _RU_AGE_BIRTHDAY_EXPANSION,
        "age_birthday_bridge",
    ),
    (
        frozenset({"рождения"}),
        "дата рождения день рождения родился родилась возраст лет birthday born age",
        "age_birthday_bridge",
    ),
)


def personal_fact_query_variants(query: str) -> frozenset[str]:
    variants: set[str] = set()
    if _AGE_QUERY_RE.search(query):
        variants.add("age_query")
    if _RU_AGE_QUERY_RE.search(query):
        variants.add("ru_age_query")
    if _CURRENT_OCCUPATION_QUERY_RE.search(query):
        variants.add("current_occupation_query")
    if _ORIGIN_FROM_QUERY_RE.search(query):
        variants.add("origin_from_query")
    if _RU_CURRENT_OCCUPATION_QUERY_RE.search(query):
        variants.add("ru_current_occupation_query")
    return frozenset(variants)
