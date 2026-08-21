"""Package-private mutable state for the scheduler-v2 in-memory reference."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    AttemptPhase,
    ConsumeRequest,
    ConsumeResponse,
    SlotBinding,
    StateRootFence,
)
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
)


@dataclass(slots=True)
class _Attempt:
    binding: SlotBinding
    payload_sha256: str
    prepared_boot_id: str
    dispatch_boot_id: str | None
    prepared_fence: StateRootFence
    generation: int
    version: int
    phase: AttemptPhase
    intent_sha256: str | None = None
    prior_receipt_sha256: str | None = None
    pending_request: ConsumeRequest | None = None
    consumed_response: ConsumeResponse | None = None
    consume_database_evidence: DatabasePredicateEvidence | None = None
    provider_dispatches: int = 0
    charged_tokens: int = 0
    refunded_tokens: int = 0
    burned_tokens: int = 0
    reason_code: str | None = None
    dispatch_result_sha256: str | None = None


__all__ = ()
