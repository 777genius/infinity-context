"""Authenticated clean-state and sealed corpus evidence for managed Mem0 v5."""

from __future__ import annotations

import datetime as dt
import hmac
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    ManagedMem0V5StorageWitnessVerifierPort,
    require_managed_mem0_v5_storage_witness_verifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import Mem0OssRunSeal


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5CleanCorpusScope:
    corpus_identity_sha256: str
    scope_identity_sha256: str
    source_scope_count: int
    residual_record_count: int
    residual_root_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.corpus_identity_sha256)
            or not is_sha256(self.scope_identity_sha256)
            or type(self.source_scope_count) is not int
            or not 1 <= self.source_scope_count <= 10_000
            or self.residual_record_count != 0
            or self.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        ):
            raise ManagedRunError("managed Mem0 v5 clean corpus scope is invalid")

    def payload(self) -> dict[str, object]:
        return {
            "corpus_identity_sha256": self.corpus_identity_sha256,
            "scope_identity_sha256": self.scope_identity_sha256,
            "source_scope_count": self.source_scope_count,
            "residual_record_count": self.residual_record_count,
            "residual_root_sha256": self.residual_root_sha256,
        }


@final
@dataclass(frozen=True, slots=True, weakref_slot=True)
class ManagedMem0V5AuthenticatedCleanStateWitness:
    admission_commitment_sha256: str
    run_id_sha256: str
    authority_commitment_sha256: str
    scopes: tuple[ManagedMem0V5CleanCorpusScope, ...]
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or not is_sha256(self.run_id_sha256)
            or not is_sha256(self.authority_commitment_sha256)
            or type(self.scopes) is not tuple
            or not self.scopes
            or any(type(item) is not ManagedMem0V5CleanCorpusScope for item in self.scopes)
            or len({item.corpus_identity_sha256 for item in self.scopes}) != len(self.scopes)
            or self.evidence_commitment_sha256 != canonical_sha256(self.commitment_payload())
        ):
            raise ManagedRunError("managed Mem0 v5 clean-state witness is invalid")
        for item in self.scopes:
            item.__post_init__()

    def commitment_payload(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "run_id_sha256": self.run_id_sha256,
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "scopes": [item.payload() for item in self.scopes],
        }


