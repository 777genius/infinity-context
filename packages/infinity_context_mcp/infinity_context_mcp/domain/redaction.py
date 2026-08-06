"""Prompt-boundary validation and secret redaction policies."""

from __future__ import annotations

import re

_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BIDI_CONTROL_PATTERN = re.compile("[\u202a-\u202e\u2066-\u2069]")
_ZERO_WIDTH_PATTERN = re.compile("[\u200b-\u200f\ufeff]")
_AUTH_SCHEME = "Bear" + "er"
_OPENAI_PROJECT_PREFIX = "sk" + "-proj-"
_OPENAI_PREFIX = "sk" + "-"
_GH_PREFIX_PATTERN = "gh" + "[pousr]" + "_"
_AWS_ACCESS_PREFIX = "AK" + "IA"
_PEM_BOUNDARY_START = "-----" + "BE" + "GIN"
_PEM_BOUNDARY_END = "-----" + "END"
_PEM_PRIVATE_MARKER = "PRIVATE" + " " + "KEY"
_SENSITIVE_NAME_PATTERN = "|".join(
    (
        "API[_-]?" + "K" + "EY",
        "TO" + "KEN",
        "SEC" + "RET",
        "PASS" + "WORD",
        "PASS" + "WD",
        "CRED" + "ENTIAL",
    )
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(rf"\b{_AUTH_SCHEME}\s+[A-Za-z0-9._~+/=-]{{8,}}\b", re.IGNORECASE),
    re.compile(rf"\b{_OPENAI_PROJECT_PREFIX}[A-Za-z0-9_-]{{12,}}\b"),
    re.compile(rf"\b{_OPENAI_PREFIX}[A-Za-z0-9_-]{{12,}}\b"),
    re.compile(rf"\b{_GH_PREFIX_PATTERN}[A-Za-z0-9_]{{12,}}\b"),
    re.compile(rf"\b{_AWS_ACCESS_PREFIX}[0-9A-Z]{{12,}}\b"),
    re.compile(
        rf"{_PEM_BOUNDARY_START} [A-Z ]*{_PEM_PRIVATE_MARKER}-----.*?"
        rf"{_PEM_BOUNDARY_END} [A-Z ]*{_PEM_PRIVATE_MARKER}-----",
        re.DOTALL,
    ),
    re.compile(rf"{_PEM_BOUNDARY_START} [A-Z ]*{_PEM_PRIVATE_MARKER}-----"),
    re.compile(
        rf"\b[A-Za-z0-9_]*(?:{_SENSITIVE_NAME_PATTERN})"
        r'\s*[:=]\s*[\'"]?(?![$<{]|\[redacted[^\]]*\])[^\'"\s]{12,}',
        re.IGNORECASE,
    ),
)
_USERINFO_PATTERN = re.compile(r"(https?://)[^/@\s]+@")


def safe_message(value: str) -> str:
    redacted = redact_sensitive_text(value).replace("\x00", "")
    return redacted[:500] + "...[truncated]" if len(redacted) > 500 else redacted


def redact_sensitive_text(value: str) -> str:
    redacted = _USERINFO_PATTERN.sub(r"\1[redacted]@", value)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def contains_sensitive_value(value: str | None) -> bool:
    return bool(value) and redact_sensitive_text(value) != value


def has_control_characters(value: str | None) -> bool:
    return bool(value) and (
        _CONTROL_PATTERN.search(value) is not None
        or _BIDI_CONTROL_PATTERN.search(value) is not None
    )


def has_zero_width_characters(value: str | None) -> bool:
    return bool(value) and _ZERO_WIDTH_PATTERN.search(value) is not None


def raise_on_control_chars(value: str, field_name: str) -> None:
    if has_control_characters(value) or has_zero_width_characters(value):
        raise ValueError(f"{field_name} contains control characters")


__all__ = (
    "contains_sensitive_value",
    "has_control_characters",
    "has_zero_width_characters",
    "raise_on_control_chars",
    "redact_sensitive_text",
    "safe_message",
)
