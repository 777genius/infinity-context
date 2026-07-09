from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_candidates,
    _answer_support_diversity_family,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _source_sibling_answer_continuation_hydration_requests,
)
from infinity_context_core.application.context_source_siblings import (
    _TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE,
    _is_direct_source_sibling_answer_evidence,
    source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_query_expansion_routes_geographical_location_lists_to_trip_destinations() -> None:
    plan = build_query_expansion_plan("Which geographical locations has Riley been to?")

    expansion = _expansion_query(plan, "trip_destination_bridge")

    assert "location locations geographical been" in expansion
    assert "photo picture image caption visual query" in expansion


def test_best_query_relevance_uses_trip_destination_for_location_list_evidence() -> None:
    plan = build_query_expansion_plan("Which geographical locations has Riley been to?")
    cases = (
        "D1:18 Riley: I went to a place in London a few years ago.",
        "D3:2 Riley: Last week, I had a nice chat with a fantasy fan in California.",
        "D14:16 Riley: I snapped that pic on my trip to the Smoky Mountains last year.",
    )

    for text in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "trip_destination_bridge"
        assert relevance.distinctive_term_hits >= 1
        assert relevance.unique_term_hits >= 2


def test_source_sibling_answer_evidence_accepts_direct_trip_destination_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Rowan trip destination place city country",
        expansion_reason="trip_destination_bridge",
        text=(
            "D4:3 Rowan: I was in Chicago, it was awesome. "
            "The locals were friendly and it was great to experience another culture."
        ),
    )
    assert _is_direct_source_sibling_answer_evidence(
        expansion_query="Rowan trip destination place city country",
        expansion_reason="trip_destination_bridge",
        text="D4:3 Rowan: I was in Chicago for a conference.",
    )
    assert not _is_direct_source_sibling_answer_evidence(
        expansion_query="Rowan trip destination place city country",
        expansion_reason="trip_destination_bridge",
        text="D4:3 Mira: I was in Chicago for a conference.",
    )
    assert _TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE.search(
        "D4:3 Rowan: I was in a meeting downtown before practice."
    ) is None


def test_place_question_source_sibling_requests_next_answer_turn_hydration() -> None:
    question_turn = _answer_support_item(
        "place_question",
        "D4:2 Mira: Where did you go? Exploring new places can be inspiring.",
        source_id="locomo:conv-fixture:session_4:D4:2:turn",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {
        "locomo:conv-fixture:session_4:D4:3:turn": "trip_destination_bridge"
    }


def test_location_inventory_splits_direct_place_slots_and_keeps_exact_turns() -> None:
    london = _answer_support_item(
        "london",
        "D1:18 Riley: I went to a place in London a few years ago.",
        source_id="locomo:conv-fixture:session_1:D1:18:turn",
    )
    california = _answer_support_item(
        "california",
        "D3:2 Riley: Last week, I had a nice chat with a fantasy fan in California.",
        source_id="locomo:conv-fixture:session_3:D3:2:turn",
    )
    mountains = _answer_support_item(
        "mountains",
        "D14:16 Riley: I snapped that pic on my trip to the Smoky Mountains last year.",
        source_id="locomo:conv-fixture:session_14:D14:16:turn",
    )
    shelter_noise = _answer_support_item(
        "shelter_noise",
        "D4:1 Riley: I went to a shelter to volunteer, but not as a travel destination.",
        source_id="locomo:conv-fixture:session_4:D4:1:turn",
    )
    travel_intent = _answer_support_item(
        "travel_intent",
        "D6:1 Riley: I joined a travel club and want to visit countries someday.",
        source_id="locomo:conv-fixture:session_6:D6:1:turn",
    )

    families = {
        _answer_support_diversity_family(item)
        for item in (london, california, mountains)
    }
    candidates = _answer_support_diversity_candidates(
        [shelter_noise, travel_intent, london, california, mountains],
        query="Which geographical locations has Riley been to?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which geographical locations has Riley been to?",
    )
    first_three_ids = {candidates[family].item_id for family in ordered[:3]}
    result = ContextPacker().pack(
        bundle_id="ctx_location_inventory",
        items=(shelter_noise, travel_intent, london, california, mountains),
        token_budget=320,
        query="Which geographical locations has Riley been to?",
        max_rendered_chars=1300,
    )
    rendered = result.bundle.rendered_text

    assert any(":travel-place-realized:" in family for family in families)
    assert any(":state-place-realized:" in family for family in families)
    assert first_three_ids == {"london", "california", "mountains"}
    assert "place in London" in rendered
    assert "fan in California" in rendered
    assert "trip to the Smoky Mountains" in rendered


def test_location_inventory_treats_mountain_landmark_visual_turn_as_travel_place() -> None:
    mountain_photo = _answer_support_item(
        "mountain_photo",
        (
            "D13:15 Riley: I saved a photo from my internship break. "
            "image caption: Riley doing yoga on top of mount Aurora."
        ),
        source_id="locomo:conv-fixture:session_13:D13:15:turn",
    )
    generic_yoga = _answer_support_item(
        "generic_yoga",
        "D12:4 Riley: Yoga after work helps me reset before the commute home.",
        source_id="locomo:conv-fixture:session_12:D12:4:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [generic_yoga, mountain_photo],
        query="Which US state did Riley visit during the internship?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which US state did Riley visit during the internship?",
    )

    assert any(":travel-place:" in family for family in candidates)
    assert candidates[ordered[0]].item_id == "mountain_photo"


def test_event_place_query_prefers_named_location_over_wrong_venue() -> None:
    exact_location = _answer_support_item(
        "exact_location",
        "D7:4 Riley: I attended the concert in Rome last Friday.",
        source_id="locomo:conv-fixture:session_7:D7:4:turn",
    )
    wrong_venue = _answer_support_item(
        "wrong_venue",
        "D8:4 Riley: I attended the concert at the Rialto Theater in Milan.",
        source_id="locomo:conv-fixture:session_8:D8:4:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [wrong_venue, exact_location],
        query="Where did Riley attend the concert in Rome?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Where did Riley attend the concert in Rome?",
    )

    assert [candidates[family].item_id for family in ordered] == [
        "exact_location",
        "wrong_venue",
    ]


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion {reason}")


def _answer_support_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "source_type": "locomo_turn",
            "source_id": source_id,
            "score_signals": {
                "query_expansion_reason": "trip_destination_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 6,
            },
        },
    )
