"""Journal-bound canonical registration for managed-v5 live activation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRecoveryAuthorityTransfer,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
)


def register_and_observe_managed_v5(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    *,
    cleanup_plan: ManagedBenchmarkCleanupPlan,
    recovery_authority: ManagedV5LiveRecoveryAuthority,
    recovery_journal: ManagedV5LiveRecoveryJournalStore,
    registry_config: ManagedBenchmarkRegistryHttpConfig,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    space_slug: str,
    clock: Callable[[], datetime],
) -> ManagedBenchmarkRunRegistration:
    registration = registry.register(
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        space_slug=space_slug,
        cleanup_plan=cleanup_plan,
    )
    fresh_registry = ManagedBenchmarkRegistryHttpAdapter(registry_config)
    try:
        observed = fresh_registry.recover_lifecycle(
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
            cleanup_plan_sha256=cleanup_plan.sha256,
        )
        _relinquish(
            fresh_registry,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            target_identity_sha256=registry_config.target_identity_sha256,
            space_slug=space_slug,
            cleanup_plan_sha256=cleanup_plan.sha256,
        )
    except BaseException as primary:
        try:
            if fresh_registry.cleanup_required:
                _relinquish(
                    fresh_registry,
                    run_id_sha256=run_id_sha256,
                    binding_commitment_sha256=binding_commitment_sha256,
                    target_identity_sha256=registry_config.target_identity_sha256,
                    space_slug=space_slug,
                    cleanup_plan_sha256=cleanup_plan.sha256,
                )
            else:
                fresh_registry.close()
        except BaseException as ownership:
            error = RuntimeError("managed_v5_live_registration_observation_ownership_failed")
            error.add_note(f"primary={type(primary).__name__}")
            raise error from ownership
        raise
    if (
        observed.run_id_sha256 != run_id_sha256
        or observed.binding_commitment_sha256 != binding_commitment_sha256
        or observed.infinity_target_identity_sha256 != registry_config.target_identity_sha256
        or observed.space_slug != space_slug
        or observed.state != "active"
        or observed.projection_cleanup_state != "unsealed"
        or observed.cleanup_plan_state != "sealed"
        or observed.cleanup_plan_sha256 != cleanup_plan.sha256
        or observed.space_id != registration.space_id
    ):
        raise RuntimeError("managed_v5_live_registration_observation_mismatch")
    recovery_journal.append(
        expected_authority=recovery_authority,
        kind="registration_observed",
        recorded_at=managed_v5_recovery_recorded_at(clock()),
        details={
            "cleanup_plan_sha256": cleanup_plan.sha256,
            "cleanup_plan_state": "sealed",
            "space_id": observed.space_id,
            "registration_commitment_sha256": canonical_sha256(
                {
                    "run_id_sha256": observed.run_id_sha256,
                    "binding_commitment_sha256": observed.binding_commitment_sha256,
                    "space_id": observed.space_id,
                    "cleanup_plan_sha256": observed.cleanup_plan_sha256,
                }
            ),
        },
    )
    return registration


def managed_v5_recovery_recorded_at(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("managed_v5_live_registration_clock_invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _relinquish(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    target_identity_sha256: str,
    space_slug: str,
    cleanup_plan_sha256: str,
) -> None:
    receipt = registry.relinquish_recovery_authority(
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        infinity_target_identity_sha256=target_identity_sha256,
        space_slug=space_slug,
        cleanup_plan_sha256=cleanup_plan_sha256,
    )
    if type(receipt) is not ManagedBenchmarkRecoveryAuthorityTransfer or (
        receipt.run_id_sha256,
        receipt.binding_commitment_sha256,
        receipt.infinity_target_identity_sha256,
        receipt.space_slug,
        receipt.cleanup_plan_sha256,
    ) != (
        run_id_sha256,
        binding_commitment_sha256,
        target_identity_sha256,
        space_slug,
        cleanup_plan_sha256,
    ):
        raise RuntimeError("managed_v5_live_registration_observation_ownership_failed")


__all__ = ("managed_v5_recovery_recorded_at", "register_and_observe_managed_v5")
