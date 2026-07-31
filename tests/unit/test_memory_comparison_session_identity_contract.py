from __future__ import annotations

import json
import pickle
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
    SessionIdentityMapping,
    session_identity_contract,
    session_identity_contract_is_publishable,
    session_identity_contract_is_verified,
)


def _key(run_id: str = "run-1") -> RunScopedSessionHmacKey:
    return RunScopedSessionHmacKey.generate(run_id=run_id)


class _DuckSessionVerifier:
    def verify(self, evidence: SessionIdentityEvidence) -> bool:
        del evidence
        return True


def _mappings() -> tuple[SessionIdentityMapping, ...]:
    return (
        SessionIdentityMapping(
            corpus_id="corpus-b",
            thread_id="thread-a",
            case_id="case-1",
            conversation_role="memory",
            session_alias="session-0003",
        ),
        SessionIdentityMapping(
            corpus_id="corpus-b",
            thread_id="thread-a",
            case_id="case-1",
            conversation_role="query",
            session_alias="session-0004",
        ),
        SessionIdentityMapping(
            corpus_id="corpus-a",
            thread_id="thread-b",
            case_id="case-2",
            conversation_role="memory",
            session_alias="session-0001",
        ),
        SessionIdentityMapping(
            corpus_id="corpus-a",
            thread_id="thread-b",
            case_id="case-2",
            conversation_role="query",
            session_alias="session-0002",
        ),
    )


def _evidence(
    mappings: tuple[SessionIdentityMapping, ...],
    *,
    key: RunScopedSessionHmacKey,
) -> tuple[SessionIdentityEvidence, ...]:
    return tuple(key.issue(mapping) for mapping in mappings)


def test_live_run_scoped_hmac_proves_exact_session_isolation_mapping() -> None:
    key = _key()
    mappings = _mappings()
    evidence = _evidence(mappings, key=key)

    contract = session_identity_contract(mappings, evidence, verifier=key)

    assert contract["matches"] is True
    assert contract["expected_mapping_count"] == 4
    assert contract["verified_mapping_count"] == 4
    assert contract["publishable"] is False
    assert contract["publication_blockers"] == ["retrieval_completeness_not_composed"]
    assert session_identity_contract_is_verified(
        contract,
        expected_mappings=mappings,
        evidence=evidence,
        verifier=key,
    )
    assert not session_identity_contract_is_publishable(
        contract,
        expected_mappings=mappings,
        evidence=evidence,
        verifier=key,
    )


def test_missing_or_cross_run_verifier_fails_closed() -> None:
    key = _key("run-a")
    mappings = _mappings()
    evidence = _evidence(mappings, key=key)

    missing = session_identity_contract(mappings, evidence, verifier=None)
    cross_run = session_identity_contract(mappings, evidence, verifier=_key("run-b"))

    assert missing["matches"] is False
    assert missing["failure_counts"]["missing_live_verifier_count"] == 1
    assert cross_run["matches"] is False
    assert cross_run["failure_counts"]["invalid_hmac_proof_count"] == 4


@pytest.mark.parametrize("run_id", ("", " run ", True, "x" * 513))
def test_run_key_rejects_empty_raw_or_unbounded_run_id(run_id: object) -> None:
    with pytest.raises(ValueError):
        RunScopedSessionHmacKey.generate(  # type: ignore[arg-type]
            run_id=run_id,
        )


def test_session_verifier_is_exact_sealed_and_privately_constructed() -> None:
    mappings = _mappings()
    key = _key()
    evidence = _evidence(mappings, key=key)

    with pytest.raises(TypeError):
        RunScopedSessionHmacKey(  # type: ignore[call-arg]
            run_id="forged",
            secret=b"x" * 32,
        )
    with pytest.raises(TypeError):

        class _ForgedSubclass(RunScopedSessionHmacKey):
            pass

    contract = session_identity_contract(
        mappings,
        evidence,
        verifier=_DuckSessionVerifier(),  # type: ignore[arg-type]
    )
    assert contract["matches"] is False
    assert contract["failure_counts"]["invalid_live_verifier_type_count"] == 1


