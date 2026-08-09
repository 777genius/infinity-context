"""One-shot transfer of exact managed benchmark recovery authority."""

from __future__ import annotations

from typing import Any

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRecoveryAuthorityTransfer,
    ManagedBenchmarkRunRegistration,
    digest,
    fail,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    space_slug as validated_space_slug,
)

_TRANSFER_PHASES = frozenset(
    {
        "registered",
        "registration_outcome_unknown",
        "sealed",
        "seal_outcome_unknown",
        "cleanup_outcome_unknown",
        "pending",
        "finalize_outcome_unknown",
        "recovery_required",
        "recovery_outcome_unknown",
    }
)


def relinquish_recovery_authority(
    adapter: Any,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    infinity_target_identity_sha256: str,
    space_slug: str,
    cleanup_plan_sha256: str,
) -> ManagedBenchmarkRecoveryAuthorityTransfer:
    identity = (
        digest(run_id_sha256, "managed_benchmark_registry_recovery_transfer_invalid"),
        digest(
            binding_commitment_sha256,
            "managed_benchmark_registry_recovery_transfer_invalid",
        ),
        digest(
            infinity_target_identity_sha256,
            "managed_benchmark_registry_recovery_transfer_invalid",
        ),
        validated_space_slug(
            space_slug,
            "managed_benchmark_registry_recovery_transfer_invalid",
        ),
        digest(cleanup_plan_sha256, "managed_benchmark_registry_recovery_transfer_invalid"),
    )
    with adapter._lock:
        registration = adapter._registration
        registration_attempt = adapter._registration_attempt
        recovery_attempt = adapter._recovery_attempt
        prior_phase = adapter._phase
        matches_registration_attempt = (
            prior_phase == "registration_outcome_unknown"
            and registration is None
            and registration_attempt is not None
            and identity
            == (
                registration_attempt.run_id_sha256,
                registration_attempt.binding_commitment_sha256,
                adapter._config.target_identity_sha256,
                registration_attempt.space_slug,
                registration_attempt.cleanup_plan_sha256,
            )
        )
        matches_recovery_attempt = (
            prior_phase == "recovery_outcome_unknown"
            and registration is None
            and recovery_attempt is not None
            and identity
            == (
                recovery_attempt.run_id_sha256,
                recovery_attempt.binding_commitment_sha256,
                adapter._config.target_identity_sha256,
                recovery_attempt.space_slug,
                recovery_attempt.cleanup_plan_sha256,
            )
        )
        if prior_phase not in _TRANSFER_PHASES or not (
            matches_registration_attempt
            or matches_recovery_attempt
            or (
                type(registration) is ManagedBenchmarkRunRegistration
                and identity
                == (
                    registration.run_id_sha256,
                    registration.binding_commitment_sha256,
                    registration.infinity_target_identity_sha256,
                    registration.space_slug,
                    registration.cleanup_plan_sha256,
                )
            )
        ):
            fail("managed_benchmark_registry_recovery_transfer_invalid")
        adapter._phase = "recovery_authority_transferred"
    adapter._close_client(suppress_failure=True)
    with adapter._lock:
        transport_close_confirmed = adapter._close_warning_code is None
    return ManagedBenchmarkRecoveryAuthorityTransfer(
        schema_version="memory-comparison-benchmark-recovery-authority-transfer.v2",
        run_id_sha256=identity[0],
        binding_commitment_sha256=identity[1],
        infinity_target_identity_sha256=identity[2],
        space_slug=identity[3],
        cleanup_plan_sha256=identity[4],
        prior_phase=prior_phase,
        transport_close_confirmed=transport_close_confirmed,
        transport_close_warning=(
            None
            if transport_close_confirmed
            else "managed_benchmark_registry_transport_close_unconfirmed"
        ),
    )


__all__ = ("relinquish_recovery_authority",)
