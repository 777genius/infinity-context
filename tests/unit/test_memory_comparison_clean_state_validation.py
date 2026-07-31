from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.memory_comparison_clean_state import (
    BackendCleanStateProof,
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    public_clean_state_validation,
)
from infinity_context_server.memory_comparison_clean_state_runner import (
    validate_backend_clean_state,
)

_KEY = b"v" * 32
_RUN = "run-with-private-identity"
_RUN_HASH = clean_state_identity_sha256(_RUN)
_INFINITY_CORPUS = clean_state_identity_sha256("namespace-corpus")
_MEM0_CORPUS = clean_state_identity_sha256("actual-corpus")


@dataclass(frozen=True)
class _ProofBackend:
    clean_state_backend_role: str
    values: tuple[BackendCleanStateProof, ...]

    def clean_state_proofs(self) -> tuple[BackendCleanStateProof, ...]:
        return self.values

    def reset_for_clean_state(
        self, *, run_id: str, attestation_key: bytes
    ) -> BackendCleanStateProof:
        raise NotImplementedError


def _backends(scope: str = "private-mem0-scope") -> tuple[_ProofBackend, _ProofBackend]:
    infinity = _ProofBackend(
        "infinity-context",
        (
            fresh_namespace_clean_state_proof(
                backend="infinity-context",
                run_id=_RUN,
                expected_slug="fresh-space",
                corpus_identity_sha256=_INFINITY_CORPUS,
                expected_scope_count=1,
                status_code=201,
                payload={"data": {"slug": "fresh-space"}},
                attestation_key=_KEY,
            ),
        ),
    )
    mem0 = _ProofBackend(
        "mem0",
        (
            mem0_delete_clean_state_proof(
                run_id=_RUN,
                scope_identity=scope,
                corpus_identity_sha256=_MEM0_CORPUS,
                expected_scope_count=1,
                status_code=200,
                payload={"deleted": True, "verified_absent": True},
                attestation_key=_KEY,
            ),
        ),
    )
    return infinity, mem0


def _expectations() -> dict[str, dict[str, str]]:
    return {
        "infinity-context": {_INFINITY_CORPUS: clean_state_identity_sha256("fresh-space")},
        "mem0": {_MEM0_CORPUS: clean_state_identity_sha256("private-mem0-scope")},
    }


def test_runner_validates_exact_canonical_scope_mapping() -> None:
    validation = validate_backend_clean_state(
        _backends(),
        ("infinity-context", "mem0"),
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )
    public = public_clean_state_validation(validation)

    assert public["eligible"] is True
    assert public["issues"] == ()
    assert _RUN not in str(public)
    assert "private-mem0-scope" not in str(public)


def test_runner_rejects_actual_ingest_scope_that_differs_from_expectation() -> None:
    validation = validate_backend_clean_state(
        _backends("different-actual-scope"),
        ("infinity-context", "mem0"),
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )

    assert validation.eligible is False
    assert "mem0:clean_state_scope_set_mismatch" in validation.payload["issues"]
