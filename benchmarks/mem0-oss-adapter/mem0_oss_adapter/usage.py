"""Sanitized run-scoped usage evidence and deterministic witness helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

FIXED_EXTRACTION_MODEL = "gpt-5.6-sol"
MAX_USAGE_OPERATIONS = 10_000
MAX_USAGE_BYTES = 1_048_576

_UTC_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

_Mode = Literal["raw_passthrough", "subscription_llm"]


class UsageEvidenceError(RuntimeError):
    """The adapter cannot produce bounded, internally consistent usage evidence."""


@dataclass(frozen=True, slots=True)
class RunUsageAggregate:
    mode: _Mode
    operation_count: int
    extraction_calls: int
    request_bytes: int
    response_bytes: int
    model: str
    first_operation_at: str
    last_operation_at: str

    def __post_init__(self) -> None:
        counts = (
            self.operation_count,
            self.extraction_calls,
            self.request_bytes,
            self.response_bytes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
            raise UsageEvidenceError("usage evidence counters are invalid")
        if not 1 <= self.operation_count <= MAX_USAGE_OPERATIONS:
            raise UsageEvidenceError("usage operation count is outside the verified bound")
        if not 0 <= self.request_bytes <= MAX_USAGE_BYTES:
            raise UsageEvidenceError("usage request bytes are outside the verified bound")
        if not 0 <= self.response_bytes <= MAX_USAGE_BYTES:
            raise UsageEvidenceError("usage response bytes are outside the verified bound")
        if self.model != FIXED_EXTRACTION_MODEL:
            raise UsageEvidenceError("usage evidence model differs from the fixed model")
        first = _parse_timestamp(self.first_operation_at)
        last = _parse_timestamp(self.last_operation_at)
        if first > last:
            raise UsageEvidenceError("usage evidence timestamp interval is invalid")
        if self.mode == "raw_passthrough":
            if self.extraction_calls != 0 or self.request_bytes != 0 or self.response_bytes != 0:
                raise UsageEvidenceError("raw passthrough usage must prove zero extraction")
        elif self.mode == "subscription_llm":
            if self.operation_count != 1 or self.extraction_calls != 1 or self.request_bytes < 1:
                raise UsageEvidenceError(
                    "subscription usage must prove one isolated extraction call"
                )
        else:
            raise UsageEvidenceError("usage evidence mode is invalid")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "mode": self.mode,
            "operation_count": self.operation_count,
            "extraction_calls": self.extraction_calls,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "model": self.model,
            "first_operation_at": self.first_operation_at,
            "last_operation_at": self.last_operation_at,
        }


def usage_fingerprint_sha256(usage: RunUsageAggregate, *, attested_at: str) -> str:
    attested = _parse_timestamp(attested_at)
    if _parse_timestamp(usage.last_operation_at) > attested:
        raise UsageEvidenceError("usage operation timestamp exceeds attestation time")
    encoded = json.dumps(
        {"attested_at": attested_at, "usage": usage.as_dict()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def usage_witness_signature(
    *,
    token: str,
    run_id_sha256: str,
    probe_nonce_sha256: str,
    target_identity_sha256: str,
    attested_at: str,
    usage_fingerprint_sha256: str,
) -> str:
    message = "\n".join(
        (
            "mem0-benchmark-usage-witness.v1",
            run_id_sha256,
            probe_nonce_sha256,
            target_identity_sha256,
            attested_at,
            usage_fingerprint_sha256,
        )
    ).encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def usage_attested_at() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or _UTC_MILLISECONDS.fullmatch(value) is None:
        raise UsageEvidenceError("usage evidence timestamp is invalid")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise UsageEvidenceError("usage evidence timestamp is invalid") from exc
