"""Application state machine for authenticated resumable operations."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from infinity_context_server.resumable_operation_journal.commitments import initial_facts
from infinity_context_server.resumable_operation_journal.domain import (
    OPERATION_JOURNAL_SCHEMA_VERSION,
    DispatchPreparation,
    LogicalOperationIdentity,
    OperationEvent,
    OperationJournalCheckpoint,
    OperationJournalError,
    OperationJournalFacts,
    OperationJournalSnapshot,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    OperationResumeResult,
    OperationRunIdentity,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    OperationTransitionResult,
    RetryDisposition,
    VerifiedOperationReceipt,
    create_operation_event,
    operation_checkpoint_payload,
    sha256_commitment,
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
    rebuild_operation_journal_facts,
    stream_operation_manifest_commitment,
    verify_operation_event_stream,
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
    """Coordinate transitions without full scans or provider calls in transactions."""

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
        self,
        identity: OperationRunIdentity,
        manifest: OperationManifest,
    ) -> OperationRunState:
        if type(identity) is not OperationRunIdentity or type(manifest) is not OperationManifest:
            raise OperationJournalError("operation_journal_initialize_input_invalid")
        self._assert_manifest_binding(identity, manifest)
        self._manifest_policy.validate(identity=identity, manifest=manifest)
        self._assert_runtime_binding(identity)
        with self._journal.write_transaction() as transaction:
            existing = transaction.get_run(identity.run_id)
            if existing is None:
                run = OperationRunState(identity=identity)
                transaction.put_run(run)
                transaction.put_manifest(manifest)
                run = self._append_event(
                    transaction,
                    run,
                    event_type="run_initialized",
                    logical_operation_id=None,
                    payload=identity.commitment_payload(),
                    notify=True,
                )
                checkpoint = self._write_checkpoint(
                    transaction,
                    run=run,
                    facts=initial_facts(identity.expected_operation_count),
                )
            else:
                if existing.identity != identity:
                    raise OperationJournalError("operation_journal_run_identity_divergent")
                checkpoint = self._recover_transaction(transaction, existing)
                if checkpoint.run.identity.manifest_commitment_sha256 != manifest.commitment_sha256:
                    raise OperationJournalError("operation_journal_manifest_divergent")
            result = checkpoint.run
        self.retry_pending_notifications(identity.run_id)
        return result

    def current_checkpoint(self, run_id: str) -> OperationJournalCheckpoint:
        """Read the signed transition checkpoint without scanning journal history."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            return self._require_checkpoint(transaction, run=run)

    def read_checkpoint(self, run_id: str) -> OperationJournalCheckpoint:
        return self.current_checkpoint(run_id)

    def checkpoint_snapshot(
        self,
        checkpoint: OperationJournalCheckpoint,
    ) -> OperationJournalSnapshot:
        """Render a previously returned authenticated checkpoint without I/O."""

        if type(checkpoint) is not OperationJournalCheckpoint:
            raise OperationJournalError("operation_journal_checkpoint_invalid")
        self._authenticate_checkpoint(checkpoint)
        return self._snapshot(checkpoint)

    def prepare_dispatch(
        self,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
    ) -> DispatchPreparation:
        if type(identity) is not LogicalOperationIdentity or not isinstance(
            request_commitment_sha256, str
        ):
            raise OperationJournalError("operation_journal_dispatch_input_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            checkpoint = self._require_checkpoint(transaction, run=run)
            self._require_manifest_identity(transaction, identity)
            current = transaction.get_authenticated_operation(
                run_id=identity.run_id,
                ordinal=identity.ordinal,
                facts=checkpoint.facts,
            )
            candidate, payload = self._validated_dispatch_transition(
                identity=identity,
                request_commitment_sha256=request_commitment_sha256,
                current=current,
                identity_error="operation_journal_manifest_identity_divergent",
            )
            if current is not None and current.phase in (
                OperationPhase.DISPATCHED,
                OperationPhase.COMMITTED,
            ):
                return DispatchPreparation(
                    state=current,
                    should_dispatch=False,
                    checkpoint=checkpoint,
                )
            if run.phase is OperationRunPhase.SEALED:
                raise OperationJournalError("operation_journal_run_not_dispatchable")
            facts = transaction.apply_operation_transition(
                state=candidate,
                verified=None,
                expected_facts=checkpoint.facts,
            )
            run = self._append_event(
                transaction,
                run,
                event_type="operation_dispatched",
                logical_operation_id=identity.logical_operation_id,
                payload=payload,
                notify=False,
            )
            checkpoint = self._write_checkpoint(transaction, run=run, facts=facts)
            return DispatchPreparation(
                state=candidate,
                should_dispatch=True,
                checkpoint=checkpoint,
            )

    def prepare_dispatch_batch(
        self,
        batch: tuple[tuple[LogicalOperationIdentity, str], ...],
    ) -> tuple[DispatchPreparation, ...]:
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
        run_id = batch[0][0].run_id
        if any(item[0].run_id != run_id for item in batch):
            raise OperationJournalError("operation_journal_dispatch_batch_run_divergent")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            checkpoint = self._require_checkpoint(transaction, run=run)
            if len(batch) != run.identity.expected_operation_count:
                raise OperationJournalError("operation_journal_dispatch_batch_manifest_divergent")
            currents: list[OperationState | None] = []
            transitions: list[tuple[OperationState, dict[str, object]]] = []
            for ordinal, (identity, request_commitment) in enumerate(batch):
                if identity.ordinal != ordinal:
                    raise OperationJournalError(
                        "operation_journal_dispatch_batch_manifest_divergent"
                    )
                self._require_manifest_identity(transaction, identity)
                try:
                    current = transaction.get_authenticated_operation(
                        run_id=run_id,
                        ordinal=ordinal,
                        facts=checkpoint.facts,
                    )
                except OperationJournalError as error:
                    if run.phase is OperationRunPhase.SEALED:
                        raise OperationJournalError(
                            "operation_journal_run_not_dispatchable_"
                            "projection_authentication_invalid"
                        ) from error
                    raise
                currents.append(current)
                transitions.append(
                    self._validated_dispatch_transition(
                        identity=identity,
                        request_commitment_sha256=request_commitment,
                        current=current,
                        identity_error=("operation_journal_dispatch_batch_manifest_divergent"),
                    )
                )
            fresh = [
                current is None or current.phase is OperationPhase.PENDING for current in currents
            ]
            replay = [
                current is not None
                and current.phase in (OperationPhase.DISPATCHED, OperationPhase.COMMITTED)
                for current in currents
            ]
            if all(replay):
                return tuple(
                    DispatchPreparation(
                        state=current,
                        should_dispatch=False,
                        checkpoint=checkpoint,
                    )
                    for current in currents
                    if current is not None
                )
            if not all(fresh):
                raise OperationJournalError("operation_journal_dispatch_batch_mixed_state")
            if run.phase is OperationRunPhase.SEALED:
                raise OperationJournalError("operation_journal_run_not_dispatchable")
            facts = checkpoint.facts
            prepared: list[OperationState] = []
            for state, payload in transitions:
                facts = transaction.apply_operation_transition(
                    state=state,
                    verified=None,
                    expected_facts=facts,
                )
                run = self._append_event(
                    transaction,
                    run,
                    event_type="operation_dispatched",
                    logical_operation_id=state.identity.logical_operation_id,
                    payload=payload,
                    notify=False,
                )
                prepared.append(state)
            checkpoint = self._write_checkpoint(transaction, run=run, facts=facts)
            return tuple(
                DispatchPreparation(
                    state=state,
                    should_dispatch=True,
                    checkpoint=checkpoint,
                )
                for state in prepared
            )

    def commit(
        self,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> OperationState:
        return self.commit_with_checkpoint(identity, receipt).state

    def commit_with_checkpoint(
        self,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> OperationTransitionResult:
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
            checkpoint = self._require_checkpoint(transaction, run=run)
            current = self._require_authenticated_operation(
                transaction,
                identity=identity,
                facts=checkpoint.facts,
            )
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
                result = OperationTransitionResult(state=current, checkpoint=checkpoint)
            else:
                late_idempotent = (
                    current.phase is OperationPhase.PENDING
                    and current.identity.retry_disposition is RetryDisposition.IDEMPOTENT_REPLAY
                    and current.request_commitment_sha256 is not None
                    and run.phase is OperationRunPhase.ACTIVE
                )
                if (
                    current.phase not in (OperationPhase.DISPATCHED, OperationPhase.OUTCOME_UNKNOWN)
                    and not late_idempotent
                ):
                    raise OperationJournalError("operation_journal_commit_requires_dispatch")
                if run.phase is OperationRunPhase.SEALED:
                    raise OperationJournalError("operation_journal_run_sealed")
                state = OperationState(
                    identity=identity,
                    phase=OperationPhase.COMMITTED,
                    request_commitment_sha256=current.request_commitment_sha256,
                    receipt=receipt,
                    verifier_key_id=verified.verifier_key_id,
                    verification_commitment_sha256=(verified.verification_commitment_sha256),
                )
                facts = transaction.apply_operation_transition(
                    state=state,
                    verified=verified,
                    expected_facts=checkpoint.facts,
                )
                run = self._append_event(
                    transaction,
                    run,
                    event_type="operation_committed",
                    logical_operation_id=identity.logical_operation_id,
                    payload=self._commit_payload(identity, verified),
                    notify=False,
                )
                if (
                    run.phase is OperationRunPhase.RECONCILIATION_REQUIRED
                    and facts.outcome_unknown_count == 0
                ):
                    run = self._append_event(
                        transaction,
                        replace(run, phase=OperationRunPhase.ACTIVE),
                        event_type="reconciliation_cleared",
                        logical_operation_id=None,
                        payload={"resolved_logical_operation_id": identity.logical_operation_id},
                        notify=True,
                    )
                checkpoint = self._write_checkpoint(transaction, run=run, facts=facts)
                result = OperationTransitionResult(state=state, checkpoint=checkpoint)
        self.retry_pending_notifications(identity.run_id)
        return result

    def quarantine_dispatched(
        self,
        identity: LogicalOperationIdentity,
    ) -> OperationTransitionResult:
        """Quarantine exactly one dispatched identity without replaying the run."""

        if type(identity) is not LogicalOperationIdentity:
            raise OperationJournalError("operation_journal_quarantine_input_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            checkpoint = self._require_checkpoint(transaction, run=run)
            self._require_manifest_identity(transaction, identity)
            current = self._require_authenticated_operation(
                transaction,
                identity=identity,
                facts=checkpoint.facts,
            )
            if current.phase is OperationPhase.OUTCOME_UNKNOWN:
                return OperationTransitionResult(state=current, checkpoint=checkpoint)
            if (
                current.phase is not OperationPhase.DISPATCHED
                or current.identity.retry_disposition is not RetryDisposition.QUARANTINE_UNKNOWN
                or run.phase is OperationRunPhase.SEALED
            ):
                raise OperationJournalError("operation_journal_quarantine_requires_dispatch")
            state = OperationState(
                identity=current.identity,
                phase=OperationPhase.OUTCOME_UNKNOWN,
                request_commitment_sha256=current.request_commitment_sha256,
            )
            facts = transaction.apply_operation_transition(
                state=state,
                verified=None,
                expected_facts=checkpoint.facts,
            )
            run = self._append_event(
                transaction,
                run,
                event_type="operation_outcome_unknown",
                logical_operation_id=identity.logical_operation_id,
                payload={
                    "ordinal": identity.ordinal,
                    "reason": "restart_without_verified_receipt",
                },
                notify=False,
            )
            if run.phase is OperationRunPhase.ACTIVE:
                run = self._append_event(
                    transaction,
                    replace(run, phase=OperationRunPhase.RECONCILIATION_REQUIRED),
                    event_type="reconciliation_required",
                    logical_operation_id=None,
                    payload={"outcome_unknown_count": facts.outcome_unknown_count},
                    notify=True,
                )
            checkpoint = self._write_checkpoint(transaction, run=run, facts=facts)
            result = OperationTransitionResult(state=state, checkpoint=checkpoint)
        self.retry_pending_notifications(identity.run_id)
        return result

    def recover(self, run_id: str) -> OperationResumeResult:
        """Audit streams once, then normalize every dispatched operation in pages."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            checkpoint = self._recover_transaction(transaction, run)
            if run.phase is OperationRunPhase.SEALED:
                result = OperationResumeResult(
                    run=run,
                    replayable_count=0,
                    outcome_unknown_count=0,
                    checkpoint=checkpoint,
                )
            else:
                facts = checkpoint.facts
                replayable_count = 0
                after_ordinal = -1
                while page := transaction.operation_phase_page(
                    run_id=run_id,
                    phases=(OperationPhase.DISPATCHED.value,),
                    after_ordinal=after_ordinal,
                    batch_size=512,
                ):
                    for current in page:
                        if current.identity.retry_disposition is RetryDisposition.IDEMPOTENT_REPLAY:
                            replacement = OperationState(
                                identity=current.identity,
                                request_commitment_sha256=(current.request_commitment_sha256),
                            )
                            event_type = "operation_replay_scheduled"
                            replayable_count += 1
                        else:
                            replacement = OperationState(
                                identity=current.identity,
                                phase=OperationPhase.OUTCOME_UNKNOWN,
                                request_commitment_sha256=(current.request_commitment_sha256),
                            )
                            event_type = "operation_outcome_unknown"
                        facts = transaction.apply_operation_transition(
                            state=replacement,
                            verified=None,
                            expected_facts=facts,
                        )
                        run = self._append_event(
                            transaction,
                            run,
                            event_type=event_type,
                            logical_operation_id=(current.identity.logical_operation_id),
                            payload={
                                "ordinal": current.identity.ordinal,
                                "reason": "restart_without_verified_receipt",
                            },
                            notify=False,
                        )
                    after_ordinal = page[-1].identity.ordinal
                if (
                    facts.outcome_unknown_count
                    and run.phase is not OperationRunPhase.RECONCILIATION_REQUIRED
                ):
                    run = self._append_event(
                        transaction,
                        replace(run, phase=OperationRunPhase.RECONCILIATION_REQUIRED),
                        event_type="reconciliation_required",
                        logical_operation_id=None,
                        payload={"outcome_unknown_count": facts.outcome_unknown_count},
                        notify=True,
                    )
                checkpoint = self._write_checkpoint(transaction, run=run, facts=facts)
                result = OperationResumeResult(
                    run=run,
                    replayable_count=replayable_count,
                    outcome_unknown_count=facts.outcome_unknown_count,
                    checkpoint=checkpoint,
                )
        self.retry_pending_notifications(run_id)
        return result

    def resume(self, run_id: str) -> OperationResumeResult:
        return self.recover(run_id)

    def seal_with_checkpoint(self, run_id: str) -> OperationJournalCheckpoint:
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            checkpoint = self._recover_transaction(transaction, run)
            facts = checkpoint.facts
            if run.phase is OperationRunPhase.RECONCILIATION_REQUIRED:
                raise OperationJournalError("operation_journal_seal_reconciliation_required")
            if facts.committed_count != run.identity.expected_operation_count:
                raise OperationJournalError("operation_journal_seal_incomplete")
            if run.phase is OperationRunPhase.SEALED:
                result = checkpoint
            else:
                run = self._append_event(
                    transaction,
                    replace(run, phase=OperationRunPhase.SEALED),
                    event_type="run_sealed",
                    logical_operation_id=None,
                    payload={
                        "committed_count": run.identity.expected_operation_count,
                        "state_commitment_sha256": facts.state_commitment_sha256,
                    },
                    notify=True,
                )
                result = self._write_checkpoint(transaction, run=run, facts=facts)
        self.retry_pending_notifications(run_id)
        return result

    def seal(self, run_id: str) -> OperationRunState:
        return self.seal_with_checkpoint(run_id).run

    def snapshot(self, run_id: str) -> OperationJournalSnapshot:
        """Perform the explicit full audit and return its authenticated checkpoint."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            checkpoint = self._recover_transaction(transaction, run)
        return self._snapshot(checkpoint)

    def prove_pristine(
        self,
        identity: OperationRunIdentity,
        manifest: OperationManifest,
    ) -> str:
        if type(identity) is not OperationRunIdentity or type(manifest) is not OperationManifest:
            raise OperationJournalError("operation_journal_pristine_input_invalid")
        self._assert_manifest_binding(identity, manifest)
        self._manifest_policy.validate(identity=identity, manifest=manifest)
        self._assert_runtime_binding(identity)
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            checkpoint = self._recover_transaction(transaction, run)
            facts = checkpoint.facts
            if (
                run.identity != identity
                or run.phase is not OperationRunPhase.ACTIVE
                or run.event_count != 1
                or facts.pending_count != identity.expected_operation_count
                or facts.committed_count
                or facts.dispatched_count
                or facts.outcome_unknown_count
                or facts.receipt_count
            ):
                raise OperationJournalError("operation_journal_not_pristine")
            return sha256_commitment(
                {
                    "head_event_sha256": run.head_event_sha256,
                    "identity": identity.commitment_payload(),
                    "manifest_commitment_sha256": manifest.commitment_sha256,
                    "schema_version": "operation-journal-pristine-proof.v1",
                    "state_commitment_sha256": facts.state_commitment_sha256,
                }
            )

    def retry_pending_notifications(self, run_id: str, *, batch_size: int = 64) -> int:
        delivered = 0
        for event in self._journal.iter_pending_notifications(
            run_id=run_id,
            batch_size=batch_size,
        ):
            self._notifications.deliver(event)
            with self._journal.write_transaction() as transaction:
                transaction.mark_notification_delivered(
                    run_id=run_id,
                    event_sha256=event.event_sha256,
                )
            delivered += 1
        return delivered

    def _recover_transaction(
        self,
        transaction: OperationJournalTransactionPort,
        run: OperationRunState,
    ) -> OperationJournalCheckpoint:
        checkpoint = transaction.get_checkpoint(run_id=run.identity.run_id)
        if checkpoint is None:
            raise OperationJournalError("operation_journal_checkpoint_missing")
        self._authenticate_checkpoint(checkpoint)
        manifest_commitment = stream_operation_manifest_commitment(
            transaction.iter_manifest(run_id=run.identity.run_id, batch_size=512),
            expected_run_id=run.identity.run_id,
            expected_operation_count=run.identity.expected_operation_count,
        )
        if manifest_commitment != run.identity.manifest_commitment_sha256:
            raise OperationJournalError("operation_journal_manifest_binding_mismatch")
        facts = rebuild_operation_journal_facts(
            transaction.iter_operations(run_id=run.identity.run_id, batch_size=512),
            transaction.iter_verified_receipts(
                run_id=run.identity.run_id,
                batch_size=512,
            ),
            expected_run_id=run.identity.run_id,
            expected_operation_count=run.identity.expected_operation_count,
        )
        if facts != checkpoint.facts:
            raise OperationJournalError("operation_journal_replay_state_mismatch")
        verification = verify_operation_event_stream(
            transaction.iter_events(run_id=run.identity.run_id, batch_size=512),
            run=run,
            signer=self._signer,
            checkpoint=checkpoint,
        )
        if checkpoint.run != run:
            self._raise_uncheckpointed_tail(
                verification,
                checkpoint_phase=checkpoint.run.phase,
            )
            raise OperationJournalError("operation_journal_checkpoint_state_mismatch")
        if (
            verification.event_count != run.event_count
            or verification.head_event_sha256 != run.head_event_sha256
        ):
            raise OperationJournalError("operation_journal_event_chain_invalid")
        return checkpoint

    @staticmethod
    def _raise_uncheckpointed_tail(
        verification: object,
        *,
        checkpoint_phase: OperationRunPhase,
    ) -> None:
        event = getattr(verification, "last_extra_event", None)
        if checkpoint_phase is OperationRunPhase.SEALED and isinstance(event, OperationEvent):
            raise OperationJournalError("operation_journal_post_seal_event")
        if not isinstance(event, OperationEvent):
            event = getattr(verification, "first_extra_event", None)
        if not isinstance(event, OperationEvent):
            return
        mapping = {
            "run_initialized": "operation_journal_initialize_replay_invalid",
            "operation_dispatched": "operation_journal_dispatch_replay_invalid",
            "operation_replay_scheduled": ("operation_journal_replay_schedule_invalid"),
            "operation_outcome_unknown": "operation_journal_unknown_replay_invalid",
            "operation_committed": "operation_journal_commit_replay_invalid",
            "reconciliation_required": ("operation_journal_reconciliation_replay_invalid"),
            "reconciliation_cleared": ("operation_journal_reconciliation_replay_invalid"),
            "run_sealed": "operation_journal_seal_replay_invalid",
        }
        raise OperationJournalError(
            mapping.get(event.event_type, "operation_journal_event_type_unknown")
        )

    def _require_checkpoint(
        self,
        transaction: OperationJournalTransactionPort,
        *,
        run: OperationRunState,
    ) -> OperationJournalCheckpoint:
        checkpoint = transaction.get_checkpoint(run_id=run.identity.run_id)
        if checkpoint is None:
            raise OperationJournalError("operation_journal_checkpoint_missing")
        self._authenticate_checkpoint(checkpoint)
        if checkpoint.run != run:
            raise OperationJournalError("operation_journal_checkpoint_state_mismatch")
        return checkpoint

    def _authenticate_checkpoint(self, checkpoint: OperationJournalCheckpoint) -> None:
        if checkpoint.signer_key_id != self._signer.key_id or not self._signer.verify(
            checkpoint.checkpoint_sha256.encode("ascii"),
            checkpoint.signature,
        ):
            raise OperationJournalError("operation_journal_checkpoint_authentication_invalid")
        self._assert_runtime_binding(checkpoint.run.identity)

    def _write_checkpoint(
        self,
        transaction: OperationJournalTransactionPort,
        *,
        run: OperationRunState,
        facts: OperationJournalFacts,
    ) -> OperationJournalCheckpoint:
        payload = operation_checkpoint_payload(
            run=run,
            facts=facts,
            signer_key_id=self._signer.key_id,
        )
        commitment = sha256_commitment(payload)
        checkpoint = OperationJournalCheckpoint(
            run=run,
            facts=facts,
            signer_key_id=self._signer.key_id,
            checkpoint_sha256=commitment,
            signature=self._signer.sign(commitment.encode("ascii")),
        )
        transaction.put_checkpoint(checkpoint)
        return checkpoint

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
        updated = replace(
            run,
            event_count=event.sequence,
            head_event_sha256=event.event_sha256,
        )
        transaction.put_run(updated)
        return updated

    def _require_run(
        self,
        transaction: OperationJournalTransactionPort,
        run_id: str,
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
            run_id=identity.run_id,
            ordinal=identity.ordinal,
        )
        if expected != identity:
            raise OperationJournalError("operation_journal_manifest_identity_divergent")

    @staticmethod
    def _require_authenticated_operation(
        transaction: OperationJournalTransactionPort,
        *,
        identity: LogicalOperationIdentity,
        facts: OperationJournalFacts,
    ) -> OperationState:
        state = transaction.get_authenticated_operation(
            run_id=identity.run_id,
            ordinal=identity.ordinal,
            facts=facts,
        )
        if state is None or state.identity != identity:
            raise OperationJournalError("operation_journal_operation_missing")
        return state

    @staticmethod
    def _validated_dispatch_transition(
        *,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
        current: OperationState | None,
        identity_error: str,
    ) -> tuple[OperationState, dict[str, object]]:
        if current is not None and current.identity != identity:
            raise OperationJournalError(identity_error)
        if current is not None and current.request_commitment_sha256 not in (
            None,
            request_commitment_sha256,
        ):
            raise OperationJournalError("operation_journal_request_binding_immutable")
        if current is not None and current.phase is OperationPhase.OUTCOME_UNKNOWN:
            raise OperationJournalError("operation_journal_outcome_unknown_quarantined")
        state = OperationState(
            identity=identity,
            phase=OperationPhase.DISPATCHED,
            request_commitment_sha256=request_commitment_sha256,
        )
        return state, {
            "ordinal": identity.ordinal,
            "request_commitment_sha256": request_commitment_sha256,
            "retry_disposition": identity.retry_disposition.value,
        }

    @staticmethod
    def _commit_payload(
        identity: LogicalOperationIdentity,
        verified: VerifiedOperationReceipt,
    ) -> dict[str, object]:
        receipt = verified.receipt
        return {
            "ordinal": identity.ordinal,
            "receipt_id": receipt.receipt_id,
            "request_commitment_sha256": receipt.request_commitment_sha256,
            "result_commitment_sha256": receipt.result_commitment_sha256,
            "verification_commitment_sha256": (verified.verification_commitment_sha256),
            "verifier_key_id": verified.verifier_key_id,
        }

    @staticmethod
    def _snapshot(checkpoint: OperationJournalCheckpoint) -> OperationJournalSnapshot:
        facts = checkpoint.facts
        return OperationJournalSnapshot(
            run=checkpoint.run,
            pending_count=facts.pending_count,
            dispatched_count=facts.dispatched_count,
            committed_count=facts.committed_count,
            outcome_unknown_count=facts.outcome_unknown_count,
            state_commitment_sha256=facts.state_commitment_sha256,
        )

    def _assert_runtime_binding(self, identity: OperationRunIdentity) -> None:
        if identity.signer_key_id != self._signer.key_id:
            raise OperationJournalError("operation_journal_signer_key_binding_mismatch")
        if self._journal.schema_version != OPERATION_JOURNAL_SCHEMA_VERSION:
            raise OperationJournalError("operation_journal_schema_binding_mismatch")

    @staticmethod
    def _assert_manifest_binding(
        identity: OperationRunIdentity,
        manifest: OperationManifest,
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
