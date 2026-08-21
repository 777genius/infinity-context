from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict
from pathlib import Path

from mem0_oss_adapter_v5.admission_evidence import bind_admission, bind_cleanup_authority
from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.cleanup import (
    CleanupReceipt as StorageCleanupReceipt,
)
from mem0_oss_adapter_v5.cleanup import (
    CleanupSeal,
    cleanup_scope_idempotent,
    seal_cleanup_snapshot,
)
from mem0_oss_adapter_v5.cleanup_evidence import (
    decode as decode_cleanup_evidence,
)
from mem0_oss_adapter_v5.cleanup_evidence import (
    encode as encode_cleanup_evidence,
)
from mem0_oss_adapter_v5.cleanup_evidence import (
    path_for as cleanup_evidence_path,
)
from mem0_oss_adapter_v5.domain import (
    ExtractionMemory,
    OperationDispatchIntent,
    RuntimeExtractionResult,
    canonical_sha256,
)
from mem0_oss_adapter_v5.durable_result import (
    DurableResult as _DurableResult,
)
from mem0_oss_adapter_v5.durable_result import (
    ReceiptAuthority as _ReceiptAuthority,
)
from mem0_oss_adapter_v5.durable_result import digest as _digest
from mem0_oss_adapter_v5.durable_result import encode_result as _encode_result
from mem0_oss_adapter_v5.durable_result import parse_result as _parse_result
from mem0_oss_adapter_v5.evidence_composition import V5EvidenceComposition
from mem0_oss_adapter_v5.evidence_contracts import ExpectedMemoryCommitment
from mem0_oss_adapter_v5.extraction_contract import build_extraction_request
from mem0_oss_adapter_v5.http_models import (
    AdmissionReceipt,
    AdmitRequest,
    CleanStateRequest,
    CleanStateResponse,
    CleanupReceipt,
    CleanupRequest,
    DispatchRequest,
    RuntimeReceiptEnvelope,
    RuntimeReceiptV2,
    ScopedSearchRequest,
    ScopedSearchResponse,
    StatusRequest,
    StorageObservationRequest,
    StorageObservationResponse,
)
from mem0_oss_adapter_v5.mem0_storage import (
    Mem0StorageAdapter,
    StorageMemory,
    StorageScope,
    StorageSnapshot,
    independent_snapshot,
)
from mem0_oss_adapter_v5.private_io import atomic_private_write as _atomic_private_write
from mem0_oss_adapter_v5.private_io import (
    ensure_private_file_durable as _ensure_private_file_durable,
)
from mem0_oss_adapter_v5.private_io import private_directory as _private_directory
from mem0_oss_adapter_v5.private_io import read_private_json as _read_private_json
from mem0_oss_adapter_v5.request_binding import (
    RequestBindingError,
    RequestBindingRequest,
    RequestBindingResponse,
    RequestBindingService,
    RequestBindingV2Response,
)
from mem0_oss_adapter_v5.run_commitments import OperationEvidence, reconstruct, runner_state
from mem0_oss_adapter_v5.runtime_attestation import V5RuntimeAuthorityProjection
from mem0_oss_adapter_v5.sealed_manifest import InputUnit as _InputUnit
from mem0_oss_adapter_v5.sealed_manifest import SealedInputManifest
from mem0_oss_adapter_v5.state_sqlite import OperationRecord, OperationState, SqliteOperationState
from mem0_oss_adapter_v5.subscription_runtime import (
    SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    SubscriptionRuntimeClient,
    SubscriptionRuntimeError,
)

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class V5AdapterService:
    """Coordinates durable state, one runtime attempt, exact storage, and cleanup."""

    def __init__(
        self,
        *,
        manifest: SealedInputManifest,
        state: SqliteOperationState,
        runtime: SubscriptionRuntimeClient,
        receipt_authority: _ReceiptAuthority,
        storage: Mem0StorageAdapter,
        receipt_directory: Path,
        result_hmac_key: bytes,
        runtime_authority: V5RuntimeAuthorityProjection,
    ) -> None:
        self._manifest = manifest
        self._state = state
        self._runtime = runtime
        self._receipt_authority = receipt_authority
        if type(runtime_authority) is not V5RuntimeAuthorityProjection:
            raise ValueError("adapter_configuration_invalid")
        self._runtime_authority = runtime_authority
        self._expected_account_binding = runtime_authority.expected_account_binding_hmac_sha256
        self._expected_base_instructions = runtime_authority.expected_base_instructions_sha256
        self._storage = storage
        self._receipt_directory = _private_directory(receipt_directory)
        if type(result_hmac_key) is not bytes or len(result_hmac_key) < 32:
            raise ValueError("adapter_configuration_invalid")
        self._result_hmac_key = bytes(result_hmac_key)
        self._runtime_binding = runtime_authority.runtime_binding_commitment_sha256
        self._runtime_source_sha256 = runtime_authority.runtime_source_sha256
        self._admission: str | None = None
        self._committed_memory_ids: dict[str, tuple[str, ...]] = {}
        self._evidence = V5EvidenceComposition(
            manifest=manifest,
            state=state,
            backend=lambda: self._storage.backend,
            current_admission=lambda: self._admission,
            operation_id=self._operation_id,
            extraction_request=self._extraction_request,
            storage_authority=self._evidence_storage_authority,
            runtime_binding_commitment_sha256=self._runtime_binding,
            runtime_source_sha256=self._runtime_source_sha256,
            evidence_directory=self._receipt_directory,
            hmac_key=self._result_hmac_key,
        )
        self._lock = threading.RLock()

    def admit(self, request: AdmitRequest, *, idempotency_key: str) -> AdmissionReceipt:
        del idempotency_key
        with self._lock:
            if (
                request.ingestion_manifest_sha256 != self._manifest.ingestion_manifest_sha256
                or request.ingestion_root_sha256 != self._manifest.ingestion_root_sha256
                or request.expected_operation_count != len(self._manifest.units)
                or request.route_sha256 != SUBSCRIPTION_RUNTIME_ROUTE_SHA256
            ):
                raise AdapterServiceError("manifest_invalid", status_code=400)
            if self._admission not in {None, request.admission_commitment_sha256}:
                raise AdapterServiceError("admission_conflict")
            self._admission = request.admission_commitment_sha256
            inventory = []
            artifact_paths = []
            for unit in self._manifest.units:
                extraction = self._extraction_request(unit)
                inventory.append(
                    {
                        "operation_id_sha256": self._operation_id(unit),
                        "unit_index": unit.sequence,
                        "unit_identity_sha256": unit.unit_identity_sha256,
                        "unit_sha256": unit.unit_sha256,
                        "scope_sha256": unit.scope_sha256,
                        "request_body_sha256": extraction.request_body_sha256,
                    }
                )
                artifact_paths.extend(
                    (
                        self._result_path(self._operation_id(unit)),
                        self._cleanup_evidence_path(unit),
                    )
                )
            try:
                bind_admission(
                    directory=self._receipt_directory,
                    hmac_key=self._result_hmac_key,
                    admission=request.model_dump(mode="json"),
                    inventory=tuple(inventory),
                    state=self._state,
                    artifact_paths=tuple(artifact_paths),
                )
            except ValueError:
                raise AdapterServiceError("admission_conflict") from None
            self._resume_local_operations()
            self._state.recover()
            return AdmissionReceipt(
                admission_commitment_sha256=request.admission_commitment_sha256,
                runtime_binding_commitment_sha256=self._runtime_binding,
                accepted=True,
            )

    def dispatch(self, request: DispatchRequest, *, idempotency_key: str) -> RuntimeReceiptEnvelope:
        del idempotency_key
        with self._lock:
            unit = self._bound_unit(request)
            record = self._state.get(unit.unit_identity_sha256)
            if record.state in {
                OperationState.RECEIPT_DURABLE,
                OperationState.STORAGE_VERIFIED,
                OperationState.COMMITTED,
            }:
                self._resume_unit(unit)
                record = self._state.get(unit.unit_identity_sha256)
                result = self._read_result(
                    request.operation_id_sha256,
                    expected=unit,
                    record=record,
                )
                return _envelope(result)
            if record.state is OperationState.ADMITTED:
                self._state.reserve(unit.unit_identity_sha256)
                record = self._state.get(unit.unit_identity_sha256)
            if record.state is OperationState.DISPATCHED:
                self._resume_unit(unit)
                record = self._state.get(unit.unit_identity_sha256)
                if record.state in {
                    OperationState.RECEIPT_DURABLE,
                    OperationState.STORAGE_VERIFIED,
                    OperationState.COMMITTED,
                }:
                    self._resume_unit(unit)
                    return _envelope(
                        self._read_result(
                            request.operation_id_sha256,
                            expected=unit,
                            record=self._state.get(unit.unit_identity_sha256),
                        )
                    )
                if record.outcome_unknown:
                    raise AdapterServiceError(
                        "dispatch_recovery_operator_action_required",
                        status_code=503,
                    )
            if record.state not in {OperationState.RESERVED, OperationState.DISPATCHED}:
                raise AdapterServiceError("dispatch_conflict")
            extraction = self._extraction_request(unit)
            intent = _intent(request)
            if extraction.request_body_sha256 != request.request_body_sha256:
                raise AdapterServiceError("request_binding_invalid", status_code=400)
            if record.state is OperationState.RESERVED:
                self._state.mark_dispatched(unit.unit_identity_sha256)
            try:
                returned = self._runtime.extract(
                    extraction,
                    intent,
                    before_dispatch=lambda observed: self._claim_provider_call(
                        unit,
                        expected=intent,
                        observed=observed,
                    ),
                    persist_result=lambda result: self._persist_runtime_result(
                        unit,
                        expected=intent,
                        result=result,
                    ),
                )
            except SubscriptionRuntimeError as exc:
                record = self._state.get(unit.unit_identity_sha256)
                if not record.outcome_unknown and (
                    exc.outcome is None or exc.outcome.redispatch_allowed
                ):
                    raise AdapterServiceError("dispatch_failed", status_code=503) from None
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                ) from None
            except Exception:
                record = self._state.get(unit.unit_identity_sha256)
                code = (
                    "dispatch_recovery_operator_action_required"
                    if record.outcome_unknown
                    else "dispatch_failed"
                )
                raise AdapterServiceError(code, status_code=503) from None
            try:
                durable = self._read_result(
                    request.operation_id_sha256,
                    expected=unit,
                    record=self._state.get(unit.unit_identity_sha256),
                )
                returned_commitment = returned.commitment_sha256
            except Exception:
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                ) from None
            if returned_commitment != durable.commitment_sha256:
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                )
            try:
                self._state.mark_receipt_durable(
                    unit.unit_identity_sha256,
                    durable.receipt.receipt_sha256,
                )
            except Exception:
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                ) from None
            self._resume_unit(unit)
            return _envelope(durable)

    def status(self, request: StatusRequest, *, idempotency_key: str) -> RuntimeReceiptEnvelope:
        del idempotency_key
        with self._lock:
            self._require_admission(request.admission_commitment_sha256)
            unit = self._unit_by_operation(request.operation_id_sha256)
            record = self._state.get(unit.unit_identity_sha256)
            if record.state in {OperationState.CLEANED, OperationState.ABORT_CLEANED}:
                raise AdapterServiceError("operation_cleaned", status_code=410)
            if record.state is OperationState.DISPATCHED:
                self._resume_unit(unit)
                record = self._state.get(unit.unit_identity_sha256)
            if record.state not in {
                OperationState.RECEIPT_DURABLE,
                OperationState.STORAGE_VERIFIED,
                OperationState.COMMITTED,
            }:
                if record.state is OperationState.DISPATCHED and record.outcome_unknown:
                    raise AdapterServiceError(
                        "dispatch_recovery_operator_action_required",
                        status_code=503,
                    )
                raise AdapterServiceError("status_unavailable", status_code=503)
            return _envelope(
                self._read_result(
                    request.operation_id_sha256,
                    expected=unit,
                    record=record,
                )
            )

    def storage_observation(
        self,
        request: StorageObservationRequest,
        *,
        idempotency_key: str,
    ) -> StorageObservationResponse:
        with self._lock:
            return self._evidence.storage.storage_observation(
                request,
                idempotency_key=idempotency_key,
            )

    def request_binding(
        self,
        request: RequestBindingRequest,
        *,
        idempotency_key: str,
    ) -> RequestBindingResponse | RequestBindingV2Response:
        with self._lock:
            try:
                return self._evidence.request.bind(
                    request,
                    current_admission_commitment_sha256=self._admission,
                    idempotency_key=idempotency_key,
                )
            except RequestBindingError as exc:
                raise AdapterServiceError(exc.code, status_code=exc.status_code) from None

    def clean_state(
        self,
        request: CleanStateRequest,
        *,
        idempotency_key: str,
        request_commitment_sha256: str,
    ) -> CleanStateResponse:
        with self._lock:
            return self._evidence.clean.prove_empty(
                request,
                idempotency_key=idempotency_key,
                request_commitment_sha256=request_commitment_sha256,
            )

    def scoped_search(
        self,
        request: ScopedSearchRequest,
        *,
        idempotency_key: str,
    ) -> ScopedSearchResponse:
        with self._lock:
            return self._evidence.storage.scoped_search(
                request,
                idempotency_key=idempotency_key,
            )

    def cleanup(self, request: CleanupRequest, *, idempotency_key: str) -> CleanupReceipt:
        del idempotency_key
        with self._lock:
            self._require_admission(request.admission_commitment_sha256)
            if request.expected_operation_count != len(self._manifest.units):
                raise AdapterServiceError("cleanup_conflict")
            if (request.seal_commitment_sha256 is None) != (request.operation_root_sha256 is None):
                raise AdapterServiceError("cleanup_conflict")
            if request.aborting:
                self._state.recover()
            try:
                authority_path = self._receipt_directory / "cleanup-authority.json"
                expected = (
                    None if authority_path.exists() else self._run_commitments(request.aborting)
                )
                authority = bind_cleanup_authority(
                    directory=self._receipt_directory,
                    hmac_key=self._result_hmac_key,
                    expected=expected,
                )
            except ValueError:
                raise AdapterServiceError("cleanup_conflict") from None
            if authority != {
                "seal_commitment_sha256": request.seal_commitment_sha256,
                "operation_root_sha256": request.operation_root_sha256,
                "operation_inventory_root_sha256": request.operation_inventory_root_sha256,
            }:
                raise AdapterServiceError("cleanup_conflict")
            deleted = 0
            for unit in self._manifest.units:
                record = self._state.get(unit.unit_identity_sha256)
                if record.state in {OperationState.CLEANED, OperationState.ABORT_CLEANED}:
                    self._replay_cleanup(unit, record)
                    deleted += 1
                    continue
                if record.state is OperationState.COMMITTED:
                    self._clean_unit(unit, record, aborting=False)
                    deleted += 1
                    continue
                if not request.aborting or record.state not in {
                    OperationState.ADMITTED,
                    OperationState.RESERVED,
                    OperationState.DISPATCHED,
                    OperationState.RECEIPT_DURABLE,
                    OperationState.STORAGE_VERIFIED,
                }:
                    raise AdapterServiceError("cleanup_conflict")
                self._clean_unit(unit, record, aborting=True)
                deleted += 1
            residual = sum(
                len(independent_snapshot(self._storage.backend, scope=self._scope(unit)).vectors)
                for unit in self._manifest.units
            )
            return CleanupReceipt(
                admission_commitment_sha256=request.admission_commitment_sha256,
                seal_commitment_sha256=request.seal_commitment_sha256,
                operation_root_sha256=request.operation_root_sha256,
                operation_inventory_root_sha256=request.operation_inventory_root_sha256,
                deleted_operation_count=deleted,
                residual_record_count=residual,
                residual_root_sha256=(
                    _EMPTY_SHA256
                    if residual == 0
                    else canonical_sha256({"residual_record_count": residual})
                ),
            )

    def _run_commitments(self, aborting: bool) -> dict[str, object]:
        operations = []
        durable = {
            OperationState.RECEIPT_DURABLE,
            OperationState.STORAGE_VERIFIED,
            OperationState.COMMITTED,
        }
        stored = {OperationState.STORAGE_VERIFIED, OperationState.COMMITTED}
        for unit in self._manifest.units:
            record = self._state.get(unit.unit_identity_sha256)
            if record.state is OperationState.ADMITTED:
                continue
            result = None
            if record.state in durable:
                result = self._read_result(self._operation_id(unit), expected=unit, record=record)
            if record.state in stored:
                assert result is not None and record.storage_commitment_sha256 is not None
                verification = self._verify_storage_exact(unit, result.memories)
                if verification.commitment_sha256 != record.storage_commitment_sha256:
                    raise ValueError("cleanup_evidence_invalid")
            usage = result.receipt.model.usage if result is not None else None
            operations.append(
                OperationEvidence(
                    operation_id_sha256=self._operation_id(unit),
                    unit_index=unit.sequence,
                    unit_identity_sha256=unit.unit_identity_sha256,
                    unit_sha256=unit.unit_sha256,
                    scope_sha256=unit.scope_sha256,
                    provider_receipt_sha256=(
                        result.receipt.receipt_sha256 if result is not None else None
                    ),
                    request_tokens=usage.prompt_tokens if usage is not None else 0,
                    response_tokens=usage.completion_tokens if usage is not None else 0,
                    stored_identity_sha256=(
                        record.storage_commitment_sha256 if record.state in stored else None
                    ),
                    stored_record_count=len(result.memories) if record.state in stored else 0,
                    state=runner_state(record.state.value, outcome_unknown=record.outcome_unknown),
                )
            )
        return reconstruct(
            admission_commitment_sha256=str(self._admission),
            ingestion_root_sha256=self._manifest.ingestion_root_sha256,
            operations=tuple(operations),
            aborting=aborting,
        )

    def _evidence_storage_authority(
        self,
        unit: _InputUnit,
        record: OperationRecord,
    ) -> tuple[tuple[ExpectedMemoryCommitment, ...], str]:
        if record.state is not OperationState.COMMITTED or record.storage_commitment_sha256 is None:
            raise AdapterServiceError("run_state_invalid", status_code=503)
        try:
            result = self._read_result(self._operation_id(unit), expected=unit, record=record)
            expected = tuple(
                ExpectedMemoryCommitment(
                    extraction_memory_id=item.id,
                    memory_sha256=hashlib.sha256(item.text.encode()).hexdigest(),
                )
                for item in result.memories
            )
            if len({item.extraction_memory_id for item in expected}) != len(expected):
                raise ValueError("duplicate durable extraction identity")
            return expected, record.storage_commitment_sha256
        except Exception:
            raise AdapterServiceError("run_state_invalid", status_code=503) from None

    def _request_binding_service(self) -> RequestBindingService:
        return self._evidence.request

    def _clean_unit(
        self,
        unit: _InputUnit,
        record: OperationRecord,
        *,
        aborting: bool,
    ) -> None:
        scope = self._scope(unit)
        evidence = self._read_cleanup_evidence(unit, required=False)
        if evidence is None:
            snapshot = independent_snapshot(self._storage.backend, scope=scope)
            result_path, result_sha = self._cleanup_result_identity(unit, record, snapshot)
            before = seal_cleanup_snapshot(snapshot)
            self._write_cleanup_evidence(
                unit,
                before=before,
                runtime_receipt_sha256=result_sha,
                receipt=None,
            )
            prior = None
        else:
            before, result_sha, prior = evidence
            result_path = self._result_path(self._operation_id(unit)) if result_sha else None
        receipt = cleanup_scope_idempotent(
            self._storage.backend,
            scope=scope,
            sealed_before=before,
            prior_receipt=prior,
            runtime_receipt_path=result_path,
            runtime_receipt_sha256=result_sha,
        )
        self._write_cleanup_evidence(
            unit,
            before=before,
            runtime_receipt_sha256=result_sha,
            receipt=receipt,
        )
        if aborting:
            self._state.abort_cleaned(
                unit.unit_identity_sha256,
                cleanup_result_sha256=canonical_sha256(asdict(receipt)),
                tombstone_commitment_sha256=receipt.tombstone_commitment_sha256,
            )
        else:
            self._state.clean(unit.unit_identity_sha256, receipt.tombstone_commitment_sha256)

    def _cleanup_result_identity(
        self,
        unit: _InputUnit,
        record: OperationRecord,
        before: StorageSnapshot,
    ) -> tuple[Path | None, str | None]:
        operation_id = self._operation_id(unit)
        path = self._result_path(operation_id)
        if path.exists():
            result = self._read_result(operation_id, expected=unit, record=record)
            self._require_abort_subset(before, result.memories)
            return path, hashlib.sha256(path.read_bytes()).hexdigest()
        if (
            record.state
            in {
                OperationState.RECEIPT_DURABLE,
                OperationState.STORAGE_VERIFIED,
                OperationState.COMMITTED,
            }
            or not before.empty
        ):
            raise AdapterServiceError("cleanup_failed")
        return None, None

    def _require_abort_subset(
        self,
        snapshot: StorageSnapshot,
        memories: tuple[ExtractionMemory, ...],
    ) -> None:
        expected = {item.id: item for item in memories}
        actual = {item.extraction_memory_id: item for item in snapshot.vectors}
        if len(actual) != len(snapshot.vectors) or not set(actual).issubset(expected):
            raise AdapterServiceError("cleanup_failed")
        for identity, vector in actual.items():
            memory = expected[identity]
            if (
                vector.text != memory.text
                or vector.attributed_to != memory.attributed_to
                or vector.linked_memory_ids != tuple(sorted(memory.linked_memory_ids))
            ):
                raise AdapterServiceError("cleanup_failed")
        if (
            snapshot.history_memory_ids != tuple(sorted(snapshot.provider_memory_ids))
            or snapshot.message_ids
            or snapshot.entity_links
        ):
            raise AdapterServiceError("cleanup_failed")

    def _replay_cleanup(self, unit: _InputUnit, record: OperationRecord) -> None:
        evidence = self._read_cleanup_evidence(unit, required=True)
        assert evidence is not None
        before, result_sha, prior = evidence
        if prior is None or prior.tombstone_commitment_sha256 != record.tombstone_commitment_sha256:
            raise AdapterServiceError("cleanup_failed")
        if record.state is OperationState.ABORT_CLEANED and (
            record.abort_result_sha256 != canonical_sha256(asdict(prior))
        ):
            raise AdapterServiceError("cleanup_failed")
        receipt = cleanup_scope_idempotent(
            self._storage.backend,
            scope=self._scope(unit),
            sealed_before=before,
            prior_receipt=prior,
            runtime_receipt_path=(
                self._result_path(self._operation_id(unit)) if result_sha else None
            ),
            runtime_receipt_sha256=result_sha,
        )
        self._write_cleanup_evidence(
            unit,
            before=before,
            runtime_receipt_sha256=result_sha,
            receipt=receipt,
        )

    def _cleanup_evidence_path(self, unit: _InputUnit) -> Path:
        return cleanup_evidence_path(self._receipt_directory, self._operation_id(unit))

    def _write_cleanup_evidence(
        self,
        unit: _InputUnit,
        *,
        before: CleanupSeal,
        runtime_receipt_sha256: str | None,
        receipt: StorageCleanupReceipt | None,
    ) -> None:
        _atomic_private_write(
            self._cleanup_evidence_path(unit),
            encode_cleanup_evidence(
                unit_identity_sha256=unit.unit_identity_sha256,
                before=before,
                runtime_receipt_sha256=runtime_receipt_sha256,
                receipt=receipt,
                hmac_key=self._result_hmac_key,
            ),
        )

    def _read_cleanup_evidence(
        self,
        unit: _InputUnit,
        *,
        required: bool,
    ) -> tuple[CleanupSeal, str | None, StorageCleanupReceipt | None] | None:
        path = self._cleanup_evidence_path(unit)
        if not path.exists():
            if required:
                raise AdapterServiceError("cleanup_failed")
            return None
        payload = _read_private_json(path, maximum_bytes=4_194_304)
        try:
            return decode_cleanup_evidence(
                payload,
                unit_identity_sha256=unit.unit_identity_sha256,
                hmac_key=self._result_hmac_key,
            )
        except ValueError:
            raise AdapterServiceError("cleanup_failed") from None

    def _bound_unit(self, request: DispatchRequest) -> _InputUnit:
        self._require_admission(request.admission_commitment_sha256)
        try:
            unit = self._manifest.get(request.unit_identity_sha256)
        except KeyError:
            raise AdapterServiceError("operation_not_found", status_code=404) from None
        if (
            request.sequence != unit.sequence
            or request.unit_sha256 != unit.unit_sha256
            or request.scope_sha256 != unit.scope_sha256
            or request.operation_id_sha256 != self._operation_id(unit)
        ):
            raise AdapterServiceError("request_binding_invalid", status_code=400)
        return unit

    def _require_admission(self, value: str) -> None:
        if self._admission != value:
            raise AdapterServiceError("run_not_found", status_code=404)

    def _operation_id(self, unit: _InputUnit) -> str:
        assert self._admission is not None
        return canonical_sha256(
            {
                "admission_commitment_sha256": self._admission,
                "unit_index": unit.sequence,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )

    def _unit_by_operation(self, operation_id: str) -> _InputUnit:
        for unit in self._manifest.units:
            if self._operation_id(unit) == operation_id:
                return unit
        raise AdapterServiceError("operation_not_found", status_code=404)

    def _scope(self, unit: _InputUnit) -> StorageScope:
        assert self._admission is not None
        return StorageScope(
            user_id=unit.corpus_id,
            run_id=self._admission,
            source_id=unit.source_id,
            source_sha256=unit.source_sha256,
        )

    def _extraction_request(self, unit: _InputUnit):
        return build_extraction_request(
            source_messages=unit.source_messages,
            current_date=self._manifest.current_date,
            timestamp=unit.observation_date,
        )

    def _persist_or_verify(self, unit: _InputUnit, memories: tuple[ExtractionMemory, ...]):
        values = tuple(
            StorageMemory(
                memory_id=item.id,
                text=item.text,
                attributed_to=item.attributed_to,
                linked_memory_ids=item.linked_memory_ids,
            )
            for item in memories
        )
        scope = self._scope(unit)
        try:
            return self._storage.verify_exact(scope=scope, memories=values)
        except Exception:
            try:
                return self._storage.persist(scope=scope, memories=values)
            except Exception:
                raise AdapterServiceError("storage_verification_failed") from None

    def _claim_provider_call(
        self,
        unit: _InputUnit,
        *,
        expected: OperationDispatchIntent,
        observed: OperationDispatchIntent,
    ) -> None:
        if type(observed) is not OperationDispatchIntent or observed != expected:
            raise AdapterServiceError(
                "dispatch_recovery_operator_action_required",
                status_code=503,
            )
        record = self._state.get(unit.unit_identity_sha256)
        if (
            record.state is not OperationState.DISPATCHED
            or record.outcome_unknown
            or record.request_sha256 != expected.request_body_sha256
            or self._result_path(expected.operation_id_sha256).exists()
        ):
            raise AdapterServiceError(
                "dispatch_recovery_operator_action_required",
                status_code=503,
            )
        self._state.claim_provider_call(unit.unit_identity_sha256)

    def _persist_runtime_result(
        self,
        unit: _InputUnit,
        *,
        expected: OperationDispatchIntent,
        result: RuntimeExtractionResult,
    ) -> None:
        if type(result) is not RuntimeExtractionResult or result.intent != expected:
            raise AdapterServiceError(
                "dispatch_recovery_operator_action_required",
                status_code=503,
            )
        record = self._state.get(unit.unit_identity_sha256)
        if (
            record.state is not OperationState.DISPATCHED
            or not record.outcome_unknown
            or record.request_sha256 != expected.request_body_sha256
        ):
            raise AdapterServiceError(
                "dispatch_recovery_operator_action_required",
                status_code=503,
            )
        path = self._result_path(expected.operation_id_sha256)
        if not path.exists():
            self._write_result(result)
        durable = self._read_result(
            expected.operation_id_sha256,
            expected=unit,
            record=record,
        )
        if durable.commitment_sha256 != result.commitment_sha256:
            raise AdapterServiceError(
                "dispatch_recovery_operator_action_required",
                status_code=503,
            )

    def _result_path(self, operation_id: str) -> Path:
        return self._receipt_directory / f"{_digest(operation_id)}.json"

    def _write_result(self, result: RuntimeExtractionResult) -> None:
        _atomic_private_write(
            self._result_path(result.intent.operation_id_sha256),
            _encode_result(result, hmac_key=self._result_hmac_key),
        )

    def _read_result(
        self,
        operation_id: str,
        *,
        expected: _InputUnit,
        record: OperationRecord | None = None,
    ) -> _DurableResult:
        try:
            payload = _read_private_json(self._result_path(operation_id), maximum_bytes=1_048_576)
            extraction = self._extraction_request(expected)
            result = _parse_result(
                payload,
                hmac_key=self._result_hmac_key,
                receipt_authority=self._receipt_authority,
                request=extraction,
                expected_account_binding_hmac_sha256=self._expected_account_binding,
                expected_base_instructions_sha256=self._expected_base_instructions,
            )
        except AdapterServiceError:
            raise
        except Exception:
            raise AdapterServiceError("status_unavailable", status_code=503) from None
        if (
            result.intent.operation_id_sha256 != operation_id
            or result.intent.unit_identity_sha256 != expected.unit_identity_sha256
            or result.intent.unit_sha256 != expected.unit_sha256
        ):
            raise AdapterServiceError("status_unavailable", status_code=503)
        if record is not None and (
            result.intent.request_body_sha256 != record.request_sha256
            or (
                record.runtime_receipt_sha256 is not None
                and result.receipt.receipt_sha256 != record.runtime_receipt_sha256
            )
        ):
            raise AdapterServiceError("status_unavailable", status_code=503)
        return result

    def _resume_local_operations(self) -> None:
        for unit in self._manifest.units:
            self._resume_unit(unit)

    def _resume_unit(self, unit: _InputUnit) -> None:
        record = self._state.get(unit.unit_identity_sha256)
        operation_id = self._operation_id(unit)
        if record.state is OperationState.DISPATCHED:
            result_path = self._result_path(operation_id)
            if not result_path.exists():
                return
            if not record.outcome_unknown:
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                )
            try:
                _ensure_private_file_durable(result_path)
            except Exception:
                raise AdapterServiceError(
                    "dispatch_recovery_operator_action_required",
                    status_code=503,
                ) from None
            result = self._read_result(operation_id, expected=unit, record=record)
            self._state.mark_receipt_durable(
                unit.unit_identity_sha256,
                result.receipt.receipt_sha256,
            )
            record = self._state.get(unit.unit_identity_sha256)
        if record.state is OperationState.RECEIPT_DURABLE:
            result = self._read_result(operation_id, expected=unit, record=record)
            verification = self._persist_or_verify(unit, result.memories)
            self._state.mark_storage_verified(
                unit.unit_identity_sha256,
                verification.commitment_sha256,
            )
            record = self._state.get(unit.unit_identity_sha256)
        if record.state is OperationState.STORAGE_VERIFIED:
            result = self._read_result(operation_id, expected=unit, record=record)
            verification = self._verify_storage_exact(unit, result.memories)
            if verification.commitment_sha256 != record.storage_commitment_sha256:
                raise AdapterServiceError("storage_verification_failed", status_code=503)
            self._state.commit(unit.unit_identity_sha256)
            record = self._state.get(unit.unit_identity_sha256)
        if record.state is OperationState.COMMITTED:
            result = self._read_result(operation_id, expected=unit, record=record)
            self._committed_memory_ids[unit.unit_identity_sha256] = tuple(
                item.id for item in result.memories
            )

    def _verify_storage_exact(
        self,
        unit: _InputUnit,
        memories: tuple[ExtractionMemory, ...],
    ):
        values = tuple(
            StorageMemory(
                memory_id=item.id,
                text=item.text,
                attributed_to=item.attributed_to,
                linked_memory_ids=item.linked_memory_ids,
            )
            for item in memories
        )
        try:
            return self._storage.verify_exact(scope=self._scope(unit), memories=values)
        except Exception:
            raise AdapterServiceError("storage_verification_failed", status_code=503) from None


def _intent(request: DispatchRequest) -> OperationDispatchIntent:
    return OperationDispatchIntent(**request.model_dump())


def _envelope(result: RuntimeExtractionResult | _DurableResult) -> RuntimeReceiptEnvelope:
    return RuntimeReceiptEnvelope(
        admission_commitment_sha256=result.intent.admission_commitment_sha256,
        operation_id_sha256=result.intent.operation_id_sha256,
        runtime_receipt=RuntimeReceiptV2.model_validate(result.receipt.public_payload()),
    )


def build_app_from_environment():
    from mem0_oss_adapter_v5.bootstrap import build_app_from_environment as build

    return build()
