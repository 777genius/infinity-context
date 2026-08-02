from __future__ import annotations

import json

import pytest
from infinity_context_server import memory_comparison_managed_execution_receipts as receipts
from infinity_context_server import memory_comparison_managed_quality_projection as quality
from infinity_context_server import memory_comparison_managed_run as managed
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_quality_projection import (
    ManagedPairedQualityProjectionError,
    ManagedPairedQualityProjectionInput,
    ManagedSealedJudgeOutcome,
    create_managed_paired_quality_projection_input,
    project_managed_paired_quality,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedRunError,
    create_managed_comparison_run_bindings,
    public_managed_run,
)
from managed_run_test_support import make_plan as _plan
from managed_run_test_support import make_rig as _rig
from managed_run_test_support import run_managed as _run
from managed_run_test_support import sealed_judge_outcome


def _manifest(*aliases: str) -> tuple[FullExecutionCaseManifestEntry, ...]:
    return tuple(
        FullExecutionCaseManifestEntry(
            alias,
            f"corpus-{index}",
            f"thread-{index}",
            ("memory",),
            (f"session-{index:04d}",),
            1,
        )
        for index, alias in enumerate(aliases, start=1)
    )


def _proofs(
    bindings,
    rows: tuple[tuple[str, str, str, float], ...],
) -> tuple[ManagedSealedJudgeOutcome, ...]:
    return tuple(
        sealed_judge_outcome(
            bindings=bindings,
            case_alias=alias,
            backend_role=role,
            verdict=verdict,
            score=score,
        )
        for alias, role, verdict, score in rows
    )


def _projection(
    bindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    proofs: tuple[ManagedSealedJudgeOutcome, ...],
):
    value = create_managed_paired_quality_projection_input(
        bindings=bindings,
        case_manifest=manifest,
        case_manifest_sha256=execution_case_manifest_sha256(manifest),
        outcomes=proofs,
    )
    return project_managed_paired_quality(value)


def test_projection_uses_receipt_issued_proofs_and_keeps_case_material_private() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    manifest = _manifest("case-a", "case-b", "case-c")
    projection = _projection(
        bindings,
        manifest,
        _proofs(
            bindings,
            (
                ("case-a", "infinity-context", "correct", 0.9),
                ("case-a", "mem0", "incorrect", 0.1),
                ("case-b", "infinity-context", "partial", 0.3),
                ("case-b", "mem0", "error", 0.3),
                ("case-c", "infinity-context", "abstain", 0.5),
                ("case-c", "mem0", "partial", 0.8),
            ),
        ),
    )

    first = projection.public_payload()
    first["backends"]["memo_stack"]["correct"] = 999  # type: ignore[index]
    report = projection.public_payload()

    assert report["backends"] == {
        "memo_stack": {"total": 3, "correct": 1, "accuracy": 1 / 3},
        "mem0": {"total": 3, "correct": 0, "accuracy": 0.0},
    }
    assert report["paired"] == {
        "memo_stack_win_count": 1,
        "tie_count": 1,
        "mem0_win_count": 1,
        "accuracy_delta": 1 / 3,
    }
    assert report["coverage"] == {
        "case_count": 3,
        "expected_lane_count": 6,
        "observed_lane_count": 6,
        "complete": True,
    }
    rendered = json.dumps(report, sort_keys=True)
    assert "case-a" not in rendered
    assert "case-b" not in rendered
    assert "case-c" not in rendered


def test_shared_gold_blind_verdict_set_allows_fractional_scores_without_coupling() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    manifest = _manifest("case-a", "case-b", "case-c")
    report = _projection(
        bindings,
        manifest,
        _proofs(
            bindings,
            (
                ("case-a", "infinity-context", "correct", 0.2),
                ("case-a", "mem0", "incorrect", 0.9),
                ("case-b", "infinity-context", "partial", 0.17),
                ("case-b", "mem0", "abstain", 0.72),
                ("case-c", "infinity-context", "error", 0.45),
                ("case-c", "mem0", "partial", 0.55),
            ),
        ),
    ).public_payload()

    assert report["backends"]["memo_stack"] == {
        "total": 3,
        "correct": 1,
        "accuracy": 1 / 3,
    }
    assert report["backends"]["mem0"] == {"total": 3, "correct": 0, "accuracy": 0.0}
    assert report["paired"] == {
        "memo_stack_win_count": 0,
        "tie_count": 0,
        "mem0_win_count": 3,
        "accuracy_delta": 1 / 3,
    }


def test_accuracy_delta_can_be_negative() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    manifest = _manifest("case-a")
    report = _projection(
        bindings,
        manifest,
        _proofs(
            bindings,
            (
                ("case-a", "infinity-context", "partial", 0.9),
                ("case-a", "mem0", "correct", 0.1),
            ),
        ),
    ).public_payload()

    assert report["paired"] == {
        "memo_stack_win_count": 1,
        "tie_count": 0,
        "mem0_win_count": 0,
        "accuracy_delta": -1.0,
    }


