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
        "grandma",
        "necklace",
        "root",
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


_TYPED_SUPPORT_CHECKS: dict[str, Callable[[set[str]], bool]] = {
    "activity": _has_activity_support,
    "communication": _has_communication_support,
    "emotion_response": _has_emotion_response_support,
    "exchange": _has_exchange_support,
    "participation_event": _has_participation_event_support,
    "registration_event": _has_registration_event_support,
    "status_profile": _has_status_profile_support,
    "symbolic_meaning": _has_symbolic_meaning_support,
}
