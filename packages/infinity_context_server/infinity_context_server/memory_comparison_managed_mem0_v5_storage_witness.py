"""Process-local provenance for authenticated managed Mem0 v5 storage evidence."""

from __future__ import annotations

import re
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_INVALID = "managed Mem0 v5 storage witness is invalid"
_AUTHORITY_INVALID = "managed Mem0 v5 storage witness authority is invalid"


@final
@dataclass(frozen=True, slots=True, weakref_slot=True)
class ManagedMem0V5AuthenticatedStorageWitness:
    """Immutable observation properties issued only after HMAC verification."""

    operation_id_sha256: str
    unit_identity_sha256: str
    storage_commitment_sha256: str
    created_record_ids: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        payload = self.commitment_payload()
        if (
            not is_sha256(self.operation_id_sha256)
            or not is_sha256(self.unit_identity_sha256)
            or not is_sha256(self.storage_commitment_sha256)
            or type(self.created_record_ids) is not tuple
            or any(
                type(record_id) is not str or _SAFE_ID.fullmatch(record_id) is None
                for record_id in self.created_record_ids
            )
            or len(set(self.created_record_ids)) != len(self.created_record_ids)
            or type(self.source_pairs) is not tuple
            or not self.source_pairs
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or _SAFE_ID.fullmatch(pair[0]) is None
                or not is_sha256(pair[1])
                for pair in self.source_pairs
            )
            or len(set(self.source_pairs)) != len(self.source_pairs)
            or self.evidence_commitment_sha256 != canonical_sha256(payload)
        ):
            raise ManagedRunError(_INVALID)

    def commitment_payload(self) -> dict[str, object]:
        return {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "storage_commitment_sha256": self.storage_commitment_sha256,
            "created_record_ids": list(self.created_record_ids),
            "source_pairs": [
                {"source_id": source_id, "source_sha256": source_sha256}
                for source_id, source_sha256 in self.source_pairs
            ],
        }

    def public_payload(self) -> dict[str, object]:
        return {
            **self.commitment_payload(),
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(evidence_commitment_sha256={self.evidence_commitment_sha256!r})"
        )


class ManagedMem0V5StorageWitnessIssuerPort(Protocol):
    def issue_authenticated_storage(
        self,
        *,
        operation_id_sha256: str,
        unit_identity_sha256: str,
        storage_commitment_sha256: str,
        created_record_ids: tuple[str, ...],
        source_pairs: tuple[tuple[str, str], ...],
    ) -> ManagedMem0V5AuthenticatedStorageWitness: ...


class ManagedMem0V5StorageWitnessVerifierPort(Protocol):
    def authenticate_storage(self, witness: object) -> ManagedMem0V5AuthenticatedStorageWitness: ...


class _WitnessState:
    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._entries: dict[
            int,
            tuple[
                weakref.ReferenceType[ManagedMem0V5AuthenticatedStorageWitness],
                tuple[object, ...],
            ],
        ] = {}
        self._lock = threading.Lock()

    def register(
        self, witness: ManagedMem0V5AuthenticatedStorageWitness
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        identity = id(witness)

        def remove(
            reference: weakref.ReferenceType[ManagedMem0V5AuthenticatedStorageWitness],
        ) -> None:
            with self._lock:
                current = self._entries.get(identity)
                if current is not None and current[0] is reference:
                    self._entries.pop(identity, None)

        reference = weakref.ref(witness, remove)
        with self._lock:
            if identity in self._entries:
                raise ManagedRunError(_INVALID)
            self._entries[identity] = (reference, _fingerprint(witness))
        return witness

    def authenticate(self, value: object) -> ManagedMem0V5AuthenticatedStorageWitness:
        if type(value) is not ManagedMem0V5AuthenticatedStorageWitness:
            raise ManagedRunError(_INVALID)
        with self._lock:
            registered = self._entries.get(id(value))
            if (
                registered is None
                or registered[0]() is not value
                or registered[1] != _fingerprint(value)
            ):
                raise ManagedRunError(_INVALID)
        try:
            value.__post_init__()
        except Exception:
            raise ManagedRunError(_INVALID) from None
        return value


@final
class _ManagedMem0V5StorageWitnessIssuer:
    __slots__ = ("_state",)

    def __init__(self, state: _WitnessState) -> None:
        self._state = state

    def issue_authenticated_storage(
        self,
        *,
        operation_id_sha256: str,
        unit_identity_sha256: str,
        storage_commitment_sha256: str,
        created_record_ids: tuple[str, ...],
        source_pairs: tuple[tuple[str, str], ...],
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        base = {
            "operation_id_sha256": operation_id_sha256,
            "unit_identity_sha256": unit_identity_sha256,
            "storage_commitment_sha256": storage_commitment_sha256,
            "created_record_ids": list(created_record_ids),
            "source_pairs": [
                {"source_id": source_id, "source_sha256": source_sha256}
                for source_id, source_sha256 in source_pairs
            ],
        }
        witness = ManagedMem0V5AuthenticatedStorageWitness(
            operation_id_sha256=operation_id_sha256,
            unit_identity_sha256=unit_identity_sha256,
            storage_commitment_sha256=storage_commitment_sha256,
            created_record_ids=created_record_ids,
            source_pairs=source_pairs,
            evidence_commitment_sha256=canonical_sha256(base),
        )
        return self._state.register(witness)


@final
class _ManagedMem0V5StorageWitnessVerifier:
    __slots__ = ("_state",)

    def __init__(self, state: _WitnessState) -> None:
        self._state = state

    def authenticate_storage(self, witness: object) -> ManagedMem0V5AuthenticatedStorageWitness:
        return self._state.authenticate(witness)


def create_managed_mem0_v5_storage_witness_authority() -> tuple[
    ManagedMem0V5StorageWitnessIssuerPort,
    ManagedMem0V5StorageWitnessVerifierPort,
]:
    state = _WitnessState()
    return (
        _ManagedMem0V5StorageWitnessIssuer(state),
        _ManagedMem0V5StorageWitnessVerifier(state),
    )


def require_managed_mem0_v5_storage_witness_issuer(
    value: object,
) -> ManagedMem0V5StorageWitnessIssuerPort:
    if type(value) is not _ManagedMem0V5StorageWitnessIssuer:
        raise ManagedRunError(_AUTHORITY_INVALID)
    return value


def require_managed_mem0_v5_storage_witness_verifier(
    value: object,
) -> ManagedMem0V5StorageWitnessVerifierPort:
    if type(value) is not _ManagedMem0V5StorageWitnessVerifier:
        raise ManagedRunError(_AUTHORITY_INVALID)
    return value


def _fingerprint(
    value: ManagedMem0V5AuthenticatedStorageWitness,
) -> tuple[object, ...]:
    return (
        value.operation_id_sha256,
        value.unit_identity_sha256,
        value.storage_commitment_sha256,
        value.created_record_ids,
        value.source_pairs,
        value.evidence_commitment_sha256,
    )


__all__ = [
    "ManagedMem0V5AuthenticatedStorageWitness",
    "ManagedMem0V5StorageWitnessIssuerPort",
    "ManagedMem0V5StorageWitnessVerifierPort",
    "create_managed_mem0_v5_storage_witness_authority",
    "require_managed_mem0_v5_storage_witness_issuer",
    "require_managed_mem0_v5_storage_witness_verifier",
]
