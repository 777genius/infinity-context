from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_context_packer_preserves_exact_country_destination_turns() -> None:
    query = "Which country do Calvin and Dave want to meet in?"
    exact_trip = _country_destination_item(
        "exact_trip",
        (
            "D3:9 Calvin: I'm looking forward to my upcoming trip to Boston "
            "after the tour."
        ),
        source_id="locomo:conv-fixture:session_3:D3:9:turn",
    )
    exact_mutual = _country_destination_item(
        "exact_mutual",
        (
            "D3:10 Dave: I can't wait for your trip to Boston. I'll show "
            "you around town and all the cool spots."
        ),
        source_id="locomo:conv-fixture:session_3:D3:10:turn",
    )
    later_update = _country_destination_item(
        "later_update",
        "D17:6 Calvin: I booked a flight ticket to Boston last week.",
        source_id="locomo:conv-fixture:session_17:D17:6:turn",
    )
    unrelated_meeting = _country_destination_item(
        "unrelated_meeting",
        "D27:1 Calvin: I went to a networking event to meet more artists.",
        source_id="locomo:conv-fixture:session_27:D27:1:turn",
    )

    result = ContextPacker().pack(
        bundle_id="ctx_country_destination",
        items=(unrelated_meeting, later_update, exact_trip, exact_mutual),
        query=query,
        token_budget=180,
        max_rendered_chars=1000,
    )

    rendered = result.bundle.rendered_text
    assert "D3:9 Calvin: I'm looking forward to my upcoming trip to Boston" in rendered
    assert "D3:10 Dave: I can't wait for your trip to Boston" in rendered


def test_context_packer_preserves_country_destination_visiting_turn() -> None:
    query = "Which country was Avery visiting in May 2023?"
    exact_trip = _country_destination_item(
        "exact_trip",
        (
            "D2:1 Avery: Last weekend, I took my family on a road trip to "
            "Vancouver. We drove through mountain roads and stayed in a cozy cabin."
        ),
        source_id="locomo:conv-fixture:session_2:D2:1:turn",
    )
    unrelated_family = _country_destination_item(
        "unrelated_family",
        (
            "D23:1 Avery: I recently got married and told my extended family "
            "about it."
        ),
        source_id="locomo:conv-fixture:session_23:D23:1:turn",
    )

    result = ContextPacker().pack(
        bundle_id="ctx_country_destination_visiting",
        items=(unrelated_family, exact_trip),
        query=query,
        token_budget=120,
        max_rendered_chars=700,
    )

    rendered = result.bundle.rendered_text
    assert "D2:1 Avery: Last weekend, I took my family on a road trip to Vancouver" in rendered


def test_context_packer_prefers_temporally_aligned_country_destination_turn() -> None:
    query = "Which country was Avery visiting in May 2023?"
    may_trip = _country_destination_item(
        "may_trip",
        (
            "session_2 date: 7:11 pm on 24 May, 2023\n"
            "D2:1 Avery: Last weekend, I took my family on a road trip to "
            "Vancouver."
        ),
        source_id="locomo:conv-fixture:session_2:D2:1:turn",
    )
    later_trip = _country_destination_item(
        "later_trip",
        (
            "session_5 date: 7:52 pm on 7 August, 2023\n"
            "D5:1 Avery: Last week I went on a trip to Canada and met a "
            "new friend."
        ),
        source_id="locomo:conv-fixture:session_5:D5:1:turn",
    )

    result = ContextPacker().pack(
        bundle_id="ctx_country_destination_temporal",
        items=(later_trip, may_trip),
        query=query,
        token_budget=80,
        max_rendered_chars=520,
    )

    rendered = result.bundle.rendered_text
    assert "D2:1 Avery: Last weekend, I took my family on a road trip to Vancouver" in rendered


def _country_destination_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
                chunk_id=item_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "query_expansion_reason": "decomposition_country_destination",
            "score_signals": {
                "query_expansion_reason": "decomposition_country_destination",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
