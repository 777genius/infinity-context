"""Gold-free request DTO for ranked-evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


@dataclass(frozen=True, slots=True)
class RankedEvidenceRetrievalRequest:
    """Question-side fields allowed to cross the retrieval request boundary."""

    question: str
    memory_scope_external_ref: str
    thread_external_ref: str


def ranked_evidence_retrieval_request(
    case: PublicBenchmarkCase,
) -> RankedEvidenceRetrievalRequest:
    """Copy only retrieval inputs, structurally excluding evaluator metadata."""

    return RankedEvidenceRetrievalRequest(
        question=case.question,
        memory_scope_external_ref=(
            case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
        ),
        thread_external_ref=(case.thread_external_ref or f"{case.benchmark}-{case.case_id}"),
    )


__all__ = (
    "RankedEvidenceRetrievalRequest",
    "ranked_evidence_retrieval_request",
)
