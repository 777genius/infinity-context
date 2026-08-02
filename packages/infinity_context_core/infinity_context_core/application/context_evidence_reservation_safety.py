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
_MAX_DIAGNOSTIC_VALUES = 96
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
    return not _has_nested_blocking_diagnostic(item.diagnostics, depth=0, seen=[0])


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
    seen: list[int],
) -> bool:
    if depth > _MAX_DIAGNOSTIC_DEPTH or seen[0] >= _MAX_DIAGNOSTIC_VALUES:
        return True
    seen[0] += 1
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).strip().casefold()
            if normalized_key in _CONFLICT_KEYS and _has_material_value(nested):
                return True
            if normalized_key == "review_only" and nested is True:
                return True
            if _has_nested_blocking_diagnostic(nested, depth=depth + 1, seen=seen):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(
            _has_nested_blocking_diagnostic(nested, depth=depth + 1, seen=seen)
            for nested in value[:_MAX_DIAGNOSTIC_VALUES]
        )
    return False


def _has_material_value(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


__all__ = ("evidence_reservation_candidate_is_eligible",)
