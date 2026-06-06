"""Idempotency value objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IdempotencyRecord:
    space_id: str
    key: str
    fingerprint: str
    result_type: str
    result_id: str
