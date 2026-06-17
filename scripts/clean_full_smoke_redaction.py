"""Redaction helpers for the full-provider smoke report."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_ENV_KEYS = (
    "MEMORY_AGENT_BENCH_OPENAI_API_KEY",
    "MEMORY_MCP_AUTH_TOKEN",
    "MEMORY_SERVICE_TOKEN",
    "MEMORY_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "MEMORY_CLEAN_SMOKE_TOKEN",
    "MEMORY_DATABASE_URL",
    "MEMORY_GRAPHITI_NEO4J_PASSWORD",
)
SENSITIVE_KEY_SUFFIXES = (
    "_TOKEN",
    "_KEY",
    "_SECRET",
    "_PASSWORD",
    "_CREDENTIAL",
    "_DATABASE_URL",
    "_DB_URL",
    "_DSN",
)
SENSITIVE_HEADER_KEYS = {
    "authorization",
    "idempotency-key",
}
SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "auth",
    "auth_token",
    "authorization",
    "credential",
    "credentials",
    "connection_string",
    "database_url",
    "db_url",
    "dsn",
    "idempotency_key",
    "idempotency-key",
    "passwd",
    "password",
    "secret",
    "token",
}
SAFE_REPORT_KEY_NAMES = {
    "mcp_text_fallback_does_not_leak_token",
    "secret_redaction",
}
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\bbench-secret-[A-Za-z0-9_.:-]+\b", re.IGNORECASE),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|credential)\s*[:=]\s*['\"]?"
        r"[A-Za-z0-9_./+=-]{8,}"
    ),
)


def redact_payload(value: Any, *, env: Mapping[str, str] | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, env=env)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted_key = redact_key(key, env=env)
            if isinstance(key, str) and is_sensitive_key_name(key):
                redacted_item: Any = "<redacted>"
            else:
                redacted_item = redact_payload(item, env=env)
            redacted[dedupe_key(redacted, redacted_key)] = redacted_item
        return redacted
    if isinstance(value, list):
        return [redact_payload(item, env=env) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item, env=env) for item in value)
    return value


def redact_text(text: str, *, env: Mapping[str, str] | None = None) -> str:
    redacted = text
    for value in sensitive_values(env):
        redacted = redacted.replace(value, "<redacted>")
    for key in SENSITIVE_ENV_KEYS:
        redacted = redacted.replace(key, "<redacted-env>")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def redact_key(key: Any, *, env: Mapping[str, str] | None = None) -> Any:
    if not isinstance(key, str):
        return key
    if is_sensitive_key_name(key):
        return "<redacted-key>"
    redacted = redact_text(key, env=env)
    return "<redacted-key>" if redacted != key else key


def dedupe_key(mapping: Mapping[Any, Any], key: Any) -> Any:
    if key not in mapping:
        return key
    if not isinstance(key, str):
        return key
    index = 2
    while f"{key}-{index}" in mapping:
        index += 1
    return f"{key}-{index}"


def is_sensitive_key_name(key: str) -> bool:
    normalized = key.strip()
    lowered = normalized.lower()
    if lowered in SAFE_REPORT_KEY_NAMES:
        return False
    if lowered in SENSITIVE_HEADER_KEYS or lowered in SENSITIVE_KEY_NAMES:
        return True
    upper = normalized.upper()
    if upper in SENSITIVE_ENV_KEYS or upper.endswith(SENSITIVE_KEY_SUFFIXES):
        return True
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    if not compact:
        return False
    if compact.endswith(("count", "countzero", "rate", "ratemin080", "ratemin090")):
        return False
    sensitive_compact = {
        re.sub(r"[^a-z0-9]+", "", item) for item in (*SENSITIVE_HEADER_KEYS, *SENSITIVE_KEY_NAMES)
    }
    if compact in sensitive_compact:
        return True
    if compact.endswith("apikey") or compact.endswith("privatekey"):
        return True
    if compact.endswith("token") and not compact.endswith("budget"):
        return True
    return any(
        marker in compact
        for marker in (
            "authorization",
            "credential",
            "connectionstring",
            "databaseurl",
            "password",
            "passwd",
            "secret",
        )
    )


def sensitive_values(env: Mapping[str, str] | None = None) -> list[str]:
    envs = [os.environ]
    if env is not None:
        envs.append(env)
    values = set()
    for item in envs:
        values.update(
            str(item.get(key) or "").strip()
            for key in SENSITIVE_ENV_KEYS
            if str(item.get(key) or "").strip()
        )
        values.update(
            str(value).strip()
            for key, value in item.items()
            if isinstance(key, str)
            and is_sensitive_key_name(key)
            and len(str(value).strip()) >= 8
        )
    return sorted(values, key=len, reverse=True)


def has_unredacted_secret_marker(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_TEXT_PATTERNS)
