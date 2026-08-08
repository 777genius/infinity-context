"""Secret-free durable report projection for managed-v5 registry recovery."""

from __future__ import annotations

from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    ManagedV5ProductionRecoveryRequiredError,
)


def managed_v5_registry_recovery_payload(
    error: ManagedV5ProductionRecoveryRequiredError,
) -> dict[str, object]:
    """Project only canonical public state; the live adapter remains private."""

    if type(error) is not ManagedV5ProductionRecoveryRequiredError:
        raise TypeError("managed v5 recovery error required")
    envelope = error.envelope
    registration = envelope.registration
    receipt = envelope.cleanup_receipt
    return {
        "schema_version": envelope.schema_version,
        "cleanup_required": True,
        "canonical_state": ("unknown_may_exist" if registration is None else registration.state),
        "canonical_state_retained": registration is not None,
        "cleanup_stage": envelope.stage,
        "primary_reason_code": envelope.primary_reason_code,
        "run_id_sha256": envelope.run_id_sha256,
        "binding_commitment_sha256": envelope.binding_commitment_sha256,
        "infinity_target_identity_sha256": envelope.infinity_target_identity_sha256,
        "space_slug": envelope.space_slug,
        "registration": (
            None
            if registration is None
            else {
                "run_id_sha256": registration.run_id_sha256,
                "binding_commitment_sha256": registration.binding_commitment_sha256,
                "infinity_target_identity_sha256": (registration.infinity_target_identity_sha256),
                "space_id": registration.space_id,
                "space_slug": registration.space_slug,
                "state": registration.state,
                "created": registration.created,
            }
        ),
        "cleanup_receipt_sha256": None if receipt is None else receipt.receipt_sha256,
    }


__all__ = ("managed_v5_registry_recovery_payload",)
