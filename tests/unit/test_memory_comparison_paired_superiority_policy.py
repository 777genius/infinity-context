from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_paired_superiority_policy import (
    PAIRED_SUPERIORITY_POLICY_SHA256,
    PairedBinaryStratum,
    PairedDatasetRunAuthority,
    PairedSuperiorityEvidence,
    PairedSuperiorityPolicyError,
    evaluate_paired_superiority,
    paired_superiority_dataset_counts_sha256,
    paired_superiority_policy_payload,
    paired_superiority_publication_bundle_sha256,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    resolve_publishable_methodology,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    resolve_publishable_comparison_profile,
)

_EXPECTED = (
    ("locomo", "multi-hop", 282),
    ("locomo", "temporal", 321),
    ("locomo", "open-domain", 96),
    ("locomo", "single-hop", 841),
    ("longmemeval", "knowledge-update", 78),
    ("longmemeval", "multi-session", 133),
    ("longmemeval", "single-session-assistant", 56),
    ("longmemeval", "single-session-preference", 30),
    ("longmemeval", "single-session-user", 70),
    ("longmemeval", "temporal", 133),
)


def _authorities() -> tuple[str, str]:
    profile = resolve_publishable_comparison_profile()
    methodology = resolve_publishable_methodology()
    assert profile is not None
    assert methodology is not None
    return profile.commitment_sha256, methodology.commitment_sha256


