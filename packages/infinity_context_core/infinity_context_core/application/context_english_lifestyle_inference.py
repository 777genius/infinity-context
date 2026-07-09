"""English lifestyle-inference answer evidence patterns."""

from __future__ import annotations

import re

_INDOOR_PET_ACTIVITY_QUERY_RE = re.compile(
    r"\bindoor\b(?=.{0,160}\b(?:activit(?:y|ies)|hobb(?:y|ies)|enjoy|do)\b)"
    r"(?=.{0,200}\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b)|"
    r"\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b"
    r"(?=.{0,200}\bindoor\b)"
    r"(?=.{0,200}\b(?:happy|enjoy|activit(?:y|ies)|hobb(?:y|ies))\b)",
    re.IGNORECASE | re.DOTALL,
)
_STRESS_LIVING_OUTDOOR_QUERY_RE = re.compile(
    r"\b(?:stress|stressful|improve|balance|accommodat(?:e|ing)|living\s+situation)\b"
    r"(?=.{0,220}\b(?:dogs?|pupp(?:y|ies)|pups?|pets?|city|living|"
    r"outdoors?|nature|hike|open\s+spaces?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ANIMAL_NATURE_CAREER_QUERY_RE = re.compile(
    r"\bcareer\b(?=.{0,220}\b(?:animals?|dogs?|pupp(?:y|ies)|pups?|pets?)\b)"
    r"(?=.{0,220}\bnature\b)|"
    r"\b(?:animals?|dogs?|pupp(?:y|ies)|pups?|pets?)\b"
    r"(?=.{0,220}\bnature\b)"
    r"(?=.{0,220}\b(?:career|potentially|inference|support(?:ing)?|evidence|"
    r"love|affinity|preference)\b)",
    re.IGNORECASE | re.DOTALL,
)

_INDOOR_CREATIVE_ACTIVITY_RE = re.compile(
    r"\b(?:cook(?:ing)?|baking?|recipes?)\b"
    r"(?=.{0,220}\b(?:new\s+hobb(?:y|ies)|hobb(?:y|ies)|enjoy(?:able)?|"
    r"creative|de-?stress|stress|can't\s+hike|cannot\s+hike|not\s+able\s+to\s+hike)\b)|"
    r"\b(?:new\s+hobb(?:y|ies)|hobb(?:y|ies)|enjoy(?:able)?|creative|de-?stress)\b"
    r"(?=.{0,220}\b(?:cook(?:ing)?|baking?|recipes?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PET_COMPANION_CONTEXT_RE = re.compile(
    r"\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b"
    r"(?=.{0,180}\b(?:joy|happy|adopt(?:ed|ion)?|take(?:n)?\s+home|"
    r"new\s+addition|city\s+living|cuddl(?:e|ing)|bring(?:ing)?\s+"
    r"(?:a\s+lot\s+of\s+)?joy)\b)|"
    r"\b(?:adopt(?:ed|ion)?|new\s+addition|take(?:n)?\s+home)\b"
    r"(?=.{0,180}\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_WORK_STRESS_OUTDOOR_RE = re.compile(
    r"\b(?:work(?:'s|ing)?|job|work[-\s]?life)\b"
    r"(?=.{0,240}\b(?:stress(?:ful|ed)?|piling\s+up|tough|backseat|"
    r"stuck\s+inside|balance|challenging)\b)"
    r"(?=.{0,280}\b(?:hike|hiking|outdoors?|nature|peace|freedom)\b)|"
    r"\b(?:stress(?:ful|ed)?|piling\s+up|tough|backseat|stuck\s+inside|"
    r"balance|challenging)\b"
    r"(?=.{0,260}\b(?:hike|hiking|outdoors?|nature|peace|freedom)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CITY_OUTDOOR_SPACE_RE = re.compile(
    r"\b(?:city|living\s+here|open\s+spaces?|work[-\s]?life\s+balance)\b"
    r"(?=.{0,260}\b(?:hike|hiking|outdoors?|nature|beach|park|woods|"
    r"peace|freedom|challenging)\b)|"
    r"\b(?:hike|hiking|outdoors?|nature|beach|park|woods)\b"
    r"(?=.{0,260}\b(?:city|open\s+spaces?|work[-\s]?life\s+balance)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ANIMAL_NATURE_AFFINITY_RE = re.compile(
    r"\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b"
    r"(?=.{0,260}\b(?:nature|hiking|trails?|park|woods?|open\s+space|"
    r"outdoors?)\b)|"
    r"\b(?:nature|hiking|trails?|park|woods?|open\s+space|outdoors?)\b"
    r"(?=.{0,260}\b(?:dogs?|pupp(?:y|ies)|pups?|pets?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CITY_NATURE_AFFINITY_RE = re.compile(
    r"\b(?:city|cafe)\b"
    r"(?=.{0,260}\b(?:nature|outdoors?|thriv(?:e|ing)|miss|sad|park|woods?)\b)|"
    r"\b(?:refresh(?:ing)?|reset|different\s+outlook|peaceful|freedom)\b"
    r"(?=.{0,220}\bnature\b)|"
    r"\bnature\b"
    r"(?=.{0,220}\b(?:refresh(?:ing)?|reset|different\s+outlook|peaceful|freedom)\b)",
    re.IGNORECASE | re.DOTALL,
)


def english_lifestyle_query_kind(query: str) -> str:
    if _INDOOR_PET_ACTIVITY_QUERY_RE.search(query) is not None:
        return "indoor_pet_activity"
    if _STRESS_LIVING_OUTDOOR_QUERY_RE.search(query) is not None:
        return "stress_living_outdoor"
    if _ANIMAL_NATURE_CAREER_QUERY_RE.search(query) is not None:
        return "animal_nature_career"
    return ""


def english_lifestyle_answer_slot_and_rank(
    text: str,
    *,
    query: str = "",
    query_kind: str = "",
) -> tuple[str, int]:
    kind = query_kind or english_lifestyle_query_kind(query)
    if kind == "indoor_pet_activity":
        if _INDOOR_CREATIVE_ACTIVITY_RE.search(text) is not None:
            return ("indoor_activity", 0)
        if _PET_COMPANION_CONTEXT_RE.search(text) is not None:
            return ("pet_context", 0)
    if kind == "stress_living_outdoor":
        if _WORK_STRESS_OUTDOOR_RE.search(text) is not None:
            return ("work_stress_outdoor", 0)
        if _CITY_OUTDOOR_SPACE_RE.search(text) is not None:
            return ("city_outdoor_space", 0)
    if kind == "animal_nature_career":
        if _ANIMAL_NATURE_AFFINITY_RE.search(text) is not None:
            return ("animal_nature_affinity", 0)
        if _CITY_NATURE_AFFINITY_RE.search(text) is not None:
            return ("nature_affinity", 0)
    return ("", 5)


def english_lifestyle_answer_support_rank(text: str, *, query: str) -> int:
    _, rank = english_lifestyle_answer_slot_and_rank(text, query=query)
    return rank
