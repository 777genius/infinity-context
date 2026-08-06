"""Stable command fingerprints and lifecycle receipt validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum

from infinity_context_core.features.memory_facts.ports.idempotency import (
    MemoryFactOperationReceipt,
)

MAX_MEMORY_FACT_IDEMPOTENCY_KEY_LENGTH = 160


def normalize_memory_fact_idempotency_key(
    value: str | None,
    *,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError("idempotency_key cannot be blank")
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key cannot be blank")
    if len(normalized) > MAX_MEMORY_FACT_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError("idempotency_key exceeds 160 characters")
    return normalized


def lifecycle_command_fingerprint(command: object) -> str:
    """Hash command intent while excluding the transport idempotency key."""

    payload = _canonical_value(command, excluded_fields=frozenset({"idempotency_key"}))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_lifecycle_replay(
    receipt: MemoryFactOperationReceipt,
    *,
    operation: str,
    request_fingerprint: str,
) -> None:
    if receipt.operation != operation or receipt.request_fingerprint != request_fingerprint:
        raise ValueError("Idempotency key was already used for a different fact command")


def _canonical_value(
    value: object,
    *,
    excluded_fields: frozenset[str] = frozenset(),
) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
            if field.name not in excluded_fields
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported command fingerprint value: {type(value).__name__}")


__all__ = (
    "MAX_MEMORY_FACT_IDEMPOTENCY_KEY_LENGTH",
    "lifecycle_command_fingerprint",
    "normalize_memory_fact_idempotency_key",
    "validate_lifecycle_replay",
)
