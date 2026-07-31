"""Canonical JSON and provider-text validation for gold-blind contracts."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import math
import re
import unicodedata
from types import MappingProxyType

_MAX_PROVIDER_TEXT_CHARS = 16_384
_MAX_BASE64_TOKEN_CHARS = 8_192
_MAX_GOLD_JSON_BYTES = 1_048_576
_MAX_TERM_COUNT = 128
_MAX_TERM_CHARS = 4_096
_PROMPT_LEAK_MARKERS = (
    "answerpreview",
    "evaluatorgroundtruth",
    "expectedanswer",
    "expectedterms",
    "goldanswer",
    "groundtruth",
    "referenceanswer",
)
_BASE64_TOKEN = re.compile(r"(?<![A-Za-z0-9_+/-])[A-Za-z0-9_+/-]{8,}={0,2}(?![A-Za-z0-9_+/-])")
_DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


class GoldBlindContractError(ValueError):
    """Raised when a payload cannot prove that gold remains isolated."""


def canonical_gold_json(value: object) -> bytes:
    """Validate exact JSON gold and return a stable bounded representation."""

    _validate_json_value(value, depth=0)
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise GoldBlindContractError("Evaluator gold is not canonical JSON") from None
    if not rendered or len(rendered) > _MAX_GOLD_JSON_BYTES:
        raise GoldBlindContractError("Evaluator gold JSON size is invalid")
    return rendered


def validate_string_terms(values: object, *, field_name: str) -> tuple[str, ...]:
    """Copy bounded exact judge-only tuples without hostile iteration."""

    if type(values) is not tuple:
        raise GoldBlindContractError(f"{field_name} must be an exact tuple")
    if len(values) > _MAX_TERM_COUNT:
        raise GoldBlindContractError(f"{field_name} exceeds the term count limit")
    for term in values:
        _validate_exact_string_length(
            term,
            field_name=field_name,
            maximum=_MAX_TERM_CHARS,
            allow_empty=False,
        )
    return tuple(values)


def validate_provider_text(value: object, *, field_name: str) -> str:
    """Validate one bounded provider-visible string without altering its payload."""

    _validate_provider_text(value, field_name=field_name)
    return value


def contains_evaluator_secret(value: object, secrets_to_hide: object) -> bool:
    """Detect raw, default-ignorable-obfuscated, or reversible base64 gold."""

    _validate_exact_string_length(
        value,
        field_name="Public provider field",
        maximum=_MAX_PROVIDER_TEXT_CHARS,
        allow_empty=False,
    )
    if type(secrets_to_hide) is not tuple:
        raise GoldBlindContractError("Secret fragments must be an exact tuple")
    for secret in secrets_to_hide:
        _validate_exact_string_length(
            secret,
            field_name="Secret fragment",
            maximum=_MAX_TERM_CHARS,
            allow_empty=False,
        )
    variants = _provider_text_variants(value)
    return any(
        normalized_secret in _normalize_text(variant)
        for secret in secrets_to_hide
        if (normalized_secret := _normalize_text(secret))
        for variant in variants
    )


def parse_canonical_gold_json(payload: object) -> object:
    if type(payload) is not bytes:
        raise GoldBlindContractError("Judge channel gold must use exact bytes")
    if not payload or len(payload) > _MAX_GOLD_JSON_BYTES:
        raise GoldBlindContractError("Judge channel gold JSON size is invalid")
    try:
        text = payload.decode("utf-8")
        parsed = json.loads(text, object_pairs_hook=_unique_json_object)
    except GoldBlindContractError:
        raise
    except Exception:
        raise GoldBlindContractError("Judge channel gold JSON is invalid") from None
    _validate_json_value(parsed, depth=0)
    if not hmac.compare_digest(canonical_gold_json(parsed), payload):
        raise GoldBlindContractError("Judge channel gold JSON is not exact canonical JSON")
    return parsed


def freeze_json_value(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: freeze_json_value(nested) for key, nested in value.items()})
    if type(value) is list:
        return tuple(freeze_json_value(nested) for nested in value)
    return value


def secret_fragments(
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> tuple[str, ...]:
    values = (*_json_scalar_strings(ground_truth), *expected_terms, *forbidden_terms)
    fragments: set[str] = set()
    for value in values:
        _validate_exact_string_length(
            value,
            field_name="Secret fragment",
            maximum=_MAX_TERM_CHARS,
            allow_empty=False,
        )
        normalized = _normalize_text(value)
        if normalized:
            fragments.add(normalized)
    return tuple(sorted(fragments, key=lambda item: (-len(item), item)))


def validate_nonempty_exact_string(value: object, *, field_name: str) -> None:
    _validate_exact_string_length(
        value,
        field_name=field_name,
        maximum=_MAX_PROVIDER_TEXT_CHARS,
        allow_empty=False,
    )


def validate_exact_string_length(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool,
) -> None:
    _validate_exact_string_length(
        value,
        field_name=field_name,
        maximum=maximum,
        allow_empty=allow_empty,
    )


def is_public_scalar(value: object) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise GoldBlindContractError("Judge channel gold JSON contains duplicate keys")
        result[key] = value
    return result


def _json_scalar_strings(value: object) -> tuple[str, ...]:
    if type(value) is str:
        if not value:
            return ()
        return (value,)
    if value is None or type(value) is bool:
        return ()
    if type(value) in (int, float):
        return (json.dumps(value, allow_nan=False),)
    if type(value) is list:
        return tuple(item for nested in value for item in _json_scalar_strings(nested))
    if type(value) is dict:
        return tuple(item for nested in value.values() for item in _json_scalar_strings(nested))
    return ()


def _validate_provider_text(value: object, *, field_name: str) -> None:
    _validate_exact_string_length(
        value,
        field_name=field_name,
        maximum=_MAX_PROVIDER_TEXT_CHARS,
        allow_empty=False,
    )
    variants = _provider_text_variants(value)
    if any(
        marker in _normalize_key(variant) for variant in variants for marker in _PROMPT_LEAK_MARKERS
    ):
        raise GoldBlindContractError(f"{field_name} contains an evaluator-label prompt injection")
    if len(variants) > 1:
        raise GoldBlindContractError(f"{field_name} contains reversible base64-like content")


def _provider_text_variants(value: str) -> tuple[str, ...]:
    stripped = _strip_default_ignorables(value)
    decoded: list[str] = []
    for match in _BASE64_TOKEN.finditer(stripped):
        token = match.group(0)
        if len(token) > _MAX_BASE64_TOKEN_CHARS:
            raise GoldBlindContractError("Provider text contains an oversized base64-like token")
        padded = token + ("=" * (-len(token) % 4))
        try:
            raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
            if len(raw) > _MAX_BASE64_TOKEN_CHARS:
                raise GoldBlindContractError(
                    "Provider text contains an oversized base64-like token"
                )
            candidate = raw.decode("utf-8")
        except GoldBlindContractError:
            raise
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        decoded.append(candidate)
    return (stripped, *decoded)


def _validate_exact_string_length(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool,
) -> None:
    if type(value) is not str:
        raise GoldBlindContractError(f"{field_name} must be an exact string")
    if len(value) > maximum:
        raise GoldBlindContractError(f"{field_name} exceeds the length limit")
    if not allow_empty and not _normalize_text(value):
        raise GoldBlindContractError(f"{field_name} must be non-empty")


def _validate_json_value(value: object, *, depth: int) -> None:
    if depth > 12:
        raise GoldBlindContractError("Evaluator gold exceeds the maximum nesting depth")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise GoldBlindContractError("Evaluator gold contains a non-finite number")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise GoldBlindContractError("Evaluator gold contains a non-string object key")
            _validate_json_value(item, depth=depth + 1)
        return
    raise GoldBlindContractError("Evaluator gold contains a non-JSON value")


def _normalize_text(value: str) -> str:
    scan_value = _strip_default_ignorables(value)
    normalized = unicodedata.normalize("NFKC", scan_value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_key(value: str) -> str:
    scan_value = _strip_default_ignorables(value)
    normalized = unicodedata.normalize("NFKC", scan_value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _strip_default_ignorables(value: str) -> str:
    return "".join(character for character in value if not _is_default_ignorable(ord(character)))


def _is_default_ignorable(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in _DEFAULT_IGNORABLE_RANGES)
