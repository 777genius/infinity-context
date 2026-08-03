from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_clean_state import (
    BackendCleanStateProof,
    CleanStateProofError,
    clean_state_contract_is_publishable,
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    public_clean_state_validation,
    reset_proof_is_valid,
    validate_typed_clean_state_proofs,
    verify_clean_state_contract_for_publication,
)

_KEY = b"k" * 32
_OTHER_KEY = b"x" * 32
_RUN = "run-secret"
_RUN_HASH = clean_state_identity_sha256(_RUN)
_INFINITY_CORPUS = clean_state_identity_sha256("run-namespace")
_MEM0_CORPUS_A = clean_state_identity_sha256("corpus-a")
_MEM0_CORPUS_B = clean_state_identity_sha256("corpus-b")
_SHARED_SCOPE = "shared-scope"
_SHARED_SCOPE_HASH = clean_state_identity_sha256(_SHARED_SCOPE)


def _fresh() -> BackendCleanStateProof:
    return fresh_namespace_clean_state_proof(
        backend="infinity-context",
        run_id=_RUN,
        expected_slug="slug",
        corpus_identity_sha256=_INFINITY_CORPUS,
        expected_scope_count=1,
        status_code=201,
        payload={"data": {"slug": "slug"}},
        attestation_key=_KEY,
    )


def _mem0(
    corpus_hash: str = _MEM0_CORPUS_A,
    scope: str = "user-a",
) -> BackendCleanStateProof:
    return mem0_delete_clean_state_proof(
        run_id=_RUN,
        scope_identity=scope,
        corpus_identity_sha256=corpus_hash,
        expected_scope_count=2,
        status_code=200,
        payload={"deleted": True, "verified_absent": True},
        attestation_key=_KEY,
    )


def _expectations() -> dict[str, dict[str, str]]:
    return {
        "infinity-context": {
            _INFINITY_CORPUS: clean_state_identity_sha256("slug"),
        },
        "mem0": {
            _MEM0_CORPUS_A: clean_state_identity_sha256("user-a"),
            _MEM0_CORPUS_B: clean_state_identity_sha256("user-b"),
        },
    }


def _valid():
    return validate_typed_clean_state_proofs(
        {
            "infinity-context": (_fresh(),),
            "mem0": (
                _mem0(),
                _mem0(_MEM0_CORPUS_B, "user-b"),
            ),
        },
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )


def _shared_fresh(corpus_hash: str) -> BackendCleanStateProof:
    return fresh_namespace_clean_state_proof(
        backend="infinity-context",
        run_id=_RUN,
        expected_slug=_SHARED_SCOPE,
        corpus_identity_sha256=corpus_hash,
        expected_scope_count=2,
        status_code=201,
        payload={"data": {"slug": _SHARED_SCOPE}},
        attestation_key=_KEY,
    )


def _shared_scope_expectations() -> dict[str, dict[str, str]]:
    per_backend = {
        _MEM0_CORPUS_A: _SHARED_SCOPE_HASH,
        _MEM0_CORPUS_B: _SHARED_SCOPE_HASH,
    }
    return {
        "infinity-context": dict(per_backend),
        "mem0": dict(per_backend),
    }


def _shared_scope_proofs() -> dict[str, tuple[BackendCleanStateProof, ...]]:
    return {
        "infinity-context": (
            _shared_fresh(_MEM0_CORPUS_A),
            _shared_fresh(_MEM0_CORPUS_B),
        ),
        "mem0": (
            _mem0(_MEM0_CORPUS_A, _SHARED_SCOPE),
            _mem0(_MEM0_CORPUS_B, _SHARED_SCOPE),
        ),
    }


def test_builders_require_exact_ack_and_non_exported_key() -> None:
    proof = _fresh()

    assert proof.verified is True
    assert proof.run_id_sha256 == _RUN_HASH
    assert proof.attestation_hmac_sha256 != hashlib.sha256(_KEY).hexdigest()
    assert "key" not in repr(proof).lower()

    with pytest.raises(CleanStateProofError, match="namespace_ack_invalid"):
        fresh_namespace_clean_state_proof(
            backend="infinity-context",
            run_id=_RUN,
            expected_slug="slug",
            corpus_identity_sha256=_INFINITY_CORPUS,
            expected_scope_count=1,
            status_code=201,
            payload={"data": {"slug": "other"}},
            attestation_key=_KEY,
        )


