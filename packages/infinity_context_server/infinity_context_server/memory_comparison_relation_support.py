"""Typed relation-category support predicates for benchmark evidence."""

from __future__ import annotations

import re
from collections.abc import Callable


def typed_relation_category_support(
    category: str,
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool | None:
    """Return typed support status for known categories, or None if generic."""

    if category == "action_event":
        return _has_action_event_support(memory_terms, memory_text=memory_text)
    if category == "location_transition":
        return _has_location_transition_support(memory_terms, memory_text=memory_text)
    if category == "activity_profile":
        return _has_activity_profile_support(memory_terms, memory_text=memory_text)
    if category == "communication":
        return _has_communication_support(memory_terms, memory_text=memory_text)
    if category == "commitment_profile":
        return _has_commitment_profile_support(memory_terms, memory_text=memory_text)
    if category == "contact_profile":
        return _has_contact_profile_support(memory_terms, memory_text=memory_text)
    if category == "diet_profile":
        return _has_diet_profile_support(memory_terms, memory_text=memory_text)
    if category == "participation_event":
        return _has_participation_event_support(memory_terms, memory_text=memory_text)
    if category == "education_profile":
        return _has_education_profile_support(
            memory_terms,
            memory_text=memory_text,
        )
    if category == "employment_profile":
        return _has_employment_profile_support(
            memory_terms,
            memory_text=memory_text,
        )
    if category == "emotion_response":
        return _has_emotion_response_support(memory_terms, memory_text=memory_text)
    if category == "age_profile":
        return _has_age_profile_support(memory_terms, memory_text=memory_text)
    if category == "alias_profile":
        return _has_alias_profile_support(memory_terms, memory_text=memory_text)
    if category == "date_profile":
        return _has_date_profile_support(memory_terms, memory_text=memory_text)
    if category == "health_profile":
        return _has_health_profile_support(memory_terms, memory_text=memory_text)
    if category == "pet_profile":
        return _has_pet_profile_support(memory_terms, memory_text=memory_text)
    if category == "skill_profile":
        return _has_skill_profile_support(memory_terms, memory_text=memory_text)
    if category == "status_profile":
        return _has_status_profile_support(memory_terms, memory_text=memory_text)
    if category == "vehicle_profile":
        return _has_vehicle_profile_support(
            memory_terms,
            memory_text=memory_text,
        )
    if category == "exchange":
        return _has_exchange_support(memory_terms, memory_text=memory_text)
    if category == "favorite_preference":
        return _has_favorite_preference_support(
            memory_terms,
            memory_text=memory_text,
        )
    check = _TYPED_SUPPORT_CHECKS.get(category)
    if check is None:
        return None
    return check(memory_terms)


def _has_registration_event_support(memory_terms: set[str]) -> bool:
    registration_action = {
        "enroll",
        "enrolled",
        "register",
        "registered",
        "registration",
        "sign",
        "signed",
        "signup",
    } & memory_terms
    event_context = {"class", "course", "lesson", "workshop", "event"} & memory_terms
    return bool(registration_action and event_context)


def _has_symbolic_meaning_support(memory_terms: set[str]) -> bool:
    symbolic_surface = {
        "mean",
        "meaning",
        "meant",
        "message",
        "reminder",
        "represent",
        "symbol",
        "symbolize",
        "value",
    } & memory_terms
    object_context = {
        "family",
        "gift",
        "necklace",
        "special",
        "support",
    } & memory_terms
    return bool(symbolic_surface and object_context)


_ACTION_EVENT_SURFACE_RE = re.compile(
    r"\b(?:brought|took|sent|shared|painted|drew|made|booked|scheduled|"
    r"prepared|completed|fixed|repaired|created)\b"
    r"(?:\s+(?:a|an|the|their|his|her|my|our))?\s+"
    r"[a-zA-Z][a-zA-Z0-9_-]+",
    re.IGNORECASE,
)


def _has_action_event_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    action_surface = {
        "booked",
        "brought",
        "completed",
        "created",
        "drew",
        "fixed",
        "made",
        "painted",
        "prepared",
        "repaired",
        "scheduled",
        "sent",
        "shared",
        "took",
    } & memory_terms
    return bool(action_surface and _ACTION_EVENT_SURFACE_RE.search(memory_text))


_PARTICIPATION_DESTINATION_SURFACE_RE = re.compile(
    r"\b(?:visit|visited|travel|traveled|travelled|go|went)\s+"
    r"(?:to\s+)?(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:the\s+)?(?:beach|city|conference|country|gallery|museum|park|studio))\b"
    r"|\b(?:meet|met)\s+(?:up\s+)?(?:with\s+)?"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:friends?|family|mentors?|colleagues?|coworkers?|team|group))\b"
    r"|\bmeeting\s+with\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:friends?|family|mentors?|colleagues?|coworkers?|team|group))\b"
    r"|\b(?:trip|vacation)\s+(?:to|in)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:the\s+)?(?:beach|city|country|mountains|park))\b",
)


def _has_participation_event_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    participation_action = {
        "attend",
        "attended",
        "join",
        "joined",
        "meet",
        "meeting",
        "met",
        "participate",
        "participated",
        "travel",
        "traveled",
        "travelled",
        "visit",
        "visited",
        "went",
    } & memory_terms
    event_context = {
        "class",
        "club",
        "conference",
        "event",
        "group",
        "meeting",
        "place",
        "studio",
        "trip",
        "workshop",
    } & memory_terms
    return bool(
        (participation_action and event_context)
        or _PARTICIPATION_DESTINATION_SURFACE_RE.search(memory_text)
    )


_EDUCATION_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:go|goes|went)\s+to\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+(?:\s+[A-Z][a-zA-Z0-9_-]+){0,3}|"
    r"(?:college|university|school))\b"
    r"|\b(?:attend|attends|attended|study|studies|studying)\s+"
    r"(?:at\s+)?(?:[A-Z][a-zA-Z0-9_-]+(?:\s+[A-Z][a-zA-Z0-9_-]+){0,3}|"
    r"(?:college|university|school))\b",
    re.IGNORECASE,
)


