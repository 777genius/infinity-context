"""Shared deterministic sensitive-text detection for memory ingress surfaces."""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b[A-Za-z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)"
        r"\s*[:=]\s*['\"]?(?![$<{]|\[redacted[^\]]*\])[^'\"\s]{12,}",
        re.IGNORECASE,
    ),
)
_USERINFO_PATTERN = re.compile(r"(https?://)[^/@\s]+@")


def redact_sensitive_text(value: str, *, marker: str = "[redacted]") -> str:
    redacted = _USERINFO_PATTERN.sub(lambda match: f"{match.group(1)}{marker}@", value)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(marker, redacted)
    return redacted


def contains_sensitive_text(value: str | None) -> bool:
    if not value:
        return False
    if _USERINFO_PATTERN.search(value):
        return True
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
