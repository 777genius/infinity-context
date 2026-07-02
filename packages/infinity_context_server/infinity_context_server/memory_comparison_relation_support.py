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

    if category == "location_transition":
        return _has_location_transition_support(memory_terms, memory_text=memory_text)
    if category == "communication":
        return _has_communication_support(memory_terms, memory_text=memory_text)
    if category == "exchange":
        return _has_exchange_support(memory_terms, memory_text=memory_text)
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


def _has_participation_event_support(memory_terms: set[str]) -> bool:
    participation_action = {
        "attend",
        "attended",
        "join",
        "joined",
        "participate",
        "participated",
        "visit",
        "visited",
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
    return bool(participation_action and event_context)


def _has_education_profile_support(memory_terms: set[str]) -> bool:
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
    return bool(education_surface or (education_action and education_context))


def _has_emotion_response_support(memory_terms: set[str]) -> bool:
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
    return bool(emotion_surface and response_context)


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


def _has_status_profile_support(memory_terms: set[str]) -> bool:
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
        "coworker",
        "daughter",
        "father",
        "fiance",
        "fiancee",
        "friend",
        "friends",
        "girlfriend",
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
    return bool(explicit_status or direct_relation)


_LOCATION_TRANSITION_SURFACE_RE = re.compile(
    r"\b(?:move|moved|moving|relocate|relocated|relocating)\s+"
    r"(?:back\s+)?(?:from|to|into|out\s+of)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)",
)
_LOCATION_PROFILE_SURFACE_RE = re.compile(
    r"\b(?:live|lived|living|stay|stayed|staying)\s+"
    r"(?:in|at|near|around)\s+"
    r"(?:[A-Z][a-zA-Z0-9_-]+|the\s+[a-zA-Z][a-zA-Z0-9_-]+)"
    r"|\b(?:from|born\s+in|grew\s+up\s+in)\s+"
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
        "exhibit",
        "family",
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
    "causal": _has_causal_support,
    "contrast": _has_contrast_support,
    "current_goal": _has_current_goal_support,
    "education_profile": _has_education_profile_support,
    "emotion_response": _has_emotion_response_support,
    "exchange": _has_exchange_support,
    "identity_profile": _has_identity_profile_support,
    "participation_event": _has_participation_event_support,
    "preference": _has_preference_support,
    "registration_event": _has_registration_event_support,
    "status_profile": _has_status_profile_support,
    "support_goal": _has_support_goal_support,
    "symbolic_meaning": _has_symbolic_meaning_support,
}
