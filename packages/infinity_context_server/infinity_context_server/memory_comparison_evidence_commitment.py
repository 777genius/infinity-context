"""Canonical digesting for deterministic managed-comparison evidence."""

from __future__ import annotations

import hashlib
import json


def evidence_commitment(schema: str, evidence: object) -> str:
    """Return the canonical SHA-256 commitment for schema-tagged evidence."""

    encoded = json.dumps(
        {"schema": schema, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ("evidence_commitment",)
