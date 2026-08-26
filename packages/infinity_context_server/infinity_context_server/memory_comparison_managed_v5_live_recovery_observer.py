"""Secret-free durable observations for the managed-v5 production lifecycle."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import final

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkRecoveryAuthorityTransfer,
    ManagedBenchmarkRunLifecycleSnapshot,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    ManagedProjectionManifest,
)
from infinity_context_server.memory_comparison_managed_v5_mem0_terminal_observation import (
    ManagedMem0TerminalObservation,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
)


class ManagedV5LiveRecoveryObservationError(RuntimeError):
    """Stable failure raised before the next irreversible lifecycle action."""


@final
class ManagedV5LiveRecoveryObserver:
    """Append exact lifecycle facts and reconcile canonical completion freshly."""

    __slots__ = (
        "_authority",
        "_clock",
        "_journal",
        "_lock",
        "_registration",
        "_registry_factory",
    )

    def __init__(
        self,
        *,
        journal: ManagedV5LiveRecoveryJournalStore,
        authority: ManagedV5LiveRecoveryAuthority,
        registration: ManagedBenchmarkRunRegistration,
        registry_factory: Callable[[], ManagedBenchmarkRegistryHttpAdapter],
        clock: Callable[[], datetime],
    ) -> None:
        if (
            type(journal) is not ManagedV5LiveRecoveryJournalStore
            or type(authority) is not ManagedV5LiveRecoveryAuthority
            or type(registration) is not ManagedBenchmarkRunRegistration
            or not callable(registry_factory)
            or not callable(clock)
        ):
            _fail("managed_v5_live_recovery_observer_invalid")
        self._journal = journal
        self._authority = authority
        self._registration = registration
        self._registry_factory = registry_factory
        self._clock = clock
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return "ManagedV5LiveRecoveryObserver(<redacted>)"

    def projection_manifest_persisted(self, manifest: ManagedProjectionManifest) -> None:
        if type(manifest) is not ManagedProjectionManifest:
            _fail("managed_v5_live_projection_manifest_observation_invalid")
        self._append(
            kind="projection_manifest_persisted",
            details={"projection_manifest_sha256": manifest.projection_manifest_sha256},
            projection_manifest=manifest.projection_manifest,
        )

    def registry_seal_observed(self, manifest_sha256: str) -> None:
        snapshot = self._fresh_lifecycle()
        if (
            snapshot.state != "active"
            or snapshot.projection_cleanup_state != "sealed"
            or snapshot.projection_manifest_sha256 != manifest_sha256
        ):
            _fail("managed_v5_live_registry_seal_observation_invalid")
        self._append(
            kind="registry_seal_observed",
            details={
                "cleanup_plan_sha256": self._registration.cleanup_plan_sha256,
                "projection_manifest_sha256": manifest_sha256,
                "projection_cleanup_state": "sealed",
            },
        )

    def cleanup_observed(self, receipt: ManagedBenchmarkCleanupReceipt) -> None:
        if (
            type(receipt) is not ManagedBenchmarkCleanupReceipt
            or receipt.run_id_sha256 != self._registration.run_id_sha256
            or receipt.space_id != self._registration.space_id
            or receipt.space_slug != self._registration.space_slug
        ):
            _fail("managed_v5_live_cleanup_observation_invalid")
        self._append(
            kind="cleanup_observed",
            details={
                "cleanup_plan_sha256": self._registration.cleanup_plan_sha256,
                "cleanup_receipt_sha256": receipt.receipt_sha256,
                "projection_cleanup_state": receipt.projection_cleanup,
            },
        )

    def mem0_terminal_observed(self, value: ManagedMem0TerminalObservation) -> None:
        if type(value) is not ManagedMem0TerminalObservation:
            _fail("managed_v5_live_mem0_terminal_observation_invalid")
        self._append(
            kind="mem0_terminal_observed",
            details={
                "terminal_state": value.terminal_state,
                "terminal_commitment_sha256": value.terminal_commitment_sha256,
                "cleanup_readback_witness_sha256": value.cleanup_readback_witness_sha256,
            },
        )

    def canonical_terminal_observed(
        self, completion: ManagedBenchmarkCleanupCompletionReceipt
    ) -> None:
        if type(completion) is not ManagedBenchmarkCleanupCompletionReceipt:
            _fail("managed_v5_live_canonical_terminal_observation_invalid")
        snapshot = self._fresh_lifecycle()
        persisted = snapshot.completion_receipt
        cleanup = snapshot.cleanup_receipt
        if (
            snapshot.state != "cleanup_complete"
            or snapshot.projection_cleanup_state != "complete"
            or persisted is None
            or persisted.receipt_sha256 != completion.receipt_sha256
            or cleanup is None
            or cleanup.receipt_sha256 != completion.cleanup_initiation_receipt_sha256
            or persisted.cleanup_initiation_receipt_sha256
            != completion.cleanup_initiation_receipt_sha256
            or persisted.projection_manifest_sha256 != completion.projection_manifest_sha256
            or persisted.projection_absence_proof_sha256
            != completion.projection_absence_proof_sha256
        ):
            _fail("managed_v5_live_canonical_terminal_observation_invalid")
        self._append(
            kind="canonical_terminal_observed",
            details={
                "state": "cleanup_complete",
                "projection_cleanup_state": "complete",
                "completion_receipt_sha256": completion.receipt_sha256,
                "cleanup_plan_sha256": self._registration.cleanup_plan_sha256,
            },
        )

    def _fresh_lifecycle(self) -> ManagedBenchmarkRunLifecycleSnapshot:
        try:
            registry = self._registry_factory()
        except Exception:
            _fail("managed_v5_live_registry_observation_failed")
        if type(registry) is not ManagedBenchmarkRegistryHttpAdapter:
            _fail("managed_v5_live_registry_observation_failed")
        try:
            snapshot = registry.recover_lifecycle(
                run_id_sha256=self._registration.run_id_sha256,
                binding_commitment_sha256=self._registration.binding_commitment_sha256,
                space_slug=self._registration.space_slug,
                cleanup_plan_sha256=self._registration.cleanup_plan_sha256,
            )
            self._validate_snapshot_identity(snapshot)
            if snapshot.state in {"cleanup_complete", "cleanup_aborted"}:
                registry.close()
            else:
                self._relinquish(registry)
            return snapshot
        except BaseException as primary:
            try:
                if registry.cleanup_required:
                    self._relinquish(registry)
                else:
                    registry.close()
            except BaseException as ownership:
                error = ManagedV5LiveRecoveryObservationError(
                    "managed_v5_live_registry_observation_ownership_failed"
                )
                error.add_note(f"primary={type(primary).__name__}")
                raise error from ownership
            raise

    def _relinquish(self, registry: ManagedBenchmarkRegistryHttpAdapter) -> None:
        receipt = registry.relinquish_recovery_authority(
            run_id_sha256=self._registration.run_id_sha256,
            binding_commitment_sha256=self._registration.binding_commitment_sha256,
            infinity_target_identity_sha256=(self._registration.infinity_target_identity_sha256),
            space_slug=self._registration.space_slug,
            cleanup_plan_sha256=self._registration.cleanup_plan_sha256,
        )
        if (
            type(receipt) is not ManagedBenchmarkRecoveryAuthorityTransfer
            or receipt.run_id_sha256 != self._registration.run_id_sha256
            or receipt.binding_commitment_sha256 != self._registration.binding_commitment_sha256
            or receipt.infinity_target_identity_sha256
            != self._registration.infinity_target_identity_sha256
            or receipt.space_slug != self._registration.space_slug
            or receipt.cleanup_plan_sha256 != self._registration.cleanup_plan_sha256
        ):
            _fail("managed_v5_live_registry_observation_ownership_failed")

    def _validate_snapshot_identity(self, snapshot: object) -> None:
        if (
            type(snapshot) is not ManagedBenchmarkRunLifecycleSnapshot
            or snapshot.run_id_sha256 != self._registration.run_id_sha256
            or snapshot.binding_commitment_sha256 != self._registration.binding_commitment_sha256
            or snapshot.infinity_target_identity_sha256
            != self._registration.infinity_target_identity_sha256
            or snapshot.space_id != self._registration.space_id
            or snapshot.space_slug != self._registration.space_slug
            or snapshot.cleanup_plan_sha256 != self._registration.cleanup_plan_sha256
            or snapshot.cleanup_plan_state != "sealed"
        ):
            _fail("managed_v5_live_registry_observation_identity_invalid")

    def _append(
        self,
        *,
        kind: str,
        details: dict[str, object],
        projection_manifest: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            try:
                self._journal.append(
                    expected_authority=self._authority,
                    kind=kind,
                    recorded_at=_rfc3339(self._clock()),
                    details=details,
                    projection_manifest=projection_manifest,
                )
            except BaseException:
                raise


def _rfc3339(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        _fail("managed_v5_live_recovery_observer_clock_invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _fail(code: str) -> None:
    raise ManagedV5LiveRecoveryObservationError(code)


__all__ = (
    "ManagedMem0TerminalObservation",
    "ManagedV5LiveRecoveryObservationError",
    "ManagedV5LiveRecoveryObserver",
)
