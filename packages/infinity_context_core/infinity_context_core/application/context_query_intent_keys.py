"""Identity and event-key policies for query anchor intent matching."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key_for_kind,
    normalize_anchor_key,
)
from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.application.context_query_intent_common import (
    _bounded_unique,
    _metadata_text,
)
from infinity_context_core.domain.entities import MemoryAnchor, MemoryAnchorKind

_EVENT_TYPE_GROUPS: Mapping[str, frozenset[str]] = {
    "call": frozenset(
        {
            "call",
            "zvonok",
            "sozvon",
            "sozvona",
            "sozvanivalas",
            "sozvanivalis",
            "sozvanivalsya",
            "pozvonil",
            "pozvonila",
            "zvonil",
            "zvonila",
        }
    ),
    "relocation": frozenset(
        {
            "move",
            "moved",
            "moving",
            "relocate",
            "relocated",
            "relocation",
            "pereehala",
            "pereehali",
            "pereehal",
            "pereezd",
            "pereezzhala",
            "pereezzhali",
            "pereezzhal",
        }
    ),
    "activity": frozenset(
        {
            "attend",
            "attended",
            "hike",
            "hiked",
            "hikes",
            "hiking",
            "join",
            "joined",
            "live",
            "lived",
            "lives",
            "living",
            "participate",
            "participated",
            "play",
            "played",
            "playing",
            "practice",
            "practiced",
            "practicing",
            "rabotaet",
            "rabotal",
            "rabotala",
            "run",
            "running",
            "runs",
            "train",
            "trained",
            "training",
            "uchastvuet",
            "volunteer",
            "volunteered",
            "volunteering",
            "volunteers",
            "work",
            "worked",
            "working",
            "works",
            "went",
            "zhila",
            "zhili",
            "zhil",
            "zhivet",
        }
    ),
    "message": frozenset(
        {
            "chat",
            "chatted",
            "conversation",
            "discussed",
            "dm",
            "direct message",
            "message",
            "messaged",
            "obschalas",
            "obschalis",
            "obschalsya",
            "sent",
            "spoke",
            "talked",
            "texted",
            "wrote",
            "napisal",
            "napisala",
            "napisali",
            "otpravil",
            "otpravila",
            "otpravili",
            "otvetil",
            "otvetila",
            "otvetili",
            "perepiska",
            "perepiske",
            "perepiski",
            "perepisku",
            "perepiskoi",
            "perepisyvalas",
            "perepisyvalis",
            "perepisyvalsya",
            "razgovor",
            "rasskazal",
            "rasskazala",
            "rasskazali",
            "said",
            "skinul",
            "skinula",
            "skinuli",
            "skazal",
            "skazala",
            "skazali",
            "soobschil",
            "soobschila",
            "soobschili",
            "told",
            "prislal",
            "prislala",
            "prislali",
        }
    ),
    "meeting": frozenset(
        {
            "meeting",
            "meet",
            "met",
            "vstrecha",
            "vstretilsya",
            "vstretilas",
            "vstrechalsya",
            "vstrechalas",
            "vstrechalis",
        }
    ),
    "review": frozenset({"review", "revyu"}),
    "sync": frozenset(
        {
            "sync",
            "standup",
            "planning",
            "planerka",
            "stendap",
            "retro",
            "retrospective",
        }
    ),
    "demo": frozenset({"demo", "presentation", "prezentatsiya"}),
    "workshop": frozenset({"workshop", "vorkshop", "interview", "interviews", "intervyu"}),
    "launch": frozenset({"launch", "release", "zapusk", "reliz"}),
    "workflow": frozenset(
        {
            "deadline",
            "deliverable",
            "due",
            "milestone",
            "reminder",
            "task",
            "todo",
            "dedlain",
            "mailstoun",
            "napominanie",
            "poruchenie",
            "srok",
            "zadacha",
        }
    ),
}

_EVENT_TYPE_TO_GROUP = {
    value: group for group, values in _EVENT_TYPE_GROUPS.items() for value in values
}

_BROAD_CONVERSATION_EVENT_TYPES = frozenset({"conversation"})

_CONVERSATIONAL_EVENT_GROUP_KEYS = frozenset(
    {"group:call", "group:meeting", "group:message", "group:sync"}
)

def _anchor_identity_keys(anchor: MemoryAnchor) -> frozenset[str]:
    keys: set[str] = set()
    for key in (
        "canonical_key",
        "person_canonical_key",
        "project_canonical_key",
        "organization_canonical_key",
        "identity_key",
    ):
        keys.update(_metadata_identity_terms(anchor.metadata.get(key)))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.label))
    for alias in anchor.aliases:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, alias))
    if anchor.normalized_key:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.normalized_key))
    if anchor.kind == MemoryAnchorKind.PROJECT:
        keys.update(_project_key_aliases(tuple(keys)))
    value = anchor.metadata.get("event_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    value = anchor.metadata.get("alias_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    return frozenset(key for key in keys if key)

def _observed_anchor_identity_keys(anchor: ObservedAnchor) -> frozenset[str]:
    keys: set[str] = set()
    keys.update(_metadata_identity_terms(anchor.metadata.get("canonical_key")))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.label))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.normalized_key))
    for alias in anchor.aliases:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, alias))
    value = anchor.metadata.get("alias_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    if anchor.kind == MemoryAnchorKind.PROJECT:
        keys.update(_project_key_aliases(tuple(keys)))
    return frozenset(key for key in keys if key)

def _event_type_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    if _metadata_text(metadata.get("extraction_reason")) == "event query temporal hint":
        return frozenset()
    event_type = _metadata_text(metadata.get("event_type_canonical") or metadata.get("event_type"))
    if not event_type:
        return frozenset()
    keys = {event_type}
    if group := _EVENT_TYPE_TO_GROUP.get(event_type):
        keys.add(f"group:{group}")
    return frozenset(keys)

def _event_type_keys_conflict(
    *,
    query_event_type_keys: frozenset[str],
    anchor_event_type_keys: frozenset[str],
) -> bool:
    if not query_event_type_keys or not anchor_event_type_keys:
        return False
    query_groups = {key for key in query_event_type_keys if key.startswith("group:")}
    anchor_groups = {key for key in anchor_event_type_keys if key.startswith("group:")}
    if query_groups and anchor_groups:
        if _event_type_groups_are_compatible(
            query_event_type_keys=query_event_type_keys,
            anchor_groups=frozenset(anchor_groups),
        ):
            return False
        return not query_groups.intersection(anchor_groups)
    return False

def _event_type_groups_are_compatible(
    *,
    query_event_type_keys: frozenset[str],
    anchor_groups: frozenset[str],
) -> bool:
    if query_event_type_keys.intersection(_BROAD_CONVERSATION_EVENT_TYPES):
        return bool(anchor_groups.intersection(_CONVERSATIONAL_EVENT_GROUP_KEYS))
    return False

def _storage_lookup_key_variants(
    kind: MemoryAnchorKind,
    value: str,
) -> tuple[str, ...]:
    normalized = normalize_anchor_key(value)
    if not normalized:
        return ()
    variants = [normalized]
    if kind == MemoryAnchorKind.PERSON:
        variants.append(
            " ".join(normalize_cyrillic_person_case(part) for part in normalized.split() if part)
        )
    elif kind == MemoryAnchorKind.PROJECT:
        variants.append(
            " ".join(normalize_cyrillic_project_case(part) for part in normalized.split() if part)
        )
    return tuple(_bounded_unique(variants, limit=4))

def _temporal_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    keys: set[str] = set()
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_temporal_hint_code",
            quantity_key="event_temporal_quantity",
            unit_key="event_temporal_unit",
        )
    )
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_duration_hint_code",
            quantity_key="event_duration_quantity",
            unit_key="event_duration_unit",
        )
    )
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_recurrence_hint_code",
            quantity_key="event_recurrence_quantity",
            unit_key="event_recurrence_unit",
        )
    )
    return frozenset(keys)

def _event_time_identity_keys(
    metadata: Mapping[str, object],
    *,
    hint_key: str,
    quantity_key: str,
    unit_key: str,
) -> frozenset[str]:
    hint_code = _metadata_text(metadata.get(hint_key))
    if not hint_code:
        return frozenset()
    quantity = _metadata_text(metadata.get(quantity_key))
    unit = _metadata_text(metadata.get(unit_key))
    keys = {hint_code}
    if quantity and unit:
        keys.add(f"{hint_code}:{quantity}:{unit}")
    value = metadata.get("event_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            text = _metadata_text(item)
            if text.startswith(f"{hint_code}:"):
                keys.add(text)
    return frozenset(keys)

def _temporal_keys_conflict(
    *,
    query_temporal_keys: frozenset[str],
    anchor_temporal_keys: frozenset[str],
) -> bool:
    if not query_temporal_keys:
        return False
    if "relative_recent" in anchor_temporal_keys:
        return False
    if _exact_cadence_or_duration_mismatch(query_temporal_keys, anchor_temporal_keys):
        return True
    return not anchor_temporal_keys.intersection(query_temporal_keys)

def _exact_cadence_or_duration_mismatch(
    query_temporal_keys: frozenset[str],
    anchor_temporal_keys: frozenset[str],
) -> bool:
    query_exact = _exact_cadence_or_duration_keys(query_temporal_keys)
    anchor_exact = _exact_cadence_or_duration_keys(anchor_temporal_keys)
    if not query_exact or not anchor_exact:
        return False
    for code in {key.split(":", 1)[0] for key in query_exact}.intersection(
        key.split(":", 1)[0] for key in anchor_exact
    ):
        query_for_code = {key for key in query_exact if key.startswith(f"{code}:")}
        anchor_for_code = {key for key in anchor_exact if key.startswith(f"{code}:")}
        if query_for_code and anchor_for_code and not query_for_code.intersection(anchor_for_code):
            return True
    return False

def _exact_cadence_or_duration_keys(keys: frozenset[str]) -> frozenset[str]:
    prefixes = (
        "duration_for:",
        "duration_since_year:",
        "recurrence_every:",
        "recurrence_per:",
    )
    return frozenset(key for key in keys if key.startswith(prefixes))

def _metadata_identity_terms(value: object) -> tuple[str, ...]:
    text = _metadata_text(value)
    if not text:
        return ()
    if ":" in text:
        return tuple(
            _bounded_unique(
                (
                    text,
                    text.rsplit(":", 1)[-1],
                    *_identity_term_variants(text),
                    *_identity_term_variants(text.rsplit(":", 1)[-1]),
                )
            )
        )
    return tuple(_identity_term_variants(text))

def _identity_term_variants(value: str) -> frozenset[str]:
    text = _metadata_text(value)
    if not text:
        return frozenset()
    spaced = " ".join(part for part in text.replace("_", " ").split() if part)
    person_normalized = " ".join(
        normalize_cyrillic_person_case(part) for part in spaced.split() if part
    )
    project_normalized = " ".join(
        normalize_cyrillic_project_case(part) for part in spaced.split() if part
    )
    canonical = " ".join(canonical_token(part) for part in spaced.split() if part)
    person_canonical = " ".join(
        canonical_token(part) for part in person_normalized.split() if part
    )
    project_canonical = " ".join(
        canonical_token(part) for part in project_normalized.split() if part
    )
    return frozenset(
        term
        for term in (
            text,
            spaced,
            canonical,
            person_normalized,
            project_normalized,
            person_canonical,
            project_canonical,
        )
        if term
    )

def _compatible_identity_matches(
    anchor_keys: Iterable[str],
    query_keys: Iterable[str],
) -> tuple[str, ...]:
    anchor_set = frozenset(key for key in anchor_keys if key)
    query_set = frozenset(key for key in query_keys if key)
    exact = sorted(anchor_set.intersection(query_set))
    if exact:
        return tuple(exact[:8])
    matches: list[str] = []
    for anchor_key in sorted(anchor_set):
        for query_key in sorted(query_set):
            if _identity_key_prefix_compatible(anchor_key, query_key):
                matches.append(anchor_key)
                break
        if len(matches) >= 8:
            break
    return tuple(_bounded_unique(matches, limit=8))

def _identity_key_prefix_compatible(left: str, right: str) -> bool:
    left_parts = left.split()
    right_parts = right.split()
    if not left_parts or not right_parts:
        return False
    shorter, longer = (
        (left_parts, right_parts)
        if len(left_parts) <= len(right_parts)
        else (right_parts, left_parts)
    )
    if len(shorter) > len(longer):
        return False
    if longer[: len(shorter)] != shorter:
        return False
    return len(shorter) >= 2 or len(longer) <= 3

def _project_key_aliases(keys: tuple[str, ...]) -> frozenset[str]:
    aliases: set[str] = set()
    for key in keys:
        parts = key.split()
        if len(parts) >= 2 and parts[0] in {
            "project",
            "repo",
            "repository",
            "service",
            "проект",
        }:
            aliases.add(" ".join(parts[1:]))
    return frozenset(aliases)
