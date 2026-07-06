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


def test_benchmark_rerank_does_not_boost_generic_source_ref_for_dialogue_support() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex's move to Denver?",
        metadata={"category": 4},
    )
    generic_source = RetrievedMemory(
        item_id="generic-source",
        rank=1,
        score=0.05,
        text="Alex moved to Denver after the promotion.",
        source_refs=("document:profile-note",),
    )
    grounded_source = RetrievedMemory(
        item_id="grounded-source",
        rank=2,
        score=0.0,
        text="D1:2 Jamie: Alex moved to Denver after the promotion.",
        source_refs=("locomo:conv-26:session_1:D1:2:turn",),
    )

    reranked, _ = benchmark_rerank_memories(case, (generic_source, grounded_source))

    assert [memory.item_id for memory in reranked] == [
        "grounded-source",
        "generic-source",
    ]
    generic_signals = reranked[1].metadata["diagnostics"]["score_signals"]
    assert generic_signals["benchmark_source_grounding_evidence"] is False
    assert generic_signals["benchmark_source_grounding_boost"] == 0.0
    assert generic_signals["benchmark_source_grounding_ungrounded_penalty"] == -0.08


def test_benchmark_rerank_uses_structured_turn_payload_for_source_grounding() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Riley confirming the studio visit?",
        metadata={"category": 4},
    )
    ungrounded_answer = RetrievedMemory(
        item_id="ungrounded-answer",
        rank=1,
        score=0.05,
        text="Riley confirmed the studio visit.",
    )
    structured_source = RetrievedMemory(
        item_id="structured-source",
        rank=2,
        score=0.0,
        text="Riley confirmed the studio visit.",
        metadata={
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "source_dialogue_index": "D12",
                    "source_turn_index": "6",
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(
        case,
        (ungrounded_answer, structured_source),
    )

    by_id = {memory.item_id: memory for memory in reranked}
    structured_signals = by_id["structured-source"].metadata["diagnostics"][
        "score_signals"
    ]
    ungrounded_signals = by_id["ungrounded-answer"].metadata["diagnostics"][
        "score_signals"
    ]
    assert structured_signals["benchmark_source_grounding_support"] is True
    assert structured_signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_match"
    )
    assert ungrounded_signals["benchmark_source_grounding_support"] is False
    assert ungrounded_signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_answer_without_source"
    )


def test_benchmark_rerank_uses_locomo_evidence_ref_for_source_grounding() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex confirming the workshop date?",
        metadata={"category": 4},
    )
    structured_source = RetrievedMemory(
        item_id="locomo-evidence-ref-source",
        rank=1,
        score=0.0,
        text="Alex confirmed the workshop date.",
        metadata={
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "locomo_evidence_ref": "D4:5",
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(case, (structured_source,))

    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_source_grounding_support"] is True
    assert signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_match"
    )


def test_benchmark_rerank_uses_source_evidence_refs_for_source_grounding() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex confirming the workshop date?",
        metadata={"category": 4},
    )
    structured_source = RetrievedMemory(
        item_id="source-evidence-refs-source",
        rank=1,
        score=0.0,
        text="Alex confirmed the workshop date.",
        metadata={
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "source_evidence_refs": ("locomo:conv-private:D4:5",),
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(case, (structured_source,))

    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_source_grounding_support"] is True
    assert signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_match"
    )


def test_benchmark_rerank_uses_supporting_evidence_for_source_grounding() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex confirming the workshop date?",
        metadata={"category": 4},
    )
    structured_source = RetrievedMemory(
        item_id="supporting-evidence-source",
        rank=1,
        score=0.0,
        text="Alex confirmed the workshop date.",
        metadata={
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "supporting_evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(case, (structured_source,))

    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_source_grounding_support"] is True
    assert signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_match"
    )


def test_benchmark_rerank_uses_nested_evidence_for_source_grounding() -> None:
    case = SimpleNamespace(
        question="Which dialogue supports Alex confirming the workshop date?",
        metadata={"category": 4},
    )
    structured_source = RetrievedMemory(
        item_id="nested-evidence-source",
        rank=1,
        score=0.0,
        text="Alex confirmed the workshop date.",
        metadata={
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(case, (structured_source,))

    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_source_grounding_support"] is True
    assert signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_match"
    )


def test_benchmark_rerank_penalizes_unrelated_source_quote() -> None:
    case = SimpleNamespace(
        question="Which source supports Alex's move to Denver?",
        metadata={"category": 4},
    )
    unrelated_quote = RetrievedMemory(
        item_id="unrelated-quote",
        rank=1,
        score=0.05,
        text="Alex moved to Denver after the promotion.",
        source_refs=("document:profile-note",),
        metadata={
            "source_refs": [
                {
                    "source_type": "document",
                    "source_id": "document:profile-note",
                    "quote_preview": "Jamie said the promotion timing was complicated.",
                }
            ]
        },
    )
    relevant_quote = RetrievedMemory(
        item_id="relevant-quote",
        rank=2,
        score=0.0,
        text="Alex moved to Denver after the promotion.",
        source_refs=("document:profile-note-2",),
        metadata={
            "source_refs": [
                {
                    "source_type": "document",
                    "source_id": "document:profile-note-2",
                    "quote_preview": "Jamie said Alex moved to Denver after the promotion.",
                }
            ]
        },
    )

    reranked, _ = benchmark_rerank_memories(case, (unrelated_quote, relevant_quote))

    assert [memory.item_id for memory in reranked] == [
        "relevant-quote",
        "unrelated-quote",
    ]
    unrelated_signals = reranked[1].metadata["diagnostics"]["score_signals"]
    relevant_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert unrelated_signals["benchmark_source_grounding_support_reason"] == (
        "source_grounding_unrelated_quote"
    )
    assert unrelated_signals["benchmark_source_grounding_boost"] == 0.0
    assert relevant_signals["benchmark_source_grounding_evidence"] is True
    assert relevant_signals["benchmark_source_grounding_quote_relevant"] is True
