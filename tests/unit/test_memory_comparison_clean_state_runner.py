from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.memory_comparison_clean_state import (
    BackendCleanStateProof,
    clean_state_identity_sha256,
    mem0_delete_clean_state_proof,
    skipped_mem0_clean_state_proof,
)
from infinity_context_server.memory_comparison_clean_state_runner import (
    full_failures,
    reset_comparison_backends,
)

_KEY = b"r" * 32
_RUN = "run-1"
_RUN_HASH = clean_state_identity_sha256(_RUN)
_CORPUS = clean_state_identity_sha256("corpus")


@dataclass
class _ResetBackend:
    clean_state_backend_role: str = "mem0"
    skip: bool = True
    proof_run_id: str = _RUN
    reset_calls: int = 0

    def reset_for_clean_state(
        self, *, run_id: str, attestation_key: bytes
    ) -> BackendCleanStateProof:
        self.reset_calls += 1
        if self.skip:
            return skipped_mem0_clean_state_proof(
                run_id=self.proof_run_id,
                scope_identity="scope",
                corpus_identity_sha256=_CORPUS,
                expected_scope_count=1,
                attestation_key=attestation_key,
            )
        return mem0_delete_clean_state_proof(
            run_id=self.proof_run_id,
            scope_identity="scope",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            status_code=200,
            payload={"deleted": True, "verified_absent": True},
            attestation_key=attestation_key,
        )


def _reset(backend: _ResetBackend, *, full: bool = True, run_hash: str = _RUN_HASH):
    return reset_comparison_backends(
        (backend,),
        ("mem0",),
        run_id=_RUN,
        expected_run_id_sha256=run_hash,
        attestation_key=_KEY,
        error_reason=lambda exc: str(exc),
        lane=(object() if full else None, "full"),
    )


def test_full_scope_rejects_authenticated_but_unverified_skip() -> None:
    backend = _ResetBackend()

    failures = _reset(backend)

    assert full_failures(failures) == (
        {
            "backend": "mem0",
            "stage": "reset",
            "reason": "clean_state_reset_proof_invalid",
        },
    )
    assert backend.reset_calls == 1


def test_diagnostic_scope_allows_authenticated_skip() -> None:
    backend = _ResetBackend()

    assert _reset(backend, full=False) == {}
    assert backend.reset_calls == 1


def test_pre_execution_gate_accepts_verified_exact_role_and_run() -> None:
    backend = _ResetBackend(skip=False)

    assert _reset(backend) == {}


def test_pre_execution_gate_rejects_wrong_assigned_backend_role_before_reset() -> None:
    backend = _ResetBackend(clean_state_backend_role="infinity-context")

    failures = _reset(backend)

    assert failures == {"mem0": "clean_state_backend_role_mismatch"}
    assert backend.reset_calls == 0


def test_pre_execution_gate_rejects_wrong_expected_run_before_reset() -> None:
    backend = _ResetBackend(skip=False)

    failures = _reset(
        backend,
        run_hash=clean_state_identity_sha256("other-run"),
    )

    assert failures == {"mem0": "clean_state_expected_run_mismatch"}
    assert backend.reset_calls == 0


def test_pre_execution_gate_rejects_proof_for_other_run() -> None:
    backend = _ResetBackend(skip=False, proof_run_id="other-run")

    assert _reset(backend) == {"mem0": "clean_state_reset_proof_invalid"}
