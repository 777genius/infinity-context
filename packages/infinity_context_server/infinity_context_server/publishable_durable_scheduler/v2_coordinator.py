"""One-shot dispatch boundary and externally attested completion lifecycle."""

from __future__ import annotations

import hmac

from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    AttemptPhase,
    AttemptReceipt,
    ConsumeRequest,
    ConsumeResponse,
    SchedulerV2Error,
    StateRootFence,
    digest_bytes,
    digest_text,
)
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
    DispatchBoundaryObservation,
)
from infinity_context_server.publishable_durable_scheduler.v2_in_memory import (
    InMemorySchedulerV2Cas,
    _fail,
)
from infinity_context_server.publishable_durable_scheduler.v2_memory_state import _Attempt
from infinity_context_server.publishable_durable_scheduler.v2_ports import (
    DatabaseClockPort,
    DispatchBoundaryPort,
    DispatchStartedFsyncPort,
)


class _FreshBridgeInvocationCapability:
    """Private one-shot invocation; never returned as replayable authorization."""

    __slots__ = ("_spent",)

    def __init__(self) -> None:
        self._spent = False

    def invoke(self, boundary: DispatchBoundaryPort, payload: bytes) -> DispatchBoundaryObservation:
        if self._spent:
            _fail("fresh_capability_reused")
        self._spent = True
        observation = boundary.invoke_once(payload)
        if type(observation) is not DispatchBoundaryObservation:
            _fail("dispatch_boundary_observation_invalid")
        return observation


class SchedulerV2DispatchCoordinator:
    """Consumes CAS freshness and invokes one injected boundary in the same call."""

    paid_go_ready = False

    def __init__(self, store: InMemorySchedulerV2Cas) -> None:
        self._store = store

    def invoke_dispatch_boundary(
        self,
        response: ConsumeResponse,
        payload: bytes,
        *,
        fence: StateRootFence,
        now_unix_ms: int,
        post_fsync_now_unix_ms: int,
        post_fsync_fence: StateRootFence,
        database_clock: DatabaseClockPort,
        fsync_port: DispatchStartedFsyncPort,
        boundary: DispatchBoundaryPort,
    ) -> tuple[AttemptReceipt, DispatchBoundaryObservation]:
        """Durably mark count=1, recheck predicates, then immediately invoke once."""
        with self._store._lock:
            attempt = self._store._get(response.logical_slot_id)
            capability = self._mint_capability(attempt.pending_request, attempt, response, fence)
            self._store._require_payload(attempt.binding, payload)
            if digest_bytes(payload) != attempt.payload_sha256:
                _fail("dispatch_payload_changed")
            self._require_local_live(attempt, now_unix_ms)
            if attempt.provider_dispatches >= attempt.binding.max_provider_dispatches:
                _fail("provider_dispatch_limit")
            attempt.phase = AttemptPhase.DISPATCH_STARTED
            attempt.provider_dispatches = 1
            attempt.version += 1
            started = self._store._receipt(attempt)
            try:
                fsync_port.fsync_dispatch_started(started)
                self._store._require_fence(attempt, post_fsync_fence)
                predicate = digest_text(
                    f"scheduler-v2-dispatch-boundary-v1:{started.commitment_sha256}"
                )
                evidence = database_clock.observe(predicate_sha256=predicate)
                self._require_database_evidence(attempt, evidence, predicate)
                self._require_local_live(attempt, post_fsync_now_unix_ms)
                observation = capability.invoke(boundary, payload)
            except BaseException as error:
                attempt.phase = AttemptPhase.OUTCOME_UNKNOWN
                attempt.burned_tokens = attempt.binding.reservation_tokens
                attempt.reason_code = self._failure_code(error)
                attempt.version += 1
                raise
            attempt.dispatch_result_sha256 = observation.result_sha256
            return started, observation

    def freeze_unknown(self, logical_slot_id: str, *, reason_code: str) -> AttemptReceipt:
        with self._store._lock:
            attempt = self._store._get(logical_slot_id)
            if attempt.phase is not AttemptPhase.DISPATCH_STARTED:
                _fail("unknown_not_dispatch_started")
            if type(reason_code) is not str or not reason_code:
                _fail("unknown_reason_invalid")
            attempt.phase = AttemptPhase.OUTCOME_UNKNOWN
            attempt.burned_tokens = attempt.binding.reservation_tokens
            attempt.reason_code = reason_code
            attempt.version += 1
            return self._store._receipt(attempt)

    def _mint_capability(
        self,
        request: ConsumeRequest | None,
        attempt: _Attempt,
        response: ConsumeResponse,
        fence: StateRootFence,
    ) -> _FreshBridgeInvocationCapability:
        if (
            request is None
            or attempt.phase is not AttemptPhase.CAS_CONSUMED
            or attempt.consumed_response != response
            or response.challenge != request.challenge
            or not hmac.compare_digest(
                response.authenticator,
                self._store._consume_mac(
                    request,
                    response.consumed_version,
                    response.consume_database_evidence_sha256,
                ),
            )
            or response.consumed_version != attempt.version
        ):
            _fail("consume_response_not_fresh")
        self._store._require_fence(attempt, fence)
        return _FreshBridgeInvocationCapability()

    @staticmethod
    def _require_database_evidence(attempt: _Attempt, evidence: object, predicate: str) -> None:
        if (
            type(evidence) is not DatabasePredicateEvidence
            or evidence.predicate_sha256 != predicate
            or evidence.observed_unix_ms >= attempt.binding.absolute_deadline_unix_ms
        ):
            _fail("database_predicate_evidence_invalid")

    @staticmethod
    def _require_local_live(attempt: _Attempt, now_unix_ms: int) -> None:
        if type(now_unix_ms) is not int or now_unix_ms >= attempt.binding.absolute_deadline_unix_ms:
            _fail("absolute_deadline_exhausted")

    @staticmethod
    def _failure_code(error: BaseException) -> str:
        if isinstance(error, SchedulerV2Error):
            return "post_fsync_fence_or_deadline"
        return "dispatch_boundary_outcome_unknown"


__all__ = ("SchedulerV2DispatchCoordinator",)
