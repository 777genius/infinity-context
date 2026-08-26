from __future__ import annotations

from pathlib import Path

import pytest
from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerError,
)
from infinity_context_server.memory_comparison_managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionDispatch,
    ManagedFullRunExtractionLedgerService,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_FULL_RUN_MAX_OPERATIONS,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5AdmitRequest,
    Mem0V5DispatchRequest,
)

_KEY = b"k" * 32
_RUNTIME = "9" * 64
_ADMISSION = "4" * 64


def _sha(value: int) -> str:
    return f"{value:064x}"


def _ledger_context(expected: int) -> ManagedFullRunExtractionContext:
    return ManagedFullRunExtractionContext(
        profile_id="managed-mem0-v5-publishable",
        run_id_sha256=_sha(1),
        binding_commitment_sha256=_sha(2),
        methodology_commitment_sha256=_sha(3),
        admission_commitment_sha256=_ADMISSION,
        ingestion_root_sha256=_sha(5),
        a1_terminal_commitment_sha256=_sha(6),
        a1_manifest_context_sha256=_sha(8),
        runtime_binding_commitment_sha256=_RUNTIME,
        expected_receipt_count=expected,
    )


def _verification_context(
    sequence: int,
    *,
    readback: bool,
) -> RuntimeReceiptVerificationContext:
    return RuntimeReceiptVerificationContext(
        admission_commitment_sha256=_ADMISSION,
        operation_id_sha256=_sha(1_000 + sequence * 10),
        unit_identity_sha256=_sha(1_001 + sequence * 10),
        unit_sha256=_sha(1_002 + sequence * 10),
        route_sha256=_sha(20),
        scope_sha256=_sha(21),
        readback_only=readback,
    )


class _VerifiedReceiptAuthority:
    def __init__(
        self,
        *,
        runtime_binding: str = _RUNTIME,
        disposition: Mem0OssReceiptDisposition = Mem0OssReceiptDisposition.COMPLETED,
    ) -> None:
        self.runtime_binding = runtime_binding
        self.disposition = disposition
        self.dispatch_calls = 0
        self.readback_calls = 0

    def mark_outcome_unknown(
        self,
        *,
        context: RuntimeReceiptVerificationContext,
    ) -> None:
        del context

    def verify_dispatch_receipt(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        self.dispatch_calls += 1
        return self._result(payload, context)

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        self.readback_calls += 1
        return self._result(payload, context)

    def _result(
        self,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert type(payload) is dict
        sequence = int(payload["sequence"])
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha(50_000 + sequence),
            sequence=sequence,
            request_body_sha256=_sha(60_000 + sequence),
            output_text_sha256=_sha(70_000 + sequence),
            runtime_binding_commitment_sha256=self.runtime_binding,
            disposition=self.disposition,
            extraction_calls=1,
            retry_count=0,
            request_tokens=7,
            response_tokens=3,
        )


class _ExpectedOperations:
    def __init__(self, count: int, *, drift_at: int | None = None) -> None:
        self.count = count
        self.drift_at = drift_at

    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]:
        assert manifest_context_sha256 == _sha(8)
        end = min(start_sequence + 512, self.count)
        values = [
            _verification_context(sequence, readback=False).operation_id_sha256
            for sequence in range(start_sequence, end)
        ]
        if self.drift_at is not None and start_sequence <= self.drift_at < end:
            values[self.drift_at - start_sequence] = _sha(999_999)
        return tuple(values)


def _dispatch_page(
    start: int,
    count: int,
    *,
    readback: bool,
) -> tuple[ManagedFullRunExtractionDispatch, ...]:
    return tuple(
        ManagedFullRunExtractionDispatch(
            receipt_payload={"sequence": sequence},
            verification_context=_verification_context(
                sequence,
                readback=readback,
            ),
        )
        for sequence in range(start, start + count)
    )


