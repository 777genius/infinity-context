"""Benchmark-owned profile patterns policy."""

from __future__ import annotations

import re
from collections.abc import Sequence

from infinity_context_benchmarks.retrieval_intent.contracts import RetrievalTimeIntent


def _is_kinship_status_lookup(
    question: str,
    relation_terms: Sequence[str],
) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    if not re.search(r"\bwho\s+(?:are|were)\b", normalized):
        return False
    if re.search(r"\b(?:list|names?|items?)\b", normalized):
        return False
    return bool(
        {
            "brother",
            "child",
            "children",
            "cousin",
            "daughter",
            "father",
            "grandfather",
            "grandmother",
            "husband",
            "kid",
            "mother",
            "parent",
            "sibling",
            "sister",
            "son",
            "spouse",
            "wife",
        }
        & set(relation_terms)
    )


def _has_activity_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {"activity", "exercise", "hobby", "sport"} & relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bsports?\s+(?:team|score|game|match|event)\b", normalized_question):
        return False
    if "activity" in relation_set and not {"exercise", "hobby", "sport"} & relation_set:
        return bool(
            re.search(
                r"\b(?:hobby|hobbies|pastime|free\s+time|for\s+fun)\b|"
                r"\bwhat\b.+\b(?:do|does)\b.+\b(?:for\s+fun|free\s+time|relax)\b|"
                r"\b(?:exercise|workout)\b",
                normalized_question,
            )
        )
    return bool(
        re.search(
            r"\b(?:what|which)\s+(?:activity|activities|hobby|hobbies|sport|sports)\b|"
            r"\b(?:hobby|hobbies|pastime|free\s+time|for\s+fun)\b|"
            r"\bwhat\b.+\b(?:do|does)\b.+\b(?:for\s+fun|free\s+time|relax)\b|"
            r"\b(?:exercise|workout)\b",
            normalized_question,
        )
    )


def _has_status_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> bool:
    relation_set = set(relation_terms)
    status_terms = {
        "boyfriend",
        "boss",
        "brother",
        "child",
        "children",
        "colleague",
        "cousin",
        "coworker",
        "dating",
        "daughter",
        "engag",
        "engaged",
        "family",
        "father",
        "fiance",
        "fiancee",
        "friend",
        "girlfriend",
        "grandfather",
        "grandmother",
        "husband",
        "manager",
        "member",
        "mentor",
        "marital",
        "marri",
        "marry",
        "married",
        "mother",
        "neighbor",
        "parent",
        "partner",
        "relationship",
        "roommate",
        "sibling",
        "sister",
        "son",
        "spouse",
        "status",
        "team",
        "teammate",
        "wife",
    }
    if not status_terms & relation_set:
        return False
    if time_intent.is_temporal:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bgroup\s+of\s+friends\b", normalized_question):
        return False
    if re.search(
        r"\bpartner(?:ed)?\s+with\b.+\b(?:project|work|assignment|team|"
        r"presentation|report)\b|"
        r"\bwho\s+did\b.+\bpartner\s+with\b|"
        r"\b(?:project|work|assignment|team|presentation|report)\s+"
        r"partner\s+s\s+name\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(r"\b(?:relationship|marital)\s+status\b", normalized_question)
        or re.search(
            r"\bwho\b.+\b(?:boyfriend|boss|brother|child|children|colleague|"
            r"cousin|coworker|daughter|father|fiancee?|friend|girlfriend|"
            r"grandfather|grandmother|husband|"
            r"kids|manager|mentor|mother|neighbor|parent|parents|partner|roommate|sibling|"
            r"sister|son|spouse|team|team\s+member|teammate|wife)\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:does|do|did)\b.+\bhave\b.+"
            r"\b(?:child|children|kids|son|daughter)\b",
            normalized_question,
        )
        or re.search(
            r"\bwhat\s+(?:is|are|was|were)\b.+"
            r"\b(?:boyfriend|boss|brother|child|children|colleague|cousin|"
            r"coworker|daughter|father|fiancee?|friend|girlfriend|grandfather|"
            r"grandmother|husband|kids|manager|mentor|mother|neighbor|parent|"
            r"parents|partner|roommate|sibling|sister|son|spouse|team|"
            r"team\s+member|teammate|wife)"
            r"\s+s\s+names?\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:who|whom)\b.+\b(?:team\s+member|teammate)\b|"
            r"\b(?:who|whom)\b.+\bon\b.+\bteam\b|"
            r"\bwhat\b.+\bteam\b.+\b(?:on|member|teammate)\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:is|are|was|were)\b.+\b(?:dating|engaged|married|single|"
            r"divorced)\b",
            normalized_question,
        )
    )


