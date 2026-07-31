from __future__ import annotations

import copy

import pytest
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
    annotate_full_comparison_contract,
    full_comparison_contract_blocks_result,
    full_comparison_scope_blockers,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError


def _dataset_scope() -> dict[str, object]:
    return {
        "code": "dataset_scope_mismatch",
        "expected": {"locomo": 1540},
        "actual": {"locomo": 10},
    }


def _distribution() -> dict[str, object]:
    return {
        "code": "dataset_distribution_mismatch",
        "expected": {"multi-hop": 282, "temporal": 321},
        "actual": {"multi-hop": 5, "temporal": 5},
    }


def _corpus() -> dict[str, object]:
    return {"code": "corpus_count_mismatch", "expected": 10, "actual": 1}


def _contract(blockers: list[dict[str, object]], *, eligible: bool = False) -> dict[str, object]:
    return {"eligible": eligible, "blockers": blockers}


def test_canary_waives_empty_actual_dataset_count_mapping() -> None:
    blocker = {
        "code": "dataset_scope_mismatch",
        "expected": {"locomo": 1540},
        "actual": {},
    }
    assert full_comparison_scope_blockers([blocker], scope=FULL_COMPARISON_SCOPE_CANARY) == ()


@pytest.mark.parametrize("blocker", (_dataset_scope(), _distribution(), _corpus()))
def test_canary_waives_only_exact_dataset_blocker_objects(
    blocker: dict[str, object],
) -> None:
    assert (
        full_comparison_scope_blockers(
            [blocker],
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        == ()
    )


@pytest.mark.parametrize(
    "blocker",
    (
        {"code": "clean_state_proof_invalid", "status": "invalid"},
        {"code": "provider_provenance_untrusted", "trust": "diagnostic"},
        {"code": "mem0_runtime_attestation_invalid", "status": "missing"},
        {"code": "retrieval_width_mismatch", "expected": 200, "actual": 50},
        {"code": "session_isolation_not_verified"},
        {"code": "invalid_answerer_token_usage", "count": 1},
    ),
)
def test_canary_preserves_every_safety_and_unknown_blocker(
    blocker: dict[str, object],
) -> None:
    assert full_comparison_scope_blockers(
        [blocker],
        scope=FULL_COMPARISON_SCOPE_CANARY,
    ) == (blocker,)
    annotated = annotate_full_comparison_contract(
        _contract([blocker]),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is True
    )


def test_canary_recomputes_exact_diagnostic_from_root_on_every_call() -> None:
    root_blockers = [_dataset_scope(), _distribution(), _corpus()]
    annotated = annotate_full_comparison_contract(
        _contract(root_blockers),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    assert annotated["diagnostic_canary"] == {
        "schema_version": "memory-comparison-full-canary-scope.v1",
        "publishable": False,
        "eligible": True,
        "blockers": [],
        "waived_blockers": root_blockers,
        "allowed_non_publishable_blockers": [
            "corpus_count_mismatch",
            "dataset_distribution_mismatch",
            "dataset_scope_mismatch",
        ],
    }
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is False
    )

    annotated["blockers"].append({"code": "retrieval_width_mismatch"})
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is True
    )


def test_full_scope_blocks_any_root_blocker_even_when_eligible_true() -> None:
    annotated = annotate_full_comparison_contract(
        _contract([_dataset_scope()], eligible=True),
        scope=FULL_COMPARISON_SCOPE_FULL,
    )
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_FULL,
        )
        is True
    )
    clean = annotate_full_comparison_contract(
        _contract([], eligible=True),
        scope=FULL_COMPARISON_SCOPE_FULL,
    )
    assert (
        full_comparison_contract_blocks_result(
            clean,
            scope=FULL_COMPARISON_SCOPE_FULL,
        )
        is False
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda contract: contract["diagnostic_canary"].update(eligible=False),
        lambda contract: contract["diagnostic_canary"].update(extra="unknown"),
        lambda contract: contract["diagnostic_canary"]["allowed_non_publishable_blockers"].append(
            "retrieval_width_mismatch"
        ),
        lambda contract: contract.update(scope="full"),
        lambda contract: contract.update(publishable=True),
    ),
)
def test_root_diagnostic_divergence_and_extra_fields_fail_closed(mutate) -> None:
    annotated = annotate_full_comparison_contract(
        _contract([_dataset_scope()]),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    mutate(annotated)
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is True
    )


