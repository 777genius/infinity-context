"""Application state machine for a durable publishable evaluation journal."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from infinity_context_server.publishable_checkpoint_journal.domain import (
    PUBLISHABLE_ANSWER_CALL_COUNT,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    JournalEvent,
    JournalRunState,
    LogicalCallIdentity,
    ProviderCallState,
    PublishableEvaluationManifest,
    PublishableRunIdentity,
    ResumeResult,
    RunPhase,
    RuntimeReceipt,
    VerifiedRuntimeReceipt,
    create_journal_event,
)
from infinity_context_server.publishable_checkpoint_journal.ports import (
    CheckpointJournalPort,
    CheckpointJournalTransactionPort,
    ExternalLifecyclePort,
    JournalHmacSignerPort,
    RuntimeReceiptVerifierPort,
)
from infinity_context_server.publishable_checkpoint_journal.replay import (
    replay_journal_events,
)


@final
class NullExternalLifecycle:
    """Explicit no-op lifecycle adapter for local-only journal use."""

    def deliver(self, event: JournalEvent) -> None:
        del event

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("NullExternalLifecycle is final")


@final
class PublishableCheckpointJournalService:
    """Coordinate exact evaluation slots, local durability, and safe replay."""

    def __init__(
        self,
        *,
        journal: CheckpointJournalPort,
        signer: JournalHmacSignerPort,
        receipt_verifier: RuntimeReceiptVerifierPort,
        external_lifecycle: ExternalLifecyclePort,
    ) -> None:
        self._journal = journal
        self._signer = signer
        self._receipt_verifier = receipt_verifier
        self._external_lifecycle = external_lifecycle

    def initialize(
        self,
        identity: PublishableRunIdentity,
        evaluation_manifest: PublishableEvaluationManifest,
    ) -> JournalRunState:
        """Persist an exact immutable evaluation manifest before provider work."""

        if (
            type(identity) is not PublishableRunIdentity
            or type(evaluation_manifest) is not PublishableEvaluationManifest
        ):
            raise CheckpointJournalError("checkpoint_journal_initialize_input_invalid")
        self._assert_manifest_binding(identity, evaluation_manifest)
        if identity.signer_key_id != self._signer.key_id:
            raise CheckpointJournalError("checkpoint_journal_signer_key_binding_mismatch")
        if identity.journal_schema_version != self._journal.schema_version:
            raise CheckpointJournalError("checkpoint_journal_schema_binding_mismatch")
        with self._journal.write_transaction() as transaction:
            existing = transaction.get_run(identity.run_id)
            if existing is not None:
                if existing.identity != identity:
                    raise CheckpointJournalError("checkpoint_journal_run_identity_divergent")
                self._verify_chain(transaction, existing)
                coverage = transaction.evaluation_coverage(run_id=identity.run_id)
                if not coverage.manifest_is_exact_for(identity):
                    raise CheckpointJournalError(
                        "checkpoint_journal_persisted_manifest_binding_invalid"
                    )
                result = existing
            else:
                state = JournalRunState(identity=identity)
                transaction.put_run(state)
                transaction.put_evaluation_manifest(evaluation_manifest)
                result = self._append_event(
                    transaction,
                    state,
                    event_type="run_initialized",
                    logical_call_id=None,
                    payload=identity.commitment_payload(),
                    notify_external=True,
                )
        self.retry_pending_notifications(identity.run_id)
        return result

    def reserve(
        self,
        identity: LogicalCallIdentity,
        *,
        request_commitment_sha256: str | None = None,
    ) -> ProviderCallState:
        """Reserve one stable slot and optionally bind its live request once."""

        if type(identity) is not LogicalCallIdentity:
            raise CheckpointJournalError("checkpoint_journal_call_identity_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            self._require_manifest_identity(transaction, identity)
            existing = transaction.get_call(
                run_id=identity.run_id,
                logical_call_id=identity.logical_call_id,
            )
            if existing is not None:
                if existing.identity != identity:
                    raise CheckpointJournalError("checkpoint_journal_logical_identity_divergent")
                if request_commitment_sha256 is None:
                    return existing
                result, _ = self._bind_request_in_transaction(
                    transaction,
                    run,
                    existing,
                    request_commitment_sha256=request_commitment_sha256,
                )
                return result
            replayed = transaction.get_call_by_replay_key(
                run_id=identity.run_id,
                replay_key=identity.replay_key,
            )
            if replayed is not None:
                raise CheckpointJournalError("checkpoint_journal_replay_divergent")
            if run.phase is not RunPhase.ACTIVE:
                raise CheckpointJournalError("checkpoint_journal_run_not_accepting_calls")
            self._require_judge_dependency(transaction, identity)
            result = ProviderCallState(
                identity=identity,
                phase=CallPhase.RESERVED,
                request_commitment_sha256=request_commitment_sha256,
            )
            transaction.put_call(result)
            updated_run = self._append_event(
                transaction,
                run,
                event_type="call_reserved",
                logical_call_id=identity.logical_call_id,
                payload={
                    "ordinal": identity.ordinal,
                    "replay_key": identity.replay_key,
                    "stage": identity.stage.value,
                },
                notify_external=False,
            )
            if request_commitment_sha256 is not None:
                updated_run = self._append_event(
                    transaction,
                    updated_run,
                    event_type="request_bound",
                    logical_call_id=identity.logical_call_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "request_commitment_sha256": request_commitment_sha256,
                    },
                    notify_external=False,
                )
            return result

    def bind_request(
        self,
        identity: LogicalCallIdentity,
        request_commitment_sha256: str,
    ) -> ProviderCallState:
        """Write-once bind the exact post-retrieval request to a stable slot."""

        if type(identity) is not LogicalCallIdentity or not isinstance(
            request_commitment_sha256, str
        ):
            raise CheckpointJournalError("checkpoint_journal_request_binding_input_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            self._require_manifest_identity(transaction, identity)
            current = self._require_exact_call(transaction, identity)
            self._require_judge_dependency(transaction, identity)
            result, _ = self._bind_request_in_transaction(
                transaction,
                run,
                current,
                request_commitment_sha256=request_commitment_sha256,
            )
            return result

    def mark_dispatched(self, identity: LogicalCallIdentity) -> ProviderCallState:
        """Record that a reserved evaluation call crossed the provider boundary."""

        if type(identity) is not LogicalCallIdentity:
            raise CheckpointJournalError("checkpoint_journal_call_identity_invalid")
        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            current = self._require_exact_call(transaction, identity)
            if current.phase is CallPhase.RESERVED:
                if run.phase is not RunPhase.ACTIVE:
                    raise CheckpointJournalError("checkpoint_journal_run_not_accepting_calls")
                if current.request_commitment_sha256 is None:
                    raise CheckpointJournalError("checkpoint_journal_dispatch_request_unbound")
                result = ProviderCallState(
                    identity=identity,
                    phase=CallPhase.DISPATCHED,
                    request_commitment_sha256=current.request_commitment_sha256,
                )
                transaction.put_call(result)
                self._append_event(
                    transaction,
                    run,
                    event_type="call_dispatched",
                    logical_call_id=identity.logical_call_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "request_commitment_sha256": (current.request_commitment_sha256),
                        "stage": identity.stage.value,
                    },
                    notify_external=True,
                )
            elif current.phase in (CallPhase.DISPATCHED, CallPhase.COMMITTED):
                result = current
            else:
                raise CheckpointJournalError("checkpoint_journal_outcome_unknown_retry_blocked")
        self.retry_pending_notifications(identity.run_id)
        return result

    def commit(
        self,
        identity: LogicalCallIdentity,
        receipt: RuntimeReceipt,
    ) -> ProviderCallState:
        """Commit a verified provider receipt, including reconciliation work."""

        if type(identity) is not LogicalCallIdentity or type(receipt) is not RuntimeReceipt:
            raise CheckpointJournalError("checkpoint_journal_commit_input_invalid")
        if receipt.run_id != identity.run_id or receipt.logical_call_id != identity.logical_call_id:
            raise CheckpointJournalError("checkpoint_journal_receipt_identity_mismatch")
        verified = self._receipt_verifier.verify(identity=identity, receipt=receipt)
        if type(verified) is not VerifiedRuntimeReceipt or verified.receipt != receipt:
            raise CheckpointJournalError("checkpoint_journal_receipt_verification_invalid")

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, identity.run_id)
            current = self._require_exact_call(transaction, identity)
            if receipt.request_commitment_sha256 != current.request_commitment_sha256:
                raise CheckpointJournalError("checkpoint_journal_receipt_request_mismatch")
            if current.phase is CallPhase.COMMITTED:
                if (
                    current.receipt == receipt
                    and current.verifier_key_id == verified.verifier_key_id
                    and current.verification_commitment_sha256
                    == verified.verification_commitment_sha256
                ):
                    result = current
                else:
                    raise CheckpointJournalError("checkpoint_journal_receipt_replay_divergent")
            else:
                if current.phase not in (
                    CallPhase.DISPATCHED,
                    CallPhase.OUTCOME_UNKNOWN,
                ):
                    raise CheckpointJournalError(
                        "checkpoint_journal_commit_requires_dispatched_call"
                    )
                if run.phase is RunPhase.EVALUATION_SEALED:
                    raise CheckpointJournalError("checkpoint_journal_evaluation_sealed")
                result = ProviderCallState(
                    identity=identity,
                    phase=CallPhase.COMMITTED,
                    request_commitment_sha256=current.request_commitment_sha256,
                    receipt=receipt,
                    verifier_key_id=verified.verifier_key_id,
                    verification_commitment_sha256=verified.verification_commitment_sha256,
                )
                transaction.put_call(result)
                transaction.put_private_provider_result(
                    state=result,
                    verified_receipt=verified,
                )
                updated_run = self._append_event(
                    transaction,
                    run,
                    event_type="call_committed",
                    logical_call_id=identity.logical_call_id,
                    payload={
                        "ordinal": identity.ordinal,
                        "provider_receipt_id": receipt.provider_receipt_id,
                        "request_commitment_sha256": (receipt.request_commitment_sha256),
                        "result_commitment_sha256": receipt.result_commitment_sha256,
                        "verifier_key_id": verified.verifier_key_id,
                        "verification_commitment_sha256": (verified.verification_commitment_sha256),
                    },
                    notify_external=False,
                )
                if (
                    updated_run.phase is RunPhase.RECONCILIATION_REQUIRED
                    and not transaction.has_calls_in_phase(
                        run_id=identity.run_id,
                        phase=CallPhase.OUTCOME_UNKNOWN,
                    )
                ):
                    updated_run = replace(updated_run, phase=RunPhase.ACTIVE)
                    self._append_event(
                        transaction,
                        updated_run,
                        event_type="reconciliation_cleared",
                        logical_call_id=None,
                        payload={"resolved_logical_call_id": identity.logical_call_id},
                        notify_external=False,
                    )
        self.retry_pending_notifications(identity.run_id)
        return result

    def resume(self, run_id: str) -> ResumeResult:
        """Fail closed after restart: dispatched calls become outcome_unknown."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_chain(transaction, run)
            if run.phase is RunPhase.EVALUATION_SEALED:
                result = ResumeResult(
                    run=run,
                    outcome_unknown_count=0,
                    newly_outcome_unknown_count=0,
                )
            else:
                unknown_count = transaction.count_calls_in_phase(
                    run_id=run_id,
                    phase=CallPhase.OUTCOME_UNKNOWN,
                )
                newly_unknown_count = 0
                updated_run = run
                for current in transaction.iter_calls(
                    run_id=run_id,
                    phases=(CallPhase.DISPATCHED,),
                    batch_size=128,
                ):
                    unknown = ProviderCallState(
                        identity=current.identity,
                        phase=CallPhase.OUTCOME_UNKNOWN,
                        request_commitment_sha256=(current.request_commitment_sha256),
                    )
                    transaction.put_call(unknown)
                    updated_run = self._append_event(
                        transaction,
                        updated_run,
                        event_type="call_outcome_unknown",
                        logical_call_id=current.identity.logical_call_id,
                        payload={
                            "ordinal": current.identity.ordinal,
                            "reason": "restart_without_verified_receipt",
                        },
                        notify_external=False,
                    )
                    newly_unknown_count += 1
                unknown_count += newly_unknown_count
                if unknown_count and updated_run.phase is not RunPhase.RECONCILIATION_REQUIRED:
                    updated_run = replace(
                        updated_run,
                        phase=RunPhase.RECONCILIATION_REQUIRED,
                    )
                    updated_run = self._append_event(
                        transaction,
                        updated_run,
                        event_type="reconciliation_required",
                        logical_call_id=None,
                        payload={"outcome_unknown_count": unknown_count},
                        notify_external=True,
                    )
                result = ResumeResult(
                    run=updated_run,
                    outcome_unknown_count=unknown_count,
                    newly_outcome_unknown_count=newly_unknown_count,
                )
        self.retry_pending_notifications(run_id)
        return result

    def seal_evaluation(self, run_id: str) -> JournalRunState:
        """Seal the 6,160 provider-call evaluation, never the entire run."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_chain(transaction, run)
            if run.phase is RunPhase.RECONCILIATION_REQUIRED:
                raise CheckpointJournalError(
                    "checkpoint_journal_evaluation_seal_reconciliation_required"
                )
            coverage = transaction.evaluation_coverage(run_id=run_id)
            if not coverage.is_complete_for(run.identity):
                raise CheckpointJournalError(
                    "checkpoint_journal_evaluation_seal_manifest_incomplete"
                )
            if run.phase is RunPhase.EVALUATION_SEALED:
                result = run
            else:
                result = self._append_event(
                    transaction,
                    replace(run, phase=RunPhase.EVALUATION_SEALED),
                    event_type="evaluation_sealed",
                    logical_call_id=None,
                    payload={
                        "committed_answer_count": coverage.committed_answer_count,
                        "committed_judge_count": coverage.committed_judge_count,
                        "evaluation_manifest_commitment_sha256": (
                            coverage.evaluation_manifest_commitment_sha256
                        ),
                    },
                    notify_external=True,
                )
        self.retry_pending_notifications(run_id)
        return result

    def retry_pending_notifications(self, run_id: str, *, batch_size: int = 64) -> int:
        """Retry durable authority events; event_sha256 is the idempotency key."""

        delivered = 0
        for event in self._journal.iter_pending_lifecycle_events(
            run_id=run_id,
            batch_size=batch_size,
        ):
            self._external_lifecycle.deliver(event)
            with self._journal.write_transaction() as transaction:
                transaction.mark_lifecycle_event_delivered(
                    run_id=run_id,
                    event_sha256=event.event_sha256,
                )
            delivered += 1
        return delivered

    def verify_chain(self, run_id: str) -> JournalRunState:
        """Validate the complete durable chain under the journal write lock."""

        with self._journal.write_transaction() as transaction:
            run = self._require_run(transaction, run_id)
            self._verify_chain(transaction, run)
            return run

    def _append_event(
        self,
        transaction: CheckpointJournalTransactionPort,
        run: JournalRunState,
        *,
        event_type: str,
        logical_call_id: str | None,
        payload: dict[str, object],
        notify_external: bool,
    ) -> JournalRunState:
        event = create_journal_event(
            run_id=run.identity.run_id,
            sequence=run.event_count + 1,
            event_type=event_type,
            logical_call_id=logical_call_id,
            payload=payload,
            predecessor_event_sha256=run.head_event_sha256,
            signer_key_id=self._signer.key_id,
            sign=self._signer.sign,
        )
        transaction.append_event(event)
        if notify_external:
            transaction.enqueue_lifecycle_event(event)
        updated = replace(
            run,
            event_count=event.sequence,
            head_event_sha256=event.event_sha256,
        )
        transaction.put_run(updated)
        return updated

    def _bind_request_in_transaction(
        self,
        transaction: CheckpointJournalTransactionPort,
        run: JournalRunState,
        current: ProviderCallState,
        *,
        request_commitment_sha256: str,
    ) -> tuple[ProviderCallState, JournalRunState]:
        if current.request_commitment_sha256 is not None:
            if current.request_commitment_sha256 != request_commitment_sha256:
                raise CheckpointJournalError("checkpoint_journal_request_binding_immutable")
            return current, run
        if current.phase is not CallPhase.RESERVED or run.phase is not RunPhase.ACTIVE:
            raise CheckpointJournalError("checkpoint_journal_request_binding_not_allowed")
        result = ProviderCallState(
            identity=current.identity,
            phase=CallPhase.RESERVED,
            request_commitment_sha256=request_commitment_sha256,
        )
        transaction.put_call(result)
        updated_run = self._append_event(
            transaction,
            run,
            event_type="request_bound",
            logical_call_id=current.identity.logical_call_id,
            payload={
                "ordinal": current.identity.ordinal,
                "request_commitment_sha256": request_commitment_sha256,
            },
            notify_external=False,
        )
        return result, updated_run

    def _require_run(
        self,
        transaction: CheckpointJournalTransactionPort,
        run_id: str,
    ) -> JournalRunState:
        run = transaction.get_run(run_id)
        if run is None:
            raise CheckpointJournalError("checkpoint_journal_run_missing")
        if run.identity.signer_key_id != self._signer.key_id:
            raise CheckpointJournalError("checkpoint_journal_signer_key_binding_mismatch")
        return run

    def _require_manifest_identity(
        self,
        transaction: CheckpointJournalTransactionPort,
        identity: LogicalCallIdentity,
    ) -> None:
        expected = transaction.get_evaluation_manifest_call(
            run_id=identity.run_id,
            ordinal=identity.ordinal,
        )
        if expected is None:
            raise CheckpointJournalError("checkpoint_journal_call_outside_manifest")
        if expected != identity:
            raise CheckpointJournalError("checkpoint_journal_manifest_identity_divergent")

    def _require_exact_call(
        self,
        transaction: CheckpointJournalTransactionPort,
        identity: LogicalCallIdentity,
    ) -> ProviderCallState:
        current = transaction.get_call(
            run_id=identity.run_id,
            logical_call_id=identity.logical_call_id,
        )
        if current is None:
            replayed = transaction.get_call_by_replay_key(
                run_id=identity.run_id,
                replay_key=identity.replay_key,
            )
            if replayed is not None:
                raise CheckpointJournalError("checkpoint_journal_replay_divergent")
            raise CheckpointJournalError("checkpoint_journal_call_missing")
        if current.identity != identity:
            raise CheckpointJournalError("checkpoint_journal_logical_identity_divergent")
        return current

    def _require_judge_dependency(
        self,
        transaction: CheckpointJournalTransactionPort,
        identity: LogicalCallIdentity,
    ) -> None:
        if identity.stage is not CallStage.JUDGE:
            return
        dependency = transaction.get_call(
            run_id=identity.run_id,
            logical_call_id=identity.depends_on_logical_call_id or "",
        )
        if dependency is None or dependency.phase is not CallPhase.COMMITTED:
            raise CheckpointJournalError("checkpoint_journal_judge_answer_not_committed")
        if (
            dependency.identity.stage is not CallStage.ANSWER
            or dependency.identity.case_id != identity.case_id
            or dependency.identity.case_alias != identity.case_alias
            or dependency.identity.backend_role != identity.backend_role
            or dependency.identity.backend_target_id != identity.backend_target_id
            or dependency.identity.backend_target_commitment_sha256
            != identity.backend_target_commitment_sha256
            or dependency.identity.ordinal + PUBLISHABLE_ANSWER_CALL_COUNT != identity.ordinal
        ):
            raise CheckpointJournalError("checkpoint_journal_judge_dependency_invalid")

    def _verify_chain(
        self,
        transaction: CheckpointJournalTransactionPort,
        run: JournalRunState,
    ) -> None:
        events = transaction.iter_events(run_id=run.identity.run_id, batch_size=128)
        try:
            verification = replay_journal_events(
                events,
                identity=run.identity,
                signer_key_id=self._signer.key_id,
                verify=self._signer.verify,
            )
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()
        if (
            verification.event_count != run.event_count
            or verification.head_event_sha256 != run.head_event_sha256
            or verification.phase is not run.phase
            or verification.call_state_commitment_sha256
            != transaction.runtime_state_commitment(run_id=run.identity.run_id)
        ):
            raise CheckpointJournalError("checkpoint_journal_chain_run_state_mismatch")

    @staticmethod
    def _assert_manifest_binding(
        identity: PublishableRunIdentity,
        manifest: PublishableEvaluationManifest,
    ) -> None:
        if (
            manifest.run_id != identity.run_id
            or manifest.case_manifest_sha256 != identity.case_manifest_sha256
            or manifest.manifest_authority_commitment_sha256
            != identity.manifest_authority_commitment_sha256
            or manifest.commitment_sha256 != identity.evaluation_manifest_commitment_sha256
        ):
            raise CheckpointJournalError("checkpoint_journal_manifest_binding_mismatch")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("PublishableCheckpointJournalService is final")


__all__ = ("NullExternalLifecycle", "PublishableCheckpointJournalService")
