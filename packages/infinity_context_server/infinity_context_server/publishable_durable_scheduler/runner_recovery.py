"""Dispatch-intent reconciliation for the resumable scheduler."""

from __future__ import annotations

from collections.abc import Callable

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerDispatchEnvelope,
    SchedulerDispatchOutcome,
    SchedulerDispatchReadback,
    SchedulerDispatchReadbackDisposition,
    SchedulerDispatchReconciliationPort,
    SchedulerRenderedRequest,
    SchedulerRunnerError,
    bound_request_sha256,
    dispatch_intent_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
)

RenderRequest = Callable[[SchedulerLogicalCall], SchedulerRenderedRequest]
RequireOutcome = Callable[..., None]


def reconcile_dispatch_intent(
    *,
    suite: SchedulerSuiteAuthority,
    run: SchedulerRunAuthority,
    manifest: BuiltSchedulerManifest,
    store: SQLiteDurableSchedulerStore,
    call: SchedulerCallState,
    now_unix_ms: int,
    reconciliation: SchedulerDispatchReconciliationPort | None,
    readback_policy_sha256: str,
    render_request: RenderRequest,
    require_outcome: RequireOutcome,
) -> None:
    """Adopt an exact terminal; only expired authenticated absence permits retry."""

    lease_expires = call.lease_expires_unix_ms
    if call.phase is not SchedulerCallPhase.DISPATCH_INTENT or lease_expires is None:
        _fail("scheduler_runner_recovery_state_invalid")
    expired = now_unix_ms >= lease_expires
    if reconciliation is None:
        if expired:
            _freeze(
                suite=suite,
                run=run,
                store=store,
                call=call,
                failure_code="scheduler_runner_outcome_readback_unavailable",
            )
        return
    try:
        manifest_call = _manifest_call(manifest, call.ordinal)
        envelope = _recovery_envelope(
            suite=suite,
            run=run,
            call=call,
            manifest_call=manifest_call,
            rendered=render_request(manifest_call),
            readback_policy_sha256=readback_policy_sha256,
        )
        readback = reconciliation.lookup(envelope)
        if type(readback) is not SchedulerDispatchReadback:
            _fail("scheduler_runner_dispatch_readback_invalid")
        SchedulerDispatchReadback.__post_init__(readback)
        if (
            readback.readback_policy_sha256 != readback_policy_sha256
            or readback.request_sha256 != envelope.request_sha256
            or readback.intent_sha256 != envelope.intent_sha256
            or reconciliation.authenticate(readback=readback, envelope=envelope) is not True
        ):
            _fail("scheduler_runner_dispatch_readback_unauthenticated")
    except Exception as error:
        if not expired:
            raise SchedulerRunnerError(_failure_code(error)) from error
        _freeze(
            suite=suite,
            run=run,
            store=store,
            call=call,
            failure_code=_failure_code(error),
        )
        return
    if readback.disposition is SchedulerDispatchReadbackDisposition.FOUND:
        outcome_verified = False
        try:
            outcome = readback.outcome
            require_outcome(outcome, envelope=envelope, call=manifest_call)
            outcome_verified = True
            if outcome is None:
                _fail("scheduler_runner_dispatch_readback_invalid")
            store.commit_outcome(
                call.logical_call_id,
                intent_sha256=envelope.intent_sha256,
                receipt_sha256=outcome.receipt.commitment_sha256,
                completion_tokens=outcome.receipt.completion_tokens,
                charged_tokens=outcome.receipt.charged_tokens,
                answer_ciphertext=outcome.private_output_ciphertext,
            )
            return
        except Exception as error:
            current = store.read_call(call.logical_call_id)
            if current.phase is SchedulerCallPhase.COMMITTED:
                if outcome_verified and _committed_matches(store, current, outcome):
                    return
                raise SchedulerRunnerError(
                    "scheduler_runner_dispatch_recovery_divergent"
                ) from error
            if not expired:
                raise SchedulerRunnerError(
                    "scheduler_runner_dispatch_recovery_divergent"
                ) from error
            _freeze(
                suite=suite,
                run=run,
                store=store,
                call=call,
                failure_code=_failure_code(error),
                readback=readback,
            )
            return
    if not expired:
        return
    if readback.disposition is SchedulerDispatchReadbackDisposition.TERMINAL_ABSENT:
        try:
            store.reconcile_authenticated_terminal_absence(
                call.logical_call_id,
                now_unix_ms=now_unix_ms,
                lease_id=call.lease_id or "",
                intent_sha256=call.intent_sha256 or "",
                absence_sha256=readback.commitment_sha256,
            )
            return
        except Exception as error:
            current = store.read_call(call.logical_call_id)
            if current.phase is SchedulerCallPhase.COMMITTED:
                return
            if (
                current.phase is SchedulerCallPhase.PLANNED
                and current.attempt_count == call.attempt_count
                and current.terminal_evidence_sha256 == readback.commitment_sha256
            ):
                return
            raise SchedulerRunnerError("scheduler_runner_dispatch_recovery_divergent") from error
    _freeze(
        suite=suite,
        run=run,
        store=store,
        call=call,
        failure_code="scheduler_runner_dispatch_readback_ambiguous",
        readback=readback,
    )