class ManagedMem0V5CleanStateWitnessIssuerPort(Protocol):
    def issue_authenticated_clean_state(
        self,
        *,
        admission_commitment_sha256: str,
        run_id_sha256: str,
        authority_commitment_sha256: str,
        scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness: ...


class ManagedMem0V5CleanStateWitnessVerifierPort(Protocol):
    def authenticate_clean_state(
        self, witness: object
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness: ...


class ManagedMem0V5CleanStateSnapshotPort(Protocol):
    def prove_empty_scopes(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_run_id_sha256: str,
        expected_authority_commitment_sha256: str,
        expected_scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness: ...


class ManagedMem0V5DurableCleanStatePort(Protocol):
    def save_original(self, witness: ManagedMem0V5AuthenticatedCleanStateWitness) -> None: ...

    def load_original(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_run_id_sha256: str,
        expected_authority_commitment_sha256: str,
        expected_evidence_commitment_sha256: str,
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness: ...


class _CleanWitnessState:
    def __init__(self, hmac_key: bytes) -> None:
        self.entries: dict[int, tuple[weakref.ReferenceType[object], bytes]] = {}
        self.hmac_key = hmac_key
        self.lock = threading.Lock()

    def register(
        self, witness: ManagedMem0V5AuthenticatedCleanStateWitness
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        identity = id(witness)
        reference = weakref.ref(witness, lambda item: self._remove(identity, item))
        with self.lock:
            self.entries[identity] = (reference, self._signature(witness))
        return witness

    def authenticate(self, value: object) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        if type(value) is not ManagedMem0V5AuthenticatedCleanStateWitness:
            raise ManagedRunError("managed Mem0 v5 clean-state witness is unauthenticated")
        try:
            signature = self._signature(value)
        except Exception:
            raise ManagedRunError(
                "managed Mem0 v5 clean-state witness is unauthenticated"
            ) from None
        with self.lock:
            registered = self.entries.get(id(value))
            if (
                registered is None
                or registered[0]() is not value
                or not hmac.compare_digest(registered[1], signature)
            ):
                raise ManagedRunError("managed Mem0 v5 clean-state witness is unauthenticated")
        value.__post_init__()
        return value

    def _remove(self, identity: int, reference: weakref.ReferenceType[object]) -> None:
        with self.lock:
            current = self.entries.get(identity)
            if current is not None and current[0] is reference:
                self.entries.pop(identity, None)

    def _signature(self, value: ManagedMem0V5AuthenticatedCleanStateWitness) -> bytes:
        return hmac.digest(
            self.hmac_key,
            canonical_sha256(
                {
                    **value.commitment_payload(),
                    "evidence_commitment_sha256": value.evidence_commitment_sha256,
                }
            ).encode(),
            "sha256",
        )


@final
class _CleanWitnessIssuer:
    def __init__(self, state: _CleanWitnessState) -> None:
        self._state = state

    def issue_authenticated_clean_state(
        self,
        *,
        admission_commitment_sha256: str,
        run_id_sha256: str,
        authority_commitment_sha256: str,
        scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        payload = {
            "admission_commitment_sha256": admission_commitment_sha256,
            "run_id_sha256": run_id_sha256,
            "authority_commitment_sha256": authority_commitment_sha256,
            "scopes": [item.payload() for item in scopes],
        }
        witness = ManagedMem0V5AuthenticatedCleanStateWitness(
            admission_commitment_sha256,
            run_id_sha256,
            authority_commitment_sha256,
            scopes,
            evidence_commitment_sha256=canonical_sha256(payload),
        )
        return self._state.register(witness)


@final
class _CleanWitnessVerifier:
    def __init__(self, state: _CleanWitnessState) -> None:
        self._state = state

    def authenticate_clean_state(
        self, witness: object
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        return self._state.authenticate(witness)


def create_managed_mem0_v5_clean_state_witness_authority(
    *, hmac_key: bytes | None = None
) -> tuple[
    ManagedMem0V5CleanStateWitnessIssuerPort,
    ManagedMem0V5CleanStateWitnessVerifierPort,
]:
    if hmac_key is not None and (type(hmac_key) is not bytes or len(hmac_key) < 32):
        raise ManagedRunError("managed Mem0 v5 clean-state HMAC key is invalid")
    state = _CleanWitnessState(hmac_key if hmac_key is not None else secrets.token_bytes(32))
    return _CleanWitnessIssuer(state), _CleanWitnessVerifier(state)


def managed_mem0_v5_clean_evidence_commitment_sha256(
    *,
    admission_commitment_sha256: str,
    run_id_sha256: str,
    authority_commitment_sha256: str,
    scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
) -> str:
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission_commitment_sha256,
            "run_id_sha256": run_id_sha256,
            "authority_commitment_sha256": authority_commitment_sha256,
            "scopes": [item.payload() for item in scopes],
        }
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5CorpusUnitEvidence:
    unit_identity_sha256: str
    source_id: str
    source_sha256: str
    observation_date: str
    created_record_ids: tuple[str, ...]
    storage_evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        try:
            parsed = dt.date.fromisoformat(self.observation_date)
        except (TypeError, ValueError):
            raise ManagedRunError("managed Mem0 v5 corpus unit evidence is invalid") from None
        if (
            not is_sha256(self.unit_identity_sha256)
            or type(self.source_id) is not str
            or not self.source_id
            or not is_sha256(self.source_sha256)
            or parsed.isoformat() != self.observation_date
            or type(self.created_record_ids) is not tuple
            or len(set(self.created_record_ids)) != len(self.created_record_ids)
            or not is_sha256(self.storage_evidence_commitment_sha256)
        ):
            raise ManagedRunError("managed Mem0 v5 corpus unit evidence is invalid")

    def payload(self) -> dict[str, object]:
        return {
            "unit_identity_sha256": self.unit_identity_sha256,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "observation_date": self.observation_date,
            "created_record_ids": list(self.created_record_ids),
            "storage_evidence_commitment_sha256": self.storage_evidence_commitment_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5CorpusIngestEvidence:
    run_id: str
    target_identity_sha256: str
    corpus_id: str
    authority_commitment_sha256: str
    seal_commitment_sha256: str
    units: tuple[ManagedMem0V5CorpusUnitEvidence, ...]
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or not is_sha256(self.target_identity_sha256)
            or type(self.corpus_id) is not str
            or not self.corpus_id
            or not is_sha256(self.authority_commitment_sha256)
            or not is_sha256(self.seal_commitment_sha256)
            or type(self.units) is not tuple
            or not self.units
            or any(type(item) is not ManagedMem0V5CorpusUnitEvidence for item in self.units)
            or self.evidence_commitment_sha256 != canonical_sha256(self.commitment_payload())
        ):
            raise ManagedRunError("managed Mem0 v5 corpus ingest evidence is invalid")

    def commitment_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "target_identity_sha256": self.target_identity_sha256,
            "corpus_id": self.corpus_id,
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "units": [item.payload() for item in self.units],
        }


@final
class ManagedMem0V5CorpusEvidenceProjector:
    """Authenticate the full ordered storage inventory before corpus projection."""

    __slots__ = ("_admission", "_authority", "_storage_verifier")

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission_commitment_sha256: str,
        storage_verifier: ManagedMem0V5StorageWitnessVerifierPort,
    ) -> None:
        if type(authority) is not ManagedMem0V5ManifestAuthority or not is_sha256(
            admission_commitment_sha256
        ):
            raise ManagedRunError("managed Mem0 v5 corpus projector authority is invalid")
        authority.__post_init__()
        self._authority = authority
        self._admission = admission_commitment_sha256
        self._storage_verifier = require_managed_mem0_v5_storage_witness_verifier(storage_verifier)

    def project(
        self,
        *,
        run_id: str,
        corpus_id: str,
        seal: Mem0OssRunSeal,
        expected_seal_commitment_sha256: str,
        observations: tuple[ManagedMem0V5AuthenticatedStorageWitness, ...],
    ) -> ManagedMem0V5CorpusIngestEvidence:
        self._validate_gate(
            run_id=run_id,
            corpus_id=corpus_id,
            seal=seal,
            expected_seal_commitment_sha256=expected_seal_commitment_sha256,
            observations=observations,
        )
        projected = []
        for index, (source, raw) in enumerate(
            zip(self._authority.units, observations, strict=True)
        ):
            try:
                storage = self._storage_verifier.authenticate_storage(raw)
            except Exception:
                raise ManagedRunError(
                    "managed Mem0 v5 corpus storage witness is unauthenticated"
                ) from None
            expected_operation = canonical_sha256(
                {
                    "admission_commitment_sha256": self._admission,
                    "unit_index": index,
                    "unit_identity_sha256": source.unit_identity_sha256,
                }
            )
            if (
                storage is not raw
                or storage.operation_id_sha256 != expected_operation
                or storage.unit_identity_sha256 != source.unit_identity_sha256
                or storage.source_pairs != ((source.source_id, source.source_sha256),)
            ):
                raise ManagedRunError("managed Mem0 v5 corpus storage order differs")
            created_record_ids = storage.created_record_ids
            storage_evidence_commitment_sha256 = storage.evidence_commitment_sha256
            try:
                self._storage_verifier.authenticate_storage(storage)
            except Exception:
                raise ManagedRunError(
                    "managed Mem0 v5 corpus storage witness is unauthenticated"
                ) from None
            if source.corpus_id == corpus_id:
                projected.append(
                    ManagedMem0V5CorpusUnitEvidence(
                        source.unit_identity_sha256,
                        source.source_id,
                        source.source_sha256,
                        source.observation_date,
                        created_record_ids,
                        storage_evidence_commitment_sha256,
                    )
                )
        if not projected:
            raise ManagedRunError("managed Mem0 v5 corpus evidence corpus differs")
        return _corpus_evidence(
            run_id=run_id,
            corpus_id=corpus_id,
            authority_commitment_sha256=self._authority.authority_commitment_sha256,
            seal=seal,
            units=tuple(projected),
        )

    def _validate_gate(
        self,
        *,
        run_id: object,
        corpus_id: object,
        seal: object,
        expected_seal_commitment_sha256: object,
        observations: object,
    ) -> None:
        if type(seal) is Mem0OssRunSeal:
            try:
                seal.__post_init__()
            except Exception:
                raise ManagedRunError("managed Mem0 v5 corpus seal differs") from None
        if (
            type(run_id) is not str
            or not run_id
            or type(corpus_id) is not str
            or not corpus_id
            or type(seal) is not Mem0OssRunSeal
            or seal.admission_commitment_sha256 != self._admission
            or seal.operation_count != self._authority.operation_count
            or seal.ingestion_root_sha256 != self._authority.ingestion_root_sha256
            or not is_sha256(expected_seal_commitment_sha256)
            or seal.commitment_sha256 != expected_seal_commitment_sha256
            or type(observations) is not tuple
            or len(observations) != self._authority.operation_count
        ):
            raise ManagedRunError("managed Mem0 v5 corpus evidence gate differs")


def _corpus_evidence(
    *,
    run_id: str,
    corpus_id: str,
    authority_commitment_sha256: str,
    seal: Mem0OssRunSeal,
    units: tuple[ManagedMem0V5CorpusUnitEvidence, ...],
) -> ManagedMem0V5CorpusIngestEvidence:
    target = canonical_sha256(
        {"admission_commitment_sha256": seal.admission_commitment_sha256, "corpus_id": corpus_id}
    )
    base = {
        "run_id": run_id,
        "target_identity_sha256": target,
        "corpus_id": corpus_id,
        "authority_commitment_sha256": authority_commitment_sha256,
        "seal_commitment_sha256": seal.commitment_sha256,
        "units": [item.payload() for item in units],
    }
    return ManagedMem0V5CorpusIngestEvidence(
        run_id,
        target,
        corpus_id,
        authority_commitment_sha256,
        seal.commitment_sha256,
        units,
        canonical_sha256(base),
    )


__all__ = (
    "ManagedMem0V5AuthenticatedCleanStateWitness",
    "ManagedMem0V5CleanCorpusScope",
    "ManagedMem0V5CleanStateSnapshotPort",
    "ManagedMem0V5CleanStateWitnessIssuerPort",
    "ManagedMem0V5CleanStateWitnessVerifierPort",
    "ManagedMem0V5CorpusEvidenceProjector",
    "ManagedMem0V5CorpusIngestEvidence",
    "ManagedMem0V5CorpusUnitEvidence",
    "ManagedMem0V5DurableCleanStatePort",
    "create_managed_mem0_v5_clean_state_witness_authority",
    "managed_mem0_v5_clean_evidence_commitment_sha256",
)