def test_raw_fabricated_or_tampered_proofs_fail_closed() -> None:
    key = _key()
    mappings = _mappings()
    signed = list(_evidence(mappings, key=key))
    signed[0] = replace(signed[0], proof=b"fabricated")
    raw_marker = {
        "mapping": mappings[1],
        "proof": b"fabricated",
        "session_identity_schema": "valid",
    }

    contract = session_identity_contract(
        mappings,
        (signed[0], raw_marker, *signed[2:]),
        verifier=key,
    )

    assert contract["matches"] is False
    assert contract["failure_counts"]["invalid_evidence_type_count"] == 1
    assert contract["failure_counts"]["invalid_hmac_proof_count"] == 1


def test_signed_mapping_tamper_invalidates_proof() -> None:
    key = _key()
    mappings = _mappings()
    evidence = list(_evidence(mappings, key=key))
    evidence[0] = replace(
        evidence[0],
        mapping=replace(evidence[0].mapping, case_id="case-forged"),
    )

    assert session_identity_contract(mappings, tuple(evidence), verifier=key)["matches"] is False


def test_evidence_isolation_shape_is_rejected_independently_before_hmac() -> None:
    key = _key()
    mappings = _mappings()
    evidence = list(_evidence(mappings, key=key))
    evidence[1] = replace(
        evidence[1],
        mapping=replace(evidence[1].mapping, corpus_id="corpus-forged"),
    )

    contract = session_identity_contract(mappings, tuple(evidence), verifier=key)

    assert contract["matches"] is False
    assert contract["failure_counts"]["multiple_evidence_corpus_per_case_count"] == 1
    assert contract["failure_counts"]["invalid_hmac_proof_count"] == 1


def test_duplicate_empty_or_missing_mapping_proofs_fail_closed() -> None:
    key = _key()
    mappings = _mappings()
    evidence = _evidence(mappings, key=key)

    assert session_identity_contract((), (), verifier=key)["matches"] is False
    duplicate = session_identity_contract(mappings, (*evidence, evidence[0]), verifier=key)
    missing = session_identity_contract(mappings, evidence[:-1], verifier=key)

    assert duplicate["matches"] is False
    assert duplicate["failure_counts"]["duplicate_evidence_count"] == 1
    assert missing["matches"] is False
    assert missing["failure_counts"]["missing_mapping_count"] == 1


def test_expected_identity_and_alias_mappings_must_be_bijective_per_case() -> None:
    key = _key()
    mappings = _mappings()
    duplicate_role = replace(mappings[1], session_alias="session-0003", conversation_role="memory")
    duplicate_alias = replace(
        mappings[1],
        conversation_role="assistant",
        session_alias=mappings[0].session_alias,
    )

    role_contract = session_identity_contract(
        (*mappings, duplicate_role),
        _evidence(mappings, key=key),
        verifier=key,
    )
    alias_contract = session_identity_contract(
        (*mappings, duplicate_alias),
        _evidence(mappings, key=key),
        verifier=key,
    )

    assert role_contract["failure_counts"]["duplicate_expected_role_count"] == 1
    assert alias_contract["failure_counts"]["duplicate_expected_alias_count"] == 1


@pytest.mark.parametrize(
    ("field", "replacement", "failure"),
    (
        ("corpus_id", "corpus-other", "multiple_expected_corpus_per_case_count"),
        ("thread_id", "thread-other", "multiple_expected_thread_per_case_count"),
    ),
)
def test_each_case_requires_exactly_one_corpus_and_thread_before_hmac(
    field: str,
    replacement: str,
    failure: str,
) -> None:
    key = _key()
    mappings = list(_mappings())
    mappings[1] = replace(mappings[1], **{field: replacement})
    evidence = _evidence(tuple(mappings), key=key)

    contract = session_identity_contract(tuple(mappings), evidence, verifier=key)

    assert contract["matches"] is False
    assert contract["failure_counts"][failure] == 1


@pytest.mark.parametrize(
    ("field", "case_two_values"),
    (
        ("corpus_id", ("corpus-b", "corpus-b")),
        ("thread_id", ("thread-a", "thread-a")),
        ("session_alias", ("session-0003", "session-0004")),
    ),
)
def test_corpus_thread_and_alias_may_be_shared_across_cases(
    field: str,
    case_two_values: tuple[str, str],
) -> None:
    key = _key()
    mappings = list(_mappings())
    mappings[2] = replace(mappings[2], **{field: case_two_values[0]})
    mappings[3] = replace(mappings[3], **{field: case_two_values[1]})
    evidence = _evidence(tuple(mappings), key=key)

    contract = session_identity_contract(tuple(mappings), evidence, verifier=key)

    assert contract["matches"] is True
    assert contract["failure_counts"] == {}