def _has_commitment_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {
        "cancel",
        "deadline",
        "promise",
        "remember",
        "reschedule",
        "task",
    } & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(
        r"\bremember(?:ed|s|ing)?\s+(?:childhood|story|trip|vacation|birthday)\b|"
        r"\bpromise\s+ring\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:deadline|due\s+date|when\b.+\bdue|"
            r"what\b.+\b(?:task|todo|to do|to-do)|"
            r"what\b.+\bpromise(?:d)?|"
            r"(?:task|todo|to do|to-do|plan|promise|deadline)\b.+"
            r"\b(?:cancel(?:ed|led|s)?|reschedul(?:e|ed|es|ing)?)\b|"
            r"(?:cancel(?:ed|led|s)?|reschedul(?:e|ed|es|ing)?)\b.+"
            r"\b(?:task|todo|to do|to-do|plan|promise|deadline)\b|"
            r"(?:need|needs|needed)\s+to\s+remember|"
            r"remember\s+to)\b",
            normalized_question,
        )
    )


def _has_education_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"class", "education"} & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:what|which)\s+school\b|"
            r"\b(?:college|university)\b|"
            r"\b(?:study|studies|studying|majoring)\b|"
            r"\bwhat\s+(?:is|was)\b.+\bmajor\b(?:\s+(?:in|at)\b|$)|"
            r"\bwhat\s+(?:is|was)\b.+\bdegree\b(?:\s+(?:in|from)\b|$)|"
            r"\bwhat\s+degree\s+(?:does|did|is|was|has|have)\b|"
            r"\bdegree\s+(?:does|did)\b.+\bhave\b|"
            r"\b(?:major|degree)\s+in\b|"
            r"\b(?:where|when|what\s+school)\b.+\bgraduat(?:e|ed|ion)\b|"
            r"\bgraduat(?:e|ed|ion)\b.+\b(?:from|school|college|university)\b|"
            r"\bwhat\s+class\b",
            normalized_question,
        )
    )


def _has_employment_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "employment" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:what|which)\s+"
            r"(?:company|employer|job|occupation|profession|workplace)\b|"
            r"\bwho\s+(?:is|was)\b.+\bemployer\b|"
            r"\bwhat\s+(?:is|was)\b.+\b(?:salary|wage|pay\s+rate|hourly\s+rate)\b|"
            r"\b(?:job|occupation|profession|workplace)\b|"
            r"\bwhere\b.+\bwork\b|"
            r"\bwhat\b.+\bdo\b.+\bfor\s+work\b|"
            r"\bwork\b.+\b(?:company|for)\b",
            normalized_question,
        )
    )


def _has_health_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "health" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:doctor|physician|therapist|medication|medicine|prescription|allerg"
            r"(?:y|ic)|health\s+issue|condition|dentist|dental)\b"
            r"|\bblood\s+type\b"
            r"|\bprimary\s+care\s+(?:doctor|physician|provider)\b"
            r"|\b(?:medical|doctor(?:'s)?|dentist(?:'s)?|therapy|clinic)\s+"
            r"appointment\b",
            normalized_question,
        )
    )


