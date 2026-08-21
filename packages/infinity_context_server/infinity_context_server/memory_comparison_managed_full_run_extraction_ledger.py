"""Verified runtime-receipt composition for the full-run extraction ledger."""

from __future__ import annotations

import hmac
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_adapters.postgres.managed_mem0_v6_sqlite_preparation import (
    SQLiteManagedMem0V6PreparationStore,
)
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
    StrictV4PreparationReceiptPort,
    authenticate_strict_v4_preparation_receipt,
    strict_v4_preparation_key_commitment,
)
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExpectedOperationPagePort,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerError,
    ManagedFullRunExtractionLedgerPort,
    ManagedFullRunExtractionReceipt,
    ManagedFullRunExtractionTerminal,
)

from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
)


def build_managed_full_run_extraction_context(
    *,
    preparation_receipt: StrictV4PreparationReceipt,
    preparation_authenticator: ProjectionReceiptAuthenticator,
    runtime_binding_commitment_sha256: str,
) -> ManagedFullRunExtractionContext:
    """Derive the ledger identity only from an authenticated strict-v4 receipt."""

    authenticate_strict_v4_preparation_receipt(
        preparation_receipt,
        authenticator=preparation_authenticator,
    )
    return ManagedFullRunExtractionContext(
        profile_id=preparation_receipt.profile_id,
        run_id_sha256=preparation_receipt.run_id_sha256,
        binding_commitment_sha256=preparation_receipt.binding_commitment_sha256,
        methodology_commitment_sha256=preparation_receipt.methodology_commitment_sha256,
        admission_commitment_sha256=preparation_receipt.admission_commitment_sha256,
        ingestion_root_sha256=preparation_receipt.ingestion_root_sha256,
        a1_terminal_commitment_sha256=(preparation_receipt.a1_authority.terminal_commitment_sha256),
        a1_manifest_context_sha256=preparation_receipt.a1_context.manifest_context_sha256,
        runtime_binding_commitment_sha256=runtime_binding_commitment_sha256,
        expected_receipt_count=preparation_receipt.a1_authority.operation_count,
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedFullRunExtractionDispatch:
    receipt_payload: object
    verification_context: RuntimeReceiptVerificationContext

    def __post_init__(self) -> None:
        if type(self.verification_context) is not RuntimeReceiptVerificationContext:
            raise ManagedFullRunExtractionLedgerError("dispatch_context_invalid")


@final
class ManagedFullRunExtractionLedgerService:
    """Translate only receipts accepted by the configured verification authority."""

    __slots__ = ("_context", "_expected_operations", "_ledger", "_receipt_verifier")

    def __init__(
        self,
        *,
        ledger: ManagedFullRunExtractionLedgerPort,
        expected_operations: ManagedFullRunExpectedOperationPagePort,
        receipt_verifier: RuntimeReceiptVerificationPort,
    ) -> None:
        if not callable(getattr(expected_operations, "read_operation_page", None)):
            raise ManagedFullRunExtractionLedgerError("expected_operations_invalid")
        if any(
            not callable(getattr(receipt_verifier, method, None))
            for method in (
                "mark_outcome_unknown",
                "verify_dispatch_receipt",
                "verify_status_readback",
            )
        ):
            raise ManagedFullRunExtractionLedgerError("receipt_verifier_invalid")
        self._ledger = ledger
        self._expected_operations = expected_operations
        self._receipt_verifier = receipt_verifier
        self._context: ManagedFullRunExtractionContext | None = None

    def begin(self, context: ManagedFullRunExtractionContext) -> None:
        if type(context) is not ManagedFullRunExtractionContext:
            raise ManagedFullRunExtractionLedgerError("context_invalid")
        self._ledger.begin(context)
        self._context = context

    def verify_dispatch_page(
        self,
        dispatches: tuple[ManagedFullRunExtractionDispatch, ...],
    ) -> None:
        self._verify_and_append(dispatches, readback=False)

    def verify_readback_page(
        self,
        dispatches: tuple[ManagedFullRunExtractionDispatch, ...],
    ) -> None:
        self._verify_and_append(dispatches, readback=True)

    def finalize(self) -> ManagedFullRunExtractionTerminal:
        self._require_context()
        return self._ledger.finalize()

    def readback(self) -> ManagedFullRunExtractionTerminal | None:
        self._require_context()
        return self._ledger.readback()

    def close(self) -> None:
        self._ledger.close()

    def _verify_and_append(
        self,
        dispatches: tuple[ManagedFullRunExtractionDispatch, ...],
        *,
        readback: bool,
    ) -> None:
        context = self._require_context()
        if (
            type(dispatches) is not tuple
            or not dispatches
            or len(dispatches) > FULL_RUN_EXTRACTION_PAGE_SIZE
        ):
            raise ManagedFullRunExtractionLedgerError("dispatch_page_invalid")
        receipts: list[ManagedFullRunExtractionReceipt] = []
        for dispatch in dispatches:
            if type(dispatch) is not ManagedFullRunExtractionDispatch:
                raise ManagedFullRunExtractionLedgerError("dispatch_page_invalid")
            verification_context = dispatch.verification_context
            if verification_context.readback_only is not readback:
                raise ManagedFullRunExtractionLedgerError("dispatch_context_invalid")
            if readback:
                result = self._receipt_verifier.verify_status_readback(
                    payload=dispatch.receipt_payload,
                    context=verification_context,
                )
            else:
                result = self._receipt_verifier.verify_dispatch_receipt(
                    payload=dispatch.receipt_payload,
                    context=verification_context,
                )
            receipts.append(
                _verified_ledger_receipt(
                    result=result,
                    verification_context=verification_context,
                    ledger_context=context,
                )
            )
        first_sequence = receipts[0].sequence
        expected = self._expected_operations.read_operation_page(
            manifest_context_sha256=context.a1_manifest_context_sha256,
            start_sequence=first_sequence,
        )
        observed = tuple(receipt.operation_id_sha256 for receipt in receipts)
        if first_sequence % FULL_RUN_EXTRACTION_PAGE_SIZE != 0 or expected != observed:
            raise ManagedFullRunExtractionLedgerError("a1_operation_page_binding_invalid")
        self._ledger.append_page(tuple(receipts))

    def _require_context(self) -> ManagedFullRunExtractionContext:
        if self._context is None:
            raise ManagedFullRunExtractionLedgerError("ledger_not_started")
        return self._context


@final
class RecoveredManagedFullRunExtractionLedger:
    """Own the authenticated A1 page authority and its durable receipt ledger."""

    __slots__ = ("_a1", "_closed", "_service")

    def __init__(
        self,
        *,
        a1: SQLiteManagedMem0V6PreparationStore,
        service: ManagedFullRunExtractionLedgerService,
    ) -> None:
        self._a1 = a1
        self._service = service
        self._closed = False

    def verify_dispatch_page(
        self, dispatches: tuple[ManagedFullRunExtractionDispatch, ...]
    ) -> None:
        self._require_open()
        self._service.verify_dispatch_page(dispatches)

    def verify_readback_page(
        self, dispatches: tuple[ManagedFullRunExtractionDispatch, ...]
    ) -> None:
        self._require_open()
        self._service.verify_readback_page(dispatches)

    def finalize(self) -> ManagedFullRunExtractionTerminal:
        self._require_open()
        return self._service.finalize()

    def readback(self) -> ManagedFullRunExtractionTerminal | None:
        self._require_open()
        return self._service.readback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        error: BaseException | None = None
        try:
            self._service.close()
        except BaseException as exc:
            error = exc
        try:
            self._a1.close()
        except BaseException:
            if error is None:
                raise
        if error is not None:
            raise error

    def __enter__(self) -> RecoveredManagedFullRunExtractionLedger:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise ManagedFullRunExtractionLedgerError("ledger_closed")


async def recover_managed_full_run_extraction_ledger(
    *,
    receipt_store: StrictV4PreparationReceiptPort,
    registration_port: ContextAuthorityRegistrationPort,
    preparation_authenticator: ProjectionReceiptAuthenticator,
    key_identity_authority: StrictV4PreparationKeyIdentityPort,
    ledger_path: str | Path,
    ledger_authentication_key: bytes,
    runtime_binding_commitment_sha256: str,
    receipt_verifier: RuntimeReceiptVerificationPort,
) -> RecoveredManagedFullRunExtractionLedger:
    """Recover every strict-v4 artifact before accepting any runtime receipt."""

    receipt = await recover_strict_v4_full_run(
        receipt_store=receipt_store,
        registration_port=registration_port,
        authenticator=preparation_authenticator,
        key_identity_authority=key_identity_authority,
    )
    a1_key = key_identity_authority.resolve(purpose="a1", key_id=receipt.a1_key_id)
    if type(a1_key) is not bytes or len(a1_key) < 32:
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    observed_key_commitment = strict_v4_preparation_key_commitment(
        a1_key,
        purpose="a1",
        key_id=receipt.a1_key_id,
        artifact_context=f"{receipt.run_id_sha256}:{Path(receipt.a1_path)}",
    )
    if not hmac.compare_digest(observed_key_commitment, receipt.a1_key_commitment_sha256):
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    a1 = SQLiteManagedMem0V6PreparationStore.open(
        receipt.a1_path,
        authentication_key=a1_key,
    )
    ledger: SQLiteManagedFullRunExtractionLedger | None = None
    try:
        ledger = SQLiteManagedFullRunExtractionLedger.open_or_create(
            ledger_path,
            authentication_key=ledger_authentication_key,
        )
        service = ManagedFullRunExtractionLedgerService(
            ledger=ledger,
            expected_operations=a1,
            receipt_verifier=receipt_verifier,
        )
        service.begin(
            build_managed_full_run_extraction_context(
                preparation_receipt=receipt,
                preparation_authenticator=preparation_authenticator,
                runtime_binding_commitment_sha256=runtime_binding_commitment_sha256,
            )
        )
        return RecoveredManagedFullRunExtractionLedger(a1=a1, service=service)
    except BaseException:
        if ledger is not None:
            with suppress(BaseException):
                ledger.close()
        with suppress(BaseException):
            a1.close()
        raise


def _verified_ledger_receipt(
    *,
    result: RuntimeReceiptVerificationResult,
    verification_context: RuntimeReceiptVerificationContext,
    ledger_context: ManagedFullRunExtractionContext,
) -> ManagedFullRunExtractionReceipt:
    if (
        type(result) is not RuntimeReceiptVerificationResult
        or result.admission_commitment_sha256 != ledger_context.admission_commitment_sha256
        or result.runtime_binding_commitment_sha256
        != ledger_context.runtime_binding_commitment_sha256
        or result.admission_commitment_sha256 != verification_context.admission_commitment_sha256
        or result.operation_id_sha256 != verification_context.operation_id_sha256
        or result.unit_identity_sha256 != verification_context.unit_identity_sha256
        or result.unit_sha256 != verification_context.unit_sha256
        or result.route_sha256 != verification_context.route_sha256
        or result.scope_sha256 != verification_context.scope_sha256
        or result.disposition is not Mem0OssReceiptDisposition.COMPLETED
        or result.extraction_calls != 1
        or result.retry_count != 0
    ):
        raise ManagedFullRunExtractionLedgerError("verified_receipt_binding_invalid")
    return ManagedFullRunExtractionReceipt(
        sequence=result.sequence,
        operation_id_sha256=result.operation_id_sha256,
        unit_identity_sha256=result.unit_identity_sha256,
        request_body_sha256=result.request_body_sha256,
        output_text_sha256=result.output_text_sha256,
        provider_receipt_sha256=result.provider_receipt_sha256,
        runtime_binding_commitment_sha256=result.runtime_binding_commitment_sha256,
        prompt_tokens=result.request_tokens,
        completion_tokens=result.response_tokens,
        total_tokens=result.request_tokens + result.response_tokens,
    )


__all__ = (
    "ManagedFullRunExtractionDispatch",
    "ManagedFullRunExtractionLedgerService",
    "RecoveredManagedFullRunExtractionLedger",
    "build_managed_full_run_extraction_context",
    "recover_managed_full_run_extraction_ledger",
)
