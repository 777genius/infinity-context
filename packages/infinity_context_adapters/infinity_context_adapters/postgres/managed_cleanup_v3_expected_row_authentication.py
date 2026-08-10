"""Per-row authentication for the cleanup-v4 expected-row SQLite index."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from typing import Final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
    digest,
)

_DOMAIN: Final = b"managed-cleanup-v4/expected-row-index-row/v1\0"


def expected_index_row_tag(
    key: bytes | bytearray,
    *,
    context_sha256: str,
    authority_terminal_sha256: str,
    table: str,
    values: Sequence[object],
) -> str:
    if type(key) not in (bytes, bytearray) or len(key) < 32:
        _fail("authentication_key_invalid")
    if table not in {"corpora", "operations", "source_refs", "fragments"}:
        _fail("table_invalid")
    payload = canonical_bytes(
        {
            "context_sha256": digest(context_sha256),
            "authority_terminal_sha256": digest(authority_terminal_sha256),
            "table": table,
            "values": list(values),
        }
    )
    return hmac.new(key, _DOMAIN + payload, hashlib.sha256).hexdigest()


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_row_{suffix}")


__all__ = ("expected_index_row_tag",)
