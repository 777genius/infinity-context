"""English evidence rules for travel-related creative-writing hobby suggestions."""

from __future__ import annotations

import re

TRAVEL_HOBBY_WRITING_REASON = "travel_hobby_writing_bridge"

_TRAVEL_HOBBY_QUERY_RE = re.compile(
    r"\b(?:hobby|hobbies|pastime|activity|interest|creative)\b"
    r"(?=.{0,180}\b(?:travel|travels|traveling|travelling|trip|trips|"
    r"dreams?|destinations?|places?|visit(?:ing)?)\b)|"
    r"\b(?:travel|travels|traveling|travelling|trip|trips|dreams?|"
    r"destinations?|places?|visit(?:ing)?)\b"
    r"(?=.{0,180}\b(?:hobby|hobbies|pastime|activity|interest|creative)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WRITING_EVIDENCE_RE = re.compile(
    r"\b(?:writing|write|writes|wrote|written)\b"
    r"(?=.{0,220}\b(?:articles?|blog(?:ging)?|posts?|stories?|novels?|"
    r"books?|mag(?:azine)?|reading|sharing|creative|creativity|rewarding|joy)\b)|"
    r"\b(?:articles?|blog(?:ging)?|blog\s+posts?|stories?|novels?|books?|"
    r"mag(?:azine)?)\b"
    r"(?=.{0,220}\b(?:writing|write|writes|wrote|written|reading|sharing|"
    r"creative|creativity|rewarding|joy)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NON_CREATIVE_WRITING_RE = re.compile(
    r"\bwrite\s+it\s+down\b|"
    r"\brecipe\b(?=.{0,120}\b(?:write|mail|send|share|sharing)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STRONG_CREATIVE_WRITING_RE = re.compile(
    r"\b(?:writing|write|writes|wrote|written)\b"
    r"(?=.{0,180}\b(?:articles?|blog(?:ging)?|posts?|online\s+mag|"
    r"mag(?:azine)?|sharing\s+(?:great\s+)?stories|stories?)\b)|"
    r"\b(?:articles?|blog(?:ging)?|blog\s+posts?|online\s+mag|mag(?:azine)?|"
    r"sharing\s+(?:great\s+)?stories|stories?)\b"
    r"(?=.{0,180}\b(?:writing|write|writes|wrote|written|reading|sharing)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WRITING_PUBLICATION_RE = re.compile(
    r"\b(?:writing|write|writes|wrote|written)\b"
    r"(?=.{0,180}\b(?:blog(?:ging)?|blog\s+posts?|posts?|"
    r"online\s+mag|mag(?:azine)?|newsletter|publication|published|"
    r"forum|column)\b)|"
    r"\b(?:blog(?:ging)?|blog\s+posts?|posts?|online\s+mag|"
    r"mag(?:azine)?|newsletter|publication|published|forum|column)\b"
    r"(?=.{0,180}\b(?:writing|write|writes|wrote|written)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_WRITING_STORY_SHARING_RE = re.compile(
    r"\b(?:writing|write|writes|wrote|written)\b"
    r"(?=.{0,220}\b(?:sharing\s+(?:great\s+)?stories|storytelling|"
    r"stories?|combine(?:s|d)?\s+(?:my|their|his|her)?\s*love\s+"
    r"for\s+reading|love\s+for\s+reading)\b)|"
    r"\b(?:sharing\s+(?:great\s+)?stories|storytelling|stories?|"
    r"combine(?:s|d)?\s+(?:my|their|his|her)?\s*love\s+for\s+reading|"
    r"love\s+for\s+reading)\b"
    r"(?=.{0,220}\b(?:writing|write|writes|wrote|written|articles?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRAVEL_INTEREST_EVIDENCE_RE = re.compile(
    r"\b(?:love|loves|enjoy|enjoys|interest(?:ed)?|dreams?|hope|hopes|want|"
    r"wants|wish|wishes|plan|plans|planning|can'?t\s+wait|joined|join(?:ed)?)\b"
    r"(?=.{0,240}\b(?:travel|traveling|travelling|trips?|journey|journeys|"
    r"destinations?|places?|countries|cities|visit(?:ed|ing)?|globetrotters?|"
    r"road\s+trips?|landmarks?|tower|castle)\b)|"
    r"\b(?:travel|traveling|travelling|trips?|journey|journeys|destinations?|"
    r"places?|countries|cities|visit(?:ed|ing)?|globetrotters?|road\s+trips?|"
    r"landmarks?|tower|castle)\b"
    r"(?=.{0,240}\b(?:love|loves|enjoy|enjoys|interest(?:ed)?|dreams?|hope|"
    r"hopes|want|wants|wish|wishes|plan|plans|planning|can'?t\s+wait|"
    r"joined|join(?:ed)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRAVEL_AFFECTIVE_RE = re.compile(
    r"\b(?:love|loves|enjoy|enjoys|interest(?:ed)?|can'?t\s+wait|hope|hopes)\b"
    r"(?=.{0,220}\b(?:travel|traveling|travelling|trips?|journey|destinations?|"
    r"places?|countries|cities|visit(?:ed|ing)?|landmarks?|tower|castle)\b)|"
    r"\b(?:travel|traveling|travelling|trips?|journey|destinations?|places?|"
    r"countries|cities|visit(?:ed|ing)?|landmarks?|tower|castle)\b"
    r"(?=.{0,220}\b(?:love|loves|enjoy|enjoys|interest(?:ed)?|can'?t\s+wait|"
    r"hope|hopes)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRAVEL_PLACE_DETAIL_RE = re.compile(
    r"\b(?:been|go|going|went|travel(?:ed|led|ing)?|visit(?:ed|ing)?)\s+"
    r"(?:to|in|through|around|near)\s+(?:the\s+)?(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:tower|castle|landmark|city|cities|countries|destinations?|places?)\b",
    re.IGNORECASE | re.DOTALL,
)
_TRAVEL_LOGISTICS_RE = re.compile(
    r"\b(?:requirements?|visa|visas|travel\s+agency|agency|paperwork|"
    r"application|applications)\b",
    re.IGNORECASE,
)


