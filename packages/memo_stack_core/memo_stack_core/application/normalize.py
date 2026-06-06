"""Pure text normalization helpers for retrieval and idempotency."""

from __future__ import annotations

import re
from hashlib import sha256

_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip().lower())


def content_hash(text: str) -> str:
    return sha256(normalize_text(text).encode("utf-8")).hexdigest()


def scoped_source_hash(*parts: object) -> str:
    raw = "\u241f".join("" if part is None else str(part) for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()


def scoped_idempotency_key(operation: str, *parts: object) -> str:
    return f"idmp:{operation}:{scoped_source_hash(operation, *parts)}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
