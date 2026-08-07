"""Application service for exact, authenticated storage and search evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.evidence_contracts import (
    EvidenceOperation,
    EvidenceSigner,
    ExpectedMemoryCommitment,
    ObservedRecord,
    ObservedStorage,
    SearchRecord,
)
from mem0_oss_adapter_v5.http_models import (
    ScopedSearchRequest,
    ScopedSearchResponse,
    StorageObservationRequest,
    StorageObservationResponse,
)
from mem0_oss_adapter_v5.sealed_manifest import InputUnit, SealedInputManifest
from mem0_oss_adapter_v5.state_sqlite import OperationRecord, OperationState, SqliteOperationState

OperationStorageAuthority = tuple[tuple[ExpectedMemoryCommitment, ...], str]


class EvidenceContext(Protocol):
    def committed_operation(
        self, *, admission_commitment_sha256: str, operation_id_sha256: str
    ) -> EvidenceOperation: ...

    def committed_corpus(
        self, *, admission_commitment_sha256: str, corpus_id: str
    ) -> tuple[EvidenceOperation, ...]: ...


class EvidenceStorage(Protocol):
    def observe(self, operation: EvidenceOperation) -> ObservedStorage: ...

    def observe_corpus(
        self, operations: tuple[EvidenceOperation, ...]
    ) -> tuple[ObservedRecord, ...]: ...

    def search(
        self,
        *,
        admission_commitment_sha256: str,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> tuple[SearchRecord, ...]: ...


class ManifestEvidenceContext:
    """Binds signed durable result content to HMAC-authenticated run state."""

    def __init__(
        self,
        *,
        manifest: SealedInputManifest,
        state: SqliteOperationState,
        admission: Callable[[], str | None],
        operation_id: Callable[[InputUnit], str],
        storage_authority: Callable[[InputUnit, OperationRecord], OperationStorageAuthority],
    ) -> None:
        self._manifest = manifest
        self._state = state
        self._admission = admission
        self._operation_id = operation_id
        self._storage_authority = storage_authority

    def committed_operation(
        self, *, admission_commitment_sha256: str, operation_id_sha256: str
    ) -> EvidenceOperation:
        self._require_admission(admission_commitment_sha256)
        unit = next(
            (
                candidate
                for candidate in self._manifest.units
                if self._operation_id(candidate) == operation_id_sha256
            ),
            None,
        )
        if unit is None:
            raise AdapterServiceError("operation_not_found", status_code=404)
        return self._committed(unit)

    def committed_corpus(
        self, *, admission_commitment_sha256: str, corpus_id: str
    ) -> tuple[EvidenceOperation, ...]:
        self._require_admission(admission_commitment_sha256)
        units = tuple(unit for unit in self._manifest.units if unit.corpus_id == corpus_id)
        if not units:
            raise AdapterServiceError("corpus_not_found", status_code=404)
        try:
            records = self._state.get_many(unit.unit_identity_sha256 for unit in units)
            return tuple(
                self._committed(unit, record=record)
                for unit, record in zip(units, records, strict=True)
            )
        except AdapterServiceError as exc:
            if exc.code in {"operation_cleaned"}:
                raise
            raise AdapterServiceError("run_state_invalid", status_code=503) from None
        except Exception:
            raise AdapterServiceError("run_state_invalid", status_code=503) from None

    def _require_admission(self, value: str) -> None:
        if self._admission() != value:
            raise AdapterServiceError("run_not_found", status_code=404)

    def _committed(
        self, unit: InputUnit, *, record: OperationRecord | None = None
    ) -> EvidenceOperation:
        try:
            record = record or self._state.get(unit.unit_identity_sha256)
            if record.state in {OperationState.CLEANED, OperationState.ABORT_CLEANED}:
                raise AdapterServiceError("operation_cleaned", status_code=410)
            if record.state is not OperationState.COMMITTED:
                raise AdapterServiceError("run_state_invalid", status_code=503)
            expected_memories, storage_commitment = self._storage_authority(unit, record)
            return EvidenceOperation(
                admission_commitment_sha256=str(self._admission()),
                operation_id_sha256=self._operation_id(unit),
                scope_sha256=unit.scope_sha256,
                corpus_id=unit.corpus_id,
                source_id=unit.source_id,
                source_sha256=unit.source_sha256,
                expected_memories=expected_memories,
                storage_commitment_sha256=storage_commitment,
            )
        except AdapterServiceError as exc:
            if exc.code == "operation_cleaned":
                raise
            raise AdapterServiceError("run_state_invalid", status_code=503) from None
        except Exception:
            raise AdapterServiceError("run_state_invalid", status_code=503) from None


class AuthenticatedEvidenceService:
    """Coordinates trusted run context with an independently read storage port."""

    def __init__(
        self, *, context: EvidenceContext, storage: EvidenceStorage, hmac_key: bytes
    ) -> None:
        self._context = context
        self._storage = storage
        self._signer = EvidenceSigner(hmac_key)

    def storage_observation(
        self, request: StorageObservationRequest, *, idempotency_key: str
    ) -> StorageObservationResponse:
        del idempotency_key
        operation = self._context.committed_operation(
            admission_commitment_sha256=request.admission_commitment_sha256,
            operation_id_sha256=request.operation_id_sha256,
        )
        try:
            payload = self._signer.storage_observation(
                operation=operation,
                observation=self._storage.observe(operation),
            )
            return StorageObservationResponse.model_validate(payload)
        except AdapterServiceError:
            raise
        except Exception:
            raise AdapterServiceError("storage_verification_failed", status_code=503) from None

    def scoped_search(
        self, request: ScopedSearchRequest, *, idempotency_key: str
    ) -> ScopedSearchResponse:
        del idempotency_key
        operations = self._context.committed_corpus(
            admission_commitment_sha256=request.admission_commitment_sha256,
            corpus_id=request.corpus_id,
        )
        try:
            allowed = {
                (record.record_id, record.source_id, record.source_sha256, record.memory_sha256)
                for record in self._storage.observe_corpus(operations)
            }
            results = self._storage.search(
                admission_commitment_sha256=request.admission_commitment_sha256,
                corpus_id=request.corpus_id,
                query=request.query,
                limit=request.limit,
            )
            if any(
                (item.record_id, item.source_id, item.source_sha256, item.memory_sha256)
                not in allowed
                for item in results
            ):
                raise ValueError("mem0_v5_search_result_invalid")
            payload = self._signer.scoped_search(
                admission_commitment_sha256=request.admission_commitment_sha256,
                corpus_id=request.corpus_id,
                query=request.query,
                limit=request.limit,
                results=results,
            )
            return ScopedSearchResponse.model_validate(payload)
        except AdapterServiceError:
            raise
        except Exception:
            raise AdapterServiceError("storage_verification_failed", status_code=503) from None


__all__ = (
    "AuthenticatedEvidenceService",
    "EvidenceContext",
    "EvidenceStorage",
    "ManifestEvidenceContext",
    "OperationStorageAuthority",
)
