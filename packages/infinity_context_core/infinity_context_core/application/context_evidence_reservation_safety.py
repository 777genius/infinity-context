"""Shared fail-closed safety admission for evidence reservations."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence

from infinity_context_core.application.context_evidence_priority import (
    has_unresolved_rerank_rejection,
)
from infinity_context_core.application.context_packer_diagnostics import diagnostic_value
from infinity_context_core.application.dto import ContextItem

_MAX_DIAGNOSTIC_DEPTH = 5
_MAX_DIAGNOSTIC_CONTAINERS = 96
_MAX_DIAGNOSTIC_CONTAINER_MEMBERS = 512
_MAX_DIAGNOSTIC_MEMBERS = 1024
_MAX_DIAGNOSTIC_KEY_CHARS = 512
_CONFLICT_KEYS = frozenset(
    {"conflicting_fact_id", "conflict_fact_id", "possible_conflict_fact_id"}
)
_MAX_SOURCE_IDENTITY_PART_CHARS = 512
_INSTRUCTION_PAYLOAD_RE = re.compile(
    r"\b(?:ignore|disregard|override|bypass)\b.{0,48}\b"
    r"(?:instructions?|prompts?|rules?|safeguards?)\b|"
    r"\b(?:system|developer)\s+(?:message|instructions?|prompts?)\b",
    re.IGNORECASE,
)
_UNSAFE_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cn", "Co", "Cs"})


def evidence_reservation_candidate_is_eligible(item: ContextItem) -> bool:
    """Return whether an item may consume a scarce evidence reservation."""

    if (
        item.is_instruction
        or not item.text.strip()
        or not item.source_refs
        or has_unresolved_rerank_rejection(item)
        or _has_unsafe_source_identity(item)
    ):
        return False
    if diagnostic_value(item, "review_only") is True:
        return False
    if diagnostic_value(item, "conflicting_fact_id") is not None:
        return False
    return not _has_nested_blocking_diagnostic(
        item.diagnostics,
        depth=0,
        seen_containers=[0],
        seen_members=[0],
        active_container_ids=set(),
    )


def _has_unsafe_source_identity(item: ContextItem) -> bool:
    for ref in item.source_refs:
        for value in (ref.source_type, ref.source_id, ref.chunk_id):
            if value is None:
                continue
            part = str(value)
            if (
                not part
                or part != part.strip()
                or len(part) > _MAX_SOURCE_IDENTITY_PART_CHARS
                or any(
                    unicodedata.category(char) in _UNSAFE_UNICODE_CATEGORIES
                    for char in part
                )
            ):
                return True
            normalized = re.sub(r"[:_\-]+", " ", part)
            if _INSTRUCTION_PAYLOAD_RE.search(normalized):
                return True
    return False


def _has_nested_blocking_diagnostic(
    value: object,
    *,
    depth: int,
    seen_containers: list[int],
    seen_members: list[int],
    active_container_ids: set[int],
) -> bool:
    """Fail closed on unsafe diagnostics with separate structural and CPU bounds."""

    if not _is_diagnostic_container(value):
        return False
    if depth > _MAX_DIAGNOSTIC_DEPTH:
        return True
    if (
        len(value) > _MAX_DIAGNOSTIC_CONTAINER_MEMBERS
        or seen_containers[0] >= _MAX_DIAGNOSTIC_CONTAINERS
    ):
        return True
    container_id = id(value)
    if container_id in active_container_ids:
        return True
    seen_containers[0] += 1
    active_container_ids.add(container_id)
    try:
        if isinstance(value, Mapping):
            return _mapping_has_blocking_diagnostic(
                value,
                depth=depth,
                seen_containers=seen_containers,
                seen_members=seen_members,
                active_container_ids=active_container_ids,
            )
        return _sequence_has_blocking_diagnostic(
            value,
            depth=depth,
            seen_containers=seen_containers,
            seen_members=seen_members,
            active_container_ids=active_container_ids,
        )
    finally:
        active_container_ids.remove(container_id)


def _mapping_has_blocking_diagnostic(
    value: Mapping[object, object],
    *,
    depth: int,
    seen_containers: list[int],
    seen_members: list[int],
    active_container_ids: set[int],
) -> bool:
    for key, nested in value.items():
        if _diagnostic_member_budget_exhausted(seen_members):
            return True
        normalized_key = _normalized_diagnostic_key(key)
        if normalized_key is None:
            return True
        if normalized_key in _CONFLICT_KEYS and _has_material_value(nested):
            return True
        if normalized_key == "review_only" and nested is True:
            return True
        if _has_nested_blocking_diagnostic(
            nested,
            depth=depth + 1,
            seen_containers=seen_containers,
            seen_members=seen_members,
            active_container_ids=active_container_ids,
        ):
            return True
    return False


def _sequence_has_blocking_diagnostic(
    value: Sequence[object],
    *,
    depth: int,
    seen_containers: list[int],
    seen_members: list[int],
    active_container_ids: set[int],
) -> bool:
    for nested in value:
        if _diagnostic_member_budget_exhausted(seen_members):
            return True
        if _has_nested_blocking_diagnostic(
            nested,
            depth=depth + 1,
            seen_containers=seen_containers,
            seen_members=seen_members,
            active_container_ids=active_container_ids,
        ):
            return True
    return False


def _diagnostic_member_budget_exhausted(seen_members: list[int]) -> bool:
    if seen_members[0] >= _MAX_DIAGNOSTIC_MEMBERS:
        return True
    seen_members[0] += 1
    return False


def _normalized_diagnostic_key(key: object) -> str | None:
    if not isinstance(key, str) or len(key) > _MAX_DIAGNOSTIC_KEY_CHARS:
        return None
    normalized = key.strip().casefold()
    if not normalized or any(
        unicodedata.category(char) in _UNSAFE_UNICODE_CATEGORIES for char in key
    ):
        return None
    return normalized


def _is_diagnostic_container(value: object) -> bool:
    return isinstance(value, Mapping) or _is_diagnostic_sequence(value)


def _is_diagnostic_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _has_material_value(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


__all__ = ("evidence_reservation_candidate_is_eligible",)