def _has_education_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    education_surface = {
        "campus",
        "class",
        "college",
        "course",
        "degree",
        "education",
        "major",
        "majoring",
        "school",
        "studies",
        "study",
        "studying",
        "university",
    } & memory_terms
    education_action = {
        "attend",
        "attended",
        "go",
        "goes",
        "major",
        "majoring",
        "study",
        "studies",
        "studying",
        "take",
        "taking",
    } & memory_terms
    education_context = {
        "campus",
        "class",
        "college",
        "course",
        "degree",
        "education",
        "major",
        "school",
        "university",
    } & memory_terms
    return bool(
        education_surface
        or (education_action and education_context)
        or _EDUCATION_PROFILE_SURFACE_RE.search(memory_text)
    )


_OCCUPATION_TITLE_RE = (
    r"(?:accountant|artist|attorney|chef|counselor|designer|developer|doctor|"
    r"engineer|lawyer|manager|nurse|photographer|professor|researcher|"
    r"scientist|teacher|therapist|writer|software\s+engineer|social\s+worker)"
)
_EMPLOYMENT_OCCUPATION_SURFACE_RE = re.compile(
    rf"\b(?:i\s+am|i'm|he\s+is|he's|she\s+is|she's|they\s+are|"
    rf"they're)\s+(?:a\s+|an\s+)?{_OCCUPATION_TITLE_RE}\b",
    re.IGNORECASE,
)
_EMPLOYMENT_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:work|works|worked|working)\s+(?:at|for|in|as)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+|"
    r"a\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    r"|\b(?:job|occupation|profession|role)\s+(?:is|was|as)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|a\s+[a-zA-Z][a-zA-Z0-9_-]+|"
    r"the\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    rf"|{_EMPLOYMENT_OCCUPATION_SURFACE_RE.pattern}",
    re.IGNORECASE,
)


def has_employment_occupation_surface(memory_text: str) -> bool:
    return bool(_EMPLOYMENT_OCCUPATION_SURFACE_RE.search(memory_text))


def _has_employment_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    employment_context = {
        "career",
        "company",
        "employer",
        "job",
        "occupation",
        "office",
        "profession",
        "role",
        "workplace",
    } & memory_terms
    work_action = {"work", "worked", "working", "works"} & memory_terms
    return bool(
        employment_context
        or (work_action and employment_context)
        or _EMPLOYMENT_PROFILE_SURFACE_RE.search(memory_text)
    )


_HEALTH_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:doctor|dentist|dental|therapist|clinic|prescription|medication|"
    r"medicine|allergy|allergic|condition)\b"
    r"|\bprimary\s+care\s+(?:doctor|physician|provider)\b"
    r"|\b(?:medical|doctor(?:'s)?|dentist(?:'s)?|therapy|clinic)\s+"
    r"appointment\b"
    r"|\bappointment\s+with\s+(?:the\s+)?"
    r"(?:doctor|physician|dentist|therapist|clinic|dr\.?\s+[A-Z][a-zA-Z0-9_-]*)\b"
    r"|\b(?:take|takes|taking)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:a\s+|an\s+|the\s+)?(?:pill|medication|medicine|prescription))\b"
    r"|\b(?:have|has|had)\s+(?:asthma|diabetes|migraine|allergies|allergy)\b",
    re.IGNORECASE,
)


_AGE_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:i\s+am|i'm|he\s+is|he's|she\s+is|she's|they\s+are|they're)\s+"
    r"(?:\d{1,3}|[a-z]+)\s+years?\s+old\b"
    r"|\b(?:age\s+(?:is|was)|turned)\s+(?:\d{1,3}|[a-z]+)\b",
    re.IGNORECASE,
)


def _has_age_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    age_surface = {"age", "old"} & memory_terms
    year_surface = {"year", "years"} & memory_terms
    return bool(
        (age_surface and year_surface)
        or _AGE_PROFILE_SURFACE_RE.search(memory_text)
    )


_ALIAS_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:nickname|alias)\s+(?:is|was|for)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|[\"'][^\"']+[\"'])\b"
    r"|\b(?:call|calls|called)\s+"
    r"(?:me|him|her|them|us|you|[A-Z][a-zA-Z0-9_-]+)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|[\"'][^\"']+[\"'])\b"
    r"|\b(?:go|goes|went)\s+by\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|[\"'][^\"']+[\"'])\b",
)


def _has_alias_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    alias_surface = {"alias", "nickname"} & memory_terms
    naming_surface = {"call", "called", "calls", "name", "named"} & memory_terms
    return bool(
        alias_surface
        or (naming_surface and _ALIAS_PROFILE_SURFACE_RE.search(memory_text))
        or _ALIAS_PROFILE_SURFACE_RE.search(memory_text)
    )


_DATE_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:anniversary|birthday)\s+(?:is|was|falls|fell)\s+"
    r"(?:on\s+|in\s+)?(?:\d{1,2}(?:st|nd|rd|th)?|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b"
    r"|\bborn\s+(?:(?:on|in)\s+)?"
    r"(?:\d{1,2}(?:st|nd|rd|th)?|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b"
    r"|\bdate\s+of\s+birth\s+(?:is|was)\s+"
    r"(?:\d{1,2}(?:st|nd|rd|th)?|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)


def _has_date_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    date_subject = {"anniversary", "birthday"} & memory_terms
    date_surface = {
        "april",
        "august",
        "december",
        "february",
        "january",
        "july",
        "june",
        "march",
        "may",
        "month",
        "november",
        "october",
        "september",
    } & memory_terms
    return bool(
        (date_subject and date_surface)
        or _DATE_PROFILE_SURFACE_RE.search(memory_text)
    )


