"""English place-inference source-sibling evidence rules."""

from __future__ import annotations

import re

from infinity_context_core.application.context_english_temporal_dates import (
    english_textual_month_year_terms,
)

_COUNTRY_LEVEL_PLACE_NAMES = (
    "afghanistan",
    "albania",
    "algeria",
    "andorra",
    "angola",
    "argentina",
    "armenia",
    "australia",
    "austria",
    "azerbaijan",
    "bahamas",
    "bahrain",
    "bangladesh",
    "barbados",
    "belarus",
    "belgium",
    "belize",
    "benin",
    "bhutan",
    "bolivia",
    "bosnia",
    "botswana",
    "brazil",
    "britain",
    "brunei",
    "bulgaria",
    "burkina faso",
    "burundi",
    "cambodia",
    "cameroon",
    "canada",
    "chad",
    "chile",
    "china",
    "colombia",
    "comoros",
    "congo",
    "costa rica",
    "croatia",
    "cuba",
    "cyprus",
    "czechia",
    "denmark",
    "djibouti",
    "dominica",
    "dominican republic",
    "ecuador",
    "egypt",
    "england",
    "eritrea",
    "estonia",
    "eswatini",
    "ethiopia",
    "fiji",
    "finland",
    "france",
    "gabon",
    "gambia",
    "georgia",
    "germany",
    "ghana",
    "greece",
    "grenada",
    "guatemala",
    "guinea",
    "guyana",
    "haiti",
    "honduras",
    "hungary",
    "iceland",
    "india",
    "indonesia",
    "iran",
    "iraq",
    "ireland",
    "israel",
    "italy",
    "jamaica",
    "japan",
    "jordan",
    "kazakhstan",
    "kenya",
    "kiribati",
    "kosovo",
    "kuwait",
    "kyrgyzstan",
    "laos",
    "latvia",
    "lebanon",
    "lesotho",
    "liberia",
    "libya",
    "liechtenstein",
    "lithuania",
    "luxembourg",
    "madagascar",
    "malawi",
    "malaysia",
    "maldives",
    "mali",
    "malta",
    "mauritania",
    "mauritius",
    "mexico",
    "micronesia",
    "moldova",
    "monaco",
    "mongolia",
    "montenegro",
    "morocco",
    "mozambique",
    "myanmar",
    "namibia",
    "nauru",
    "nepal",
    "netherlands",
    "new zealand",
    "nicaragua",
    "niger",
    "nigeria",
    "north korea",
    "north macedonia",
    "northern ireland",
    "norway",
    "oman",
    "pakistan",
    "palau",
    "panama",
    "paraguay",
    "peru",
    "philippines",
    "poland",
    "portugal",
    "qatar",
    "romania",
    "russia",
    "rwanda",
    "samoa",
    "san marino",
    "saudi arabia",
    "scotland",
    "senegal",
    "serbia",
    "seychelles",
    "singapore",
    "slovakia",
    "slovenia",
    "somalia",
    "south africa",
    "south korea",
    "spain",
    "sri lanka",
    "sudan",
    "suriname",
    "sweden",
    "switzerland",
    "syria",
    "taiwan",
    "tajikistan",
    "tanzania",
    "thailand",
    "togo",
    "tonga",
    "tunisia",
    "turkey",
    "turkmenistan",
    "tuvalu",
    "uganda",
    "ukraine",
    "united kingdom",
    "united states",
    "uruguay",
    "usa",
    "uzbekistan",
    "vanuatu",
    "vatican",
    "venezuela",
    "vietnam",
    "wales",
    "yemen",
    "zambia",
    "zimbabwe",
)
_COUNTRY_LEVEL_PLACE_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(name).replace(r"\ ", r"\s+") for name in _COUNTRY_LEVEL_PLACE_NAMES)
    + r")\b",
    re.IGNORECASE,
)
_COUNTRY_INVENTORY_QUERY_RE = re.compile(
    r"\b(?:countries|european\s+countries)\b",
    re.IGNORECASE,
)
_GEO_PLACE_QUERY_RE = re.compile(
    r"\bnational\s+parks?\b|"
    r"\b(?:countries|country|states?|national\s+parks?|parks?)\b"
    r"(?=.{0,180}\b(?:visit(?:ed|ing)?|went|gone|been|travel(?:ed|led|ing)?|"
    r"trip|vacation(?:ed)?|during|internship|summer|semester|which|what)\b)|"
    r"\b(?:visit(?:ed|ing)?|went|gone|been|travel(?:ed|led|ing)?|trip|"
    r"vacation(?:ed)?|during|internship|summer|semester)\b"
    r"(?=.{0,180}\b(?:countries|country|states?|national\s+parks?|parks?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_PLACE = r"(?:the\s+)?(?-i:[A-Z])[A-Za-z' .-]{2,80}"
_REALIZED_NAMED_PLACE_RE = re.compile(
    r"\b(?:on\s+)?vacation\b(?=.{0,180}\b(?:in|at|near|on|to)\s+"
    + _NAMED_PLACE
    + r"\b)|"
    r"\b(?:picture|photo|pic|image|snapshot)\b"
    r"(?=.{0,180}\b(?:in|at|near|on|to)\s+"
    + _NAMED_PLACE
    + r"\b)"
    r"(?=.{0,220}\b(?:vacation|trip|travel|visited|went|summer|"
    r"last\s+summer)\b)|"
    r"\b(?:visited|visit(?:ed|ing)?|went|gone|travel(?:ed|led|ing)?|"
    r"vacationed|stayed|spent)\b"
    r"(?=.{0,180}\b(?:to|in|through|around|at|near|on)\s+"
    + _NAMED_PLACE
    + r"\b)",
    re.IGNORECASE | re.DOTALL,
)
_LANDMARK_PLACE_RE = re.compile(
    r"\b(?:photo|picture|pic|image|caption|visual|yoga|hiking|spent|visit|"
    r"trip|travel|vacation|internship|morning)\b"
    r"(?=.{0,220}\b(?:on\s+top\s+of|at|near|by|on)\s+"
    r"(?i:mount|mt\.?|mountain)\s+"
    + _NAMED_PLACE
    + r"\b)|"
    r"\b(?:on\s+top\s+of|at|near|by|on)\s+"
    r"(?i:mount|mt\.?|mountain)\s+"
    + _NAMED_PLACE
    + r"\b"
    r"(?=.{0,220}\b(?:photo|picture|pic|image|caption|visual|yoga|hiking|"
    r"spent|visit|trip|travel|vacation|internship|morning)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MAP_TRAIL_PLACE_QUERY_RE = re.compile(
    r"\b(?:which|what)\b(?=.{0,120}\b(?:national\s+parks?|parks?|places?|"
    r"locations?)\b)|"
    r"\b(?:national\s+parks?|parks?)\b",
    re.IGNORECASE | re.DOTALL,
)
_MAP_TRAIL_PLACE_RE = re.compile(
    r"\bmap\b(?=.{0,220}\b(?:trails?|hiking|parks?)\b)|"
    r"\b(?:trails?|hiking|parks?)\b(?=.{0,220}\bmap\b)",
    re.IGNORECASE | re.DOTALL,
)
_THEMED_LOCATION_QUERY_RE = re.compile(
    r"\b(?:locations?|places?)\b(?=.{0,180}\b(?:would|enjoy|visit|"
    r"related|recommend|interested)\b)|"
    r"\b(?:would|enjoy|visit|related|recommend|interested)\b"
    r"(?=.{0,180}\b(?:locations?|places?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_THEMED_LOCATION_EXPERIENCE_RE = re.compile(
    r"\b(?:place|places|locations?|tour|trip|visit(?:ed|ing)?|went)\b"
    r"(?=.{0,260}\b(?:movie|film|book|fantasy|fiction|universe|world|"
    r"real\s+\w+\s+places?)\b)"
    r"(?=.{0,260}\b(?:amazing|love|loved|enjoy|enjoyed|like|liked|"
    r"explore|explored|visit|visited|walking\s+into)\b)|"
    r"\b(?:movie|film|book|fantasy|fiction|universe|world|"
    r"real\s+\w+\s+places?)\b"
    r"(?=.{0,260}\b(?:place|places|locations?|tour|trip|visit(?:ed|ing)?|went)\b)"
    r"(?=.{0,260}\b(?:amazing|love|loved|enjoy|enjoyed|like|liked|"
    r"explore|explored|visit|visited|walking\s+into)\b)",
    re.IGNORECASE | re.DOTALL,
)
_QUERY_DESTINATION_PLACE_RE = re.compile(
    r"\b(?:to|in|at|near)\s+"
    r"(?P<place>(?-i:[A-Z])[A-Za-z'-]{2,40}"
    r"(?:\s+(?-i:[A-Z])[A-Za-z'-]{2,40}){0,3})\b",
    re.IGNORECASE,
)
_QUERY_DESTINATION_PLACE_STOPWORDS = frozenset(
    {
        "April",
        "August",
        "December",
        "February",
        "Friday",
        "January",
        "July",
        "June",
        "March",
        "May",
        "Monday",
        "November",
        "October",
        "Saturday",
        "September",
        "Sunday",
        "Thursday",
        "Tuesday",
        "Wednesday",
    }
)
_QUERY_DESTINATION_REASON_SCOPE = frozenset(
    {
        "decomposition-inference-support",
        "original-query",
        "place-area-inventory-bridge",
        "themed-location-destination-anchor-bridge",
        "themed-location-destination-bridge",
        "travel-country-inventory-bridge",
        "trip-destination-bridge",
    }
)
_DESTINATION_QUERY_INTENT_RE = re.compile(
    r"\b(?:where|during|visit|visiting|travel|trip|stay|staying|study\s+abroad|"
    r"semester|locations?|places?|recommend|enjoy|attend(?:ed|ing)?|"
    r"concert|conference|event|venue|ceremony|reception|workshop)\b",
    re.IGNORECASE,
)
_DESTINATION_ANCHOR_TEXT_RE = re.compile(
    r"\b(?:visit(?:ed|ing)?|travel(?:ed|led|ing)|trip|stay(?:ed|ing)?|"
    r"study\s+abroad|semester|off\s+to|going\s+to|headed\s+to|accepted\s+"
    r"(?:into|to)|applied\s+for|live\s+in|living\s+in|moved\s+to|"
    r"attend(?:ed|ing)?|concert|conference|event|venue|ceremony|reception|"
    r"workshop)\b|"
    r"\btravel(?:ed|led|ing)\b",
    re.IGNORECASE,
)
_COUNTRY_DESTINATION_QUERY_RE = re.compile(
    r"\b(?:which|what)\b(?=.{0,160}\bcountry\b)"
    r"(?=.{0,220}\b(?:meet|meeting|met|see|visit(?:ed|ing)?|trip|"
    r"travel(?:ed|led|ing)?|go|going|show|tour(?:ed|ing)?|"
    r"stay(?:ed|ing)?)\b)|"
    r"\bcountry\b(?=.{0,220}\b(?:meet|meeting|met|see|visit(?:ed|ing)?|trip|"
    r"travel(?:ed|led|ing)?|go|going|show|tour(?:ed|ing)?|"
    r"stay(?:ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COUNTRY_DESTINATION_MEETING_QUERY_RE = re.compile(
    r"\b(?:meet|meeting|met|see)\b",
    re.IGNORECASE,
)
_COUNTRY_DESTINATION_CITY_EVIDENCE_RE = re.compile(
    r"\b(?:upcoming\s+trip|road\s+trip|roadtrip|trip|visit(?:ed|ing)?|"
    r"travel(?:ed|led|ing)?|flight|going|headed|heading|off|come|coming)\b"
    r"(?=.{0,180}\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b)|"
    r"\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b"
    r"(?=.{0,180}\b(?:trip|flight|"
    r"show\s+(?:you|him|her|them)\s+around|around\s+town|"
    r"music\s+scene|can'?t\s+wait|see\s+you)\b)|"
    r"\bshow\s+(?:you|him|her|them)\s+around\b"
    r"(?=.{0,220}\b(?:city|town|places?|spots?|scene)\b)"
    r"(?=.{0,220}\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b)",
    re.IGNORECASE | re.DOTALL,
)
_COUNTRY_DESTINATION_MEETING_CITY_EVIDENCE_RE = re.compile(
    r"\b(?:upcoming\s+trip|road\s+trip|roadtrip|trip|flight|going|headed|"
    r"heading|off|come|coming)\b"
    r"(?=.{0,180}\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b)|"
    r"\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b"
    r"(?=.{0,180}\b(?:trip|flight|"
    r"show\s+(?:you|him|her|them)\s+around|around\s+town|"
    r"music\s+scene|can'?t\s+wait|see\s+you)\b)|"
    r"\bshow\s+(?:you|him|her|them)\s+around\b"
    r"(?=.{0,220}\b(?:city|town|places?|spots?|scene)\b)"
    r"(?=.{0,220}\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b)",
    re.IGNORECASE | re.DOTALL,
)
_COUNTRY_DESTINATION_MUTUAL_EVIDENCE_RE = re.compile(
    r"\b(?:can'?t\s+wait\s+for\s+your\s+trip|your\s+trip\s+to|"
    r"show\s+(?:you|him|her|them)\s+around|around\s+town|"
    r"show\s+(?:you|him|her|them)\s+all\s+the\s+cool\s+spots)\b",
    re.IGNORECASE | re.DOTALL,
)
_COUNTRY_DESTINATION_TRIP_ANCHOR_RE = re.compile(
    r"\b(?:upcoming\s+trip|road\s+trip|roadtrip|trip)\b"
    r"(?=.{0,180}\b(?:to|in|around)\s+"
    + _NAMED_PLACE
    + r"\b)",
    re.IGNORECASE | re.DOTALL,
)


def is_place_inference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    """Return true when a turn supplies direct place evidence for geo inference."""

    query_matches_place = _GEO_PLACE_QUERY_RE.search(expansion_query) is not None
    if not query_matches_place:
        return False
    if (
        _MAP_TRAIL_PLACE_QUERY_RE.search(expansion_query) is not None
        and _MAP_TRAIL_PLACE_RE.search(text) is not None
    ):
        return True
    if _COUNTRY_INVENTORY_QUERY_RE.search(expansion_query) is not None:
        return (
            _COUNTRY_LEVEL_PLACE_RE.search(text) is not None
            and _REALIZED_NAMED_PLACE_RE.search(text) is not None
        )
    return (
        _REALIZED_NAMED_PLACE_RE.search(text) is not None
        or _LANDMARK_PLACE_RE.search(text) is not None
    )


def is_country_inventory_place_inference_query(expansion_query: str) -> bool:
    """Return true for list-shaped country inventory questions."""

    return _COUNTRY_INVENTORY_QUERY_RE.search(expansion_query) is not None


def is_themed_location_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    """Return true for fandom/story-world place experience evidence."""

    _ = expansion_reason
    return (
        _THEMED_LOCATION_QUERY_RE.search(expansion_query) is not None
        and _THEMED_LOCATION_EXPERIENCE_RE.search(text) is not None
    )


def is_query_destination_source_sibling_anchor(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    """Return true when a turn anchors the destination named by a place query."""

    if (
        expansion_reason.replace("_", "-") not in _QUERY_DESTINATION_REASON_SCOPE
        or _DESTINATION_QUERY_INTENT_RE.search(expansion_query) is None
        or _DESTINATION_ANCHOR_TEXT_RE.search(text) is None
    ):
        return False
    text_folded = text.casefold()
    return any(
        place.casefold() in text_folded for place in query_destination_places(expansion_query)
    )


def is_country_destination_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    """Return true when a country answer is implied by city-level destination evidence."""

    _ = expansion_reason
    evidence_re = (
        _COUNTRY_DESTINATION_MEETING_CITY_EVIDENCE_RE
        if _COUNTRY_DESTINATION_MEETING_QUERY_RE.search(expansion_query) is not None
        else _COUNTRY_DESTINATION_CITY_EVIDENCE_RE
    )
    return (
        _COUNTRY_DESTINATION_QUERY_RE.search(expansion_query) is not None
        and evidence_re.search(text) is not None
    )


def country_destination_answer_support_rank(
    *,
    expansion_query: str,
    text: str,
    has_exact_turn: bool,
) -> int:
    """Return directness rank for city-level evidence answering a country question."""

    if _COUNTRY_DESTINATION_QUERY_RE.search(expansion_query) is None:
        return 5
    evidence_re = (
        _COUNTRY_DESTINATION_MEETING_CITY_EVIDENCE_RE
        if _COUNTRY_DESTINATION_MEETING_QUERY_RE.search(expansion_query) is not None
        else _COUNTRY_DESTINATION_CITY_EVIDENCE_RE
    )
    temporal_rank = _country_destination_temporal_alignment_rank(
        expansion_query=expansion_query,
        text=text,
    )
    base_rank = 5
    if _COUNTRY_DESTINATION_MUTUAL_EVIDENCE_RE.search(text) is not None:
        base_rank = 0
    elif _COUNTRY_DESTINATION_TRIP_ANCHOR_RE.search(text) is not None:
        base_rank = 1
    elif evidence_re.search(text) is not None:
        base_rank = 2 if has_exact_turn else 3
    if base_rank >= 5:
        return 5
    if temporal_rank == 0:
        return max(0, base_rank - 1)
    if temporal_rank == 2:
        return min(4, base_rank + 3)
    return base_rank


def _country_destination_temporal_alignment_rank(
    *,
    expansion_query: str,
    text: str,
) -> int:
    query_terms = set(english_textual_month_year_terms(expansion_query))
    if not query_terms:
        return 1
    text_terms = set(english_textual_month_year_terms(text))
    if not text_terms:
        return 1
    if query_terms.intersection(text_terms):
        return 0
    return 2


def query_destination_places(query: str) -> tuple[str, ...]:
    places: list[str] = []
    seen: set[str] = set()
    for match in _QUERY_DESTINATION_PLACE_RE.finditer(query):
        place = " ".join(match.group("place").split()).strip(" ,.;:!?")
        if not place or place in _QUERY_DESTINATION_PLACE_STOPWORDS:
            continue
        key = place.casefold()
        if key in seen:
            continue
        seen.add(key)
        places.append(place)
    if _DESTINATION_QUERY_INTENT_RE.search(query) is not None:
        query_folded = query.casefold()
        for place in _COUNTRY_LEVEL_PLACE_NAMES:
            if place in seen:
                continue
            if re.search(rf"\b{re.escape(place)}\b", query_folded) is None:
                continue
            seen.add(place)
            places.append(place)
    return tuple(places)
