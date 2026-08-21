"""Provider-free scheduler-v2 value objects and secret-safe receipts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from hashlib import sha256

from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
)


class SchedulerV2Error(ValueError):
    """Stable, non-secret scheduler-v2 contract failure."""


class AttemptPhase(StrEnum):
    PREPARED = "prepared"
    INTENT_DURABLE = "intent_durable"
    CONSUME_PENDING = "consume_pending"
    CAS_CONSUMED = "cas_consumed"
    DISPATCH_STARTED = "dispatch_started"
    COMPLETED_VERIFIED = "completed_verified"
    OUTCOME_UNKNOWN = "outcome_unknown"
    PREDISPATCH_PROVEN = "predispatch_proven"
    TOMBSTONED = "tombstoned"
    FROZEN_NO_REDISPATCH = "frozen_no_redispatch"


@dataclass(frozen=True, slots=True)
class StateRootFence:
    root_sha256: str
    epoch: int

    def __post_init__(self) -> None:
        _require_sha(self.root_sha256, "state_root_invalid")
        _require_nonnegative(self.epoch, "state_epoch_invalid")


@dataclass(frozen=True, slots=True)
class SlotBinding:
    account_id: str
    suite_authority_sha256: str
    run_authority_sha256: str
    logical_call_sha256: str
    model_id: str
    route_id: str
    profile_id: str
    case_id: str
    backend_id: str
    stage: str
    ordinal: int
    token_ceiling: int
    reservation_tokens: int
    absolute_deadline_unix_ms: int
    payload_byte_ceiling: int
    base_attempt: int = 0
    max_generations: int = 2
    max_provider_dispatches: int = 1
    paid_go_ready: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.suite_authority_sha256,
            self.run_authority_sha256,
            self.logical_call_sha256,
        ):
            _require_sha(value, "slot_authority_invalid")
        strings = (
            self.account_id,
            self.model_id,
            self.route_id,
            self.profile_id,
            self.case_id,
            self.backend_id,
            self.stage,
        )
        ints = (
            self.ordinal,
            self.token_ceiling,
            self.reservation_tokens,
            self.absolute_deadline_unix_ms,
            self.payload_byte_ceiling,
            self.base_attempt,
            self.max_generations,
            self.max_provider_dispatches,
        )
        if (
            any(type(value) is not str or not value for value in strings)
            or any(type(value) is not int for value in ints)
            or self.ordinal < 0
            or self.token_ceiling < 1
            or not 1 <= self.reservation_tokens <= self.token_ceiling
            or self.absolute_deadline_unix_ms < 1
            or self.payload_byte_ceiling < 1
            or self.base_attempt < 0
            or self.max_generations < 1
            or self.max_provider_dispatches != 1
            or self.paid_go_ready is not False
        ):
            _fail("slot_binding_invalid")

    @property
    def logical_slot_id(self) -> str:
        return _canonical_commitment(
            "scheduler-v2-logical-slot-v1",
            {
                "logical_call_sha256": self.logical_call_sha256,
                "run_authority_sha256": self.run_authority_sha256,
                "suite_authority_sha256": self.suite_authority_sha256,
            },
        )

    @property
    def commitment_sha256(self) -> str:
        return _canonical_commitment("scheduler-v2-slot-binding-v1", asdict(self))


@dataclass(frozen=True, slots=True)
class AttemptReceipt:
    logical_slot_id: str
    generation: int
    version: int
    phase: AttemptPhase
    binding_sha256: str
    payload_sha256: str
    intent_sha256: str | None = None
    prior_receipt_sha256: str | None = None
    provider_dispatches: int = 0
    charged_tokens: int = 0
    refunded_tokens: int = 0
    burned_tokens: int = 0
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for value in (self.logical_slot_id, self.binding_sha256, self.payload_sha256):
            _require_sha(value, "attempt_receipt_invalid")
        for value in (self.intent_sha256, self.prior_receipt_sha256):
            if value is not None:
                _require_sha(value, "attempt_receipt_invalid")
        for value in (
            self.generation,
            self.version,
            self.provider_dispatches,
            self.charged_tokens,
            self.refunded_tokens,
            self.burned_tokens,
        ):
            _require_nonnegative(value, "attempt_receipt_invalid")
        if self.provider_dispatches > 1:
            _fail("attempt_receipt_invalid")

    @property
    def commitment_sha256(self) -> str:
        return _canonical_commitment("scheduler-v2-attempt-receipt-v1", asdict(self))


@dataclass(frozen=True, slots=True)
class ConsumeRequest:
    logical_slot_id: str
    generation: int
    version: int
    binding_seal_sha256: str
    intent_sha256: str
    prepared_boot_id: str
    dispatch_boot_id: str
    fence: StateRootFence
    absolute_deadline_unix_ms: int
    reservation_tokens: int
    issue_database_evidence: DatabasePredicateEvidence
    challenge: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_sha(self.logical_slot_id, "consume_request_invalid")
        _require_sha(self.binding_seal_sha256, "consume_request_invalid")
        _require_sha(self.intent_sha256, "consume_request_invalid")
        if (
            type(self.challenge) is not bytes
            or len(self.challenge) != 32
            or type(self.prepared_boot_id) is not str
            or not self.prepared_boot_id
            or type(self.dispatch_boot_id) is not str
            or not self.dispatch_boot_id
            or self.prepared_boot_id == self.dispatch_boot_id
            or type(self.fence) is not StateRootFence
            or type(self.generation) is not int
            or self.generation < 0
            or type(self.version) is not int
            or self.version < 0
            or type(self.absolute_deadline_unix_ms) is not int
            or self.absolute_deadline_unix_ms < 1
            or type(self.issue_database_evidence) is not DatabasePredicateEvidence
            or type(self.reservation_tokens) is not int
            or self.reservation_tokens < 1
        ):
            _fail("consume_request_invalid")


@dataclass(frozen=True, slots=True)
class ConsumeResponse:
    logical_slot_id: str
    generation: int
    consume_database_evidence_sha256: str
    consumed_version: int
    challenge: bytes = field(repr=False)
    authenticator: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_sha(self.logical_slot_id, "consume_response_invalid")
        _require_sha(self.consume_database_evidence_sha256, "consume_response_invalid")
        if (
            type(self.generation) is not int
            or self.generation < 0
            or type(self.consumed_version) is not int
            or self.consumed_version < 0
            or type(self.challenge) is not bytes
            or len(self.challenge) != 32
            or type(self.authenticator) is not bytes
        ):
            _fail("consume_response_invalid")


def _canonical_commitment(schema: str, values: dict[str, object]) -> str:
    material = json.dumps(
        {"schema": schema, "values": values},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return digest_text(material)


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode())


def _require_sha(value: object, code: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        _fail(code)


def _require_nonnegative(value: object, code: str) -> None:
    if type(value) is not int or value < 0:
        _fail(code)


def _fail(code: str) -> None:
    raise SchedulerV2Error(code)


__all__ = (
    "AttemptPhase",
    "AttemptReceipt",
    "ConsumeRequest",
    "ConsumeResponse",
    "SchedulerV2Error",
    "SlotBinding",
    "StateRootFence",
    "digest_bytes",
    "digest_text",
)
