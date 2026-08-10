"""Nominal execution states for the publishable scheduler v4."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerContractError,
)


class SchedulerRunPhase(StrEnum):
    ACTIVE = "active"
    FROZEN_OUTCOME_UNKNOWN = "frozen_outcome_unknown"
    FAILED_KNOWN = "failed_known"
    DEADLINE_EXHAUSTED = "deadline_exhausted"
    SEALED = "sealed"


class SchedulerCallPhase(StrEnum):
    PLANNED = "planned"
    LEASED = "leased"
    REQUEST_BOUND = "request_bound"
    DISPATCH_INTENT = "dispatch_intent"
    COMMITTED = "committed"
    FAILED_KNOWN = "failed_known"
    OUTCOME_UNKNOWN = "outcome_unknown"


@final
@dataclass(frozen=True, slots=True)
class SchedulerRunState:
    run_id: str
    run_authority_sha256: str
    bridge_boot_authority_sha256: str
    dispatch_not_before_unix_ms: int
    dispatch_deadline_unix_ms: int
    token_ceiling: int
    expected_call_count: int
    phase: SchedulerRunPhase = SchedulerRunPhase.ACTIVE
    reserved_tokens: int = 0
    consumed_tokens: int = 0
    burned_tokens: int = 0
    inflight_logical_call_id: str | None = None
    version: int = 0

    def __post_init__(self) -> None:
        values = (
            self.dispatch_not_before_unix_ms,
            self.dispatch_deadline_unix_ms,
            self.token_ceiling,
            self.expected_call_count,
            self.reserved_tokens,
            self.consumed_tokens,
            self.burned_tokens,
            self.version,
        )
        if (
            type(self.run_id) is not str
            or not self.run_id
            or not is_sha256(self.run_authority_sha256)
            or not is_sha256(self.bridge_boot_authority_sha256)
            or any(type(item) is not int for item in values)
            or self.dispatch_not_before_unix_ms < 0
            or self.dispatch_deadline_unix_ms <= self.dispatch_not_before_unix_ms
            or self.token_ceiling < 1
            or self.expected_call_count < 1
            or min(self.reserved_tokens, self.consumed_tokens, self.burned_tokens, self.version) < 0
            or self.reserved_tokens + self.consumed_tokens + self.burned_tokens > self.token_ceiling
            or self.inflight_logical_call_id is not None
            and not is_sha256(self.inflight_logical_call_id)
            or self.phase is not SchedulerRunPhase.ACTIVE
            and self.inflight_logical_call_id is not None
            or type(self.phase) is not SchedulerRunPhase
        ):
            _fail("scheduler_run_state_invalid")


@final
@dataclass(frozen=True, slots=True)
class SchedulerCallState:
    run_id: str
    run_authority_sha256: str
    logical_call_id: str
    ordinal: int
    stage: SchedulerCallStage
    token_ceiling: int
    depends_on_logical_call_id: str | None
    phase: SchedulerCallPhase = SchedulerCallPhase.PLANNED
    attempt_count: int = 0
    lease_id: str | None = None
    lease_expires_unix_ms: int | None = None
    request_sha256: str | None = None
    intent_sha256: str | None = None
    terminal_evidence_sha256: str | None = None
    charged_tokens: int = 0
    version: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or not is_sha256(self.run_authority_sha256)
            or not is_sha256(self.logical_call_id)
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or type(self.stage) is not SchedulerCallStage
            or type(self.token_ceiling) is not int
            or self.token_ceiling < 1
            or self.depends_on_logical_call_id is not None
            and not is_sha256(self.depends_on_logical_call_id)
            or type(self.phase) is not SchedulerCallPhase
            or type(self.attempt_count) is not int
            or self.attempt_count < 0
            or type(self.charged_tokens) is not int
            or self.charged_tokens < 0
            or type(self.version) is not int
            or self.version < 0
        ):
            _fail("scheduler_call_state_invalid")
        _require_call_phase_shape(self)


def is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _require_call_phase_shape(call: SchedulerCallState) -> None:
    observed = (
        call.lease_id is not None and type(call.lease_expires_unix_ms) is int,
        is_sha256(call.request_sha256),
        is_sha256(call.intent_sha256),
        is_sha256(call.terminal_evidence_sha256),
    )
    terminal = call.phase in (
        SchedulerCallPhase.COMMITTED,
        SchedulerCallPhase.FAILED_KNOWN,
        SchedulerCallPhase.OUTCOME_UNKNOWN,
    )
    expected = {
        SchedulerCallPhase.LEASED: (True, False, False, False),
        SchedulerCallPhase.REQUEST_BOUND: (True, True, False, False),
        SchedulerCallPhase.DISPATCH_INTENT: (True, True, True, False),
    }.get(call.phase, (True, True, True, terminal))
    planned_shapes = {
        (False, False, False, False),
        (False, False, False, True),
    }
    if (
        call.phase is SchedulerCallPhase.PLANNED
        and observed not in planned_shapes
        or call.phase is not SchedulerCallPhase.PLANNED
        and observed != expected
    ):
        _fail("scheduler_call_phase_shape_invalid")
    if (
        call.phase
        not in (
            SchedulerCallPhase.COMMITTED,
            SchedulerCallPhase.FAILED_KNOWN,
        )
        and call.charged_tokens != 0
    ):
        _fail("scheduler_call_charge_invalid")


def _fail(code: str) -> None:
    raise SchedulerContractError(code)


__all__ = (
    "SchedulerCallPhase",
    "SchedulerCallState",
    "SchedulerRunPhase",
    "SchedulerRunState",
    "is_sha256",
)