def _evidence(
    changes: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> PairedSuperiorityEvidence:
    profile_sha, methodology_sha = _authorities()
    changes = changes or {}
    strata = tuple(
        PairedBinaryStratum(
            benchmark,
            category,
            total - sum(changes.get((benchmark, category), (0, 0))),
            changes.get((benchmark, category), (0, 0))[0],
            changes.get((benchmark, category), (0, 0))[1],
            0,
        )
        for benchmark, category, total in _EXPECTED
    )
    locomo_counts = paired_superiority_dataset_counts_sha256(
        benchmark="locomo",
        strata=tuple(item for item in strata if item.benchmark == "locomo"),
    )
    longmemeval_counts = paired_superiority_dataset_counts_sha256(
        benchmark="longmemeval",
        strata=tuple(item for item in strata if item.benchmark == "longmemeval"),
    )
    runs = (
        PairedDatasetRunAuthority(
            benchmark="locomo",
            profile_commitment_sha256=profile_sha,
            binding_commitment_sha256="a" * 64,
            case_manifest_sha256="b" * 64,
            judge_outcomes_sha256="c" * 64,
            paired_counts_sha256=locomo_counts,
            terminal_report_sha256="d" * 64,
            terminal_receipt_sha256="e" * 64,
        ),
        PairedDatasetRunAuthority(
            benchmark="longmemeval",
            profile_commitment_sha256=profile_sha,
            binding_commitment_sha256="f" * 64,
            case_manifest_sha256="1" * 64,
            judge_outcomes_sha256="2" * 64,
            paired_counts_sha256=longmemeval_counts,
            terminal_report_sha256="3" * 64,
            terminal_receipt_sha256="4" * 64,
        ),
    )
    bundle = paired_superiority_publication_bundle_sha256(
        profile_commitment_sha256=profile_sha,
        methodology_commitment_sha256=methodology_sha,
        policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        dataset_runs=runs,
    )
    return PairedSuperiorityEvidence(
        profile_sha,
        methodology_sha,
        PAIRED_SUPERIORITY_POLICY_SHA256,
        runs,
        bundle,
        strata,
    )


def _distributed_evidence(infinity_wins: int, mem0_wins: int) -> PairedSuperiorityEvidence:
    remaining_left = infinity_wins
    remaining_right = mem0_wins
    changes: dict[tuple[str, str], tuple[int, int]] = {}
    for benchmark, category, total in _EXPECTED:
        left = min(total, remaining_left)
        remaining_left -= left
        right = min(total - left, remaining_right)
        remaining_right -= right
        changes[(benchmark, category)] = (left, right)
    assert remaining_left == 0
    assert remaining_right == 0
    return _evidence(changes)


def test_policy_is_result_independent_and_matches_frozen_profile_counts() -> None:
    payload = paired_superiority_policy_payload()
    profile = resolve_publishable_comparison_profile()
    assert profile is not None
    public = public_publishable_comparison_profile(profile)

    assert canonical_payload_sha256(payload) == PAIRED_SUPERIORITY_POLICY_SHA256
    assert payload["expected_pair_count"] == 2040
    assert payload["alpha"] == {"numerator": 1, "denominator": 40}
    assert payload["primary"] == {
        "test": "one_sided_exact_mcnemar",
        "minimum_accuracy_delta_basis_points": 200,
    }
    assert (
        sum(item[2] for item in _EXPECTED if item[0] == "locomo")
        == public["benchmarks"]["locomo"]["expected_case_count"]
    )
    assert (
        sum(item[2] for item in _EXPECTED if item[0] == "longmemeval")
        == public["benchmarks"]["longmemeval"]["expected_case_count"]
    )


def test_exact_41_net_wins_meets_effect_significance_and_guardrails() -> None:
    result = evaluate_paired_superiority(
        _evidence(
            {
                ("locomo", "multi-hop"): (21, 0),
                ("longmemeval", "knowledge-update"): (20, 0),
            }
        )
    )

    assert result["criterion_met"] is True
    assert result["publishable"] is False
    assert result["failures"] == []
    assert result["overall"]["pair_count"] == 2040
    assert result["overall"]["net_win_count"] == 41
    assert result["overall"]["minimum_effect_met"] is True
    assert result["overall"]["exact_mcnemar_p_value"] == "4.547473508865E-13"
    assert all(item["observed_delta_guardrail_met"] for item in result["datasets"])
    assert all(item["observed_delta_guardrail_met"] for item in result["categories"])
    assert [item["benchmark"] for item in result["ordered_dataset_runs"]] == [
        "locomo",
        "longmemeval",
    ]
    body = copy.deepcopy(result)
    digest = body.pop("decision_sha256")
    assert digest == canonical_payload_sha256(body)


def test_40_net_wins_fails_predeclared_two_point_effect() -> None:
    result = evaluate_paired_superiority(
        _evidence(
            {
                ("locomo", "multi-hop"): (20, 0),
                ("longmemeval", "knowledge-update"): (20, 0),
            }
        )
    )

    assert result["overall"]["exact_superiority_met"] is True
    assert result["overall"]["minimum_effect_met"] is False
    assert result["criterion_met"] is False
    assert result["failures"] == ["overall_minimum_effect_not_met"]


def test_effect_without_exact_mcnemar_significance_fails() -> None:
    result = evaluate_paired_superiority(_distributed_evidence(1040, 999))

    assert result["overall"]["net_win_count"] == 41
    assert result["overall"]["minimum_effect_met"] is True
    assert result["overall"]["exact_superiority_met"] is False
    assert "overall_exact_superiority_not_met" in result["failures"]


def test_overall_win_cannot_hide_dataset_regression() -> None:
    result = evaluate_paired_superiority(
        _evidence(
            {
                ("locomo", "multi-hop"): (100, 0),
                ("longmemeval", "knowledge-update"): (0, 20),
            }
        )
    )

    assert result["overall"]["exact_superiority_met"] is True
    assert "longmemeval_observed_regression" in result["failures"]
    assert result["criterion_met"] is False


def test_dataset_balance_cannot_hide_material_category_harm() -> None:
    result = evaluate_paired_superiority(
        _evidence(
            {
                ("locomo", "multi-hop"): (100, 0),
                ("longmemeval", "knowledge-update"): (3, 0),
                ("longmemeval", "single-session-preference"): (0, 3),
            }
        )
    )

    longmemeval = next(item for item in result["datasets"] if item["benchmark"] == "longmemeval")
    assert longmemeval["net_win_count"] == 0
    assert longmemeval["observed_delta_guardrail_met"] is True
    assert "longmemeval:single-session-preference_observed_harm_exceeded" in result["failures"]


def test_exact_coverage_policy_and_authorities_fail_closed() -> None:
    evidence = _evidence()
    malformed = PairedBinaryStratum("locomo", "multi-hop", 281, 0, 0, 0)
    with pytest.raises(PairedSuperiorityPolicyError, match="paired_superiority_coverage_invalid"):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            evidence.policy_sha256,
            evidence.dataset_runs,
            evidence.publication_bundle_sha256,
            (malformed, *evidence.strata[1:]),
        )
    with pytest.raises(PairedSuperiorityPolicyError, match="paired_superiority_evidence_invalid"):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            "d" * 64,
            evidence.dataset_runs,
            evidence.publication_bundle_sha256,
            evidence.strata,
        )


def test_ordered_dataset_runs_and_publication_bundle_fail_closed() -> None:
    evidence = _evidence()
    with pytest.raises(
        PairedSuperiorityPolicyError, match="paired_superiority_run_authority_invalid"
    ):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            evidence.policy_sha256,
            tuple(reversed(evidence.dataset_runs)),
            evidence.publication_bundle_sha256,
            evidence.strata,
        )


