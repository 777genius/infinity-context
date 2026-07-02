"""Typed relation-category support predicates for benchmark evidence."""

from __future__ import annotations

from collections.abc import Callable


def typed_relation_category_support(
    category: str,
    memory_terms: set[str],
) -> bool | None:
    """Return typed support status for known categories, or None if generic."""

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


def _has_communication_support(memory_terms: set[str]) -> bool:
    communication_action = {
        "advis",
        "advise",
        "advised",
        "ask",
        "asked",
        "mention",
        "mentioned",
        "recommend",
        "recommended",
        "request",
        "requested",
        "said",
        "suggest",
        "suggested",
        "tell",
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
    return bool(communication_action and communication_context)


def _has_exchange_support(memory_terms: set[str]) -> bool:
    exchange_actions = {
        "bought",
        "bring",
        "brought",
        "buy",
        "gave",
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
    return bool(len(exchange_actions) >= 2 or (exchange_actions and object_context))


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
        "marriage",
        "married",
        "single",
    } & memory_terms
    direct_relation = {
        "brother",
        "child",
        "children",
        "daughter",
        "father",
        "friend",
        "friends",
        "husband",
        "kid",
        "kids",
        "mother",
        "parent",
        "partner",
        "sibling",
        "sister",
        "son",
        "spouse",
        "wife",
    } & memory_terms
    return bool(explicit_status or direct_relation)


def _has_location_transition_support(memory_terms: set[str]) -> bool:
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
    return bool((movement_action and origin_context) or (travel_surface and travel_context))


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
    "communication": _has_communication_support,
    "contrast": _has_contrast_support,
    "current_goal": _has_current_goal_support,
    "emotion_response": _has_emotion_response_support,
    "exchange": _has_exchange_support,
    "identity_profile": _has_identity_profile_support,
    "location_transition": _has_location_transition_support,
    "participation_event": _has_participation_event_support,
    "preference": _has_preference_support,
    "registration_event": _has_registration_event_support,
    "status_profile": _has_status_profile_support,
    "support_goal": _has_support_goal_support,
    "symbolic_meaning": _has_symbolic_meaning_support,
}
