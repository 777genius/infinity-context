"""Pure state-transition validator for the publishable scheduler v4."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    require_run_authority,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerLogicalCall,
    SchedulerManifestShard,
    SchedulerRunManifestAuthority,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
    SchedulerRunPhase,
    SchedulerRunState,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    is_sha256 as _sha,
)


@final
class SchedulerStateTransitionValidator:
    """Validate one run against its immutable authority on every transition."""

    __slots__ = ("_authority", "_manifest")

    def __init__(
        self,
        suite: SchedulerSuiteAuthority,
        authority: SchedulerRunAuthority,
        manifest: SchedulerRunManifestAuthority,
    ) -> None:
        self._authority = require_run_authority(suite, authority)
        if (
            type(manifest) is not SchedulerRunManifestAuthority
            or manifest.suite_authority_sha256 != suite.commitment_sha256
            or manifest.run_authority_sha256 != authority.commitment_sha256
            or manifest.run_id != authority.binding.run_id
            or manifest.case_manifest_sha256 != authority.binding.case_manifest_sha256
            or manifest.call_count != authority.binding.profile.call_count
            or len(manifest.ordered_shard_commitments) != authority.binding.profile.shard_count
        ):
            _fail("scheduler_transition_manifest_invalid")
        self._manifest = manifest

    def initial_run(self) -> SchedulerRunState:
        limits = self._authority.binding.limits
        return SchedulerRunState(
            run_id=self._authority.binding.run_id,
            run_authority_sha256=self._authority.commitment_sha256,
            bridge_boot_authority_sha256=self._authority.bridge_boot_authority_sha256,
            dispatch_not_before_unix_ms=limits.dispatch_not_before_unix_ms,
            dispatch_deadline_unix_ms=limits.dispatch_deadline_unix_ms,
            token_ceiling=limits.run_token_ceiling,
            expected_call_count=self._authority.binding.profile.call_count,
        )

    def initial_call(
        self, call: SchedulerLogicalCall, *, shard: SchedulerManifestShard
    ) -> SchedulerCallState:
        self._require_call_identity(call)
        if (
            type(shard) is not SchedulerManifestShard
            or shard.shard_index >= len(self._manifest.ordered_shard_commitments)
            or shard.commitment_sha256
            != self._manifest.ordered_shard_commitments[shard.shard_index]
            or shard.run_authority_sha256 != self._authority.commitment_sha256
            or not shard.start_ordinal <= call.ordinal < shard.end_ordinal
            or shard.calls[call.ordinal - shard.start_ordinal] != call
        ):
            _fail("scheduler_call_manifest_membership_invalid")
        return SchedulerCallState(
            run_id=call.run_id,
            run_authority_sha256=call.run_authority_sha256,
            logical_call_id=call.logical_call_id,
            ordinal=call.ordinal,
            stage=call.stage,
            token_ceiling=call.token_ceiling,
            depends_on_logical_call_id=call.depends_on_logical_call_id,
        )

    def acquire_lease(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        now_unix_ms: int,
        lease_id: str,
        lease_expires_unix_ms: int,
        dependency: SchedulerCallState | None = None,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_pair(run, call)
        _time(now_unix_ms)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or call.phase is not SchedulerCallPhase.PLANNED
            or run.inflight_logical_call_id is not None
            or now_unix_ms < run.dispatch_not_before_unix_ms
            or now_unix_ms >= run.dispatch_deadline_unix_ms
            or type(lease_id) is not str
            or not lease_id
            or type(lease_expires_unix_ms) is not int
            or not now_unix_ms < lease_expires_unix_ms <= run.dispatch_deadline_unix_ms
        ):
            _fail("scheduler_lease_acquire_invalid")
        self._require_dependency(call, dependency)
        return replace(
            run,
            inflight_logical_call_id=call.logical_call_id,
            version=run.version + 1,
        ), replace(
            call,
            phase=SchedulerCallPhase.LEASED,
            attempt_count=call.attempt_count + 1,
            lease_id=lease_id,
            lease_expires_unix_ms=lease_expires_unix_ms,
            version=call.version + 1,
        )

    def bind_request(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        lease_id: str,
        request_sha256: str,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_pair(run, call)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or call.phase is not SchedulerCallPhase.LEASED
            or call.lease_id != lease_id
            or not _sha(request_sha256)
            or run.reserved_tokens + run.consumed_tokens + run.burned_tokens + call.token_ceiling
            > run.token_ceiling
        ):
            _fail("scheduler_request_bind_invalid")
        return replace(
            run,
            reserved_tokens=run.reserved_tokens + call.token_ceiling,
            version=run.version + 1,
        ), replace(
            call,
            phase=SchedulerCallPhase.REQUEST_BOUND,
            request_sha256=request_sha256,
            version=call.version + 1,
        )

    def record_dispatch_intent(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        lease_id: str,
        now_unix_ms: int,
        bridge_boot_authority_sha256: str,
        intent_sha256: str,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_pair(run, call)
        _time(now_unix_ms)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or call.phase is not SchedulerCallPhase.REQUEST_BOUND
            or call.lease_id != lease_id
            or call.lease_expires_unix_ms is None
            or now_unix_ms >= call.lease_expires_unix_ms
            or now_unix_ms >= run.dispatch_deadline_unix_ms
            or bridge_boot_authority_sha256 != run.bridge_boot_authority_sha256
            or not _sha(intent_sha256)
        ):
            _fail("scheduler_dispatch_intent_invalid")
        return run, replace(
            call,
            phase=SchedulerCallPhase.DISPATCH_INTENT,
            intent_sha256=intent_sha256,
            version=call.version + 1,
        )

    def commit_outcome(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        intent_sha256: str,
        receipt_sha256: str,
        charged_tokens: int,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_intent(run, call, intent_sha256)
        _charge(charged_tokens, call.token_ceiling)
        return self._terminal(
            run,
            call,
            run_phase=SchedulerRunPhase.ACTIVE,
            call_phase=SchedulerCallPhase.COMMITTED,
            evidence_sha256=receipt_sha256,
            charged_tokens=charged_tokens,
            burned_tokens=0,
        )

    def record_known_failure(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        intent_sha256: str,
        failure_sha256: str,
        charged_tokens: int,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_intent(run, call, intent_sha256)
        _charge(charged_tokens, call.token_ceiling)
        return self._terminal(
            run,
            call,
            run_phase=SchedulerRunPhase.FAILED_KNOWN,
            call_phase=SchedulerCallPhase.FAILED_KNOWN,
            evidence_sha256=failure_sha256,
            charged_tokens=charged_tokens,
            burned_tokens=0,
        )

    def record_ambiguous_outcome(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        intent_sha256: str,
        ambiguity_sha256: str,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_intent(run, call, intent_sha256)
        return self._terminal(
            run,
            call,
            run_phase=SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN,
            call_phase=SchedulerCallPhase.OUTCOME_UNKNOWN,
            evidence_sha256=ambiguity_sha256,
            charged_tokens=0,
            burned_tokens=call.token_ceiling,
        )

    def reclaim_expired_no_intent_lease(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        now_unix_ms: int,
        lease_id: str,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        self._require_pair(run, call)
        _time(now_unix_ms)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or call.phase not in (SchedulerCallPhase.LEASED, SchedulerCallPhase.REQUEST_BOUND)
            or call.lease_id != lease_id
            or call.lease_expires_unix_ms is None
            or now_unix_ms < call.lease_expires_unix_ms
            or call.intent_sha256 is not None
        ):
            _fail("scheduler_lease_reclaim_invalid")
        reserved = call.token_ceiling if call.phase is SchedulerCallPhase.REQUEST_BOUND else 0
        return replace(
            run,
            reserved_tokens=run.reserved_tokens - reserved,
            inflight_logical_call_id=None,
            version=run.version + 1,
        ), replace(
            call,
            phase=SchedulerCallPhase.PLANNED,
            lease_id=None,
            lease_expires_unix_ms=None,
            request_sha256=None,
            version=call.version + 1,
        )

    def seal_run(
        self,
        run: SchedulerRunState,
        calls: tuple[SchedulerCallState, ...],
    ) -> SchedulerRunState:
        self._require_run(run)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or run.reserved_tokens != 0
            or run.inflight_logical_call_id is not None
            or type(calls) is not tuple
            or len(calls) != run.expected_call_count
            or any(type(item) is not SchedulerCallState for item in calls)
            or tuple(item.ordinal for item in calls) != tuple(range(run.expected_call_count))
            or any(
                item.run_id != run.run_id
                or item.run_authority_sha256 != run.run_authority_sha256
                or item.phase is not SchedulerCallPhase.COMMITTED
                for item in calls
            )
        ):
            _fail("scheduler_run_seal_invalid")
        return replace(run, phase=SchedulerRunPhase.SEALED, version=run.version + 1)

    def exhaust_deadline(
        self,
        run: SchedulerRunState,
        calls: tuple[SchedulerCallState, ...],
        *,
        now_unix_ms: int,
    ) -> SchedulerRunState:
        self._require_run(run)
        _time(now_unix_ms)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or now_unix_ms < run.dispatch_deadline_unix_ms
            or run.reserved_tokens != 0
            or run.inflight_logical_call_id is not None
            or type(calls) is not tuple
            or len(calls) != run.expected_call_count
            or any(type(item) is not SchedulerCallState for item in calls)
            or tuple(item.ordinal for item in calls) != tuple(range(run.expected_call_count))
            or any(
                item.run_id != run.run_id
                or item.run_authority_sha256 != run.run_authority_sha256
                or item.phase
                not in (
                    SchedulerCallPhase.PLANNED,
                    SchedulerCallPhase.COMMITTED,
                )
                for item in calls
            )
        ):
            _fail("scheduler_deadline_exhaustion_invalid")
        return replace(
            run,
            phase=SchedulerRunPhase.DEADLINE_EXHAUSTED,
            version=run.version + 1,
        )

    def _terminal(
        self,
        run: SchedulerRunState,
        call: SchedulerCallState,
        *,
        run_phase: SchedulerRunPhase,
        call_phase: SchedulerCallPhase,
        evidence_sha256: str,
        charged_tokens: int,
        burned_tokens: int,
    ) -> tuple[SchedulerRunState, SchedulerCallState]:
        if not _sha(evidence_sha256):
            _fail("scheduler_terminal_evidence_invalid")
        return replace(
            run,
            phase=run_phase,
            reserved_tokens=run.reserved_tokens - call.token_ceiling,
            consumed_tokens=run.consumed_tokens + charged_tokens,
            burned_tokens=run.burned_tokens + burned_tokens,
            inflight_logical_call_id=None,
            version=run.version + 1,
        ), replace(
            call,
            phase=call_phase,
            terminal_evidence_sha256=evidence_sha256,
            charged_tokens=charged_tokens,
            version=call.version + 1,
        )

    def _require_intent(
        self, run: SchedulerRunState, call: SchedulerCallState, intent_sha256: str
    ) -> None:
        self._require_pair(run, call)
        if (
            run.phase is not SchedulerRunPhase.ACTIVE
            or call.phase is not SchedulerCallPhase.DISPATCH_INTENT
            or call.intent_sha256 != intent_sha256
        ):
            _fail("scheduler_intent_resolution_invalid")

    def _require_pair(self, run: SchedulerRunState, call: SchedulerCallState) -> None:
        self._require_run(run)
        if (
            type(call) is not SchedulerCallState
            or call.run_id != run.run_id
            or call.run_authority_sha256 != run.run_authority_sha256
            or call.phase
            in (
                SchedulerCallPhase.LEASED,
                SchedulerCallPhase.REQUEST_BOUND,
                SchedulerCallPhase.DISPATCH_INTENT,
            )
            and run.inflight_logical_call_id != call.logical_call_id
        ):
            _fail("scheduler_cross_run_state_invalid")

    def _require_run(self, run: SchedulerRunState) -> None:
        authority = self._authority
        limits = authority.binding.limits
        if (
            type(run) is not SchedulerRunState
            or run.run_id != authority.binding.run_id
            or run.run_authority_sha256 != authority.commitment_sha256
            or run.bridge_boot_authority_sha256 != authority.bridge_boot_authority_sha256
            or run.dispatch_not_before_unix_ms != limits.dispatch_not_before_unix_ms
            or run.dispatch_deadline_unix_ms != limits.dispatch_deadline_unix_ms
            or run.token_ceiling != limits.run_token_ceiling
            or run.expected_call_count != authority.binding.profile.call_count
        ):
            _fail("scheduler_run_state_authority_drift")

    def _require_call_identity(self, call: SchedulerLogicalCall) -> None:
        if (
            type(call) is not SchedulerLogicalCall
            or call.run_id != self._authority.binding.run_id
            or call.run_authority_sha256 != self._authority.commitment_sha256
            or call.suite_authority_sha256 != self._authority.suite_authority_sha256
        ):
            _fail("scheduler_call_authority_drift")

    @staticmethod
    def _require_dependency(
        call: SchedulerCallState, dependency: SchedulerCallState | None
    ) -> None:
        if call.stage is SchedulerCallStage.ANSWER:
            if dependency is not None:
                _fail("scheduler_answer_dependency_state_invalid")
            return
        if (
            type(dependency) is not SchedulerCallState
            or dependency.run_id != call.run_id
            or dependency.run_authority_sha256 != call.run_authority_sha256
            or dependency.logical_call_id != call.depends_on_logical_call_id
            or dependency.phase is not SchedulerCallPhase.COMMITTED
        ):
            _fail("scheduler_judge_dependency_state_invalid")


def _time(value: object) -> int:
    if type(value) is not int or value < 0:
        _fail("scheduler_time_invalid")
    return value


def _charge(value: object, ceiling: int) -> int:
    if type(value) is not int or not 0 <= value <= ceiling:
        _fail("scheduler_token_charge_invalid")
    return value


def _fail(code: str) -> None:
    raise SchedulerContractError(code)


__all__ = (
    "SchedulerCallPhase",
    "SchedulerCallState",
    "SchedulerRunPhase",
    "SchedulerRunState",
    "SchedulerStateTransitionValidator",
)
