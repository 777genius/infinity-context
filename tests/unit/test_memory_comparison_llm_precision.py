from __future__ import annotations

from infinity_context_server.memory_comparison_llm import _render_memory_evidence_line
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_llm_memory_line_renders_answer_context_source_attribution() -> None:
    line = _render_memory_evidence_line(
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=2,
            source_refs=("D4:2",),
            metadata={
                "answer_context_role": "primary",
                "answer_context_retrieval_order": 1,
                "answer_context_source_type": "raw_turn",
                "answer_context_source_types": ("raw_turn", "chunk"),
                "answer_context_retrieval_sources": (
                    "raw_turns",
                    "semantic_chunks",
                ),
                "answer_context_bundle_source_chain_proximity_support_count": 1,
                "answer_context_bundle_source_chain_proximity_closest_distance": 2,
            },
        ),
        index=1,
    )

    assert "source_type=raw_turn" in line
    assert "source_types=raw_turn,chunk" in line
    assert "retrieval_sources=raw_turns,semantic_chunks" in line
    assert "bundle_chain_proximity=1" in line
    assert "bundle_chain_proximity_closest=2" in line
    assert "refs=D4:2" in line
