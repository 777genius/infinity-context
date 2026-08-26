"""Strict raw-byte JSON seam for canonical Retrieval contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

_UNICODE_SCALAR_ERROR = "canonical JSON contains an unpaired Unicode surrogate"


def decode_context_retrieval_json(raw: bytes) -> Mapping[str, object]:
    """Decode one UTF-8 JSON object while preserving duplicate-key evidence."""

    if not isinstance(raw, bytes):
        raise ValueError("canonical JSON input must be raw bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("canonical JSON input must be valid UTF-8") from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: _reject_constant(token),
        )
    except json.JSONDecodeError as error:
        raise ValueError("canonical JSON input is malformed") from error
    value = _normalize_context_retrieval_unicode(decoded)
    if not isinstance(value, Mapping):
        raise ValueError("canonical JSON input must contain one object")
    return value


def decode_retrieve_context_request(raw: bytes):
    from ._context_building_retrieval import RetrieveContextRequestDto

    return RetrieveContextRequestDto.from_dict(decode_context_retrieval_json(raw))


def decode_retrieve_context_response(raw: bytes):
    from ._context_building_retrieval import RetrieveContextResponseDto

    return RetrieveContextResponseDto.from_dict(decode_context_retrieval_json(raw))


def _normalize_context_retrieval_unicode(value: object) -> object:
    """Return JSON data containing Unicode scalars, without NFC/NFD folding."""

    if isinstance(value, str):
        return _decode_surrogate_pairs(value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            scalar_key = _decode_surrogate_pairs(key)
            if scalar_key in normalized:
                raise ValueError(f"canonical JSON contains duplicate key: {scalar_key}")
            normalized[scalar_key] = _normalize_context_retrieval_unicode(nested)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_normalize_context_retrieval_unicode(item) for item in value]
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        scalar_key = _decode_surrogate_pairs(key)
        if scalar_key in result:
            raise ValueError(f"canonical JSON contains duplicate key: {scalar_key}")
        result[scalar_key] = value
    return result


def _decode_surrogate_pairs(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(value):
                raise ValueError(_UNICODE_SCALAR_ERROR)
            low = ord(value[index + 1])
            if not 0xDC00 <= low <= 0xDFFF:
                raise ValueError(_UNICODE_SCALAR_ERROR)
            result.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00))
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise ValueError(_UNICODE_SCALAR_ERROR)
        result.append(value[index])
        index += 1
    return "".join(result)


def _reject_constant(token: str):
    raise ValueError(f"canonical JSON contains unsupported number: {token}")


__all__ = (
    "decode_context_retrieval_json",
    "decode_retrieve_context_request",
    "decode_retrieve_context_response",
)
