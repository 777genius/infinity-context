"""Externally produced scheduler-v2 predicate and outcome evidence contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256


class EvidenceContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatabasePredicateEvidence:
    observed_unix_ms: int
    predicate_sha256: str

    def __post_init__(self) -> None:
        if type(self.observed_unix_ms) is not int or self.observed_unix_ms < 0:
            raise EvidenceContractError("database_time_evidence_invalid")
        _sha(self.predicate_sha256, "database_predicate_invalid")

    @property
    def commitment_sha256(self) -> str:
        return _commitment("scheduler-v2-database-predicate-v1", asdict(self))


@dataclass(frozen=True, slots=True)
class DispatchBoundaryObservation:
    result_sha256: str

    def __post_init__(self) -> None:
        _sha(self.result_sha256, "dispatch_boundary_result_invalid")


@dataclass(frozen=True, slots=True)
class ProviderCompletionAttestation:
    logical_slot_id: str
    generation: int
    dispatch_receipt_sha256: str
    result_sha256: str
    used_tokens: int
    bridge_boot_id: str
    attestation: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for value in (
            self.logical_slot_id,
            self.dispatch_receipt_sha256,
            self.result_sha256,
        ):
            _sha(value, "provider_completion_attestation_invalid")
        if (
            type(self.generation) is not int
            or self.generation < 0
            or type(self.used_tokens) is not int
            or self.used_tokens < 0
            or type(self.bridge_boot_id) is not str
            or not self.bridge_boot_id
            or type(self.attestation) is not bytes
            or not self.attestation
        ):
            raise EvidenceContractError("provider_completion_attestation_invalid")


def _commitment(schema: str, values: dict[str, object]) -> str:
    material = json.dumps(
        {"schema": schema, "values": values}, separators=(",", ":"), sort_keys=True
    )
    return sha256(material.encode()).hexdigest()


def _sha(value: object, code: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise EvidenceContractError(code)


__all__ = (
    "DatabasePredicateEvidence",
    "DispatchBoundaryObservation",
    "EvidenceContractError",
    "ProviderCompletionAttestation",
)
