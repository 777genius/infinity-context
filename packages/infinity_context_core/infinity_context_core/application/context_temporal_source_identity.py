"""Source identity helpers for source-turn temporal retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping

from infinity_context_core.application.context_temporal_source_turn_patterns import (
    _SOURCE_TURN_IDENTITY_RE,
    _SOURCE_TURN_RE,
)


def source_identity_from_label(value: str) -> str:
    text = value.strip().strip(".,!?;()[]{}<>\"'")
    if not text or re.search(r"\s", text):
        return ""
    if _SOURCE_TURN_RE.fullmatch(text):
        return ""
    normalized = _SOURCE_TURN_IDENTITY_RE.sub("d*:t*", text.casefold())
    return normalized.strip(":-_")


def source_scope_identity_from_label(value: str) -> str:
    text = value.strip().strip(".,!?;()[]{}<>\"'")
    if not text or re.search(r"\s", text):
        return ""
    if identity := source_identity_from_label(text):
        return identity
    normalized = text.casefold().strip(":-_")
    if (
        "locomo" in normalized
        or re.search(r"(?:^|[:_-])conv[-_:]?\d", normalized)
        or re.search(r"(?:^|[:_-])session[-_:]?\d", normalized)
    ):
        return normalized
    return ""


def direct_source_scope_identity_from_label(value: str) -> str:
    text = value.strip().strip(".,!?;()[]{}<>\"'")
    normalized = text.casefold()
    if "locomo" not in normalized and not re.search(r"(?:^|[:_-])conv[-_:]?\d", normalized):
        return ""
    return source_scope_identity_from_label(text)


def conversation_source_scope_identity_from_label(value: str) -> str:
    text = value.casefold()
    if (
        "locomo" not in text
        and not re.search(r"(?:^|[:_-])conv[-_:]?\w", text)
        and not re.search(r"(?:^|[:_-])session[-_:]?\d", text)
    ):
        return ""
    return source_scope_identity_from_label(value)


def source_scope_identity_from_mapping(mapping: Mapping[str, object]) -> str:
    for key in (
        "source_id",
        "source_ref",
        "source_ref_id",
        "source_identity",
        "source_key",
    ):
        value = mapping.get(key)
        if isinstance(value, str) and (
            scope_identity := source_scope_identity_from_label(value)
        ):
            return scope_identity
    return ""


def source_identity_matches(first: str, second: str) -> bool:
    if first == second:
        return True
    normalized_first = normalized_source_identity(first)
    normalized_second = normalized_source_identity(second)
    if normalized_first == normalized_second:
        return True
    return source_identity_has_scope(first, second) or source_identity_has_scope(
        second,
        first,
    )


def source_identity_has_scope(identity: str, scope: str) -> bool:
    if identity.startswith(f"{scope}:") or identity.startswith(f"{scope}-"):
        return True
    normalized_identity = normalized_source_identity(identity)
    normalized_scope = normalized_source_identity(scope)
    return normalized_identity.startswith(f"{normalized_scope}:")


def normalized_source_identity(value: str) -> str:
    return re.sub(r"[:_-]+", ":", value.casefold()).strip(":")