_ACTIVITY_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:hobby|pastime)\s+(?:is|was|became)\b"
    r"|\b(?:for\s+fun|in\s+(?:my|his|her|their|our)\s+free\s+time)\b"
    r"|\b(?:enjoy|enjoys|like|likes|love|loves)\s+"
    r"(?:to\s+)?(?:hike|hiking|paint|painting|read|reading|run|running|"
    r"cook|cooking|dance|dancing|swim|swimming|yoga|tennis|gardening)\b"
    r"|\b(?:do|does|did|started|took\s+up|takes\s+up)\s+"
    r"(?:yoga|tennis|gardening|painting|running|hiking|cooking|dancing)\b"
    r"|\b(?:go|goes|went)\s+"
    r"(?:hiking|running|swimming|camping)\b",
    re.IGNORECASE,
)


def _has_activity_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    activity_context = {
        "activity",
        "camping",
        "cooking",
        "dancing",
        "exercise",
        "fun",
        "gardening",
        "hiking",
        "hobbies",
        "hobby",
        "leisure",
        "paint",
        "painting",
        "pastime",
        "run",
        "running",
        "sport",
        "tennis",
        "yoga",
    } & memory_terms
    activity_action = {
        "do",
        "does",
        "enjoy",
        "enjoys",
        "go",
        "goes",
        "like",
        "likes",
        "love",
        "loves",
        "play",
        "plays",
        "run",
        "runs",
        "started",
    } & memory_terms
    return bool(
        (activity_context and activity_action)
        or _ACTIVITY_PROFILE_SURFACE_RE.search(memory_text)
    )


def _has_health_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    health_surface = {
        "allergic",
        "allergy",
        "clinic",
        "condition",
        "dental",
        "dentist",
        "doctor",
        "health",
        "medication",
        "medicine",
        "prescription",
        "therapist",
    } & memory_terms
    medical_appointment = "appointment" in memory_terms and bool(
        {
            "clinic",
            "dental",
            "dentist",
            "doctor",
            "medical",
            "physician",
            "therapy",
            "therapist",
        }
        & memory_terms
    )
    medication_action = {"take", "takes", "taking"} & memory_terms
    medication_context = {
        "dose",
        "medication",
        "medicine",
        "pill",
        "prescription",
    } & memory_terms
    return bool(
        health_surface
        or medical_appointment
        or (medication_action and medication_context)
        or _HEALTH_PROFILE_SURFACE_RE.search(memory_text)
    )


_CONTACT_PROFILE_SURFACE_RE = re.compile(
    r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b"
    r"|\b(?:email|e-mail)(?:\s+address)?\s+(?:is|was)\s+\S+"
    r"|\b(?:phone|telephone|cell|mobile)(?:\s+number)?\s+"
    r"(?:is|was)\s+(?:\+?\d[\d()\-\s.]{5,}\d)\b"
    r"|\b(?:(?:my|his|her|their|our|your)\s+)?(?:phone\s+)?number\s+"
    r"(?:is|was)\s+(?:\+?\d[\d()\-\s.]{5,}\d)\b"
    r"|\b(?:contact\s+(?:info|information|details)|"
    r"(?:mailing\s+)?address)\s+(?:is|was)\s+"
    r"(?:\d{1,6}\s+)?[A-Za-z0-9][A-Za-z0-9 .'-]{2,}",
    re.IGNORECASE,
)


def _has_contact_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    phone_surface = {"cell", "mobile", "phone", "telephone"} & memory_terms
    contact_surface = {"contact"} & memory_terms
    address_surface = {"address"} & memory_terms
    number_surface = {"number"} & memory_terms
    return bool(
        (phone_surface and number_surface)
        or (contact_surface and {"detail", "details", "info", "information"} & memory_terms)
        or (
            address_surface
            and {"avenue", "home", "mailing", "road", "street"} & memory_terms
            and not {"concern", "issue", "problem", "topic"} & memory_terms
        )
        or _CONTACT_PROFILE_SURFACE_RE.search(memory_text)
    )


_COMMITMENT_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:deadline|due\s+date)\s+(?:is|was)\s+"
    r"(?:\d{1,2}(?::\d{2})?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|next\s+week)\b"
    r"|\b(?:due|finish|complete)\s+(?:by|before)\s+"
    r"(?:\d{1,2}(?::\d{2})?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|next\s+week)\b"
    r"|\b(?:need|needs|needed)\s+to\s+remember\s+to\b"
    r"|\bremember\s+to\s+(?:bring|send|call|finish|complete|take)\b"
    r"|\b(?:promise|promised)\s+to\s+"
    r"(?:bring|send|call|finish|complete|take|help)\b",
    re.IGNORECASE,
)


def _has_commitment_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    deadline_surface = {"due"} & memory_terms or (
        "deadline" in memory_terms
        and {
            "friday",
            "monday",
            "saturday",
            "sunday",
            "thursday",
            "today",
            "tomorrow",
            "tuesday",
            "wednesday",
        }
        & memory_terms
    )
    task_action = {"complete", "finish", "send", "bring", "call", "take"} & memory_terms
    task_surface = {"task", "todo", "to-do"} & memory_terms
    promise_surface = {"promise", "promised"} & memory_terms
    reminder_surface = {"remember", "reminder"} & memory_terms
    return bool(
        deadline_surface
        or (task_surface and task_action)
        or (promise_surface and task_action)
        or (reminder_surface and task_action)
        or _COMMITMENT_PROFILE_SURFACE_RE.search(memory_text)
    )


_DIET_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:i\s+am|i'm|he\s+is|he's|she\s+is|she's|they\s+are|they're)\s+"
    r"(?:a\s+)?(?:vegetarian|vegan)\b"
    r"|\b(?:vegetarian|vegan)\s+(?:diet|now|since|because)\b"
    r"|\b(?:gluten|dairy)[-\s]?free\b"
    r"|\b(?:avoid|avoids|avoided)\s+(?:eating\s+)?"
    r"(?:gluten|dairy|meat|pork|seafood|shellfish|eggs?|soy|lactose|"
    r"peanuts?|tree\s+nuts?)\b"
    r"|\b(?:can't|cannot|doesn't|don't|do\s+not|does\s+not)\s+eat\s+"
    r"(?:gluten|dairy|meat|pork|seafood|shellfish|eggs?|soy|lactose|"
    r"peanuts?|tree\s+nuts?)\b"
    r"|\b(?:dietary\s+)?restriction\s+(?:is|was)\s+"
    r"(?:vegetarian|vegan|gluten|dairy|pork|shellfish|peanuts?)\b",
    re.IGNORECASE,
)


