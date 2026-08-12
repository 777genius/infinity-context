"""Durable fail-closed orchestration for one fresh extraction plus four evaluations."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunProviderInputs,
    PublishableRunSecrets,
)

from .authority import (
    FRESH_CHAIN_AUTHORITY_ID,
    FRESH_CHAIN_STATIC_AUTHORITY_SHA256,
    FreshChainCanaryAuthority,
    fresh_chain_static_authority_payload,
)
from .authorization import FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION
from .contracts import (
    FRESH_CHAIN_STAGES,
    FreshChainCallFailure,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainCanaryDependencyFactoryPort,
    FreshChainCanaryError,
    FreshChainCanaryRuntimeSession,
    FreshChainCleanupResult,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainRetrievalHandoff,
    canonical_sha256,
)
from .evidence import (
    FreshChainCanaryEvidence,
    build_fresh_chain_evidence_from_snapshot,
    read_fresh_chain_evidence,
    write_fresh_chain_evidence,
)
from .layout import FreshChainLayout, open_fresh_chain_layout
from .ledger import FreshChainCanaryLedger
from .ledger_models import (
    FreshChainPlan,
    FreshChainSnapshot,
    FreshChainStageRecord,
    RetrievalHandoff,
    TokenUsage,
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainCanaryOrchestrator:
    """Execute exactly the fixed five-call authority or authenticate its replay."""

    dependency_factory: FreshChainCanaryDependencyFactoryPort = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.dependency_factory, "open_fresh_chain_session", None)):
            _fail("fresh_chain_dependency_factory_invalid")

    def run(
        self,
        *,
        config: PublishableRunConfig,
        secrets: PublishableRunSecrets,
        authorization: object | None = None,
    ) -> FreshChainCanaryEvidence:
        if authorization is not FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION:
            _fail("fresh_chain_live_1_plus_4_authorization_required")
        if type(config) is not PublishableRunConfig or type(secrets) is not PublishableRunSecrets:
            _fail("fresh_chain_orchestrator_inputs_invalid")
        layout = open_fresh_chain_layout(config, secrets)
        authority = FreshChainCanaryAuthority(
            namespace_commitment_sha256=layout.namespace_commitment_sha256,
            source_commitment_sha256=layout.source_commitment_sha256,
        )
        plan = _plan(layout, authority)
        require_ledger = layout.resume and layout.ledger_path.exists()
        ledger = FreshChainCanaryLedger.open(
            layout.ledger_path,
            authentication_secret=layout.ledger_authentication_key,
            plan=plan,
            require_existing=require_ledger,
        )
        snapshot = ledger.read_snapshot()
        replay = _terminal_replay(layout, snapshot)
        if replay is not None:
            return replay
        if layout.evidence_path.exists():
            _fail("fresh_chain_evidence_precedes_terminal")
        if _ready_to_complete_without_provider(snapshot):
            snapshot = _complete_success(ledger, snapshot)
            evidence = build_fresh_chain_evidence_from_snapshot(
                snapshot,
                authentication_key=layout.evidence_authentication_key,
            )
            return write_fresh_chain_evidence(
                layout.evidence_path,
                evidence,
                authentication_key=layout.evidence_authentication_key,
            )
        if _ready_to_fail_without_provider(snapshot):
            ledger.terminate_failed()
            _fail("fresh_chain_known_provider_failure")

        session = self.dependency_factory.open_fresh_chain_session(
            inputs=PublishableRunProviderInputs(
                state_root=layout.provider_root,
                adapter_config_json=config.adapter_config_json,
                adapter_secrets_json=secrets.adapter_secrets_json,
            ),
            state_root=layout.provider_root,
            namespace_id=layout.namespace_id,
            namespace_commitment_sha256=layout.namespace_commitment_sha256,
            source_commitment_sha256=layout.source_commitment_sha256,
            resume=_provider_state_requires_resume(layout, snapshot),
        )
        try:
            _require_session(
                session,
                layout,
                common_condition_policy_sha256=plan.common_condition_policy_sha256,
            )
            snapshot = _bind_source_projection(ledger, snapshot, session)
            if snapshot.abort_reason_sha256 is not None:
                snapshot = _finish_local_abort(
                    session=session,
                    ledger=ledger,
                    snapshot=snapshot,
                    layout=layout,
                )
                _fail("fresh_chain_prior_terminal_failed")
            snapshot = self._execute_calls(
                session=session,
                ledger=ledger,
                initial=snapshot,
                layout=layout,
            )
            snapshot = self._finish(
                session=session,
                ledger=ledger,
                snapshot=snapshot,
                layout=layout,
            )
            evidence = build_fresh_chain_evidence_from_snapshot(
                snapshot,
                authentication_key=layout.evidence_authentication_key,
            )
            return write_fresh_chain_evidence(
                layout.evidence_path,
                evidence,
                authentication_key=layout.evidence_authentication_key,
            )
        except BaseException as error:
            _abort_after_post_extraction_failure(
                session=session,
                ledger=ledger,
                layout=layout,
                error=error,
            )
            raise
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _execute_calls(
        self,
        *,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        initial: FreshChainSnapshot,
        layout: FreshChainLayout,
    ) -> FreshChainSnapshot:
        snapshot = initial
        calls: list[FreshChainCallResult] = []
        handoff: FreshChainRetrievalHandoff | None = None
        for ordinal, stage in enumerate(FRESH_CHAIN_STAGES):
            record = snapshot.stages[ordinal]
            if record.stage != stage:
                _fail("fresh_chain_ledger_stage_order_invalid")
            intent = session.prepare_call(
                stage=stage,
                prior_results=tuple(calls),
                retrieval_handoff=handoff,
            )
            _require_intent(
                intent,
                stage=stage,
                layout=layout,
                handoff=handoff,
                source_projection_commitment_sha256=(session.source_projection_commitment_sha256),
            )
            if record.status == "succeeded":
                _require_record_intent(record, intent)
                lookup = session.lookup(intent)
                result = _terminal_result(
                    lookup,
                    intent=intent,
                    dispatched=False,
                    conflict_code="fresh_chain_provider_replay_conflict",
                )
                _require_record_result(record, result)
            elif record.status == "pending":
                _require_record_intent(record, intent)
                result = self._recover_pending(session, ledger, record, intent)
                snapshot = ledger.read_snapshot()
            elif record.status == "not_started":
                if snapshot.next_stage != stage:
                    _fail("fresh_chain_call_out_of_order")
                snapshot = ledger.record_intent(
                    stage,
                    intent_sha256=intent.intent_sha256,
                    request_sha256=intent.request_sha256,
                    input_authority_sha256=intent.input_authority_sha256,
                    commitments=_intent_commitments(intent),
                )
                result = self._dispatch_new(session, ledger, intent)
                snapshot = ledger.read_snapshot()
            elif record.status == "failed":
                _require_record_intent(record, intent)
                lookup = session.recover(intent)
                failure = _terminal_failure(
                    lookup,
                    intent=intent,
                    dispatched=False,
                    conflict_code="fresh_chain_failure_recovery_invalid",
                )
                _require_record_failure(record, failure)
                result = failure
            else:
                _fail("fresh_chain_prior_call_failed")
            if type(result) is FreshChainCallFailure:
                return self._finish_failure(
                    session=session,
                    ledger=ledger,
                    failure=result,
                    layout=layout,
                )
            if any(
                prior.physical_receipt_sha256 == result.physical_receipt_sha256
                or prior.receipt_id == result.receipt_id
                for prior in calls
            ):
                _fail("fresh_chain_receipt_duplicate")
            calls.append(result)
            if stage == "mem0_extraction":
                observed = session.capture_retrieval(result)
                _require_handoff(observed, extraction=result, layout=layout)
                if snapshot.retrieval_handoff is None:
                    snapshot = ledger.record_retrieval_handoff(
                        extraction_result_sha256=observed.extraction_result_sha256,
                        extraction_receipt_sha256=observed.extraction_receipt_sha256,
                        namespace_commitment_sha256=observed.namespace_commitment_sha256,
                        memory_authority_sha256=observed.memory_authority_sha256,
                        retrieval_authority_sha256=observed.retrieval_authority_sha256,
                        memory_count=observed.memory_count,
                        commitments={
                            "extraction_intent_sha256": observed.extraction_intent_sha256,
                            "handoff_sha256": observed.handoff_sha256,
                            "memory_count_sha256": canonical_sha256(
                                {"memory_count": observed.memory_count}
                            ),
                            "retrieval_material_sha256": (observed.retrieval_material_sha256),
                            "source_commitment_sha256": observed.source_commitment_sha256,
                            "source_projection_commitment_sha256": (
                                observed.source_projection_commitment_sha256
                            ),
                        },
                    )
                else:
                    _require_ledger_handoff(snapshot.retrieval_handoff, observed)
                handoff = observed
        if (
            len(calls) != 5
            or tuple(item.stage for item in calls) != FRESH_CHAIN_STAGES
            or snapshot.physical_attempt_count != 5
            or snapshot.ordered_completed_stages != FRESH_CHAIN_STAGES
        ):
            _fail("fresh_chain_five_call_accounting_invalid")
        return snapshot

    def _dispatch_new(
        self,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        lookup = session.lookup(intent)
        _require_lookup(lookup, intent)
        if lookup.disposition is not FreshChainLookupDisposition.AUTHENTICATED_ABSENT:
            _record_ambiguity_if_needed(ledger, intent, phase="pre_dispatch_conflict")
            _fail("fresh_chain_pre_dispatch_state_not_absent")
        assert lookup.authenticated_absence_sha256 is not None
        ledger.record_authenticated_pre_call_absence(
            intent.stage,
            intent_sha256=intent.intent_sha256,
            absence_sha256=lookup.authenticated_absence_sha256,
        )
        return self._start_and_dispatch(
            session,
            ledger,
            intent,
            authenticated_absence_sha256=lookup.authenticated_absence_sha256,
        )

    def _start_and_dispatch(
        self,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        intent: FreshChainCallIntent,
        *,
        authenticated_absence_sha256: str,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        ledger.record_dispatch_started(
            intent.stage,
            intent_sha256=intent.intent_sha256,
            authenticated_absence_sha256=authenticated_absence_sha256,
        )
        try:
            result = session.dispatch(intent)
        except BaseException:
            _record_ambiguity_if_needed(ledger, intent, phase="dispatch_outcome_unknown")
            _fail("fresh_chain_dispatch_outcome_unknown")
        if type(result) is FreshChainCallFailure:
            _require_failure(result, intent=intent, dispatched=True)
            _record_failure(ledger, result)
            return result
        _require_result(result, intent=intent, dispatched=True)
        _record_success(ledger, result)
        return result

    def _recover_pending(
        self,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        record: FreshChainStageRecord,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        if record.dispatch_started_sha256 is None:
            return self._resume_before_dispatch(session, ledger, record, intent)
        lookup = session.recover(intent)
        _require_lookup(lookup, intent)
        if lookup.disposition is FreshChainLookupDisposition.TERMINAL:
            result = _terminal_result(
                lookup,
                intent=intent,
                dispatched=False,
                conflict_code="fresh_chain_recovery_terminal_invalid",
            )
            _record_success(ledger, result)
            return result
        if lookup.disposition is FreshChainLookupDisposition.FAILED:
            assert lookup.failure is not None
            _require_failure(lookup.failure, intent=intent, dispatched=False)
            _record_failure(ledger, lookup.failure)
            return lookup.failure
        if lookup.disposition is FreshChainLookupDisposition.AMBIGUOUS:
            if record.ambiguity_sha256 is None:
                assert lookup.ambiguity_sha256 is not None
                ledger.record_ambiguous_outcome(
                    intent.stage,
                    intent_sha256=intent.intent_sha256,
                    ambiguity_sha256=lookup.ambiguity_sha256,
                )
            _fail("fresh_chain_recovery_still_ambiguous")
        if lookup.disposition is FreshChainLookupDisposition.AUTHENTICATED_ABSENT:
            assert lookup.authenticated_absence_sha256 is not None
            if lookup.authenticated_absence_sha256 not in (record.authenticated_absence_sha256):
                _record_ambiguity_if_needed(
                    ledger,
                    intent,
                    phase="recovery_absence_generation_conflict",
                )
                _fail("fresh_chain_recovery_absence_conflict")
            # The genuine one-shot and subscription bridge seams authenticate
            # this exact absence only while no provider intent has been
            # claimed.  Re-entering dispatch is therefore a recovery of the
            # pre-claim crash window, not a blind post-call redispatch.
            return self._dispatch_after_started(session, ledger, intent)
        _fail("fresh_chain_recovered_call_failed")

    def _dispatch_after_started(
        self,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        try:
            result = session.dispatch(intent)
        except BaseException:
            _record_ambiguity_if_needed(ledger, intent, phase="recovery_dispatch_outcome_unknown")
            _fail("fresh_chain_dispatch_outcome_unknown")
        if type(result) is FreshChainCallFailure:
            _require_failure(result, intent=intent, dispatched=True)
            _record_failure(ledger, result)
        else:
            _require_result(result, intent=intent, dispatched=True)
            _record_success(ledger, result)
        return result

    def _resume_before_dispatch(
        self,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        record: FreshChainStageRecord,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        if record.ambiguity_sha256 is not None:
            _fail("fresh_chain_pre_dispatch_ambiguity_requires_operator")
        lookup = session.lookup(intent)
        _require_lookup(lookup, intent)
        if lookup.disposition is not FreshChainLookupDisposition.AUTHENTICATED_ABSENT:
            _record_ambiguity_if_needed(
                ledger,
                intent,
                phase="resumed_pre_dispatch_state_not_absent",
            )
            _fail("fresh_chain_pre_dispatch_state_not_absent")
        assert lookup.authenticated_absence_sha256 is not None
        absence = lookup.authenticated_absence_sha256
        if absence not in record.authenticated_absence_sha256:
            ledger.record_authenticated_pre_call_absence(
                intent.stage,
                intent_sha256=intent.intent_sha256,
                absence_sha256=absence,
            )
        return self._start_and_dispatch(
            session,
            ledger,
            intent,
            authenticated_absence_sha256=absence,
        )

    def _finish_failure(
        self,
        *,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        failure: FreshChainCallFailure,
        layout: FreshChainLayout,
    ) -> FreshChainSnapshot:
        snapshot = ledger.read_snapshot()
        if snapshot.cleanup is None:
            cleanup = session.cleanup(failure)
            if (
                type(cleanup) is not FreshChainCleanupResult
                or cleanup.namespace_commitment_sha256 != layout.namespace_commitment_sha256
            ):
                _fail("fresh_chain_cleanup_binding_invalid")
            snapshot = _record_cleanup(ledger, cleanup)
        ledger.terminate_failed()
        _fail("fresh_chain_known_provider_failure")

    def _finish(
        self,
        *,
        session: FreshChainCanaryRuntimeSession,
        ledger: FreshChainCanaryLedger,
        snapshot: FreshChainSnapshot,
        layout: FreshChainLayout,
    ) -> FreshChainSnapshot:
        if snapshot.cleanup is None:
            cleanup = session.cleanup()
            if (
                type(cleanup) is not FreshChainCleanupResult
                or cleanup.namespace_commitment_sha256 != layout.namespace_commitment_sha256
            ):
                _fail("fresh_chain_cleanup_binding_invalid")
            snapshot = _record_cleanup(ledger, cleanup)
        return _complete_success(ledger, snapshot)


def _plan(layout: FreshChainLayout, authority: FreshChainCanaryAuthority) -> FreshChainPlan:
    static = fresh_chain_static_authority_payload()
    evaluation = static["evaluation"]
    if type(evaluation) is not dict:
        _fail("fresh_chain_static_authority_invalid")
    common = evaluation["common_condition"]
    return FreshChainPlan(
        run_id=FRESH_CHAIN_AUTHORITY_ID,
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
        common_condition_policy_sha256=canonical_sha256(common),
        commitments={
            "authorization_capability_sha256": (
                FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION.commitment_sha256
            ),
            "dynamic_authority_sha256": authority.commitment_sha256,
            "static_authority_sha256": FRESH_CHAIN_STATIC_AUTHORITY_SHA256,
        },
    )


def _bind_source_projection(
    ledger: FreshChainCanaryLedger,
    snapshot: FreshChainSnapshot,
    session: FreshChainCanaryRuntimeSession,
) -> FreshChainSnapshot:
    observed = session.source_projection_commitment_sha256
    if not _sha(observed):
        _fail("fresh_chain_source_projection_invalid")
    if snapshot.source_projection_commitment_sha256 is None:
        return ledger.record_source_projection_bound(source_projection_commitment_sha256=observed)
    if snapshot.source_projection_commitment_sha256 != observed:
        _fail("fresh_chain_source_projection_replay_conflict")
    return snapshot


def _record_cleanup(
    ledger: FreshChainCanaryLedger,
    cleanup: FreshChainCleanupResult,
) -> FreshChainSnapshot:
    return ledger.record_cleanup(
        namespace_commitment_sha256=cleanup.namespace_commitment_sha256,
        cleanup_authority_sha256=cleanup.cleanup_authority_sha256,
        receipt_id=cleanup.receipt_id,
        receipt_sha256=cleanup.receipt_sha256,
        outcome_sha256=cleanup.outcome_sha256,
        deleted=cleanup.deleted,
        operation_count=cleanup.operation_count,
        residual_count=cleanup.residual_count,
    )


def _abort_after_post_extraction_failure(
    *,
    session: FreshChainCanaryRuntimeSession,
    ledger: FreshChainCanaryLedger,
    layout: FreshChainLayout,
    error: BaseException,
) -> None:
    """Best-effort durable abort plus mandatory namespace cleanup.

    The original failure remains authoritative.  A durable abort prevents a
    replay from rendering, retrieving, or dispatching another provider call;
    if ledger integrity itself is unavailable, cleanup is still attempted.
    """

    try:
        snapshot = ledger.read_snapshot()
    except BaseException:
        with suppress(BaseException):
            session.cleanup()
        return
    if snapshot.completed or snapshot.cleanup is not None:
        return
    extraction = snapshot.stages[0]
    if extraction.status != "succeeded":
        return
    if snapshot.abort_reason_sha256 is None:
        reason = canonical_sha256(
            {
                "error_code": getattr(error, "code", type(error).__name__),
                "failure_domain": "fresh-chain-post-extraction-local-abort/v1",
                "stage_statuses": [record.status for record in snapshot.stages],
            }
        )
        try:
            snapshot = ledger.record_local_abort(reason_sha256=reason)
        except BaseException:
            with suppress(BaseException):
                session.cleanup()
            return
    try:
        _finish_local_abort(
            session=session,
            ledger=ledger,
            snapshot=snapshot,
            layout=layout,
        )
    except BaseException:
        # The abort event is replay-safe: the next invocation performs cleanup
        # before any rendering, retrieval, or dispatch.
        return


def _finish_local_abort(
    *,
    session: FreshChainCanaryRuntimeSession,
    ledger: FreshChainCanaryLedger,
    snapshot: FreshChainSnapshot,
    layout: FreshChainLayout,
) -> FreshChainSnapshot:
    if snapshot.abort_reason_sha256 is None:
        _fail("fresh_chain_local_abort_missing")
    if snapshot.cleanup is None:
        cleanup = session.cleanup()
        if (
            type(cleanup) is not FreshChainCleanupResult
            or cleanup.namespace_commitment_sha256 != layout.namespace_commitment_sha256
        ):
            _fail("fresh_chain_cleanup_binding_invalid")
        snapshot = _record_cleanup(ledger, cleanup)
    return ledger.terminate_failed()


def _terminal_replay(
    layout: FreshChainLayout,
    snapshot: FreshChainSnapshot,
) -> FreshChainCanaryEvidence | None:
    if not snapshot.completed:
        return None
    if not snapshot.succeeded:
        _fail("fresh_chain_prior_terminal_failed")
    rebuilt = build_fresh_chain_evidence_from_snapshot(
        snapshot,
        authentication_key=layout.evidence_authentication_key,
    )
    if layout.evidence_path.exists():
        observed = read_fresh_chain_evidence(
            layout.evidence_path,
            authentication_key=layout.evidence_authentication_key,
        )
        if observed != rebuilt:
            _fail("fresh_chain_evidence_replay_conflict")
        return observed
    return write_fresh_chain_evidence(
        layout.evidence_path,
        rebuilt,
        authentication_key=layout.evidence_authentication_key,
    )


def _require_session(
    session: object,
    layout: FreshChainLayout,
    *,
    common_condition_policy_sha256: str,
) -> None:
    required = (
        "prepare_call",
        "lookup",
        "dispatch",
        "recover",
        "capture_retrieval",
        "cleanup",
        "close",
    )
    try:
        valid = (
            all(callable(getattr(session, name, None)) for name in required)
            and session.namespace_id == layout.namespace_id
            and session.namespace_commitment_sha256 == layout.namespace_commitment_sha256
            and session.source_commitment_sha256 == layout.source_commitment_sha256
            and _sha(session.source_projection_commitment_sha256)
            and session.common_condition_policy_sha256 == common_condition_policy_sha256
        )
    except Exception:
        valid = False
    if not valid:
        _fail("fresh_chain_runtime_session_invalid")


def _ready_to_complete_without_provider(snapshot: FreshChainSnapshot) -> bool:
    return bool(
        snapshot.terminal_outcome is None
        and snapshot.source_projection_commitment_sha256 is not None
        and snapshot.cleanup is not None
        and snapshot.retrieval_handoff is not None
        and snapshot.physical_attempt_count == len(FRESH_CHAIN_STAGES)
        and snapshot.ordered_completed_stages == FRESH_CHAIN_STAGES
    )


def _ready_to_fail_without_provider(snapshot: FreshChainSnapshot) -> bool:
    return bool(
        snapshot.terminal_outcome is None
        and snapshot.source_projection_commitment_sha256 is not None
        and snapshot.cleanup is not None
        and (
            any(record.status == "failed" for record in snapshot.stages)
            or snapshot.abort_reason_sha256 is not None
        )
    )


def _provider_state_requires_resume(
    layout: FreshChainLayout,
    snapshot: FreshChainSnapshot,
) -> bool:
    """Permit safe first provider initialization after a pre-open crash only."""

    if not layout.resume:
        return False
    pristine = (
        snapshot.source_projection_commitment_sha256 is None
        and snapshot.event_count == 0
        and snapshot.intent_count == 0
        and snapshot.result_count == 0
        and snapshot.physical_attempt_count == 0
        and snapshot.retrieval_handoff is None
        and snapshot.cleanup is None
        and snapshot.terminal_outcome is None
    )
    if not pristine:
        return True
    try:
        return any(layout.provider_root.iterdir())
    except OSError:
        _fail("fresh_chain_provider_state_unavailable")


def _complete_success(
    ledger: FreshChainCanaryLedger,
    snapshot: FreshChainSnapshot,
) -> FreshChainSnapshot:
    if not _ready_to_complete_without_provider(snapshot):
        _fail("fresh_chain_terminal_state_unexpected")
    terminal_sha256 = canonical_sha256(
        {
            "activation_evidence_only": True,
            "cleanup": snapshot.cleanup.material(),
            "ordered_receipt_ids": list(snapshot.ordered_receipt_ids),
            "plan_commitment_sha256": snapshot.plan.commitment_sha256,
            "publishable": False,
            "retrieval_handoff": snapshot.retrieval_handoff.material(),
            "source_projection_commitment_sha256": (snapshot.source_projection_commitment_sha256),
        }
    )
    return ledger.complete(outcome_sha256=terminal_sha256)


def _require_intent(
    intent: object,
    *,
    stage: str,
    layout: FreshChainLayout,
    handoff: FreshChainRetrievalHandoff | None,
    source_projection_commitment_sha256: str,
) -> None:
    if (
        type(intent) is not FreshChainCallIntent
        or intent.stage != stage
        or intent.ordinal != FRESH_CHAIN_STAGES.index(stage)
        or intent.namespace_id != layout.namespace_id
        or intent.namespace_commitment_sha256 != layout.namespace_commitment_sha256
        or intent.source_commitment_sha256 != layout.source_commitment_sha256
        or intent.source_projection_commitment_sha256 != source_projection_commitment_sha256
        or (
            stage == "mem0_extraction"
            and intent.input_authority_sha256 != intent.source_projection_commitment_sha256
        )
        or (
            stage == "mem0_answer"
            and (
                handoff is None
                or intent.input_authority_sha256 != handoff.retrieval_authority_sha256
                or intent.retrieval_handoff_sha256 != handoff.handoff_sha256
            )
        )
    ):
        _fail("fresh_chain_prepared_intent_invalid")


def _require_record_intent(
    record: FreshChainStageRecord,
    intent: FreshChainCallIntent,
) -> None:
    if (
        record.intent_sha256 != intent.intent_sha256
        or record.request_sha256 != intent.request_sha256
        or record.input_authority_sha256 != intent.input_authority_sha256
        or record.intent_commitments != tuple(sorted(_intent_commitments(intent).items()))
    ):
        _fail("fresh_chain_intent_replay_conflict")


def _require_result(
    result: object,
    *,
    intent: FreshChainCallIntent,
    dispatched: bool,
) -> None:
    if (
        type(result) is not FreshChainCallResult
        or result.stage != intent.stage
        or result.ordinal != intent.ordinal
        or result.intent_sha256 != intent.intent_sha256
        or result.transport_dispatched is not dispatched
    ):
        _fail("fresh_chain_result_binding_invalid")


def _require_record_result(
    record: FreshChainStageRecord,
    result: FreshChainCallResult,
) -> None:
    _require_result_for_record = (
        record.result_sha256 == result.result_sha256
        and record.receipt_id == result.receipt_id
        and record.receipt_sha256 == result.physical_receipt_sha256
        and record.token_usage is not None
        and record.token_usage.as_tuple() == result.usage.as_tuple()
        and record.result_commitments == result.commitments
    )
    if not _require_result_for_record:
        _fail("fresh_chain_result_replay_conflict")


def _require_record_failure(
    record: FreshChainStageRecord,
    failure: FreshChainCallFailure,
) -> None:
    if (
        record.status != "failed"
        or record.failure_sha256 != failure.failure_sha256
        or record.provider_disposition != failure.provider_disposition
        or record.receipt_id != failure.receipt_id
        or record.receipt_sha256 != failure.physical_receipt_sha256
        or record.token_usage is None
        or record.token_usage.as_tuple() != failure.usage.as_tuple()
        or record.result_commitments != failure.commitments
    ):
        _fail("fresh_chain_failure_replay_conflict")


def _terminal_result(
    lookup: FreshChainLookup,
    *,
    intent: FreshChainCallIntent,
    dispatched: bool,
    conflict_code: str,
) -> FreshChainCallResult:
    _require_lookup(lookup, intent)
    if lookup.disposition is not FreshChainLookupDisposition.TERMINAL:
        _fail(conflict_code)
    assert lookup.result is not None
    _require_result(lookup.result, intent=intent, dispatched=dispatched)
    return lookup.result


def _terminal_failure(
    lookup: FreshChainLookup,
    *,
    intent: FreshChainCallIntent,
    dispatched: bool,
    conflict_code: str,
) -> FreshChainCallFailure:
    _require_lookup(lookup, intent)
    if lookup.disposition is not FreshChainLookupDisposition.FAILED:
        _fail(conflict_code)
    assert lookup.failure is not None
    _require_failure(lookup.failure, intent=intent, dispatched=dispatched)
    return lookup.failure


def _require_lookup(lookup: object, intent: FreshChainCallIntent) -> None:
    if type(lookup) is not FreshChainLookup or lookup.intent_sha256 != intent.intent_sha256:
        _fail("fresh_chain_lookup_binding_invalid")


def _record_success(
    ledger: FreshChainCanaryLedger,
    result: FreshChainCallResult,
) -> None:
    ledger.record_success(
        result.stage,
        intent_sha256=result.intent_sha256,
        result_sha256=result.result_sha256,
        receipt_id=result.receipt_id,
        receipt_sha256=result.physical_receipt_sha256,
        token_usage=TokenUsage(
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
        ),
        commitments=result.commitments,
    )


def _require_failure(
    failure: object,
    *,
    intent: FreshChainCallIntent,
    dispatched: bool,
) -> None:
    if (
        type(failure) is not FreshChainCallFailure
        or failure.stage != intent.stage
        or failure.ordinal != intent.ordinal
        or failure.intent_sha256 != intent.intent_sha256
        or failure.transport_dispatched is not dispatched
    ):
        _fail("fresh_chain_failure_binding_invalid")


def _record_failure(
    ledger: FreshChainCanaryLedger,
    failure: FreshChainCallFailure,
) -> None:
    ledger.record_failure(
        failure.stage,
        intent_sha256=failure.intent_sha256,
        failure_sha256=failure.failure_sha256,
        receipt_id=failure.receipt_id,
        receipt_sha256=failure.physical_receipt_sha256,
        token_usage=TokenUsage(
            input_tokens=failure.usage.prompt_tokens,
            output_tokens=failure.usage.completion_tokens,
            total_tokens=failure.usage.total_tokens,
        ),
        provider_disposition=failure.provider_disposition,
        commitments=failure.commitments,
    )


def _record_ambiguity_if_needed(
    ledger: FreshChainCanaryLedger,
    intent: FreshChainCallIntent,
    *,
    phase: str,
) -> None:
    snapshot = ledger.read_snapshot()
    record = snapshot.stages[intent.ordinal]
    if record.status == "pending" and record.ambiguity_sha256 is None:
        ledger.record_ambiguous_outcome(
            intent.stage,
            intent_sha256=intent.intent_sha256,
            ambiguity_sha256=canonical_sha256(
                {"intent_sha256": intent.intent_sha256, "phase": phase}
            ),
        )


def _intent_commitments(intent: FreshChainCallIntent) -> dict[str, str]:
    commitments = {
        "namespace_commitment_sha256": intent.namespace_commitment_sha256,
        "source_commitment_sha256": intent.source_commitment_sha256,
        "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
    }
    if intent.retrieval_handoff_sha256 is not None:
        commitments["retrieval_handoff_sha256"] = intent.retrieval_handoff_sha256
    return commitments


def _require_handoff(
    handoff: object,
    *,
    extraction: FreshChainCallResult,
    layout: FreshChainLayout,
) -> None:
    if (
        type(handoff) is not FreshChainRetrievalHandoff
        or handoff.extraction_intent_sha256 != extraction.intent_sha256
        or handoff.extraction_result_sha256 != extraction.result_sha256
        or handoff.extraction_receipt_sha256 != extraction.physical_receipt_sha256
        or handoff.namespace_commitment_sha256 != layout.namespace_commitment_sha256
        or handoff.source_commitment_sha256 != layout.source_commitment_sha256
        or handoff.source_projection_commitment_sha256
        != dict(extraction.commitments).get("source_projection_commitment_sha256")
    ):
        _fail("fresh_chain_retrieval_handoff_binding_invalid")


def _require_ledger_handoff(
    stored: RetrievalHandoff,
    observed: FreshChainRetrievalHandoff,
) -> None:
    commitments = dict(stored.commitments)
    if (
        stored.extraction_result_sha256 != observed.extraction_result_sha256
        or stored.extraction_receipt_sha256 != observed.extraction_receipt_sha256
        or stored.namespace_commitment_sha256 != observed.namespace_commitment_sha256
        or stored.memory_authority_sha256 != observed.memory_authority_sha256
        or stored.retrieval_authority_sha256 != observed.retrieval_authority_sha256
        or stored.memory_count != observed.memory_count
        or commitments.get("extraction_intent_sha256") != observed.extraction_intent_sha256
        or commitments.get("handoff_sha256") != observed.handoff_sha256
        or commitments.get("retrieval_material_sha256") != observed.retrieval_material_sha256
        or commitments.get("source_commitment_sha256") != observed.source_commitment_sha256
        or commitments.get("source_projection_commitment_sha256")
        != observed.source_projection_commitment_sha256
        or commitments.get("memory_count_sha256")
        != canonical_sha256({"memory_count": observed.memory_count})
    ):
        _fail("fresh_chain_retrieval_handoff_replay_conflict")


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ("FreshChainCanaryOrchestrator",)
