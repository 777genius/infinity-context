"""Canonical registry transitions used by managed-v5 recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, final

from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkRegistryHttpError,
    ManagedBenchmarkRunLifecycleSnapshot,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournal,
)


class ManagedV5RecoveryError(RuntimeError):
    __slots__ = ("code", "exit_code")

    def __init__(self, code: str, *, exit_code: int) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


class RecoveryRegistryPort(Protocol):
    def recover_lifecycle_or_missing(
        self, **kwargs: object
    ) -> ManagedBenchmarkRunLifecycleSnapshot | None: ...
    def recover_lifecycle(self, **kwargs: object) -> ManagedBenchmarkRunLifecycleSnapshot: ...
    def register(self, **kwargs: object) -> object: ...
    def seal_projection_manifest(self, **kwargs: object) -> object: ...
    def relinquish_recovery_authority(self, **kwargs: object) -> object: ...
    def close(self) -> None: ...
    def begin_cleanup(self) -> ManagedBenchmarkCleanupReceipt: ...
    def finalize_cleanup(self, **kwargs: object) -> ManagedBenchmarkCleanupCompletionReceipt: ...
    def finalize_unsealed_abort(self, **kwargs: object) -> object: ...


@final
class RecoveryRegistryCoordinator:
    __slots__ = ("_authority", "_cleanup_plan", "_factory")

    def __init__(
        self,
        *,
        authority: ManagedV5LiveRecoveryAuthority,
        cleanup_plan: ManagedBenchmarkCleanupPlan,
        factory: Callable[[], RecoveryRegistryPort],
    ) -> None:
        self._authority = authority
        self._cleanup_plan = cleanup_plan
        self._factory = factory

    def recover_initial(self, cleanup_plan_sha: str) -> ManagedBenchmarkRunLifecycleSnapshot:
        adapter = self._factory()
        try:
            observed = adapter.recover_lifecycle_or_missing(**self._identity(cleanup_plan_sha))
        except ManagedBenchmarkRegistryHttpError as error:
            self._release_unknown(adapter, cleanup_plan_sha)
            _registry_failure(error)
        if observed is not None:
            try:
                observed = require_snapshot(observed, self._authority, cleanup_plan_sha)
            except ManagedV5RecoveryError:
                self._release_unknown(adapter, cleanup_plan_sha)
                raise
            self._release(adapter, observed, cleanup_plan_sha)
            return observed
        self._close(adapter)
        replay = self._factory()
        try:
            replay.register(
                run_id_sha256=self._authority.run_id_sha256,
                binding_commitment_sha256=self._authority.binding_commitment_sha256,
                space_slug=self._authority.space_slug,
                cleanup_plan=self._cleanup_plan,
            )
        except ManagedBenchmarkRegistryHttpError as error:
            if not _ambiguous(error):
                self._close(replay)
                blocked("managed_v5_recovery_registry_rejected")
            self._relinquish(replay, cleanup_plan_sha)
            return self.fresh_get(cleanup_plan_sha)
        self._relinquish(replay, cleanup_plan_sha)
        return self.fresh_get(cleanup_plan_sha)

    def recover_existing_or_missing(
        self, cleanup_plan_sha: str
    ) -> ManagedBenchmarkRunLifecycleSnapshot | None:
        """Probe canonical state without creating a missing registration."""

        adapter = self._factory()
        try:
            observed = adapter.recover_lifecycle_or_missing(**self._identity(cleanup_plan_sha))
        except ManagedBenchmarkRegistryHttpError as error:
            self._release_unknown(adapter, cleanup_plan_sha)
            _registry_failure(error)
        if observed is None:
            self._close(adapter)
            return None
        try:
            observed = require_snapshot(observed, self._authority, cleanup_plan_sha)
        except ManagedV5RecoveryError:
            self._release_unknown(adapter, cleanup_plan_sha)
            raise
        self._release(adapter, observed, cleanup_plan_sha)
        return observed

    def recover_projection_seal(
        self,
        journal: ManagedV5LiveRecoveryJournal,
        observed: ManagedBenchmarkRunLifecycleSnapshot,
        cleanup_plan_sha: str,
    ) -> ManagedBenchmarkRunLifecycleSnapshot:
        manifest = journal.projection_manifest
        manifest_sha = journal.projection_manifest_sha256
        persisted = next(
            (event for event in journal.events if event.kind == "projection_manifest_persisted"),
            None,
        )
        if manifest is None:
            if manifest_sha is not None or persisted is not None:
                blocked("managed_v5_recovery_projection_manifest_invalid")
            if observed.projection_cleanup_state == "sealed":
                blocked("managed_v5_recovery_projection_manifest_missing")
            return observed
        if (
            not _sha(manifest_sha)
            or persisted is None
            or persisted.details != {"projection_manifest_sha256": manifest_sha}
            or canonical_sha256(manifest) != manifest_sha
        ):
            blocked("managed_v5_recovery_projection_manifest_invalid")
        if observed.projection_cleanup_state == "sealed":
            if observed.projection_manifest_sha256 != manifest_sha:
                blocked("managed_v5_recovery_projection_manifest_mismatch")
            return observed
        if observed.projection_cleanup_state != "unsealed":
            blocked("managed_v5_recovery_projection_state_invalid")
        adapter = self._factory()
        recovered = False
        try:
            adapter.recover_lifecycle(**self._identity(cleanup_plan_sha))
            recovered = True
            adapter.seal_projection_manifest(
                projection_manifest=manifest,
                projection_manifest_sha256=manifest_sha,
            )
        except ManagedBenchmarkRegistryHttpError as error:
            if not _ambiguous(error):
                self._release_failed(adapter, recovered, cleanup_plan_sha)
                blocked("managed_v5_recovery_registry_rejected")
            if not recovered:
                self._release_unknown(adapter, cleanup_plan_sha)
                retry("managed_v5_recovery_registry_get_unknown")
        self._relinquish(adapter, cleanup_plan_sha)
        fresh = self.fresh_get(cleanup_plan_sha)
        if (
            fresh.state != "active"
            or fresh.projection_cleanup_state != "sealed"
            or fresh.projection_manifest_sha256 != manifest_sha
        ):
            blocked("managed_v5_recovery_projection_seal_unknown")
        return fresh

    def begin_cleanup(self, cleanup_plan_sha: str) -> ManagedBenchmarkRunLifecycleSnapshot:
        adapter = self._factory()
        recovered = False
        try:
            adapter.recover_lifecycle(**self._identity(cleanup_plan_sha))
            recovered = True
            receipt = adapter.begin_cleanup()
        except ManagedBenchmarkRegistryHttpError as error:
            if not _ambiguous(error):
                self._release_failed(adapter, recovered, cleanup_plan_sha)
                blocked("managed_v5_recovery_registry_rejected")
            if not recovered:
                self._release_unknown(adapter, cleanup_plan_sha)
                retry("managed_v5_recovery_registry_get_unknown")
            self._relinquish(adapter, cleanup_plan_sha)
            return self.fresh_get(cleanup_plan_sha)
        if type(receipt) is not ManagedBenchmarkCleanupReceipt:
            self._relinquish(adapter, cleanup_plan_sha)
            blocked("managed_v5_recovery_cleanup_receipt_invalid")
        self._relinquish(adapter, cleanup_plan_sha)
        observed = self.fresh_get(cleanup_plan_sha)
        if require_cleanup_receipt(observed).receipt_sha256 != receipt.receipt_sha256:
            blocked("managed_v5_recovery_cleanup_receipt_mismatch")
        return observed

    def finalize(
        self, *, cleanup_plan_sha: str, cleanup_receipt_sha: str
    ) -> ManagedBenchmarkRunLifecycleSnapshot:
        observed = self.fresh_get(cleanup_plan_sha)
        if observed.state in {"cleanup_complete", "cleanup_aborted"}:
            return observed
        if observed.state != "cleanup_pending":
            retry("managed_v5_recovery_canonical_terminal_unknown")
        if observed.projection_cleanup_state not in {"pending", "blocked"}:
            blocked("managed_v5_recovery_cleanup_state_invalid")
        adapter = self._factory()
        recovered = False
        try:
            adapter.recover_lifecycle(**self._identity(cleanup_plan_sha))
            recovered = True
            if observed.projection_cleanup_state == "pending":
                adapter.finalize_cleanup(
                    cleanup_initiation_receipt_sha256=cleanup_receipt_sha,
                )
            elif observed.projection_cleanup_state == "blocked":
                adapter.finalize_unsealed_abort(
                    cleanup_initiation_receipt_sha256=cleanup_receipt_sha,
                )
        except ManagedBenchmarkRegistryHttpError as error:
            if not _ambiguous(error):
                self._release_failed(adapter, recovered, cleanup_plan_sha)
                blocked("managed_v5_recovery_registry_rejected")
            if not recovered:
                self._release_unknown(adapter, cleanup_plan_sha)
                retry("managed_v5_recovery_registry_get_unknown")
            self._relinquish(adapter, cleanup_plan_sha)
            return self.fresh_get(cleanup_plan_sha)
        self._relinquish(adapter, cleanup_plan_sha)
        return self.fresh_get(cleanup_plan_sha)

    def fresh_get(self, cleanup_plan_sha: str) -> ManagedBenchmarkRunLifecycleSnapshot:
        adapter = self._factory()
        try:
            result = adapter.recover_lifecycle(**self._identity(cleanup_plan_sha))
        except ManagedBenchmarkRegistryHttpError as error:
            self._release_unknown(adapter, cleanup_plan_sha)
            _registry_failure(error)
        try:
            result = require_snapshot(result, self._authority, cleanup_plan_sha)
        except ManagedV5RecoveryError:
            self._release_unknown(adapter, cleanup_plan_sha)
            raise
        self._release(adapter, result, cleanup_plan_sha)
        return result

    def _identity(self, cleanup_plan_sha: str) -> dict[str, str]:
        return {
            "run_id_sha256": self._authority.run_id_sha256,
            "binding_commitment_sha256": self._authority.binding_commitment_sha256,
            "space_slug": self._authority.space_slug,
            "cleanup_plan_sha256": cleanup_plan_sha,
        }

    def _release(
        self,
        adapter: RecoveryRegistryPort,
        snapshot: ManagedBenchmarkRunLifecycleSnapshot,
        cleanup_plan_sha: str,
    ) -> None:
        if snapshot.state in {"active", "cleanup_pending"}:
            self._relinquish(adapter, cleanup_plan_sha)
        else:
            self._close(adapter)

    def _release_failed(
        self, adapter: RecoveryRegistryPort, recovered: bool, cleanup_plan_sha: str
    ) -> None:
        if recovered:
            self._relinquish(adapter, cleanup_plan_sha)
        else:
            self._close(adapter)

    def _release_unknown(self, adapter: RecoveryRegistryPort, cleanup_plan_sha: str) -> None:
        try:
            self._relinquish(adapter, cleanup_plan_sha)
            return
        except ManagedV5RecoveryError:
            pass
        try:
            self._close(adapter)
        except ManagedV5RecoveryError:
            blocked("managed_v5_recovery_registry_ownership_failed")

    def _relinquish(self, adapter: RecoveryRegistryPort, cleanup_plan_sha: str) -> None:
        try:
            transfer = adapter.relinquish_recovery_authority(
                **self._identity(cleanup_plan_sha),
                infinity_target_identity_sha256=self._authority.infinity_target_identity_sha256,
            )
        except ManagedBenchmarkRegistryHttpError:
            blocked("managed_v5_recovery_registry_transfer_failed")
        expected = {
            **self._identity(cleanup_plan_sha),
            "infinity_target_identity_sha256": self._authority.infinity_target_identity_sha256,
        }
        if any(getattr(transfer, key, None) != value for key, value in expected.items()):
            blocked("managed_v5_recovery_registry_transfer_mismatch")

    @staticmethod
    def _close(adapter: RecoveryRegistryPort) -> None:
        try:
            adapter.close()
        except ManagedBenchmarkRegistryHttpError:
            blocked("managed_v5_recovery_registry_close_failed")


def require_snapshot(
    value: object, authority: ManagedV5LiveRecoveryAuthority, cleanup_plan_sha: str
) -> ManagedBenchmarkRunLifecycleSnapshot:
    if type(value) is not ManagedBenchmarkRunLifecycleSnapshot:
        blocked("managed_v5_recovery_registry_snapshot_invalid")
    value.__post_init__()
    if (
        value.run_id_sha256 != authority.run_id_sha256
        or value.binding_commitment_sha256 != authority.binding_commitment_sha256
        or value.infinity_target_identity_sha256 != authority.infinity_target_identity_sha256
        or value.space_slug != authority.space_slug
        or value.cleanup_plan_sha256 != cleanup_plan_sha
        or value.cleanup_plan_state != "sealed"
    ):
        blocked("managed_v5_recovery_registry_snapshot_mismatch")
    return value


def registration_details(value: ManagedBenchmarkRunLifecycleSnapshot) -> dict[str, object]:
    return {
        "cleanup_plan_sha256": value.cleanup_plan_sha256,
        "cleanup_plan_state": value.cleanup_plan_state,
        "space_id": value.space_id,
        "registration_commitment_sha256": canonical_sha256(
            {
                "run_id_sha256": value.run_id_sha256,
                "binding_commitment_sha256": value.binding_commitment_sha256,
                "space_id": value.space_id,
                "cleanup_plan_sha256": value.cleanup_plan_sha256,
            }
        ),
    }


def require_cleanup_receipt(value: ManagedBenchmarkRunLifecycleSnapshot):
    if value.cleanup_receipt is None:
        retry("managed_v5_recovery_cleanup_outcome_unknown")
    return value.cleanup_receipt


def _ambiguous(error: ManagedBenchmarkRegistryHttpError) -> bool:
    return error.code in {
        "managed_benchmark_registry_request_failed",
        "managed_benchmark_registry_response_retryable",
    }


def _registry_failure(error: ManagedBenchmarkRegistryHttpError) -> None:
    if _ambiguous(error):
        retry("managed_v5_recovery_registry_get_unknown")
    blocked("managed_v5_recovery_registry_rejected")


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def retry(code: str) -> None:
    raise ManagedV5RecoveryError(code, exit_code=2)


def blocked(code: str) -> None:
    raise ManagedV5RecoveryError(code, exit_code=3)


__all__ = (
    "ManagedV5RecoveryError",
    "RecoveryRegistryCoordinator",
    "RecoveryRegistryPort",
    "blocked",
    "registration_details",
    "require_cleanup_receipt",
    "retry",
)
