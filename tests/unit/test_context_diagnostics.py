from memo_stack_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)
from memo_stack_core.application.dto import ContextItem


def test_context_bundle_diagnostics_are_bounded_redacted_and_typed() -> None:
    item = ContextItem(
        item_id="chunk_contract",
        item_type="chunk",
        text="Contract diagnostics item.",
        score=0.9,
        source_refs=(),
        diagnostics={
            "retrieval_sources": [f"source_{index}" for index in range(12)],
            "retrieval_source": "source_extra",
        },
    )
    raw_diagnostics = {
        "context_assembly_version": "context-v2-hybrid-explainable",
        "consistency_mode": "best_effort",
        "hybrid_items_used": 2,
        "temporal_replacements_applied": 1,
        "stale_facts_considered": 3,
        "stale_facts_used": 1,
        "api_key": "SECRET_VALUE_SHOULD_NOT_LEAK",
        **{f"extra_{index}": "x" * 500 for index in range(80)},
    }

    diagnostics = normalize_context_bundle_diagnostics(
        raw_diagnostics,
        items=(item,),
    )

    assert diagnostics["context_assembly_version"] == "context-v2-hybrid-explainable"
    assert diagnostics["consistency_mode"] == "best_effort"
    assert diagnostics["retrieval_sources_used"] == [f"source_{index}" for index in range(8)]
    assert diagnostics["hybrid_items_used"] == 2
    assert diagnostics["temporal_replacements_applied"] == 1
    assert diagnostics["stale_facts_considered"] == 3
    assert diagnostics["stale_facts_used"] == 1
    assert diagnostics["diagnostics_truncated"] is True
    assert "api_key" not in diagnostics
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in str(diagnostics)


def test_context_bundle_retrieval_sources_use_stable_priority_order() -> None:
    keyword = ContextItem(
        item_id="chunk_keyword",
        item_type="chunk",
        text="Keyword item.",
        score=0.8,
        source_refs=(),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    vector = ContextItem(
        item_id="chunk_vector",
        item_type="chunk",
        text="Vector item.",
        score=0.7,
        source_refs=(),
        diagnostics={"retrieval_source": "vector_chunks"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(keyword, vector),
    )

    assert diagnostics["retrieval_sources_used"] == ["vector_chunks", "keyword_chunks"]


def test_context_bundle_retrieval_sources_prioritize_rag_over_keyword() -> None:
    keyword = ContextItem(
        item_id="chunk_keyword",
        item_type="chunk",
        text="Keyword item.",
        score=0.9,
        source_refs=(),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    rag = ContextItem(
        item_id="chunk_rag",
        item_type="chunk",
        text="RAG item.",
        score=0.8,
        source_refs=(),
        diagnostics={"retrieval_source": "rag_recall"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(keyword, rag),
    )

    assert diagnostics["retrieval_sources_used"] == ["rag_recall", "keyword_chunks"]