def test_case_local_aliases_allow_shared_corpus_and_thread_across_cases() -> None:
    key = _key()
    mappings = list(_mappings())
    mappings[2] = replace(
        mappings[2],
        corpus_id=mappings[0].corpus_id,
        thread_id=mappings[0].thread_id,
        session_alias=mappings[0].session_alias,
    )
    mappings[3] = replace(
        mappings[3],
        corpus_id=mappings[1].corpus_id,
        thread_id=mappings[1].thread_id,
        session_alias=mappings[1].session_alias,
    )
    shared = tuple(mappings)

    contract = session_identity_contract(shared, _evidence(shared, key=key), verifier=key)

    assert contract["matches"] is True
    assert contract["failure_counts"] == {}


def test_cross_case_evidence_swap_and_replay_fail_closed() -> None:
    key = _key()
    mappings = _mappings()
    evidence = list(_evidence(mappings, key=key))
    swapped = list(evidence)
    swapped[2] = replace(swapped[0], mapping=mappings[2])

    swap_contract = session_identity_contract(mappings, tuple(swapped), verifier=key)
    replay_contract = session_identity_contract(
        mappings,
        (evidence[0], evidence[1], evidence[0], evidence[3]),
        verifier=key,
    )

    assert swap_contract["matches"] is False
    assert swap_contract["failure_counts"]["invalid_hmac_proof_count"] == 1
    assert replay_contract["matches"] is False
    assert replay_contract["failure_counts"]["duplicate_evidence_count"] == 1
    assert replay_contract["failure_counts"]["missing_mapping_count"] == 1


def test_session_identity_evidence_requires_exact_manifest_order() -> None:
    key = _key()
    mappings = _mappings()

    contract = session_identity_contract(
        mappings,
        tuple(reversed(_evidence(mappings, key=key))),
        verifier=key,
    )

    assert contract["matches"] is False
    assert contract["failure_counts"] == {"mapping_order_mismatch_count": 1}


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("corpus_id", ""),
        ("thread_id", " thread "),
        ("case_id", "x" * 513),
        ("conversation_role", True),
        ("session_alias", "raw-private-session-id"),
        ("session_alias", "session-0000"),
    ),
)
def test_empty_raw_or_malformed_identity_fields_fail_closed(
    field: str,
    value: object,
) -> None:
    key = _key()
    mappings = list(_mappings())
    mappings[0] = replace(mappings[0], **{field: value})

    contract = session_identity_contract(tuple(mappings), (), verifier=key)

    assert contract["matches"] is False
    assert contract["failure_counts"]["invalid_expected_mapping_count"] == 1


def test_key_and_proofs_are_not_serialized_or_leaked_by_artifact() -> None:
    key = _key()
    mappings = _mappings()
    evidence = _evidence(mappings, key=key)
    contract = session_identity_contract(mappings, evidence, verifier=key)

    encoded = json.dumps(contract, allow_nan=False, sort_keys=True)
    assert "corpus-a" not in encoded
    assert "session-0001" not in encoded
    assert "ssss" not in encoded
    assert repr(key) == "RunScopedSessionHmacKey(<redacted>)"
    with pytest.raises(TypeError):
        pickle.dumps(key)
    with pytest.raises(TypeError):
        pickle.dumps(evidence[0])
    with pytest.raises(TypeError):
        json.dumps(key)


def test_writable_valid_marker_cannot_replace_live_verification() -> None:
    key = _key()
    mappings = _mappings()
    evidence = _evidence(mappings, key=key)
    forged_payload = {
        "schema_version": "memory-comparison-session-isolation.v2",
        "status": "valid",
        "matches": True,
    }

    assert not session_identity_contract_is_publishable(
        forged_payload,
        expected_mappings=mappings,
        evidence=evidence,
        verifier=key,
    )
    valid_payload = session_identity_contract(mappings, evidence, verifier=key)
    assert not session_identity_contract_is_publishable(
        valid_payload,
        expected_mappings=mappings,
        evidence=evidence,
        verifier=None,
    )
