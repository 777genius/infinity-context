"""Computed identity profiles for canonical anchor context items."""

from __future__ import annotations

from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import MemoryAnchor

_MAX_IDENTITY_TERMS = 8


def anchor_identity_profile(
    anchor: MemoryAnchor,
    *,
    metadata: dict[str, object],
) -> dict[str, object]:
    identity_terms = _identity_terms(metadata)
    components = _identity_components(metadata=metadata, identity_terms=identity_terms)
    return {
        "schema_version": "anchor-identity-profile-v1",
        "anchor_kind": anchor.kind.value,
        "normalized_key": _safe_text(anchor.normalized_key, limit=160),
        "primary_identity_key": _primary_identity_key(anchor=anchor, metadata=metadata),
        "identity_scope": _metadata_text(metadata, "identity_scope"),
        "identity_term_count": len(identity_terms),
        "identity_terms": list(identity_terms),
        "alias_count": len(anchor.aliases),
        "alias_identity_term_count": _list_count(metadata.get("alias_identity_terms")),
        "event_identity_term_count": _list_count(metadata.get("event_identity_terms")),
        "has_event_participant": bool(_metadata_text(metadata, "event_participant_canonical_key")),
        "has_event_project": bool(
            _metadata_text(metadata, "event_project_canonical_key")
            or _metadata_text(metadata, "project_canonical_key")
        ),
        "has_event_temporal_hint": bool(_metadata_text(metadata, "event_temporal_hint_code")),
        "event_type": _metadata_text(metadata, "event_type_canonical")
        or _metadata_text(metadata, "event_type"),
        "identity_components": list(components),
    }


def _primary_identity_key(
    *,
    anchor: MemoryAnchor,
    metadata: dict[str, object],
) -> str:
    typed_key = _typed_canonical_identity_key(anchor=anchor, metadata=metadata)
    if typed_key:
        return typed_key
    for key in (
        "identity_key",
        "event_participant_canonical_key",
        "event_project_canonical_key",
        "canonical_key",
    ):
        if text := _metadata_text(metadata, key):
            return text
    return _safe_text(anchor.normalized_key, limit=160)


def _typed_canonical_identity_key(
    *,
    anchor: MemoryAnchor,
    metadata: dict[str, object],
) -> str:
    kind = anchor.kind.value
    key_name = {
        "person": "person_canonical_key",
        "project": "project_canonical_key",
        "organization": "organization_canonical_key",
    }.get(kind)
    if key_name is None:
        return ""
    canonical_key = _metadata_text(metadata, key_name)
    return f"{kind}:{canonical_key}" if canonical_key else ""


def _identity_terms(metadata: dict[str, object]) -> tuple[str, ...]:
    terms: list[str] = []
    for key in (
        "event_identity_terms",
        "alias_identity_terms",
    ):
        terms.extend(_safe_list(metadata.get(key), limit=120))
    for key in (
        "person_canonical_key",
        "project_canonical_key",
        "organization_canonical_key",
        "event_participant_canonical_key",
        "event_project_canonical_key",
        "canonical_key",
    ):
        if text := _metadata_text(metadata, key):
            terms.append(text)
    return _dedupe_preserve_order(tuple(terms))[:_MAX_IDENTITY_TERMS]


def _identity_components(
    *,
    metadata: dict[str, object],
    identity_terms: tuple[str, ...],
) -> tuple[str, ...]:
    components: list[str] = []
    if _metadata_text(metadata, "person_canonical_key"):
        components.append("person")
    if _metadata_text(metadata, "project_canonical_key"):
        components.append("project")
    if _metadata_text(metadata, "organization_canonical_key"):
        components.append("organization")
    if _metadata_text(metadata, "event_type_canonical") or _metadata_text(metadata, "event_type"):
        components.append("event_type")
    if _metadata_text(metadata, "event_participant_canonical_key"):
        components.append("event_participant")
    if _metadata_text(metadata, "event_project_canonical_key"):
        components.append("event_project")
    if _metadata_text(metadata, "event_temporal_hint_code"):
        components.append("event_temporal_hint")
    if identity_terms:
        components.append("identity_terms")
    return _dedupe_preserve_order(tuple(components))


def _metadata_text(metadata: dict[str, object], key: str) -> str:
    return _safe_text(metadata.get(key), limit=160)


def _safe_text(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    text = safe_metadata_text(str(value), limit=limit).strip()
    return "" if "[redacted]" in text else text


def _safe_list(value: object, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        text
        for item in value[:_MAX_IDENTITY_TERMS]
        if (text := _safe_text(item, limit=limit))
    )


def _list_count(value: object) -> int:
    return len(_safe_list(value, limit=120))


def _dedupe_preserve_order(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.strip().split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)
