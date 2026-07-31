"""Runner-only clean-state capability collection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from infinity_context_server.memory_comparison_clean_state import (
    CleanStateBackendPort,
    ResetProofPort,
    VerifiedCleanStateValidation,
    clean_state_identity_sha256,
    reset_proof_is_valid,
    validate_typed_clean_state_proofs,
)


class _ResetFailures(dict[str, str]):
    def __init__(self, *, block_execution: bool) -> None:
        super().__init__()
        self.block_execution = block_execution

    @property
    def should_block(self) -> bool:
        return self.block_execution and bool(self)


def reset_comparison_backends(
    backends: Sequence[ResetProofPort],
    expected_backend_roles: Sequence[str],
    *,
    run_id: str,
    expected_run_id_sha256: str,
    attestation_key: bytes,
    error_reason: Callable[[Exception], str],
    lane: tuple[object | None, str],
) -> _ResetFailures:
    """Reset and authenticate every proof against its assigned role and run."""

    profile, scope = lane
    full = profile is not None and scope == "full"
    failures = _ResetFailures(block_execution=full)
    if clean_state_identity_sha256(run_id) != expected_run_id_sha256:
        for role in expected_backend_roles:
            failures[role] = "clean_state_expected_run_mismatch"
        return failures
    for backend, expected_role in zip(backends, expected_backend_roles, strict=True):
        if backend.clean_state_backend_role != expected_role:
            failures[expected_role] = "clean_state_backend_role_mismatch"
            continue
        try:
            proof = backend.reset_for_clean_state(
                run_id=run_id,
                attestation_key=attestation_key,
            )
            if not reset_proof_is_valid(
                proof,
                expected_backend=expected_role,
                expected_run_id_sha256=expected_run_id_sha256,
                attestation_key=attestation_key,
                require_verified=full,
            ):
                failures[expected_role] = "clean_state_reset_proof_invalid"
        except Exception as exc:
            failures[expected_role] = error_reason(exc)
    return failures


def full_failures(failures: _ResetFailures) -> tuple[dict[str, object], ...]:
    if not failures.block_execution or not failures:
        return ()
    return tuple(
        {"backend": backend, "stage": "reset", "reason": reason}
        for backend, reason in sorted(failures.items())
    )


def validate_backend_clean_state(
    backends: Sequence[CleanStateBackendPort],
    expected_backend_roles: Sequence[str],
    *,
    expected_run_id_sha256: str,
    expected_scopes_by_backend: Mapping[str, Mapping[str, str]],
    attestation_key: bytes,
) -> VerifiedCleanStateValidation:
    """Validate exact canonical corpus-to-scope mappings after ingestion."""

    proofs_by_backend = {
        expected_role: backend.clean_state_proofs()
        for backend, expected_role in zip(backends, expected_backend_roles, strict=True)
    }
    return validate_typed_clean_state_proofs(
        proofs_by_backend,
        expected_run_id_sha256=expected_run_id_sha256,
        expected_scopes_by_backend=expected_scopes_by_backend,
        attestation_key=attestation_key,
    )


__all__ = [
    "full_failures",
    "reset_comparison_backends",
    "validate_backend_clean_state",
]
