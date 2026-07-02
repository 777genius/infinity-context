from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_fusion import fuse_query_results
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_candidate_fusion_promotes_repeated_cross_query_evidence() -> None:
    distractor = RetrievedMemory(
        item_id="generic-career",
        rank=1,
        score=0.9,
        text="Caroline mentioned counseling as a possible career.",
        metadata={"item_type": "fact"},
    )
    evidence_semantic = RetrievedMemory(
        item_id="received-support",
        rank=2,
        score=0.84,
        text="Caroline received support growing up and pursued counseling.",
        metadata={
            "item_type": "chunk",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    evidence_keyword = RetrievedMemory(
        item_id="received-support",
        rank=1,
        score=0.84,
        text="Caroline received support growing up and pursued counseling.",
        metadata={
            "item_type": "chunk",
            "diagnostics": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
    evidence_turn = RetrievedMemory(
        item_id="received-support",
        rank=1,
        score=0.84,
        text="Caroline received support growing up and pursued counseling.",
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (
            ("original", (distractor, evidence_semantic)),
            ("focused", (evidence_keyword,)),
            ("compact", (evidence_turn,)),
        )
    )

    assert [memory.item_id for memory in fused] == [
        "received-support",
        "generic-career",
    ]
    assert diagnostics["schema_version"] == "candidate_fusion.v1"
    assert diagnostics["raw_result_count"] == 4
    assert diagnostics["unique_result_count"] == 2
    assert diagnostics["multi_query_hit_count"] == 1
    fused_diagnostics = fused[0].metadata["diagnostics"]
    fusion = fused_diagnostics["benchmark_candidate_fusion"]
    assert fusion["query_match_count"] == 3
    assert fusion["source_diversity_count"] >= 3
    assert fused_diagnostics["benchmark_query_indices"] == [1, 2, 3]
    assert fused_diagnostics["score_signals"]["benchmark_candidate_fusion_boost"] > 0
    assert fused_diagnostics["score_signals"]["benchmark_rrf_fusion_boost"] > 0


def test_candidate_fusion_dedupes_order_insensitive_source_refs() -> None:
    first = RetrievedMemory(
        rank=1,
        score=0.7,
        text="D2:8 Caroline looked into adoption agencies.",
        source_refs=("session-2", "D2:8"),
    )
    stronger = RetrievedMemory(
        rank=1,
        score=0.72,
        text="D2:8 Caroline looked into adoption agencies.",
        source_refs=("D2:8", "session-2"),
    )

    fused, diagnostics = fuse_query_results(
        (("original", (first,)), ("focused", (stronger,)))
    )

    assert len(fused) == 1
    assert fused[0].score > 0.72
    assert diagnostics["duplicate_result_count"] == 1
    assert fused[0].metadata["diagnostics"]["benchmark_query_match_count"] == 2


def test_candidate_fusion_preserves_non_winning_source_refs() -> None:
    semantic_winner = RetrievedMemory(
        item_id="adoption-support",
        rank=1,
        score=0.91,
        text="D2:8 Caroline looked into adoption agencies.",
        source_refs=("chunk-ref",),
        metadata={
            "item_type": "chunk",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    raw_turn = RetrievedMemory(
        item_id="adoption-support",
        rank=2,
        score=0.82,
        text="D2:8 Caroline looked into adoption agencies.",
        source_refs=("D2:8",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (("semantic", (semantic_winner,)), ("raw-turn", (raw_turn,)))
    )

    assert len(fused) == 1
    assert diagnostics["duplicate_result_count"] == 1
    assert fused[0].source_refs == ("chunk-ref", "D2:8")
    fusion = fused[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["source_refs"] == ["chunk-ref", "D2:8"]
    assert fusion["source_types"] == ["chunk", "raw_turn"]
    assert fusion["retrieval_sources"] == ["semantic_chunks", "raw_turns"]


def test_candidate_fusion_merges_distinct_ids_for_same_precise_turn_ref() -> None:
    chunk = RetrievedMemory(
        item_id="chunk-123",
        rank=2,
        score=0.82,
        text="Caroline looked into adoption agencies.",
        source_refs=("locomo:conv-26:session_2:D2:8:chunk",),
        metadata={
            "item_type": "chunk",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    raw_turn = RetrievedMemory(
        item_id="raw-turn-456",
        rank=1,
        score=0.79,
        text="D2:8 Caroline: I looked into adoption agencies.",
        source_refs=("locomo:conv-26:session_2:D2:8:turn",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (("semantic", (chunk,)), ("raw-turn", (raw_turn,)))
    )

    assert len(fused) == 1
    assert diagnostics["duplicate_result_count"] == 1
    assert fused[0].item_id == "chunk-123"
    assert fused[0].score > chunk.score
    fusion = fused[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["dedupe_key"] == "turn_refs:D2:8"
    assert fusion["source_refs"] == [
        "locomo:conv-26:session_2:D2:8:chunk",
        "locomo:conv-26:session_2:D2:8:turn",
    ]
    assert fusion["source_types"] == ["chunk", "raw_turn"]


def test_candidate_fusion_selects_local_evidence_within_score_band() -> None:
    broad_chunk = RetrievedMemory(
        item_id="adoption-support",
        rank=1,
        score=0.82,
        text=(
            "Summary: Caroline discussed adoption agencies, family goals, "
            "paperwork, support, and follow-up plans."
        ),
        source_refs=("D2:8", "D2:9", "D2:10", "D2:11"),
        metadata={
            "item_type": "chunk",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    raw_turn = RetrievedMemory(
        item_id="adoption-support",
        rank=2,
        score=0.805,
        text="D2:9 Caroline: I found an adoption agency that can help.",
        source_refs=("D2:9",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (("semantic", (broad_chunk,)), ("raw-turn", (raw_turn,)))
    )

    assert len(fused) == 1
    assert diagnostics["duplicate_result_count"] == 1
    assert diagnostics["lower_score_evidence_selection_count"] == 1
    assert diagnostics["source_type_evidence_selection_count"] == 1
    assert diagnostics["focused_query_evidence_selection_count"] == 0
    assert fused[0].text == raw_turn.text
    assert fused[0].score > broad_chunk.score
    assert fused[0].source_refs == ("D2:9", "D2:8", "D2:10", "D2:11")
    fusion = fused[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["winner_score"] == 0.82
    assert fusion["score_winner_source_type"] == "chunk"
    assert fusion["selected_evidence_score"] == 0.805
    assert fusion["selected_evidence_source_type"] == "raw_turn"


def test_candidate_fusion_prefers_focused_query_evidence_within_score_band() -> None:
    generic_hit = RetrievedMemory(
        item_id="move-evidence",
        rank=1,
        score=0.82,
        text="D3:4 Morgan talked about moving plans after work.",
        source_refs=("D3:4",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    focused_hit = RetrievedMemory(
        item_id="move-evidence",
        rank=2,
        score=0.81,
        text="D3:4 Morgan moved from Boston to Denver for work.",
        source_refs=("D3:4",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (("original", (generic_hit,)), ("location-support", (focused_hit,))),
        query_roles=("original_question", "location_support"),
    )

    assert len(fused) == 1
    assert diagnostics["duplicate_result_count"] == 1
    assert diagnostics["lower_score_evidence_selection_count"] == 1
    assert diagnostics["source_type_evidence_selection_count"] == 0
    assert diagnostics["focused_query_evidence_selection_count"] == 1
    assert fused[0].text == focused_hit.text
    assert fused[0].score > generic_hit.score
    fusion = fused[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["score_winner_query_role"] == "original_question"
    assert fusion["selected_evidence_query_role"] == "location_support"


def test_candidate_fusion_prefers_typed_relation_support_evidence() -> None:
    generic_hit = RetrievedMemory(
        item_id="exchange-evidence",
        rank=1,
        score=0.82,
        text="D19:2 Melanie mentioned a fair and some shopping.",
        source_refs=("D19:2",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["semantic_chunks"]},
        },
    )
    exchange_hit = RetrievedMemory(
        item_id="exchange-evidence",
        rank=2,
        score=0.81,
        text="D19:2 Melanie: I bought a small keepsake after the fair.",
        source_refs=("D19:2",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"retrieval_sources": ["raw_turns"]},
        },
    )

    fused, diagnostics = fuse_query_results(
        (("original", (generic_hit,)), ("exchange", (exchange_hit,))),
        query_roles=("original_question", "exchange_support"),
    )

    assert len(fused) == 1
    assert diagnostics["focused_query_evidence_selection_count"] == 1
    assert diagnostics["query_role_counts"] == {
        "exchange_support": 1,
        "original_question": 1,
    }
    assert fused[0].text == exchange_hit.text
    fusion = fused[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["score_winner_query_role"] == "original_question"
    assert fusion["selected_evidence_query_role"] == "exchange_support"


def test_candidate_fusion_keeps_broad_source_ref_sets_separate() -> None:
    summary = RetrievedMemory(
        item_id="summary",
        rank=1,
        score=0.9,
        text="Summary mentioning several turns.",
        source_refs=("D1:1", "D1:2", "D1:3", "D1:4"),
    )
    turn = RetrievedMemory(
        item_id="turn",
        rank=2,
        score=0.85,
        text="D1:1 Morgan: I made the checklist.",
        source_refs=("D1:1",),
    )

    fused, diagnostics = fuse_query_results(
        (("summary", (summary,)), ("turn", (turn,)))
    )

    assert len(fused) == 2
    assert diagnostics["duplicate_result_count"] == 0
    assert [memory.item_id for memory in fused] == ["summary", "turn"]


def test_candidate_fusion_leaves_single_query_candidates_unboosted() -> None:
    memory = RetrievedMemory(
        item_id="single",
        rank=1,
        score=0.8,
        text="Single query hit.",
    )

    fused, diagnostics = fuse_query_results((("original", (memory,)),))

    assert fused == [memory]
    assert diagnostics["multi_query_hit_count"] == 0


def test_candidate_fusion_records_query_role_provenance_without_single_query_boost() -> None:
    memory = RetrievedMemory(
        item_id="bridge-only",
        rank=1,
        score=0.8,
        text="D2:3 Caroline got support while choosing the agency.",
    )

    fused, diagnostics = fuse_query_results(
        (("caroline agency reason support", (memory,)),),
        query_roles=("multi_hop_bridge",),
    )

    assert fused[0].score == 0.8
    assert diagnostics["multi_query_hit_count"] == 0
    assert diagnostics["query_role_counts"] == {"multi_hop_bridge": 1}
    assert diagnostics["bridge_query_hit_count"] == 1
    fused_diagnostics = fused[0].metadata["diagnostics"]
    assert fused_diagnostics["benchmark_query_roles"] == ["multi_hop_bridge"]
    assert fused_diagnostics["benchmark_bridge_query_hit"] is True
    assert (
        fused_diagnostics["benchmark_candidate_fusion"]["query_role_counts"]
        == {"multi_hop_bridge": 1}
    )
    assert "benchmark_candidate_fusion_boost" not in fused_diagnostics["score_signals"]
