"""Structured query intent for anchor-aware context retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key_for_kind,
    extract_observed_anchors,
    normalize_anchor_key,
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import MemoryAnchor, MemoryAnchorKind

_EVENTISH_QUERY_RE = re.compile(
    r"\b("
    r"call|meeting|review|sync|demo|chat|dm|message|conversation|"
    r"direct message|meet|met|wrote|sent|messaged|texted|said|told|"
    r"standup|planning|retro|retrospective|workshop|interview|release|launch|"
    r"звонок|созвон|встреча|ревью|демо|переписка|переписывался|"
    r"позвонил|позвонила|звонил|звонила|написал|написала|"
    r"сказал|сказала|рассказал|рассказала|"
    r"встретился|встретилась|встречался|встречалась|"
    r"разговор|чат|планерка|планёрка|стендап|ретро|интервью|воркшоп|релиз|запуск"
    r")\b",
    re.IGNORECASE,
)
_RELATIVE_TIME_RE = re.compile(
    r"\b("
    r"earlier today|this morning|this afternoon|this evening|"
    r"last week|previous week|week ago|yesterday|today|tomorrow|an hour ago|hour ago|"
    r"(?:\d{1,3}|one|two|three|four|five|six)\s+hours?\s+ago|"
    r"\d{1,3}\s+days?\s+ago|"
    r"\d{1,2}\s+weeks?\s+ago|"
    r"ранее сегодня|сегодня утром|утром сегодня|"
    r"сегодня д[нн]ём|д[нн]ём сегодня|сегодня днем|днем сегодня|"
    r"сегодня вечером|вечером сегодня|"
    r"неделю назад|на прошлой неделе|прошлой неделе|прошлую неделю|"
    r"вчера|сегодня|завтра|час назад|"
    r"\d{1,3}\s+час(?:а|ов)?\s+назад|"
    r"\d{1,3}\s+д(?:ень|ня|ней)\s+назад|"
    r"\d{1,2}\s+недел[юи]\s+назад"
    r")\b",
    re.IGNORECASE,
)
_LOWER_PERSON_HINT_RE = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    r"(?P<label>@?[a-zа-яё][a-zа-яё0-9._-]{2,39})\b",
    re.IGNORECASE,
)
_LOWER_PROJECT_HINT_RE = re.compile(
    r"\b(?P<prep>about|for|in|по|про|для|в)\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[a-zа-яё0-9][a-zа-яё0-9._-]{1,79})\b",
    re.IGNORECASE,
)
_PERSON_HINT_STOP_WORDS = frozenset(
    {
        "client",
        "customer",
        "team",
        "user",
        "команда",
        "командой",
        "клиент",
        "клиентом",
        "проект",
        "проектом",
        "пользователь",
    }
)
_PROJECT_HINT_STOP_WORDS = frozenset(
    {
        "call",
        "chat",
        "meeting",
        "message",
        "review",
        "sync",
        "звонок",
        "созвон",
        "чат",
        "встреча",
        "переписка",
    }
)
_EVENT_TYPE_GROUPS: Mapping[str, frozenset[str]] = {
    "call": frozenset(
        {
            "call",
            "zvonok",
            "sozvon",
            "pozvonil",
            "pozvonila",
            "zvonil",
            "zvonila",
        }
    ),
    "message": frozenset(
        {
            "chat",
            "conversation",
            "dm",
            "direct message",
            "message",
            "messaged",
            "sent",
            "texted",
            "wrote",
            "napisal",
            "napisala",
            "perepiska",
            "perepisyvalsya",
            "razgovor",
            "rasskazal",
            "rasskazala",
            "said",
            "skazal",
            "skazala",
            "told",
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
    "workshop": frozenset({"workshop", "vorkshop", "interview", "intervyu"}),
    "launch": frozenset({"launch", "release", "zapusk", "reliz"}),
}
_EVENT_TYPE_TO_GROUP = {
    value: group for group, values in _EVENT_TYPE_GROUPS.items() for value in values
}


@dataclass(frozen=True)
class QueryAnchorHint:
    kind: MemoryAnchorKind
    canonical_key: str
    label: str
    reason: str
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class QueryAnchorIntent:
    hints: tuple[QueryAnchorHint, ...]

    @property
    def empty(self) -> bool:
        return not self.hints

    def keys_for_kind(self, kind: MemoryAnchorKind) -> frozenset[str]:
        return frozenset(hint.canonical_key for hint in self.hints if hint.kind == kind)

    def temporal_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_temporal_identity_keys(hint.metadata))
        return frozenset(keys)

    def event_type_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_event_type_identity_keys(hint.metadata))
        return frozenset(keys)

    def diagnostics(self) -> dict[str, object]:
        counts = {
            kind.value: sum(1 for hint in self.hints if hint.kind == kind)
            for kind in MemoryAnchorKind
        }
        return {
            "query_anchor_intent_status": "empty" if self.empty else "available",
            "query_anchor_hint_count": len(self.hints),
            "query_anchor_person_hint_count": counts[MemoryAnchorKind.PERSON.value],
            "query_anchor_event_hint_count": counts[MemoryAnchorKind.EVENT.value],
            "query_anchor_project_hint_count": counts[MemoryAnchorKind.PROJECT.value],
            "query_anchor_organization_hint_count": counts[
                MemoryAnchorKind.ORGANIZATION.value
            ],
            "query_anchor_temporal_hint_count": len(self.temporal_keys()),
            "query_anchor_event_type_hint_count": len(self.event_type_keys()),
            "query_anchor_hint_reasons": _bounded_unique(
                hint.reason for hint in self.hints
            ),
        }


@dataclass(frozen=True)
class QueryAnchorMatch:
    score_boost: float
    reasons: tuple[str, ...]
    matched_keys: tuple[str, ...]

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_anchor_match_score_boost": self.score_boost,
            "query_anchor_match_reasons": list(self.reasons),
            "query_anchor_match_keys": list(self.matched_keys),
        }


@dataclass(frozen=True)
class QueryAnchorLookupKey:
    kind: MemoryAnchorKind
    normalized_key: str


def build_query_anchor_intent(query: str) -> QueryAnchorIntent:
    hints: list[QueryAnchorHint] = []
    seen: set[tuple[str, str]] = set()
    for observed in extract_observed_anchors(query):
        _append_observed_hint(hints, seen, observed)
    if _is_eventish_query(query):
        _append_lowercase_event_hints(hints, seen, query)
        if not _event_temporal_keys(hints):
            _append_temporal_event_hints(hints, seen, query)
    return QueryAnchorIntent(hints=tuple(hints[:16]))


def query_anchor_lookup_keys(intent: QueryAnchorIntent) -> tuple[QueryAnchorLookupKey, ...]:
    keys: list[QueryAnchorLookupKey] = []
    seen: set[tuple[str, str]] = set()
    for hint in intent.hints:
        if (
            hint.kind == MemoryAnchorKind.EVENT
            and _metadata_text(hint.reason) == "event query temporal hint"
        ):
            continue
        for raw_key in (hint.label, hint.canonical_key):
            if raw_key.startswith("event_temporal:"):
                continue
            for normalized_key in _storage_lookup_key_variants(hint.kind, raw_key):
                key = (hint.kind.value, normalized_key)
                if key in seen:
                    continue
                seen.add(key)
                keys.append(
                    QueryAnchorLookupKey(
                        kind=hint.kind,
                        normalized_key=normalized_key,
                    )
                )
                if len(keys) >= 32:
                    return tuple(keys)
    return tuple(keys)


def match_query_anchor_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    if intent.empty:
        return None
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _match_event_anchor(intent, anchor)
    anchor_keys = _anchor_identity_keys(anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    shared = _compatible_identity_matches(anchor_keys, query_keys)
    if not shared:
        return None
    return QueryAnchorMatch(
        score_boost=0.055,
        reasons=(f"query_{anchor.kind.value}_identity_match",),
        matched_keys=tuple(shared[:4]),
    )


def query_anchor_intent_conflicts(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    if intent.empty:
        return False
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _event_anchor_conflicts_intent(intent, anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    if not query_keys:
        return False
    return not _compatible_identity_matches(_anchor_identity_keys(anchor), query_keys)


def _append_observed_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    observed: ObservedAnchor,
) -> None:
    canonical_key = _metadata_text(observed.metadata.get("canonical_key"))
    if not canonical_key:
        canonical_key = canonical_anchor_key_for_kind(observed.kind, observed.label)
    _append_hint(
        hints,
        seen,
        kind=observed.kind,
        canonical_key=canonical_key,
        label=observed.label,
        reason=observed.reason,
        metadata=observed.metadata,
    )


def _append_lowercase_event_hints(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    query: str,
) -> None:
    for match in _LOWER_PERSON_HINT_RE.finditer(query):
        label = match.group("label").lstrip("@")
        if _normalized(label) in _PERSON_HINT_STOP_WORDS:
            continue
        _append_label_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.PERSON,
            label=label,
            reason="event query participant hint",
        )
    for match in _LOWER_PROJECT_HINT_RE.finditer(query):
        label = match.group("label")
        if _normalized(label) in _PROJECT_HINT_STOP_WORDS:
            continue
        _append_label_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=label,
            reason="event query project hint",
        )


def _append_temporal_event_hints(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    query: str,
) -> None:
    for match in _RELATIVE_TIME_RE.finditer(query):
        phrase = match.group(1)
        metadata = structured_anchor_metadata_for_label(
            MemoryAnchorKind.EVENT,
            f"meeting {phrase}",
        )
        temporal_keys = _temporal_identity_keys(metadata)
        if not temporal_keys:
            continue
        strongest_key = sorted(temporal_keys, key=lambda value: (":" not in value, value))[-1]
        _append_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.EVENT,
            canonical_key=f"event_temporal:{strongest_key}",
            label=phrase,
            reason="event query temporal hint",
            metadata={
                "extraction_reason": "event query temporal hint",
                "extractor": "context-query-intent-v1",
                **metadata,
            },
        )


def _append_label_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    label: str,
    reason: str,
) -> None:
    canonical_key = canonical_anchor_key_for_kind(kind, label)
    if not canonical_key:
        return
    _append_hint(
        hints,
        seen,
        kind=kind,
        canonical_key=canonical_key,
        label=label,
        reason=reason,
        metadata={
            "extraction_reason": reason,
            "extractor": "context-query-intent-v1",
            **structured_anchor_metadata_for_label(kind, label),
        },
    )


def _append_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    canonical_key: str,
    label: str,
    reason: str,
    metadata: Mapping[str, object],
) -> None:
    safe_key = _metadata_text(canonical_key)
    if not safe_key:
        return
    key = (kind.value, safe_key)
    if key in seen:
        return
    seen.add(key)
    hints.append(
        QueryAnchorHint(
            kind=kind,
            canonical_key=safe_key,
            label=_metadata_text(label),
            reason=_metadata_text(reason),
            metadata=dict(metadata),
        )
    )


def _match_event_anchor(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    event_keys = _anchor_identity_keys(anchor)
    exact_event_keys = intent.keys_for_kind(MemoryAnchorKind.EVENT).intersection(event_keys)
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()

    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_person_keys = _identity_term_variants(anchor_person)
    anchor_project_keys = _identity_term_variants(anchor_project)
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)

    if person_keys and not anchor_person_keys.intersection(person_keys):
        return None
    if project_keys and not _compatible_identity_matches(anchor_project_keys, project_keys):
        return None
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return None
    if _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    ):
        return None

    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    if exact_event_keys:
        reasons.append("query_event_identity_match")
        matched_keys.extend(sorted(exact_event_keys)[:4])
        score_boost += 0.04
    person_matches = sorted(anchor_person_keys.intersection(person_keys))
    if person_matches:
        reasons.append("query_event_participant_match")
        matched_keys.extend(person_matches[:2])
        score_boost += 0.035
    project_matches = _compatible_identity_matches(anchor_project_keys, project_keys)
    if project_matches:
        reasons.append("query_event_project_match")
        matched_keys.extend(project_matches[:2])
        score_boost += 0.035
    shared_event_type = sorted(anchor_event_type_keys.intersection(event_type_keys))
    if shared_event_type:
        reasons.append("query_event_type_match")
        matched_keys.extend(shared_event_type[:3])
        score_boost += 0.025
    shared_temporal = sorted(anchor_temporal_keys.intersection(temporal_keys))
    if shared_temporal:
        reasons.append("query_event_temporal_match")
        matched_keys.extend(shared_temporal[:3])
        score_boost += 0.02
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.09, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
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


def _event_anchor_conflicts_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()
    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)
    if person_keys and not _identity_term_variants(anchor_person).intersection(person_keys):
        return True
    if project_keys and not _compatible_identity_matches(
        _identity_term_variants(anchor_project),
        project_keys,
    ):
        return True
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return True
    return _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    )


def _event_type_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    if _metadata_text(metadata.get("extraction_reason")) == "event query temporal hint":
        return frozenset()
    event_type = _metadata_text(
        metadata.get("event_type_canonical") or metadata.get("event_type")
    )
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
    query_groups = {
        key for key in query_event_type_keys if key.startswith("group:")
    }
    anchor_groups = {
        key for key in anchor_event_type_keys if key.startswith("group:")
    }
    if query_groups and anchor_groups:
        return not query_groups.intersection(anchor_groups)
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
            " ".join(
                normalize_cyrillic_person_case(part) for part in normalized.split() if part
            )
        )
    elif kind == MemoryAnchorKind.PROJECT:
        variants.append(
            " ".join(
                normalize_cyrillic_project_case(part) for part in normalized.split() if part
            )
        )
    return tuple(_bounded_unique(variants, limit=4))


def _temporal_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    hint_code = _metadata_text(metadata.get("event_temporal_hint_code"))
    if not hint_code:
        return frozenset()
    quantity = _metadata_text(metadata.get("event_temporal_quantity"))
    unit = _metadata_text(metadata.get("event_temporal_unit"))
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


def _event_temporal_keys(hints: Iterable[QueryAnchorHint]) -> frozenset[str]:
    keys: set[str] = set()
    for hint in hints:
        if hint.kind == MemoryAnchorKind.EVENT:
            keys.update(_temporal_identity_keys(hint.metadata))
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
    return not anchor_temporal_keys.intersection(query_temporal_keys)


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
    canonical = " ".join(canonical_token(part) for part in spaced.split() if part)
    return frozenset(term for term in (text, spaced, canonical) if term)


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


def _is_eventish_query(query: str) -> bool:
    return bool(_EVENTISH_QUERY_RE.search(query) or _RELATIVE_TIME_RE.search(query))


def _metadata_text(value: object) -> str:
    if value is None:
        return ""
    return safe_metadata_text(str(value), limit=160).strip().casefold()


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip("._-:/#()[]{}")


def _bounded_unique(values: Iterable[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        safe = _metadata_text(value)
        if not safe or safe in seen:
            continue
        seen.add(safe)
        result.append(safe)
        if len(result) >= limit:
            break
    return result
