"""Shared wire contract for authenticated publishable extraction terminals."""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

from infinity_context_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)

PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA: Final = "publishable-full-extraction-terminal-seal.v1"
PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT: Final = 128 * 1024
_MAC_DOMAIN: Final = b"infinity-context/publishable-run/extraction-terminal-seal/v1\0"


def extraction_terminal_seal_hmac(
    terminal_payload: dict[str, object], *, authentication_key: bytes
) -> str:
    """Authenticate the exact producer/consumer terminal payload."""

    if (
        type(terminal_payload) is not dict
        or type(authentication_key) is not bytes
        or len(authentication_key) < 32
    ):
        raise ValueError("publishable extraction terminal seal input is invalid")
    return hmac.new(
        authentication_key,
        _MAC_DOMAIN + canonical_json_bytes(terminal_payload),
        hashlib.sha256,
    ).hexdigest()


__all__ = (
    "PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT",
    "PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA",
    "extraction_terminal_seal_hmac",
)
