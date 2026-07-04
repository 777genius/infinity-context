from __future__ import annotations

import infinity_context_server.memory_comparison_rerank as rerank_module
from infinity_context_server.memory_comparison_evidence import evidence_bundle
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    PublicBenchmarkCase,
)


def test_query_decomposition_marks_no_longer_question_as_negative_support() -> None:
    case = _case(
        case_id="no-longer-provider-query-plan",
        question="Which Atlas provider is no longer valid?",
        expected_terms=("LocalAI",),
        answer="LocalAI",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]

    assert "negative_absence" in query_profile["evidence_need"]
    assert "negative_support" in query_profile["bundle_evidence_roles"]
    assert "negative_support" in metadata["query_plan"]["selected_roles"]
    assert any("no longer" in query for query in queries)


def test_negative_absence_rerank_prefers_no_longer_evidence_over_positive_topic() -> None:
    case = _case(
        case_id="no-longer-provider-rerank",
        question="Which Atlas provider is no longer valid?",
        expected_terms=("LocalAI",),
        answer="LocalAI",
    )
    positive_topic = RetrievedMemory(
        item_id="positive-topic",
        rank=1,
        score=0.0,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Atlas uses LocalAI as a valid provider."
        ),
        source_refs=("D1:1",),
    )
    no_longer_evidence = RetrievedMemory(
        item_id="no-longer-evidence",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:05 am "
            "D1:2 LocalAI is no longer valid for Atlas after the switch."
        ),
        source_refs=("D1:2",),
    )

    reranked, _metadata = rerank_module.benchmark_rerank_memories(
        case,
        (positive_topic, no_longer_evidence),
    )

    assert reranked[0].item_id == "no-longer-evidence"
    negative_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    positive_signals = reranked[1].metadata["diagnostics"]["score_signals"]
    assert negative_signals["benchmark_negative_absence_support_boost"] > 0
    assert (
        positive_signals["benchmark_negative_absence_positive_topic_penalty"]
        < 0
    )


def test_evidence_bundle_requires_negative_support_for_no_longer_question() -> None:
    case = _case(
        case_id="no-longer-provider-bundle",
        question="Which Atlas provider is no longer valid?",
        expected_terms=("LocalAI",),
        answer="LocalAI",
    )
    memories, _metadata = rerank_module.benchmark_rerank_memories(
        case,
        (
            RetrievedMemory(
                item_id="positive-topic",
                rank=1,
                score=0.0,
                text=(
                    "session_1 turn D1:1 date: 10:00 am "
                    "D1:1 Atlas uses LocalAI as a valid provider."
                ),
                source_refs=("D1:1",),
            ),
            RetrievedMemory(
                item_id="no-longer-evidence",
                rank=2,
                score=0.0,
                text=(
                    "session_1 turn D1:2 date: 10:05 am "
                    "D1:2 LocalAI is no longer valid for Atlas after the switch."
                ),
                source_refs=("D1:2",),
            ),
        ),
    )

    bundle = evidence_bundle(case, memories)

    assert "negative_support" in bundle["required_roles"]
    assert "negative_support" in bundle["satisfied_required_roles"]
    items_by_id = {item["id"]: item for item in bundle["items"]}
    assert items_by_id["no-longer-evidence"]["role"] == "negative_support"


def test_negative_absence_support_accepts_has_no_evidence() -> None:
    case = _case(
        case_id="has-no-provider-bundle",
        question="Which Atlas provider has no valid API key?",
        expected_terms=("LocalAI",),
        answer="LocalAI",
    )
    memories, _metadata = rerank_module.benchmark_rerank_memories(
        case,
        (
            RetrievedMemory(
                item_id="positive-topic",
                rank=1,
                score=0.0,
                text=(
                    "session_1 turn D1:1 date: 10:00 am "
                    "D1:1 Atlas lists LocalAI as a provider."
                ),
                source_refs=("D1:1",),
            ),
            RetrievedMemory(
                item_id="has-no-evidence",
                rank=2,
                score=0.0,
                text=(
                    "session_1 turn D1:2 date: 10:05 am "
                    "D1:2 LocalAI has no valid API key for Atlas."
                ),
                source_refs=("D1:2",),
            ),
        ),
    )

    bundle = evidence_bundle(case, memories)

    assert memories[0].item_id == "has-no-evidence"
    assert "negative_support" in bundle["required_roles"]
    assert "negative_support" in bundle["satisfied_required_roles"]
    items_by_id = {item["id"]: item for item in bundle["items"]}
    assert items_by_id["has-no-evidence"]["negation_surface"] is True
    assert (
        bundle["bundle_planner"]["bundle_quality"]["negative_absence_support_count"]
        == 1
    )


def _case(
    *,
    case_id: str,
    question: str,
    expected_terms: tuple[str, ...],
    answer: str,
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        documents=(
            BenchmarkDocumentInput(
                title="Conversation",
                text=f"Alex said: {answer}",
                source_external_id="conv-1-doc",
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4, "answer_preview": answer},
    )