@pytest.mark.parametrize(
    "proof",
    [
        replace(_fresh(), backend="mem0"),
        replace(_fresh(), run_id_sha256=clean_state_identity_sha256("other-run")),
        replace(_fresh(), scope_identity_sha256=clean_state_identity_sha256("other")),
        replace(_fresh(), expected_scope_count=2),
        replace(_fresh(), http_status_code=200),
        replace(_fresh(), attestation_hmac_sha256="0" * 64),
    ],
)
def test_hmac_binds_backend_run_scope_and_count(proof: BackendCleanStateProof) -> None:
    assert (
        reset_proof_is_valid(
            proof,
            expected_backend="infinity-context",
            expected_run_id_sha256=_RUN_HASH,
            attestation_key=_KEY,
            require_verified=True,
        )
        is False
    )


def test_recomputed_unkeyed_sha_and_fabricated_structural_proof_fail() -> None:
    proof = _fresh()
    recomputed_sha = hashlib.sha256(repr(proof).encode()).hexdigest()
    forged = replace(proof, attestation_hmac_sha256=recomputed_sha)

    assert not reset_proof_is_valid(
        forged,
        expected_backend="infinity-context",
        expected_run_id_sha256=_RUN_HASH,
        attestation_key=_KEY,
        require_verified=True,
    )
    fabricated = BackendCleanStateProof(
        backend="infinity-context",
        strategy="fresh_namespace",
        run_id_sha256=_RUN_HASH,
        corpus_identity_sha256=_INFINITY_CORPUS,
        scope_identity_sha256=clean_state_identity_sha256("slug"),
        expected_scope_count=1,
        http_status_code=201,
        verified=True,
        reason_code=None,
        deleted=None,
        verified_absent=None,
        attestation_hmac_sha256=hashlib.sha256(b"fabricated").hexdigest(),
    )
    invalid = validate_typed_clean_state_proofs(
        {"infinity-context": (fabricated,), "mem0": ()},
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )
    assert invalid.eligible is False


def test_copied_signature_cannot_attest_different_proof() -> None:
    original = _mem0()
    changed = replace(
        original,
        corpus_identity_sha256=_MEM0_CORPUS_B,
        scope_identity_sha256=clean_state_identity_sha256("user-b"),
    )

    assert not reset_proof_is_valid(
        changed,
        expected_backend="mem0",
        expected_run_id_sha256=_RUN_HASH,
        attestation_key=_KEY,
        require_verified=True,
    )


def test_same_scope_covers_two_distinct_corpora_for_both_backends() -> None:
    expectations = _shared_scope_expectations()
    validation = validate_typed_clean_state_proofs(
        _shared_scope_proofs(),
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=expectations,
        attestation_key=_KEY,
    )

    assert validation.eligible is True
    payload = public_clean_state_validation(validation)
    backends = payload["backends"]
    assert isinstance(backends, dict)
    for backend in ("infinity-context", "mem0"):
        report = backends[backend]
        assert isinstance(report, dict)
        assert report["expected_scope_count"] == 2
        assert report["observed_scope_count"] == 2
        assert report["verified"] is True
    assert clean_state_contract_is_publishable(
        payload,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=expectations,
        attestation_key=_KEY,
    )


def test_conflicting_scope_for_same_corpus_fails_closed() -> None:
    proofs = _shared_scope_proofs()
    proofs["mem0"] = (
        _mem0(_MEM0_CORPUS_A, _SHARED_SCOPE),
        _mem0(_MEM0_CORPUS_A, "conflicting-scope"),
    )

    validation = validate_typed_clean_state_proofs(
        proofs,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_shared_scope_expectations(),
        attestation_key=_KEY,
    )

    assert validation.eligible is False
    assert "mem0:clean_state_corpus_duplicate" in validation.payload["issues"]
    assert "mem0:clean_state_scope_set_mismatch" in validation.payload["issues"]


