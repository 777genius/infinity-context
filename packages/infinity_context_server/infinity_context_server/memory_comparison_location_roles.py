"""Question/evidence role matching for location-support rerank signals."""

from __future__ import annotations

import re


def has_location_role_grounding(
    *,
    question: str,
    memory_terms: set[str],
    memory_text: str,
) -> bool:
    requested_roles = requested_location_roles(question)
    if not requested_roles:
        return True
    evidence_roles = evidence_location_roles(memory_text, memory_terms)
    return bool(requested_roles & evidence_roles)


def has_current_location_query(question: str) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    if not normalized:
        return False
    return bool(
        re.search(
            r"\b(?:current(?:ly)?|now|these\s+days|still)\b[^?]{0,100}"
            r"\b(?:live|living|lives|reside|resides|based|home|city|location)\b|"
            r"\b(?:where|which\s+(?:city|place)|what\s+place)\b[^?]{0,80}"
            r"\b(?:live|living|lives|reside|resides|based)\b|"
            r"\b(?:live|living|lives|reside|resides|based)\b[^?]{0,80}"
            r"\b(?:where|which\s+(?:city|place)|what\s+place)\b",
            normalized,
        )
    )


def requested_location_roles(question: str) -> frozenset[str]:
    normalized = " ".join(str(question or "").casefold().split())
    if not normalized:
        return frozenset()
    roles: set[str] = set()
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated|travel|traveled|"
        r"travelled|came|come|coming)\s+from\b|"
        r"\b(?:where|which\s+(?:city|country|place))\b[^?]{0,80}\bfrom\b|"
        r"\b(?:origin|home\s+country|hometown|born|raised|childhood|"
        r"originally|grew\s+up)\b",
        normalized,
    ):
        roles.add("origin")
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated|travel|traveled|"
        r"travelled|go|went|visit|visited|stay|stayed|trip)\s+"
        r"(?:to|in|at|near|around)\b|"
        r"\bdestination\b|"
        r"\bwhere\s+did\s+\w+\s+(?:go|travel|visit|stay)\b",
        normalized,
    ):
        roles.add("destination")
    if re.search(
        r"\b(?:attend|attended|attending|concert|conference|ceremony|"
        r"reception|wedding|venue)\b|"
        r"\bwhat\s+(?:type\s+of\s+|kind\s+of\s+)?(?:place|venue)\b",
        normalized,
    ):
        roles.add("venue")
    if has_current_location_query(normalized):
        roles.add("current_location")
    if re.search(
        r"\b(?:which\s+(?:city|country|place)|what\s+place)\b[^?]{0,100}"
        r"\b(?:work|worked|working)\b|"
        r"\b(?:work|worked|working)\b[^?]{0,100}"
        r"\b(?:which\s+(?:city|country|place)|what\s+place)\b",
        normalized,
    ):
        roles.add("workplace_location")
    return frozenset(roles)


def evidence_location_roles(memory_text: str, memory_terms: set[str]) -> frozenset[str]:
    text = str(memory_text or "")
    normalized = " ".join(text.casefold().split())
    roles: set[str] = set()
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated|came|come|coming|"
        r"travel|traveled|travelled)\s+from\b|"
        r"\b(?:from|origin|originally)\s+(?:my\s+|his\s+|her\s+|their\s+|"
        r"our\s+)?(?:home|hometown|country|city)\b|"
        r"\b(?:home\s+country|hometown|born|raised|grew\s+up|"
        r"originally\s+from)\b",
        normalized,
    ):
        roles.add("origin")
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated|travel|traveled|"
        r"travelled|went|go|visit|visited|stay|stayed|trip)\s+"
        r"(?:to|in|at|near|around)\b|"
        r"\b(?:destination|settled\s+in|ended\s+up\s+in)\b",
        normalized,
    ):
        roles.add("destination")
    if _has_event_venue_role(normalized, text, memory_terms):
        roles.add("venue")
    if re.search(
        r"\b(?:currently|current|now|these\s+days|still|today|lately)\b"
        r".{0,120}\b(?:live|living|lives|reside|resides|based|home|city|"
        r"location)\b|"
        r"\b(?:live|living|lives|reside|resides|based)\b.{0,120}"
        r"\b(?:currently|current|now|these\s+days|still|today|lately)\b",
        normalized,
    ) and not re.search(
        r"\b(?:used\s+to|formerly|previously|no\s+longer)\b",
        normalized,
    ):
        roles.add("current_location")
    if re.search(
        r"\b(?:work|worked|working|workplace|office)\b",
        normalized,
    ) and _has_place_surface(text, memory_terms):
        roles.add("workplace_location")
    return frozenset(roles)


def _has_event_venue_role(
    normalized: str,
    memory_text: str,
    memory_terms: set[str],
) -> bool:
    if not re.search(
        r"\b(?:attend|attended|attending|concert|conference|ceremony|"
        r"reception|wedding|venue)\b",
        normalized,
    ):
        return False
    return bool(
        (
            re.search(r"\b(?:at|in)\b", normalized)
            or re.search(
                r"\b(?:choose|chose|chosen|pick|picked|select|selected)\b",
                normalized,
            )
        )
        and _has_place_surface(memory_text, memory_terms)
    )


def _has_place_surface(memory_text: str, memory_terms: set[str]) -> bool:
    if {
        "city",
        "country",
        "place",
        "location",
        "office",
        "company",
        "studio",
        "gallery",
        "museum",
        "theater",
        "theatre",
        "venue",
        "barn",
        "hall",
        "hotel",
        "campground",
        "campsite",
    } & set(memory_terms):
        return True
    return bool(re.search(r"\b(?:in|at|near|around)\s+[A-Z][a-zA-Z]+", memory_text))