def _has_contact_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "contact" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(
        r"\baddress(?:ed|es|ing)?\s+(?:a|an|the|their|his|her|my|our)?\s*"
        r"(?:concern|issue|problem|question|risk|topic)\b|"
        r"\b(?:concern|issue|problem|question|risk|topic)\b.+"
        r"\baddress(?:ed|es|ing)?\b|"
        r"\baddress(?:ed|es|ing)?\b.+\bwith\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:contact\s+(?:info|information|details)|"
            r"emergency\s+contact|"
            r"email|e mail|phone|telephone|cell|mobile|address)\b|"
            r"\b(?:phone|telephone|cell|mobile)\s+number\b|"
            r"\b(?:instagram|signal|slack|telegram|whatsapp)\s+"
            r"(?:handle|username|number)\b|"
            r"\bwhat\s+is\s+(?:[a-z0-9]+(?:\s+s)?|my|his|her|their|our|your)\s+"
            r"(?:handle|number|username)\b|"
            r"\bhow\s+(?:can|could|do|does|did)\s+(?:i|we|you)\s+"
            r"(?:contact|reach)\b",
            normalized_question,
        )
    )


def _has_diet_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "diet" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:dietary\s+(?:restriction|restrictions)|"
            r"vegetarian|vegan|gluten\s?free|dairy\s?free)\b|"
            r"\b(?:avoid|avoids|can t|cannot|can\s+not|doesn t|does\s+not|don t|do\s+not)\s+eat\b|"
            r"\bwhat\s+can\b.+\bnot\s+eat\b|"
            r"\bavoid(?:s|ed)?\s+eating\b|"
            r"\bwhat\s+food\b.+\b(?:avoid|eat)\b",
            normalized_question,
        )
    )


def _has_pet_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "pet" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\bwhat\s+pet\b|\b(?:dog|cat|pet)\b.+\bnamed?\b|"
            r"\bname\b.+\b(?:dog|cat|pet)\b|"
            r"\bbreed\b.+\b(?:dog|cat|pet)\b|\b(?:dog|cat|pet)\b.+\bbreed\b|"
            r"\b(?:dog|cat|pet|puppy|kitten)\b.+\bmicrochip\b|"
            r"\bmicrochip\b.+\b(?:dog|cat|pet|puppy|kitten)\b",
            normalized_question,
        )
    )


def _has_skill_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "skill" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\blanguages?\b.+\b(?:speak|know|fluent|bilingual)\b|"
            r"\b(?:speak|know)\b.+\blanguages?\b|"
            r"\b(?:fluent|bilingual)\b.+\blanguages?\b|"
            r"\blanguages?\b.+\blearn(?:ed|ing)?\b|"
            r"\blearn(?:ed|ing)?\b.+\blanguages?\b|"
            r"\bprogramming\s+languages?\b|\blanguages?\b.+\bprogramming\b|"
            r"\bskill\b.+\blearn(?:ed|ing)?\b|"
            r"\blearn(?:ed|ing)?\b.+\bskill\b|"
            r"\b(?:certification|credential)\b|"
            r"\bcertified\s+in\b|"
            r"\binstrument\b.+\bplay\b|\bplay\b.+\binstrument\b|"
            r"\bplay\s+(?:guitar|piano|violin|drums?)\b",
            normalized_question,
        )
    )


def _has_vehicle_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "vehicle" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\blicen[cs]e\s+plate\b|"
            r"\b(?:what|which|kind\s+of|color)\b.+"
            r"\b(?:car|vehicle|truck|suv|sedan|van)\b|"
            r"\b(?:car|vehicle|truck|suv|sedan|van)\b.+"
            r"\b(?:drive|have|has|own|color)\b|"
            r"\bdrive\s+(?:a|an|the|my|his|her|their)\s+"
            r"(?:car|vehicle|truck|suv|sedan|van)\b",
            normalized_question,
        )
    )


def _has_date_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"anniversary", "birthday"} & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\bwhen\b.+\b(?:anniversary|birthday)\b|"
            r"\bwhat\s+(?:is|was)\b.+\b(?:anniversary|birthday)\b|"
            r"\b(?:what|which)\s+(?:date|day|month)\b.+"
            r"\b(?:anniversary|birthday)\b|"
            r"\b(?:anniversary|birthday)\b.+\b(?:date|when)\b|"
            r"\bwedding\s+date\b|"
            r"\b(?:date\s+of\s+birth|birth\s+date|birthdate|dob)\b",
            normalized_question,
        )
    )
