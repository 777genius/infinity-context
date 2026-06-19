"""Conservative semantic duplicate checks for canonical memory facts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key,
    extract_observed_anchors,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_NUMERIC_VALUE_RE = re.compile(
    r"\b(?P<prefix>v|version\s+)?(?P<number>\d+(?:[.,]\d+)?)"
    r"(?:\s*(?P<unit>%|percent|percentage|milliseconds?|msecs?|ms|seconds?|secs?|sec|"
    r"minutes?|mins?|min|hours?|hrs?|hr|days?|weeks?|months?|years?|pages?|tokens?|"
    r"gb|mb|kb|replicas?|shards?))?\b",
    re.IGNORECASE,
)
_EVENT_TYPE_ALIASES = {
    "perepiska": "chat",
    "soobshchenie": "message",
    "sozvon": "call",
    "vstrecha": "meeting",
    "zvonok": "call",
}
_IDENTITY_TERM_PREFIXES = (
    "event_participant:",
    "event_project:",
    "event_temporal:",
    "event_type:",
    "organization:",
    "person:",
    "project:",
)
_DUPLICATE_CONTENT_SIGNAL_TERMS = {
    "audio",
    "billing",
    "call",
    "dashboard",
    "document",
    "image",
    "invoice",
    "meeting",
    "note",
    "owner",
    "pricing",
    "retrieval",
    "screenshot",
    "storage",
    "transcript",
    "vector",
    "video",
}


@dataclass(frozen=True)
class FactDuplicateMatch:
    match_type: str
    score: float
    reason_codes: tuple[str, ...]
    overlap_terms: tuple[str, ...]


@dataclass(frozen=True)
class FactConflictMatch:
    match_type: str
    score: float
    reason_codes: tuple[str, ...]
    overlap_terms: tuple[str, ...]


def normalize_memory_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return " ".join(normalized.strip().casefold().split())


def meaningful_memory_terms(text: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "use",
        "uses",
        "user",
        "decided",
        "should",
        "memory",
    }
    return {
        token.strip(".,:;!?()[]{}\"'")
        for token in text.split()
        if len(token.strip(".,:;!?()[]{}\"'")) >= 4
        and token.strip(".,:;!?()[]{}\"'") not in stop_words
    }


def looks_equivalent_fact(candidate_text: str, existing_text: str) -> bool:
    return describe_duplicate_fact_match(candidate_text, existing_text) is not None


def describe_duplicate_fact_match(
    candidate_text: str,
    existing_text: str,
) -> FactDuplicateMatch | None:
    candidate_normalized = normalize_memory_text(candidate_text)
    existing_normalized = normalize_memory_text(existing_text)
    if not candidate_normalized or not existing_normalized:
        return None
    if candidate_normalized == existing_normalized:
        return FactDuplicateMatch(
            match_type="exact_normalized_text",
            score=1.0,
            reason_codes=("exact_normalized_text",),
            overlap_terms=tuple(sorted(semantic_memory_terms(candidate_text))),
        )
    candidate_terms = semantic_memory_terms(candidate_text)
    existing_terms = semantic_memory_terms(existing_text)
    if len(candidate_terms) < 3 or len(existing_terms) < 3:
        return None
    if _has_negation_mismatch(candidate_text, existing_text):
        return None
    if _has_named_anchor_mismatch(candidate_text, existing_text):
        return None
    if _has_event_identity_mismatch(candidate_text, existing_text):
        return None
    if _has_numeric_value_mismatch(candidate_text, existing_text):
        return None
    if _has_exclusive_anchor_mismatch(candidate_terms, existing_terms):
        return None
    overlap = candidate_terms & existing_terms
    if len(overlap) < 3:
        return None
    union = candidate_terms | existing_terms
    score = len(overlap) / len(union)
    if score >= 0.6:
        return FactDuplicateMatch(
            match_type="semantic_token_overlap",
            score=round(score, 3),
            reason_codes=("semantic_duplicate", "token_overlap"),
            overlap_terms=tuple(sorted(overlap))[:12],
        )
    identity_match = _semantic_identity_overlap_match(
        overlap=overlap,
        candidate_terms=candidate_terms,
        existing_terms=existing_terms,
        base_score=score,
    )
    if identity_match is not None:
        return identity_match
    anchors = {
        "adapter",
        "canonical",
        "cognee",
        "database",
        "document",
        "graph",
        "graphiti",
        "memory",
        "mcp",
        "neo4j",
        "postgres",
        "qdrant",
        "rag",
        "temporal",
        "truth",
        "vector",
    }
    anchor_score = len(overlap) / min(
        len(candidate_terms),
        len(existing_terms),
    )
    if len(overlap & anchors) >= 2 and anchor_score >= 0.75:
        return FactDuplicateMatch(
            match_type="semantic_anchor_overlap",
            score=round(max(score, anchor_score * 0.92), 3),
            reason_codes=("semantic_duplicate", "anchor_overlap"),
            overlap_terms=tuple(sorted(overlap))[:12],
        )
    return None


def _semantic_identity_overlap_match(
    *,
    overlap: set[str],
    candidate_terms: set[str],
    existing_terms: set[str],
    base_score: float,
) -> FactDuplicateMatch | None:
    identity_overlap = {term for term in overlap if _is_identity_term(term)}
    if len(identity_overlap) < 2:
        return None
    signal_overlap = overlap & _DUPLICATE_CONTENT_SIGNAL_TERMS
    if len(signal_overlap) < 2:
        return None
    candidate_signals = candidate_terms & _DUPLICATE_CONTENT_SIGNAL_TERMS
    existing_signals = existing_terms & _DUPLICATE_CONTENT_SIGNAL_TERMS
    if not candidate_signals or not existing_signals:
        return None
    score = max(base_score, 0.58 + min(len(identity_overlap), 4) * 0.05)
    score += min(len(signal_overlap), 4) * 0.035
    return FactDuplicateMatch(
        match_type="semantic_identity_overlap",
        score=round(min(score, 0.93), 3),
        reason_codes=("semantic_duplicate", "identity_overlap", "content_overlap"),
        overlap_terms=tuple(sorted(identity_overlap | signal_overlap))[:12],
    )


def _is_identity_term(term: str) -> bool:
    return term.startswith(_IDENTITY_TERM_PREFIXES)


def semantic_memory_terms(text: str) -> set[str]:
    aliases = {
        "docs": "document",
        "doc": "document",
        "documents": "document",
        "audio": "audio",
        "graphs": "graph",
        "image": "image",
        "images": "image",
        "invoice": "invoice",
        "invoices": "invoice",
        "memories": "memory",
        "memo": "note",
        "memos": "note",
        "notes": "note",
        "own": "owner",
        "owned": "owner",
        "owns": "owner",
        "photo": "image",
        "photos": "image",
        "record": "transcript",
        "recorded": "transcript",
        "recording": "transcript",
        "recap": "note",
        "responsibility": "owner",
        "responsible": "owner",
        "retrieves": "retrieval",
        "search": "retrieval",
        "searched": "retrieval",
        "searches": "retrieval",
        "screenshot": "screenshot",
        "screenshots": "screenshot",
        "summaries": "note",
        "summary": "note",
        "transcripts": "transcript",
        "video": "video",
        "videos": "video",
        "vectors": "vector",
        "аудио": "audio",
        "видео": "video",
        "видеозапись": "video",
        "видеофрагмент": "video",
        "владельц": "owner",
        "владелец": "owner",
        "демо": "demo",
        "документ": "document",
        "документа": "document",
        "документам": "document",
        "документами": "document",
        "документах": "document",
        "документов": "document",
        "документы": "document",
        "использовать": "uses",
        "использует": "uses",
        "искать": "retrieval",
        "ищем": "retrieval",
        "запись": "transcript",
        "изображение": "image",
        "инвойс": "invoice",
        "итог": "note",
        "итоги": "note",
        "картинка": "image",
        "конспект": "note",
        "мемо": "note",
        "заметка": "note",
        "заметки": "note",
        "заметк": "note",
        "поиск": "retrieval",
        "показал": "shows",
        "показано": "shows",
        "показывает": "shows",
        "проект": "project",
        "проекта": "project",
        "проекте": "project",
        "проектам": "project",
        "проектами": "project",
        "проектах": "project",
        "проектов": "project",
        "проекту": "project",
        "проекты": "project",
        "снимок": "screenshot",
        "созвон": "call",
        "скриншот": "screenshot",
        "скриншота": "screenshot",
        "скриншоте": "screenshot",
        "счет": "invoice",
        "счета": "invoice",
        "счёт": "invoice",
        "счёта": "invoice",
        "транскрипт": "transcript",
        "отвечает": "owner",
        "ответственен": "owner",
        "ответственна": "owner",
        "ответственный": "owner",
        "ответственная": "owner",
        "фото": "image",
        "фотография": "image",
        "фрагмент": "segment",
        "владеет": "owner",
        "хранилище": "storage",
        "хранит": "storage",
        "хранить": "storage",
        "хранят": "storage",
    }
    terms = set(_semantic_anchor_terms(text))
    for raw_token in normalize_memory_text(text).split():
        token = raw_token.strip(".,:;!?()[]{}\"'")
        if not token:
            continue
        token = aliases.get(token, _normalize_russian_semantic_token(token))
        token = aliases.get(token, token)
        if token.endswith("s") and len(token) > 5 and token not in {"postgres", "redis"}:
            token = token[:-1]
        if token in {
            "about",
            "again",
            "already",
            "decided",
            "durable",
            "fact",
            "only",
            "should",
            "store",
            "that",
            "this",
            "use",
            "uses",
            "using",
            "with",
            "был",
            "была",
            "были",
            "для",
            "его",
            "или",
            "как",
            "надо",
            "нужно",
            "пришел",
            "пришла",
            "пришло",
            "сказал",
            "сказала",
            "через",
            "что",
            "это",
        }:
            continue
        if len(token) >= 4:
            terms.add(token)
            if re.search(r"[а-яё]", token, re.IGNORECASE):
                canonical_token = canonical_anchor_key(token)
                transliterated = aliases.get(canonical_token, canonical_token)
                if transliterated and transliterated != token and len(transliterated) >= 4:
                    terms.add(transliterated)
    return terms


def _semantic_anchor_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    anchors = tuple(extract_observed_anchors(text))
    has_event = any(anchor.kind == MemoryAnchorKind.EVENT for anchor in anchors)
    explicit_event_participants = {
        str(anchor.metadata.get("event_participant_canonical_key") or "").strip().casefold()
        for anchor in anchors
        if anchor.kind == MemoryAnchorKind.EVENT
    }
    explicit_event_participants.discard("")
    for anchor in anchors:
        if anchor.kind == MemoryAnchorKind.EVENT:
            terms.extend(_event_semantic_terms(anchor))
            continue
        if anchor.kind not in {
            MemoryAnchorKind.PERSON,
            MemoryAnchorKind.PROJECT,
            MemoryAnchorKind.ORGANIZATION,
        }:
            continue
        canonical_key = str(anchor.metadata.get("canonical_key") or anchor.normalized_key).strip()
        if not canonical_key:
            continue
        if anchor.kind == MemoryAnchorKind.PERSON and _is_false_person_anchor_key(
            canonical_key
        ):
            continue
        normalized_key = canonical_key.casefold()
        terms.append(f"{anchor.kind.value}:{normalized_key}")
        if (
            anchor.kind == MemoryAnchorKind.PERSON
            and has_event
            and not explicit_event_participants
        ):
            terms.append(f"event_participant:{normalized_key}")
    return tuple(terms)


def _is_false_person_anchor_key(canonical_key: str) -> bool:
    return canonical_key.strip().casefold() in {
        "audio",
        "backend",
        "database",
        "doc",
        "docs",
        "document",
        "frontend",
        "graph",
        "graphiti",
        "image",
        "itogi",
        "memory",
        "mysql",
        "neo4j",
        "note",
        "notes",
        "postgres",
        "provider",
        "qdrant",
        "recording",
        "recap",
        "redis",
        "retrieval",
        "screenshot",
        "sqlite",
        "storage",
        "summary",
        "transcript",
        "vector",
        "vectors",
        "video",
    }


def _event_semantic_terms(anchor: ObservedAnchor) -> tuple[str, ...]:
    metadata = anchor.metadata
    terms: list[str] = []
    event_type = _normalized_event_type(metadata.get("event_type_canonical"))
    if event_type:
        terms.append(f"event_type:{event_type}")
    participant = _person_identity_key(metadata.get("event_participant_canonical_key"))
    if participant:
        terms.append(f"event_participant:{participant}")
    project = str(metadata.get("event_project_canonical_key") or "").strip().casefold()
    if project:
        terms.append(f"event_project:{project}")
    temporal = _event_temporal_identity(metadata).strip().casefold()
    if temporal:
        terms.append(f"event_temporal:{temporal}")
    return tuple(terms)


def _normalize_russian_semantic_token(token: str) -> str:
    if not re.search(r"[а-яё]", token, re.IGNORECASE):
        return token
    if len(token) <= 4:
        return token
    suffixes = (
        ("иями", "ия"),
        ("ями", "я"),
        ("ами", "а"),
        ("ого", ""),
        ("ему", ""),
        ("ыми", ""),
        ("ими", ""),
        ("ах", ""),
        ("ях", "я"),
        ("ов", ""),
        ("ев", "й"),
        ("ом", ""),
        ("ем", ""),
        ("е", ""),
        ("ам", ""),
        ("ям", "я"),
        ("у", ""),
        ("а", ""),
        ("ы", ""),
        ("и", ""),
    )
    for suffix, replacement in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return f"{token[: -len(suffix)]}{replacement}"
    return token


def looks_conflicting_fact(candidate_text: str, existing_text: str) -> bool:
    return describe_conflicting_fact_match(candidate_text, existing_text) is not None


def describe_conflicting_fact_match(
    candidate_text: str,
    existing_text: str,
) -> FactConflictMatch | None:
    candidate_normalized = normalize_memory_text(candidate_text)
    existing_normalized = normalize_memory_text(existing_text)
    if not candidate_normalized or not existing_normalized:
        return None
    if candidate_normalized == existing_normalized:
        return None
    if looks_equivalent_fact(candidate_normalized, existing_normalized):
        return None
    decision_terms = {
        "adapter",
        "backend",
        "cache",
        "canonical",
        "cognee",
        "database",
        "engine",
        "graphiti",
        "memory",
        "model",
        "neo4j",
        "postgres",
        "provider",
        "qdrant",
        "rag",
        "storage",
        "truth",
        "vector",
    }
    candidate_terms = semantic_memory_terms(candidate_normalized)
    existing_terms = semantic_memory_terms(existing_normalized)
    overlap = candidate_terms & existing_terms
    if len(overlap) < 2:
        return None
    if _has_named_anchor_mismatch(candidate_text, existing_text):
        return None
    if _has_event_identity_mismatch(candidate_text, existing_text):
        return None
    if _has_numeric_value_mismatch(candidate_text, existing_text):
        if bool(overlap & decision_terms) or len(overlap) >= 3:
            return _conflict_match(
                match_type="numeric_value_mismatch",
                reason_codes=("semantic_conflict", "numeric_value_mismatch"),
                overlap=overlap,
                candidate_terms=candidate_terms,
                existing_terms=existing_terms,
            )
        return None
    if _has_negation_mismatch(candidate_normalized, existing_normalized):
        if bool(overlap & decision_terms) or len(overlap) >= 3:
            return _conflict_match(
                match_type="negation_mismatch",
                reason_codes=("semantic_conflict", "negation_mismatch"),
                overlap=overlap,
                candidate_terms=candidate_terms,
                existing_terms=existing_terms,
            )
        return None
    if _has_exclusive_anchor_mismatch(candidate_terms, existing_terms):
        if overlap & decision_terms:
            return _conflict_match(
                match_type="exclusive_anchor_mismatch",
                reason_codes=("semantic_conflict", "exclusive_anchor_mismatch"),
                overlap=overlap,
                candidate_terms=candidate_terms,
                existing_terms=existing_terms,
            )
        return None
    if bool(overlap & decision_terms) and len(overlap) >= 3:
        return _conflict_match(
            match_type="decision_term_overlap",
            reason_codes=("semantic_conflict", "decision_term_overlap"),
            overlap=overlap,
            candidate_terms=candidate_terms,
            existing_terms=existing_terms,
        )
    return None


def _conflict_match(
    *,
    match_type: str,
    reason_codes: tuple[str, ...],
    overlap: set[str],
    candidate_terms: set[str],
    existing_terms: set[str],
) -> FactConflictMatch:
    union = candidate_terms | existing_terms
    score = len(overlap) / len(union) if union else 0.0
    return FactConflictMatch(
        match_type=match_type,
        score=round(score, 3),
        reason_codes=reason_codes,
        overlap_terms=tuple(sorted(overlap))[:12],
    )


def _has_negation_mismatch(candidate_text: str, existing_text: str) -> bool:
    negation_terms = {"avoid", "disable", "disabled", "except", "never", "not", "without"}
    candidate_has_negation = bool(
        set(normalize_memory_text(candidate_text).split()) & negation_terms
    )
    existing_has_negation = bool(
        set(normalize_memory_text(existing_text).split()) & negation_terms
    )
    return candidate_has_negation != existing_has_negation


def _has_exclusive_anchor_mismatch(
    candidate_terms: set[str],
    existing_terms: set[str],
) -> bool:
    engines = {"cognee", "graphiti", "mysql", "neo4j", "postgres", "qdrant", "redis", "sqlite"}
    candidate_engines = candidate_terms & engines
    existing_engines = existing_terms & engines
    return bool(candidate_engines and existing_engines and not candidate_engines & existing_engines)


def _has_numeric_value_mismatch(candidate_text: str, existing_text: str) -> bool:
    candidate_values = _numeric_value_groups(candidate_text)
    existing_values = _numeric_value_groups(existing_text)
    for group in candidate_values.keys() & existing_values.keys():
        if candidate_values[group] != existing_values[group]:
            return True
    return False


def _numeric_value_groups(text: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for match in _NUMERIC_VALUE_RE.finditer(normalize_memory_text(text)):
        number = _normalize_numeric_value(match.group("number"))
        if not number:
            continue
        group = _numeric_value_group(
            prefix=match.group("prefix") or "",
            unit=match.group("unit") or "",
        )
        values.setdefault(group, set()).add(number)
    return values


def _numeric_value_group(*, prefix: str, unit: str) -> str:
    normalized_prefix = prefix.strip().casefold()
    if normalized_prefix:
        return "version"
    normalized_unit = _normalize_numeric_unit(unit)
    return normalized_unit or "number"


def _normalize_numeric_value(raw_value: str) -> str:
    value = raw_value.replace(",", ".")
    integer, separator, fraction = value.partition(".")
    integer = integer.lstrip("0") or "0"
    if not separator:
        return integer
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def _normalize_numeric_unit(raw_unit: str) -> str:
    unit = raw_unit.strip().casefold()
    aliases = {
        "%": "percent",
        "percent": "percent",
        "percentage": "percent",
        "millisecond": "ms",
        "milliseconds": "ms",
        "msec": "ms",
        "msecs": "ms",
        "second": "second",
        "seconds": "second",
        "sec": "second",
        "secs": "second",
        "minute": "minute",
        "minutes": "minute",
        "min": "minute",
        "mins": "minute",
        "hour": "hour",
        "hours": "hour",
        "hr": "hour",
        "hrs": "hour",
        "day": "day",
        "days": "day",
        "week": "week",
        "weeks": "week",
        "month": "month",
        "months": "month",
        "year": "year",
        "years": "year",
        "page": "page",
        "pages": "page",
        "token": "token",
        "tokens": "token",
        "gb": "gb",
        "mb": "mb",
        "kb": "kb",
        "replica": "replica",
        "replicas": "replica",
        "shard": "shard",
        "shards": "shard",
    }
    return aliases.get(unit, unit)


def _has_named_anchor_mismatch(candidate_text: str, existing_text: str) -> bool:
    candidate_projects = _named_anchor_keys(
        candidate_text,
        kind=MemoryAnchorKind.PROJECT,
        reasons={"explicit project reference"},
    )
    existing_projects = _named_anchor_keys(
        existing_text,
        kind=MemoryAnchorKind.PROJECT,
        reasons={"explicit project reference"},
    )
    if candidate_projects and existing_projects and not candidate_projects & existing_projects:
        return True

    candidate_people = _named_anchor_keys(candidate_text, kind=MemoryAnchorKind.PERSON)
    existing_people = _named_anchor_keys(existing_text, kind=MemoryAnchorKind.PERSON)
    if candidate_people and existing_people and not candidate_people & existing_people:
        return True

    candidate_orgs = _named_anchor_keys(candidate_text, kind=MemoryAnchorKind.ORGANIZATION)
    existing_orgs = _named_anchor_keys(existing_text, kind=MemoryAnchorKind.ORGANIZATION)
    return bool(candidate_orgs and existing_orgs and not candidate_orgs & existing_orgs)


def _has_event_identity_mismatch(candidate_text: str, existing_text: str) -> bool:
    candidate_events = _event_identity_payloads(candidate_text)
    existing_events = _event_identity_payloads(existing_text)
    if not candidate_events or not existing_events:
        return False
    candidate_project_events = tuple(event for event in candidate_events if event.get("project"))
    existing_project_events = tuple(event for event in existing_events if event.get("project"))
    if candidate_project_events and existing_project_events:
        for candidate in candidate_project_events:
            for existing in existing_project_events:
                if _event_payloads_compatible(candidate, existing):
                    return False
        return True
    for candidate in candidate_events:
        for existing in existing_events:
            if _event_payloads_compatible(candidate, existing):
                return False
    return True


def _event_identity_payloads(text: str) -> tuple[dict[str, str], ...]:
    payloads: list[dict[str, str]] = []
    for anchor in extract_observed_anchors(text):
        if anchor.kind != MemoryAnchorKind.EVENT:
            continue
        metadata = anchor.metadata
        payload = {
            "event_type": _normalized_event_type(metadata.get("event_type_canonical")),
            "participant": _person_identity_key(metadata.get("event_participant_canonical_key")),
            "project": str(metadata.get("event_project_canonical_key") or ""),
            "temporal": _event_temporal_identity(metadata),
        }
        if any(payload.values()):
            payloads.append(payload)
    return tuple(payloads)


def _event_payloads_compatible(candidate: dict[str, str], existing: dict[str, str]) -> bool:
    for key in ("event_type", "participant", "project", "temporal"):
        left = candidate.get(key, "")
        right = existing.get(key, "")
        if left and right and left != right:
            return False
    return True


def _normalized_event_type(value: object) -> str:
    event_type = str(value or "").strip().casefold()
    return _EVENT_TYPE_ALIASES.get(event_type, event_type)


def _event_temporal_identity(metadata: dict[str, object]) -> str:
    code = str(metadata.get("event_temporal_hint_code") or "")
    if not code:
        return ""
    quantity = metadata.get("event_temporal_quantity")
    unit = str(metadata.get("event_temporal_unit") or "")
    return f"{code}:{quantity}:{unit}" if quantity is not None and unit else code


def _named_anchor_keys(
    text: str,
    *,
    kind: MemoryAnchorKind,
    reasons: set[str] | None = None,
) -> set[str]:
    return {
        key
        for anchor in extract_observed_anchors(text)
        if (key := _canonical_named_anchor_key(anchor))
        if anchor.kind == kind and (reasons is None or anchor.reason in reasons)
        and not (kind == MemoryAnchorKind.PERSON and _is_false_person_anchor_key(key))
    }


def _canonical_named_anchor_key(anchor: ObservedAnchor) -> str:
    canonical_key = anchor.metadata.get("canonical_key")
    if isinstance(canonical_key, str) and canonical_key.strip():
        return canonical_key.strip().casefold()
    return anchor.normalized_key.strip().casefold()


def _has_event_anchor(text: str) -> bool:
    return any(anchor.kind == MemoryAnchorKind.EVENT for anchor in extract_observed_anchors(text))


def _person_identity_key(value: object) -> str:
    key = str(value or "").strip().casefold()
    return "" if _is_false_person_anchor_key(key) else key