@pytest.mark.parametrize(
    "blocker",
    (
        {
            "code": "dataset_scope_mismatch",
            "expected": {"locomo": 1540},
            "actual": {"locomo": 10},
            "safety": "ignore",
        },
        {"code": "corpus_count_mismatch", "expected": True, "actual": 1},
        {"code": "corpus_count_mismatch", "expected": 10.0, "actual": 1},
        {"code": "corpus_count_mismatch", "expected": 10, "actual": -1},
    ),
)
def test_malformed_relaxable_blocker_is_replaced_and_never_waived(
    blocker: dict[str, object],
) -> None:
    assert full_comparison_scope_blockers(
        [blocker],
        scope=FULL_COMPARISON_SCOPE_CANARY,
    ) == ({"code": "invalid_blocker_contract"},)


def test_mapping_subclasses_and_forged_get_are_rejected() -> None:
    class Forged(dict):
        def get(self, key, default=None):
            raise AssertionError("forged get must not be called")

    with pytest.raises(BenchmarkValidationError, match="exact dict"):
        annotate_full_comparison_contract(
            Forged(_contract([])),
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
    assert full_comparison_scope_blockers(
        [Forged(_dataset_scope())],
        scope=FULL_COMPARISON_SCOPE_CANARY,
    ) == ({"code": "invalid_blocker_contract"},)


def test_nested_mapping_mutation_does_not_alias_annotated_root() -> None:
    blocker = _dataset_scope()
    annotated = annotate_full_comparison_contract(
        _contract([blocker]),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    blocker["actual"]["locomo"] = 999
    assert annotated["blockers"][0]["actual"] == {"locomo": 10}
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is False
    )


def test_mapping_subclass_diagnostic_and_exact_bool_are_rejected() -> None:
    annotated = annotate_full_comparison_contract(
        _contract([_dataset_scope()]),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    annotated["diagnostic_canary"] = type("Subclass", (dict,), {})(
        copy.deepcopy(annotated["diagnostic_canary"])
    )
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_CANARY,
        )
        is True
    )
    annotated = annotate_full_comparison_contract(
        _contract([], eligible=True),
        scope=FULL_COMPARISON_SCOPE_FULL,
    )
    annotated["eligible"] = 1
    assert (
        full_comparison_contract_blocks_result(
            annotated,
            scope=FULL_COMPARISON_SCOPE_FULL,
        )
        is True
    )


def test_overdeep_blocker_payload_fails_closed_without_recursive_trust() -> None:
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(12):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    blocker = {"code": "safety_blocker", "details": nested}
    assert full_comparison_scope_blockers([blocker], scope=FULL_COMPARISON_SCOPE_CANARY) == (
        {"code": "invalid_blocker_contract"},
    )


def test_mutating_exact_waived_root_blocker_diverges_from_diagnostic_snapshot() -> None:
    annotated = annotate_full_comparison_contract(
        _contract([_dataset_scope()]),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    annotated["blockers"][0]["actual"]["locomo"] = 999
    assert (
        full_comparison_contract_blocks_result(annotated, scope=FULL_COMPARISON_SCOPE_CANARY)
        is True
    )


def test_root_eligible_must_exactly_match_root_blockers() -> None:
    inconsistent = annotate_full_comparison_contract(
        _contract([], eligible=False),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    assert (
        full_comparison_contract_blocks_result(inconsistent, scope=FULL_COMPARISON_SCOPE_CANARY)
        is True
    )
    consistent = annotate_full_comparison_contract(
        _contract([], eligible=True),
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    assert (
        full_comparison_contract_blocks_result(consistent, scope=FULL_COMPARISON_SCOPE_CANARY)
        is False
    )
