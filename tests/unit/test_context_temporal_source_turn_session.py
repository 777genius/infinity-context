from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_temporal_query_boosts_explicit_session_bridge_match() -> None:
    intent = build_temporal_query_intent("What did Alex decide in session 4?")
    matched = _item(
        "locomo:conv-1:session_4:D4:7:turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_4 turn D4:7 Alex decided to wait for invoice approval.",
    )
    different_session = _item(
        "locomo:conv-1:session_3:D3:7:turn",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_3 turn D3:7 Alex was still evaluating invoice options.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (4,)
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score == 0.734
    assert by_id["locomo:conv-1:session_3:D3:7:turn"].score == 0.702
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score > by_id[
        "locomo:conv-1:session_3:D3:7:turn"
    ].score
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item matches it"
    assert by_id["locomo:conv-1:session_3:D3:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item has a different session"


def test_temporal_query_uses_hyphenated_dialogue_turn_for_session_match() -> None:
    intent = build_temporal_query_intent("What did Riley say in session 12?")
    matched = _item(
        "locomo-conv-1-D12-5-turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12-5 Riley said Morgan confirmed the studio visit.",
    )
    different_session = _item(
        "locomo-conv-1-D11-5-turn",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D11-5 Riley was still waiting for confirmation.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (12,)
    assert by_id["locomo-conv-1-D12-5-turn"].score == 0.734
    assert by_id["locomo-conv-1-D11-5-turn"].score == 0.702
    assert by_id["locomo-conv-1-D12-5-turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item matches it"


def test_temporal_query_uses_source_ref_turn_fields_for_session_match() -> None:
    intent = build_temporal_query_intent("What did Riley say in session 12?")
    quote_matched = ContextItem(
        item_id="quote_matched",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="D12:5 Riley said Morgan confirmed the studio visit.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    chunk_matched = ContextItem(
        item_id="chunk_matched",
        item_type="fact",
        text="Riley said the visit was still on.",
        score=0.69,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                chunk_id="locomo-conv-1-D12-6-turn",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_session = ContextItem(
        item_id="different_session",
        item_type="fact",
        text="Riley was still waiting for confirmation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="D11:5 Riley was still waiting for confirmation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, chunk_matched, quote_matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["quote_matched"].score == 0.734
    assert by_id["chunk_matched"].score == 0.724
    assert by_id["different_session"].score == 0.702
    assert by_id["quote_matched"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item matches it"
    )


def test_temporal_query_uses_nested_diagnostic_turn_refs_for_session_match() -> None:
    intent = build_temporal_query_intent("What did Riley say in session 12?")
    matched = ContextItem(
        item_id="nested_diagnostic_session_match",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "benchmark_candidate_features": {
                "source_turn_refs": ["D12:5"],
                "source_ref_dedupe_key": "source_turn_refs:D12:5",
            },
        },
    )
    different_session = ContextItem(
        item_id="nested_diagnostic_session_conflict",
        item_type="fact",
        text="Riley was still waiting for confirmation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "benchmark_candidate_features": {
                "source_turn_refs": ["D11:5"],
                "source_ref_dedupe_key": "source_turn_refs:D11:5",
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["nested_diagnostic_session_match"].score == 0.734
    assert by_id["nested_diagnostic_session_conflict"].score == 0.702


def test_temporal_query_uses_structured_diagnostic_turn_refs_for_session_match() -> None:
    intent = build_temporal_query_intent("What did Riley say in session 12?")
    matched = ContextItem(
        item_id="structured_diagnostic_session_match",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "benchmark_candidate_features": {
                "source_turn": {"dialogue_id": 12, "source_turn": 5},
            },
        },
    )
    different_session = ContextItem(
        item_id="structured_diagnostic_session_conflict",
        item_type="fact",
        text="Riley was still waiting for confirmation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "benchmark_candidate_features": {
                "source_turn": {"dialogue_id": 11, "source_turn": 5},
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["structured_diagnostic_session_match"].score == 0.734
    assert by_id["structured_diagnostic_session_conflict"].score == 0.702


def test_temporal_query_uses_top_level_structured_diagnostic_turn_refs_for_session_match() -> None:
    intent = build_temporal_query_intent("What did Riley say in session 12?")
    matched = ContextItem(
        item_id="top_level_structured_diagnostic_session_match",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "source_dialogue_id": 12,
            "source_turn_id": 5,
        },
    )
    different_session = ContextItem(
        item_id="top_level_structured_diagnostic_session_conflict",
        item_type="fact",
        text="Riley was still waiting for confirmation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "source_dialogue_id": 11,
            "source_turn_id": 5,
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["top_level_structured_diagnostic_session_match"].score == 0.734
    assert by_id["top_level_structured_diagnostic_session_conflict"].score == 0.702


def test_temporal_query_boosts_written_ordinal_session_match() -> None:
    intent = build_temporal_query_intent("What did Alex decide in the fourth session?")
    matched = _item(
        "locomo:conv-1:session_4:D4:7:turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_4 turn D4:7 Alex decided to wait for invoice approval.",
    )
    different_session = _item(
        "locomo:conv-1:session_3:D3:7:turn",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_3 turn D3:7 Alex was still evaluating invoice options.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (4,)
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score > by_id[
        "locomo:conv-1:session_3:D3:7:turn"
    ].score
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item matches it"


def test_temporal_query_extracts_cardinal_word_after_session() -> None:
    intent = build_temporal_query_intent("What did Riley mention in session twelve?")

    assert intent.session_ordinals == (12,)


def test_temporal_query_does_not_treat_event_ordinals_as_session_ordinals() -> None:
    intent = build_temporal_query_intent("What was the first conversation with Sam?")

    assert intent.requests_earliest_event is True
    assert intent.session_ordinals == ()


def _item(
    item_id: str,
    *,
    score: float,
    retrieval_source: str,
    fact_status: str,
    review_only: bool = False,
    event_temporal_hint_code: str | None = None,
    temporal_hint_code: str | None = None,
    event_valid_from: str | None = None,
    text: str | None = None,
) -> ContextItem:
    provenance = {"fact_status": fact_status}
    if event_temporal_hint_code:
        provenance["event_temporal_hint_code"] = event_temporal_hint_code
    if temporal_hint_code:
        provenance["temporal_hint_code"] = temporal_hint_code
    if event_valid_from:
        provenance["event_valid_from"] = event_valid_from
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=text or item_id,
        score=score,
        source_refs=(SourceRef(source_type="fact", source_id=item_id),),
        diagnostics={
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "review_only": review_only,
            "score_signals": {"base_score": score},
            "provenance": provenance,
        },
    )