def _has_diet_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    diet_identity = {"vegetarian", "vegan"} & memory_terms
    restriction_context = {
        "dairy",
        "egg",
        "eggs",
        "gluten",
        "lactose",
        "meat",
        "peanut",
        "peanuts",
        "pork",
        "seafood",
        "shellfish",
        "soy",
    } & memory_terms
    restriction_action = {
        "avoid",
        "avoids",
        "eat",
        "restriction",
    } & memory_terms
    return bool(
        (diet_identity and {"am", "diet", "is"} & memory_terms)
        or (restriction_context and restriction_action)
        or _DIET_PROFILE_SURFACE_RE.search(memory_text)
    )


_PET_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:my|our|his|her|their)\s+(?:pet|dog|cat|puppy|kitten)\b"
    r"|\b(?:my|our|his|her|their)\s+"
    r"(?:golden\s+retriever|labrador|poodle|beagle|bulldog|terrier|"
    r"siamese|tabby|persian)\b"
    r"|\b(?:pet|dog|cat|puppy|kitten)\s+(?:is|was|named|called)\b"
    r"|\b(?:golden\s+retriever|labrador|poodle|beagle|bulldog|terrier|"
    r"siamese|tabby|persian)\s+(?:is|was|named|called)\b"
    r"|\b(?:have|has|had)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:pet|dog|cat|puppy|kitten|golden\s+retriever|labrador|poodle|"
    r"beagle|bulldog|terrier|siamese|tabby|persian)\b",
    re.IGNORECASE,
)


def _has_pet_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    pet_surface = {
        "beagle",
        "bulldog",
        "cat",
        "dog",
        "kitten",
        "labrador",
        "persian",
        "pet",
        "poodle",
        "puppy",
        "retriever",
        "siamese",
        "tabby",
        "terrier",
    } & memory_terms
    name_surface = {"call", "called", "name", "named"} & memory_terms
    ownership_surface = {"have", "has", "had", "my", "our"} & memory_terms
    return bool(
        (pet_surface and (name_surface or ownership_surface))
        or _PET_PROFILE_SURFACE_RE.search(memory_text)
    )


_SKILL_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:speak|speaks|speaking|spoken)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:english|spanish|french|german|mandarin|japanese|arabic|hindi))\b"
    r"|\b(?:know|knows|knew|known)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:english|spanish|french|german|mandarin|japanese|arabic|hindi))\b"
    r"|\bfluent\s+(?:in\s+)?"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:english|spanish|french|german|mandarin|japanese|arabic|hindi))\b"
    r"|\bbilingual\s+(?:in\s+)?"
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:english|spanish|french|german|mandarin|japanese|arabic|hindi))\b"
    r"|\b(?:play|plays|playing)\s+"
    r"(?:guitar|piano|violin|drums?|cello|flute|saxophone)\b",
)


def _has_skill_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    language_action = {"speak", "speaks", "spoken", "speaking"} & memory_terms
    language_ability = {"bilingual", "fluent", "know", "known"} & memory_terms
    language_context = {
        "arabic",
        "english",
        "french",
        "german",
        "hindi",
        "japanese",
        "language",
        "mandarin",
        "spanish",
    } & memory_terms
    play_action = {"play", "plays", "playing"} & memory_terms
    instrument_context = {
        "drums",
        "guitar",
        "instrument",
        "piano",
        "violin",
    } & memory_terms
    return bool(
        (language_action and language_context)
        or (language_ability and language_context)
        or (play_action and instrument_context)
        or _SKILL_PROFILE_SURFACE_RE.search(memory_text)
    )


_VEHICLE_MODEL_NAME_PATTERN = (
    r"(?:accord|audi|bmw|camry|civic|corolla|ford|honda|jeep|mazda|"
    r"nissan|prius|rav4|subaru|tesla|toyota|volvo)"
)
_VEHICLE_MODEL_OWNER_PATTERN = (
    r"(?:(?i:my|our|his|her|their)|[A-Z][a-zA-Z0-9_-]{1,40}'s)"
)
_VEHICLE_MODEL_SURFACE_RE = re.compile(
    rf"\b{_VEHICLE_MODEL_OWNER_PATTERN}\s+"
    rf"(?i:{_VEHICLE_MODEL_NAME_PATTERN})\b",
)
_VEHICLE_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:my|our|his|her|their)\s+(?:car|vehicle|truck|suv|sedan|van)\b"
    rf"|\b{_VEHICLE_MODEL_OWNER_PATTERN}\s+"
    rf"(?i:{_VEHICLE_MODEL_NAME_PATTERN})\b"
    r"|\b(?:drive|drives|driving)\s+"
    r"(?:a|an|the|my|his|her|their)\s+"
    r"(?:(?:black|blue|green|red|silver|white)\s+)?"
    r"(?:car|vehicle|truck|suv|sedan|van|[A-Z][a-zA-Z0-9_-]+)\b"
    r"|\b(?:own|owns|owned|have|has|had)\s+"
    r"(?:a|an|the|my|his|her|their)\s+"
    r"(?:(?:black|blue|green|red|silver|white)\s+)?"
    r"(?:car|vehicle|truck|suv|sedan|van|[A-Z][a-zA-Z0-9_-]+)\b"
    r"|\b(?:car|vehicle|truck|suv|sedan|van)\s+(?:is|was)\s+"
    r"(?:black|blue|green|red|silver|white|[A-Z][a-zA-Z0-9_-]+)\b",
)


