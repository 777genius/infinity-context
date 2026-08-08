"""Application state machine for resumable manifest-bound operations."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from infinity_context_server.resumable_operation_journal.domain import (
    OPERATION_JOURNAL_SCHEMA_VERSION,
    DispatchPreparation,
    LogicalOperationIdentity,
    OperationEvent,
    OperationJournalError,
    OperationJournalSnapshot,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    OperationResumeResult,
    OperationRunIdentity,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    RetryDisposition,
    VerifiedOperationReceipt,
    create_operation_event,
)
from infinity_context_server.resumable_operation_journal.ports import (
    OperationJournalPort,
    OperationJournalSignerPort,
    OperationJournalTransactionPort,
    OperationManifestPolicyPort,
    OperationNotificationPort,
    OperationReceiptVerifierPort,
)
from infinity_context_server.resumable_operation_journal.replay import (
    replay_operation_events,
)


@final
class NullOperationNotification:
    def deliver(self, event: OperationEvent) -> None:
        del event


@final
class AllowAllOperationManifestPolicy:
    """Minimal generic policy; compositions should normally inject a stricter one."""

    def validate(self, *, identity: OperationRunIdentity, manifest: OperationManifest) -> None:
        del identity, manifest


@final
class ResumableOperationJournalService:
    """Coordinate two-transition operations without calling providers in transactions."""

    def __init__(
        self,
        *,
        journal: OperationJournalPort,
        signer: OperationJournalSignerPort,
        manifest_policy: OperationManifestPolicyPort,
        receipt_verifier: OperationReceiptVerifierPort,
        notifications: OperationNotificationPort,
    ) -> None:
        self._journal = journal
        self._signer = signer
        self._manifest_policy = manifest_policy
        self._receipt_verifier = receipt_verifier
        self._notifications = notifications

    def initialize(
        self, identity: OperationRunIdentity, manifest: OperationManifest
    ) -> OperationRunState:
        if type(identity) is not OperationRunIdentity or type(manifest) is not OperationManifest:
            raise OperationJournalError("operation_journal_initialize_input_invalid")
        self._assert_manifest_binding(identity, manifest)
        self._manifest_policy.validate(identity=identity, manifest=manifest)
        self._assert_runtime_binding(identity)
        with self._journal.write_transaction() as transaction:
            existing = transaction.get_run(identity.run_id)
            if existing is None:
                transaction.put_run(OperationRunState(identity=identity))
                transaction.put_manifest(manifest)
                result = self._append_event(
                    transaction,
                    OperationRunState(identity=identity),
                    event_type="run_initialized",
                    logical_operation_id=None,
                    payload=identity.commitment_payload(),
                    notify=True,
                )
            else:
                if existing.identity != identity:
                    raise OperationJournalError("operation_journal_run_identity_divergent")
                self._verify_replay(transaction, existing)
                persisted = OperationManifest(
                    tuple(transaction.iter_manifest(run_id=identity.run_id))
                )
                if persisted != manifest:
                    raise OperationJournalError("operation_journal_manifest_divergent")
                result = existing
        self.retry_pending_notifications(identity.run_id)
        return result

    def prepare_dispatch(
        self,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
    ) -> DispatchPreparation:
        """Durably cross the dispatch boundary before external work starts."""

        if type(identity) is not LogicalOperationIdentity or not isinstance(
            request_commitment_sha256, str
        ):
            raise OperationJournalError("operation_journal_dispatch_input_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            self._require_manifest_identity(transaction, identity)
            current = transaction.get_operation(
                run_id=identity.run_id,
                logical_operation_id=identity.logical_operation_id,
            )
            if current is not None and current.request_commitment_sha256 not in (
                None,
                request_commitment_sha256,
            ):
                raise OperationJournalError("operation_journal_request_binding_immutable")
            if current is not None and current.phase in (
                OperationPhase.DISPATCHED,
                OperationPhase.COMMITTED,
            ):
                result = DispatchPreparation(state=current, should_dispatch=False)
            else:
                if current is not None and current.phase is OperationPhase.OUTCOME_UNKNOWN:
                    raise OperationJournalError("operation_journal_outcome_unknown_quarantined")
                if run.phase is OperationRunPhase.SEALED:
                    raise OperationJournalError("operation_journal_run_not_dispatchable")
                state = OperationState(
                    identity=identity,
                    phase=OperationPhase.DISPATCHED,
                    request_commitment_sha256=request_commitment_sha256,
                )
                transaction.put_operation(state)
                self._append_event(
                    transaction,
                    run,
                    event_type="operation_dispatched",
                    logical_operation_id=identity.logical_operation_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "request_commitment_sha256": request_commitment_sha256,
                        "retry_disposition": identity.retry_disposition.value,
                    },
                    notify=False,
                )
                result = DispatchPreparation(state=state, should_dispatch=True)
        return result

    def prepare_dispatch_batch(
        self,
        batch: tuple[tuple[LogicalOperationIdentity, str], ...],
    ) -> tuple[DispatchPreparation, ...]:
        """Atomically cross the dispatch boundary for one exact manifest batch."""

        if (
            type(batch) is not tuple
            or not batch
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not LogicalOperationIdentity
                or not isinstance(item[1], str)
                for item in batch
            )
        ):
            raise OperationJournalError("operation_journal_dispatch_batch_input_invalid")

        identities = tuple(item[0] for item in batch)
        request_commitments = tuple(item[1] for item in batch)
        run_id = identities[0].run_id
        if any(identity.run_id != run_id for identity in identities):
            raise OperationJournalError("operation_journal_dispatch_batch_run_divergent")

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            manifest = tuple(transaction.iter_manifest(run_id=run_id))
            if identities != manifest:
                raise OperationJournalError("operation_journal_dispatch_batch_manifest_divergent")

            current_states = tuple(
                transaction.get_operation(
                    run_id=run_id,
                    logical_operation_id=identity.logical_operation_id,
                )
                for identity in identities
            )
            for identity, request_commitment, current in zip(
                identities, request_commitments, current_states, strict=True
            ):
                if current is not None and current.identity != identity:
                    raise OperationJournalError(
                        "operation_journal_dispatch_batch_manifest_divergent"
                    )
                if current is not None and current.request_commitment_sha256 not in (
                    None,
                    request_commitment,
                ):
                    raise OperationJournalError("operation_journal_request_binding_immutable")
                if current is not None and current.phase is OperationPhase.OUTCOME_UNKNOWN:
                    raise OperationJournalError("operation_journal_outcome_unknown_quarantined")

            fresh = tuple(
                current is None or current.phase is OperationPhase.PENDING
                for current in current_states
            )
            replay = tuple(
                current is not None
                and current.phase in (OperationPhase.DISPATCHED, OperationPhase.COMMITTED)
                for current in current_states
            )
            if all(replay):
                return tuple(
                    DispatchPreparation(state=current, should_dispatch=False)
                    for current in current_states
                    if current is not None
                )
            if not all(fresh):
                raise OperationJournalError("operation_journal_dispatch_batch_mixed_state")
            if run.phase is OperationRunPhase.SEALED:
                raise OperationJournalError("operation_journal_run_not_dispatchable")

            prepared: list[DispatchPreparation] = []
            updated_run = run
            for identity, request_commitment in zip(identities, request_commitments, strict=True):
                state = OperationState(
                    identity=identity,
                    phase=OperationPhase.DISPATCHED,
                    request_commitment_sha256=request_commitment,
                )
                transaction.put_operation(state)
                updated_run = self._append_event(
                    transaction,
                    updated_run,
                    event_type="operation_dispatched",
                    logical_operation_id=identity.logical_operation_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "request_commitment_sha256": request_commitment,
                        "retry_disposition": identity.retry_disposition.value,
                    },
                    notify=False,
                )
                prepared.append(DispatchPreparation(state=state, should_dispatch=True))
            return tuple(prepared)

    def commit(
        self, identity: LogicalOperationIdentity, receipt: OperationReceipt
    ) -> OperationState:
        """Persist verified evidence after the external operation has returned."""

        if type(identity) is not LogicalOperationIdentity or type(receipt) is not OperationReceipt:
            raise OperationJournalError("operation_journal_commit_input_invalid")
        if (
            receipt.run_id != identity.run_id
            or receipt.logical_operation_id != identity.logical_operation_id
        ):
            raise OperationJournalError("operation_journal_receipt_identity_mismatch")
        verified = self._receipt_verifier.verify(identity=identity, receipt=receipt)
        if type(verified) is not VerifiedOperationReceipt or verified.receipt != receipt:
            raise OperationJournalError("operation_journal_receipt_verification_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            current = self._require_operation(transaction, identity)
            if receipt.request_commitment_sha256 != current.request_commitment_sha256:
                raise OperationJournalError("operation_journal_receipt_request_mismatch")
            if current.phase is OperationPhase.COMMITTED:
                if (
                    current.receipt != receipt
                    or current.verifier_key_id != verified.verifier_key_id
                    or current.verification_commitment_sha256
                    != verified.verification_commitment_sha256
                ):
                    raise OperationJournalError("operation_journal_receipt_replay_divergent")
                result = current
            else:
                late_idempotent = (
                    current.phase is OperationPhase.PENDING
                    and current.identity.retry_disposition is RetryDisposition.IDEMPOTENT_REPLAY
                    and current.request_commitment_sha256 is not None
                    and run.phase is OperationRunPhase.ACTIVE
                )
                if (
                    current.phase
                    not in (
                        OperationPhase.DISPATCHED,
                        OperationPhase.OUTCOME_UNKNOWN,
                    )
                    and not late_idempotent
                ):
                    raise OperationJournalError("operation_journal_commit_requires_dispatch")
                if run.phase is OperationRunPhase.SEALED:
                    raise OperationJournalError("operation_journal_run_sealed")
                result = OperationState(
                    identity=identity,
                    phase=OperationPhase.COMMITTED,
                    request_commitment_sha256=current.request_commitment_sha256,
                    receipt=receipt,
                    verifier_key_id=verified.verifier_key_id,
                    verification_commitment_sha256=verified.verification_commitment_sha256,
                )
                transaction.put_operation(result)
                transaction.put_receipt(state=result, verified=verified)
                updated = self._append_event(
                    transaction,
                    run,
                    event_type="operation_committed",
                    logical_operation_id=identity.logical_operation_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "receipt_id": receipt.receipt_id,
                        "request_commitment_sha256": receipt.request_commitment_sha256,
                        "result_commitment_sha256": receipt.result_commitment_sha256,
                        "verification_commitment_sha256": (verified.verification_commitment_sha256),
                        "verifier_key_id": verified.verifier_key_id,
                    },
                    notify=False,
                )
                counts = transaction.phase_counts(run_id=identity.run_id)
                if (
                    updated.phase is OperationRunPhase.RECONCILIATION_REQUIRED
                    and counts.get(OperationPhase.OUTCOME_UNKNOWN.value, 0) == 0
                ):
                    self._append_event(
                        transaction,
                        replace(updated, phase=OperationRunPhase.ACTIVE),
                        event_type="reconciliation_cleared",
                        logical_operation_id=None,
                        payload={"resolved_logical_operation_id": identity.logical_operation_id},
                        notify=True,
                    )
        self.retry_pending_notifications(identity.run_id)
        return result

    def resume(self, run_id: str) -> OperationResumeResult:
        """Replay idempotent work and quarantine all outcome-ambiguous work."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_replay(transaction, run)
            if run.phase is OperationRunPhase.SEALED:
                result = OperationResumeResult(run=run, replayable_count=0, outcome_unknown_count=0)
            else:
                updated = run
                replayable_count = 0
                for current in transaction.iter_operations(run_id=run_id):
                    if current.phase is not OperationPhase.DISPATCHED:
                        continue
                    if current.identity.retry_disposition is RetryDisposition.IDEMPOTENT_REPLAY:
                        replacement = OperationState(
                            identity=current.identity,
                            request_commitment_sha256=current.request_commitment_sha256,
                        )
                        event_type = "operation_replay_scheduled"
                        replayable_count += 1
                    else:
                        replacement = OperationState(
                            identity=current.identity,
                            phase=OperationPhase.OUTCOME_UNKNOWN,
                            request_commitment_sha256=current.request_commitment_sha256,
                        )
                        event_type = "operation_outcome_unknown"
                    transaction.put_operation(replacement)
                    updated = self._append_event(
                        transaction,
                        updated,
                        event_type=event_type,
                        logical_operation_id=current.identity.logical_operation_id,
                        payload={
                            "ordinal": current.identity.ordinal,
                            "reason": "restart_without_verified_receipt",
                        },
                        notify=False,
                    )
                counts = transaction.phase_counts(run_id=run_id)
                unknown_count = counts.get(OperationPhase.OUTCOME_UNKNOWN.value, 0)
                if unknown_count and updated.phase is not OperationRunPhase.RECONCILIATION_REQUIRED:
                    updated = self._append_event(
                        transaction,
                        replace(updated, phase=OperationRunPhase.RECONCILIATION_REQUIRED),
                        event_type="reconciliation_required",
                        logical_operation_id=None,
                        payload={"outcome_unknown_count": unknown_count},
                        notify=True,
                    )
                result = OperationResumeResult(
                    run=updated,
                    replayable_count=replayable_count,
                    outcome_unknown_count=unknown_count,
                )
        self.retry_pending_notifications(run_id)
        return result

    def seal(self, run_id: str) -> OperationRunState:
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_replay(transaction, run)
            if run.phase is OperationRunPhase.RECONCILIATION_REQUIRED:
                raise OperationJournalError("operation_journal_seal_reconciliation_required")
            counts = transaction.phase_counts(run_id=run_id)
            committed_count = counts.get(OperationPhase.COMMITTED.value, 0)
            if committed_count != run.identity.expected_operation_count:
                raise OperationJournalError("operation_journal_seal_incomplete")
            if run.phase is OperationRunPhase.SEALED:
                result = run
            else:
                result = self._append_event(
                    transaction,
                    replace(run, phase=OperationRunPhase.SEALED),
                    event_type="run_sealed",
                    logical_operation_id=None,
                    payload={
                        "committed_count": run.identity.expected_operation_count,
                        "state_commitment_sha256": transaction.state_commitment(run_id=run_id),
                    },
                    notify=True,
                )
        self.retry_pending_notifications(run_id)
        return result

    def snapshot(self, run_id: str) -> OperationJournalSnapshot:
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_replay(transaction, run)
            counts = transaction.phase_counts(run_id=run_id)
            dispatched = counts.get(OperationPhase.DISPATCHED.value, 0)
            committed = counts.get(OperationPhase.COMMITTED.value, 0)
            unknown = counts.get(OperationPhase.OUTCOME_UNKNOWN.value, 0)
            return OperationJournalSnapshot(
                run=run,
                pending_count=run.identity.expected_operation_count
                - dispatched
                - committed
                - unknown,
                dispatched_count=dispatched,
                committed_count=committed,
                outcome_unknown_count=unknown,
                state_commitment_sha256=transaction.state_commitment(run_id=run_id),
            )

    def retry_pending_notifications(self, run_id: str, *, batch_size: int = 64) -> int:
        delivered = 0
        for event in self._journal.iter_pending_notifications(run_id=run_id, batch_size=batch_size):
            self._notifications.deliver(event)
            with self._journal.write_transaction() as transaction:
                transaction.mark_notification_delivered(
                    run_id=run_id, event_sha256=event.event_sha256
                )
            delivered += 1
        return delivered

    def _verify_replay(
        self, transaction: OperationJournalTransactionPort, run: OperationRunState
    ) -> None:
        manifest = OperationManifest(tuple(transaction.iter_manifest(run_id=run.identity.run_id)))
        self._assert_manifest_binding(run.identity, manifest)
        manifest_by_id = {item.logical_operation_id: item for item in manifest.operations}
        events = transaction.iter_events(run_id=run.identity.run_id)
        verification = replay_operation_events(
            events,
            run=run,
            manifest_by_id=manifest_by_id,
            signer=self._signer,
        )
        if (
            verification.event_count != run.event_count
            or verification.head_event_sha256 != run.head_event_sha256
            or verification.phase is not run.phase
            or verification.state_commitment_sha256
            != transaction.state_commitment(run_id=run.identity.run_id)
            or verification.receipt_count != transaction.receipt_count(run_id=run.identity.run_id)
            or verification.receipts_commitment_sha256
            != transaction.receipts_commitment(run_id=run.identity.run_id)
        ):
            raise OperationJournalError("operation_journal_replay_state_mismatch")

    def _append_event(
        self,
        transaction: OperationJournalTransactionPort,
        run: OperationRunState,
        *,
        event_type: str,
        logical_operation_id: str | None,
        payload: dict[str, object],
        notify: bool,
    ) -> OperationRunState:
        event = create_operation_event(
            run=run,
            event_type=event_type,
            logical_operation_id=logical_operation_id,
            payload=payload,
            signer_key_id=self._signer.key_id,
            sign=self._signer.sign,
        )
        transaction.append_event(event)
        if notify:
            transaction.enqueue_notification(event)
        updated = replace(run, event_count=event.sequence, head_event_sha256=event.event_sha256)
        transaction.put_run(updated)
        return updated

    def _require_run(
        self, transaction: OperationJournalTransactionPort, run_id: str
    ) -> OperationRunState:
        run = transaction.get_run(run_id)
        if run is None:
            raise OperationJournalError("operation_journal_run_missing")
        self._assert_runtime_binding(run.identity)
        return run

    @staticmethod
    def _require_manifest_identity(
        transaction: OperationJournalTransactionPort,
        identity: LogicalOperationIdentity,
    ) -> None:
        expected = transaction.get_manifest_operation(
            run_id=identity.run_id, ordinal=identity.ordinal
        )
        if expected != identity:
            raise OperationJournalError("operation_journal_manifest_identity_divergent")

    @staticmethod
    def _require_operation(
        transaction: OperationJournalTransactionPort,
        identity: LogicalOperationIdentity,
    ) -> OperationState:
        state = transaction.get_operation(
            run_id=identity.run_id,
            logical_operation_id=identity.logical_operation_id,
        )
        if state is None or state.identity != identity:
            raise OperationJournalError("operation_journal_operation_missing")
        return state

    def _assert_runtime_binding(self, identity: OperationRunIdentity) -> None:
        if identity.signer_key_id != self._signer.key_id:
            raise OperationJournalError("operation_journal_signer_key_binding_mismatch")
        if self._journal.schema_version != OPERATION_JOURNAL_SCHEMA_VERSION:
            raise OperationJournalError("operation_journal_schema_binding_mismatch")

    @staticmethod
    def _assert_manifest_binding(
        identity: OperationRunIdentity, manifest: OperationManifest
    ) -> None:
        if (
            manifest.run_id != identity.run_id
            or manifest.commitment_sha256 != identity.manifest_commitment_sha256
            or len(manifest.operations) != identity.expected_operation_count
        ):
            raise OperationJournalError("operation_journal_manifest_binding_mismatch")


__all__ = (
    "AllowAllOperationManifestPolicy",
    "NullOperationNotification",
    "ResumableOperationJournalService",
)
