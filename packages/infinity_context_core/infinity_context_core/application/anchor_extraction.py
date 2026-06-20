"""Rule-based semantic anchor extraction shared by memory use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_PERSON_PATTERN = re.compile(r"\b([A-Z][a-z][A-Za-z]{1,40})(?:\s+([A-Z][a-z][A-Za-z]{1,40}))?\b")
_CYRILLIC_PERSON_PATTERN = re.compile(r"\b([А-ЯЁ][а-яё]{2,40})(?:\s+([А-ЯЁ][а-яё]{2,40}))?\b")
_HANDLE_PERSON_TOKEN = r"@[A-Za-z][A-Za-z0-9._-]{2,39}"
_HANDLE_PATTERN = re.compile(rf"(?<![\w.])(?P<label>{_HANDLE_PERSON_TOKEN})\b")
_EMAIL_PATTERN = re.compile(
    r"\b(?P<local>[A-Za-z][A-Za-z0-9._+-]{2,63})@"
    r"(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
)
_ALIAS_CONNECTOR = (
    r"(?i:aka|a\.k\.a\.|also known as|он же|она же|"
    r"также известн(?:ый|ая|о|ые)? как)"
)
_PERSON_ALIAS_PATTERN = re.compile(
    r"\b(?P<label>"
    r"[A-Z][a-z][A-Za-z]{1,40}(?:\s+[A-Z][a-z][A-Za-z]{1,40})?|"
    r"[А-ЯЁ][а-яё]{2,40}(?:\s+[А-ЯЁ][а-яё]{2,40})?"
    r")\s*(?:\(|,)?\s*(?:" + _ALIAS_CONNECTOR + r")\s+(?P<alias>"
    r"[A-Z][a-z][A-Za-z]{1,40}(?:\s+[A-Z][a-z][A-Za-z]{1,40})?|"
    r"[А-ЯЁ][а-яё]{2,40}(?:\s+[А-ЯЁ][а-яё]{2,40})?"
    r")\)?",
)
_PROJECT_PATTERN = re.compile(
    r"\b(?:project|проект(?:у|е|а|ом)?|repo|repository|service|сервис)\s+"
    r"([A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})",
    re.IGNORECASE,
)
_PROJECT_ALIAS_PATTERN = re.compile(
    r"\b(?:project|проект(?:у|е|а|ом)?|repo|repository|service|сервис)\s+"
    r"(?P<label>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})"
    r"\s*(?:\(|,)?\s*(?:" + _ALIAS_CONNECTOR + r")\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<alias>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})\)?",
    re.IGNORECASE,
)
_ORGANIZATION_PATTERN = re.compile(
    r"\b(?:company|org|organization|team|customer|client|vendor|"
    r"компания|организация|команда|клиент|заказчик|вендор)\s+"
    r"([A-Za-zА-Яа-яЁё0-9][\w.&-]{1,80}(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.&-]{1,80}){0,3})",
    re.IGNORECASE,
)
_ORGANIZATION_SUFFIX_PATTERN = re.compile(
    r"\b([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9&.-]{1,60}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9&.-]{1,60}){0,3})\s+"
    r"(?:Inc|LLC|Ltd|Corp|Corporation|GmbH|AG|SAS|ООО|АО|ЗАО)\b"
)
_IMPLICIT_PROJECT_CONTEXT_PATTERN = re.compile(
    r"\b(?P<label>[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9][\w.-]{1,80})\s+"
    r"(?P<context>billing|dashboard|document|documents|docs|invoice|memo|notes|pricing|"
    r"retrieval|screenshot|storage|transcript|video|документ|документы|заметка|заметки|"
    r"инвойс|поиск|скриншот|транскрипт)\b"
)
_TEMPORAL_PHRASE = (
    r"last week|yesterday|today|tomorrow|an hour ago|hour ago|"
    r"\d{1,3}\s+hours?\s+ago|\d{1,3}\s+days?\s+ago|\d{1,2}\s+weeks?\s+ago|"
    r"неделю назад|на прошлой неделе|прошлой неделе|прошлую неделю|"
    r"вчера|сегодня|завтра|час назад|"
    r"\d{1,3}\s+час(?:а|ов)?\s+назад|"
    r"\d{1,3}\s+д(?:ень|ня|ней)\s+назад|"
    r"\d{1,2}\s+недел[юи]\s+назад"
)
_EVENT_KEYWORDS = (
    r"call|meeting|review|sync|demo|chat|dm|direct message|message|conversation|"
    r"meet|met|"
    r"standup|planning|retro|retrospective|workshop|interview|presentation|release|launch|"
    r"звонок|созвон|позвонил|позвонила|звонил|звонила|"
    r"встреча|ревью|демо|переписка|переписывался|"
    r"написал|написала|"
    r"встретился|встретилась|встречался|встречалась|встречались|"
    r"разговор(?:а|е|ом)?|чат|планерка|планёрка|стендап|ретро|"
    r"интервью|воркшоп|релиз|запуск"
)
_EVENT_PATTERN = re.compile(
    rf"\b({_EVENT_KEYWORDS})"
    r"(?:\s+(?:with|from|about|с|от|по|об|про|[A-Za-zА-Яа-яЁё0-9][\w.-]{1,40})){0,5}?"
    rf"(?:\s+({_TEMPORAL_PHRASE}))?",
    re.IGNORECASE,
)
_EVENT_PARTICIPANT_PATTERN = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    rf"(?P<label>{_HANDLE_PERSON_TOKEN}|[A-Z][a-z][A-Za-z]{{1,40}}|[А-ЯЁ][а-яё]{{2,40}})\b"
)
_EVENT_DIRECT_PARTICIPANT_PATTERN = re.compile(
    rf"^\s+(?P<label>{_HANDLE_PERSON_TOKEN}|[A-Z][a-z][A-Za-z]{{1,40}}|[А-ЯЁ][а-яё]{{2,40}})\b"
)
_EVENT_PROJECT_PATTERN = re.compile(
    r"\b(?P<prep>about|for|in|по|про|для|в)\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})",
    re.IGNORECASE,
)
_EVENT_PREFIX_PARTICIPANT_PATTERN = re.compile(
    rf"(?P<label>{_HANDLE_PERSON_TOKEN}|[A-Z][a-z][A-Za-z]{{1,40}}|[А-ЯЁ][а-яё]{{2,40}})\s*$"
)
_EVENT_KEYWORD_PATTERN = re.compile(rf"\b({_EVENT_KEYWORDS})\b", re.IGNORECASE)
_TEMPORAL_PATTERN = re.compile(
    rf"\b({_TEMPORAL_PHRASE})\b",
    re.IGNORECASE,
)
_PERSON_STOP_WORDS = {
    "api",
    "attach",
    "call",
    "e2e",
    "frontend",
    "backend",
    "docker",
    "flutter",
    "memo",
    "memory",
    "project",
    "meeting",
    "review",
    "sync",
    "demo",
    "chat",
    "message",
    "conversation",
    "standup",
    "planning",
    "retro",
    "retrospective",
    "workshop",
    "interview",
    "presentation",
    "release",
    "launch",
    "dm",
    "direct",
    "позвонил",
    "позвонила",
    "звонил",
    "звонила",
    "написал",
    "написала",
    "quick",
    "capture",
    "content",
    "context",
    "dimensions",
    "duration",
    "format",
    "screenshot",
    "stack",
    "stream",
    "streams",
    "transcript",
    "keyframe",
    "keyframes",
    "marionette",
    "page",
    "pages",
    "qdrant",
    "graphiti",
    "docling",
    "company",
    "corp",
    "corporation",
    "inc",
    "llc",
    "ltd",
    "gmbh",
    "organization",
    "org",
    "team",
    "openai",
    "open",
    "please",
    "save",
    "today",
    "tomorrow",
    "yesterday",
    "anthropic",
    "github",
    "google",
    "microsoft",
    "notion",
    "linear",
    "slack",
    "stripe",
    "figma",
    "скриншот",
    "проект",
    "час",
    "часа",
    "часов",
    "неделя",
    "неделю",
    "вчера",
    "сегодня",
    "завтра",
    "созвон",
    "разговор",
    "переписка",
    "переписывался",
    "встреча",
    "звонок",
    "планерка",
    "планёрка",
    "стендап",
    "ретро",
    "интервью",
    "итог",
    "итоги",
    "воркшоп",
    "релиз",
    "запуск",
}
_PERSON_TEMPORAL_PREFIX_WORDS = {
    "today",
    "tomorrow",
    "yesterday",
}
_PERSON_HANDLE_STOP_WORDS = {
    "admin",
    "alert",
    "alerts",
    "billing",
    "bot",
    "contact",
    "hello",
    "info",
    "noreply",
    "no reply",
    "notification",
    "notifications",
    "ops",
    "project",
    "repo",
    "sales",
    "security",
    "service",
    "support",
    "team",
}
_ORGANIZATION_SUFFIX_WORDS = {
    "ag",
    "ao",
    "corp",
    "corporation",
    "gmbh",
    "inc",
    "llc",
    "ltd",
    "sas",
    "ао",
    "зао",
    "ооо",
}
_ORGANIZATION_LEADING_STOP_WORDS = {
    "approved",
    "failed",
    "mention",
    "mentioned",
    "mentions",
    "notes",
    "owns",
    "reviewed",
    "reviewing",
    "shared",
}
_PROJECT_LABEL_STOP_WORDS = {
    "about",
    "after",
    "and",
    "belongs",
    "confirmed",
    "covered",
    "from",
    "has",
    "is",
    "keeps",
    "meeting",
    "needs",
    "notes",
    "owns",
    "said",
    "says",
    "shared",
    "tracks",
    "uses",
    "with",
    "по",
    "после",
    "про",
    "с",
}
_PROJECT_HINTS = {
    "qdrant",
    "graphiti",
    "docling",
    "memo",
    "infinity context",
    "frontend",
    "backend",
}
_ORGANIZATION_HINTS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "github": "GitHub",
    "google": "Google",
    "microsoft": "Microsoft",
    "notion": "Notion",
    "linear": "Linear",
    "slack": "Slack",
    "stripe": "Stripe",
    "figma": "Figma",
}


@dataclass(frozen=True)
class ObservedAnchor:
    kind: MemoryAnchorKind
    normalized_key: str
    label: str
    aliases: tuple[str, ...]
    reason: str
    score_boost: float
    metadata: dict[str, object]


@dataclass(frozen=True)
class _EventComponents:
    event_type: str
    participant_label: str
    participant_relation: str
    project_label: str
    project_relation: str
    temporal_phrase: str
    temporal_hint_code: str
    temporal_quantity: int | None
    temporal_unit: str


def extract_observed_anchors(text: str) -> tuple[ObservedAnchor, ...]:
    seen: set[tuple[str, str]] = set()
    anchors: list[ObservedAnchor] = []
    for kind, label, aliases, reason, score_boost in _explicit_alias_observations(text):
        _append_anchor(
            anchors,
            seen,
            kind=kind,
            label=label,
            reason=reason,
            score_boost=score_boost,
            aliases=(label, *aliases),
        )
        _mark_alias_keys_seen(seen, kind=kind, aliases=aliases)
    for raw in _organization_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.ORGANIZATION,
            label=raw,
            reason="organization reference",
            score_boost=21,
        )
    for raw in _explicit_project_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=raw,
            reason="explicit project reference",
            score_boost=24,
        )
    for raw in _project_hint_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=raw,
            reason="known project/tool reference",
            score_boost=18,
        )
    for raw in _event_project_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=raw,
            reason="event project reference",
            score_boost=19,
        )
    for raw in _implicit_project_context_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=raw,
            reason="implicit project context",
            score_boost=17,
        )
    for raw in _event_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.EVENT,
            label=raw,
            reason="event phrase",
            score_boost=20,
        )
    for raw in _person_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PERSON,
            label=raw,
            reason="person name",
            score_boost=22,
        )
    return tuple(anchors[:12])


def normalize_anchor_key(label: str) -> str:
    parts = [part.strip("._-:/#()[]{}").lower() for part in _TERM_PATTERN.findall(label)]
    return " ".join(part for part in parts if part)


def canonical_anchor_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    return " ".join(canonical_token(part) for part in normalized.split())


def canonical_anchor_key_for_kind(kind: MemoryAnchorKind, label: str) -> str:
    if kind == MemoryAnchorKind.PERSON:
        return _canonical_person_key(label)
    if kind == MemoryAnchorKind.PROJECT:
        return _canonical_project_key(label)
    if kind == MemoryAnchorKind.EVENT:
        return _canonical_event_key(label)
    return canonical_anchor_key(label)


def structured_anchor_metadata_for_label(
    kind: MemoryAnchorKind,
    label: str,
    aliases: tuple[str, ...] = (),
) -> dict[str, object]:
    canonical_key = canonical_anchor_key_for_kind(kind, label)
    alias_identity_terms = alias_identity_terms_for_kind(
        kind,
        label=label,
        aliases=aliases,
    )
    return {
        "canonical_key": canonical_key,
        **_identity_anchor_metadata(kind, canonical_key),
        **({"alias_identity_terms": alias_identity_terms} if alias_identity_terms else {}),
        **_structured_anchor_metadata(kind, label, canonical_key=canonical_key),
    }


def alias_identity_terms_for_kind(
    kind: MemoryAnchorKind,
    *,
    label: str,
    aliases: tuple[str, ...],
) -> list[str]:
    canonical_key = canonical_anchor_key_for_kind(kind, label)
    terms: list[str] = []
    seen = {canonical_key}
    for alias in aliases:
        alias_key = canonical_anchor_key_for_kind(kind, alias)
        if not alias_key or alias_key in seen:
            continue
        seen.add(alias_key)
        terms.append(alias_key)
        if len(terms) >= 12:
            break
    return terms


def _identity_anchor_metadata(
    kind: MemoryAnchorKind,
    canonical_key: str,
) -> dict[str, object]:
    identity_scope = kind.value
    return {
        "identity_scope": identity_scope,
        "identity_key": f"{identity_scope}:{canonical_key}",
        "identity_resolver_version": "anchor-identity-v1",
    }


def _append_anchor(
    anchors: list[ObservedAnchor],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    label: str,
    reason: str,
    score_boost: float,
    aliases: tuple[str, ...] | None = None,
) -> None:
    normalized_key = _normalized_anchor_key_for_kind(kind, label)
    key = (kind.value, normalized_key)
    if not normalized_key or key in seen:
        return
    seen.add(key)
    safe_label = label.strip()[:120]
    safe_aliases = _safe_aliases(safe_label, aliases or (safe_label,))
    anchors.append(
        ObservedAnchor(
            kind=kind,
            normalized_key=normalized_key,
            label=safe_label,
            aliases=safe_aliases,
            reason=reason,
            score_boost=score_boost,
            metadata={
                "extraction_reason": reason,
                "extractor": "anchor-rule-v2",
                **structured_anchor_metadata_for_label(kind, label, aliases=safe_aliases),
            },
        )
    )


def _mark_alias_keys_seen(
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    aliases: tuple[str, ...],
) -> None:
    for alias in aliases:
        normalized_key = _normalized_anchor_key_for_kind(kind, alias)
        if normalized_key:
            seen.add((kind.value, normalized_key))


def _safe_aliases(label: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    safe: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        value = alias.strip()[:120]
        normalized = normalize_anchor_key(value)
        if not value or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        safe.append(value)
        if len(safe) >= 8:
            break
    if not safe:
        safe.append(label)
    return tuple(safe)


def _normalized_anchor_key_for_kind(kind: MemoryAnchorKind, label: str) -> str:
    if kind == MemoryAnchorKind.PERSON:
        parts = [
            normalize_cyrillic_person_case(part) for part in normalize_anchor_key(label).split()
        ]
        return " ".join(part for part in parts if part)
    if kind == MemoryAnchorKind.PROJECT:
        parts = [
            normalize_cyrillic_project_case(part) for part in normalize_anchor_key(label).split()
        ]
        return " ".join(part for part in parts if part)
    return normalize_anchor_key(label)


def _structured_anchor_metadata(
    kind: MemoryAnchorKind,
    label: str,
    *,
    canonical_key: str,
) -> dict[str, object]:
    if kind == MemoryAnchorKind.PERSON:
        return {
            "anchor_family": "person",
            "person_canonical_key": canonical_key,
        }
    if kind == MemoryAnchorKind.PROJECT:
        return {
            "anchor_family": "project",
            "project_canonical_key": canonical_key,
        }
    if kind == MemoryAnchorKind.ORGANIZATION:
        return {
            "anchor_family": "organization",
            "organization_canonical_key": canonical_key,
        }
    if kind != MemoryAnchorKind.EVENT:
        return {"anchor_family": kind.value}

    components = _event_components(label)
    metadata: dict[str, object] = {
        "anchor_family": "event",
        "event_type": components.event_type,
        "event_type_canonical": canonical_anchor_key(components.event_type),
        "event_has_participant": bool(components.participant_label),
        "event_has_project": bool(components.project_label),
        "event_has_temporal": bool(components.temporal_phrase),
        "event_identity_terms": _event_identity_terms(components),
    }
    if components.participant_label:
        metadata.update(
            {
                "event_participant_label": components.participant_label,
                "event_participant_relation": components.participant_relation,
                "event_participant_canonical_key": _canonical_person_key(
                    components.participant_label
                ),
            }
        )
    if components.project_label:
        project_canonical_key = _canonical_project_key(components.project_label)
        metadata.update(
            {
                "event_project_label": components.project_label,
                "event_project_relation": components.project_relation,
                "event_project_canonical_key": project_canonical_key,
                "project_canonical_key": project_canonical_key,
            }
        )
    if components.temporal_phrase:
        metadata["event_temporal_phrase"] = components.temporal_phrase
    if components.temporal_hint_code:
        metadata["event_temporal_hint_code"] = components.temporal_hint_code
    if components.temporal_quantity is not None:
        metadata["event_temporal_quantity"] = components.temporal_quantity
    if components.temporal_unit:
        metadata["event_temporal_unit"] = components.temporal_unit
    return metadata


def _event_identity_terms(components: _EventComponents) -> list[str]:
    terms = [canonical_anchor_key(components.event_type)]
    if components.participant_label:
        terms.append(_canonical_person_key(components.participant_label))
    if components.project_label:
        terms.append(_canonical_project_key(components.project_label))
    if components.temporal_hint_code:
        temporal = components.temporal_hint_code
        if components.temporal_quantity is not None and components.temporal_unit:
            temporal = f"{temporal}:{components.temporal_quantity}:{components.temporal_unit}"
        terms.append(temporal)
    return [term for term in terms if term]


def _event_components(label: str) -> _EventComponents:
    normalized = normalize_anchor_key(label)
    parts = normalized.split()
    event_type = parts[0] if parts else normalized
    temporal_phrase = _event_temporal_phrase(label)
    temporal_parts = set(normalize_anchor_key(temporal_phrase).split())
    participant_relation = ""
    participant_label = ""
    project_relation = ""
    project_label = ""
    for index, part in enumerate(parts):
        if part not in {"with", "from", "с", "от"}:
            continue
        participant_relation = part
        participant_tokens: list[str] = []
        for token in parts[index + 1 :]:
            if token in temporal_parts or token in {
                "about",
                "for",
                "in",
                "по",
                "про",
                "для",
                "в",
            }:
                break
            participant_tokens.append(token)
        participant_label = " ".join(participant_tokens).strip()
        break
    for index, part in enumerate(parts):
        if part not in {"about", "for", "in", "по", "про", "для", "в"}:
            continue
        project_relation = part
        project_tokens: list[str] = []
        for token in parts[index + 1 :]:
            if token in temporal_parts:
                break
            if token in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}:
                continue
            project_tokens.append(token)
        project_label = _clean_project_label(" ".join(project_tokens)).casefold()
        break
    temporal_hint_code, temporal_quantity, temporal_unit = _temporal_hint_payload(temporal_phrase)
    return _EventComponents(
        event_type=event_type,
        participant_label=participant_label,
        participant_relation=participant_relation,
        project_label=project_label,
        project_relation=project_relation,
        temporal_phrase=temporal_phrase,
        temporal_hint_code=temporal_hint_code,
        temporal_quantity=temporal_quantity,
        temporal_unit=temporal_unit,
    )


def _event_temporal_phrase(label: str) -> str:
    matches = list(_TEMPORAL_PATTERN.finditer(label))
    if not matches:
        return ""
    return matches[-1].group(1).strip()


def _temporal_hint_payload(phrase: str) -> tuple[str, int | None, str]:
    normalized = normalize_anchor_key(phrase)
    if not normalized:
        return "", None, ""
    if normalized in {"today", "сегодня"}:
        return "today", 0, "day"
    if normalized in {"yesterday", "вчера"}:
        return "yesterday", 1, "day"
    if normalized in {"tomorrow", "завтра"}:
        return "tomorrow", 1, "day"
    if normalized in {
        "last week",
        "week ago",
        "1 week ago",
        "неделю назад",
        "на прошлой неделе",
        "прошлой неделе",
        "прошлую неделю",
    }:
        return "last_week", 1, "week"
    if normalized in {"an hour ago", "hour ago", "1 hour ago", "час назад"}:
        return "hours_ago", 1, "hour"
    if match := re.match(r"(?P<count>\d{1,3}) hours? ago$", normalized):
        return "hours_ago", int(match.group("count")), "hour"
    if match := re.match(r"(?P<count>\d{1,3}) час(?:а|ов)? назад$", normalized):
        return "hours_ago", int(match.group("count")), "hour"
    if match := re.match(r"(?P<count>\d{1,3}) days? ago$", normalized):
        return "days_ago", int(match.group("count")), "day"
    if match := re.match(r"(?P<count>\d{1,3}) д(?:ень|ня|ней) назад$", normalized):
        return "days_ago", int(match.group("count")), "day"
    if match := re.match(r"(?P<count>\d{1,2}) weeks? ago$", normalized):
        return "weeks_ago", int(match.group("count")), "week"
    if match := re.match(r"(?P<count>\d{1,2}) недел[юи] назад$", normalized):
        return "weeks_ago", int(match.group("count")), "week"
    return "relative_time", None, ""


def _explicit_alias_observations(
    text: str,
) -> tuple[tuple[MemoryAnchorKind, str, tuple[str, ...], str, float], ...]:
    observations: list[tuple[MemoryAnchorKind, str, tuple[str, ...], str, float]] = []
    for match in _PROJECT_ALIAS_PATTERN.finditer(text):
        label = _clean_project_label(match.group("label"))
        alias = _clean_project_label(match.group("alias"))
        if (
            label
            and alias
            and _is_probable_event_project_label(label)
            and _is_probable_event_project_label(alias)
        ):
            observations.append(
                (
                    MemoryAnchorKind.PROJECT,
                    label,
                    (alias,),
                    "explicit project alias reference",
                    27,
                )
            )
    for match in _PERSON_ALIAS_PATTERN.finditer(text):
        label = _clean_person_alias_label(match.group("label"))
        alias = _clean_person_alias_label(match.group("alias"))
        if (
            label
            and alias
            and _is_probable_person_label(label)
            and _is_probable_person_label(alias)
        ):
            observations.append(
                (
                    MemoryAnchorKind.PERSON,
                    label,
                    (alias,),
                    "explicit person alias reference",
                    26,
                )
            )
    return tuple(observations)


def _explicit_project_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _PROJECT_PATTERN.finditer(text):
        value = _clean_project_label(match.group(1))
        if len(normalize_anchor_key(value)) >= 2:
            labels.append(value)
    return tuple(labels)


def _organization_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    terms = set(_terms(text))
    for normalized, label in sorted(_ORGANIZATION_HINTS.items(), key=lambda item: item[0]):
        if normalized in terms:
            labels.append(label)
    for match in _ORGANIZATION_PATTERN.finditer(text):
        value = _clean_organization_label(match.group(1))
        if _is_probable_organization_label(value):
            labels.append(value)
    for match in _ORGANIZATION_SUFFIX_PATTERN.finditer(text):
        value = _clean_organization_label(match.group(0))
        if _is_probable_organization_label(value):
            labels.append(value)
    return tuple(labels)


def _project_hint_labels(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    terms = set(_terms(text))
    labels: list[str] = []
    for hint in sorted(_PROJECT_HINTS, key=len, reverse=True):
        if (" " in hint and hint in lowered) or (" " not in hint and hint in terms):
            labels.append(" ".join(part.capitalize() for part in hint.split()))
    return tuple(labels)


def _event_project_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for event_label in _event_labels(text):
        project = _event_components(event_label).project_label
        if project:
            labels.append(project)
    return tuple(labels)


def _implicit_project_context_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _IMPLICIT_PROJECT_CONTEXT_PATTERN.finditer(text):
        label = _clean_project_label(match.group("label"))
        normalized = normalize_anchor_key(label)
        if label and normalized not in _PERSON_STOP_WORDS and normalized not in _ORGANIZATION_HINTS:
            labels.append(label)
    return tuple(labels)


def _event_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _EVENT_PATTERN.finditer(text):
        event = match.group(1).strip()
        participant = _nearby_event_participant_before(
            text,
            match.start(),
        ) or _nearby_event_participant(text, match.end())
        project = _event_project_in_phrase(match.group(0)) or _nearby_event_project(
            text,
            match.end(),
        )
        temporal = (
            match.group(2)
            or _nearby_temporal_after(text, match.end())
            or _nearby_temporal_before(text, match.start())
        ).strip()
        label = " ".join(part for part in (event, participant, project, temporal) if part).strip()
        labels.append(label)
        generic_participant_label = " ".join(
            part for part in (event, participant, temporal) if part
        ).strip()
        if project and generic_participant_label != label:
            labels.append(generic_participant_label)
        generic_temporal_label = f"{event} {temporal}".strip()
        if participant and temporal and generic_temporal_label != label:
            labels.append(generic_temporal_label)
    return tuple(labels)


def _person_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    labels.extend(_person_handle_labels(text))
    for pattern in (_PERSON_PATTERN, _CYRILLIC_PERSON_PATTERN):
        for match in pattern.finditer(text):
            parts = tuple(part for part in match.groups() if part)
            normalized_parts = tuple(normalize_anchor_key(part) for part in parts)
            if normalized_parts and _is_project_qualifier(normalized_parts[0]):
                continue
            if _is_project_qualified_person_match(text, match.start()):
                continue
            if _is_project_preposition_person_false_positive(text, match.start()):
                continue
            if _is_followed_by_organization_suffix(text, match.end()):
                continue
            if any(part in _ORGANIZATION_SUFFIX_WORDS for part in normalized_parts[1:]):
                continue
            if len(parts) > 1 and normalized_parts[0] in _PERSON_TEMPORAL_PREFIX_WORDS:
                parts = (parts[1],)
                normalized_parts = normalized_parts[1:]
            if len(parts) > 1 and normalized_parts[0] in _PERSON_STOP_WORDS:
                parts = (parts[1],)
                normalized_parts = normalized_parts[1:]
            if len(parts) > 1 and normalized_parts[1] in _PERSON_STOP_WORDS:
                parts = (parts[0],)
            label = " ".join(parts).strip()
            if _is_probable_person_label(label):
                labels.append(label)
    return tuple(labels)


def _person_handle_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for match in _HANDLE_PATTERN.finditer(text):
        label = _display_person_label(match.group("label"))
        normalized = normalize_anchor_key(label)
        if normalized and normalized not in seen and _is_probable_person_label(label):
            seen.add(normalized)
            labels.append(label)
    for match in _EMAIL_PATTERN.finditer(text):
        label = _display_person_label(match.group("local"))
        normalized = normalize_anchor_key(label)
        if normalized and normalized not in seen and _is_probable_person_label(label):
            seen.add(normalized)
            labels.append(label)
    return tuple(labels)


def _nearby_temporal_after(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 80])
    match = _TEMPORAL_PATTERN.search(tail)
    return match.group(1) if match else ""


def _nearby_event_participant(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 80])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    match = _EVENT_PARTICIPANT_PATTERN.search(tail)
    if match:
        label = _display_person_label(match.group("label"))
        prep = match.group("prep")
    else:
        direct_match = _EVENT_DIRECT_PARTICIPANT_PATTERN.search(tail)
        if not direct_match:
            return ""
        label = _display_person_label(direct_match.group("label"))
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    if not _is_probable_person_label(label):
        return ""
    return f"{prep} {label}"


def _nearby_event_project(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 100])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    return _event_project_in_phrase(tail)


def _event_project_in_phrase(text: str) -> str:
    match = _EVENT_PROJECT_PATTERN.search(text)
    if not match:
        return ""
    label = _clean_project_label(match.group("label"))
    if not _is_probable_event_project_label(label):
        return ""
    return f"{match.group('prep')} {label}"


def _nearby_event_participant_before(text: str, end: int) -> str:
    prefix = _nearby_clause_before(text[max(0, end - 80) : end])
    if re.search(r"(?:project|проект)\s+[A-Za-zА-Яа-яЁё0-9][\w.-]*\s*$", prefix, re.IGNORECASE):
        return ""
    match = _EVENT_PREFIX_PARTICIPANT_PATTERN.search(prefix)
    if not match:
        return ""
    label = _display_person_label(match.group("label"))
    if not _is_probable_person_label(label):
        return ""
    prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    return f"{prep} {label}"


def _nearby_temporal_before(text: str, end: int) -> str:
    prefix = _nearby_clause_before(text[max(0, end - 80) : end])
    matches = list(_TEMPORAL_PATTERN.finditer(prefix))
    return matches[-1].group(1) if matches else ""


def _nearby_clause(value: str) -> str:
    return re.split(r"(?:[!?]\s*|\n|\.\s+)", value, maxsplit=1)[0]


def _nearby_clause_before(value: str) -> str:
    return re.split(r"(?:[!?]\s*|\n|\.\s+)", value)[-1]


def _is_project_qualified_person_match(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24) : start].lower()
    return bool(re.search(r"(?:project|проект(?:у|е|а|ом)?)\s+$", prefix))


def _is_project_qualifier(value: str) -> bool:
    return value in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}


def _is_project_preposition_person_false_positive(text: str, start: int) -> bool:
    prefix = text[max(0, start - 16) : start].casefold()
    return bool(re.search(r"\b(?:about|for|in|по|про|для|в)\s+$", prefix))


def _is_followed_by_organization_suffix(text: str, end: int) -> bool:
    tail = text[end : end + 16]
    return bool(
        re.match(
            r"\s+(?:Inc|LLC|Ltd|Corp|Corporation|GmbH|AG|SAS|ООО|АО|ЗАО)\b",
            tail,
        )
    )


def _is_probable_person_label(label: str) -> bool:
    if len(label) < 3 or len(label) > 80:
        return False
    normalized = normalize_anchor_key(label)
    if not normalized:
        return False
    if normalized in _PERSON_STOP_WORDS:
        return False
    if normalized in _PERSON_HANDLE_STOP_WORDS:
        return False
    if normalized in _PROJECT_HINTS or normalized in _ORGANIZATION_HINTS:
        return False
    first = normalized.split()[0]
    if first in _PERSON_STOP_WORDS or first in _PERSON_HANDLE_STOP_WORDS:
        return False
    if first in {"project", "repo", "service", "team"}:
        return False
    return any(char.isalpha() for char in normalized)


def _display_person_label(raw: str) -> str:
    value = raw.strip().lstrip("@")
    value = value.split("+", 1)[0]
    tokens = [
        token
        for token in re.split(r"[._-]+", value)
        if token and any(char.isalpha() for char in token)
    ]
    if not tokens:
        return raw.strip()
    return " ".join(token[:1].upper() + token[1:] for token in tokens[:3])


def _is_probable_organization_label(label: str) -> bool:
    normalized = normalize_anchor_key(label)
    if len(normalized) < 2 or len(normalized) > 120:
        return False
    if normalized.split()[0] in _ORGANIZATION_LEADING_STOP_WORDS:
        return False
    return normalized not in _PERSON_STOP_WORDS


def _is_probable_event_project_label(label: str) -> bool:
    normalized = normalize_anchor_key(label)
    if len(normalized) < 2 or len(normalized) > 120:
        return False
    first = normalized.split()[0]
    if normalized in _PROJECT_HINTS or first in _PROJECT_HINTS:
        return True
    if normalized in _PERSON_STOP_WORDS:
        return False
    if first in _PROJECT_LABEL_STOP_WORDS:
        return False
    return _looks_like_project_label_continuation(label.split()[0])


def _clean_organization_label(label: str) -> str:
    value = label.strip(".,:;()[]{}")
    value = re.split(r"\b(?:and|with|и|с|по|про|about)\b", value, maxsplit=1, flags=re.IGNORECASE)[
        0
    ]
    return value.strip(".,:;()[]{} ")


def _clean_project_label(label: str) -> str:
    raw_tokens = [token for token in label.split() if token.strip(".,:;()[]{}")]
    if not raw_tokens:
        return ""
    cleaned: list[str] = []
    for index, raw_token in enumerate(raw_tokens[:4]):
        token = raw_token.strip(".,:;()[]{}")
        normalized = normalize_anchor_key(token)
        if not normalized:
            continue
        if index > 0 and (
            normalized in _PROJECT_LABEL_STOP_WORDS
            or not _looks_like_project_label_continuation(token)
        ):
            break
        cleaned.append(token)
        if raw_token.rstrip().endswith((".", "!", "?", ";", ":")):
            break
    return " ".join(cleaned).strip(".,:;()[]{} ")


def _clean_person_alias_label(label: str) -> str:
    value = label.strip(".,:;()[]{} ")
    value = re.split(
        r"\b(?:and|with|и|с|по|про|about|for)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return " ".join(value.split()[:3]).strip(".,:;()[]{} ")


def _looks_like_project_label_continuation(token: str) -> bool:
    return bool(re.match(r"[A-ZА-ЯЁ0-9]", token)) or any(
        marker in token for marker in ("-", ".", "_")
    )


def _canonical_person_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    parts = [normalize_cyrillic_person_case(part) for part in normalized.split()]
    return " ".join(canonical_token(part) for part in parts if part)


def _canonical_project_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    parts = [normalize_cyrillic_project_case(part) for part in normalized.split()]
    return " ".join(canonical_token(part) for part in parts if part)


def _canonical_event_key(label: str) -> str:
    normalized_parts: list[str] = []
    normalize_next_person = False
    normalize_next_project = False
    for part in normalize_anchor_key(label).split():
        if normalize_next_person:
            normalized_parts.append(normalize_cyrillic_person_case(part))
            normalize_next_person = False
        elif normalize_next_project:
            if part in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}:
                continue
            normalized_parts.append(normalize_cyrillic_project_case(part))
            normalize_next_project = False
        else:
            normalized_parts.append(part)
        if part in {"with", "from", "с", "от"}:
            normalize_next_person = True
        if part in {"about", "for", "in", "по", "про", "для", "в"}:
            normalize_next_project = True
    return " ".join(canonical_token(part) for part in normalized_parts if part)


def _terms(text: str) -> tuple[str, ...]:
    return tuple(raw.strip("._-:/#()[]{}").lower() for raw in _TERM_PATTERN.findall(text))