def has_vehicle_model_surface(memory_text: str) -> bool:
    return bool(_VEHICLE_MODEL_SURFACE_RE.search(memory_text))


def _has_vehicle_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    vehicle_surface = {"car", "sedan", "suv", "truck", "van", "vehicle"} & memory_terms
    ownership_surface = {
        "drive",
        "drives",
        "driving",
        "had",
        "has",
        "have",
        "my",
        "our",
        "own",
        "owned",
        "owns",
    } & memory_terms
    color_surface = {
        "black",
        "blue",
        "color",
        "green",
        "red",
        "silver",
        "white",
    } & memory_terms
    return bool(
        (vehicle_surface and ownership_surface)
        or (vehicle_surface and color_surface)
        or _VEHICLE_PROFILE_SURFACE_RE.search(memory_text)
    )


_EMOTION_RESPONSE_SURFACE_RE = re.compile(
    r"\b(?:feel|feels|feeling|felt)\s+"
    r"(?:anxious|concerned|excited|happy|hopeful|nervous|overwhelmed|"
    r"proud|relieved|sad|thrilled|upset|worried)\b"
    r"|\b(?:reaction|response)\s+(?:to|about)\s+[^.?!]{0,80}\b"
    r"(?:was|is|felt)\s+"
    r"(?:anxious|concerned|excited|happy|hopeful|nervous|overwhelmed|"
    r"proud|relieved|sad|thrilled|upset|worried)\b"
    r"|\b(?:i|he|she|they|we)\s+(?:am|are|was|were)\s+"
    r"(?:anxious|concerned|excited|happy|hopeful|nervous|overwhelmed|"
    r"proud|relieved|sad|thrilled|upset|worried)\b",
    re.IGNORECASE,
)


def _has_emotion_response_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    emotion_surface = {
        "anxious",
        "concern",
        "excite",
        "excited",
        "feel",
        "felt",
        "happy",
        "nervous",
        "overwhelm",
        "overwhelmed",
        "proud",
        "relieved",
        "reliev",
        "thrill",
        "thrilled",
        "upset",
        "worried",
        "worri",
    } & memory_terms
    response_context = {
        "about",
        "because",
        "news",
        "family",
        "kid",
        "kids",
        "make",
        "process",
        "reaction",
        "response",
        "said",
        "thought",
        "think",
        "when",
    } & memory_terms
    return bool(
        (emotion_surface and response_context)
        or _EMOTION_RESPONSE_SURFACE_RE.search(memory_text)
    )


_COMMUNICATION_RECIPIENT_RE = (
    r"(?:[A-Z][a-zA-Z0-9_-]+|"
    r"(?:my|his|her|their|our)\s+"
    r"(?:brother|child|client|daughter|doctor|father|friend|manager|mother|"
    r"parent|partner|sibling|sister|son|spouse|teacher|team|wife|husband)|"
    r"the\s+(?:client|doctor|group|manager|teacher|team)|"
    r"(?:her|him|me|them|us|you)"
    r"(?=\s+(?:about|after|before|during|later|that|then|today|tomorrow|"
    r"yesterday)|[.?!,;:]|$))"
)
_DIRECTED_COMMUNICATION_SURFACE_RE = re.compile(
    rf"\b(?:advised|asked|recommended|requested|suggested|told)\s+"
    rf"(?:that\s+)?{_COMMUNICATION_RECIPIENT_RE}",
)
_CONVERSATION_COMMUNICATION_SURFACE_RE = re.compile(
    rf"\b(?:chat(?:ted)?|discuss(?:ed)?|talk(?:ed)?)\b"
    rf".{{0,80}}\b(?:about|to|with)\s+"
    rf"(?:{_COMMUNICATION_RECIPIENT_RE}|[A-Z][a-zA-Z0-9_-]+|"
    rf"[a-zA-Z][a-zA-Z0-9_-]+)",
)
_CHANNEL_COMMUNICATION_SURFACE_RE = re.compile(
    rf"\b(?:called|messaged|texted)\s+{_COMMUNICATION_RECIPIENT_RE}"
    rf"|\bsent\s+(?:{_COMMUNICATION_RECIPIENT_RE}\s+)?"
    rf"(?:a\s+|an\s+|the\s+)?message\b"
    rf"|\bsent\s+(?:a\s+|an\s+|the\s+)?message\s+to\s+"
    rf"{_COMMUNICATION_RECIPIENT_RE}",
)
_INDIRECT_COMMUNICATION_RECIPIENT_RE = re.compile(
    rf"\b(?:advised|mentioned|recommended|said|suggested)\b"
    rf".{{0,80}}\b(?:to|with)\s+{_COMMUNICATION_RECIPIENT_RE}",
)


def _has_communication_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    communication_action = {
        "advis",
        "advise",
        "advised",
        "ask",
        "asked",
        "call",
        "called",
        "chat",
        "chatt",
        "chatted",
        "conversation",
        "discus",
        "discuss",
        "discussed",
        "discussion",
        "message",
        "messag",
        "messaged",
        "mention",
        "mentioned",
        "recommend",
        "recommended",
        "request",
        "requested",
        "say",
        "said",
        "send",
        "sent",
        "suggest",
        "suggested",
        "talk",
        "talked",
        "tell",
        "text",
        "texted",
        "told",
    } & memory_terms
    communication_context = {
        "about",
        "advice",
        "book",
        "call",
        "conversation",
        "delay",
        "invoice",
        "message",
        "project",
        "read",
        "request",
        "requested",
        "recommendation",
        "response",
    } & memory_terms
    return bool(
        (communication_action and communication_context)
        or (
            communication_action
            and (
                _DIRECTED_COMMUNICATION_SURFACE_RE.search(memory_text)
                or _CHANNEL_COMMUNICATION_SURFACE_RE.search(memory_text)
                or _CONVERSATION_COMMUNICATION_SURFACE_RE.search(memory_text)
                or _INDIRECT_COMMUNICATION_RECIPIENT_RE.search(memory_text)
            )
        )
    )


