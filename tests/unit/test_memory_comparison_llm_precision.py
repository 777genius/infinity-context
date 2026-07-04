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
                "answer_context_bundle_source_type_diversity": 3,
                "answer_context_bundle_retrieval_source_diversity": 4,
                "answer_context_bundle_source_type_support_diversity": 1,
                "answer_context_bundle_retrieval_source_support_diversity": 2,
                "answer_context_bundle_source_ref_support_item_count": 1,
                "answer_context_bundle_source_identity_support_item_count": 2,
                "answer_context_bundle_source_chain_proximity_support_count": 1,
                "answer_context_bundle_source_chain_proximity_closest_distance": 2,
            },
        ),
        index=1,
    )

    assert "source_type=raw_turn" in line
    assert "source_types=raw_turn,chunk" in line
    assert "retrieval_sources=raw_turns,semantic_chunks" in line
    assert "bundle_sources=types:1,retrieval:2" in line
    assert "bundle_sources=types:3,retrieval:4" not in line
    assert "bundle_source_ref_support=1" in line
    assert "bundle_source_identity_support=2" in line
    assert "bundle_chain_proximity=1" in line
    assert "bundle_chain_proximity_closest=2" in line
    assert "refs=D4:2" in line


def test_llm_memory_line_suppresses_raw_source_diversity_when_support_is_zero() -> None:
    line = _render_memory_evidence_line(
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=2,
            source_refs=("D4:2",),
            metadata={
                "answer_context_bundle_source_type_diversity": 3,
                "answer_context_bundle_retrieval_source_diversity": 4,
                "answer_context_bundle_source_type_support_diversity": 0,
                "answer_context_bundle_retrieval_source_support_diversity": 0,
            },
        ),
        index=1,
    )

    assert "bundle_sources=" not in line
    assert "bundle_sources=types:3,retrieval:4" not in line


def test_llm_memory_line_renders_backfill_skip_diagnostics() -> None:
    line = _render_memory_evidence_line(
        RetrievedMemory(
            text="D2:12 Morgan: The class registration email arrived.",
            rank=3,
            source_refs=("D2:12",),
            metadata={
                "answer_context_role": "retrieval_backfill",
                "answer_context_skipped_redundant_risky_backfill_count": 1,
                "answer_context_skipped_redundant_source_backfill_count": 2,
                "answer_context_skipped_redundant_role_backfill_count": 3,
            },
        ),
        index=2,
    )

    assert "backfill_skipped=risky:1,source:2,role:3" in line


def test_llm_memory_line_merges_bundle_and_item_risk_reasons() -> None:
    line = _render_memory_evidence_line(
        RetrievedMemory(
            text="D2:12 Morgan: The class registration email arrived.",
            rank=3,
            source_refs=("D2:12",),
            metadata={
                "answer_context_role": "retrieval_backfill",
                "answer_context_bundle_risk_reason_codes": (
                    "risk:missing_required_role",
                    "risk:missing_required_contrast",
                ),
                "answer_context_risk_reason_codes": (
                    "risk:missing_required_role",
                    "risk:retrieval_backfill",
                    "risk:skipped_redundant_source_backfill",
                ),
            },
        ),
        index=2,
    )

    assert (
        "risks=risk:missing_required_role,risk:missing_required_contrast,"
        "risk:retrieval_backfill,risk:skipped_redundant_source_backfill"
    ) in line