def test_projection_rejects_forged_replayed_and_manifest_mismatched_proofs() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    manifest = _manifest("case-a")
    proofs = _proofs(
        bindings,
        (
            ("case-a", "infinity-context", "correct", 1.0),
            ("case-a", "mem0", "incorrect", 0.0),
        ),
    )

    with pytest.raises(ManagedPairedQualityProjectionError, match="quality_input_forged"):
        ManagedPairedQualityProjectionInput(_token=object())
    with pytest.raises(
        ManagedPairedQualityProjectionError,
        match="quality_manifest_binding_invalid",
    ):
        create_managed_paired_quality_projection_input(
            bindings=bindings,
            case_manifest=manifest,
            case_manifest_sha256="0" * 64,
            outcomes=proofs,
        )
    value = create_managed_paired_quality_projection_input(
        bindings=bindings,
        case_manifest=manifest,
        case_manifest_sha256=execution_case_manifest_sha256(manifest),
        outcomes=proofs,
    )
    assert type(value) is ManagedPairedQualityProjectionInput
    with pytest.raises(ManagedPairedQualityProjectionError, match="quality_proof_invalid"):
        create_managed_paired_quality_projection_input(
            bindings=bindings,
            case_manifest=manifest,
            case_manifest_sha256=execution_case_manifest_sha256(manifest),
            outcomes=proofs,
        )


def test_projection_rejects_a_foreign_issuer_proof_for_the_same_lane() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    foreign_bindings = create_managed_comparison_run_bindings(
        _plan(run_id="managed-foreign")
    )
    manifest = _manifest("case-a")
    foreign = sealed_judge_outcome(
        bindings=foreign_bindings,
        case_alias="case-a",
        backend_role="infinity-context",
        verdict="correct",
        score=1.0,
    )
    local = sealed_judge_outcome(
        bindings=bindings,
        case_alias="case-a",
        backend_role="mem0",
        verdict="incorrect",
        score=0.0,
    )

    with pytest.raises(ManagedPairedQualityProjectionError, match="quality_proof_invalid"):
        create_managed_paired_quality_projection_input(
            bindings=bindings,
            case_manifest=manifest,
            case_manifest_sha256=execution_case_manifest_sha256(manifest),
            outcomes=(foreign, local),
        )


def test_projection_rejects_post_issue_comparison_commitment_substitution() -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    foreign_bindings = create_managed_comparison_run_bindings(
        _plan(run_id="managed-foreign")
    )
    assert foreign_bindings.binding_commitment_sha256 != bindings.binding_commitment_sha256
    foreign = sealed_judge_outcome(
        bindings=foreign_bindings,
        case_alias="case-a",
        backend_role="infinity-context",
        verdict="correct",
        score=1.0,
    )
    issuer = receipts._SEALED_JUDGE_OUTCOMES[foreign].issuer
    issuer_state = receipts._ISSUERS[issuer]
    object.__setattr__(
        issuer_state.answer_binding,
        "comparison_commitment_sha256",
        bindings.binding_commitment_sha256,
    )
    object.__setattr__(
        issuer_state.judge_binding,
        "comparison_commitment_sha256",
        bindings.binding_commitment_sha256,
    )
    local = sealed_judge_outcome(
        bindings=bindings,
        case_alias="case-a",
        backend_role="mem0",
        verdict="incorrect",
        score=0.0,
    )

    with pytest.raises(ManagedPairedQualityProjectionError, match="quality_proof_invalid"):
        create_managed_paired_quality_projection_input(
            bindings=bindings,
            case_manifest=_manifest("case-a"),
            case_manifest_sha256=execution_case_manifest_sha256(_manifest("case-a")),
            outcomes=(foreign, local),
        )


def test_projection_uses_the_public_binding_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings = create_managed_comparison_run_bindings(_plan())
    manifest = _manifest("case-a")
    calls: list[object] = []
    original = quality.validate_full_comparison_run_bindings

    def validate(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(quality, "validate_full_comparison_run_bindings", validate)
    create_managed_paired_quality_projection_input(
        bindings=bindings,
        case_manifest=manifest,
        case_manifest_sha256=execution_case_manifest_sha256(manifest),
        outcomes=_proofs(
            bindings,
            (
                ("case-a", "infinity-context", "correct", 1.0),
                ("case-a", "mem0", "incorrect", 0.0),
            ),
        ),
    )
    assert calls == [bindings]


def test_managed_run_wires_sealed_proofs_to_safe_public_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _run(_rig(), monkeypatch)
    report = public_managed_run(outcome)

    assert report["paired_quality"]["backends"]["memo_stack"] == {
        "total": 2,
        "correct": 2,
        "accuracy": 1.0,
    }
    assert report["paired_quality"]["paired"] == {
        "memo_stack_win_count": 2,
        "tie_count": 0,
        "mem0_win_count": 0,
        "accuracy_delta": 1.0,
    }
    rendered = json.dumps(report, sort_keys=True)
    assert "question 1" not in rendered
    assert "answer 1" not in rendered
    assert "case-1" not in rendered

    state = managed._OUTCOMES[outcome]
    projection_state = quality._PROJECTIONS[state.quality_projection]
    object.__setattr__(projection_state.outcomes[0], "score", 0.0)
    with pytest.raises(ManagedRunError, match="managed paired quality projection changed"):
        public_managed_run(outcome)