_EXCHANGE_RECIPIENT_RE = (
    r"(?:[A-Z][a-zA-Z0-9_-]+|her|him|me|them|us|you|"
    r"(?:my|his|her|their|our)\s+"
    r"(?:brother|child|client|daughter|father|friend|manager|mother|parent|"
    r"partner|sibling|sister|son|spouse|team|wife|husband)|"
    r"the\s+(?:client|group|team))"
)
_EXCHANGE_OBJECT_RE = (
    r"(?!(?:advice|help|message|news|request|response|support)\b)"
    r"[a-zA-Z][a-zA-Z0-9_-]+"
)
_DIRECT_EXCHANGE_SURFACE_RE = re.compile(
    rf"\b(?:bought|get|got|purchased|received)\s+"
    rf"(?:a|an|the|my|his|her|their|our|some)?\s*{_EXCHANGE_OBJECT_RE}"
    rf"(?:\s+from\s+{_EXCHANGE_RECIPIENT_RE})?"
    rf"|\b(?:bring|brought|gave|give|offered|offer)\s+"
    rf"{_EXCHANGE_RECIPIENT_RE}\s+"
    rf"(?:a|an|the|my|his|her|their|our|some)?\s*{_EXCHANGE_OBJECT_RE}",
)


def _has_exchange_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    exchange_actions = {
        "bought",
        "bring",
        "brought",
        "buy",
        "gave",
        "get",
        "give",
        "gift",
        "got",
        "offer",
        "offered",
        "purchas",
        "purchase",
        "purchased",
        "receiv",
        "receive",
        "received",
    } & memory_terms
    object_context = {
        "book",
        "card",
        "gift",
        "item",
        "items",
        "necklace",
        "object",
        "photo",
        "picture",
        "ticket",
        "tickets",
    } & memory_terms
    exchange_action_family_count = len(
        {
            _exchange_action_family(action)
            for action in exchange_actions
            if _exchange_action_family(action)
        }
    )
    return bool(
        exchange_action_family_count >= 2
        or (exchange_actions and object_context)
        or (exchange_actions and _DIRECT_EXCHANGE_SURFACE_RE.search(memory_text))
    )


def _exchange_action_family(action: str) -> str:
    if action in {"bought", "buy", "get", "got", "purchas", "purchase", "purchased"}:
        return "acquire"
    if action in {"bring", "brought"}:
        return "bring"
    if action in {"gave", "gift", "give"}:
        return "give"
    if action in {"offer", "offered"}:
        return "offer"
    if action in {"receiv", "receive", "received"}:
        return "receive"
    return ""


def _has_causal_support(memory_terms: set[str]) -> bool:
    direct_cause = {"because", "cause", "caused"} & memory_terms
    decision_surface = {"choose", "chose", "decide", "decision"} & memory_terms
    reason_surface = {"reason", "fit", "value"} & memory_terms
    realization_surface = {"realize", "realized", "understood"} & memory_terms
    help_surface = {"help", "helped", "helps"} & memory_terms
    response_surface = {
        "amaz",
        "amazing",
        "awesome",
        "feel",
        "felt",
        "lovely",
        "reaction",
        "response",
        "think",
        "thought",
    } & memory_terms
    causal_context = {
        "accept",
        "adopt",
        "adoption",
        "agency",
        "balance",
        "because",
        "create",
        "creating",
        "family",
        "fit",
        "help",
        "important",
        "inclusivity",
        "kid",
        "kids",
        "lgbtq",
        "mom",
        "present",
        "refresh",
        "refreshes",
        "routine",
        "support",
    } & memory_terms
    return bool(
        direct_cause
        or (decision_surface and causal_context)
        or (reason_surface and causal_context)
        or (realization_surface and causal_context)
        or (help_surface and causal_context)
        or (response_surface and causal_context)
    )


_STATUS_PROFILE_RELATION_RE = re.compile(
    r"\b(?:my|his|her|their|our|your)\s+"
    r"(?:boyfriend|boss|brother|child|children|colleague|cousin|coworker|daughter|"
    r"father|fiancee?|friend|girlfriend|grandfather|grandmother|husband|kid|kids|manager|mentor|"
    r"mother|neighbor|parent|partner|roommate|sibling|sister|son|spouse|"
    r"teammate|wife)\b"
    r"|\b[A-Z][a-zA-Z0-9_-]+\s+(?:is|was|are|were)\s+"
    r"[A-Z][a-zA-Z0-9_-]+(?:'s|’s)\s+"
    r"(?:boyfriend|boss|brother|child|children|colleague|cousin|coworker|daughter|"
    r"father|fiancee?|friend|girlfriend|grandfather|grandmother|husband|kid|kids|manager|mentor|"
    r"mother|neighbor|parent|partner|roommate|sibling|sister|son|spouse|"
    r"teammate|wife)\b"
    r"|\b[A-Z][a-zA-Z0-9_-]+(?:'s|’s)\s+"
    r"(?:boyfriend|boss|brother|child|children|colleague|cousin|coworker|daughter|"
    r"father|fiancee?|friend|girlfriend|grandfather|grandmother|husband|kid|kids|manager|mentor|"
    r"mother|neighbor|parent|partner|roommate|sibling|sister|son|spouse|"
    r"teammate|wife)\s+(?:is|was|are|were)\s+"
    r"[A-Z][a-zA-Z0-9_-]+\b"
    r"|\b[A-Z][a-zA-Z0-9_-]+(?:'s|’s)\s+"
    r"(?:boyfriend|boss|brother|child|children|colleague|cousin|coworker|daughter|"
    r"father|fiancee?|friend|girlfriend|grandfather|grandmother|husband|kid|kids|manager|mentor|"
    r"mother|neighbor|parent|partner|roommate|sibling|sister|son|spouse|"
    r"teammate|wife)[,;:]\s+[A-Z][a-zA-Z0-9_-]+\b"
    r"|\b(?:is|was|are|were)\s+"
    r"(?:my|his|her|their|our|your)\s+"
    r"(?:boyfriend|boss|brother|child|colleague|cousin|coworker|daughter|father|"
    r"fiancee?|friend|girlfriend|grandfather|grandmother|husband|manager|mentor|mother|neighbor|"
    r"parent|partner|roommate|sibling|sister|son|spouse|teammate|wife)\b"
    r"|\b(?:dating|engaged\s+to|married\s+to)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|my|his|her|their|our|your)\b"
    r"|\b(?:relationship\s+status|status)\s+(?:is|was)\s+"
    r"(?:single|dating|engaged|married|divorced)\b",
    re.IGNORECASE,
)


