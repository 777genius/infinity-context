"""Trusted application service and sealed evidence chain for Mem0 OSS v5."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.memory_comparison_mem0_oss_v5_cleanup import (
    verify_cleanup_result,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE,
    CleanupVerificationContext,
    CleanupVerificationPort,
    CleanupVerificationResult,
    ManifestAuthorityResult,
    ManifestAuthorityVerificationPort,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssFullRunError,
    Mem0OssFullRunState,
    Mem0OssManifestUnit,
    Mem0OssOperationState,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationPort,
    StorageVerificationResult,
    canonical_sha256,
    manifest_root_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssEvidencePage,
    Mem0OssFailedReceiptEvidence,
    Mem0OssOperationEvidence,
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
    operation_root,
    verify_mem0_oss_sealed_evidence_pages,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_recovery import (
    Mem0OssOperationRecoveryState,
    operation_recovery_states,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    Mem0OssTerminalBasis,
    build_terminal_evidence,
)

_WITNESS_TOKEN = object()


@dataclass(slots=True)
class _Operation:
    operation_id_sha256: str
    unit_index: int
    unit: Mem0OssManifestUnit
    state: Mem0OssOperationState = Mem0OssOperationState.RESERVED
    provider_receipt_sha256: str | None = None
    disposition: Mem0OssReceiptDisposition | None = None
    extraction_calls: int = 0
    retry_count: int = 0
    request_tokens: int = 0
    response_tokens: int = 0
    stored_identity_sha256: str | None = None
    stored_record_count: int = 0
    commitment_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _ManifestWitness:
    result: ManifestAuthorityResult
    token: object

    def __post_init__(self) -> None:
        if self.token is not _WITNESS_TOKEN or type(self.result) is not ManifestAuthorityResult:
            raise Mem0OssFullRunError("mem0_v5_manifest_witness_invalid")


@dataclass(frozen=True, slots=True)
class _ReceiptWitness:
    result: RuntimeReceiptVerificationResult
    context: RuntimeReceiptVerificationContext
    token: object

    def __post_init__(self) -> None:
        if (
            self.token is not _WITNESS_TOKEN
            or type(self.result) is not RuntimeReceiptVerificationResult
            or type(self.context) is not RuntimeReceiptVerificationContext
        ):
            raise Mem0OssFullRunError("mem0_v5_receipt_witness_invalid")


@dataclass(frozen=True, slots=True)
class _StorageWitness:
    result: StorageVerificationResult
    context: StorageVerificationContext
    token: object

    def __post_init__(self) -> None:
        if (
            self.token is not _WITNESS_TOKEN
            or type(self.result) is not StorageVerificationResult
            or type(self.context) is not StorageVerificationContext
        ):
            raise Mem0OssFullRunError("mem0_v5_storage_witness_invalid")


@dataclass(frozen=True, slots=True)
class _CleanupWitness:
    result: CleanupVerificationResult
    context: CleanupVerificationContext
    token: object

    def __post_init__(self) -> None:
        if (
            self.token is not _WITNESS_TOKEN
            or type(self.result) is not CleanupVerificationResult
            or type(self.context) is not CleanupVerificationContext
        ):
            raise Mem0OssFullRunError("mem0_v5_cleanup_witness_invalid")


class Mem0OssFullRunService:
    """Application service whose configured ports are the only proof authority."""

    __slots__ = (
        "_admission",
        "_cleanup_port",
        "_manifest_port",
        "_manifest_units",
        "_operations",
        "_receipt_port",
        "_seal",
        "_sealed_items",
        "_state",
        "_storage_port",
        "_terminal_cleanup",
    )

    def __init__(
        self,
        *,
        manifest_port: ManifestAuthorityVerificationPort,
        receipt_port: RuntimeReceiptVerificationPort,
        storage_port: StorageVerificationPort,
        cleanup_port: CleanupVerificationPort,
    ) -> None:
        self._manifest_port = manifest_port
        self._receipt_port = receipt_port
        self._storage_port = storage_port
        self._cleanup_port = cleanup_port
        self._state = Mem0OssFullRunState.UNBOUND
        self._admission: Mem0OssFullRunAdmission | None = None
        self._manifest_units: tuple[Mem0OssManifestUnit, ...] = ()
        self._operations: dict[int, _Operation] = {}
        self._seal: Mem0OssRunSeal | None = None
        self._sealed_items: tuple[Mem0OssOperationEvidence, ...] = ()
        self._terminal_cleanup: Mem0OssTerminalCleanupEvidence | None = None

    @property
    def state(self) -> Mem0OssFullRunState:
        return self._state

    @property
    def admission(self) -> Mem0OssFullRunAdmission:
        if self._admission is None:
            raise Mem0OssFullRunError("mem0_v5_run_unbound")
        return self._admission

    @property
    def seal_evidence(self) -> Mem0OssRunSeal:
        if self._seal is None:
            raise Mem0OssFullRunError("mem0_v5_run_not_sealed")
        return self._seal

    @property
    def terminal_cleanup_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        if self._terminal_cleanup is None:
            raise Mem0OssFullRunError("mem0_v5_terminal_cleanup_not_available")
        return self._terminal_cleanup

    @property
    def terminal_cleanup_commitment_sha256(self) -> str:
        return self.terminal_cleanup_evidence.commitment_sha256

    def admit(
        self, request: Mem0OssAdmissionRequest, *, manifest_authority_payload: object
    ) -> None:
        if self._state is not Mem0OssFullRunState.UNBOUND:
            raise Mem0OssFullRunError("mem0_v5_admission_rebind_forbidden")
        if type(request) is not Mem0OssAdmissionRequest:
            raise Mem0OssFullRunError("mem0_v5_admission_request_invalid")
        try:
            result = self._manifest_port.verify(payload=manifest_authority_payload)
        except Exception:
            raise Mem0OssFullRunError("mem0_v5_manifest_verification_failed") from None
        witness = self._manifest_witness(result)
        if len(witness.result.units) != request.expected_operation_count:
            raise Mem0OssFullRunError("mem0_v5_manifest_count_mismatch")
        self._manifest_units = witness.result.units
        self._admission = Mem0OssFullRunAdmission(
            request=request,
            ingestion_manifest_sha256=witness.result.ingestion_manifest_sha256,
            ingestion_root_sha256=witness.result.ingestion_root_sha256,
            ingestion_unit_count=len(witness.result.units),
        )
        self._state = Mem0OssFullRunState.ADMITTED

    def activate(self, *, admission_commitment_sha256: str) -> None:
        if self._state is not Mem0OssFullRunState.ADMITTED:
            raise Mem0OssFullRunError("mem0_v5_activate_state_invalid")
        if admission_commitment_sha256 != self.admission.commitment_sha256:
            raise Mem0OssFullRunError("mem0_v5_admission_binding_mismatch")
        self._state = Mem0OssFullRunState.ACTIVE

    def reserve(self, *, unit_index: int) -> str:
        self._require_active()
        if type(unit_index) is not int or not 0 <= unit_index < len(self._manifest_units):
            raise Mem0OssFullRunError("mem0_v5_operation_reservation_invalid")
        if unit_index in self._operations:
            raise Mem0OssFullRunError("mem0_v5_operation_duplicate")
        unit = self._manifest_units[unit_index]
        operation_id_sha256 = canonical_sha256(
            {
                "admission_commitment_sha256": self.admission.commitment_sha256,
                "unit_index": unit_index,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )
        self._operations[unit_index] = _Operation(operation_id_sha256, unit_index, unit)
        return operation_id_sha256

    def record_dispatched(self, *, unit_index: int) -> None:
        operation = self._operation(unit_index, require_active=True)
        if operation.state is not Mem0OssOperationState.RESERVED:
            raise Mem0OssFullRunError("mem0_v5_dispatch_state_invalid")
        operation.state = Mem0OssOperationState.DISPATCHED

    def verify_dispatch_receipt(self, *, unit_index: int, receipt_payload: object) -> None:
        operation = self._operation(unit_index, require_active=True)
        if operation.state is not Mem0OssOperationState.DISPATCHED:
            raise Mem0OssFullRunError("mem0_v5_receipt_state_invalid")
        self._verify_and_apply_receipt(operation, receipt_payload, readback_only=False)

    def recover_after_crash(self) -> tuple[int, ...]:
        if self._state is not Mem0OssFullRunState.ACTIVE:
            raise Mem0OssFullRunError("mem0_v5_recovery_state_invalid")
        resumable: list[int] = []
        for unit_index, operation in sorted(self._operations.items()):
            if operation.state is Mem0OssOperationState.RESERVED:
                resumable.append(unit_index)
            elif operation.state is Mem0OssOperationState.DISPATCHED:
                operation.state = Mem0OssOperationState.RECONCILIATION_REQUIRED
        if any(
            operation.state is Mem0OssOperationState.RECONCILIATION_REQUIRED
            for operation in self._operations.values()
        ):
            self._state = Mem0OssFullRunState.RECONCILIATION_REQUIRED
        return tuple(resumable)

    def operation_recovery_states(self) -> tuple[Mem0OssOperationRecoveryState, ...]:
        """Expose stage and trusted storage identity, never private unit content."""

        return operation_recovery_states(self._state, self._operations)

    def reconcile_receipt_readback(self, *, unit_index: int, receipt_payload: object) -> None:
        if self._state is not Mem0OssFullRunState.RECONCILIATION_REQUIRED:
            raise Mem0OssFullRunError("mem0_v5_reconciliation_state_invalid")
        operation = self._operation(unit_index, require_active=False)
        if operation.state is not Mem0OssOperationState.RECONCILIATION_REQUIRED:
            raise Mem0OssFullRunError("mem0_v5_reconciliation_operation_invalid")
        self._verify_and_apply_receipt(operation, receipt_payload, readback_only=True)
        if not any(
            item.state is Mem0OssOperationState.RECONCILIATION_REQUIRED
            for item in self._operations.values()
        ):
            self._state = Mem0OssFullRunState.ACTIVE

    def verify_storage(self, *, unit_index: int, storage_payload: object) -> None:
        operation = self._operation(unit_index, require_active=True)
        if operation.state is not Mem0OssOperationState.RECEIPT_VERIFIED:
            raise Mem0OssFullRunError("mem0_v5_storage_state_invalid")
        context = StorageVerificationContext(
            admission_commitment_sha256=self.admission.commitment_sha256,
            operation_id_sha256=operation.operation_id_sha256,
            unit_identity_sha256=operation.unit.unit_identity_sha256,
            unit_sha256=operation.unit.unit_sha256,
            route_sha256=self.admission.request.route_sha256,
            scope_sha256=operation.unit.scope_sha256,
            provider_receipt_sha256=str(operation.provider_receipt_sha256),
        )
        try:
            result = self._storage_port.verify(payload=storage_payload, context=context)
        except Exception:
            raise Mem0OssFullRunError("mem0_v5_storage_verification_failed") from None
        witness = self._storage_witness(result, context)
        operation.stored_identity_sha256 = witness.result.stored_identity_sha256
        operation.stored_record_count = witness.result.stored_record_count
        operation.state = Mem0OssOperationState.STORAGE_VERIFIED

    def commit(self, *, unit_index: int) -> str:
        operation = self._operation(unit_index, require_active=True)
        if operation.state is not Mem0OssOperationState.STORAGE_VERIFIED:
            raise Mem0OssFullRunError("mem0_v5_commit_state_invalid")
        operation.commitment_sha256 = canonical_sha256(self._operation_payload(operation))
        operation.state = Mem0OssOperationState.COMMITTED
        return operation.commitment_sha256

    def seal(self) -> Mem0OssRunSeal:
        self._require_active()
        expected = self.admission.request.expected_operation_count
        if set(self._operations) != set(range(expected)) or any(
            operation.state is not Mem0OssOperationState.COMMITTED
            for operation in self._operations.values()
        ):
            raise Mem0OssFullRunError("mem0_v5_seal_operation_count_mismatch")
        items = tuple(
            self._operation_evidence(self._operations[index]) for index in range(expected)
        )
        operation_root_sha256 = operation_root(items)
        self._seal = Mem0OssRunSeal(
            admission_commitment_sha256=self.admission.commitment_sha256,
            operation_count=expected,
            ingestion_root_sha256=self.admission.ingestion_root_sha256,
            operation_root_sha256=operation_root_sha256,
            provider_observed_extraction_calls=sum(item.extraction_calls for item in items),
            provider_observed_request_tokens=sum(item.request_tokens for item in items),
            provider_observed_response_tokens=sum(item.response_tokens for item in items),
        )
        if self._seal.provider_observed_extraction_calls != expected:
            raise Mem0OssFullRunError("mem0_v5_seal_extraction_count_mismatch")
        self._sealed_items = items
        self._state = Mem0OssFullRunState.SEALED
        return self._seal

    def sealed_evidence_pages(self, *, page_size: int) -> tuple[Mem0OssEvidencePage, ...]:
        if self._state not in {
            Mem0OssFullRunState.SEALED,
            Mem0OssFullRunState.DELETING,
            Mem0OssFullRunState.DELETED,
        }:
            raise Mem0OssFullRunError("mem0_v5_evidence_requires_sealed_snapshot")
        if type(page_size) is not int or not 1 <= page_size <= MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE:
            raise Mem0OssFullRunError("mem0_v5_evidence_page_size_invalid")
        chunks = [
            self._sealed_items[start : start + page_size]
            for start in range(0, len(self._sealed_items), page_size)
        ]
        pages: list[Mem0OssEvidencePage] = []
        previous = MEM0_OSS_EMPTY_ROOT_SHA256
        for page_index, items in enumerate(chunks):
            start = page_index * page_size
            base = {
                "seal_commitment_sha256": self.seal_evidence.commitment_sha256,
                "operation_root_sha256": self.seal_evidence.operation_root_sha256,
                "page_index": page_index,
                "total_pages": len(chunks),
                "start_unit_index": start,
                "end_unit_index_exclusive": start + len(items),
                "previous_page_commitment_sha256": previous,
                "items": [item.payload() for item in items],
            }
            page = Mem0OssEvidencePage(
                seal_commitment_sha256=self.seal_evidence.commitment_sha256,
                operation_root_sha256=self.seal_evidence.operation_root_sha256,
                page_index=page_index,
                total_pages=len(chunks),
                start_unit_index=start,
                end_unit_index_exclusive=start + len(items),
                previous_page_commitment_sha256=previous,
                items=items,
                page_commitment_sha256=canonical_sha256(base),
            )
            pages.append(page)
            previous = page.page_commitment_sha256
        return tuple(pages)

    def begin_delete(self) -> None:
        if self._state is not Mem0OssFullRunState.SEALED:
            raise Mem0OssFullRunError("mem0_v5_delete_state_invalid")
        self._state = Mem0OssFullRunState.DELETING

    def finish_delete(self, *, cleanup_payload: object) -> None:
        if self._state is not Mem0OssFullRunState.DELETING:
            raise Mem0OssFullRunError("mem0_v5_cleanup_state_invalid")
        witness = self._verified_cleanup(cleanup_payload, aborting=False)
        if (
            witness.result.deleted_operation_count
            != self.admission.request.expected_operation_count
        ):
            raise Mem0OssFullRunError("mem0_v5_cleanup_count_mismatch")
        self._terminal_cleanup = self._terminal_evidence(
            witness,
            terminal_state=Mem0OssFullRunState.DELETED,
        )
        self._state = Mem0OssFullRunState.DELETED

    def begin_abort(self) -> None:
        if self._state not in {
            Mem0OssFullRunState.ACTIVE,
            Mem0OssFullRunState.RECONCILIATION_REQUIRED,
            Mem0OssFullRunState.FAILED,
        }:
            raise Mem0OssFullRunError("mem0_v5_abort_state_invalid")
        self._state = Mem0OssFullRunState.ABORTING

    def finish_abort(self, *, cleanup_payload: object) -> None:
        if self._state is not Mem0OssFullRunState.ABORTING:
            raise Mem0OssFullRunError("mem0_v5_abort_cleanup_state_invalid")
        witness = self._verified_cleanup(cleanup_payload, aborting=True)
        if witness.result.deleted_operation_count > self.admission.request.expected_operation_count:
            raise Mem0OssFullRunError("mem0_v5_cleanup_count_mismatch")
        self._terminal_cleanup = self._terminal_evidence(
            witness,
            terminal_state=Mem0OssFullRunState.ABORTED,
        )
        self._state = Mem0OssFullRunState.ABORTED

    def cleanup_verification_context(self, *, aborting: bool) -> CleanupVerificationContext:
        """Return the sole server-owned cleanup tuple used by request and verifier."""

        expected_state = Mem0OssFullRunState.ABORTING if aborting else Mem0OssFullRunState.DELETING
        if type(aborting) is not bool or self._state is not expected_state:
            raise Mem0OssFullRunError("mem0_v5_cleanup_context_state_invalid")
        seal = self._seal
        return CleanupVerificationContext(
            admission_commitment_sha256=self.admission.commitment_sha256,
            seal_commitment_sha256=seal.commitment_sha256 if seal is not None else None,
            operation_root_sha256=seal.operation_root_sha256 if seal is not None else None,
            operation_inventory_root_sha256=self._operation_inventory_root(),
            expected_operation_count=self.admission.request.expected_operation_count,
            aborting=aborting,
        )

    def terminal_basis(self, *, aborting: bool) -> Mem0OssTerminalBasis:
        context = self.cleanup_verification_context(aborting=aborting)
        return Mem0OssTerminalBasis(
            terminal_state=(
                Mem0OssFullRunState.ABORTED.value if aborting else Mem0OssFullRunState.DELETED.value
            ),
            cleanup_context=context,
            provider_observed_extraction_calls=sum(
                operation.extraction_calls for operation in self._operations.values()
            ),
            provider_observed_request_tokens=sum(
                operation.request_tokens for operation in self._operations.values()
            ),
            provider_observed_response_tokens=sum(
                operation.response_tokens for operation in self._operations.values()
            ),
            failed_receipts=tuple(
                self._failed_receipt_evidence(self._operations[index])
                for index in sorted(self._operations)
                if self._operations[index].state is Mem0OssOperationState.FAILED
            ),
        )

    def verify_cleanup_payload(
        self, *, payload: object, context: CleanupVerificationContext
    ) -> CleanupVerificationResult:
        """Verify a replayed cleanup receipt against a durable server-owned context."""

        if (
            type(context) is not CleanupVerificationContext
            or context.admission_commitment_sha256 != self.admission.commitment_sha256
        ):
            raise Mem0OssFullRunError("mem0_v5_cleanup_binding_mismatch")
        return verify_cleanup_result(port=self._cleanup_port, payload=payload, context=context)

    def _manifest_witness(self, result: object) -> _ManifestWitness:
        if type(result) is not ManifestAuthorityResult:
            raise Mem0OssFullRunError("mem0_v5_manifest_authority_result_invalid")
        units = result.units
        if result.ingestion_root_sha256 != manifest_root_sha256(units):
            raise Mem0OssFullRunError("mem0_v5_manifest_root_mismatch")
        identities = [unit.unit_identity_sha256 for unit in units]
        # Exact source content may legitimately repeat in different official turns.
        # Scope-bound unit identities, not content hashes, define operation uniqueness.
        if len(set(identities)) != len(identities):
            raise Mem0OssFullRunError("mem0_v5_manifest_duplicate_unit_identity")
        return _ManifestWitness(result, _WITNESS_TOKEN)

    def _verify_and_apply_receipt(
        self, operation: _Operation, payload: object, *, readback_only: bool
    ) -> None:
        context = RuntimeReceiptVerificationContext(
            admission_commitment_sha256=self.admission.commitment_sha256,
            operation_id_sha256=operation.operation_id_sha256,
            unit_identity_sha256=operation.unit.unit_identity_sha256,
            unit_sha256=operation.unit.unit_sha256,
            route_sha256=self.admission.request.route_sha256,
            scope_sha256=operation.unit.scope_sha256,
            readback_only=readback_only,
        )
        if readback_only:
            try:
                result = self._receipt_port.verify_status_readback(
                    payload=payload,
                    context=context,
                )
            except Exception:
                raise Mem0OssFullRunError("mem0_v5_receipt_readback_failed") from None
        else:
            try:
                result = self._receipt_port.verify_dispatch_receipt(
                    payload=payload,
                    context=context,
                )
            except Exception:
                raise Mem0OssFullRunError("mem0_v5_receipt_verification_failed") from None
        witness = self._receipt_witness(result, context)
        operation.provider_receipt_sha256 = witness.result.provider_receipt_sha256
        operation.disposition = witness.result.disposition
        operation.extraction_calls = witness.result.extraction_calls
        operation.retry_count = witness.result.retry_count
        operation.request_tokens = witness.result.request_tokens
        operation.response_tokens = witness.result.response_tokens
        if witness.result.disposition is not Mem0OssReceiptDisposition.COMPLETED:
            operation.state = Mem0OssOperationState.FAILED
            self._state = Mem0OssFullRunState.FAILED
            raise Mem0OssFullRunError("mem0_v5_receipt_disposition_not_successful")
        operation.state = Mem0OssOperationState.RECEIPT_VERIFIED

    @staticmethod
    def _receipt_witness(
        result: object, context: RuntimeReceiptVerificationContext
    ) -> _ReceiptWitness:
        if type(result) is not RuntimeReceiptVerificationResult:
            raise Mem0OssFullRunError("mem0_v5_receipt_result_invalid")
        bindings = (
            "admission_commitment_sha256",
            "operation_id_sha256",
            "unit_identity_sha256",
            "unit_sha256",
            "route_sha256",
            "scope_sha256",
        )
        if any(getattr(result, field) != getattr(context, field) for field in bindings):
            raise Mem0OssFullRunError("mem0_v5_receipt_binding_mismatch")
        return _ReceiptWitness(result, context, _WITNESS_TOKEN)

    @staticmethod
    def _storage_witness(result: object, context: StorageVerificationContext) -> _StorageWitness:
        if type(result) is not StorageVerificationResult:
            raise Mem0OssFullRunError("mem0_v5_storage_result_invalid")
        bindings = (
            "admission_commitment_sha256",
            "operation_id_sha256",
            "unit_identity_sha256",
            "unit_sha256",
            "route_sha256",
            "scope_sha256",
            "provider_receipt_sha256",
        )
        if any(getattr(result, field) != getattr(context, field) for field in bindings):
            raise Mem0OssFullRunError("mem0_v5_storage_binding_mismatch")
        return _StorageWitness(result, context, _WITNESS_TOKEN)

    def _verified_cleanup(self, payload: object, *, aborting: bool) -> _CleanupWitness:
        context = self.cleanup_verification_context(aborting=aborting)
        result = verify_cleanup_result(port=self._cleanup_port, payload=payload, context=context)
        return _CleanupWitness(result, context, _WITNESS_TOKEN)

    def _operation_inventory_root(self) -> str:
        return canonical_sha256(
            {
                "operations": [
                    {
                        **self._operation_payload(self._operations[index]),
                        "state": self._operations[index].state.value,
                        "commitment_sha256": self._operations[index].commitment_sha256,
                    }
                    for index in sorted(self._operations)
                ]
            }
        )

    def _terminal_evidence(
        self,
        witness: _CleanupWitness,
        *,
        terminal_state: Mem0OssFullRunState,
    ) -> Mem0OssTerminalCleanupEvidence:
        return build_terminal_evidence(
            basis=self.terminal_basis(
                aborting=terminal_state is Mem0OssFullRunState.ABORTED,
            ),
            result=witness.result,
        )

    @staticmethod
    def _failed_receipt_evidence(operation: _Operation) -> Mem0OssFailedReceiptEvidence:
        if operation.disposition is None or operation.provider_receipt_sha256 is None:
            raise Mem0OssFullRunError("mem0_v5_failed_receipt_evidence_invalid")
        return Mem0OssFailedReceiptEvidence(
            operation_id_sha256=operation.operation_id_sha256,
            unit_index=operation.unit_index,
            disposition=operation.disposition.value,
            provider_receipt_sha256=operation.provider_receipt_sha256,
            extraction_calls=operation.extraction_calls,
            request_tokens=operation.request_tokens,
            response_tokens=operation.response_tokens,
        )

    def _require_active(self) -> None:
        if self._state is not Mem0OssFullRunState.ACTIVE:
            raise Mem0OssFullRunError("mem0_v5_run_not_active")

    def _operation(self, unit_index: int, *, require_active: bool) -> _Operation:
        if require_active:
            self._require_active()
        if type(unit_index) is not int or unit_index not in self._operations:
            raise Mem0OssFullRunError("mem0_v5_operation_not_found")
        return self._operations[unit_index]

    @staticmethod
    def _operation_payload(operation: _Operation) -> dict[str, object]:
        return {
            "operation_id_sha256": operation.operation_id_sha256,
            "unit_index": operation.unit_index,
            "unit_identity_sha256": operation.unit.unit_identity_sha256,
            "unit_sha256": operation.unit.unit_sha256,
            "scope_sha256": operation.unit.scope_sha256,
            "provider_receipt_sha256": operation.provider_receipt_sha256,
            "disposition": (
                operation.disposition.value if operation.disposition is not None else None
            ),
            "extraction_calls": operation.extraction_calls,
            "retry_count": operation.retry_count,
            "request_tokens": operation.request_tokens,
            "response_tokens": operation.response_tokens,
            "stored_identity_sha256": operation.stored_identity_sha256,
            "stored_record_count": operation.stored_record_count,
        }

    @classmethod
    def _operation_evidence(cls, operation: _Operation) -> Mem0OssOperationEvidence:
        if (
            operation.commitment_sha256 is None
            or operation.provider_receipt_sha256 is None
            or operation.disposition is None
            or operation.stored_identity_sha256 is None
        ):
            raise Mem0OssFullRunError("mem0_v5_seal_evidence_incomplete")
        return Mem0OssOperationEvidence(
            **cls._operation_payload(operation),
            state=operation.state.value,
            commitment_sha256=operation.commitment_sha256,
        )


__all__ = [
    "Mem0OssEvidencePage",
    "Mem0OssFailedReceiptEvidence",
    "Mem0OssFullRunService",
    "Mem0OssOperationEvidence",
    "Mem0OssOperationRecoveryState",
    "Mem0OssRunSeal",
    "Mem0OssTerminalCleanupEvidence",
    "verify_mem0_oss_sealed_evidence_pages",
]
