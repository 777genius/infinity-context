from __future__ import annotations

import gc
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_extraction_projection as extraction,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    create_managed_mem0_v5_single_dispatch_guard,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedMem0V5OperationReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as run_composition,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    OpenedPublishableExtractionStores,
    PublishableExtractionAdvancePhase,
    PublishableExtractionWorkerError,
)
from infinity_context_server.processes.publishable_full_extraction_managed_mem0_v5_http import (
    PublishableManagedMem0V5HttpAdapter,
    PublishableManagedMem0V5HttpAdapterError,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableFullExtractionWorker,
)
from infinity_context_server.resumable_operation_journal.crypto import (
    HmacSha256OperationJournalSigner,
)
from infinity_context_server.resumable_operation_journal.domain import OperationJournalError
from infinity_context_server.resumable_operation_journal.service import (
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal
from publishable_full_extraction_managed_mem0_v5_test_support import (
    RecordingHttpTransport,
    SyntheticRun,
    build_lane,
    build_locomo_run,
    idempotency_key,
    scaled_receipt_authority,
    sha,
)

_ExactManifestPolicy = run_composition._ExactManifestPolicy
_ExactOperationReceiptIssuer = run_composition._ExactOperationReceiptIssuer


@pytest.fixture(scope="module")
def locomo_run() -> SyntheticRun:
    patch = pytest.MonkeyPatch()
    prompt = extraction._system_prompt()
    patch.setattr(extraction, "_system_prompt", lambda: prompt)
    try:
        yield build_locomo_run()
    finally:
        patch.undo()


def _adapter(
    run: SyntheticRun,
    transport: RecordingHttpTransport,
) -> PublishableManagedMem0V5HttpAdapter:
    return PublishableManagedMem0V5HttpAdapter(
        authority=run.authority,
        manifest=run.manifest,
        admission=run.admission,
        lane=build_lane(run, transport),
        expected_runtime=run.expected_runtime,
        runtime_attestation=run.runtime_attestation,
        runtime_target_identity_sha256=run.target_identity_sha256,
    )


def test_exact_dispatch_and_status_use_auth_and_separate_idempotency(
    locomo_run: SyntheticRun,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    adapter = _adapter(locomo_run, transport)
    command = locomo_run.command(0)

    dispatched = adapter.dispatch_once(command=command)
    status = adapter.lookup_outcome(command=command)

    assert dispatched.operation_id_sha256 == command.operation_id_sha256
    assert status.operation_id_sha256 == command.operation_id_sha256
    assert [str(item["url"]).rsplit("/", 1)[-1] for item in transport.calls] == [
        "request-binding",
        "dispatch",
        "status",
        "request-binding",
    ]
    expected_keys = (
        idempotency_key("request-binding", command.operation_id_sha256),
        idempotency_key("dispatch", command.operation_id_sha256),
        idempotency_key("status", command.operation_id_sha256),
        idempotency_key("request-binding", command.operation_id_sha256),
    )
    assert (
        tuple(
            item["headers"]["Idempotency-Key"]
            for item in transport.calls  # type: ignore[index]
        )
        == expected_keys
    )
    assert all(
        item["headers"]["Authorization"]  # type: ignore[index]
        == "Bearer publishable-test-bearer-token-value"
        for item in transport.calls
    )


def test_crosswire_and_local_projection_tamper_fail_before_dispatch(
    locomo_run: SyntheticRun,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    adapter = _adapter(locomo_run, transport)
    command = locomo_run.command(1)

    with pytest.raises(
        PublishableManagedMem0V5HttpAdapterError,
        match="publishable_mem0_v5_command_cross_wire",
    ):
        adapter.dispatch_once(command=replace(command, request_body_sha256=sha("foreign-request")))
    assert transport.calls == []

    unit = locomo_run.manifest.units[1]
    original = unit.source_messages
    object.__setattr__(
        unit,
        "source_messages",
        (replace(original[0], content="tampered-local-source"),),
    )
    try:
        with pytest.raises(
            PublishableManagedMem0V5HttpAdapterError,
            match="publishable_mem0_v5_command_cross_wire",
        ):
            adapter.dispatch_once(command=command)
    finally:
        object.__setattr__(unit, "source_messages", original)
    assert transport.calls == []


def test_request_binding_hmac_tamper_never_reaches_dispatch(
    locomo_run: SyntheticRun,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    transport.tamper_binding_hmac = True
    adapter = _adapter(locomo_run, transport)

    with pytest.raises(
        Mem0V5HttpError,
        match="mem0_v5_http_remote_failed",
    ):
        adapter.dispatch_once(command=locomo_run.command(2))

    assert len(transport.calls) == 1
    assert str(transport.calls[0]["url"]).endswith("/v5/operations/request-binding")


def test_attestation_target_crosswire_rejected_without_http(
    locomo_run: SyntheticRun,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    with pytest.raises(
        PublishableManagedMem0V5HttpAdapterError,
        match="publishable_mem0_v5_http_lane_cross_wire",
    ):
        PublishableManagedMem0V5HttpAdapter(
            authority=locomo_run.authority,
            manifest=locomo_run.manifest,
            admission=locomo_run.admission,
            lane=build_lane(locomo_run, transport),
            expected_runtime=locomo_run.expected_runtime,
            runtime_attestation=locomo_run.runtime_attestation,
            runtime_target_identity_sha256=sha("foreign-target"),
        )
    assert transport.calls == []


def test_single_dispatch_canary_guard_is_rejected_for_full_run(
    locomo_run: SyntheticRun,
    tmp_path: Path,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    guard_root = tmp_path / "single-dispatch-guard"
    guard_root.mkdir(mode=0o700)
    lane = build_lane(
        locomo_run,
        transport,
        dispatch_guard=create_managed_mem0_v5_single_dispatch_guard(guard_root / "claim.json"),
    )

    with pytest.raises(
        PublishableManagedMem0V5HttpAdapterError,
        match="publishable_mem0_v5_http_lane_dispatch_guard_forbidden",
    ):
        PublishableManagedMem0V5HttpAdapter(
            authority=locomo_run.authority,
            manifest=locomo_run.manifest,
            admission=locomo_run.admission,
            lane=lane,
            expected_runtime=locomo_run.expected_runtime,
            runtime_attestation=locomo_run.runtime_attestation,
            runtime_target_identity_sha256=locomo_run.target_identity_sha256,
        )
    assert transport.calls == []
    assert not (guard_root / "claim.json").exists()


class _ExpectedOperations:
    def __init__(self, run: SyntheticRun) -> None:
        self._context = run.authority.ledger_context.a1_manifest_context_sha256
        self._operations = run.receipt_authority.operations

    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]:
        assert manifest_context_sha256 == self._context
        return tuple(
            item.operation_id_sha256
            for item in self._operations[start_sequence : start_sequence + 512]
        )


class _RuntimeVerifier:
    def __init__(self, run: SyntheticRun) -> None:
        self.run = run
        self.unknown: list[str] = []

    def mark_outcome_unknown(self, *, context: RuntimeReceiptVerificationContext) -> None:
        self.unknown.append(context.operation_id_sha256)

    def verify_dispatch_receipt(self, *, payload: object, context: object) -> object:
        del payload, context
        raise AssertionError("crash path must not consume a dispatch receipt")

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        del payload
        operation = self.run.receipt_authority.operations[0]
        assert context.readback_only is True
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=self.run.admission.commitment_sha256,
            operation_id_sha256=operation.operation_id_sha256,
            unit_identity_sha256=operation.unit_identity_sha256,
            unit_sha256=operation.unit_sha256,
            route_sha256=self.run.admission.request.route_sha256,
            scope_sha256=operation.scope_sha256,
            provider_receipt_sha256=sha("provider-runtime-receipt"),
            sequence=0,
            request_body_sha256=operation.request_body_sha256,
            output_text_sha256=sha("provider-output"),
            runtime_binding_commitment_sha256=(
                self.run.authority.ledger_context.runtime_binding_commitment_sha256
            ),
            disposition=Mem0OssReceiptDisposition.COMPLETED,
            extraction_calls=1,
            retry_count=0,
            request_tokens=17,
            response_tokens=5,
        )


class _CrashAfterHttpDispatch:
    def __init__(self, adapter: PublishableManagedMem0V5HttpAdapter) -> None:
        self.adapter = adapter

    def dispatch_once(self, *, command: object) -> object:
        self.adapter.dispatch_once(command=command)  # type: ignore[arg-type]
        raise RuntimeError("simulated process loss after HTTP success")

    def lookup_outcome(self, *, command: object) -> object:
        return self.adapter.lookup_outcome(command=command)  # type: ignore[arg-type]


def _open_worker(
    *,
    run: SyntheticRun,
    state_directory: Path,
    boundary: object,
    runtime_verifier: _RuntimeVerifier,
) -> PublishableFullExtractionWorker:
    state_directory.mkdir(mode=0o700, exist_ok=True)
    journal = SQLiteOperationJournal(
        state_directory / "operation-journal.sqlite3",
        private_directory=state_directory,
    )
    ledger = SQLiteManagedFullRunExtractionLedger.open_or_create(
        state_directory / "extraction-ledger.sqlite3",
        authentication_key=b"l" * 32,
    )
    receipt_authority = ManagedMem0V5OperationReceiptAuthority(
        key=b"r" * 32,
        key_id="publishable-state-machine-receipt",
        manifest=run.authority.operation_manifest,
    )
    service = ResumableOperationJournalService(
        journal=journal,
        signer=HmacSha256OperationJournalSigner(
            key_id=run.authority.journal_identity.signer_key_id,
            secret=b"j" * 32,
        ),
        manifest_policy=_ExactManifestPolicy(
            run.authority.journal_identity,
            run.authority.operation_manifest,
        ),
        receipt_verifier=receipt_authority,
        notifications=NullOperationNotification(),
    )
    stores = OpenedPublishableExtractionStores(
        journal_service=service,
        journal_store=journal,
        extraction_ledger=ledger,
        expected_operations=_ExpectedOperations(run),
        operation_receipt_issuer=_ExactOperationReceiptIssuer(receipt_authority),
        close_callbacks=(ledger.close,),
    )
    return PublishableFullExtractionWorker(
        authority=run.authority,
        stores=stores,
        boundary=boundary,  # type: ignore[arg-type]
        runtime_receipt_verifier=runtime_verifier,
    )


def test_crash_after_http_success_reconciles_by_status_without_duplicate_dispatch(
    locomo_run: SyntheticRun,
    tmp_path: Path,
) -> None:
    transport = RecordingHttpTransport(locomo_run)
    adapter = _adapter(locomo_run, transport)
    state = tmp_path / "private-state"
    first_verifier = _RuntimeVerifier(locomo_run)
    worker = _open_worker(
        run=locomo_run,
        state_directory=state,
        boundary=_CrashAfterHttpDispatch(adapter),
        runtime_verifier=first_verifier,
    )
    with pytest.raises(
        PublishableExtractionWorkerError,
        match="extraction_dispatch_outcome_unknown",
    ):
        worker.advance_one()
    worker.close()

    assert sum(str(item["url"]).endswith("/dispatch") for item in transport.calls) == 1
    assert len(first_verifier.unknown) == 1

    second_verifier = _RuntimeVerifier(locomo_run)
    reopened = _open_worker(
        run=locomo_run,
        state_directory=state,
        boundary=adapter,
        runtime_verifier=second_verifier,
    )
    blocked = reopened.advance_one()
    assert blocked.phase is PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED
    assert sum(str(item["url"]).endswith("/dispatch") for item in transport.calls) == 1

    reconciled = reopened.reconcile_one()
    assert reconciled.phase is PublishableExtractionAdvancePhase.OPERATION_COMMITTED
    assert reconciled.operation_ordinal == 0
    assert sum(str(item["url"]).endswith("/status") for item in transport.calls) == 1
    assert sum(str(item["url"]).endswith("/dispatch") for item in transport.calls) == 1
    reopened.close()


def test_operation_result_receipt_hmac_rejects_exact_field_tamper(
    locomo_run: SyntheticRun,
) -> None:
    authority = ManagedMem0V5OperationReceiptAuthority(
        key=b"r" * 32,
        key_id="publishable-result-hmac",
        manifest=locomo_run.authority.operation_manifest,
    )
    identity = locomo_run.authority.operation_manifest.operations[0]
    receipt = authority._issue_exact(
        identity=identity,
        request_commitment_sha256=sha("request-result-binding"),
        result_commitment_sha256=sha("result-binding"),
    )
    verified = authority.verify(identity=identity, receipt=receipt)
    assert verified.receipt == receipt

    with pytest.raises(
        OperationJournalError,
        match="managed_mem0_v5_receipt_authentication_failed",
    ):
        authority.verify(
            identity=identity,
            receipt=replace(receipt, result_commitment_sha256=sha("tampered-result")),
        )


@pytest.mark.parametrize("operation_count", (5_882, 124_344))
def test_runtime_receipt_authority_commitment_traversal_is_bounded(
    operation_count: int,
) -> None:
    authority = scaled_receipt_authority(operation_count)
    tracemalloc.start()
    first = run_composition._runtime_receipt_authority_commitment(authority)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(authority.operations) == operation_count
    assert len(first) == 64
    assert peak < 2 * 1024 * 1024
    last = authority.operations[-1]
    original = last.request_body_sha256
    object.__setattr__(last, "request_body_sha256", sha("tampered-runtime-request"))
    try:
        assert run_composition._runtime_receipt_authority_commitment(authority) != first
    finally:
        object.__setattr__(last, "request_body_sha256", original)
    del authority
    gc.collect()
