from __future__ import annotations

import inspect
import json
import pickle
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_retrieval_width import (
    ANSWER_CUTOFF,
    COMPARISON_BACKEND_ROLES,
    RETRIEVAL_TOP_K,
    RetrievalCompletenessEvidence,
    RunScopedRetrievalCompletenessKey,
    retrieval_width_contract,
)


class _DuckVerifier:
    def verify(self, evidence: RetrievalCompletenessEvidence) -> bool:
        del evidence
        return True


_TRUSTED_KEY = RunScopedRetrievalCompletenessKey.generate(run_id="retrieval-test-run")


def _evidence(
    role: str,
    case_id: str,
    *,
    requested: object = RETRIEVAL_TOP_K,
    answer_cutoff: object = ANSWER_CUTOFF,
    returned: object = RETRIEVAL_TOP_K,
    available: object = RETRIEVAL_TOP_K,
    exhaustive: object = True,
    continuation: object = None,
) -> RetrievalCompletenessEvidence:
    return _TRUSTED_KEY.issue(
        backend_role=role,
        case_id=case_id,
        requested_count=requested,  # type: ignore[arg-type]
        answer_cutoff=answer_cutoff,  # type: ignore[arg-type]
        returned_count=returned,  # type: ignore[arg-type]
        available_count=available,  # type: ignore[arg-type]
        exhaustive=exhaustive,  # type: ignore[arg-type]
        continuation_proof=continuation,  # type: ignore[arg-type]
    )


def _complete_case(case_id: str) -> tuple[RetrievalCompletenessEvidence, ...]:
    return tuple(_evidence(role, case_id) for role in COMPARISON_BACKEND_ROLES)


def _contract(
    evidence: tuple[object, ...],
    *,
    expected: tuple[object, ...] = ("case-1",),
    verifier: object = _TRUSTED_KEY,
) -> dict[str, object]:
    return retrieval_width_contract(
        evidence,
        expected_case_ids=expected,
        verifier=verifier,  # type: ignore[arg-type]
    )


def test_contract_freezes_retrieval_200_and_answer_50_without_override_parameters() -> None:
    contract = _contract(_complete_case("case-1"))

    assert RETRIEVAL_TOP_K == 200
    assert ANSWER_CUTOFF == 50
    assert contract["expected_retrieval_top_k"] == 200
    assert contract["expected_answer_cutoff"] == 50
    assert "retrieval_top_k" not in inspect.signature(retrieval_width_contract).parameters
    assert "answer_cutoff" not in inspect.signature(retrieval_width_contract).parameters
    assert contract["matches"] is True
    assert contract["publishable"] is False
    assert contract["publication_blockers"] == ["session_isolation_not_composed"]


def test_every_role_and_case_requires_one_nonempty_observation() -> None:
    evidence = _complete_case("case-1") + (_evidence("infinity-context", "case-2"),)

    contract = _contract(evidence, expected=("case-1", "case-2"))

    assert contract["matches"] is False
    assert contract["failure_counts"]["missing_role_case_count"] == 1


def test_empty_observation_set_is_never_complete() -> None:
    contract = _contract(())

    assert contract["matches"] is False
    assert contract["failure_counts"]["missing_role_case_count"] == 2


@pytest.mark.parametrize(
    "expected",
    ((), ("",), (" case-1 ",), ("x" * 513,), ("case-1", "case-1"), (True,)),
)
def test_expected_case_set_must_be_nonempty_exact_and_unique(
    expected: tuple[object, ...],
) -> None:
    assert _contract((), expected=expected)["matches"] is False


def test_non_sequence_evidence_fails_closed_without_raising() -> None:
    contract = retrieval_width_contract(
        None,  # type: ignore[arg-type]
        expected_case_ids=("case-1",),
        verifier=_TRUSTED_KEY,
    )

    assert contract["matches"] is False
    assert contract["failure_counts"]["invalid_evidence_sequence_count"] == 1


def test_capped_14_of_200_cannot_claim_complete_retrieval() -> None:
    evidence = tuple(
        _evidence(role, "case-1", returned=14, available=200) for role in COMPARISON_BACKEND_ROLES
    )

    contract = _contract(evidence)

    assert contract["matches"] is False
    assert contract["failure_counts"]["incomplete_return_count"] == 2


def test_unknown_available_count_or_raw_writable_marker_cannot_pass() -> None:
    raw = {
        "backend_role": "infinity-context",
        "case_id": "case-1",
        "requested_count": 200,
        "returned_count": 14,
        "exhaustive": True,
    }

    contract = _contract((raw, *_complete_case("case-1")))

    assert contract["matches"] is False
    assert contract["failure_counts"]["invalid_evidence_type_count"] == 1


