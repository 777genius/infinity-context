"""Immutable logical-call authority enforced by the resumable runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import commitment
from infinity_context_server.publishable_durable_scheduler.manifest import SchedulerLogicalCall
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    SchedulerDispatchEnvelope,
    SchedulerRunnerError,
    is_sha256,
)

SCHEDULER_DISPATCH_AUTHORITY_SCHEMA = "publishable-scheduler-dispatch-authority.v1"
SCHEDULER_DISPATCH_SCOPE_EXCEEDED = "scheduler_runner_dispatch_scope_exceeded"


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerDispatchAuthority:
    """Exact immutable allowlist for one suite's provider dispatches."""

    suite_authority_sha256: str
    ordered_calls: tuple[SchedulerLogicalCall, ...] = field(repr=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        material = self._validated_material()
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("scheduler-dispatch-authority", material),
        )

    @property
    def ordered_logical_call_ids(self) -> tuple[str, ...]:
        return tuple(call.logical_call_id for call in self.ordered_calls)

    def require_authorized(
        self,
        *,
        suite_authority_sha256: str,
        run_authority_sha256: str,
        call: SchedulerLogicalCall,
    ) -> None:
        """Reject unless the complete call is one of the frozen entries."""

        self.verify()
        if (
            suite_authority_sha256 != self.suite_authority_sha256
            or type(call) is not SchedulerLogicalCall
            or call.suite_authority_sha256 != suite_authority_sha256
            or call.run_authority_sha256 != run_authority_sha256
        ):
            _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)
        for allowed in self.ordered_calls:
            if allowed.logical_call_id == call.logical_call_id:
                if allowed != call:
                    _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)
                return
        _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)

    def require_envelope_authorized(self, envelope: SchedulerDispatchEnvelope) -> None:
        """Reject a boundary envelope not bound to one complete allowed call."""

        self.verify()
        if type(envelope) is not SchedulerDispatchEnvelope:
            _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)
        for allowed in self.ordered_calls:
            if allowed.logical_call_id == envelope.logical_call_id:
                if (
                    envelope.suite_authority_sha256 != self.suite_authority_sha256
                    or envelope.run_authority_sha256 != allowed.run_authority_sha256
                    or envelope.stage is not allowed.stage
                    or envelope.ordinal != allowed.ordinal
                    or envelope.token_ceiling != allowed.token_ceiling
                    or (envelope.dependency_answer_ciphertext_sha256 is None)
                    != (allowed.depends_on_logical_call_id is None)
                ):
                    _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)
                return
        _fail(SCHEDULER_DISPATCH_SCOPE_EXCEEDED)

    def verify(self) -> None:
        material = self._validated_material()
        if self.commitment_sha256 != commitment("scheduler-dispatch-authority", material):
            _fail("scheduler_runner_dispatch_authority_invalid")

    def _validated_material(self) -> dict[str, object]:
        calls = self.ordered_calls
        if (
            not is_sha256(self.suite_authority_sha256)
            or type(calls) is not tuple
            or not 1 <= len(calls) <= PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
            or any(type(call) is not SchedulerLogicalCall for call in calls)
            or any(call.suite_authority_sha256 != self.suite_authority_sha256 for call in calls)
            or len({call.logical_call_id for call in calls}) != len(calls)
        ):
            _fail("scheduler_runner_dispatch_authority_invalid")
        return {
            "ordered_logical_call_ids": list(self.ordered_logical_call_ids),
            "schema_version": SCHEDULER_DISPATCH_AUTHORITY_SCHEMA,
            "suite_authority_sha256": self.suite_authority_sha256,
        }

    def __repr__(self) -> str:
        return (
            "SchedulerDispatchAuthority("
            f"commitment_sha256={self.commitment_sha256!r}, calls=<bound>)"
        )


def scheduler_dispatch_authority_sha256(
    authority: SchedulerDispatchAuthority | None,
) -> str | None:
    if authority is None:
        return None
    if type(authority) is not SchedulerDispatchAuthority:
        _fail("scheduler_runner_dispatch_authority_invalid")
    authority.verify()
    return authority.commitment_sha256


def require_scheduler_dispatch_authority(
    authority: SchedulerDispatchAuthority | None,
    *,
    suite_authority_sha256: str,
    run_authority_sha256: str,
    call: SchedulerLogicalCall,
) -> None:
    if authority is None:
        return
    if type(authority) is not SchedulerDispatchAuthority:
        _fail("scheduler_runner_dispatch_authority_invalid")
    authority.require_authorized(
        suite_authority_sha256=suite_authority_sha256,
        run_authority_sha256=run_authority_sha256,
        call=call,
    )


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = (
    "SCHEDULER_DISPATCH_AUTHORITY_SCHEMA",
    "SCHEDULER_DISPATCH_SCOPE_EXCEEDED",
    "SchedulerDispatchAuthority",
    "require_scheduler_dispatch_authority",
    "scheduler_dispatch_authority_sha256",
)
