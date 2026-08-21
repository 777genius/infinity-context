"""Externally verified scheduler-v2 completion; contains no signing capability."""

from __future__ import annotations

from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    AttemptPhase,
    AttemptReceipt,
)
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    ProviderCompletionAttestation,
)
from infinity_context_server.publishable_durable_scheduler.v2_in_memory import (
    InMemorySchedulerV2Cas,
    _fail,
)
from infinity_context_server.publishable_durable_scheduler.v2_ports import (
    CompletionAttestationVerifierPort,
)


class SchedulerV2CompletionCoordinator:
    """Owns a verifier capability selected by trusted outer composition."""

    paid_go_ready = False

    def __init__(
        self,
        store: InMemorySchedulerV2Cas,
        *,
        verifier: CompletionAttestationVerifierPort,
    ) -> None:
        self._store = store
        self._verifier = verifier

    def complete(self, attestation: ProviderCompletionAttestation) -> AttemptReceipt:
        with self._store._lock:
            attempt = self._store._get(attestation.logical_slot_id)
            expected_receipt = self._store._receipt(attempt).commitment_sha256
            if (
                attempt.generation != attestation.generation
                or attempt.phase is not AttemptPhase.DISPATCH_STARTED
                or attempt.dispatch_result_sha256 is None
                or attestation.dispatch_receipt_sha256 != expected_receipt
                or attestation.result_sha256 != attempt.dispatch_result_sha256
                or attestation.bridge_boot_id != attempt.dispatch_boot_id
                or not 0 <= attestation.used_tokens <= attempt.binding.reservation_tokens
                or self._verifier.verify(attestation) is not True
            ):
                _fail("completion_attestation_invalid")
            attempt.charged_tokens = attestation.used_tokens
            attempt.refunded_tokens = attempt.binding.reservation_tokens - attestation.used_tokens
            attempt.phase = AttemptPhase.COMPLETED_VERIFIED
            attempt.version += 1
            return self._store._receipt(attempt)


__all__ = ("SchedulerV2CompletionCoordinator",)
