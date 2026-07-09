"""Rule-based semantic anchor extraction shared by memory use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from infinity_context_core.application.anchor_creative_work_filters import (
    is_creative_work_person_false_positive,
)
from infinity_context_core.application.anchor_event_extraction import (
    canonical_event_key,
    event_labels,
    event_participant_labels,
    event_project_labels,
    structured_event_metadata,
)
from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_PERSON_PATTERN = re.compile(r"\b([A-Z][a-z][A-Za-z]{1,40})(?:\s+([A-Z][a-z][A-Za-z]{1,40}))?\b")
_CYRILLIC_PERSON_PATTERN = re.compile(r"\b([А-ЯЁ][а-яё]{2,40})(?:\s+([А-ЯЁ][а-яё]{2,40}))?\b")
_PERSON_INITIAL_PATTERN = re.compile(r"\b([A-Z][a-z][A-Za-z]{1,40})\s+([A-Z])\.(?![A-Za-z])")
_CYRILLIC_PERSON_INITIAL_PATTERN = re.compile(r"\b([А-ЯЁ][а-яё]{2,40})\s+([А-ЯЁ])\.(?![А-Яа-яЁё])")
_QUESTION_SUBJECT_PERSON_PATTERN = re.compile(
    r"\b(?i:would|should|could|can|did|does|is|was|were|will|might|may)\s+"
    r"(?P<label>[A-Z][a-z][A-Za-z]{1,40}"
    r"(?:\s+[A-Z][a-z][A-Za-z]{1,40}){0,2})\b",
)
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
    r"deadline|manifest|manifests|migration|overlay|overlays|"
    r"retrieval|screenshot|storage|transcript|video|документ|документы|заметка|заметки|"
    r"инвойс|поиск|скриншот|транскрипт)\b"
)
_IMPLICIT_PROJECT_CONTEXT_TAIL_PATTERN = re.compile(
    r"\s+(?:billing|dashboard|deadline|document|documents|docs|invoice|manifest|"
    r"manifests|memo|migration|notes|overlay|overlays|pricing|retrieval|"
    r"screenshot|storage|transcript|video)\b",
    re.IGNORECASE,
)
_RELOCATION_ORIGIN_PREFIX_PATTERN = re.compile(
    r"(?:\b(?:move|moved|moving|relocate|relocated|relocation)\b[\w\s.,:;!?-]{0,48}\bfrom\s*$)"
    r"|(?:\b(?:переезд|переехал|переехала|переехали|переезжал|переезжала|переезжали)"
    r"\b[\w\s.,:;!?-]{0,48}\bиз\s*$)",
    re.IGNORECASE,
)
_PERSON_STOP_WORDS = {
    "a",
    "about",
    "an",
    "are",
    "api",
    "attach",
    "can",
    "call",
    "could",
    "customer",
    "daily",
    "did",
    "does",
    "e2e",
    "email",
    "from",
    "frontend",
    "backend",
    "african",
    "american",
    "asian",
    "australian",
    "british",
    "canadian",
    "chinese",
    "docker",
    "dutch",
    "english",
    "european",
    "french",
    "flutter",
    "german",
    "irish",
    "italian",
    "japanese",
    "korean",
    "mexican",
    "memo",
    "memory",
    "norwegian",
    "polish",
    "portuguese",
    "project",
    "meeting",
    "monday",
    "review",
    "sync",
    "demo",
    "chat",
    "message",
    "conversation",
    "has",
    "have",
    "how",
    "is",
    "may",
    "might",
    "new york",
    "nintendo switch",
    "standup",
    "planning",
    "next",
    "previous",
    "should",
    "retro",
    "retrospective",
    "workshop",
    "interview",
    "kiev",
    "kyiv",
    "last",
    "presentation",
    "release",
    "launch",
    "dm",
    "direct",
    "chto",
    "gde",
    "kak",
    "kakaya",
    "kakie",
    "kakoe",
    "kakoi",
    "kogda",
    "kto",
    "pochemu",
    "zachem",
    "где",
    "зачем",
    "как",
    "какая",
    "какие",
    "какое",
    "какой",
    "когда",
    "кто",
    "почему",
    "что",
    "позвонил",
    "позвонила",
    "переезд",
    "переехал",
    "переехала",
    "переехали",
    "звонил",
    "звонила",
    "написал",
    "написала",
    "quick",
    "capture",
    "content",
    "context",
    "confirmed",
    "covered",
    "dimensions",
    "discussed",
    "duration",
    "format",
    "fort wayne",
    "friday",
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
    "owns",
    "team",
    "openai",
    "open",
    "please",
    "reviewed",
    "save",
    "said",
    "says",
    "sent",
    "shared",
    "spanish",
    "sweden",
    "swedish",
    "saturday",
    "sunday",
    "today",
    "tomorrow",
    "tuesday",
    "the",
    "thursday",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "would",
    "this",
    "that",
    "them",
    "tracks",
    "yesterday",
    "yep",
    "user",
    "uses",
    "weekly",
    "wednesday",
    "monthly",
    "yearly",
    "xenoblade chronicles",
    "anthropic",
    "github",
    "google",
    "her",
    "him",
    "microsoft",
    "notion",
    "linear",
    "slack",
    "stripe",
    "figma",
    "скриншот",
    "скриншота",
    "скриншотом",
    "файл",
    "файла",
    "файлом",
    "документ",
    "документа",
    "документом",
    "ссылка",
    "ссылку",
    "ссылки",
    "картинка",
    "картинку",
    "картинки",
    "фото",
    "изображение",
    "изображения",
    "видео",
    "аудио",
    "транскрипт",
    "транскрипта",
    "заметка",
    "заметку",
    "заметки",
    "проект",
    "киев",
    "киева",
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
    "он",
    "она",
    "воркшоп",
    "релиз",
    "запуск",
    "куда",
    "откуда",
    "я",
    "мы",
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
    "billing",
    "confirmed",
    "covered",
    "document",
    "documents",
    "docs",
    "from",
    "has",
    "invoice",
    "invoices",
    "is",
    "keeps",
    "meeting",
    "needs",
    "notes",
    "pricing",
    "owns",
    "said",
    "says",
    "shared",
    "timeline",
    "tracks",
    "update",
    "updates",
    "uses",
    "with",
    "документ",
    "документы",
    "заметка",
    "заметки",
    "по",
    "после",
    "про",
    "с",
}
_PROJECT_HINTS = {
    "backend",
    "docling",
    "frontend",
    "graphiti",
    "infinity context",
    "memo",
    "qdrant",
}
_ORGANIZATION_HINTS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "github": "GitHub",
    "google": "Google",
    "microsoft": "Microsoft",
    "nintendo": "Nintendo",
    "notion": "Notion",
    "linear": "Linear",
    "slack": "Slack",
    "stripe": "Stripe",
    "figma": "Figma",
}
_OBSERVED_ANCHOR_CACHE_MAX_SIZE = 2048
_OBSERVED_ANCHOR_CACHE_MAX_TEXT_CHARS = 16000


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
    if len(text) > _OBSERVED_ANCHOR_CACHE_MAX_TEXT_CHARS:
        return _extract_observed_anchors_uncached(text)
    return _extract_observed_anchors_cached(text)


@lru_cache(maxsize=_OBSERVED_ANCHOR_CACHE_MAX_SIZE)
def _extract_observed_anchors_cached(text: str) -> tuple[ObservedAnchor, ...]:
    return _extract_observed_anchors_uncached(text)


def _extract_observed_anchors_uncached(text: str) -> tuple[ObservedAnchor, ...]:
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
    for raw, _, _ in _question_subject_person_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PERSON,
            label=raw,
            reason="question subject person",
            score_boost=22,
        )
        _mark_person_label_token_keys_seen(seen, raw)
    for raw in event_participant_labels(text):
        _append_anchor(
            anchors,
            seen,
            kind=MemoryAnchorKind.PERSON,
            label=raw,
            reason="event participant reference",
            score_boost=20,
        )
    for raw in event_project_labels(text):
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
    for raw in event_labels(text):
        if _is_weak_event_label(raw):
            continue
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
        return canonical_event_key(label)
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
    safe_label = _display_anchor_label(kind, label)
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


def _display_anchor_label(kind: MemoryAnchorKind, label: str) -> str:
    safe_label = label.strip()[:120]
    if kind == MemoryAnchorKind.PERSON:
        return _display_person_label(safe_label)[:120]
    return safe_label


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


def _mark_person_label_token_keys_seen(seen: set[tuple[str, str]], label: str) -> None:
    normalized_key = _normalized_anchor_key_for_kind(MemoryAnchorKind.PERSON, label)
    parts = normalized_key.split()
    if len(parts) <= 1:
        return
    for part in parts:
        seen.add((MemoryAnchorKind.PERSON.value, part))


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

    return structured_event_metadata(label, canonical_key=canonical_key)


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


def _implicit_project_context_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _IMPLICIT_PROJECT_CONTEXT_PATTERN.finditer(text):
        label = _clean_project_label(match.group("label"))
        normalized = normalize_anchor_key(label)
        if label and normalized not in _PERSON_STOP_WORDS and normalized not in _ORGANIZATION_HINTS:
            labels.append(label)
    return tuple(labels)


def _person_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    labels.extend(_person_handle_labels(text))
    question_subject_spans: list[tuple[int, int]] = []
    for raw, start, end in _question_subject_person_labels(text):
        labels.append(raw)
        question_subject_spans.append((start, end))
    for pattern in (_PERSON_INITIAL_PATTERN, _CYRILLIC_PERSON_INITIAL_PATTERN):
        for match in pattern.finditer(text):
            if _overlaps_any_span(match.start(), match.end(), question_subject_spans):
                continue
            parts = tuple(part for part in match.groups() if part)
            normalized_parts = tuple(normalize_anchor_key(part) for part in parts)
            if normalized_parts and _is_project_qualifier(normalized_parts[0]):
                continue
            if _is_project_qualified_person_match(text, match.start()):
                continue
            if _is_project_preposition_person_false_positive(text, match.start()):
                continue
            if _is_relocation_origin_person_false_positive(text, match.start()):
                continue
            if _is_implicit_project_context_person_false_positive(text, match.end()):
                continue
            if is_creative_work_person_false_positive(text, match.start(), match.end()):
                continue
            label = " ".join(parts).strip()
            if _is_probable_person_label(label):
                labels.append(label)
    for pattern in (_PERSON_PATTERN, _CYRILLIC_PERSON_PATTERN):
        for match in pattern.finditer(text):
            if _overlaps_any_span(match.start(), match.end(), question_subject_spans):
                continue
            parts = tuple(part for part in match.groups() if part)
            normalized_parts = tuple(normalize_anchor_key(part) for part in parts)
            if normalized_parts and _is_project_qualifier(normalized_parts[0]):
                continue
            if _is_project_qualified_person_match(text, match.start()):
                continue
            if _is_project_preposition_person_false_positive(text, match.start()):
                continue
            if _is_relocation_origin_person_false_positive(text, match.start()):
                continue
            if _is_implicit_project_context_person_false_positive(text, match.end()):
                continue
            if is_creative_work_person_false_positive(text, match.start(), match.end()):
                continue
            if _is_followed_by_organization_suffix(text, match.end()):
                continue
            if len(parts) == 1 and _is_followed_by_person_initial(text, match.end()):
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


def _question_subject_person_labels(text: str) -> tuple[tuple[str, int, int], ...]:
    labels: list[tuple[str, int, int]] = []
    for match in _QUESTION_SUBJECT_PERSON_PATTERN.finditer(text):
        label = match.group("label").strip()
        if len(label.split()) <= 1 or not _is_probable_person_label(label):
            continue
        labels.append((label, match.start("label"), match.end("label")))
    return tuple(labels)


def _overlaps_any_span(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


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


def _is_project_qualified_person_match(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24) : start].lower()
    return bool(re.search(r"(?:project|проект(?:у|е|а|ом)?)\s+$", prefix))


def _is_project_qualifier(value: str) -> bool:
    return value in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}


def _is_project_preposition_person_false_positive(text: str, start: int) -> bool:
    prefix = text[max(0, start - 16) : start].casefold()
    return bool(re.search(r"\b(?:about|for|in|по|про|для|в)\s+$", prefix))


def _is_relocation_origin_person_false_positive(text: str, start: int) -> bool:
    prefix = text[max(0, start - 96) : start]
    return bool(_RELOCATION_ORIGIN_PREFIX_PATTERN.search(prefix))


def _is_implicit_project_context_person_false_positive(text: str, end: int) -> bool:
    return bool(_IMPLICIT_PROJECT_CONTEXT_TAIL_PATTERN.match(text[end : end + 48]))


def _is_followed_by_organization_suffix(text: str, end: int) -> bool:
    tail = text[end : end + 16]
    return bool(
        re.match(
            r"\s+(?:Inc|LLC|Ltd|Corp|Corporation|GmbH|AG|SAS|ООО|АО|ЗАО)\b",
            tail,
        )
    )


def _is_followed_by_person_initial(text: str, end: int) -> bool:
    return bool(re.match(r"\s+[A-ZА-ЯЁ]\.(?![\wА-Яа-яЁё])", text[end : end + 8]))


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
    if _canonical_project_key(label) in _PROJECT_HINTS:
        return True
    if normalized in _PERSON_STOP_WORDS:
        return False
    if first in _PROJECT_LABEL_STOP_WORDS:
        return False
    return _looks_like_project_label_continuation(label.split()[0])


def _is_weak_event_label(label: str) -> bool:
    metadata = structured_event_metadata(label, canonical_key=canonical_anchor_key(label))
    if metadata.get("event_has_project") or metadata.get("event_has_participant"):
        return False
    if metadata.get("event_temporal_phrase"):
        return False
    normalized = normalize_anchor_key(label)
    return normalized in {"deadline", "due", "milestone", "reminder", "task", "todo"}


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
        if index == 0 and normalized in _PROJECT_LABEL_STOP_WORDS:
            return ""
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


def _terms(text: str) -> tuple[str, ...]:
    return tuple(raw.strip("._-:/#()[]{}").lower() for raw in _TERM_PATTERN.findall(text))