@pytest.mark.parametrize("backend", ("infinity-context", "mem0"))
@pytest.mark.parametrize("mutation", ("replay", "swap"))
def test_same_scope_evidence_replay_or_signature_swap_fails_closed(
    backend: str,
    mutation: str,
) -> None:
    proofs = _shared_scope_proofs()
    first, second = proofs[backend]
    if mutation == "replay":
        proofs[backend] = (first, first)
        expected_issue = f"{backend}:clean_state_corpus_duplicate"
    else:
        proofs[backend] = (
            replace(first, attestation_hmac_sha256=second.attestation_hmac_sha256),
            replace(second, attestation_hmac_sha256=first.attestation_hmac_sha256),
        )
        expected_issue = f"{backend}:clean_state_proof_invalid"

    validation = validate_typed_clean_state_proofs(
        proofs,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_shared_scope_expectations(),
        attestation_key=_KEY,
    )

    assert validation.eligible is False
    assert expected_issue in validation.payload["issues"]


@pytest.mark.parametrize(
    "mem0_proofs",
    [
        (_mem0(),),
        (_mem0(), _mem0()),
        (_mem0(), _mem0(_MEM0_CORPUS_B, "actual-wrong-scope")),
    ],
)
def test_exact_scope_mapping_rejects_partial_duplicate_and_mismatch(
    mem0_proofs: tuple[BackendCleanStateProof, ...],
) -> None:
    result = validate_typed_clean_state_proofs(
        {"infinity-context": (_fresh(),), "mem0": mem0_proofs},
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )

    assert result.eligible is False
    assert "mem0:clean_state_scope_set_mismatch" in result.payload["issues"]


def test_publishability_reverifies_deserialized_contract_with_exact_inputs() -> None:
    validation = _valid()
    payload = public_clean_state_validation(validation)

    assert validation.eligible is True
    assert clean_state_contract_is_publishable(
        payload,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )
    assert not clean_state_contract_is_publishable(
        payload,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_OTHER_KEY,
    )
    assert not clean_state_contract_is_publishable(
        payload,
        expected_run_id_sha256=clean_state_identity_sha256("wrong-run"),
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )


@pytest.mark.parametrize(
    ("level", "extra_key"),
    [
        ("top", "raw_user_id"),
        ("backend", "raw_api_key"),
        ("proof", "raw_user_id"),
    ],
)
def test_publication_rejects_unsigned_extra_at_every_schema_level(
    level: str,
    extra_key: str,
) -> None:
    payload = copy.deepcopy(public_clean_state_validation(_valid()))
    if level == "top":
        payload[extra_key] = "secret"
    else:
        backends = payload["backends"]
        assert isinstance(backends, dict)
        mem0 = backends["mem0"]
        assert isinstance(mem0, dict)
        if level == "backend":
            mem0[extra_key] = "secret"
        else:
            proofs = mem0["proofs"]
            assert isinstance(proofs, tuple)
            proof = proofs[0]
            assert isinstance(proof, dict)
            proof[extra_key] = "secret"

    assert (
        verify_clean_state_contract_for_publication(
            payload,
            expected_run_id_sha256=_RUN_HASH,
            expected_scopes_by_backend=_expectations(),
            attestation_key=_KEY,
        )
        is None
    )


def test_publication_returns_reconstructed_sanitized_contract() -> None:
    deserialized = json.loads(json.dumps(public_clean_state_validation(_valid())))

    verified = verify_clean_state_contract_for_publication(
        deserialized,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )

    assert verified is not None
    assert verified is not deserialized
    assert "raw_user_id" not in json.dumps(verified)
    backends = verified["backends"]
    assert isinstance(backends, dict)
    mem0 = backends["mem0"]
    assert isinstance(mem0, dict)
    assert isinstance(mem0["proofs"], tuple)


def test_raw_claim_without_signed_proofs_is_never_publishable() -> None:
    raw = {"status": "verified", "eligible": True, "backends": {}}

    assert not clean_state_contract_is_publishable(
        raw,
        expected_run_id_sha256=_RUN_HASH,
        expected_scopes_by_backend=_expectations(),
        attestation_key=_KEY,
    )
