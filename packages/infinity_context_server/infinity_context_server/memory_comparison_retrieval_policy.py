"""Immutable retrieval policies for fair memory-system comparisons."""

from __future__ import annotations

from dataclasses import dataclass

NEUTRAL_RETRIEVAL_POLICY_ID = "neutral-retrieval-v1"
INFINITY_TUNED_RETRIEVAL_POLICY_ID = "infinity-tuned-retrieval-v1"


@dataclass(frozen=True)
class ComparisonRetrievalPolicy:
    """Harness behavior kept separate from provider retrieval implementations."""

    policy_id: str
    single_pass_retrieval: bool
    mirror_memories_as_documents: bool
    apply_candidate_fusion: bool
    apply_temporal_rerank: bool
    apply_benchmark_rerank: bool
    publication_lane: str

    def __post_init__(self) -> None:
        for name in ("policy_id", "publication_lane"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} must be a bounded non-empty string")
        for name in (
            "single_pass_retrieval",
            "mirror_memories_as_documents",
            "apply_candidate_fusion",
            "apply_temporal_rerank",
            "apply_benchmark_rerank",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an exact boolean")

    def telemetry(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "publishable": False,
            "publication_status": "pending_composite_wiring",
            "publication_blockers": [
                "retrieval_completeness_not_composed",
                "session_isolation_not_composed",
            ],
            "single_pass_retrieval": self.single_pass_retrieval,
            "mirror_memories_as_documents": self.mirror_memories_as_documents,
            "candidate_fusion": self.apply_candidate_fusion,
            "temporal_rerank": self.apply_temporal_rerank,
            "benchmark_rerank": self.apply_benchmark_rerank,
            "publication_lane": self.publication_lane,
        }


NEUTRAL_COMPARISON_RETRIEVAL_POLICY = ComparisonRetrievalPolicy(
    policy_id=NEUTRAL_RETRIEVAL_POLICY_ID,
    single_pass_retrieval=True,
    mirror_memories_as_documents=False,
    apply_candidate_fusion=False,
    apply_temporal_rerank=False,
    apply_benchmark_rerank=False,
    publication_lane="neutral_head_to_head",
)

INFINITY_TUNED_RETRIEVAL_POLICY = ComparisonRetrievalPolicy(
    policy_id=INFINITY_TUNED_RETRIEVAL_POLICY_ID,
    single_pass_retrieval=True,
    mirror_memories_as_documents=True,
    apply_candidate_fusion=True,
    apply_temporal_rerank=True,
    apply_benchmark_rerank=True,
    publication_lane="system_tuned_vs_mem0",
)


def disabled_postprocessing_telemetry(
    *,
    stage: str,
    policy: ComparisonRetrievalPolicy,
) -> dict[str, object]:
    """Return an explicit non-applied stage verdict for report contracts."""

    if type(stage) is not str or not stage or stage != stage.strip() or len(stage) > 128:
        raise ValueError("stage must be a bounded non-empty string")

    return {
        "applied": False,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "stage": stage,
        "reason": "disabled_by_retrieval_policy",
        "policy_id": policy.policy_id,
    }


__all__ = (
    "ComparisonRetrievalPolicy",
    "INFINITY_TUNED_RETRIEVAL_POLICY",
    "INFINITY_TUNED_RETRIEVAL_POLICY_ID",
    "NEUTRAL_COMPARISON_RETRIEVAL_POLICY",
    "NEUTRAL_RETRIEVAL_POLICY_ID",
    "disabled_postprocessing_telemetry",
)
