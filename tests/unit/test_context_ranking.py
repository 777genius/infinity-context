from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import (
    apply_bm25_lexical_boosts,
    apply_query_plan_bm25_lexical_boosts,
    apply_rank_fusion_boosts,
    reciprocal_rank_fusion_scores,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_reciprocal_rank_fusion_scores_combine_ordered_sources() -> None:
    top = _item("top", score=0.8, retrieval_source="keyword_chunks")
    mid = _item("mid", score=0.7, retrieval_source="keyword_chunks")
    low = _item("low", score=0.6, retrieval_source="keyword_chunks")

    scores = reciprocal_rank_fusion_scores(
        {
            "keyword_chunks": (top, mid, low),
            "vector_chunks": (top, low, mid),
        }
    )

    assert scores[("chunk", "top")] > scores[("chunk", "mid")]
    assert scores[("chunk", "top")] > scores[("chunk", "low")]


def test_reciprocal_rank_fusion_deduplicates_within_source() -> None:
    top = _item("top", score=0.8, retrieval_source="keyword_chunks")
    low = _item("low", score=0.6, retrieval_source="keyword_chunks")

    duplicate_scores = reciprocal_rank_fusion_scores(
        {"keyword_chunks": (top, top, low)}
    )
    unique_scores = reciprocal_rank_fusion_scores({"keyword_chunks": (top, low)})

    assert duplicate_scores[("chunk", "top")] == unique_scores[("chunk", "top")]


def test_rank_fusion_boost_requires_multiple_retrieval_sources() -> None:
    only_keyword = (
        _item("top", score=0.8, retrieval_source="keyword_chunks"),
        _item("low", score=0.6, retrieval_source="keyword_chunks"),
    )

    boosted = apply_rank_fusion_boosts(only_keyword)

    assert boosted == only_keyword


def test_rank_fusion_boosts_multi_source_candidates_with_diagnostics() -> None:
    keyword_top = _item("shared", score=0.8, retrieval_source="keyword_chunks")
    keyword_low = _item("keyword_low", score=0.6, retrieval_source="keyword_chunks")
    vector_top = _item("shared", score=0.82, retrieval_source="vector_chunks")
    vector_low = _item("vector_low", score=0.61, retrieval_source="vector_chunks")

    boosted = apply_rank_fusion_boosts(
        (keyword_top, keyword_low, vector_top, vector_low),
        max_boost=0.04,
    )

    shared_keyword = boosted[0]
    shared_vector = boosted[2]
    assert shared_keyword.score > keyword_top.score
    assert shared_vector.score > vector_top.score
    assert shared_keyword.score <= keyword_top.score + 0.04
    assert shared_keyword.diagnostics["score_signals"]["rank_fusion_boost"] <= 0.04
    assert shared_keyword.diagnostics["provenance"]["rank_fusion_applied"] is True


def test_rank_fusion_does_not_apply_twice_to_same_candidate() -> None:
    keyword_top = _item("shared", score=0.8, retrieval_source="keyword_chunks")
    keyword_low = _item("keyword_low", score=0.6, retrieval_source="keyword_chunks")
    vector_top = _item("shared", score=0.82, retrieval_source="vector_chunks")

    first_pass = apply_rank_fusion_boosts(
        (keyword_top, keyword_low, vector_top),
        max_boost=0.04,
    )
    second_pass = apply_rank_fusion_boosts(first_pass, max_boost=0.04)

    assert second_pass[0].score == first_pass[0].score
    assert second_pass[2].score == first_pass[2].score


def test_bm25_lexical_boost_prefers_precise_multi_term_candidate() -> None:
    precise = _item(
        "precise",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex approved the Atlas launch checklist.",
    )
    loose = _item(
        "loose",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Alex discussed many unrelated launch ideas and launch notes, "
            "but there was no checklist reference."
        ),
    )

    boosted = apply_bm25_lexical_boosts(
        (precise, loose),
        query="Alex Atlas launch checklist",
        max_boost=0.04,
    )

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["bm25_lexical_boost"] <= 0.04
    assert boosted[0].diagnostics["score_signals"][
        "bm25_lexical_matched_term_count"
    ] == 4
    assert boosted[0].diagnostics["provenance"]["bm25_lexical_applied"] is True


def test_bm25_lexical_boost_skips_queries_without_terms() -> None:
    item = _item("only", score=0.7, retrieval_source="keyword_chunks")

    boosted = apply_bm25_lexical_boosts((item,), query="what and where")

    assert boosted == (item,)


def test_bm25_lexical_boost_does_not_apply_twice() -> None:
    first = _item(
        "first",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex approved the Atlas launch checklist.",
    )
    second = _item(
        "second",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="The billing export finished after lunch.",
    )

    first_pass = apply_bm25_lexical_boosts(
        (first, second),
        query="Alex Atlas launch checklist",
    )
    second_pass = apply_bm25_lexical_boosts(
        first_pass,
        query="Alex Atlas launch checklist",
    )

    assert second_pass[0].score == first_pass[0].score


def test_query_plan_bm25_lexical_boost_uses_best_decomposed_query() -> None:
    artifact = _item(
        "artifact",
        score=0.7,
        retrieval_source="artifact_evidence",
        text="Screenshot OCR detected text: Atlas launch deadline moved after Alex call.",
    )
    decoy = _item(
        "decoy",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex and Atlas were mentioned in a broad planning note.",
    )
    plan = build_query_expansion_plan(
        "What changed after the call with Alex about Atlas and what was written in the screenshot?"
    )

    boosted = apply_query_plan_bm25_lexical_boosts(
        (artifact, decoy),
        plan=plan,
        max_boost=0.04,
    )

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["bm25_lexical_query_reason"] == (
        "decomposition_artifact_evidence"
    )
    assert boosted[0].diagnostics["provenance"]["bm25_lexical_query_reason"] == (
        "decomposition_artifact_evidence"
    )


def _item(
    item_id: str,
    *,
    score: float,
    retrieval_source: str,
    text: str | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text or item_id,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": [retrieval_source]},
        },
    )