def is_travel_hobby_writing_query(*, expansion_query: str, expansion_reason: str) -> bool:
    """Return true when a query asks for a travel-related hobby recommendation."""

    return (
        expansion_reason == TRAVEL_HOBBY_WRITING_REASON
        or _TRAVEL_HOBBY_QUERY_RE.search(expansion_query) is not None
    )


def travel_hobby_writing_answer_slot(text: str) -> str:
    """Return the evidence facet supplied by a travel-hobby writing turn."""

    has_writing = (
        _CREATIVE_WRITING_EVIDENCE_RE.search(text) is not None
        and not (
            _NON_CREATIVE_WRITING_RE.search(text) is not None
            and _STRONG_CREATIVE_WRITING_RE.search(text) is None
        )
    )
    has_travel = _TRAVEL_INTEREST_EVIDENCE_RE.search(text) is not None
    if has_writing and has_travel:
        return "travel_writing_overlap"
    if (
        has_travel
        and _TRAVEL_AFFECTIVE_RE.search(text) is not None
        and _TRAVEL_PLACE_DETAIL_RE.search(text) is not None
    ):
        return "travel_place_interest"
    if has_writing:
        if _CREATIVE_WRITING_PUBLICATION_RE.search(text) is not None:
            return "creative_writing_publication"
        if _CREATIVE_WRITING_STORY_SHARING_RE.search(text) is not None:
            return "creative_writing_story_sharing"
        return "creative_writing"
    if has_travel:
        return "travel_interest"
    return ""


def travel_hobby_writing_answer_rank(text: str) -> int:
    """Return directness rank for travel-hobby writing support evidence."""

    slot = travel_hobby_writing_answer_slot(text)
    if slot == "travel_writing_overlap":
        return 0
    if slot in {"creative_writing_publication", "creative_writing_story_sharing"}:
        return 0
    if slot == "creative_writing":
        if _STRONG_CREATIVE_WRITING_RE.search(text) is not None:
            return 0
        return 1
    if slot == "travel_place_interest":
        return 0
    if slot == "travel_interest":
        if (
            _TRAVEL_AFFECTIVE_RE.search(text) is not None
            and _TRAVEL_PLACE_DETAIL_RE.search(text) is not None
        ):
            return 0
        if _TRAVEL_LOGISTICS_RE.search(text) is not None:
            return 3
        return 1
    return 5


def is_travel_hobby_writing_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    """Return true when a turn supplies one facet of a travel-writing hobby fit."""

    return is_travel_hobby_writing_query(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ) and bool(travel_hobby_writing_answer_slot(text))
