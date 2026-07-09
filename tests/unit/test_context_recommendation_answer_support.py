from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_candidates,
    _answer_support_item_limit,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_concrete_recommendation_answer,
    recommendation_list_answer_kind,
    recommendation_list_answer_support_rank,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.context_recommendation_exact_turns import (
    exact_recommendation_list_turn_candidates,
)
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _restore_exact_source_sibling_answer_evidence_items,
    _source_sibling_answer_continuation_hydration_requests,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _recommendation_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float = 0.98,
    query_reason: str = "decomposition_recommendation_source",
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": query_reason,
                "source_sibling_answer_evidence": 1,
            },
        },
    )


def test_recommendation_rank_prefers_answer_window_over_request_only_turn() -> None:
    request_only = _recommendation_item(
        item_id="request_only",
        source_id="locomo:conv-fixture:session_5:D5:13:turn",
        text=(
            "D5:13 Lee: What books do you enjoy? "
            "I'm always up for new recommendations."
        ),
        score=0.99,
    )
    answer_window = _recommendation_item(
        item_id="answer_window",
        source_id="locomo:conv-fixture:session_5",
        text=(
            "D5:12 Dana: This trilogy is one of my faves; the story "
            "still blows me away. D5:13 Lee: What books do you enjoy? "
            "D5:14 Dana: I love this series, and it is a must-read."
        ),
        score=0.90,
    )

    candidates = _answer_support_diversity_candidates(
        [request_only, answer_window],
        query="What things has Dana recommended to Lee?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What things has Dana recommended to Lee?",
    )

    assert candidates[ordered[0]].item_id == "answer_window"


def test_recommendation_rank_prefers_named_object_followup_over_generic_acceptance() -> None:
    generic_acceptance = _recommendation_item(
        item_id="generic_acceptance",
        source_id="locomo:conv-fixture:session_8:D8:1:turn",
        text='D8:1 Lee: I took your recommendation and watched "A Quiet Sky".',
        score=0.99,
        query_reason="recommendation_source_bridge",
    )
    named_followup = _recommendation_item(
        item_id="named_followup",
        source_id="locomo:conv-fixture:session_8:D8:11:turn",
        text=(
            "D8:11 Lee: I really liked your maple flavoring recommendation "
            "you gave me for the cake."
        ),
        score=0.91,
        query_reason="recommendation_source_bridge",
    )

    assert (
        recommendation_list_answer_support_rank(
            text=named_followup.text,
            query_reason="recommendation_source_bridge",
        )
        < recommendation_list_answer_support_rank(
            text=generic_acceptance.text,
            query_reason="recommendation_source_bridge",
        )
    )

    candidates = _answer_support_diversity_candidates(
        [generic_acceptance, named_followup],
        query="What things has Dana recommended to Lee?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What things has Dana recommended to Lee?",
    )

    assert candidates[ordered[0]].item_id == "named_followup"


def test_recommendation_rank_keeps_direct_recommendation_objects_general() -> None:
    direct_recommendation = _recommendation_item(
        item_id="direct_recommendation",
        source_id="locomo:conv-fixture:session_11:D11:7:turn",
        text=(
            "D11:7 Dana: I highly recommend this game if you have not "
            "played it before."
        ),
        query_reason="decomposition_action_role",
    )

    assert (
        recommendation_list_answer_support_rank(
            text=direct_recommendation.text,
            query_reason="decomposition_action_role",
        )
        == 0
    )


def test_recommendation_rank_accepts_modified_demonstrative_objects() -> None:
    text = (
        "D4:9 Dana: Have you seen this romantic drama about memory? "
        "It is such a good one."
    )

    assert (
        recommendation_list_answer_kind(
            text=text,
            query_reason="decomposition_recommendation_source",
        )
        == "implicit"
    )
    assert (
        recommendation_role_alignment_rank(
            text=text,
            query="What recommendations has Dana given to Lee?",
            query_reason="decomposition_recommendation_source",
        )
        == 0
    )


def test_recommendation_rank_promotes_visual_positive_object_answers() -> None:
    text = (
        "D4:9 Dana: Yeah, for sure! This trilogy is one of my faves. "
        "The world building and storytelling always blow me away!\n"
        "image caption: a photo of a shelf with movies on it\n"
        "visual query: fantasy trilogy boxset"
    )

    assert (
        recommendation_list_answer_kind(
            text=text,
            query_reason="decomposition_recommendation_source",
        )
        == "implicit"
    )
    assert (
        recommendation_list_answer_support_rank(
            text=text,
            query_reason="decomposition_recommendation_source",
        )
        == 0
    )
    assert (
        recommendation_role_alignment_rank(
            text=text,
            query="What recommendations has Dana given to Lee?",
            query_reason="decomposition_recommendation_source",
        )
        == 0
    )