def _recovery_envelope(
    *,
    suite: SchedulerSuiteAuthority,
    run: SchedulerRunAuthority,
    call: SchedulerCallState,
    manifest_call: SchedulerLogicalCall,
    rendered: SchedulerRenderedRequest,
    readback_policy_sha256: str,
) -> SchedulerDispatchEnvelope:
    request_sha256 = bound_request_sha256(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
        renderer_policy_sha256=rendered.renderer_policy_sha256,
        private_answer_policy_sha256=rendered.private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=rendered.dependency_answer_ciphertext_sha256,
        call=manifest_call,
        payload=rendered.payload,
    )
    deadline = run.binding.limits.dispatch_deadline_unix_ms
    intent_sha256 = dispatch_intent_sha256(
        envelope_binding={
            "attempt_count": call.attempt_count,
            "bridge_boot_authority_sha256": suite.bridge_boot.commitment_sha256,
            "dispatch_deadline_unix_ms": deadline,
            "dependency_answer_ciphertext_sha256": (rendered.dependency_answer_ciphertext_sha256),
            "lease_id": call.lease_id,
            "logical_call_id": call.logical_call_id,
            "private_answer_policy_sha256": rendered.private_answer_policy_sha256,
            "readback_policy_sha256": readback_policy_sha256,
            "renderer_policy_sha256": rendered.renderer_policy_sha256,
            "request_sha256": request_sha256,
            "run_authority_sha256": run.commitment_sha256,
            "suite_authority_sha256": suite.commitment_sha256,
            "token_ceiling": call.token_ceiling,
        }
    )
    if request_sha256 != call.request_sha256 or intent_sha256 != call.intent_sha256:
        _fail("scheduler_runner_dispatch_recovery_binding_invalid")
    return SchedulerDispatchEnvelope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
        logical_call_id=call.logical_call_id,
        stage=call.stage,
        ordinal=call.ordinal,
        renderer_policy_sha256=rendered.renderer_policy_sha256,
        private_answer_policy_sha256=rendered.private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=rendered.dependency_answer_ciphertext_sha256,
        request_sha256=request_sha256,
        intent_sha256=intent_sha256,
        token_ceiling=call.token_ceiling,
        dispatch_deadline_unix_ms=deadline,
        payload=rendered.payload,
    )


def _freeze(
    *,
    suite: SchedulerSuiteAuthority,
    run: SchedulerRunAuthority,
    store: SQLiteDurableSchedulerStore,
    call: SchedulerCallState,
    failure_code: str,
    readback: SchedulerDispatchReadback | None = None,
) -> None:
    ambiguity_sha256 = commitment(
        "runner-recovered-dispatch-intent",
        {
            "failure_code": failure_code,
            "intent_sha256": call.intent_sha256,
            "logical_call_id": call.logical_call_id,
            "readback_sha256": None if readback is None else readback.commitment_sha256,
            "run_authority_sha256": run.commitment_sha256,
            "suite_authority_sha256": suite.commitment_sha256,
        },
    )
    current = store.read_call(call.logical_call_id)
    if current.phase is SchedulerCallPhase.COMMITTED:
        return
    if current.phase is SchedulerCallPhase.OUTCOME_UNKNOWN:
        if current.terminal_evidence_sha256 != ambiguity_sha256:
            _fail("scheduler_runner_dispatch_recovery_divergent")
        return
    if (
        current.phase is not SchedulerCallPhase.DISPATCH_INTENT
        or current.intent_sha256 != call.intent_sha256
    ):
        _fail("scheduler_runner_dispatch_recovery_invalid")
    try:
        store.record_ambiguous_outcome(
            call.logical_call_id,
            intent_sha256=call.intent_sha256 or "",
            ambiguity_sha256=ambiguity_sha256,
        )
    except Exception as error:
        current = store.read_call(call.logical_call_id)
        if current.phase is SchedulerCallPhase.COMMITTED:
            return
        if (
            current.phase is SchedulerCallPhase.OUTCOME_UNKNOWN
            and current.terminal_evidence_sha256 == ambiguity_sha256
        ):
            return
        raise SchedulerRunnerError("scheduler_runner_dispatch_recovery_divergent") from error


def _committed_matches(
    store: SQLiteDurableSchedulerStore,
    current: SchedulerCallState,
    outcome: SchedulerDispatchOutcome | None,
) -> bool:
    if (
        type(outcome) is not SchedulerDispatchOutcome
        or current.terminal_evidence_sha256 != outcome.receipt.commitment_sha256
        or current.charged_tokens != outcome.receipt.charged_tokens
    ):
        return False
    if current.stage.value == "judge":
        return outcome.private_output_ciphertext is None
    try:
        return (
            store.read_private_answer_ciphertext(current.logical_call_id)
            == outcome.private_output_ciphertext
        )
    except Exception:
        return False


def _manifest_call(manifest: BuiltSchedulerManifest, ordinal: int) -> SchedulerLogicalCall:
    try:
        shard = manifest.shards[ordinal // 256]
        return shard.calls[ordinal - shard.start_ordinal]
    except (IndexError, TypeError):
        _fail("scheduler_runner_manifest_call_missing")


def _failure_code(error: BaseException) -> str:
    if isinstance(error, SchedulerRunnerError):
        return error.code
    return "scheduler_runner_dispatch_readback_failed"


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = ("reconcile_dispatch_intent",)
