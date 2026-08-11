"""Provider-neutral, exact-resume worker for one managed Mem0 extraction run."""

from __future__ import annotations

import threading
from contextlib import suppress
from typing import final

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionCheckpoint,
    ManagedFullRunExtractionLedgerError,
    ManagedFullRunExtractionReceipt,
    ManagedFullRunExtractionTerminal,
)

from infinity_context_server.memory_comparison_managed_full_run_extraction_ledger import (
    _verified_ledger_receipt,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    MANAGED_MEM0_EXTRACTION_NAMESPACE,
    MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
    PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA,
    PUBLISHABLE_EXTRACTION_WORKER_SCHEMA,
    OpenedPublishableExtractionStores,
    PublishableExtractionAdvance,
    PublishableExtractionAdvancePhase,
    PublishableExtractionCommand,
    PublishableExtractionOneShotPort,
    PublishableExtractionOperationReceiptIssuerPort,
    PublishableExtractionRecoveryError,
    PublishableExtractionRunAuthority,
    PublishableExtractionRunTerminal,
    PublishableExtractionWorkerError,
    _fail,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationJournalCheckpoint,
    OperationPhase,
    OperationReceipt,
    OperationRunPhase,
    OperationState,
    sha256_commitment,
)


@final
class PublishableFullExtractionWorker:
    """Dispatch one operation and reconcile through an exact idempotent probe."""

    __slots__ = (
        "_authority",
        "_boundary",
        "_checkpoint",
        "_closed",
        "_journal_seal_attempted",
        "_ledger_cursor",
        "_ledger_terminal",
        "_lock",
        "_marked_unknown_ordinal",
        "_runtime_verifier",
        "_stores",
        "_verified_receipts",
    )

    def __init__(
        self,
        *,
        authority: PublishableExtractionRunAuthority,
        stores: OpenedPublishableExtractionStores,
        boundary: PublishableExtractionOneShotPort,
        runtime_receipt_verifier: RuntimeReceiptVerificationPort,
    ) -> None:
        if (
            type(authority) is not PublishableExtractionRunAuthority
            or type(stores) is not OpenedPublishableExtractionStores
            or any(
                not callable(getattr(boundary, name, None))
                for name in ("dispatch_once", "lookup_outcome", "recover_once")
            )
            or any(
                not callable(getattr(runtime_receipt_verifier, name, None))
                for name in (
                    "mark_outcome_unknown",
                    "verify_dispatch_receipt",
                    "verify_status_readback",
                )
            )
        ):
            _fail("extraction_worker_composition_invalid")
        self._authority = authority
        self._stores = stores
        self._boundary = boundary
        self._runtime_verifier = runtime_receipt_verifier
        self._verified_receipts: dict[int, ManagedFullRunExtractionReceipt] = {}
        self._checkpoint: OperationJournalCheckpoint | None = None
        self._ledger_terminal: ManagedFullRunExtractionTerminal | None = None
        self._ledger_cursor = 0
        self._journal_seal_attempted = False
        self._marked_unknown_ordinal: int | None = None
        self._closed = False
        self._lock = threading.RLock()
        self._initialize()

    def advance_one(self) -> PublishableExtractionAdvance:
        """Dispatch only the next ordered pending operation."""

        with self._lock:
            self._require_open()
            checkpoint = self._read_current_checkpoint()
            checkpoint = self._quarantine_current_dispatch(checkpoint)
            if checkpoint.facts.outcome_unknown_count:
                return self._advance_result(
                    PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED,
                    checkpoint=checkpoint,
                )
            self._flush_ready_pages(checkpoint)
            committed = checkpoint.facts.committed_prefix_count
            expected = self._authority.journal_identity.expected_operation_count
            if committed == expected:
                return self._seal_exact(checkpoint)
            if checkpoint.run.phase is not OperationRunPhase.ACTIVE:
                _fail("extraction_run_not_active")
            identity = self._authority.operation_manifest.operations[committed]
            command = self._command(identity)
            try:
                prepared = self._stores.journal_service.prepare_dispatch(
                    identity,
                    command.request_body_sha256,
                )
            except Exception:
                _fail("extraction_dispatch_intent_failed")
            checkpoint = self._accept_checkpoint(prepared.checkpoint)
            if not prepared.should_dispatch:
                return self._replayed_preparation(
                    identity=identity,
                    checkpoint=checkpoint,
                    state=prepared.state,
                )
            try:
                payload = self._boundary.dispatch_once(command=command)
            except BaseException:
                self._quarantine(identity, command=command, mark_runtime=True)
                _fail("extraction_dispatch_outcome_unknown")
            try:
                receipt = self._verify_runtime_receipt(
                    payload=payload,
                    command=command,
                    readback=False,
                )
                self._verified_receipts[identity.ordinal] = receipt
                checkpoint = self._commit_verified(identity, receipt)
            except BaseException:
                self._quarantine(
                    identity,
                    command=command,
                    mark_runtime=identity.ordinal not in self._verified_receipts,
                )
                _fail("extraction_dispatch_receipt_invalid")
            self._flush_ready_pages(checkpoint)
            if checkpoint.facts.committed_prefix_count == expected:
                return self._seal_exact(checkpoint)
            return self._advance_result(
                PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
                checkpoint=checkpoint,
                operation_ordinal=identity.ordinal,
            )

    def reconcile_one(self) -> PublishableExtractionAdvance:
        """Resolve unknown state by status, then the boundary's explicit safe probe."""

        with self._lock:
            self._require_open()
            checkpoint = self._read_current_checkpoint()
            checkpoint = self._quarantine_current_dispatch(checkpoint)
            unsettled = checkpoint.facts.first_unsettled
            if unsettled is None:
                self._flush_ready_pages(checkpoint)
                if (
                    checkpoint.facts.committed_prefix_count
                    == self._authority.journal_identity.expected_operation_count
                ):
                    return self._seal_exact(checkpoint)
                return self._advance_result(
                    PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
                    checkpoint=checkpoint,
                )
            if unsettled.phase is not OperationPhase.OUTCOME_UNKNOWN:
                _fail("extraction_operation_phase_invalid")
            identity = self._identity_for_unsettled(checkpoint)
            command = self._command(identity)
            if command.request_body_sha256 != unsettled.request_commitment_sha256:
                _fail("extraction_journal_cross_wire")
            try:
                self._mark_first_unknown(checkpoint)
                receipt = self._verified_receipts.get(identity.ordinal)
                if receipt is None:
                    try:
                        payload = self._boundary.lookup_outcome(command=command)
                    except Exception:
                        payload = self._boundary.recover_once(command=command)
                    receipt = self._verify_runtime_receipt(
                        payload=payload,
                        command=command,
                        readback=True,
                    )
                    self._verified_receipts[identity.ordinal] = receipt
                checkpoint = self._commit_verified(identity, receipt)
            except PublishableExtractionRecoveryError as exc:
                if exc.code == "operator_action_required":
                    _fail("extraction_recovery_operator_action_required")
                _fail("extraction_outcome_reconciliation_failed")
            except BaseException:
                _fail("extraction_outcome_reconciliation_failed")
            if checkpoint.facts.outcome_unknown_count:
                self._mark_first_unknown(checkpoint, suppress_errors=True)
                return self._advance_result(
                    PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED,
                    checkpoint=checkpoint,
                    operation_ordinal=identity.ordinal,
                )
            self._flush_ready_pages(checkpoint)
            if (
                checkpoint.facts.committed_prefix_count
                == self._authority.journal_identity.expected_operation_count
            ):
                return self._seal_exact(checkpoint)
            return self._advance_result(
                PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
                checkpoint=checkpoint,
                operation_ordinal=identity.ordinal,
            )

    def read_terminal(self) -> PublishableExtractionRunTerminal | None:
        """Read both durable terminals without provider dispatch or status I/O."""

        with self._lock:
            self._require_open()
            checkpoint = self._read_current_checkpoint()
            ledger_checkpoint = self._read_ledger_checkpoint(checkpoint)
            terminal = ledger_checkpoint.terminal
            if terminal is None or checkpoint.run.phase is not OperationRunPhase.SEALED:
                return None
            self._validate_ledger_terminal(terminal)
            self._ledger_terminal = terminal
            self._ledger_cursor = ledger_checkpoint.next_sequence
            return self._run_terminal(checkpoint, terminal)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stores.close()

    def __enter__(self) -> PublishableFullExtractionWorker:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize(self) -> None:
        authority = self._authority
        try:
            operations = authority.runtime_receipt_authority.operations
            for start in range(0, len(operations), FULL_RUN_EXTRACTION_PAGE_SIZE):
                end = min(start + FULL_RUN_EXTRACTION_PAGE_SIZE, len(operations))
                self._require_a1_page(
                    start=start,
                    observed=tuple(
                        operation.operation_id_sha256 for operation in operations[start:end]
                    ),
                )
            self._stores.journal_service.initialize(
                authority.journal_identity,
                authority.operation_manifest,
            )
            self._stores.extraction_ledger.begin(authority.ledger_context)
            recovered = self._stores.journal_service.recover(authority.journal_identity.run_id)
            checkpoint = self._accept_checkpoint(recovered.checkpoint)
            ledger_checkpoint = self._read_ledger_checkpoint(checkpoint)
            self._ledger_cursor = ledger_checkpoint.next_sequence
            self._ledger_terminal = ledger_checkpoint.terminal
            self._mark_first_unknown(checkpoint)
        except BaseException:
            _fail("extraction_worker_open_failed")

    def _read_current_checkpoint(self) -> OperationJournalCheckpoint:
        try:
            checkpoint = self._stores.journal_service.current_checkpoint(
                self._authority.journal_identity.run_id
            )
        except BaseException:
            _fail("extraction_journal_checkpoint_failed")
        return self._accept_checkpoint(checkpoint)

    def _accept_checkpoint(self, checkpoint: object) -> OperationJournalCheckpoint:
        if type(checkpoint) is not OperationJournalCheckpoint:
            _fail("extraction_journal_checkpoint_invalid")
        facts = checkpoint.facts
        expected = self._authority.journal_identity.expected_operation_count
        unsettled = facts.first_unsettled
        if (
            checkpoint.run.identity != self._authority.journal_identity
            or facts.expected_operation_count != expected
            or facts.committed_count != facts.committed_prefix_count
            or self._ledger_cursor > facts.committed_prefix_count
            or (
                checkpoint.run.phase is OperationRunPhase.SEALED
                and facts.committed_prefix_count != expected
            )
        ):
            _fail("extraction_operation_order_divergent")
        if facts.dispatched_count:
            valid_unsettled = (
                facts.dispatched_count == 1
                and facts.outcome_unknown_count == 0
                and unsettled is not None
                and unsettled.phase is OperationPhase.DISPATCHED
            )
        elif facts.outcome_unknown_count:
            valid_unsettled = (
                unsettled is not None
                and unsettled.phase is OperationPhase.OUTCOME_UNKNOWN
                and checkpoint.run.phase is OperationRunPhase.RECONCILIATION_REQUIRED
            )
        else:
            valid_unsettled = (
                unsettled is None
                and checkpoint.run.phase is not OperationRunPhase.RECONCILIATION_REQUIRED
            )
        if not valid_unsettled or (
            unsettled is not None and unsettled.ordinal != facts.committed_prefix_count
        ):
            _fail("extraction_operation_order_divergent")
        if unsettled is not None:
            self._identity_for_unsettled(checkpoint)
        self._checkpoint = checkpoint
        return checkpoint

    def _read_ledger_checkpoint(
        self,
        journal: OperationJournalCheckpoint,
    ) -> ManagedFullRunExtractionCheckpoint:
        checkpoint = self._stores.extraction_ledger.read_checkpoint()
        total = self._authority.ledger_context.expected_receipt_count
        if (
            type(checkpoint) is not ManagedFullRunExtractionCheckpoint
            or checkpoint.context_commitment_sha256
            != self._authority.ledger_context.commitment_sha256
            or checkpoint.expected_receipt_count != total
            or checkpoint.next_sequence > journal.facts.committed_prefix_count
            or (
                checkpoint.next_sequence != total
                and checkpoint.next_sequence % FULL_RUN_EXTRACTION_PAGE_SIZE
            )
        ):
            _fail("extraction_ledger_checkpoint_divergent")
        if checkpoint.terminal is not None:
            self._validate_ledger_terminal(checkpoint.terminal)
        return checkpoint

    def _identity_for_unsettled(
        self,
        checkpoint: OperationJournalCheckpoint,
    ) -> LogicalOperationIdentity:
        unsettled = checkpoint.facts.first_unsettled
        operations = self._authority.operation_manifest.operations
        if unsettled is None or unsettled.ordinal >= len(operations):
            _fail("extraction_journal_cross_wire")
        identity = operations[unsettled.ordinal]
        if identity.logical_operation_id != unsettled.logical_operation_id:
            _fail("extraction_journal_cross_wire")
        return identity

    def _mark_first_unknown(
        self,
        checkpoint: OperationJournalCheckpoint,
        *,
        suppress_errors: bool = False,
    ) -> None:
        unsettled = checkpoint.facts.first_unsettled
        if unsettled is None or unsettled.phase is not OperationPhase.OUTCOME_UNKNOWN:
            self._marked_unknown_ordinal = None
            return
        if self._marked_unknown_ordinal == unsettled.ordinal:
            return
        identity = self._identity_for_unsettled(checkpoint)
        try:
            self._runtime_verifier.mark_outcome_unknown(
                context=self._verification_context(
                    self._command(identity),
                    readback=False,
                )
            )
        except BaseException:
            if suppress_errors:
                return
            raise
        self._marked_unknown_ordinal = unsettled.ordinal

    def _quarantine_current_dispatch(
        self,
        checkpoint: OperationJournalCheckpoint,
    ) -> OperationJournalCheckpoint:
        if checkpoint.facts.dispatched_count == 0:
            return checkpoint
        identity = self._identity_for_unsettled(checkpoint)
        unsettled = checkpoint.facts.first_unsettled
        if (
            unsettled is None
            or self._command(identity).request_body_sha256 != unsettled.request_commitment_sha256
        ):
            _fail("extraction_journal_cross_wire")
        try:
            transition = self._stores.journal_service.quarantine_dispatched(identity)
            checkpoint = self._accept_checkpoint(transition.checkpoint)
        except BaseException:
            _fail("extraction_dispatch_quarantine_failed")
        self._mark_first_unknown(checkpoint, suppress_errors=True)
        return checkpoint

    def _replayed_preparation(
        self,
        *,
        identity: LogicalOperationIdentity,
        checkpoint: OperationJournalCheckpoint,
        state: OperationState,
    ) -> PublishableExtractionAdvance:
        if type(state) is not OperationState or state.identity != identity:
            _fail("extraction_dispatch_intent_replayed")
        if state.phase is OperationPhase.DISPATCHED:
            checkpoint = self._quarantine_current_dispatch(checkpoint)
            return self._advance_result(
                PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED,
                checkpoint=checkpoint,
                operation_ordinal=identity.ordinal,
            )
        if state.phase is not OperationPhase.COMMITTED:
            _fail("extraction_dispatch_intent_replayed")
        self._flush_ready_pages(checkpoint)
        if (
            checkpoint.facts.committed_prefix_count
            == self._authority.journal_identity.expected_operation_count
        ):
            return self._seal_exact(checkpoint)
        return self._advance_result(
            PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
            checkpoint=checkpoint,
            operation_ordinal=identity.ordinal,
        )

    def _flush_ready_pages(self, checkpoint: OperationJournalCheckpoint) -> None:
        if self._ledger_terminal is not None:
            return
        committed = checkpoint.facts.committed_prefix_count
        total = self._authority.journal_identity.expected_operation_count
        while self._ledger_cursor < total:
            start = self._ledger_cursor
            end = min(start + FULL_RUN_EXTRACTION_PAGE_SIZE, total)
            if committed < end:
                return
            states = self._read_committed_page(
                checkpoint=checkpoint,
                start=start,
                end=end,
            )
            receipts: list[ManagedFullRunExtractionReceipt] = []
            for state in states:
                ordinal = state.identity.ordinal
                receipt = self._verified_receipts.get(ordinal)
                if receipt is None:
                    command = self._command(state.identity)
                    try:
                        payload = self._boundary.lookup_outcome(command=command)
                        receipt = self._verify_runtime_receipt(
                            payload=payload,
                            command=command,
                            readback=True,
                        )
                    except BaseException:
                        _fail("extraction_committed_readback_failed")
                    self._verified_receipts[ordinal] = receipt
                self._validate_committed_receipt(state, receipt)
                receipts.append(receipt)
            self._require_a1_page(
                start=start,
                observed=tuple(receipt.operation_id_sha256 for receipt in receipts),
            )
            try:
                self._stores.extraction_ledger.append_page(tuple(receipts))
            except ManagedFullRunExtractionLedgerError:
                raise
            except BaseException:
                _fail("extraction_ledger_append_failed")
            self._ledger_cursor = end
            for ordinal in range(start, end):
                self._verified_receipts.pop(ordinal, None)

    def _read_committed_page(
        self,
        *,
        checkpoint: OperationJournalCheckpoint,
        start: int,
        end: int,
    ) -> tuple[OperationState, ...]:
        if (
            start < 0
            or end <= start
            or end - start > FULL_RUN_EXTRACTION_PAGE_SIZE
            or end > checkpoint.facts.committed_prefix_count
        ):
            _fail("extraction_ledger_page_state_invalid")
        run_id = self._authority.journal_identity.run_id
        states: list[OperationState] = []
        with self._stores.journal_store.write_transaction() as transaction:
            for ordinal in range(start, end):
                state = transaction.get_authenticated_operation(
                    run_id=run_id,
                    ordinal=ordinal,
                    facts=checkpoint.facts,
                )
                expected = self._authority.operation_manifest.operations[ordinal]
                if (
                    type(state) is not OperationState
                    or state.identity != expected
                    or state.phase is not OperationPhase.COMMITTED
                ):
                    _fail("extraction_ledger_page_state_invalid")
                states.append(state)
        return tuple(states)

    def _require_a1_page(self, *, start: int, observed: tuple[str, ...]) -> None:
        expected = self._stores.expected_operations.read_operation_page(
            manifest_context_sha256=self._authority.ledger_context.a1_manifest_context_sha256,
            start_sequence=start,
        )
        if (
            start % FULL_RUN_EXTRACTION_PAGE_SIZE
            or not observed
            or len(observed) > FULL_RUN_EXTRACTION_PAGE_SIZE
            or expected != observed
        ):
            _fail("extraction_a1_page_binding_invalid")

    def _seal_exact(
        self,
        checkpoint: OperationJournalCheckpoint,
    ) -> PublishableExtractionAdvance:
        total = self._authority.journal_identity.expected_operation_count
        if checkpoint.facts.committed_prefix_count != total:
            _fail("extraction_seal_incomplete")
        self._flush_ready_pages(checkpoint)
        if self._ledger_cursor != total:
            _fail("extraction_seal_incomplete")
        terminal = self._ledger_terminal
        if terminal is None:
            terminal = self._stores.extraction_ledger.finalize()
        self._validate_ledger_terminal(terminal)
        self._ledger_terminal = terminal
        sealed = checkpoint
        if sealed.run.phase is not OperationRunPhase.SEALED:
            if self._journal_seal_attempted:
                _fail("extraction_journal_seal_already_attempted")
            self._journal_seal_attempted = True
            sealed = self._accept_checkpoint(
                self._stores.journal_service.seal_with_checkpoint(
                    self._authority.journal_identity.run_id
                )
            )
        return self._advance_result(
            PublishableExtractionAdvancePhase.SEALED,
            checkpoint=sealed,
            terminal=self._run_terminal(sealed, terminal),
        )

    def _verify_runtime_receipt(
        self,
        *,
        payload: object,
        command: PublishableExtractionCommand,
        readback: bool,
    ) -> ManagedFullRunExtractionReceipt:
        context = self._verification_context(command, readback=readback)
        if readback:
            result = self._runtime_verifier.verify_status_readback(
                payload=payload,
                context=context,
            )
        else:
            result = self._runtime_verifier.verify_dispatch_receipt(
                payload=payload,
                context=context,
            )
        if (
            type(result) is not RuntimeReceiptVerificationResult
            or result.sequence != command.ordinal
            or result.request_body_sha256 != command.request_body_sha256
        ):
            _fail("extraction_runtime_receipt_binding_invalid")
        try:
            return _verified_ledger_receipt(
                result=result,
                verification_context=context,
                ledger_context=self._authority.ledger_context,
            )
        except ManagedFullRunExtractionLedgerError:
            _fail("extraction_runtime_receipt_binding_invalid")

    def _commit_verified(
        self,
        identity: LogicalOperationIdentity,
        receipt: ManagedFullRunExtractionReceipt,
    ) -> OperationJournalCheckpoint:
        result = self._result_commitment(receipt)
        issued = self._stores.operation_receipt_issuer.issue(
            identity=identity,
            request_commitment_sha256=receipt.request_body_sha256,
            result_commitment_sha256=result,
        )
        if (
            type(issued) is not OperationReceipt
            or issued.run_id != identity.run_id
            or issued.logical_operation_id != identity.logical_operation_id
            or issued.request_commitment_sha256 != receipt.request_body_sha256
            or issued.result_commitment_sha256 != result
        ):
            _fail("extraction_journal_receipt_invalid")
        transition = self._stores.journal_service.commit_with_checkpoint(
            identity,
            issued,
        )
        self._validate_committed_receipt(transition.state, receipt)
        return self._accept_checkpoint(transition.checkpoint)

    def _validate_committed_receipt(
        self,
        state: OperationState,
        receipt: ManagedFullRunExtractionReceipt,
    ) -> None:
        observed = self._authority.runtime_receipt_authority.operations[receipt.sequence]
        if (
            type(state) is not OperationState
            or state.phase is not OperationPhase.COMMITTED
            or state.identity.ordinal != receipt.sequence
            or state.identity.operation_key != receipt.operation_id_sha256
            or state.request_commitment_sha256 != receipt.request_body_sha256
            or state.receipt is None
            or state.receipt.result_commitment_sha256 != self._result_commitment(receipt)
            or observed.operation_id_sha256 != receipt.operation_id_sha256
            or observed.unit_identity_sha256 != receipt.unit_identity_sha256
            or observed.request_body_sha256 != receipt.request_body_sha256
            or receipt.runtime_binding_commitment_sha256
            != self._authority.ledger_context.runtime_binding_commitment_sha256
        ):
            _fail("extraction_committed_receipt_divergent")

    @staticmethod
    def _result_commitment(receipt: ManagedFullRunExtractionReceipt) -> str:
        return sha256_commitment(
            {
                "schema_version": PUBLISHABLE_EXTRACTION_WORKER_SCHEMA,
                "verified_extraction_receipt": receipt.payload(),
            }
        )

    def _quarantine(
        self,
        identity: LogicalOperationIdentity,
        *,
        command: PublishableExtractionCommand,
        mark_runtime: bool,
    ) -> None:
        if mark_runtime:
            with suppress(BaseException):
                self._runtime_verifier.mark_outcome_unknown(
                    context=self._verification_context(command, readback=False)
                )
        try:
            transition = self._stores.journal_service.quarantine_dispatched(identity)
            self._accept_checkpoint(transition.checkpoint)
        except BaseException:
            pass

    def _command(self, identity: LogicalOperationIdentity) -> PublishableExtractionCommand:
        observed = self._authority.runtime_receipt_authority.operations[identity.ordinal]
        if identity.operation_key != observed.operation_id_sha256:
            _fail("extraction_command_cross_wire")
        return PublishableExtractionCommand(
            run_id=identity.run_id,
            run_identity_commitment_sha256=sha256_commitment(
                self._authority.journal_identity.commitment_payload()
            ),
            logical_operation_id=identity.logical_operation_id,
            ordinal=identity.ordinal,
            admission_commitment_sha256=(
                self._authority.runtime_receipt_authority.admission_commitment_sha256
            ),
            operation_id_sha256=observed.operation_id_sha256,
            unit_identity_sha256=observed.unit_identity_sha256,
            unit_sha256=observed.unit_sha256,
            route_sha256=self._authority.runtime_receipt_authority.route_binding_sha256,
            scope_sha256=observed.scope_sha256,
            request_body_sha256=observed.request_body_sha256,
        )

    @staticmethod
    def _verification_context(
        command: PublishableExtractionCommand,
        *,
        readback: bool,
    ) -> RuntimeReceiptVerificationContext:
        return RuntimeReceiptVerificationContext(
            admission_commitment_sha256=command.admission_commitment_sha256,
            operation_id_sha256=command.operation_id_sha256,
            unit_identity_sha256=command.unit_identity_sha256,
            unit_sha256=command.unit_sha256,
            route_sha256=command.route_sha256,
            scope_sha256=command.scope_sha256,
            readback_only=readback,
        )

    def _validate_ledger_terminal(
        self,
        terminal: ManagedFullRunExtractionTerminal,
    ) -> None:
        context = self._authority.ledger_context
        if (
            type(terminal) is not ManagedFullRunExtractionTerminal
            or terminal.context_commitment_sha256 != context.commitment_sha256
            or terminal.receipt_count != context.expected_receipt_count
        ):
            _fail("extraction_ledger_terminal_divergent")

    def _run_terminal(
        self,
        checkpoint: OperationJournalCheckpoint,
        ledger: ManagedFullRunExtractionTerminal,
    ) -> PublishableExtractionRunTerminal:
        authority = self._authority
        context = authority.ledger_context
        facts = checkpoint.facts
        if (
            checkpoint.run.phase is not OperationRunPhase.SEALED
            or facts.committed_count != context.expected_receipt_count
            or facts.pending_count
            or facts.dispatched_count
            or facts.outcome_unknown_count
            or checkpoint.run.head_event_sha256 is None
            or checkpoint.run.identity != authority.journal_identity
        ):
            _fail("extraction_journal_terminal_divergent")
        return PublishableExtractionRunTerminal(
            profile_id=context.profile_id,
            run_id_sha256=context.run_id_sha256,
            binding_commitment_sha256=context.binding_commitment_sha256,
            methodology_commitment_sha256=context.methodology_commitment_sha256,
            admission_commitment_sha256=context.admission_commitment_sha256,
            ingestion_root_sha256=context.ingestion_root_sha256,
            a1_terminal_commitment_sha256=context.a1_terminal_commitment_sha256,
            a1_manifest_context_sha256=context.a1_manifest_context_sha256,
            runtime_binding_commitment_sha256=context.runtime_binding_commitment_sha256,
            scheduler_bridge_runtime_authority_sha256=(
                authority.scheduler_bridge_runtime_authority_sha256
            ),
            preparation_receipt_sha256=authority.preparation_receipt_sha256,
            dataset_sha256=authority.dataset_sha256,
            a2_terminal_commitment_sha256=authority.a2_terminal_commitment_sha256,
            expected_receipt_count=context.expected_receipt_count,
            journal_manifest_commitment_sha256=(authority.operation_manifest.commitment_sha256),
            journal_state_commitment_sha256=facts.state_commitment_sha256,
            journal_head_event_sha256=checkpoint.run.head_event_sha256,
            ledger_terminal=ledger,
        )

    def _advance_result(
        self,
        phase: PublishableExtractionAdvancePhase,
        *,
        checkpoint: OperationJournalCheckpoint,
        operation_ordinal: int | None = None,
        terminal: PublishableExtractionRunTerminal | None = None,
    ) -> PublishableExtractionAdvance:
        snapshot = self._stores.journal_service.checkpoint_snapshot(checkpoint)
        return PublishableExtractionAdvance(
            phase=phase,
            journal_snapshot=snapshot,
            operation_ordinal=operation_ordinal,
            terminal=terminal,
        )

    def _require_open(self) -> None:
        if self._closed:
            _fail("extraction_worker_closed")


__all__ = (
    "MANAGED_MEM0_EXTRACTION_NAMESPACE",
    "MANAGED_MEM0_EXTRACTION_OPERATION_KIND",
    "OpenedPublishableExtractionStores",
    "PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA",
    "PUBLISHABLE_EXTRACTION_WORKER_SCHEMA",
    "PublishableExtractionAdvance",
    "PublishableExtractionAdvancePhase",
    "PublishableExtractionCommand",
    "PublishableExtractionOneShotPort",
    "PublishableExtractionOperationReceiptIssuerPort",
    "PublishableExtractionRunAuthority",
    "PublishableExtractionRunTerminal",
    "PublishableExtractionWorkerError",
    "PublishableFullExtractionWorker",
)
