"""Private registry ownership retained when live composition cannot continue."""

from __future__ import annotations

from typing import final

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)

_SCHEMA = "managed-v5-registry-recovery.v1"
_STAGES = frozenset(
    {
        "registration_outcome_unknown",
        "begin_cleanup",
        "awaiting_projection_cleanup",
        "finalize_unsealed_abort",
    }
)


class ManagedV5LivePrivateDependencyError(RuntimeError):
    """Stable composition error, optionally retaining registry recovery authority."""

    __slots__ = ("code", "recovery_envelope")

    def __init__(
        self,
        code: str,
        *,
        recovery_envelope: ManagedV5RegistryRecoveryEnvelope | None = None,
    ) -> None:
        if recovery_envelope is not None and type(recovery_envelope) is not (
            ManagedV5RegistryRecoveryEnvelope
        ):
            raise TypeError("managed v5 recovery envelope required")
        self.code = code
        self.recovery_envelope = recovery_envelope
        super().__init__(code)

    @property
    def recovery_registry(self) -> ManagedBenchmarkRegistryHttpAdapter | None:
        envelope = self.recovery_envelope
        return None if envelope is None else envelope.recovery_registry

    def __reduce__(self) -> object:
        raise TypeError("managed v5 private dependency error is nonserializable")


@final
class ManagedV5RegistryRecoveryEnvelope:
    """Exact public recovery facts plus one private live registry capability."""

    __slots__ = (
        "binding_commitment_sha256",
        "cleanup_receipt",
        "infinity_target_identity_sha256",
        "primary_reason_code",
        "recovery_registry",
        "registration",
        "run_id_sha256",
        "schema_version",
        "space_slug",
        "stage",
    )

    def __init__(
        self,
        *,
        stage: str,
        primary_reason_code: str,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        infinity_target_identity_sha256: str,
        space_slug: str,
        recovery_registry: ManagedBenchmarkRegistryHttpAdapter,
        registration: ManagedBenchmarkRunRegistration | None = None,
        cleanup_receipt: ManagedBenchmarkCleanupReceipt
        | ManagedBenchmarkPersistedCleanupReceipt
        | None = None,
    ) -> None:
        unknown = stage == "registration_outcome_unknown"
        if (
            stage not in _STAGES
            or not _reason(primary_reason_code)
            or any(
                not _sha(value)
                for value in (
                    run_id_sha256,
                    binding_commitment_sha256,
                    infinity_target_identity_sha256,
                )
            )
            or not _slug(space_slug)
            or type(recovery_registry) is not ManagedBenchmarkRegistryHttpAdapter
            or (unknown and (registration is not None or cleanup_receipt is not None))
            or (not unknown and type(registration) is not ManagedBenchmarkRunRegistration)
            or (
                cleanup_receipt is not None
                and type(cleanup_receipt)
                not in {ManagedBenchmarkCleanupReceipt, ManagedBenchmarkPersistedCleanupReceipt}
            )
        ):
            _fail()
        if not unknown and (
            registration.run_id_sha256 != run_id_sha256
            or registration.binding_commitment_sha256 != binding_commitment_sha256
            or registration.infinity_target_identity_sha256 != infinity_target_identity_sha256
            or registration.space_slug != space_slug
        ):
            _fail()
        self.schema_version = _SCHEMA
        self.stage = stage
        self.primary_reason_code = primary_reason_code
        self.run_id_sha256 = run_id_sha256
        self.binding_commitment_sha256 = binding_commitment_sha256
        self.infinity_target_identity_sha256 = infinity_target_identity_sha256
        self.space_slug = space_slug
        self.registration = registration
        self.cleanup_receipt = cleanup_receipt
        self.recovery_registry = recovery_registry

    def __repr__(self) -> str:
        return f"ManagedV5RegistryRecoveryEnvelope(stage={self.stage!r}, <sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("managed v5 registry recovery envelope is nonserializable")

    def __copy__(self) -> object:
        raise TypeError("managed v5 registry recovery envelope is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed v5 registry recovery envelope is noncopyable")


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _slug(value: object) -> bool:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")
    return type(value) is str and 1 <= len(value) <= 200 and set(value) <= allowed


def _reason(value: object) -> bool:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    return (
        type(value) is str
        and value.startswith("managed_")
        and len(value) <= 200
        and set(value) <= allowed
    )


def _fail() -> None:
    raise ManagedV5LivePrivateDependencyError(
        "managed_v5_live_private_dependencies_recovery_envelope_invalid"
    ) from None


__all__ = ("ManagedV5LivePrivateDependencyError", "ManagedV5RegistryRecoveryEnvelope")