def test_recommendation_rank_accepts_anaphoric_definite_recommendation() -> None:
    text = "D4:10 Dana: I would definitely recommend it if you explain what it is."

    assert (
        recommendation_list_answer_kind(
            text=text,
            query_reason="decomposition_recommendation_source",
        )
        == "direct"
    )


def test_recommendation_rank_accepts_advice_lists_and_source_confirmations() -> None:
    query = "What recommendations has Lee received from Dana?"
    advice_list = (
        "D6:11 Dana: Sure! For one, you should get a couch that can sit "
        "multiple people, and also invest in dimmable lights."
    )
    positive_confirmation = (
        "D6:12 Dana: That's a great one! Let me know what you think when "
        "you are finished."
    )
    object_setup = "D6:13 Lee: Good idea! How about this series?"

    assert (
        recommendation_list_answer_kind(
            text=advice_list,
            query_reason="recommendation_source_bridge",
        )
        == "direct"
    )
    assert (
        recommendation_list_answer_support_rank(
            text=advice_list,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )
    assert (
        recommendation_list_answer_kind(
            text=positive_confirmation,
            query_reason="recommendation_source_bridge",
        )
        == "confirmation"
    )
    assert (
        recommendation_role_alignment_rank(
            text=positive_confirmation,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )
    assert (
        recommendation_list_answer_kind(
            text=object_setup,
            query_reason="recommendation_source_bridge",
        )
        == "setup"
    )
    assert (
        recommendation_role_alignment_rank(
            text=object_setup,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 1
    )


def test_recommendation_role_alignment_accepts_nominal_given_query_shape() -> None:
    query = "What recommendations has Dana given to Lee?"

    assert (
        recommendation_role_alignment_rank(
            text=(
                "D6:11 Dana: Sure! For one, you should get a couch that can "
                "sit multiple people."
            ),
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )
    assert (
        recommendation_role_alignment_rank(
            text="D6:12 Lee: Good idea! How about this series?",
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 1
    )
    assert (
        recommendation_role_alignment_rank(
            text="D6:13 Lee: I highly recommend this game.",
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 5
    )


def test_recommendation_role_alignment_rejects_reverse_direction_paired_reply() -> None:
    query = "What recommendations has Dana given to Lee?"
    reverse_pair = (
        "D6:10 Dana: I should start a cork board of my own, shouldn't I? "
        "D6:11 Lee: I would definitely recommend it!"
    )
    correct_pair = (
        "D6:10 Lee: I should start a cork board of my own, shouldn't I? "
        "D6:11 Dana: I would definitely recommend it!"
    )

    assert (
        recommendation_role_alignment_rank(
            text=reverse_pair,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        > 1
    )
    assert (
        recommendation_role_alignment_rank(
            text=correct_pair,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )


def test_recommendation_request_questions_do_not_rank_as_answers() -> None:
    text = "D4:7 Dana: Not recently. Any good ones you'd recommend?"

    assert (
        recommendation_list_answer_kind(
            text=text,
            query_reason="recommendation_source_bridge",
        )
        == "request"
    )
    assert (
        recommendation_list_answer_support_rank(
            text=text,
            query_reason="recommendation_source_bridge",
        )
        == 6
    )


def test_recommendation_thanks_acceptance_does_not_become_source_answer() -> None:
    text = (
        "D4:9 Lee: That sounds like a great one! I'll add it to my list. "
        "Thanks for the recommendation!"
    )

    assert (
        recommendation_list_answer_kind(
            text=text,
            query_reason="recommendation_source_bridge",
        )
        == "accepted"
    )
    assert (
        recommendation_role_alignment_rank(
            text=text,
            query="What recommendations has Lee given to Dana?",
            query_reason="recommendation_source_bridge",
        )
        > 1
    )
    assert (
        recommendation_role_alignment_rank(
            text=text,
            query="What recommendations has Dana given to Lee?",
            query_reason="recommendation_source_bridge",
        )
        == 1
    )


def test_recommendation_order_demotes_wrong_direction_acceptance() -> None:
    wrong_direction_acceptance = _recommendation_item(
        item_id="wrong_direction_acceptance",
        source_id="locomo:conv-fixture:session_8:D8:1:turn",
        text=(
            "D8:1 Dana: Thanks for the recommendation, Lee. "
            "I'm definitely going to check it out."
        ),
        score=0.99,
        query_reason="recommendation_source_bridge",
    )
    role_aligned_advice = _recommendation_item(
        item_id="role_aligned_advice",
        source_id="locomo:conv-fixture:session_8:D8:2:turn",
        text=(
            "D8:2 Dana: Sure! For one, you should get a couch with room "
            "to stretch out, and also invest in dimmable lights."
        ),
        score=0.88,
        query_reason="recommendation_source_bridge",
    )

    candidates = _answer_support_diversity_candidates(
        [wrong_direction_acceptance, role_aligned_advice],
        query="What recommendations has Lee received from Dana?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What recommendations has Lee received from Dana?",
    )

    assert candidates[ordered[0]].item_id == "role_aligned_advice"


def test_recommendation_rank_does_not_certify_unrelated_query_reasons() -> None:
    assert not is_concrete_recommendation_answer(
        text=(
            "D7:2 Riley: I'm running for office again. It's been a wild ride, "
            "but I'm more excited than ever."
        ),
        query_reason="public_office_service_bridge",
    )


def test_recommendation_role_alignment_prefers_source_speaker_direction() -> None:
    query = "What things has Dana recommended to Lee?"
    source_speaker = (
        "D4:7 Dana: I highly recommend this game if you have not played it before."
    )
    recipient_speaker = (
        "D4:8 Lee: I recommend finding a fantasy book series for relaxing."
    )
    accepted_by_recipient = (
        "D4:9 Lee: I liked your maple flavoring recommendation for the cake."
    )
    accepted_by_source = (
        'D4:10 Dana: I took your recommendation and watched "A Quiet Sky".'
    )

    assert (
        recommendation_role_alignment_rank(
            text=source_speaker,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )
    assert (
        recommendation_role_alignment_rank(
            text=accepted_by_recipient,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 1
    )
    assert (
        recommendation_role_alignment_rank(
            text=recipient_speaker,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        > 1
    )
    assert (
        recommendation_role_alignment_rank(
            text=accepted_by_source,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        > 1
    )


def test_recommendation_role_alignment_handles_received_from_direction() -> None:
    query = "What recommendations has Lee received from Dana?"
    source_speaker = (
        "D6:11 Dana: I would definitely recommend it if you want a quieter room."
    )
    recipient_acceptance = (
        "D6:12 Lee: I tried your recommendation and it made the room calmer."
    )
    reverse_direction = (
        "D6:13 Lee: I highly recommend this game if you have not played it before."
    )

    assert (
        recommendation_role_alignment_rank(
            text=source_speaker,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 0
    )
    assert (
        recommendation_role_alignment_rank(
            text=recipient_acceptance,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        == 1
    )
    assert (
        recommendation_role_alignment_rank(
            text=reverse_direction,
            query=query,
            query_reason="recommendation_source_bridge",
        )
        > 1
    )


def test_recommendation_exact_repair_filters_request_only_siblings() -> None:
    source_item = _recommendation_item(
        item_id="source_window",
        source_id="locomo:conv-fixture:session_5",
        text=(
            "D5:10 Dana: I made tea before reading. "
            "D5:12 Dana: This trilogy is one of my faves. "
            "D5:14 Dana: I love this series; it is a must-read. "
            "D5:16 Lee: What books do you enjoy? I need recommendations."
        ),
        query_reason="decomposition_recommendation_source",
    )
    source_item = ContextItem(
        item_id=source_item.item_id,
        item_type=source_item.item_type,
        text=source_item.text,
        score=source_item.score,
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="locomo:conv-fixture:session_5"),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:12:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:14:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:16:turn",
            ),
        ),
        diagnostics=source_item.diagnostics,
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(source_item,),
    )
    repaired_source_ids = {
        ref.source_id
        for item in restored
        for ref in item.source_refs
        if ":D5:" in str(ref.source_id)
    }

    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2
    assert repaired_source_ids == {
        "locomo:conv-fixture:session_5:D5:12:turn",
        "locomo:conv-fixture:session_5:D5:14:turn",
    }


def test_recommendation_setup_requests_next_turn_hydration() -> None:
    setup_turn = _recommendation_item(
        item_id="setup_turn",
        source_id="locomo:conv-fixture:session_7:D7:8:turn",
        text="D7:8 Lee: Good idea! How about this series?",
        query_reason="recommendation_source_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (setup_turn,),
        existing_source_ids=frozenset(
            {"locomo:conv-fixture:session_7:D7:8:turn"}
        ),
    )

    assert requests == {
        "locomo:conv-fixture:session_7:D7:9:turn": "recommendation_source_bridge"
    }


def test_recommendation_anaphoric_answer_requests_previous_turn_hydration() -> None:
    answer_turn = _recommendation_item(
        item_id="answer_turn",
        source_id="locomo:conv-fixture:session_7:D7:9:turn",
        text="D7:9 Dana: I would definitely recommend it!",
        query_reason="recommendation_source_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (answer_turn,),
        existing_source_ids=frozenset(
            {"locomo:conv-fixture:session_7:D7:9:turn"}
        ),
    )

    assert requests == {
        "locomo:conv-fixture:session_7:D7:8:turn": "recommendation_source_bridge"
    }


def test_recommendation_confirmation_requests_previous_setup_hydration() -> None:
    confirmation_turn = _recommendation_item(
        item_id="confirmation_turn",
        source_id="locomo:conv-fixture:session_7:D7:9:turn",
        text="D7:9 Dana: That's a great one! Let me know what you think.",
        query_reason="recommendation_source_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (confirmation_turn,),
        existing_source_ids=frozenset(
            {"locomo:conv-fixture:session_7:D7:9:turn"}
        ),
    )

    assert requests == {
        "locomo:conv-fixture:session_7:D7:8:turn": "recommendation_source_bridge"
    }


def test_recommendation_lists_expand_answer_support_limit_for_many_objects() -> None:
    items = [
        _recommendation_item(
            item_id=f"recommendation_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:7:turn",
            text=(
                f"D{index}:7 Dana: I highly recommend this game if you have "
                "not played it before."
            ),
        )
        for index in range(1, 10)
    ]

    candidates = _answer_support_diversity_candidates(
        items,
        query="What things has Dana recommended to Lee?",
    )

    assert _answer_support_item_limit(candidates) == 12


def test_recommendation_exact_turn_candidates_focus_multi_evidence_answers() -> None:
    source_window = _recommendation_item(
        item_id="source_window",
        source_id="locomo:conv-fixture:session_4",
        text=(
            "D4:7 Dana: I highly recommend this game if you have not "
            "played it before. D4:8 Lee: What books do you enjoy? "
            "I'm always up for new recommendations. D4:9 Lee: I really "
            "liked your maple flavoring recommendation for the cake."
        ),
    )
    source_window = ContextItem(
        item_id=source_window.item_id,
        item_type=source_window.item_type,
        text=source_window.text,
        score=source_window.score,
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="locomo:conv-fixture:session_4"),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:7:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:8:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:9:turn",
            ),
        ),
        diagnostics=source_window.diagnostics,
    )

    candidates = {"recommendation_source_group": source_window}

    selected = exact_recommendation_list_turn_candidates(
        candidates,
        query="What things has Dana recommended to Lee?",
        limit=4,
    )

    assert [item.source_refs[0].source_id for item in selected] == [
        "locomo:conv-fixture:session_4:D4:7:turn",
        "locomo:conv-fixture:session_4:D4:9:turn",
    ]


def test_recommendation_exact_turn_candidates_pair_setup_with_source_reply() -> None:
    source_window = _recommendation_item(
        item_id="source_window",
        source_id="locomo:conv-fixture:session_6",
        text=(
            "D6:8 Lee: Good idea! How about this series? "
            "D6:9 Dana: That's a great one! Let me know what you think "
            "when you are finished. "
            "D6:10 Lee: I really should start a cork board of my own, "
            "shouldn't I? That seems useful. "
            "D6:11 Dana: I would definitely recommend it!"
        ),
        query_reason="recommendation_source_bridge",
    )
    source_window = ContextItem(
        item_id=source_window.item_id,
        item_type=source_window.item_type,
        text=source_window.text,
        score=source_window.score,
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="locomo:conv-fixture:session_6"),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:8:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:11:turn",
            ),
        ),
        diagnostics=source_window.diagnostics,
    )

    selected = exact_recommendation_list_turn_candidates(
        {"recommendation_source_group": source_window},
        query="What recommendations has Lee received from Dana?",
        limit=4,
    )

    assert [tuple(ref.source_id for ref in item.source_refs) for item in selected] == [
        (
            "locomo:conv-fixture:session_6:D6:10:turn",
            "locomo:conv-fixture:session_6:D6:11:turn",
        ),
        (
            "locomo:conv-fixture:session_6:D6:8:turn",
            "locomo:conv-fixture:session_6:D6:9:turn",
        ),
    ]


def test_recommendation_exact_turn_candidates_attach_previous_ref_for_anaphora() -> None:
    answer_turn = _recommendation_item(
        item_id="answer_turn",
        source_id="locomo:conv-fixture:session_6:D6:11:turn",
        text="D6:11 Dana: I would definitely recommend it!",
        query_reason="recommendation_source_bridge",
    )

    selected = exact_recommendation_list_turn_candidates(
        {"answer_turn": answer_turn},
        query="What recommendations has Lee received from Dana?",
        limit=2,
    )

    assert [tuple(ref.source_id for ref in item.source_refs) for item in selected] == [
        (
            "locomo:conv-fixture:session_6:D6:10:turn",
            "locomo:conv-fixture:session_6:D6:11:turn",
        ),
    ]
