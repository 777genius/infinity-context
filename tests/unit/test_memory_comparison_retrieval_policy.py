from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest
from infinity_context_server.memory_comparison_retrieval_policy import (
    INFINITY_TUNED_RETRIEVAL_POLICY,
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
    disabled_postprocessing_telemetry,
)


def test_neutral_policy_disables_backend_specific_postprocessing() -> None:
    assert NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry() == {
        "policy_id": "neutral-retrieval-v1",
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "single_pass_retrieval": True,
        "mirror_memories_as_documents": False,
        "candidate_fusion": False,
        "temporal_rerank": False,
        "benchmark_rerank": False,
        "publication_lane": "neutral_head_to_head",
    }
    assert disabled_postprocessing_telemetry(
        stage="temporal_rerank",
        policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
    ) == {
        "applied": False,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "stage": "temporal_rerank",
        "reason": "disabled_by_retrieval_policy",
        "policy_id": "neutral-retrieval-v1",
    }


def test_retrieval_policies_are_immutable_contracts() -> None:
    with pytest.raises(FrozenInstanceError):
        INFINITY_TUNED_RETRIEVAL_POLICY.single_pass_retrieval = False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("policy_id", ""),
        ("publication_lane", " lane "),
        ("single_pass_retrieval", 1),
        ("apply_temporal_rerank", "false"),
    ),
)
def test_retrieval_policy_rejects_non_json_or_coerced_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        replace(NEUTRAL_COMPARISON_RETRIEVAL_POLICY, **{field: value})


@pytest.mark.parametrize("stage", ("", " stage ", "x" * 129, True))
def test_disabled_stage_telemetry_requires_exact_bounded_string(stage: object) -> None:
    with pytest.raises(ValueError):
        disabled_postprocessing_telemetry(
            stage=stage,  # type: ignore[arg-type]
            policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        )


def test_policy_artifacts_are_strict_json() -> None:
    json.dumps(
        NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
        allow_nan=False,
        sort_keys=True,
    )
