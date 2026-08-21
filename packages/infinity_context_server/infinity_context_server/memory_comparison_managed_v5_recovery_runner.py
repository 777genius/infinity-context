"""Provider-free state machine for managed-v5 crash recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, final

from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRunLifecycleSnapshot,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournal,
    ManagedV5LiveRecoveryJournalStore,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_mem0 import (
    ManagedV5RecoveryMem0Error,
    RecoveryMem0Readback,
    RecoveryMem0Terminal,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    ManagedV5RecoveryError,
    RecoveryRegistryCoordinator,
    RecoveryRegistryPort,
    registration_details,
    require_cleanup_receipt,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    blocked as _blocked,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    retry as _retry,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_report import (
    RECOVERY_REPORT_SCHEMA,
    CanonicalRecoveryProjection,
    ManagedV5RecoveryReport,
    Mem0RecoveryProjection,
    write_recovery_report,
)


class RecoveryMem0Port(Protocol):
    def recover(self, *, execution_started: bool) -> RecoveryMem0Terminal: ...
    def pass_two(self, *, terminal: RecoveryMem0Terminal) -> RecoveryMem0Readback: ...


@final
class ManagedV5RecoveryRunner:
    __slots__ = (
        "_authority",
        "_cleanup_plan",
        "_journal",
        "_mem0",
        "_clock",
        "_registry_factory",
    )

    def __init__(
        self,
        *,
        authority: ManagedV5LiveRecoveryAuthority,
        cleanup_plan: ManagedBenchmarkCleanupPlan,
        journal: ManagedV5LiveRecoveryJournalStore,
        registry_factory: Callable[[], RecoveryRegistryPort],
        mem0: RecoveryMem0Port,
        clock: Callable[[], datetime],
    ) -> None:
        if (
            type(authority) is not ManagedV5LiveRecoveryAuthority
            or type(cleanup_plan) is not ManagedBenchmarkCleanupPlan
            or type(journal) is not ManagedV5LiveRecoveryJournalStore
            or not callable(registry_factory)
            or not callable(getattr(mem0, "recover", None))
            or not callable(getattr(mem0, "pass_two", None))
            or not callable(clock)
        ):
            _blocked("managed_v5_recovery_runner_inputs_invalid")
        self._authority = authority
        self._cleanup_plan = cleanup_plan
        self._journal = journal
        self._registry_factory = RecoveryRegistryCoordinator(
            authority=authority, cleanup_plan=cleanup_plan, factory=registry_factory
        )
        self._mem0 = mem0
        self._clock = clock

    def run(self) -> ManagedV5RecoveryReport:
        try:
            return self._run()
        except ManagedV5RecoveryError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _blocked("managed_v5_recovery_unexpected_failure")

    def _run(self) -> ManagedV5RecoveryReport:
        current = self._journal.load(expected_authority=self._authority)
        if not any(event.kind == "cleanup_plan_prepared" for event in current.events):
            return ManagedV5RecoveryReport(
                True,
                "completed",
                "no_registration",
                self._authority.run_id_sha256,
                self._authority.binding_commitment_sha256,
                self._authority.infinity_target_identity_sha256,
                self._authority.space_slug,
                None,
                None,
                "not_registered",
                None,
                current.events[-1].event_sha256,
                current.body_sha256,
            )
        cleanup_plan_sha = _event_digest(current, "cleanup_plan_sha256")
        if (
            self._cleanup_plan.sha256 != cleanup_plan_sha
            or current.cleanup_plan_sha256 != cleanup_plan_sha
            or current.cleanup_plan != self._cleanup_plan.value
        ):
            _blocked("managed_v5_recovery_cleanup_plan_mismatch")
        before_snapshot = self._registry_factory.recover_initial(cleanup_plan_sha)
        before = _project_snapshot(before_snapshot)
        current = self._reconcile_event(
            current, "registration_observed", registration_details(before_snapshot)
        )
        cleanup_snapshot = before_snapshot
        if before_snapshot.state == "active":
            cleanup_snapshot = self._registry_factory.recover_projection_seal(
                current, before_snapshot, cleanup_plan_sha
            )
            if cleanup_snapshot.projection_cleanup_state == "sealed":
                current = self._record_registry_seal(
                    current, cleanup_plan_sha, cleanup_snapshot.projection_manifest_sha256
                )
            cleanup_snapshot = self._registry_factory.begin_cleanup(cleanup_plan_sha)
        cleanup = require_cleanup_receipt(cleanup_snapshot)
        current = self._reconcile_event(
            current,
            "cleanup_observed",
            {
                "cleanup_plan_sha256": cleanup_plan_sha,
                "cleanup_receipt_sha256": cleanup.receipt_sha256,
                "projection_cleanup_state": cleanup.projection_cleanup,
            },
        )
        execution_started = any(event.kind == "execution_started" for event in current.events)
        try:
            terminal = self._mem0.recover(execution_started=execution_started)
        except ManagedV5RecoveryMem0Error as error:
            if error.retryable:
                _retry(error.code)
            raise
        if type(terminal) is not RecoveryMem0Terminal:
            _blocked("managed_v5_recovery_mem0_terminal_invalid")
        if terminal.terminal_state == "not_started":
            readback = RecoveryMem0Readback(terminal.clean_state_witness_sha256)
        else:
            try:
                readback = self._mem0.pass_two(terminal=terminal)
            except ManagedV5RecoveryMem0Error as error:
                if error.retryable:
                    _retry(error.code)
                raise
            if type(readback) is not RecoveryMem0Readback:
                _blocked("managed_v5_recovery_mem0_readback_invalid")
        mem0_after = Mem0RecoveryProjection(
            terminal.terminal_state,
            terminal.terminal_commitment_sha256,
            readback.witness_sha256,
        )
        current = self._reconcile_event(current, "mem0_terminal_observed", mem0_after.payload())
        final_snapshot = self._registry_factory.finalize(
            cleanup_plan_sha=cleanup_plan_sha,
            cleanup_receipt_sha=cleanup.receipt_sha256,
        )
        after = _project_snapshot(final_snapshot)
        completion = final_snapshot.completion_receipt
        if after.state not in {"cleanup_complete", "cleanup_aborted"}:
            _retry("managed_v5_recovery_canonical_terminal_unknown")
        if completion is None:
            _blocked("managed_v5_recovery_completion_receipt_missing")
        current = self._reconcile_event(
            current,
            "canonical_terminal_observed",
            {
                "state": after.state,
                "projection_cleanup_state": after.projection_cleanup_state,
                "completion_receipt_sha256": completion.receipt_sha256,
                "cleanup_plan_sha256": cleanup_plan_sha,
            },
        )
        return ManagedV5RecoveryReport(
            True,
            "completed",
            "recovery_completed",
            self._authority.run_id_sha256,
            self._authority.binding_commitment_sha256,
            self._authority.infinity_target_identity_sha256,
            self._authority.space_slug,
            before,
            after,
            "execution_started" if execution_started else "pre_execution",
            mem0_after,
            current.events[-1].event_sha256,
            current.body_sha256,
        )

    def _record_registry_seal(
        self,
        current: ManagedV5LiveRecoveryJournal,
        cleanup_plan_sha: str,
        manifest_sha: str | None,
    ) -> ManagedV5LiveRecoveryJournal:
        if not _sha(manifest_sha):
            _blocked("managed_v5_recovery_projection_manifest_invalid")
        return self._reconcile_event(
            current,
            "registry_seal_observed",
            {
                "cleanup_plan_sha256": cleanup_plan_sha,
                "projection_manifest_sha256": manifest_sha,
                "projection_cleanup_state": "sealed",
            },
        )

    def _reconcile_event(
        self, current: ManagedV5LiveRecoveryJournal, kind: str, details: dict[str, object]
    ) -> ManagedV5LiveRecoveryJournal:
        existing = next((event for event in current.events if event.kind == kind), None)
        if existing is not None:
            if existing.details != details:
                _blocked("managed_v5_recovery_observation_mismatch")
            return current
        return self._append(current, kind, details)

    def _append(
        self, current: ManagedV5LiveRecoveryJournal, kind: str, details: dict[str, object]
    ) -> ManagedV5LiveRecoveryJournal:
        del current
        return self._journal.append(
            expected_authority=self._authority,
            kind=kind,
            recorded_at=_recorded_at(self._clock),
            details=details,
        )


def _project_snapshot(value: ManagedBenchmarkRunLifecycleSnapshot) -> CanonicalRecoveryProjection:
    cleanup = value.cleanup_receipt
    completion = value.completion_receipt
    return CanonicalRecoveryProjection(
        value.state,
        value.projection_cleanup_state,
        value.cleanup_plan_sha256,
        None if cleanup is None else cleanup.receipt_sha256,
        None if completion is None else completion.receipt_sha256,
    )


def _event_digest(journal: ManagedV5LiveRecoveryJournal, key: str) -> str:
    for event in journal.events:
        value = event.details.get(key)
        if _sha(value):
            return value
    _blocked("managed_v5_recovery_cleanup_plan_missing")


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _recorded_at(clock: Callable[[], datetime]) -> str:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _blocked("managed_v5_recovery_clock_invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = (
    "CanonicalRecoveryProjection",
    "ManagedV5RecoveryError",
    "ManagedV5RecoveryReport",
    "ManagedV5RecoveryRunner",
    "Mem0RecoveryProjection",
    "RECOVERY_REPORT_SCHEMA",
    "RecoveryMem0Readback",
    "RecoveryMem0Terminal",
    "write_recovery_report",
)
