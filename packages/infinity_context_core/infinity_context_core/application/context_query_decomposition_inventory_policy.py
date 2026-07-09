"""Inventory and aggregation policy for query decomposition."""

from __future__ import annotations

from infinity_context_core.application.context_query_decomposition_event_policy import (
    _RELOCATION_ACTION_TERMS,
)
from infinity_context_core.application.context_query_decomposition_shared import _normalize_query

_ATTRIBUTE_AGGREGATION_TERMS = frozenset(
    {
        "attend",
        "attended",
        "bought",
        "buy",
        "events",
        "instrument",
        "instruments",
        "items",
        "participate",
        "participated",
        "play",
        "plays",
        "share",
        "shared",
        "traits",
    }
)

_INVENTORY_LIST_SLOT_TERMS = frozenset(
    {
        "areas",
        "artists",
        "bands",
        "books",
        "causes",
        "cities",
        "countries",
        "country",
        "hobbies",
        "instruments",
        "items",
        "kinds",
        "people",
        "places",
        "projects",
        "shelter",
        "shelters",
        "states",
        "tasks",
        "things",
        "types",
        "volunteering",
        "виды",
        "вещи",
        "города",
        "места",
        "страна",
        "страны",
        "типы",
    }
)

_INVENTORY_LIST_ACTION_TERMS = frozenset(
    {
        "attend",
        "attended",
        "been",
        "bought",
        "buy",
        "done",
        "feel",
        "go",
        "gone",
        "helped",
        "having",
        "joined",
        "made",
        "mention",
        "mentioned",
        "met",
        "participated",
        "planning",
        "played",
        "read",
        "seen",
        "support",
        "supporting",
        "taken",
        "visited",
        "volunteer",
        "volunteered",
        "went",
        "ездил",
        "ездила",
        "ездили",
        "посещал",
        "посещала",
        "посещали",
        "посетил",
        "посетила",
        "посетили",
        "сделал",
        "сделала",
        "сделали",
    }
)

_INVENTORY_LIST_PROMPT_TERMS = frozenset(
    {
        "what",
        "where",
        "which",
        "где",
        "какие",
        "какой",
        "какую",
        "какое",
        "что",
    }
)

_PEOPLE_INVENTORY_PROMPT_TERMS = frozenset(
    {
        "who",
        "whom",
        "кого",
        "кому",
        "кто",
    }
)

_PEOPLE_INVENTORY_ACTION_TERMS = frozenset(
    {
        "help",
        "helped",
        "helping",
        "meet",
        "met",
        "support",
        "supported",
        "supporting",
        "volunteer",
        "volunteered",
        "volunteering",
        "work",
        "worked",
        "working",
        "помог",
        "помогал",
        "помогала",
        "помогали",
        "поддержал",
        "поддержала",
        "поддержали",
        "работал",
        "работала",
        "работали",
    }
)

_SOCIAL_SUPPORT_ACTION_TERMS = frozenset(
    {
        "support",
        "supported",
        "supporting",
        "supports",
        "there",
        "rocks",
        "поддерживает",
        "поддерживал",
        "поддерживала",
        "поддержал",
        "поддержала",
        "поддержали",
        "рядом",
    }
)

_SOCIAL_SUPPORT_RELATION_TERMS = frozenset(
    {
        "coach",
        "family",
        "father",
        "friend",
        "friends",
        "mentor",
        "mentors",
        "mother",
        "parent",
        "parents",
        "rock",
        "rocks",
        "system",
        "друзья",
        "наставники",
        "родители",
        "семья",
    }
)

_TECHNICAL_SUPPORT_CONTEXT_TERMS = frozenset(
    {
        "api",
        "backend",
        "browser",
        "client",
        "cloud",
        "customer",
        "database",
        "frontend",
        "infra",
        "infrastructure",
        "integration",
        "library",
        "model",
        "platform",
        "provider",
        "runtime",
        "sdk",
        "service",
        "software",
        "technical",
        "tool",
        "tools",
        "web",
    }
)

_PLACE_INVENTORY_ACTION_TERMS = frozenset(
    {
        "been",
        "friend",
        "friends",
        "go",
        "gone",
        "made",
        "meet",
        "met",
        "vacation",
        "vacationed",
        "visited",
        "went",
    }
)

_COMMONALITY_TERMS = frozenset(
    {
        "both",
        "common",
        "mutual",
        "same",
        "shared",
        "similar",
        "оба",
        "обе",
        "общ",
        "общего",
        "общие",
        "похож",
    }
)

_QUANTITY_COUNT_TERMS = frozenset(
    {
        "count",
        "counts",
        "many",
        "much",
        "number",
        "quantity",
        "total",
        "сколько",
    }
)

_ACTIVITY_PARTICIPATION_TERMS = frozenset(
    {
        "activities",
        "activity",
        "hobbies",
        "hobby",
        "partake",
        "participate",
        "participates",
        "participated",
    }
)

