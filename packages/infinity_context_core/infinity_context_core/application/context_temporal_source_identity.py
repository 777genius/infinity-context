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
    return _canonical_conversation_identity(normalized).strip(":-_")


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
    if (
        "locomo" not in normalized
        and not re.search(r"(?:^|[:_-])conv[-_:]?\d", normalized)
        and not re.search(r"(?:^|[:_-])conversation[-_:]?\d", normalized)
    ):
        return ""
    return source_scope_identity_from_label(text)


def conversation_source_scope_identity_from_label(value: str) -> str:
    text = value.casefold()
    if (
        "locomo" not in text
        and not re.search(r"(?:^|[:_-])conv(?:[-_:]\w|\d)", text)
        and not re.search(r"(?:^|[:_-])conversation[-_:]?\d", text)
        and not re.search(r"(?:^|[:_-])session[-_:]?\d", text)
    ):
        return ""
    return source_scope_identity_from_label(value)


def source_scope_identity_from_mapping(mapping: Mapping[str, object]) -> str:
    combined_identity = _combined_conversation_session_scope_identity(mapping)
    for key in (
        "source_id",
        "source_external_id",
        "source_ref",
        "source_ref_id",
        "source_identity",
        "source_identity_ref",
        "source_key",
    ):
        value = mapping.get(key)
        if isinstance(value, str) and (
            scope_identity := source_scope_identity_from_label(value)
        ):
            if combined_identity and not _source_identity_has_explicit_scope(
                scope_identity
            ):
                continue
            return scope_identity
    if combined_identity:
        return combined_identity
    for key in (
        "locomo_session_index",
        "locomo_session_key",
        "locomo_session_number",
        "source_session_id",
        "source_session_index",
        "source_session_key",
        "source_session_number",
        "session_index",
        "session_number",
        "session_order",
        "session_key",
    ):
        value = mapping.get(key)
        if scope_identity := explicit_session_scope_identity_from_value(value):
            return scope_identity
    value = mapping.get("session_id")
    if isinstance(value, str) and (
        scope_identity := conversation_source_scope_identity_from_label(value)
    ):
        return scope_identity
    return ""


def explicit_session_scope_identity_from_value(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, str):
        if scope_identity := conversation_source_scope_identity_from_label(value):
            return scope_identity
        text = value.strip()
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        return ""
    if re.fullmatch(r"\d{1,4}", text) and int(text) > 0:
        return f"session_{int(text)}"
    return ""


def source_identity_matches(first: str, second: str) -> bool:
    if first == second:
        return True
    normalized_first = normalized_source_identity(first)
    normalized_second = normalized_source_identity(second)
    if normalized_first == normalized_second:
        return True
    if _conv_scoped_identity_contains(normalized_first, normalized_second):
        return True
    if _conv_scoped_identity_contains(normalized_second, normalized_first):
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
    return re.sub(
        r"[:_-]+",
        ":",
        _canonical_conversation_identity(value.casefold()),
    ).strip(":")


def _source_identity_has_explicit_scope(value: str) -> bool:
    normalized = _canonical_conversation_identity(value.casefold())
    return (
        "locomo" in normalized
        or re.search(r"(?:^|[:_-])conv(?:[-_:]\w|\d)", normalized) is not None
        or re.search(r"(?:^|[:_-])session[-_:]?\d", normalized) is not None
    )


def _canonical_conversation_identity(value: str) -> str:
    return re.sub(
        r"(^|[:_-])conversation(?=[-_:]?\d)",
        r"\1conv",
        value,
        flags=re.IGNORECASE,
    )


def _combined_conversation_session_scope_identity(
    mapping: Mapping[str, object],
) -> str:
    conversation_identity = _conversation_scope_identity_from_mapping(mapping)
    session_identity = _session_scope_identity_from_mapping(mapping)
    if not conversation_identity or not session_identity:
        return ""
    if source_identity_matches(conversation_identity, session_identity):
        return conversation_identity
    return f"{conversation_identity}:{session_identity}"


def _conversation_scope_identity_from_mapping(mapping: Mapping[str, object]) -> str:
    for key in (
        "locomo_conversation_id",
        "locomo_conversation_key",
        "source_conversation_id",
        "source_conversation_key",
        "conversation_id",
        "conversation_key",
        "conv_id",
        "conv_key",
    ):
        value = mapping.get(key)
        if scope_identity := _explicit_conversation_scope_identity_from_value(value):
            return scope_identity
    return ""


def _explicit_conversation_scope_identity_from_value(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if match := re.fullmatch(
            r"conversation[-_:]?(?P<number>\d{1,4})",
            text,
            re.IGNORECASE,
        ):
            return f"conv_{int(match.group('number'))}"
        if scope_identity := conversation_source_scope_identity_from_label(text):
            return scope_identity
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        return ""
    if re.fullmatch(r"\d{1,4}", text) and int(text) > 0:
        return f"conv_{int(text)}"
    return ""


def _session_scope_identity_from_mapping(mapping: Mapping[str, object]) -> str:
    for key in (
        "locomo_session_index",
        "locomo_session_key",
        "locomo_session_number",
        "source_session_id",
        "source_session_index",
        "source_session_key",
        "source_session_number",
        "session_index",
        "session_number",
        "session_order",
        "session_key",
        "session_id",
    ):
        if scope_identity := explicit_session_scope_identity_from_value(
            mapping.get(key)
        ):
            return scope_identity
    for key in (
        "source_dialogue_id",
        "source_dialogue_index",
        "dialogue_id",
        "dialogue_index",
        "dia_id",
    ):
        if scope_identity := _dialogue_session_scope_identity_from_value(
            mapping.get(key)
        ):
            return scope_identity
    for key in (
        "source_turn",
        "source_turn_ref",
        "source_turn_reference",
        "turn_metadata",
    ):
        value = mapping.get(key)
        if isinstance(value, Mapping) and (
            scope_identity := _session_scope_identity_from_mapping(value)
        ):
            return scope_identity
    for key in ("source_turn_refs", "source_turn_ref", "source_turn_reference"):
        if scope_identity := _source_turn_ref_session_scope_identity_from_value(
            mapping.get(key)
        ):
            return scope_identity
    return ""


def _dialogue_session_scope_identity_from_value(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, str):
        if scope_identity := explicit_session_scope_identity_from_value(value):
            return scope_identity
        text = value.strip()
        if match := re.fullmatch(
            r"(?:d|dia|dialogue)[-_:]?(?P<number>\d{1,4})",
            text,
            re.IGNORECASE,
        ):
            return f"session_{int(match.group('number'))}"
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        return ""
    if re.fullmatch(r"\d{1,4}", text) and int(text) > 0:
        return f"session_{int(text)}"
    return ""


def _source_turn_ref_session_scope_identity_from_value(value: object) -> str:
    if isinstance(value, str):
        match = re.search(r"\bD(?P<number>\d{1,4})[:-]\d{1,4}\b", value, re.IGNORECASE)
        return f"session_{int(match.group('number'))}" if match else ""
    if isinstance(value, (list, tuple)):
        for nested_value in value:
            if scope_identity := _source_turn_ref_session_scope_identity_from_value(
                nested_value
            ):
                return scope_identity
    return ""


def _conv_scoped_identity_contains(identity: str, scope: str) -> bool:
    if not scope.startswith("conv:"):
        return False
    identity_segments = f":{identity}:"
    return f":{scope}:" in identity_segments
