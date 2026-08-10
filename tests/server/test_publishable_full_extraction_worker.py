"""Provider-free recovery and ordering tests for the full extraction worker."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionCheckpoint,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerError,
    ManagedFullRunExtractionReceipt,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.processes.publishable_full_extraction_composition import (
    open_publishable_full_extraction_worker,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    MANAGED_MEM0_EXTRACTION_NAMESPACE,
    MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
    OpenedPublishableExtractionStores,
    PublishableExtractionAdvancePhase,
    PublishableExtractionCommand,
    PublishableExtractionRunAuthority,
    PublishableExtractionWorkerError,
    PublishableFullExtractionWorker,
)
from infinity_context_server.resumable_operation_journal import (
    HmacSha256OperationJournalSigner,
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationReceipt,
    OperationRunIdentity,
    ResumableOperationJournalService,
    RetryDisposition,
    VerifiedOperationReceipt,
)
from infinity_context_server.resumable_operation_journal.service import (
    AllowAllOperationManifestPolicy,
    NullOperationNotification,
)
from infinity_context_server.resumable_operation_journal.sqlite import (
    SQLiteOperationJournal,
)

_SIGNER_KEY_ID = "publishable-extraction-test-signer"
_SIGNER_SECRET = b"publishable-extraction-test-signer-secret"


def _sha(value: object) -> str:
    return hashlib.sha256(str(value).encode("ascii")).hexdigest()


def _authority(
    count: int,
    *,
    run_id: str = "publishable-extraction-test-run",
) -> PublishableExtractionRunAuthority:
    admission = _sha(f"{run_id}:admission")
    observed: list[Mem0V5ObservedExtractionOperationAuthority] = []
    logical: list[LogicalOperationIdentity] = []
    for ordinal in range(count):
        unit_identity = _sha(f"{run_id}:unit-identity:{ordinal}")
        operation_id = canonical_sha256(
            {
                "admission_commitment_sha256": admission,
                "unit_index": ordinal,
                "unit_identity_sha256": unit_identity,
            }
        )
        operation = Mem0V5ObservedExtractionOperationAuthority(
            operation_id_sha256=operation_id,
            unit_identity_sha256=unit_identity,
            unit_sha256=_sha(f"{run_id}:unit:{ordinal}"),
            scope_sha256=_sha(f"{run_id}:scope:{ordinal}"),
            sequence=ordinal,
            request_body_sha256=_sha(f"{run_id}:request:{ordinal}"),
        )
        observed.append(operation)
        logical.append(
            LogicalOperationIdentity(
                run_id=run_id,
                operation_key=operation_id,
                operation_kind=MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
                ordinal=ordinal,
                authority_commitment_sha256=_sha(f"{run_id}:a1:{ordinal}"),
                retry_disposition=RetryDisposition.QUARANTINE_UNKNOWN,
            )
        )
    runtime = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission,
        model="test-model",
        reasoning_effort="test-effort",
        service_tier="test-tier",
        base_instructions_sha256=_sha("instructions"),
        runtime_source_sha256=_sha("runtime-source"),
        route_binding_sha256=_sha("route"),
        account_binding_hmac_sha256=_sha("account"),
        node_executable_path="/provider-free/test-node",
        node_executable_sha256=_sha("node"),
        response_format_type="json_schema",
        response_format_sha256=_sha("format"),
        response_schema_sha256=_sha("schema"),
        operations=tuple(observed),
    )
    manifest = OperationManifest(tuple(logical))
    journal_identity = OperationRunIdentity(
        run_id=run_id,
        operation_namespace=MANAGED_MEM0_EXTRACTION_NAMESPACE,
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=_sha("journal-policy"),
        signer_key_id=_SIGNER_KEY_ID,
        expected_operation_count=count,
    )
    context = ManagedFullRunExtractionContext(
        profile_id="provider-free-synthetic",
        run_id_sha256=hashlib.sha256(run_id.encode()).hexdigest(),
        binding_commitment_sha256=_sha(f"{run_id}:binding"),
        methodology_commitment_sha256=_sha("shared-methodology"),
        admission_commitment_sha256=admission,
        ingestion_root_sha256=_sha(f"{run_id}:ingestion"),
        a1_terminal_commitment_sha256=_sha(f"{run_id}:a1-terminal"),
        a1_manifest_context_sha256=_sha(f"{run_id}:a1-context"),
        runtime_binding_commitment_sha256=_sha("shared-runtime-binding"),
        expected_receipt_count=count,
    )
    return PublishableExtractionRunAuthority(
        journal_identity=journal_identity,
        operation_manifest=manifest,
        runtime_receipt_authority=runtime,
        ledger_context=context,
        preparation_receipt_sha256=_sha(f"{run_id}:preparation"),
        dataset_sha256=_sha(f"{run_id}:dataset"),
        a2_terminal_commitment_sha256=_sha(f"{run_id}:a2-terminal"),
    )


@dataclass
class _ExpectedOperations:
    authority: PublishableExtractionRunAuthority
    drift_at: int | None = None
    starts: list[int] = field(default_factory=list)
    page_lengths: list[int] = field(default_factory=list)

    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]:
        assert manifest_context_sha256 == self.authority.ledger_context.a1_manifest_context_sha256
        operations = self.authority.runtime_receipt_authority.operations
        end = min(start_sequence + FULL_RUN_EXTRACTION_PAGE_SIZE, len(operations))
        values = [operation.operation_id_sha256 for operation in operations[start_sequence:end]]
        if self.drift_at is not None and start_sequence <= self.drift_at < end:
            values[self.drift_at - start_sequence] = _sha("cross-wired-a1-operation")
        self.starts.append(start_sequence)
        self.page_lengths.append(len(values))
        return tuple(values)


@dataclass
class _RecordingLedger:
    context: ManagedFullRunExtractionContext | None = None
    receipts: list[ManagedFullRunExtractionReceipt] = field(default_factory=list)
    pages: list[tuple[ManagedFullRunExtractionReceipt, ...]] = field(default_factory=list)
    terminal: ManagedFullRunExtractionTerminal | None = None
    checkpoint_read_count: int = 0
    append_page_count: int = 0
    max_append_page_size: int = 0

    def begin(self, context: ManagedFullRunExtractionContext) -> None:
        if self.context is None:
            self.context = context
        elif self.context != context:
            raise ManagedFullRunExtractionLedgerError("context_conflict")

    def read_checkpoint(self) -> ManagedFullRunExtractionCheckpoint:
        assert self.context is not None
        self.checkpoint_read_count += 1
        return ManagedFullRunExtractionCheckpoint(
            context_commitment_sha256=self.context.commitment_sha256,
            receipt_count=len(self.receipts),
            expected_receipt_count=self.context.expected_receipt_count,
            state="committed" if self.terminal is not None else "active",
            terminal=self.terminal,
        )

    def append_page(
        self,
        receipts: tuple[ManagedFullRunExtractionReceipt, ...],
    ) -> None:
        if not receipts or len(receipts) > FULL_RUN_EXTRACTION_PAGE_SIZE:
            raise ManagedFullRunExtractionLedgerError("receipt_page_invalid")
        self.append_page_count += 1
        self.max_append_page_size = max(self.max_append_page_size, len(receipts))
        start = receipts[0].sequence
        if start < len(self.receipts):
            if tuple(self.receipts[start : start + len(receipts)]) != receipts:
                raise ManagedFullRunExtractionLedgerError("replay_conflict")
            return
        if start != len(self.receipts):
            raise ManagedFullRunExtractionLedgerError("receipt_sequence_gap")
        if any(receipt.sequence != start + offset for offset, receipt in enumerate(receipts)):
            raise ManagedFullRunExtractionLedgerError("receipt_page_invalid")
        self.pages.append(receipts)
        self.receipts.extend(receipts)

    def finalize(self) -> ManagedFullRunExtractionTerminal:
        if self.terminal is not None:
            return self.terminal
        assert self.context is not None
        if len(self.receipts) != self.context.expected_receipt_count:
            raise ManagedFullRunExtractionLedgerError("receipt_count_incomplete")
        body = {
            "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
            "context_commitment_sha256": self.context.commitment_sha256,
            "receipt_count": len(self.receipts),
            "page_count": (len(self.receipts) + FULL_RUN_EXTRACTION_PAGE_SIZE - 1)
            // FULL_RUN_EXTRACTION_PAGE_SIZE,
            "receipt_pages_root_sha256": canonical_sha256(
                [receipt.commitment_sha256 for receipt in self.receipts]
            ),
            "usage": {
                "prompt_tokens": sum(receipt.prompt_tokens for receipt in self.receipts),
                "completion_tokens": sum(receipt.completion_tokens for receipt in self.receipts),
                "total_tokens": sum(receipt.total_tokens for receipt in self.receipts),
            },
        }
        self.terminal = ManagedFullRunExtractionTerminal(
            context_commitment_sha256=str(body["context_commitment_sha256"]),
            receipt_count=int(body["receipt_count"]),
            page_count=int(body["page_count"]),
            receipt_pages_root_sha256=str(body["receipt_pages_root_sha256"]),
            prompt_tokens=int(body["usage"]["prompt_tokens"]),  # type: ignore[index]
            completion_tokens=int(body["usage"]["completion_tokens"]),  # type: ignore[index]
            total_tokens=int(body["usage"]["total_tokens"]),  # type: ignore[index]
            terminal_commitment_sha256=canonical_sha256(body),
        )
        return self.terminal

    def readback(self) -> ManagedFullRunExtractionTerminal | None:
        return self.terminal

    def close(self) -> None:
        return None


@dataclass
class _Boundary:
    dispatch_ordinals: list[int] = field(default_factory=list)
    lookup_ordinals: list[int] = field(default_factory=list)

    def dispatch_once(self, *, command: PublishableExtractionCommand) -> object:
        self.dispatch_ordinals.append(command.ordinal)
        return command

    def lookup_outcome(self, *, command: PublishableExtractionCommand) -> object:
        self.lookup_ordinals.append(command.ordinal)
        return command


@dataclass
class _RuntimeVerifier:
    mutation: str | None = None
    marked_unknown: list[str] = field(default_factory=list)

    def mark_outcome_unknown(
        self,
        *,
        context: RuntimeReceiptVerificationContext,
    ) -> None:
        self.marked_unknown.append(context.operation_id_sha256)

    def verify_dispatch_receipt(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is False
        return self._result(payload, context)

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is True
        return self._result(payload, context)

    def _result(
        self,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert isinstance(payload, PublishableExtractionCommand)
        operation_id = context.operation_id_sha256
        request_body = payload.request_body_sha256
        if self.mutation == "receipt":
            operation_id = _sha("wrong-operation-receipt")
        elif self.mutation == "request":
            request_body = _sha("wrong-request-receipt")
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=operation_id,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha(f"provider:{payload.ordinal}"),
            sequence=payload.ordinal,
            request_body_sha256=request_body,
            output_text_sha256=_sha(f"output:{payload.ordinal}"),
            runtime_binding_commitment_sha256=_sha("shared-runtime-binding"),
            disposition=Mem0OssReceiptDisposition.COMPLETED,
            extraction_calls=1,
            retry_count=0,
            request_tokens=7,
            response_tokens=3,
        )


@dataclass
class _JournalReceiptVerifier:
    def verify(
        self,
        *,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> VerifiedOperationReceipt:
        del identity
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id="publishable-test-receipt-verifier",
            verification_commitment_sha256=_sha("journal-receipt-verification"),
        )


@dataclass
class _ReceiptIssuer:
    mutation: str | None = None

    def issue(
        self,
        *,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
        result_commitment_sha256: str,
    ) -> OperationReceipt:
        run_id = "foreign-publishable-run" if self.mutation == "cross_run" else identity.run_id
        return OperationReceipt(
            run_id=run_id,
            logical_operation_id=identity.logical_operation_id,
            request_commitment_sha256=request_commitment_sha256,
            receipt_id=f"publishable-receipt-{identity.ordinal}",
            result_commitment_sha256=result_commitment_sha256,
        )


def _journal(
    root: Path,
) -> tuple[SQLiteOperationJournal, ResumableOperationJournalService]:
    root.mkdir(parents=True, exist_ok=True)
    private = root / "journal"
    journal = SQLiteOperationJournal(
        private / "operations.sqlite3",
        private_directory=private,
    )
    service = ResumableOperationJournalService(
        journal=journal,
        signer=HmacSha256OperationJournalSigner(
            key_id=_SIGNER_KEY_ID,
            secret=_SIGNER_SECRET,
        ),
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=_JournalReceiptVerifier(),
        notifications=NullOperationNotification(),
    )
    return journal, service


def _stores(
    *,
    service: ResumableOperationJournalService,
    journal: SQLiteOperationJournal,
    ledger: _RecordingLedger,
    expected: _ExpectedOperations,
    issuer: _ReceiptIssuer | None = None,
) -> OpenedPublishableExtractionStores:
    return OpenedPublishableExtractionStores(
        journal_service=service,
        journal_store=journal,
        extraction_ledger=ledger,
        expected_operations=expected,
        operation_receipt_issuer=issuer or _ReceiptIssuer(),
        close_callbacks=(),
    )


def _managed_receipt(
    authority: PublishableExtractionRunAuthority,
    ordinal: int,
) -> ManagedFullRunExtractionReceipt:
    operation = authority.runtime_receipt_authority.operations[ordinal]
    return ManagedFullRunExtractionReceipt(
        sequence=ordinal,
        operation_id_sha256=operation.operation_id_sha256,
        unit_identity_sha256=operation.unit_identity_sha256,
        request_body_sha256=operation.request_body_sha256,
        output_text_sha256=_sha(f"output:{ordinal}"),
        provider_receipt_sha256=_sha(f"provider:{ordinal}"),
        runtime_binding_commitment_sha256=(
            authority.ledger_context.runtime_binding_commitment_sha256
        ),
        prompt_tokens=7,
        completion_tokens=3,
        total_tokens=10,
    )


def _precommit(
    service: ResumableOperationJournalService,
    authority: PublishableExtractionRunAuthority,
) -> None:
    service.initialize(authority.journal_identity, authority.operation_manifest)
    service.prepare_dispatch_batch(
        tuple(
            (identity, operation.request_body_sha256)
            for identity, operation in zip(
                authority.operation_manifest.operations,
                authority.runtime_receipt_authority.operations,
                strict=True,
            )
        )
    )
    for identity in authority.operation_manifest.operations:
        receipt = _managed_receipt(authority, identity.ordinal)
        service.commit(
            identity,
            OperationReceipt(
                run_id=identity.run_id,
                logical_operation_id=identity.logical_operation_id,
                request_commitment_sha256=receipt.request_body_sha256,
                receipt_id=f"precommitted-receipt-{identity.ordinal}",
                result_commitment_sha256=(
                    PublishableFullExtractionWorker._result_commitment(receipt)
                ),
            ),
        )


def test_committed_reopen_makes_zero_dispatches(tmp_path: Path) -> None:
    authority = _authority(1)
    journal, service = _journal(tmp_path)
    _precommit(service, authority)
    ledger = _RecordingLedger()
    expected = _ExpectedOperations(authority)

    first_boundary = _Boundary()
    first = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=service,
            journal=journal,
            ledger=ledger,
            expected=expected,
        ),
        boundary=first_boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )
    assert first.advance_one().phase is PublishableExtractionAdvancePhase.SEALED
    assert first_boundary.dispatch_ordinals == []
    assert first_boundary.lookup_ordinals == [0]
    first.close()

    reopened_boundary = _Boundary()
    reopened_service = _journal_service_for(journal)
    reopened = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=reopened_service,
            journal=journal,
            ledger=ledger,
            expected=expected,
        ),
        boundary=reopened_boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )
    assert reopened.advance_one().phase is PublishableExtractionAdvancePhase.SEALED
    assert reopened_boundary.dispatch_ordinals == []
    assert reopened_boundary.lookup_ordinals == []
    reopened.close()


def _journal_service_for(
    journal: SQLiteOperationJournal,
) -> ResumableOperationJournalService:
    return ResumableOperationJournalService(
        journal=journal,
        signer=HmacSha256OperationJournalSigner(
            key_id=_SIGNER_KEY_ID,
            secret=_SIGNER_SECRET,
        ),
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=_JournalReceiptVerifier(),
        notifications=NullOperationNotification(),
    )


def test_durable_intent_crash_freezes_until_explicit_lookup(tmp_path: Path) -> None:
    authority = _authority(1, run_id="durable-intent-crash")
    journal, service = _journal(tmp_path)
    service.initialize(authority.journal_identity, authority.operation_manifest)
    operation = authority.operation_manifest.operations[0]
    request_hash = authority.runtime_receipt_authority.operations[0].request_body_sha256
    assert service.prepare_dispatch(operation, request_hash).should_dispatch is True

    boundary = _Boundary()
    verifier = _RuntimeVerifier()
    worker = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=_journal_service_for(journal),
            journal=journal,
            ledger=_RecordingLedger(),
            expected=_ExpectedOperations(authority),
        ),
        boundary=boundary,
        runtime_receipt_verifier=verifier,
    )
    for _ in range(2):
        advance = worker.advance_one()
        assert advance.phase is PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED
        assert advance.journal_snapshot.outcome_unknown_count == 1
    assert boundary.dispatch_ordinals == boundary.lookup_ordinals == []
    assert verifier.marked_unknown == [
        authority.runtime_receipt_authority.operations[0].operation_id_sha256
    ]

    reconciled = worker.reconcile_one()
    assert reconciled.phase is PublishableExtractionAdvancePhase.SEALED
    assert boundary.dispatch_ordinals == []
    assert boundary.lookup_ordinals == [0]
    worker.close()


def test_known_pre_dispatch_intent_failure_may_retry(tmp_path: Path) -> None:
    authority = _authority(1, run_id="known-predispatch-failure")
    journal, service = _journal(tmp_path)
    boundary = _Boundary()
    worker = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=service,
            journal=journal,
            ledger=_RecordingLedger(),
            expected=_ExpectedOperations(authority),
        ),
        boundary=boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )
    connection = sqlite3.connect(journal.database_path)
    connection.execute(
        """CREATE TRIGGER fail_dispatch_intent
           BEFORE INSERT ON operation_events
           WHEN NEW.run_id='known-predispatch-failure' AND NEW.sequence=2
           BEGIN SELECT RAISE(FAIL, 'known predispatch failure'); END"""
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        PublishableExtractionWorkerError,
        match="extraction_dispatch_intent_failed",
    ):
        worker.advance_one()
    snapshot = service.snapshot(authority.journal_identity.run_id)
    assert (snapshot.pending_count, snapshot.dispatched_count) == (1, 0)
    assert boundary.dispatch_ordinals == []

    connection = sqlite3.connect(journal.database_path)
    connection.execute("DROP TRIGGER fail_dispatch_intent")
    connection.commit()
    connection.close()
    assert worker.advance_one().phase is PublishableExtractionAdvancePhase.SEALED
    assert boundary.dispatch_ordinals == [0]
    worker.close()


@pytest.mark.parametrize("mutation", ["receipt", "request", "cross_run"])
def test_receipt_request_and_cross_run_mismatch_reject(
    tmp_path: Path,
    mutation: str,
) -> None:
    authority = _authority(1, run_id=f"mismatch-{mutation}")
    journal, service = _journal(tmp_path / mutation)
    boundary = _Boundary()
    ledger = _RecordingLedger()
    worker = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=service,
            journal=journal,
            ledger=ledger,
            expected=_ExpectedOperations(authority),
            issuer=_ReceiptIssuer(mutation="cross_run" if mutation == "cross_run" else None),
        ),
        boundary=boundary,
        runtime_receipt_verifier=_RuntimeVerifier(
            mutation=mutation if mutation != "cross_run" else None
        ),
    )
    with pytest.raises(
        PublishableExtractionWorkerError,
        match="extraction_dispatch_receipt_invalid",
    ):
        worker.advance_one()
    snapshot = service.snapshot(authority.journal_identity.run_id)
    assert snapshot.outcome_unknown_count == 1
    assert boundary.dispatch_ordinals == [0]
    assert ledger.pages == []
    assert worker.advance_one().phase is PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED
    assert boundary.dispatch_ordinals == [0]
    worker.close()


def test_ledger_pages_are_bounded_and_preserve_exact_order(tmp_path: Path) -> None:
    authority = _authority(513, run_id="page-order")
    journal, service = _journal(tmp_path)
    _precommit(service, authority)
    ledger = _RecordingLedger()
    expected = _ExpectedOperations(authority)
    boundary = _Boundary()
    worker = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=service,
            journal=journal,
            ledger=ledger,
            expected=expected,
        ),
        boundary=boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )

    assert worker.advance_one().phase is PublishableExtractionAdvancePhase.SEALED
    assert [len(page) for page in ledger.pages] == [512, 1]
    assert max(len(page) for page in ledger.pages) <= FULL_RUN_EXTRACTION_PAGE_SIZE
    assert [receipt.sequence for page in ledger.pages for receipt in page] == list(range(513))
    assert expected.starts == [0, 512, 0, 512]
    assert max(expected.page_lengths) <= FULL_RUN_EXTRACTION_PAGE_SIZE
    assert boundary.dispatch_ordinals == []
    assert boundary.lookup_ordinals == list(range(513))
    worker.close()


def test_4096_operation_crash_reopen_is_linearized_and_page_bounded(
    tmp_path: Path,
) -> None:
    operation_count = 4_096
    crash_ordinal = operation_count // 2
    authority = _authority(operation_count, run_id="structural-4096")
    journal, service = _journal(tmp_path)
    ledger = _RecordingLedger()
    expected = _ExpectedOperations(authority)
    boundary = _Boundary()
    worker = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=service,
            journal=journal,
            ledger=ledger,
            expected=expected,
        ),
        boundary=boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )

    journal.reset_work_counters()
    for ordinal in range(crash_ordinal):
        advance = worker.advance_one()
        assert advance.phase is PublishableExtractionAdvancePhase.OPERATION_COMMITTED
        assert advance.operation_ordinal == ordinal
    first_hot_work = journal.work_counters
    _assert_hot_work_is_near_linear(first_hot_work, operation_count=crash_ordinal)
    crash_checkpoint = service.current_checkpoint(authority.journal_identity.run_id)
    worker.close()

    reopened_journal = SQLiteOperationJournal(
        journal.database_path,
        private_directory=journal.private_directory,
    )
    reopened_service = _journal_service_for(reopened_journal)
    reopened = PublishableFullExtractionWorker(
        authority=authority,
        stores=_stores(
            service=reopened_service,
            journal=reopened_journal,
            ledger=ledger,
            expected=expected,
        ),
        boundary=boundary,
        runtime_receipt_verifier=_RuntimeVerifier(),
    )
    recovery_work = reopened_journal.work_counters
    assert recovery_work["max_scan_page_size"] == FULL_RUN_EXTRACTION_PAGE_SIZE
    assert recovery_work["manifest_rows_scanned"] == operation_count * 2
    assert recovery_work["state_rows_scanned"] == crash_ordinal * 2
    assert recovery_work["receipt_rows_scanned"] == crash_ordinal * 2
    assert recovery_work["event_rows_scanned"] == (1 + crash_ordinal * 2) * 2
    assert (
        reopened_service.current_checkpoint(authority.journal_identity.run_id) == crash_checkpoint
    )

    reopened_journal.reset_work_counters()
    for ordinal in range(crash_ordinal, operation_count - 1):
        advance = reopened.advance_one()
        assert advance.phase is PublishableExtractionAdvancePhase.OPERATION_COMMITTED
        assert advance.operation_ordinal == ordinal
    second_hot_work = reopened_journal.work_counters
    _assert_hot_work_is_near_linear(
        second_hot_work,
        operation_count=operation_count - crash_ordinal - 1,
    )

    reopened_journal.reset_work_counters()
    terminal = reopened.advance_one()
    terminal_work = reopened_journal.work_counters
    assert terminal.phase is PublishableExtractionAdvancePhase.SEALED
    assert terminal.operation_ordinal is None
    assert terminal.terminal is not None
    assert terminal.terminal.ledger_terminal.receipt_count == operation_count
    assert terminal_work["max_scan_page_size"] == FULL_RUN_EXTRACTION_PAGE_SIZE
    assert terminal_work["manifest_rows_scanned"] == operation_count
    assert terminal_work["state_rows_scanned"] == operation_count
    assert terminal_work["receipt_rows_scanned"] == operation_count
    assert terminal_work["event_rows_scanned"] == 1 + operation_count * 2
    assert boundary.dispatch_ordinals == list(range(operation_count))
    assert boundary.lookup_ordinals == []
    assert ledger.append_page_count == operation_count // FULL_RUN_EXTRACTION_PAGE_SIZE
    assert ledger.max_append_page_size == FULL_RUN_EXTRACTION_PAGE_SIZE
    assert ledger.checkpoint_read_count == 2
    assert tuple(receipt.sequence for receipt in ledger.receipts) == tuple(range(operation_count))
    reopened.close()


def _assert_hot_work_is_near_linear(
    work: dict[str, int],
    *,
    operation_count: int,
) -> None:
    assert work["operation_transitions"] == operation_count * 2
    assert work["checkpoint_reads"] == operation_count * 3
    assert work["checkpoint_writes"] == operation_count * 2
    assert work["accumulator_node_reads"] <= operation_count * 320
    assert work["accumulator_node_writes"] <= operation_count * 40
    assert (
        not {
            "manifest_rows_scanned",
            "state_rows_scanned",
            "receipt_rows_scanned",
            "event_rows_scanned",
            "scan_pages",
            "max_scan_page_size",
        }
        & work.keys()
    )


def test_cross_wired_a1_is_rejected_before_dispatch_or_journal_intent(
    tmp_path: Path,
) -> None:
    authority = _authority(1, run_id="cross-wired-a1")
    journal, service = _journal(tmp_path)
    boundary = _Boundary()
    ledger = _RecordingLedger()
    closed: list[bool] = []
    stores = OpenedPublishableExtractionStores(
        journal_service=service,
        journal_store=journal,
        extraction_ledger=ledger,
        expected_operations=_ExpectedOperations(authority, drift_at=0),
        operation_receipt_issuer=_ReceiptIssuer(),
        close_callbacks=(lambda: closed.append(True),),
    )
    with pytest.raises(
        PublishableExtractionWorkerError,
        match="extraction_worker_open_failed",
    ):
        open_publishable_full_extraction_worker(
            authority=authority,
            stores_opener=lambda _authority: stores,
            boundary=boundary,
            runtime_receipt_verifier=_RuntimeVerifier(),
        )
    assert boundary.dispatch_ordinals == boundary.lookup_ordinals == []
    assert ledger.context is None
    with pytest.raises(OperationJournalError, match="operation_journal_run_missing"):
        service.snapshot(authority.journal_identity.run_id)
    assert closed == [True]