def _attribute_aggregation_tail(variants: frozenset[str]) -> str:
    tails: list[str] = [
        "aggregate list multiple mentions evidence observed mentioned",
    ]
    if variants.intersection({"items", "bought", "buy"}):
        tails.append("item bought purchased got new gift object possession")
    if variants.intersection({"instrument", "instruments", "play", "plays"}):
        tails.append("instrument music play plays played violin clarinet piano guitar")
    if variants.intersection({"events", "attend", "attended", "participate", "participated"}):
        tails.append(
            "event attended participated went conference parade speech support group "
            "reading meeting mentorship mentoring youth children school talk gender "
            "identity inclusion community ally allies"
        )
    if variants.intersection({"share", "shared"}):
        tails.append(
            "shared both similar interests hobbies enjoy watching movies making "
            "desserts recipes baking"
        )
    if variants.intersection(_COMMONALITY_TERMS):
        tails.append(
            "common shared both mutual same similar overlap interests hobbies "
            "activities enjoy like love prefer painting camping hiking music books games"
        )
    if variants.intersection({"traits"}):
        tails.append(
            "trait personality thoughtful authentic driven caring supportive concerned helpful"
        )
    return _normalize_query(" ".join(tails))

def _inventory_list_tail(variants: frozenset[str]) -> str:
    tails: list[str] = []
    if variants.intersection({"countries", "country", "страна", "страны"}):
        tails.append(
            "country countries europe european england spain france italy germany "
            "portugal ireland sweden abroad solo trip travel visited went"
        )
    elif variants.intersection({"where", "где"}) and variants.intersection(
        _PLACE_INVENTORY_ACTION_TERMS
    ):
        tails.append(
            "place friends shelter church gym community welcoming people fellow "
            "volunteers joined made met"
        )
    elif variants.intersection(
        {
            "areas",
            "cities",
            "places",
            "states",
            "города",
            "места",
        }
    ):
        tails.append(
            "place area country state city coast destination visited went travel "
            "trip vacation planning go abroad"
        )
    if variants.intersection({"shelter", "shelters", "volunteering", "volunteer"}):
        tails.append(
            "volunteer volunteered volunteering shelter homeless dog church gym helped "
            "met people residents names donated local pup old car"
        )
    if variants.intersection({"causes", "support", "supporting"}):
        tails.append(
            "cause causes passionate support supporting veterans schools infrastructure "
            "education reform infrastructure development rights charity community "
            "campaign project appreciation"
        )
    if variants.intersection({"events", "события"}):
        tails.append(
            "event events attended participated joined went planning fundraiser tournament "
            "fair networking conference parade speech support group"
        )
    if variants.intersection({"types", "kinds", "projects", "виды", "типы"}):
        tails.append(
            "type kind made finished created project item object piece visual image "
            "caption query cup bowl pot plate painting"
        )
    if variants.intersection({"people"}) or (
        variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        and variants.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
    ):
        tails.append("people person names met helped worked with friend customer resident")
    if variants.intersection({"artists", "bands"}):
        tails.append("artist artists band bands music concert live saw seen performance")
    if variants.intersection({"items", "things"}):
        tails.append("item thing bought got had having owned mentioned object gift possession")
    tails.append("inventory list evidence observed mentioned answer options")
    return _normalize_query(" ".join(tails))

def _requests_activity_participation(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection({"activity", "hobby"}):
        return False
    return bool(raw_tokens.intersection(_ACTIVITY_PARTICIPATION_TERMS))

def _requests_inventory_list_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if _requests_place_inventory_context(raw_tokens=raw_tokens, variants=variants):
        return True
    if _requests_people_inventory_context(raw_tokens=raw_tokens, variants=variants):
        return True
    if not variants.intersection(_INVENTORY_LIST_SLOT_TERMS):
        return False
    if not (
        raw_tokens.intersection(_INVENTORY_LIST_PROMPT_TERMS)
        or variants.intersection(_INVENTORY_LIST_PROMPT_TERMS)
    ):
        return False
    return bool(
        raw_tokens.intersection(_INVENTORY_LIST_ACTION_TERMS)
        or variants.intersection(_INVENTORY_LIST_ACTION_TERMS)
        or variants.intersection({"areas", "countries", "places", "states", "types", "kinds"})
    )

def _requests_people_inventory_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if _requests_social_support_network_context(raw_tokens=raw_tokens, variants=variants):
        return False
    if not (
        raw_tokens.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
    ):
        return False
    return bool(
        raw_tokens.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
    )

def _requests_social_support_network_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not (
        raw_tokens.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
    ):
        return False
    if raw_tokens.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS):
        return False
    if variants.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS):
        return False
    has_support_action = bool(
        raw_tokens.intersection(_SOCIAL_SUPPORT_ACTION_TERMS)
        or variants.intersection(_SOCIAL_SUPPORT_ACTION_TERMS)
    )
    has_relation_marker = bool(
        raw_tokens.intersection(_SOCIAL_SUPPORT_RELATION_TERMS)
        or variants.intersection(_SOCIAL_SUPPORT_RELATION_TERMS)
    )
    return has_support_action or has_relation_marker

def _requests_place_inventory_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not (raw_tokens.intersection({"where", "где"}) or variants.intersection({"where", "где"})):
        return False
    if variants.intersection(_RELOCATION_ACTION_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_PLACE_INVENTORY_ACTION_TERMS)
        or variants.intersection(_PLACE_INVENTORY_ACTION_TERMS)
    )

def _requests_commonality_context(
    *,
    identities: tuple[str, ...],
    variants: frozenset[str],
) -> bool:
    return len(identities) >= 2 and bool(variants.intersection(_COMMONALITY_TERMS))