def test_dataset_counts_are_coupled_to_judge_run_and_publication_bundle() -> None:
    evidence = _evidence()
    first = evidence.strata[0]
    changed_first = PairedBinaryStratum(
        first.benchmark,
        first.category,
        first.both_correct - 1,
        first.infinity_only_correct + 1,
        first.mem0_only_correct,
        first.both_incorrect,
    )
    changed_strata = (changed_first, *evidence.strata[1:])
    with pytest.raises(
        PairedSuperiorityPolicyError, match="paired_superiority_run_authority_invalid"
    ):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            evidence.policy_sha256,
            evidence.dataset_runs,
            evidence.publication_bundle_sha256,
            changed_strata,
        )

    changed_counts = paired_superiority_dataset_counts_sha256(
        benchmark="locomo",
        strata=tuple(item for item in changed_strata if item.benchmark == "locomo"),
    )
    changed_run = replace(evidence.dataset_runs[0], paired_counts_sha256=changed_counts)
    changed_runs = (changed_run, evidence.dataset_runs[1])
    changed_bundle = paired_superiority_publication_bundle_sha256(
        profile_commitment_sha256=evidence.profile_commitment_sha256,
        methodology_commitment_sha256=evidence.methodology_commitment_sha256,
        policy_sha256=evidence.policy_sha256,
        dataset_runs=changed_runs,
    )
    assert changed_run.judge_outcomes_sha256 == evidence.dataset_runs[0].judge_outcomes_sha256
    assert changed_bundle != evidence.publication_bundle_sha256
    rebound = PairedSuperiorityEvidence(
        evidence.profile_commitment_sha256,
        evidence.methodology_commitment_sha256,
        evidence.policy_sha256,
        changed_runs,
        changed_bundle,
        changed_strata,
    )
    assert evaluate_paired_superiority(rebound)["publishable"] is False
    changed = PairedDatasetRunAuthority(
        benchmark="locomo",
        profile_commitment_sha256=evidence.profile_commitment_sha256,
        binding_commitment_sha256="9" * 64,
        case_manifest_sha256="b" * 64,
        judge_outcomes_sha256="c" * 64,
        paired_counts_sha256=evidence.dataset_runs[0].paired_counts_sha256,
        terminal_report_sha256="d" * 64,
        terminal_receipt_sha256="e" * 64,
    )
    with pytest.raises(
        PairedSuperiorityPolicyError, match="paired_superiority_publication_bundle_invalid"
    ):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            evidence.policy_sha256,
            (changed, evidence.dataset_runs[1]),
            evidence.publication_bundle_sha256,
            evidence.strata,
        )
    cross_profile = PairedDatasetRunAuthority(
        benchmark="locomo",
        profile_commitment_sha256="8" * 64,
        binding_commitment_sha256="a" * 64,
        case_manifest_sha256="b" * 64,
        judge_outcomes_sha256="c" * 64,
        paired_counts_sha256=evidence.dataset_runs[0].paired_counts_sha256,
        terminal_report_sha256="d" * 64,
        terminal_receipt_sha256="e" * 64,
    )
    with pytest.raises(
        PairedSuperiorityPolicyError, match="paired_superiority_run_authority_invalid"
    ):
        PairedSuperiorityEvidence(
            evidence.profile_commitment_sha256,
            evidence.methodology_commitment_sha256,
            evidence.policy_sha256,
            (cross_profile, evidence.dataset_runs[1]),
            evidence.publication_bundle_sha256,
            evidence.strata,
        )


@pytest.mark.parametrize("benchmark", ("other", "", True, None))
def test_dataset_counts_commitment_rejects_unknown_or_non_string_benchmark(
    benchmark: object,
) -> None:
    with pytest.raises(
        PairedSuperiorityPolicyError, match="paired_superiority_dataset_counts_invalid"
    ):
        paired_superiority_dataset_counts_sha256(benchmark=benchmark, strata=())  # type: ignore[arg-type]


def test_nominal_evidence_tampering_is_revalidated_at_evaluation() -> None:
    evidence = _evidence()
    object.__setattr__(evidence, "publication_bundle_sha256", "D" * 64)

    with pytest.raises(PairedSuperiorityPolicyError, match="paired_superiority_evidence_invalid"):
        evaluate_paired_superiority(evidence)

    evidence = _evidence()
    object.__setattr__(evidence.strata[0], "infinity_only_correct", True)
    object.__setattr__(evidence.strata[0], "both_correct", 281)
    with pytest.raises(PairedSuperiorityPolicyError, match="paired_superiority_stratum_invalid"):
        evaluate_paired_superiority(evidence)
