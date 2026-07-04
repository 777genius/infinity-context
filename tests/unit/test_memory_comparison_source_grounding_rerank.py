from __future__ import annotations

from types import SimpleNamespace

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import benchmark_rerank_memories


def test_benchmark_rerank_prefers_source_grounded_dialogue_evidence() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex's move to Denver?",
        metadata={"category": 4},
    )
    plausible_answer = RetrievedMemory(
        item_id="plausible-answer",
        rank=1,
        score=0.05,
        text="Alex moved to Denver after the promotion.",
    )
    grounded_source = RetrievedMemory(
        item_id="grounded-source",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 9:00 am "
            "D1:2 Jamie: Alex moved to Denver after the promotion."
        ),
        source_refs=("locomo:conv-26:session_1:D1:2:turn",),
    )

    reranked, metadata = benchmark_rerank_memories(
        case,
        (plausible_answer, grounded_source),
    )

    assert metadata["query_profile"]["source_grounding_query"] is True
    assert [memory.item_id for memory in reranked] == [
        "grounded-source",
        "plausible-answer",
    ]
    grounded_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert grounded_signals["benchmark_source_grounding_evidence"] is True
    assert grounded_signals["benchmark_source_grounding_boost"] > 0
