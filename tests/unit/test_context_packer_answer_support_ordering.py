from infinity_context_core.application.context_packer import (
    _answer_support_diversity_candidates,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.context_packer_answer_support import (
    _is_relationship_status_direct_answer_support_item,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_music_event_query_promotes_temporal_direct_event_turn() -> None:
    violin_concert = ContextItem(
        item_id="violin_concert",
        item_type="chunk",
        text=(
            "D8:12 John: Just last week, I found a violin concert that we "
            "all enjoyed."
        ),
        score=0.97,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_8:D8:12:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "classical_music_preference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    unrelated_veterans_event = ContextItem(
        item_id="unrelated_veterans_event",
        item_type="chunk",
        text=(
            "D21:22 John: I participated in a marching event for veterans' "
            "rights and it was meaningful."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_21:D21:22:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "classical_music_preference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [unrelated_veterans_event, violin_concert]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What music events has John attended?",
    )

    assert candidates[ordered[0]].item_id == "violin_concert"


def test_relationship_status_query_promotes_direct_self_disclosure() -> None:
    question_only_context = ContextItem(
        item_id="question_only_context",
        item_type="chunk",
        text=(
            "D7:6 Avery: Aw, that's wonderful! How long have you been married? "
            "D7:7 Morgan: We're not married yet but we have been together "
            "for three years."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:6:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_relationship_status",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    direct_status = ContextItem(
        item_id="direct_status",
        item_type="chunk",
        text=(
            "D19:11 Avery: Reminds me of when I used to play games with my "
            "husband. We took turns and made great memories together."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_19:D19:11:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_relationship_status",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [question_only_context, direct_status]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Is Avery married?",
    )

    assert not _is_relationship_status_direct_answer_support_item(
        question_only_context,
        query="Is Avery married?",
    )
    assert _is_relationship_status_direct_answer_support_item(
        direct_status,
        query="Is Avery married?",
    )
    assert candidates[ordered[0]].item_id == "direct_status"


def test_exact_outdoor_nature_memory_turn_precedes_broad_outdoor_support() -> None:
    broad_camping_context = ContextItem(
        item_id="broad_camping_context",
        item_type="chunk",
        text=(
            "D10:12 Morgan: Our family camping trip is the highlight of the "
            "summer. We roast marshmallows around the campfire and tell stories."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_10:D10:12:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "outdoor_preference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    exact_meteor_memory = ContextItem(
        item_id="exact_meteor_memory",
        item_type="chunk",
        text=(
            "D10:14 Morgan: I'll always remember our camping trip last year "
            "when we saw the Perseid meteor shower. The sky lit up and we "
            "felt at one with the universe."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_10:D10:14:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "outdoor_nature_memory_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [broad_camping_context, exact_meteor_memory]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Would Morgan be more interested in a national park or a theme park?",
    )

    assert candidates[ordered[0]].item_id == "exact_meteor_memory"


def test_exact_named_preference_turn_precedes_generic_inference_support() -> None:
    generic_trip_support = ContextItem(
        item_id="generic_trip_support",
        item_type="chunk",
        text=(
            "D8:4 Avery: I visited several coastal towns during the trip and "
            "liked the old stone streets."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_8:D8:4:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "original_query",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    named_preference = ContextItem(
        item_id="named_preference",
        item_type="chunk",
        text=(
            "D12:5 Avery: Definitely Aurora Quest! It is my favorite and "
            "never gets old."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_12:D12:5:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "original_query",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [generic_trip_support, named_preference]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which Aurora Quest locations would Avery enjoy visiting?",
    )

    assert candidates[ordered[0]].item_id == "named_preference"


def test_exact_themed_location_turn_precedes_generic_inference_support() -> None:
    generic_trip_support = ContextItem(
        item_id="generic_trip_support",
        item_type="chunk",
        text="D8:4 Avery: I visited several coastal towns during the trip.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_8:D8:4:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inference_support",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    themed_location = ContextItem(
        item_id="themed_location",
        item_type="chunk",
        text=(
            "D4:9 Avery: I went to a real fantasy movie place last year. "
            "The tour was amazing, and I would love to explore more places "
            "like that."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_4:D4:9:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inference_support",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [generic_trip_support, themed_location]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which Aurora Quest locations would Avery enjoy visiting?",
    )

    assert candidates[ordered[0]].item_id == "themed_location"


def test_themed_location_query_preserves_preference_place_and_destination_evidence() -> None:
    themed_place = ContextItem(
        item_id="themed_place",
        item_type="chunk",
        text=(
            "D4:9 Avery: I went to a real fantasy movie place last year. "
            "The tour was amazing, and I would love to explore more places "
            "like that."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_4:D4:9:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inference_support",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    named_preference = ContextItem(
        item_id="named_preference",
        item_type="chunk",
        text=(
            "D12:5 Avery: Definitely Aurora Quest! It is my favorite and "
            "never gets old."
        ),
        score=0.73,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_12:D12:5:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inference_support",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    destination = ContextItem(
        item_id="destination",
        item_type="chunk",
        text="D28:1 Avery: Next month, I'm off to Ireland for a semester.",
        score=0.74,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_28:D28:1:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {"query_expansion_reason": "trip_destination_bridge"},
        },
    )
    generic_place = ContextItem(
        item_id="generic_place",
        item_type="chunk",
        text="D8:4 Avery: I visited several coastal towns during the trip.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_8:D8:4:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {"query_expansion_reason": "decomposition_inference_support"},
        },
    )
    generic_destination_mention = ContextItem(
        item_id="generic_destination_mention",
        item_type="chunk",
        text=(
            "D8:6 Avery: I read an article about Ireland's coastal towns, "
            "but I have not made any plans to go there."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_8:D8:6:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {"query_expansion_reason": "trip_destination_bridge"},
        },
    )

    query = "Which Aurora Quest-related locations would Avery enjoy during a visit to Ireland?"
    candidates = _answer_support_diversity_candidates(
        [
            generic_place,
            generic_destination_mention,
            destination,
            named_preference,
            themed_place,
        ],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)
    first_three_ids = {candidates[family].item_id for family in ordered[:3]}

    assert candidates[ordered[0]].item_id == "destination"
    assert first_three_ids == {"themed_place", "named_preference", "destination"}


def test_exact_map_trail_place_turn_precedes_generic_park_context() -> None:
    generic_park_context = ContextItem(
        item_id="generic_park_context",
        item_type="chunk",
        text="D5:8 Dana: We took a road trip to a beautiful national park.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_5:D5:8:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "national_park_inference_bridge",
            },
        },
    )
    map_trail = ContextItem(
        item_id="map_trail",
        item_type="chunk",
        text=(
            "D11:9 Dana: Let's get planning for next month. Here's the map "
            "for the trail. image caption: a photo of a map of a park with "
            "a lot of trees. visual query: hiking trails map perfect spot"
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_11:D11:9:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "national_park_inference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [generic_park_context, map_trail]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which national park could Riley and Dana be referring to?",
    )

    assert candidates[ordered[0]].item_id == "map_trail"


def test_exact_landmark_place_turn_precedes_generic_trip_context() -> None:
    generic_trip_context = ContextItem(
        item_id="generic_trip_context",
        item_type="chunk",
        text="D23:1 Riley: We returned from an awesome trip to a coastal city.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_23:D23:1:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "trip_destination_bridge",
            },
        },
    )
    landmark_visit = ContextItem(
        item_id="landmark_visit",
        item_type="chunk",
        text=(
            "D13:15 Riley: Here's an example of how I spent yesterday "
            "morning, yoga on top of Mount Aurora. image caption: a photo "
            "of a person standing on a rock"
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-42:session_13:D13:15:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "trip_destination_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [generic_trip_context, landmark_visit]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Which US state did Riley visit during her internship?",
    )

    assert candidates[ordered[0]].item_id == "landmark_visit"


def test_exact_visual_activity_turn_precedes_broad_activity_support() -> None:
    broad_activity_context = ContextItem(
        item_id="broad_activity_context",
        item_type="chunk",
        text=(
            "D9:1 Morgan: We went camping with my family and had a quiet "
            "weekend. D9:5 Morgan: We spent time outside with the kids."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_9:D9:1:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_activity_participation",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    exact_painting_visual = ContextItem(
        item_id="exact_painting_visual",
        item_type="chunk",
        text=(
            "D1:12 Morgan: visual query: painting. Image caption: Morgan is "
            "painting a lake scene at home."
        ),
        score=0.74,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_1:D1:12:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "activity_visual_selfcare_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [broad_activity_context, exact_painting_visual]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What activities does Morgan partake in?",
    )

    assert candidates[ordered[0]].item_id == "exact_painting_visual"


def test_inventory_slot_family_prefers_exact_turn_over_adjacent_snippet() -> None:
    adjacent_snippet = ContextItem(
        item_id="adjacent_d29_2",
        item_type="chunk",
        text=(
            "D29:2 John: Last weekend, I participated in a community event "
            "that was inspiring. D29:4 John: I set up a 5K charity run in "
            "our neighborhood to help out veterans and their families."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_29:D29:2:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "veterans_event_inventory_bridge",
            },
        },
    )
    exact_charity_run = ContextItem(
        item_id="exact_d29_4",
        item_type="chunk",
        text=(
            "D29:4 John: I set up a 5K charity run in our neighborhood. "
            "It was all for a good cause - to help out veterans and their "
            "families."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_29:D29:4:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "veterans_event_inventory_bridge",
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [adjacent_snippet, exact_charity_run]
    )

    assert len(candidates) == 1
    assert next(iter(candidates.values())).item_id == "exact_d29_4"


def test_identity_query_prefers_exact_identity_turn_over_adjacent_context() -> None:
    support_group_context = ContextItem(
        item_id="support_group_context",
        item_type="chunk",
        text="D1:3 Caroline: I went to a LGBTQ support group yesterday.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_1:D1:3:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "identity_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    exact_identity_turn = ContextItem(
        item_id="exact_identity_turn",
        item_type="chunk",
        text=(
            "D1:5 Caroline: The transgender stories were inspiring, and "
            "the support helped me feel thankful."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_1:D1:5:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "identity_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [support_group_context, exact_identity_turn]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What is Caroline's identity?",
    )

    assert candidates[ordered[0]].item_id == "exact_identity_turn"


def test_exact_query_object_turn_precedes_broad_summary() -> None:
    broad_summary = ContextItem(
        item_id="session_4_summary",
        item_type="chunk",
        text=(
            "Caroline attended an LGBTQ+ counseling workshop and found it "
            "enlightening. Melanie asked about her motivation."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_session_summary",
                source_id="locomo:conv-26:session_4:summary",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_attribute_aggregation",
            },
        },
    )
    exact_workshop_turn = ContextItem(
        item_id="exact_d4_13",
        item_type="chunk",
        text=(
            "D4:13 Caroline: Last Friday, I went to an LGBTQ+ counseling "
            "workshop and it was really enlightening."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_4:D4:13:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_attribute_aggregation",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [broad_summary, exact_workshop_turn]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What workshop did Caroline attend recently?",
    )

    assert candidates[ordered[0]].item_id == "exact_d4_13"


def test_query_aware_candidate_selection_prefers_exact_takeaway_turn() -> None:
    book_suggestion = ContextItem(
        item_id="book_suggestion",
        item_type="chunk",
        text=(
            "D7:11 Caroline: I loved \"Becoming Nicole\" by Amy Ellis Nutt. "
            "It's a real inspiring true story about a trans girl and her "
            "family. It made me feel connected and gave me a lot of hope for "
            "my own path. Highly recommend it for sure!"
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_7:D7:11:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "book_reading_list_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    exact_takeaway = ContextItem(
        item_id="exact_takeaway",
        item_type="chunk",
        text=(
            "D7:13 Caroline: It taught me self-acceptance and how to find "
            "support. It also showed me that tough times don't last - hope "
            "and love exist."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_7:D7:13:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "book_reading_list_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [book_suggestion, exact_takeaway],
        query="What did Caroline take away from the book Becoming Nicole?",
    )

    assert len(candidates) == 1
    assert next(iter(candidates.values())).item_id == "exact_takeaway"


def test_query_aware_candidate_selection_prefers_pottery_reason_answer() -> None:
    color_question = ContextItem(
        item_id="color_question",
        item_type="chunk",
        text=(
            "D12:5 Caroline: That bowl is awesome, Mel! What gave you the "
            "idea for all the colors and patterns?"
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_12:D12:5:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "pottery_color_reason_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    exact_reason = ContextItem(
        item_id="exact_reason",
        item_type="chunk",
        text=(
            "D12:6 Melanie: Thanks, Caroline! I'm obsessed with those, so I "
            "made something to catch the eye and make people smile. Plus, "
            "painting helps me express my feelings and be creative."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_12:D12:6:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "pottery_color_reason_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [color_question, exact_reason],
        query="Why did Caroline choose to use colors and patterns in her pottery project?",
    )

    assert len(candidates) == 1
    assert next(iter(candidates.values())).item_id == "exact_reason"


def test_beach_or_mountains_query_promotes_beach_visual_evidence() -> None:
    mountain_trip = ContextItem(
        item_id="mountain_trip",
        item_type="chunk",
        text=(
            "D18:3 Maria: That mountaineering trip sounds amazing. The "
            "mountains look peaceful."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_18:D18:3:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "beach_or_mountains_inference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    beach_walk = ContextItem(
        item_id="beach_walk",
        item_type="chunk",
        text=(
            "D22:15 John: This picture from my walk reminds me to breathe "
            "and appreciate nature. D22:15 image caption: a sunset over the "
            "ocean with a sailboat."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_22:D22:15:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "beach_or_mountains_inference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    candidates = _answer_support_diversity_candidates(
        [mountain_trip, beach_walk],
        query="Does John live close to a beach or the mountains?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="Does John live close to a beach or the mountains?",
    )

    assert candidates[ordered[0]].item_id == "beach_walk"


def test_state_residence_query_promotes_exact_geo_map_evidence() -> None:
    generic_park = ContextItem(
        item_id="generic_park",
        item_type="chunk",
        text="D7:3 Andrew: I took the dog to a local park after work.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:3:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "state_residence_inference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    trail_map = ContextItem(
        item_id="trail_map",
        item_type="chunk",
        text=(
            "D11:9 Andrew: Here is the map for the trail. image caption: "
            "a photo of a map of a park with trees. visual query: hiking "
            "trails map perfect spot."
        ),
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_11:D11:9:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "state_residence_inference_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    query = "Which US state do Riley and Casey potentially live in?"
    candidates = _answer_support_diversity_candidates(
        [generic_park, trail_map],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)

    assert candidates[ordered[0]].item_id == "trail_map"


def test_family_activity_query_promotes_concrete_family_activity_turns() -> None:
    solo_pottery = ContextItem(
        item_id="solo_pottery",
        item_type="chunk",
        text=(
            "D5:4 Melanie: I just signed up for a pottery class. It's like "
            "therapy for me, letting me express myself and get creative."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_5:D5:4:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "family_activity_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    family_painting = ContextItem(
        item_id="family_painting",
        item_type="chunk",
        text=(
            "D8:6 Melanie: We love painting together lately, especially "
            "nature-inspired ones. Here's our latest work from last weekend."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_8:D8:6:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "family_painting_activity_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    family_camping = ContextItem(
        item_id="family_camping",
        item_type="chunk",
        text=(
            "D9:1 Melanie: I had a quiet weekend after we went camping with "
            "my fam two weekends ago. It was great to unplug and hang with "
            "the kids."
        ),
        score=0.89,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_9:D9:1:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "family_activity_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    query = "What activities has Melanie done with her family?"
    candidates = _answer_support_diversity_candidates(
        [solo_pottery, family_painting, family_camping],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)

    assert [candidates[family].item_id for family in ordered[:2]] == [
        "family_camping",
        "family_painting",
    ]


def test_painted_subject_query_promotes_matching_subject_turn() -> None:
    generic_sunflower = ContextItem(
        item_id="generic_sunflower",
        item_type="chunk",
        text=(
            "D14:30 Melanie: Painting landscapes and still life is my "
            "favorite. Here's a painting of sunflowers."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_14:D14:30:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "painting_inventory_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    sunset_painting = ContextItem(
        item_id="sunset_painting",
        item_type="chunk",
        text=(
            "D14:5 Caroline: I've been busy painting. D14:5 image caption: "
            "a photo of a painting of a sunset on a small easel. D14:5 "
            "visual query: vibrant sunset beach painting."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_14:D14:5:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "painting_inventory_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    query = "What subject have Caroline and Melanie both painted?"
    candidates = _answer_support_diversity_candidates(
        [generic_sunflower, sunset_painting],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)

    assert candidates[ordered[0]].item_id == "sunset_painting"


def test_art_style_query_promotes_art_show_preview_slot() -> None:
    generic_art = ContextItem(
        item_id="generic_art",
        item_type="chunk",
        text=(
            "D11:8 Caroline: Representing inclusivity and diversity in my "
            "art is important to me. Here's a recent painting."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_11:D11:8:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "art_style_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
    art_show_preview = ContextItem(
        item_id="art_show_preview",
        item_type="chunk",
        text=(
            "D9:14 Caroline: Check out my painting for the art show! Hope "
            "you like it. image caption: a painting of a tree with a bright "
            "sun in the background."
        ),
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_9:D9:14:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "art_style_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )

    query = "What kind of art does Caroline make?"
    candidates = _answer_support_diversity_candidates(
        [generic_art, art_show_preview],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)

    assert candidates[ordered[0]].item_id == "art_show_preview"