def test_verified_runtime_pages_resume_and_finalize_exact_ledger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "verified-full-run.sqlite3"
    authority = _VerifiedReceiptAuthority()
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    service = ManagedFullRunExtractionLedgerService(
        ledger=ledger,
        expected_operations=_ExpectedOperations(513),
        receipt_verifier=authority,
    )
    context = _ledger_context(513)
    service.begin(context)
    service.verify_dispatch_page(_dispatch_page(0, 512, readback=False))
    service.close()

    resumed_authority = _VerifiedReceiptAuthority()
    resumed_ledger = SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=_KEY)
    resumed = ManagedFullRunExtractionLedgerService(
        ledger=resumed_ledger,
        expected_operations=_ExpectedOperations(513),
        receipt_verifier=resumed_authority,
    )
    resumed.begin(context)
    resumed.verify_readback_page(_dispatch_page(0, 512, readback=True))
    resumed.verify_dispatch_page(_dispatch_page(512, 1, readback=False))
    terminal = resumed.finalize()
    assert terminal.receipt_count == 513
    assert terminal.page_count == 2
    assert terminal.prompt_tokens == 513 * 7
    assert terminal.completion_tokens == 513 * 3
    assert terminal.total_tokens == 513 * 10
    assert authority.dispatch_calls == 512
    assert resumed_authority.readback_calls == 512
    assert resumed_authority.dispatch_calls == 1
    resumed.close()


@pytest.mark.parametrize(
    ("runtime_binding", "disposition"),
    [
        ("8" * 64, Mem0OssReceiptDisposition.COMPLETED),
        (_RUNTIME, Mem0OssReceiptDisposition.PROVIDER_FAILED),
    ],
)
def test_untrusted_or_failed_verification_result_never_reaches_ledger(
    tmp_path: Path,
    runtime_binding: str,
    disposition: Mem0OssReceiptDisposition,
) -> None:
    ledger = SQLiteManagedFullRunExtractionLedger.create(
        tmp_path / f"reject-{runtime_binding[0]}-{disposition.value}.sqlite3",
        authentication_key=_KEY,
    )
    service = ManagedFullRunExtractionLedgerService(
        ledger=ledger,
        expected_operations=_ExpectedOperations(1),
        receipt_verifier=_VerifiedReceiptAuthority(
            runtime_binding=runtime_binding,
            disposition=disposition,
        ),
    )
    service.begin(_ledger_context(1))
    with pytest.raises(
        ManagedFullRunExtractionLedgerError,
        match="verified_receipt_binding_invalid",
    ):
        service.verify_dispatch_page(_dispatch_page(0, 1, readback=False))
    assert service.readback() is None
    service.close()


def test_a1_operation_page_drift_is_rejected_before_ledger_write(
    tmp_path: Path,
) -> None:
    ledger = SQLiteManagedFullRunExtractionLedger.create(
        tmp_path / "a1-drift.sqlite3",
        authentication_key=_KEY,
    )
    service = ManagedFullRunExtractionLedgerService(
        ledger=ledger,
        expected_operations=_ExpectedOperations(1, drift_at=0),
        receipt_verifier=_VerifiedReceiptAuthority(),
    )
    service.begin(_ledger_context(1))
    with pytest.raises(
        ManagedFullRunExtractionLedgerError,
        match="a1_operation_page_binding_invalid",
    ):
        service.verify_dispatch_page(_dispatch_page(0, 1, readback=False))
    assert service.readback() is None
    service.close()


def test_http_and_core_operation_capacity_accept_official_longmem_scale() -> None:
    assert MEM0_OSS_FULL_RUN_MAX_OPERATIONS == 124_344
    Mem0V5AdmitRequest(
        admission_commitment_sha256=_sha(1),
        ingestion_manifest_sha256=_sha(2),
        ingestion_root_sha256=_sha(3),
        expected_operation_count=124_344,
        route_sha256=_sha(4),
        idempotency_key=_sha(5),
    )
    Mem0V5DispatchRequest(
        admission_commitment_sha256=_sha(1),
        operation_id_sha256=_sha(2),
        unit_identity_sha256=_sha(3),
        unit_sha256=_sha(4),
        scope_sha256=_sha(5),
        request_body_sha256=_sha(6),
        sequence=124_343,
        idempotency_key=_sha(7),
    )
