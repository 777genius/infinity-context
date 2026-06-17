"""Rule-based semantic anchor extraction shared by memory use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from memo_stack_core.domain.entities import MemoryAnchorKind

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_PERSON_PATTERN = re.compile(r"\b([A-Z][a-z][A-Za-z]{1,40})(?:\s+([A-Z][a-z][A-Za-z]{1,40}))?\b")
_CYRILLIC_PERSON_PATTERN = re.compile(r"\b([А-ЯЁ][а-яё]{2,40})(?:\s+([А-ЯЁ][а-яё]{2,40}))?\b")
_PROJECT_PATTERN = re.compile(
    r"\b(?:project|проект|repo|repository|service|сервис)\s+([A-Za-zА-Яа-яЁё0-9][\w.-]{1,80})",
    re.IGNORECASE,
)
_TEMPORAL_PHRASE = (
    r"last week|yesterday|today|tomorrow|an hour ago|hour ago|"
    r"\d{1,3}\s+hours?\s+ago|\d{1,3}\s+days?\s+ago|\d{1,2}\s+weeks?\s+ago|"
    r"неделю назад|вчера|сегодня|завтра|час назад|"
    r"\d{1,3}\s+час(?:а|ов)?\s+назад|"
    r"\d{1,3}\s+д(?:ень|ня|ней)\s+назад|"
    r"\d{1,2}\s+недел[юи]\s+назад"
)
_EVENT_PATTERN = re.compile(
    r"\b("
    r"call|meeting|review|sync|demo|chat|message|conversation|"
    r"звонок|созвон|встреча|ревью|демо|переписка|переписывался|"
    r"разговор(?:а|е|ом)?|чат"
    r")"
    r"(?:\s+(?:with|from|about|с|от|по|об|про|[A-Za-zА-Яа-яЁё0-9][\w.-]{1,40})){0,5}?"
    rf"(?:\s+({_TEMPORAL_PHRASE}))?",
    re.IGNORECASE,
)
_EVENT_PARTICIPANT_PATTERN = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    r"(?P<label>[A-Z][a-z][A-Za-z]{1,40}|[А-ЯЁ][а-яё]{2,40})\b"
)
_TEMPORAL_PATTERN = re.compile(
    rf"\b({_TEMPORAL_PHRASE})\b",
    re.IGNORECASE,
)
_PERSON_STOP_WORDS = {
    "api",
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
}
_PROJECT_HINTS = {
    "qdrant",
    "graphiti",
    "docling",
    "memo",
    "memo stack",
    "frontend",
    "backend",
}
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


@dataclass(frozen=True)
class ObservedAnchor:
    kind: MemoryAnchorKind
    normalized_key: str
    label: str
    aliases: tuple[str, ...]
    reason: str
    score_boost: float
    metadata: dict[str, object]


def extract_observed_anchors(text: str) -> tuple[ObservedAnchor, ...]:
    seen: set[tuple[str, str]] = set()
    anchors: list[ObservedAnchor] = []
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
    return " ".join(
        part.translate(_CYRILLIC_TO_LATIN).replace("x", "ks") for part in normalized.split()
    )


def canonical_anchor_key_for_kind(kind: MemoryAnchorKind, label: str) -> str:
    if kind == MemoryAnchorKind.PERSON:
        return _canonical_person_key(label)
    if kind == MemoryAnchorKind.EVENT:
        return _canonical_event_key(label)
    return canonical_anchor_key(label)


def _append_anchor(
    anchors: list[ObservedAnchor],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    label: str,
    reason: str,
    score_boost: float,
) -> None:
    normalized_key = normalize_anchor_key(label)
    key = (kind.value, normalized_key)
    if not normalized_key or key in seen:
        return
    seen.add(key)
    safe_label = label.strip()[:120]
    anchors.append(
        ObservedAnchor(
            kind=kind,
            normalized_key=normalized_key,
            label=safe_label,
            aliases=(safe_label,),
            reason=reason,
            score_boost=score_boost,
            metadata={
                "extraction_reason": reason,
                "extractor": "anchor-rule-v2",
                "canonical_key": canonical_anchor_key_for_kind(kind, label),
            },
        )
    )


def _explicit_project_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _PROJECT_PATTERN.finditer(text):
        value = match.group(1).strip(".,:;()[]{}")
        if len(value) >= 2:
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


def _event_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _EVENT_PATTERN.finditer(text):
        event = match.group(1).strip()
        participant = _nearby_event_participant(text, match.end())
        temporal = (
            match.group(2)
            or _nearby_temporal_after(text, match.end())
            or _nearby_temporal_before(text, match.start())
        ).strip()
        label = " ".join(part for part in (event, participant, temporal) if part).strip()
        labels.append(label)
        generic_temporal_label = f"{event} {temporal}".strip()
        if participant and temporal and generic_temporal_label != label:
            labels.append(generic_temporal_label)
    return tuple(labels)


def _person_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for pattern in (_PERSON_PATTERN, _CYRILLIC_PERSON_PATTERN):
        for match in pattern.finditer(text):
            if _is_project_qualified_person_match(text, match.start()):
                continue
            parts = tuple(part for part in match.groups() if part)
            if len(parts) > 1 and normalize_anchor_key(parts[1]) in _PERSON_STOP_WORDS:
                parts = (parts[0],)
            label = " ".join(parts).strip()
            if _is_probable_person_label(label):
                labels.append(label)
    return tuple(labels)


def _nearby_temporal_after(text: str, start: int) -> str:
    tail = re.split(r"[.!?\n]", text[start : start + 80], maxsplit=1)[0]
    match = _TEMPORAL_PATTERN.search(tail)
    return match.group(1) if match else ""


def _nearby_event_participant(text: str, start: int) -> str:
    tail = re.split(r"[.!?\n]", text[start : start + 80], maxsplit=1)[0]
    match = _EVENT_PARTICIPANT_PATTERN.search(tail)
    if not match:
        return ""
    label = match.group("label")
    if not _is_probable_person_label(label):
        return ""
    return f"{match.group('prep')} {label}"


def _nearby_temporal_before(text: str, end: int) -> str:
    prefix = re.split(r"[.!?\n]", text[max(0, end - 80) : end])[-1]
    matches = list(_TEMPORAL_PATTERN.finditer(prefix))
    return matches[-1].group(1) if matches else ""


def _is_project_qualified_person_match(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24) : start].lower()
    return bool(re.search(r"(?:project|проект)\s+$", prefix))


def _is_probable_person_label(label: str) -> bool:
    if len(label) < 3 or len(label) > 80:
        return False
    normalized = normalize_anchor_key(label)
    if normalized in _PERSON_STOP_WORDS:
        return False
    first = normalized.split()[0]
    return first not in _PERSON_STOP_WORDS


def _canonical_person_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    parts = [_normalize_cyrillic_person_case(part) for part in normalized.split()]
    return " ".join(part.translate(_CYRILLIC_TO_LATIN).replace("x", "ks") for part in parts if part)


def _canonical_event_key(label: str) -> str:
    normalized_parts: list[str] = []
    normalize_next_person = False
    for part in normalize_anchor_key(label).split():
        if normalize_next_person:
            normalized_parts.append(_normalize_cyrillic_person_case(part))
            normalize_next_person = False
        else:
            normalized_parts.append(part)
        if part in {"with", "from", "с", "от"}:
            normalize_next_person = True
    return " ".join(
        part.translate(_CYRILLIC_TO_LATIN).replace("x", "ks") for part in normalized_parts if part
    )


def _normalize_cyrillic_person_case(part: str) -> str:
    if not re.search(r"[а-яё]", part, re.IGNORECASE):
        return part
    if len(part) <= 4:
        return part
    if part.endswith("ией"):
        return f"{part[:-3]}ия"
    if part.endswith("еем"):
        return f"{part[:-3]}ей"
    if part.endswith("ием"):
        return f"{part[:-3]}ий"
    if part.endswith("ой"):
        return f"{part[:-2]}а"
    if part.endswith(("ом", "ем")):
        return part[:-2]
    return part


def _terms(text: str) -> tuple[str, ...]:
    return tuple(raw.strip("._-:/#()[]{}").lower() for raw in _TERM_PATTERN.findall(text))