def _has_status_profile_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    explicit_status = {
        "breakup",
        "dating",
        "divorce",
        "divorced",
        "engag",
        "engaged",
        "engagement",
        "marriage",
        "married",
        "single",
    } & memory_terms
    direct_relation = {
        "boyfriend",
        "boss",
        "brother",
        "child",
        "children",
        "colleague",
        "cousin",
        "coworker",
        "daughter",
        "father",
        "fiance",
        "fiancee",
        "friend",
        "friends",
        "girlfriend",
        "grandfather",
        "grandmother",
        "husband",
        "kid",
        "kids",
        "manager",
        "mentor",
        "mother",
        "neighbor",
        "parent",
        "partner",
        "roommate",
        "sibling",
        "sister",
        "son",
        "spouse",
        "teammate",
        "wife",
    } & memory_terms
    return bool(
        explicit_status
        or (direct_relation and _STATUS_PROFILE_RELATION_RE.search(memory_text))
    )


_LOCATION_TRANSITION_SURFACE_RE = re.compile(
    r"\b(?:move|moved|moving|relocate|relocated|relocating)\s+"
    r"(?:back\s+)?(?:from|to|into|out\s+of)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)",
)
_LOCATION_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:live|lived|living|stay|stayed|staying|based)\s+"
    r"(?:in|at|near|around)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    r"|\b(?:from|born\s+in|grew\s+up\s+in)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    r"|\braised\s+(?:in|near|around)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    r"|\bhometown\s+(?:is|was|in)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)",
)


def _has_location_transition_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    movement_action = {
        "move",
        "moved",
        "moving",
        "relocate",
        "relocated",
        "relocat",
    } & memory_terms
    origin_context = {
        "city",
        "country",
        "from",
        "home",
        "origin",
        "place",
    } & memory_terms
    location_profile_action = {
        "live",
        "lived",
        "living",
        "based",
        "bas",
        "stay",
        "stayed",
        "staying",
    } & memory_terms
    location_profile_context = {
        "city",
        "conference",
        "country",
        "home",
        "hotel",
        "place",
    } & memory_terms
    origin_profile_surface = {
        "born",
        "childhood",
        "from",
        "grew",
        "hometown",
        "origin",
        "originally",
        "rais",
        "raise",
    } & memory_terms
    travel_surface = {"drive", "roadtrip", "travel", "trip"} & memory_terms
    travel_context = {
        "city",
        "country",
        "from",
        "home",
        "origin",
        "place",
        "road",
    } & memory_terms
    return bool(
        (movement_action and origin_context)
        or (movement_action and _LOCATION_TRANSITION_SURFACE_RE.search(memory_text))
        or (location_profile_action and location_profile_context)
        or (origin_profile_surface and origin_context)
        or _LOCATION_PROFILE_SURFACE_RE.search(memory_text)
        or (travel_surface and travel_context)
    )


def _has_preference_support(memory_terms: set[str]) -> bool:
    preference_action = {
        "enjoy",
        "enjoyed",
        "fan",
        "favorite",
        "favourite",
        "interest",
        "interested",
        "like",
        "liked",
        "love",
        "loved",
        "prefer",
        "preferred",
    } & memory_terms
    preference_context = {
        "animal",
        "animals",
        "bach",
        "book",
        "books",
        "camp",
        "campfire",
        "camping",
        "classic",
        "company",
        "color",
        "exhibit",
        "family",
        "food",
        "hike",
        "kid",
        "kids",
        "marshmallow",
        "meteor",
        "mozart",
        "music",
        "outdoor",
        "outdoors",
        "park",
        "restaurant",
        "song",
        "songs",
        "story",
        "summer",
    } & memory_terms
    outdoor_context = {"camp", "camping", "outdoor", "outdoors", "park"} & memory_terms
    self_care_surface = {"self-care", "relax", "refresh", "refreshes", "routine"} & memory_terms
    self_care_context = {"balance", "family", "present", "wellness"} & memory_terms
    durable_outdoor_context = {
        "campfire",
        "marshmallow",
        "meteor",
        "story",
        "summer",
    } & memory_terms
    return bool(
        (preference_action and preference_context)
        or (outdoor_context and durable_outdoor_context)
        or (self_care_surface and self_care_context)
    )


_FAVORITE_PREFERENCE_SURFACE_RE = re.compile(
    r"\b(?:my|his|her|their|our|your)\s+go-to\s+"
    r"(?:book|choice|color|food|music|place|restaurant|song|spot)\s+"
    r"(?:is|was)\b"
    r"|\bgo-to\s+(?:book|choice|color|food|music|place|restaurant|song|spot)\b",
    re.IGNORECASE,
)


def _has_favorite_preference_support(
    memory_terms: set[str],
    *,
    memory_text: str = "",
) -> bool:
    favorite_surface = {"favorite", "favourite"} & memory_terms
    favorite_context = {
        "book",
        "choice",
        "color",
        "food",
        "music",
        "restaurant",
        "song",
    } & memory_terms
    return bool(
        (favorite_surface and favorite_context)
        or _FAVORITE_PREFERENCE_SURFACE_RE.search(memory_text)
    )


