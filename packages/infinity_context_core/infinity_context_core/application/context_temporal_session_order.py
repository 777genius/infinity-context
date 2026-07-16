"""Session-order helpers for temporal context retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping

from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.context_temporal_source_turn_labels import (
    SOURCE_TURN_LABEL_NUMBER_PATTERN,
    canonicalize_natural_source_turn_labels,
    source_turn_label_number_value,
)
from infinity_context_core.application.dto import ContextItem

_SESSION_NOUN_PATTERN = r"(?:session|conversation|conv|dialogue|dialog|dia)"
_SESSION_ORDINAL_QUERY_NOUN_PATTERN = r"(?:session|dialogue|dialog|dia)"
_OPTIONAL_NUMBER_LABEL_PATTERN = r"(?:(?:number|no\.?)[\s_-]+)?#?"
_SESSION_ORDINAL_RE = re.compile(
    rf"\b(?P<noun>{_SESSION_NOUN_PATTERN})[\s_-]+{_OPTIONAL_NUMBER_LABEL_PATTERN}"
    r"(?P<session>\d{1,4})\b",
    re.IGNORECASE,
)
_DIALOGUE_TURN_RE = re.compile(
    r"\bD(?P<dialogue>\d{1,4})[:-]\d{1,4}\b",
    re.IGNORECASE,
)
_ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
}
_CARDINAL_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS_WORDS = {
    "twenty": 20,
    "thirty": 30,
}
_WORD_NUMBER_PATTERN = (
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    r"eighteenth|nineteenth|twentieth|thirtieth|fortieth|"
    r"twenty(?:[\s-]+(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"one|two|three|four|five|six|seven|eight|nine))?|"
    r"thirty(?:[\s-]+(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"one|two|three|four|five|six|seven|eight|nine))?|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
)
_QUERY_SESSION_NUMERIC_ORDINAL_RES = (
    re.compile(
        rf"\b(?P<order>\d{{1,4}})(?:st|nd|rd|th)\s+(?:locomo\s+)?"
        rf"{_SESSION_ORDINAL_QUERY_NOUN_PATTERN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_SESSION_NOUN_PATTERN}\s+{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        r"(?P<order>\d{1,4})(?:st|nd|rd|th)\b",
        re.IGNORECASE,
    ),
)
_QUERY_LOCOMO_CONVERSATION_NUMERIC_ORDINAL_RES = (
    re.compile(
        r"\b(?P<order>\d{1,4})(?:st|nd|rd|th)\s+locomo\s+(?:conversation|conv)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\blocomo\s+(?:conversation|conv)\s+{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        r"(?P<order>\d{1,4})(?:st|nd|rd|th)\b",
        re.IGNORECASE,
    ),
)
_QUERY_SESSION_WORD_ORDINAL_RES = (
    re.compile(
        rf"\b(?P<order>{_WORD_NUMBER_PATTERN})\s+(?:locomo\s+)?"
        rf"{_SESSION_ORDINAL_QUERY_NOUN_PATTERN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_SESSION_NOUN_PATTERN}\s+{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<order>{_WORD_NUMBER_PATTERN})\b",
        re.IGNORECASE,
    ),
)
_QUERY_LOCOMO_CONVERSATION_WORD_ORDINAL_RES = (
    re.compile(
        rf"\b(?P<order>{_WORD_NUMBER_PATTERN})\s+locomo\s+(?:conversation|conv)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\blocomo\s+(?:conversation|conv)\s+{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<order>{_WORD_NUMBER_PATTERN})\b",
        re.IGNORECASE,
    ),
)
_QUERY_DIALOGUE_ID_RE = re.compile(r"\bD(?P<dialogue>\d{1,4})\b", re.IGNORECASE)
_SESSION_ORDER_METADATA_KEYS = frozenset(
    {
        "dia_id",
        "dialogue_id",
        "dialogue_index",
        "conversation_id",
        "conversation_index",
        "conversation_number",
        "conversation_order",
        "conv_id",
        "conv_index",
        "conv_number",
        "conv_order",
        "locomo_session_index",
        "locomo_session_key",
        "locomo_session_number",
        "session_index",
        "session_key",
        "session_number",
        "session_order",
        "source_dia_id",
        "source_dialogue_id",
        "source_dialogue_index",
        "source_conversation_id",
        "source_conversation_index",
        "source_conversation_number",
        "source_conv_id",
        "source_conv_index",
        "source_conv_number",
        "source_session_index",
        "source_session_key",
    }
)


def temporal_session_recency_boost(item: ContextItem) -> float:
    """Return a bounded boost from LoCoMo-style session/dialogue ordinals."""

    session_order = max(temporal_session_orders(item), default=0)
    if session_order <= 0:
        return 0.0
    return round(min(0.026, 0.006 + min(session_order, 40) * 0.0008), 4)


def temporal_session_earliest_boost(item: ContextItem) -> float:
    """Return a bounded boost favoring earlier LoCoMo-style session/dialogue ordinals."""

    session_order = min(temporal_session_orders(item), default=0)
    if session_order <= 0:
        return 0.0
    return round(max(0.006, 0.026 - min(session_order - 1, 40) * 0.0008), 4)


def temporal_session_orders(item: ContextItem) -> tuple[int, ...]:
    """Return LoCoMo-style session/dialogue ordinals visible on an item."""

    orders: dict[int, None] = {}
    for order in _session_orders_from_values(_session_order_source_values(item)):
        orders.setdefault(order, None)
    for order in _session_orders_from_metadata(item):
        orders.setdefault(order, None)
    return tuple(orders)


def temporal_session_orders_from_query(query: str) -> tuple[int, ...]:
    """Return explicit session/dialogue ordinals requested by a query."""

    return _session_orders_from_query_values((query,))


def _session_order_source_values(item: ContextItem) -> tuple[str, ...]:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    metadata = safe_diagnostic_mapping(diagnostics.get("metadata"))
    values = [
        item.item_id,
        item.text,
        str(diagnostics.get("source_id") or ""),
        str(provenance.get("source_id") or ""),
    ]
    for mapping in (diagnostics, provenance, metadata):
        values.extend(_string_values(mapping))
    for ref in item.source_refs:
        values.extend(
            str(value)
            for value in (
                ref.source_id,
                ref.chunk_id,
                ref.quote_preview,
            )
            if value
        )
    return tuple(value for value in values if value)


def _session_orders_from_values(values: tuple[str, ...]) -> tuple[int, ...]:
    orders: dict[int, None] = {}
    for value in values:
        canonical_value = canonicalize_natural_source_turn_labels(value)
        dialogue_orders = tuple(
            int(match.group("dialogue"))
            for match in _DIALOGUE_TURN_RE.finditer(canonical_value)
        )
        session_matches = tuple(_SESSION_ORDINAL_RE.finditer(canonical_value))
        explicit_session_orders = tuple(
            int(match.group("session"))
            for match in session_matches
            if match.group("noun").casefold() not in {"conv", "conversation"}
        )
        if dialogue_orders or explicit_session_orders:
            allowed_orders = {*dialogue_orders, *explicit_session_orders}
            for order in (*explicit_session_orders, *dialogue_orders):
                orders.setdefault(order, None)
            for match in session_matches:
                order = int(match.group("session"))
                if order in allowed_orders:
                    orders.setdefault(order, None)
            continue
        for match in session_matches:
            orders.setdefault(int(match.group("session")), None)
        for match in _DIALOGUE_TURN_RE.finditer(canonical_value):
            orders.setdefault(int(match.group("dialogue")), None)
    return tuple(orders)


def _session_orders_from_query_values(values: tuple[str, ...]) -> tuple[int, ...]:
    orders: dict[int, None] = {}
    for order in _session_orders_from_values(values):
        orders.setdefault(order, None)
    for value in values:
        for match in _QUERY_DIALOGUE_ID_RE.finditer(value):
            orders.setdefault(int(match.group("dialogue")), None)
        for match in _query_order_matches(_QUERY_SESSION_NUMERIC_ORDINAL_RES, value):
            raw = match.group("order")
            if raw:
                orders.setdefault(int(raw), None)
        for match in _query_order_matches(
            _QUERY_LOCOMO_CONVERSATION_NUMERIC_ORDINAL_RES,
            value,
        ):
            raw = match.group("order")
            if raw:
                orders.setdefault(int(raw), None)
        for match in _query_order_matches(_QUERY_SESSION_WORD_ORDINAL_RES, value):
            raw = match.group("order")
            if raw and (order := _word_number_value(raw)):
                orders.setdefault(order, None)
        for match in _query_order_matches(
            _QUERY_LOCOMO_CONVERSATION_WORD_ORDINAL_RES,
            value,
        ):
            raw = match.group("order")
            if raw and (order := _word_number_value(raw)):
                orders.setdefault(order, None)
    return tuple(orders)


def _query_order_matches(
    patterns: tuple[re.Pattern[str], ...],
    value: str,
) -> tuple[re.Match[str], ...]:
    return tuple(match for pattern in patterns for match in pattern.finditer(value))


def _session_orders_from_metadata(item: ContextItem) -> tuple[int, ...]:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    metadata = safe_diagnostic_mapping(diagnostics.get("metadata"))
    orders: dict[int, None] = {}
    for mapping in (diagnostics, provenance, metadata):
        for key in _SESSION_ORDER_METADATA_KEYS:
            for order in _session_orders_from_metadata_value(mapping.get(key)):
                orders.setdefault(order, None)
    return tuple(orders)


def _session_orders_from_metadata_value(value: object) -> tuple[int, ...]:
    if isinstance(value, bool) or value is None:
        return ()
    if isinstance(value, int):
        return (value,) if value > 0 else ()
    if isinstance(value, float):
        return (int(value),) if value.is_integer() and value > 0 else ()
    text = str(value).strip()
    if not text:
        return ()
    if match := re.fullmatch(r"D(?P<dialogue>\d{1,4})", text, re.IGNORECASE):
        return (int(match.group("dialogue")),)
    if order := _positive_int_value(text):
        return (order,)
    return _session_orders_from_values((text,))


def _string_values(mapping: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    if structured_label := _structured_source_turn_label(mapping):
        values.append(structured_label)
    for value in mapping.values():
        values.extend(_strings_from_diagnostic_value(value))
    return tuple(values)


def _strings_from_diagnostic_value(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        structured_label = _structured_source_turn_label(value)
        nested_values = tuple(
            string_value
            for nested_value in value.values()
            for string_value in _strings_from_diagnostic_value(nested_value)
        )
        if structured_label:
            return (structured_label, *nested_values)
        return nested_values
    if isinstance(value, (list, tuple)):
        return tuple(
            string_value
            for nested_value in value
            for string_value in _strings_from_diagnostic_value(nested_value)
        )
    return ()


def _structured_source_turn_label(value: Mapping[str, object]) -> str:
    dialogue = _positive_int_value(
        value.get("dialogue")
        or value.get("dialogue_id")
        or value.get("dialogue_index")
        or value.get("dia_id")
        or value.get("conversation")
        or value.get("conversation_id")
        or value.get("conversation_index")
        or value.get("conversation_number")
        or value.get("conversation_order")
        or value.get("conv")
        or value.get("conv_id")
        or value.get("conv_index")
        or value.get("conv_number")
        or value.get("conv_order")
        or value.get("source_dialogue")
        or value.get("source_dialogue_id")
        or value.get("source_dialogue_index")
        or value.get("source_dia_id")
        or value.get("source_conversation")
        or value.get("source_conversation_id")
        or value.get("source_conversation_index")
        or value.get("source_conversation_number")
        or value.get("source_conv")
        or value.get("source_conv_id")
        or value.get("source_conv_index")
        or value.get("source_conv_number")
        or value.get("session")
        or value.get("session_id")
        or value.get("session_index")
        or value.get("session_order")
    )
    turn = _positive_int_value(
        value.get("turn")
        or value.get("turn_id")
        or value.get("turn_index")
        or value.get("source_turn")
        or value.get("source_turn_id")
        or value.get("source_turn_index")
    )
    if not dialogue or not turn:
        return ""
    return f"D{dialogue}:{turn}"


def _positive_int_value(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else 0
    text = str(value).strip()
    if match := re.fullmatch(
        rf"(?:session|conversation|conv|dialogue|dialog|dia)[-_ #]*"
        rf"(?:(?:number|no\.?)[-_ #]+)?(?P<number>{SOURCE_TURN_LABEL_NUMBER_PATTERN})",
        text,
        re.IGNORECASE,
    ):
        return source_turn_label_number_value(match.group("number"))
    if match := re.fullmatch(r"D(?P<number>\d{1,4})", text, re.IGNORECASE):
        return int(match.group("number"))
    return source_turn_label_number_value(text)


def _word_number_value(raw: str) -> int:
    normalized = re.sub(r"[\s-]+", " ", raw.casefold()).strip()
    if normalized in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[normalized]
    if normalized in _CARDINAL_WORDS:
        return _CARDINAL_WORDS[normalized]
    if normalized in _TENS_WORDS:
        return _TENS_WORDS[normalized]
    parts = normalized.split()
    if len(parts) != 2:
        return 0
    tens, unit = parts
    return _TENS_WORDS.get(tens, 0) + (
        _ORDINAL_WORDS.get(unit, 0) or _CARDINAL_WORDS.get(unit, 0)
    )
