from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from hashlib import sha256
from threading import RLock

from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    AttemptPhase,
    AttemptReceipt,
    ConsumeRequest,
    ConsumeResponse,
    SchedulerV2Error,
    SlotBinding,
    StateRootFence,
    digest_bytes,
    digest_text,
)
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
)
from infinity_context_server.publishable_durable_scheduler.v2_memory_state import _Attempt
from infinity_context_server.publishable_durable_scheduler.v2_ports import DatabaseClockPort
from infinity_context_server.publishable_durable_scheduler.v2_validation import (
    require_live as _require_live,
)
from infinity_context_server.publishable_durable_scheduler.v2_validation import (
    require_sha as _require_sha,
)


class InMemorySchedulerV2Cas:
    """Executable specification; no provider, runtime, database, or network dependency."""

    paid_go_ready = False

    def __init__(
        self,
        *,
        authentication_key: bytes | None = None,
        challenge_source: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        key = authentication_key or secrets.token_bytes(32)
        if type(key) is not bytes or len(key) < 32:
            _fail("authentication_key_too_short")
        self._key = key
        self._challenge_source = challenge_source
        self._attempts: dict[str, _Attempt] = {}
        self._lock = RLock()

    def prepare(
        self,
        binding: SlotBinding,
        payload: bytes,
        *,
        prepared_boot_id: str,
        fence: StateRootFence,
        now_unix_ms: int,
        database_now_unix_ms: int,
    ) -> AttemptReceipt:
        self._require_payload(binding, payload)
        _require_live(binding, now_unix_ms, database_now_unix_ms)
        if not prepared_boot_id:
            _fail("prepared_boot_invalid")
        with self._lock:
            if binding.logical_slot_id in self._attempts:
                _fail("slot_already_exists_or_tombstoned")
            attempt = _Attempt(
                binding=binding,
                payload_sha256=digest_bytes(payload),
                prepared_boot_id=prepared_boot_id,
                dispatch_boot_id=None,
                prepared_fence=fence,
                generation=0,
                version=1,
                phase=AttemptPhase.PREPARED,
            )
            self._attempts[binding.logical_slot_id] = attempt
            return self._receipt(attempt)

    def record_durable_intent(
        self,
        logical_slot_id: str,
        *,
        generation: int,
        expected_version: int,
        durable_intent_receipt_sha256: str,
        dispatch_boot_id: str,
        fence: StateRootFence,
        now_unix_ms: int,
        database_now_unix_ms: int,
    ) -> AttemptReceipt:
        with self._lock:
            attempt = self._get(logical_slot_id)
            self._require_cas(attempt, generation, expected_version, AttemptPhase.PREPARED)
            self._require_fence(attempt, fence)
            _require_live(attempt.binding, now_unix_ms, database_now_unix_ms)
            if not dispatch_boot_id or dispatch_boot_id == attempt.prepared_boot_id:
                _fail("dispatch_boot_not_fresh")
            _require_sha(durable_intent_receipt_sha256, "durable_intent_receipt_invalid")
            attempt.dispatch_boot_id = dispatch_boot_id
            attempt.intent_sha256 = durable_intent_receipt_sha256
            attempt.phase = AttemptPhase.INTENT_DURABLE
            attempt.version += 1
            return self._receipt(attempt)

    def issue_consume_request(
        self,
        logical_slot_id: str,
        *,
        generation: int,
        expected_version: int,
        fence: StateRootFence,
        now_unix_ms: int,
        database_clock: DatabaseClockPort,
    ) -> ConsumeRequest:
        with self._lock:
            attempt = self._get(logical_slot_id)
            self._require_cas(attempt, generation, expected_version, AttemptPhase.INTENT_DURABLE)
            self._require_fence(attempt, fence)
            predicate = self._issue_predicate(attempt)
            evidence = database_clock.observe(predicate_sha256=predicate)
            self._require_database_evidence(evidence, predicate, attempt.binding)
            _require_live(attempt.binding, now_unix_ms, evidence.observed_unix_ms)
            challenge = self._challenge_source(32)
            if type(challenge) is not bytes or len(challenge) != 32:
                _fail("challenge_source_invalid")
            assert attempt.intent_sha256 is not None
            assert attempt.dispatch_boot_id is not None
            request = ConsumeRequest(
                logical_slot_id=logical_slot_id,
                generation=generation,
                version=attempt.version + 1,
                binding_seal_sha256=attempt.binding.commitment_sha256,
                intent_sha256=attempt.intent_sha256,
                prepared_boot_id=attempt.prepared_boot_id,
                dispatch_boot_id=attempt.dispatch_boot_id,
                fence=fence,
                absolute_deadline_unix_ms=attempt.binding.absolute_deadline_unix_ms,
                reservation_tokens=attempt.binding.reservation_tokens,
                issue_database_evidence=evidence,
                challenge=challenge,
            )
            attempt.pending_request = request
            attempt.phase = AttemptPhase.CONSUME_PENDING
            attempt.version += 1
            return request

    def consume(
        self, request: ConsumeRequest, *, fence: StateRootFence, database_clock: DatabaseClockPort
    ) -> ConsumeResponse:
        """CAS handler requires fresh DB-observed predicate evidence."""
        with self._lock:
            attempt = self._get(request.logical_slot_id)
            if (
                attempt.phase is not AttemptPhase.CONSUME_PENDING
                or attempt.pending_request != request
                or attempt.generation != request.generation
                or attempt.version != request.version
            ):
                _fail("consume_not_fresh")
            self._require_fence(attempt, fence)
            predicate = self._consume_predicate(request)
            evidence = database_clock.observe(predicate_sha256=predicate)
            self._require_database_evidence(evidence, predicate, attempt.binding)
            attempt.phase = AttemptPhase.CAS_CONSUMED
            attempt.version += 1
            response = ConsumeResponse(
                logical_slot_id=request.logical_slot_id,
                generation=request.generation,
                consumed_version=attempt.version,
                consume_database_evidence_sha256=evidence.commitment_sha256,
                challenge=request.challenge,
                authenticator=self._consume_mac(
                    request, attempt.version, evidence.commitment_sha256
                ),
            )
            attempt.consume_database_evidence = evidence
            attempt.consumed_response = response
            return response

    def prove_predispatch_no_consumption(
        self, logical_slot_id: str, *, receipt_sha256: str
    ) -> AttemptReceipt:
        with self._lock:
            attempt = self._get(logical_slot_id)
            if (
                attempt.phase is not AttemptPhase.INTENT_DURABLE
                or attempt.consumed_response is not None
            ):
                _fail("predispatch_not_proven")
            _require_sha(receipt_sha256, "predispatch_receipt_invalid")
            attempt.phase = AttemptPhase.PREDISPATCH_PROVEN
            attempt.reason_code = receipt_sha256
            attempt.version += 1
            return self._receipt(attempt)

    def advance_generation(
        self, logical_slot_id: str, *, prior_receipt_sha256: str
    ) -> AttemptReceipt:
        with self._lock:
            attempt = self._get(logical_slot_id)
            current = self._receipt(attempt)
            if (
                attempt.phase is not AttemptPhase.PREDISPATCH_PROVEN
                or attempt.consumed_response is not None
                or prior_receipt_sha256 != current.commitment_sha256
                or attempt.generation + 1 >= attempt.binding.max_generations
            ):
                _fail("generation_advance_invalid")
            attempt.generation += 1
            attempt.version += 1
            attempt.phase = AttemptPhase.PREPARED
            attempt.dispatch_boot_id = None
            attempt.intent_sha256 = None
            attempt.pending_request = None
            attempt.prior_receipt_sha256 = prior_receipt_sha256
            attempt.reason_code = None
            return self._receipt(attempt)

    def lookup(self, logical_slot_id: str) -> AttemptReceipt | None:
        """Pure observation: never reconciles, leases, expires, or tombstones."""
        with self._lock:
            attempt = self._attempts.get(logical_slot_id)
            return None if attempt is None else self._receipt(attempt)

    def reconcile_missing(self, binding: SlotBinding, *, fence: StateRootFence) -> AttemptReceipt:
        """Mutating no-dispatch reconciliation; missing slots become permanent tombstones."""
        with self._lock:
            attempt = self._attempts.get(binding.logical_slot_id)
            if attempt is None:
                attempt = _Attempt(
                    binding=binding,
                    payload_sha256=digest_bytes(b""),
                    prepared_boot_id="reconciler",
                    dispatch_boot_id=None,
                    prepared_fence=fence,
                    generation=0,
                    version=1,
                    phase=AttemptPhase.TOMBSTONED,
                    reason_code="durable_intent_missing",
                )
                self._attempts[binding.logical_slot_id] = attempt
            elif attempt.phase in (AttemptPhase.PREPARED, AttemptPhase.INTENT_DURABLE):
                attempt.phase = AttemptPhase.TOMBSTONED
                attempt.reason_code = "durable_intent_missing"
                attempt.version += 1
            return self._receipt(attempt)

    def _consume_mac(
        self, request: ConsumeRequest, consumed_version: int, consume_evidence_sha256: str
    ) -> bytes:
        body = b"".join(
            (
                request.logical_slot_id.encode(),
                str(request.generation).encode(),
                str(request.version).encode(),
                str(consumed_version).encode(),
                request.binding_seal_sha256.encode(),
                request.intent_sha256.encode(),
                request.prepared_boot_id.encode(),
                request.dispatch_boot_id.encode(),
                request.fence.root_sha256.encode(),
                str(request.fence.epoch).encode(),
                str(request.absolute_deadline_unix_ms).encode(),
                str(request.reservation_tokens).encode(),
                request.issue_database_evidence.commitment_sha256.encode(),
                consume_evidence_sha256.encode(),
                request.challenge,
            )
        )
        return hmac.digest(self._key, body, sha256)

    @staticmethod
    def _issue_predicate(attempt: _Attempt) -> str:
        return digest_text(
            f"scheduler-v2-issue-consume-v1:{attempt.binding.logical_slot_id}:"
            f"{attempt.generation}:{attempt.version}:{attempt.intent_sha256}"
        )

    @staticmethod
    def _consume_predicate(request: ConsumeRequest) -> str:
        return digest_text(
            f"scheduler-v2-consume-cas-v1:{request.logical_slot_id}:"
            f"{request.generation}:{request.version}:{digest_bytes(request.challenge)}"
        )

    @staticmethod
    def _require_database_evidence(evidence: object, predicate: str, binding: SlotBinding) -> None:
        if (
            type(evidence) is not DatabasePredicateEvidence
            or evidence.predicate_sha256 != predicate
            or evidence.observed_unix_ms >= binding.absolute_deadline_unix_ms
        ):
            _fail("database_predicate_evidence_invalid")

    @staticmethod
    def _require_payload(binding: SlotBinding, payload: bytes) -> None:
        if type(payload) is not bytes or not payload or len(payload) > binding.payload_byte_ceiling:
            _fail("payload_invalid_or_unbounded")

    @staticmethod
    def _require_cas(attempt: _Attempt, generation: int, version: int, phase: AttemptPhase) -> None:
        if (
            type(generation) is not int
            or type(version) is not int
            or attempt.generation != generation
            or attempt.version != version
            or attempt.phase is not phase
        ):
            _fail("attempt_cas_mismatch")

    @staticmethod
    def _require_fence(attempt: _Attempt, fence: StateRootFence) -> None:
        if fence != attempt.prepared_fence:
            _fail("state_root_fence_changed")

    def _get(self, logical_slot_id: str) -> _Attempt:
        attempt = self._attempts.get(logical_slot_id)
        if attempt is None:
            _fail("attempt_missing")
        return attempt

    @staticmethod
    def _receipt(attempt: _Attempt) -> AttemptReceipt:
        return AttemptReceipt(
            logical_slot_id=attempt.binding.logical_slot_id,
            generation=attempt.generation,
            version=attempt.version,
            phase=attempt.phase,
            binding_sha256=attempt.binding.commitment_sha256,
            payload_sha256=attempt.payload_sha256,
            intent_sha256=attempt.intent_sha256,
            prior_receipt_sha256=attempt.prior_receipt_sha256,
            provider_dispatches=attempt.provider_dispatches,
            charged_tokens=attempt.charged_tokens,
            refunded_tokens=attempt.refunded_tokens,
            burned_tokens=attempt.burned_tokens,
            reason_code=attempt.reason_code,
        )


def _fail(code: str) -> None:
    raise SchedulerV2Error(code)


__all__ = ("InMemorySchedulerV2Cas",)