def _has_contrast_support(memory_terms: set[str]) -> bool:
    current_surface = {
        "current",
        "currently",
        "now",
        "ongoing",
        "present",
        "still",
        "today",
    } & memory_terms
    stale_surface = {
        "before",
        "changed",
        "earlier",
        "former",
        "formerly",
        "past",
        "previous",
        "previously",
        "used",
    } & memory_terms
    contrast_surface = {
        "alternative",
        "but",
        "compare",
        "different",
        "difference",
        "however",
        "instead",
        "rather",
        "whereas",
    } & memory_terms
    return bool(
        (current_surface and stale_surface)
        or (contrast_surface and current_surface and stale_surface)
        or (contrast_surface and {"before", "earlier", "previous", "used"} & memory_terms)
    )


def _has_activity_support(memory_terms: set[str]) -> bool:
    concrete_activity = {
        "camp",
        "camping",
        "music",
        "paint",
        "painting",
        "pottery",
        "read",
        "reading",
        "run",
        "running",
        "song",
        "songs",
        "swim",
        "swimming",
        "violin",
    } & memory_terms
    creative_context = {"creative", "express", "fun", "hobby"} & memory_terms
    hike_surface = {"hik", "hike", "hiking"} & memory_terms
    hike_occurrence_context = {
        "photo",
        "pic",
        "spot",
        "summer",
        "water",
        "waterfall",
        "weekend",
        "went",
    } & memory_terms
    roadtrip_surface = {"roadtrip", "trip"} & memory_terms
    roadtrip_occurrence_context = {
        "accident",
        "bad",
        "forest",
        "road",
        "scared",
        "start",
    } & memory_terms
    book_surface = {"book", "books", "bookshelf"} & memory_terms
    book_context = {"classic", "culture", "educational", "kid", "kids", "story"} & memory_terms
    return bool(
        concrete_activity
        or ({"class"} & memory_terms and creative_context)
        or (hike_surface and hike_occurrence_context)
        or (roadtrip_surface and roadtrip_occurrence_context)
        or (book_surface and book_context)
    )


def _has_current_goal_support(memory_terms: set[str]) -> bool:
    if {"goal", "future"} <= memory_terms:
        return True
    if "goal" in memory_terms and {"next", "plan", "soon"} & memory_terms:
        return True
    if {"hope", "plan"} <= memory_terms:
        return True
    if {"planned", "soon"} <= memory_terms:
        return True
    if "want" in memory_terms and {"goal", "future", "plan", "soon"} & memory_terms:
        return True
    return bool("plan" in memory_terms and {"future", "next", "soon"} & memory_terms)


def _has_support_goal_support(memory_terms: set[str]) -> bool:
    support_action = {
        "got",
        "help",
        "helped",
        "receive",
        "received",
        "support",
    } & memory_terms
    development_context = {
        "difference",
        "grow",
        "growing",
        "huge",
        "improv",
        "improved",
        "journey",
        "life",
    } & memory_terms
    counseling_context = {
        "counsel",
        "counseling",
        "group",
        "health",
        "mental",
    } & memory_terms
    book_self_discovery = {"book"} & memory_terms and {
        "discover",
        "guide",
        "help",
        "motivate",
    } & memory_terms
    counseling_career = counseling_context and {"job", "jobs"} & memory_terms and {
        "important",
        "people",
        "talk",
    } & memory_terms
    adoption_context = {"adopt", "adoption", "agencies", "agency"} & memory_terms
    inclusive_context = {
        "inclusive",
        "inclusivity",
        "kids",
        "lgbtq",
        "support",
    } & memory_terms
    adoption_outcome = {"family", "kid"} & memory_terms and {
        "amaz",
        "amazing",
        "awesome",
        "creat",
        "lovely",
        "mom",
    } & memory_terms
    return bool(
        (support_action and development_context and counseling_context)
        or book_self_discovery
        or counseling_career
        or (adoption_context and (support_action or inclusive_context))
        or adoption_outcome
    )


def _has_identity_profile_support(memory_terms: set[str]) -> bool:
    visual_identity = {"transgender", "pride", "flag", "mural"} <= memory_terms and {
        "inspir",
        "story",
        "support",
    } & memory_terms
    political_context = (
        {"conservative", "hike", "upset"} <= memory_terms
        and {"lgbtq", "right", "work"} <= memory_terms
        and {"accept", "support"} <= memory_terms
    )
    religious_context = {"church", "conservative", "journey"} <= memory_terms and {
        "acceptance",
        "chang",
        "faith",
        "think",
    } & memory_terms
    community_support = (
        {"lgbtq", "right", "support"} <= memory_terms
        or {"lgbtq+", "adoption", "inclusivity", "support"} <= memory_terms
        or {"community", "ally", "support"} <= memory_terms
    )
    personality_context = (
        {"care", "real", "help"} <= memory_terms
        or {"concern", "thoughtful"} <= memory_terms
    )
    return bool(
        visual_identity
        or political_context
        or religious_context
        or community_support
        or personality_context
    )


_TYPED_SUPPORT_CHECKS: dict[str, Callable[[set[str]], bool]] = {
    "activity": _has_activity_support,
    "age_profile": _has_age_profile_support,
    "alias_profile": _has_alias_profile_support,
    "causal": _has_causal_support,
    "commitment_profile": _has_commitment_profile_support,
    "contact_profile": _has_contact_profile_support,
    "contrast": _has_contrast_support,
    "current_goal": _has_current_goal_support,
    "date_profile": _has_date_profile_support,
    "diet_profile": _has_diet_profile_support,
    "education_profile": _has_education_profile_support,
    "employment_profile": _has_employment_profile_support,
    "emotion_response": _has_emotion_response_support,
    "exchange": _has_exchange_support,
    "health_profile": _has_health_profile_support,
    "identity_profile": _has_identity_profile_support,
    "pet_profile": _has_pet_profile_support,
    "participation_event": _has_participation_event_support,
    "preference": _has_preference_support,
    "registration_event": _has_registration_event_support,
    "skill_profile": _has_skill_profile_support,
    "support_goal": _has_support_goal_support,
    "symbolic_meaning": _has_symbolic_meaning_support,
    "vehicle_profile": _has_vehicle_profile_support,
}