def test_legitimate_small_exhaustive_result_set_passes() -> None:
    evidence = tuple(
        _evidence(role, "case-1", returned=14, available=14) for role in COMPARISON_BACKEND_ROLES
    )

    assert _contract(evidence)["matches"] is True


def test_large_available_set_requires_exhaustive_or_continuation_evidence() -> None:
    valid = tuple(
        _evidence(
            role,
            "case-1",
            returned=200,
            available=500,
            exhaustive=False,
            continuation=b"opaque-continuation-proof",
        )
        for role in COMPARISON_BACKEND_ROLES
    )
    missing = tuple(replace(item, continuation_proof=None) for item in valid)

    assert _contract(valid)["matches"] is True
    blocked = _contract(missing)
    assert blocked["matches"] is False
    assert blocked["failure_counts"]["missing_exhaustive_or_continuation_evidence_count"] == 2


@pytest.mark.parametrize("continuation", (None, b"unexpected-with-exhaustive"))
def test_large_available_set_rejects_exhaustive_true_even_at_width_200(
    continuation: bytes | None,
) -> None:
    evidence = tuple(
        _evidence(
            role,
            "case-1",
            returned=200,
            available=500,
            exhaustive=True,
            continuation=continuation,
        )
        for role in COMPARISON_BACKEND_ROLES
    )

    assert _contract(evidence)["matches"] is False


@pytest.mark.parametrize("continuation", (b"", b"unexpected"))
def test_continuation_marker_is_incoherent_for_exhausted_small_result_set(
    continuation: bytes,
) -> None:
    evidence = tuple(
        _evidence(role, "case-1", returned=14, available=14, continuation=continuation)
        for role in COMPARISON_BACKEND_ROLES
    )

    assert _contract(evidence)["matches"] is False


def test_returned_count_cannot_exceed_available_count() -> None:
    evidence = tuple(
        _evidence(role, "case-1", returned=15, available=14) for role in COMPARISON_BACKEND_ROLES
    )

    contract = _contract(evidence)
    assert contract["failure_counts"]["returned_exceeds_available_count"] == 2


def test_unknown_backend_role_or_case_is_rejected() -> None:
    valid = _complete_case("case-1")
    role_contract = _contract((*valid, replace(valid[0], backend_role="writable-role")))
    case_contract = _contract((*valid, _evidence("mem0", "unexpected-case")))

    assert role_contract["failure_counts"]["invalid_backend_role_count"] == 1
    assert case_contract["failure_counts"]["unexpected_case_count"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("requested_count", True),
        ("requested_count", 200.0),
        ("answer_cutoff", 49),
        ("returned_count", -1),
        ("available_count", 1_000_000_001),
        ("exhaustive", 1),
        ("attestation", b""),
    ),
)
def test_malformed_or_unbounded_completeness_evidence_fails_closed(
    field: str,
    value: object,
) -> None:
    evidence = list(_complete_case("case-1"))
    evidence[0] = replace(evidence[0], **{field: value})

    assert _contract(tuple(evidence))["matches"] is False


def test_missing_duck_or_cross_run_verifier_fails_closed() -> None:
    evidence = _complete_case("case-1")

    assert _contract(evidence, verifier=None)["matches"] is False
    assert _contract(evidence, verifier=_DuckVerifier())["matches"] is False
    assert (
        _contract(
            evidence,
            verifier=RunScopedRetrievalCompletenessKey.generate(run_id="other-run"),
        )["matches"]
        is False
    )
    forged = tuple(replace(item, attestation=b"forged") for item in evidence)
    assert _contract(forged)["matches"] is False


def test_retrieval_verifier_is_exact_sealed_and_privately_constructed() -> None:
    with pytest.raises(TypeError):
        RunScopedRetrievalCompletenessKey(  # type: ignore[call-arg]
            run_id="forged",
            secret=b"x" * 32,
        )
    with pytest.raises(TypeError):

        class _ForgedSubclass(RunScopedRetrievalCompletenessKey):
            pass


def test_duplicate_role_case_observation_fails_closed() -> None:
    evidence = _complete_case("case-1")
    contract = _contract((*evidence, evidence[0]))

    assert contract["matches"] is False
    assert contract["failure_counts"]["duplicate_role_case_count"] == 1


def test_retrieval_contract_artifact_is_strict_json_without_live_proofs() -> None:
    evidence = _complete_case("case-1")
    contract = _contract(evidence)

    encoded = json.dumps(contract, allow_nan=False, sort_keys=True)
    assert "trusted-adapter-attestation" not in encoded
    assert "opaque-continuation-proof" not in encoded
    with pytest.raises(TypeError):
        pickle.dumps(evidence[0])
    with pytest.raises(TypeError):
        pickle.dumps(_TRUSTED_KEY)
