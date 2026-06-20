"""Shared matching policy for rule-observed memory anchors."""

from __future__ import annotations

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key,
    normalize_anchor_key,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryAnchor,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkPort

_CROSS_SCRIPT_CANONICAL_KINDS = {
    MemoryAnchorKind.ORGANIZATION,
    MemoryAnchorKind.PROJECT,
}
_UNSAFE_CROSS_SCRIPT_CANONICAL_KEYS = {
    "api",
    "app",
    "chat",
    "demo",
    "dev",
    "docs",
    "test",
    "team",
}


async def find_active_by_observed_canonical_key(
    uow: UnitOfWorkPort,
    *,
    observed: ObservedAnchor,
    space_id: SpaceId,
    memory_scope_id: MemoryScopeId,
) -> MemoryAnchor | None:
    observed_key = observed_canonical_key(observed)
    if not observed_key:
        return None
    anchors = await uow.anchors.list_for_scope(
        space_id=str(space_id),
        memory_scope_id=str(memory_scope_id),
        kind=observed.kind.value,
        status=LifecycleStatus.ACTIVE.value,
        limit=500,
    )
    for anchor in anchors:
        if observed_key in canonical_anchor_keys(anchor) and _safe_canonical_identity_match(
            anchor=anchor,
            observed=observed,
            observed_key=observed_key,
        ):
            return anchor
    if observed.kind == MemoryAnchorKind.PERSON:
        return _single_person_initial_match(
            anchors=anchors,
            observed=observed,
            observed_key=observed_key,
        )
    return None


def preferred_observed_label(anchor: MemoryAnchor, observed: ObservedAnchor) -> str | None:
    observed_key = observed_canonical_key(observed)
    if observed.kind == MemoryAnchorKind.PERSON and _person_initial_matches_anchor(
        anchor=anchor,
        observed=observed,
        observed_key=observed_key,
    ):
        return None
    if (
        observed_key
        and observed_key in canonical_anchor_keys(anchor)
        and anchor.kind != MemoryAnchorKind.PERSON
    ):
        return None
    if (
        observed_key
        and observed_key in canonical_anchor_keys(anchor)
        and len(normalize_anchor_key(anchor.label)) <= len(normalize_anchor_key(observed.label))
    ):
        return None
    return observed.label


def should_promote_observed_key(anchor: MemoryAnchor, observed: ObservedAnchor) -> bool:
    observed_key = observed_canonical_key(observed)
    return bool(
        anchor.kind == MemoryAnchorKind.PERSON
        and observed.kind == MemoryAnchorKind.PERSON
        and observed_key
        and observed_key in canonical_anchor_keys(anchor)
        and _same_script_family(anchor.label, observed.label)
        and anchor.normalized_key != observed.normalized_key
        and len(normalize_anchor_key(observed.label)) < len(normalize_anchor_key(anchor.label))
    )


def _single_person_initial_match(
    *,
    anchors: list[MemoryAnchor],
    observed: ObservedAnchor,
    observed_key: str,
) -> MemoryAnchor | None:
    matches = [
        anchor
        for anchor in anchors
        if _person_initial_matches_anchor(
            anchor=anchor,
            observed=observed,
            observed_key=observed_key,
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _person_initial_matches_anchor(
    *,
    anchor: MemoryAnchor,
    observed: ObservedAnchor,
    observed_key: str | None,
) -> bool:
    if (
        anchor.kind != MemoryAnchorKind.PERSON
        or observed.kind != MemoryAnchorKind.PERSON
        or not observed_key
        or not _same_script_family(anchor.label, observed.label)
    ):
        return False
    observed_initial = _person_initial_key(observed_key)
    if observed_initial is None:
        return False
    return any(
        _initial_key_matches_full_key(observed_initial, candidate_key)
        for candidate_key in canonical_anchor_keys(anchor)
    )


def _person_initial_key(value: str) -> tuple[str, str] | None:
    parts = value.split()
    if len(parts) != 2 or len(parts[0]) < 2 or len(parts[1]) != 1:
        return None
    return parts[0], parts[1]


def _initial_key_matches_full_key(initial_key: tuple[str, str], full_key: str) -> bool:
    parts = full_key.split()
    if len(parts) < 2:
        return False
    first, initial = initial_key
    return parts[0] == first and len(parts[1]) > 1 and parts[1].startswith(initial)


def observed_canonical_key(observed: ObservedAnchor) -> str | None:
    value = observed.metadata.get("canonical_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def canonical_anchor_keys(anchor: MemoryAnchor) -> set[str]:
    keys = {
        canonical_anchor_key(anchor.normalized_key),
        canonical_anchor_key(anchor.label),
    }
    keys.update(canonical_anchor_key(alias) for alias in anchor.aliases)
    for metadata_name in (
        "canonical_key",
        "person_canonical_key",
        "project_canonical_key",
        "organization_canonical_key",
    ):
        metadata_key = anchor.metadata.get(metadata_name)
        if isinstance(metadata_key, str):
            keys.add(metadata_key.strip().casefold())
    return {key for key in keys if key}


def _safe_canonical_identity_match(
    *,
    anchor: MemoryAnchor,
    observed: ObservedAnchor,
    observed_key: str,
) -> bool:
    if _same_script_family(anchor.label, observed.label):
        return True
    return (
        anchor.kind in _CROSS_SCRIPT_CANONICAL_KINDS
        and observed.kind == anchor.kind
        and _is_stable_cross_script_canonical_key(observed_key)
    )


def _is_stable_cross_script_canonical_key(value: str) -> bool:
    compact = "".join(value.split()).casefold()
    return (
        len(compact) >= 4
        and compact not in _UNSAFE_CROSS_SCRIPT_CANONICAL_KEYS
        and any("a" <= char <= "z" for char in compact)
    )


def _same_script_family(left: str, right: str) -> bool:
    left_family = _script_family(left)
    right_family = _script_family(right)
    return left_family == right_family and left_family != "mixed"


def _script_family(value: str) -> str:
    normalized = normalize_anchor_key(value)
    has_cyrillic = bool(any("а" <= char <= "я" or char == "ё" for char in normalized))
    has_latin = bool(any("a" <= char <= "z" for char in normalized))
    if has_cyrillic and has_latin:
        return "mixed"
    if has_cyrillic:
        return "cyrillic"
    if has_latin:
        return "latin"
    return "other"
