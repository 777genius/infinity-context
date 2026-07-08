from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.use_cases.build_context import (
    _apply_explicit_requirement_guard,
    _exact_turn_source_ref_hydration_request_plan,
    _exact_turn_source_ref_hydration_requests,
    _restore_exact_source_sibling_answer_evidence_items,
    _should_use_exact_source_ref_hydration_item,
)
from infinity_context_core.domain.entities import SourceRef


def test_requirement_guard_drops_object_kind_mismatch_evidence() -> None:
    item = _item(
        "cat_note",
        "I mentioned my cat Luna during the call.",
        deterministic_reasons=("object_kind_species_mismatch",),
    )

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query="What hamster did I mention?",
        query_anchor_intent=build_query_anchor_intent("What hamster did I mention?"),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == "dropped_object_kind_mismatch"
    assert diagnostics["requirement_guard_items_dropped"] == 1
    assert diagnostics["requirement_guard_object_kind_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_object_kind_match_evidence() -> None:
    item = _item(
        "hamster_note",
        "I mentioned my hamster Pip during the call.",
        deterministic_reasons=("object_kind_match",),
    )

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query="What hamster did I mention?",
        query_anchor_intent=build_query_anchor_intent("What hamster did I mention?"),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_drops_relation_requirement_mismatch_evidence() -> None:
    item = _item(
        "alex_atlas_anchor_only",
        "Alex and Project Atlas appeared in the planning summary.",
        deterministic_reasons=("relation_requirement_missing_relation",),
    )
    query = "Did Alex ever mention Project Atlas?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_items_dropped"] == 1
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_drops_relation_requirement_object_mismatch_evidence() -> None:
    item = _item(
        "alex_mentioned_apollo",
        "Alex mentioned Project Apollo during the billing call.",
        deterministic_reasons=("relation_requirement_object_mismatch",),
    )
    query = "Did Alex ever mention Project Atlas?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_items_dropped"] == 1
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_relation_requirement_match_evidence() -> None:
    item = _item(
        "alex_mentioned_atlas",
        "Alex mentioned Project Atlas during the billing call.",
        deterministic_reasons=("relation_requirement_match",),
    )
    query = "Did Alex ever mention Project Atlas?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_domain_exact_evidence_for_relation_shape() -> None:
    item = _item(
        "melanie_pottery_cups",
        "D8:4 Melanie: My kids and I made clay cups in pottery class.",
        deterministic_reasons=(
            "relation_requirement_missing_relation",
            "inventory_list_exact_evidence",
        ),
    )
    query = "What types of pottery have Melanie and her kids made?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_precise_country_destination_answer_support() -> None:
    query = "Which country was Morgan visiting in May 2023?"
    precise_trip = _item(
        "may_country_destination",
        (
            "session_2 date: 7:11 pm on 24 May, 2023\n"
            "D2:1 Morgan: I took my family on a road trip to Vancouver and "
            "spent the weekend near the waterfront."
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:1:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "decomposition_country_destination",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_country_destination",
            },
        },
    )
    vague_trip = _item(
        "undated_country_destination",
        "D9:10 Morgan: I took a road trip to the Rocky Mountains last month.",
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "decomposition_country_destination",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_country_destination",
            },
        },
    )

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(vague_trip, precise_trip),
    )

    assert guarded_items == (precise_trip,)
    assert diagnostics["requirement_guard_status"] == (
        "filtered_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_cause_awareness_exact_evidence() -> None:
    item = _item(
        "charity_race_awareness",
        (
            "D2:2 Caroline: That charity race sounds great. Raising awareness "
            "for mental health is super rewarding."
        ),
        deterministic_reasons=(
            "relation_requirement_missing_relation",
            "cause_awareness_exact_evidence",
        ),
    )
    query = "What did the charity race raise awareness for?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_precise_list_source_sibling_answer_support() -> None:
    item = _item(
        "melanie_book_turn",
        'D6:10 Melanie: I loved reading "Charlotte\'s Web" as a kid.',
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_6:D6:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason_priority": 4,
                "distinctive_term_hits": 6,
                "unique_term_hits": 5,
            },
        },
    )
    query = "What books has Melanie read?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_still_drops_weak_list_source_sibling_relation_mismatch() -> None:
    item = _item(
        "weak_book_turn",
        "D6:9 Melanie talked about reading in general.",
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_6:D6:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason_priority": 1,
                "distinctive_term_hits": 2,
                "unique_term_hits": 2,
            },
        },
    )
    query = "What books has Melanie read?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_precise_food_inventory_exact_turn() -> None:
    item = _item(
        "riley_recipe_turn",
        (
            "D10:9 Riley: I have been testing out dairy-free dessert recipes "
            "for friends and family. Here's a pic of a cake I made recently!"
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:9:turn",
            ),
        ),
        diagnostics={
            "score_signals": {
                "query_expansion_reason": "decomposition_inventory_list",
                "distinctive_term_hits": 4,
                "unique_term_hits": 4,
            },
        },
    )
    query = "What recipes has Riley made?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 0


def test_requirement_guard_keeps_precise_count_source_sibling_answer_support() -> None:
    item = _item(
        "current_tournament_turn",
        (
            "D6:7 Riley: I'm currently participating in the video game "
            "tournament again."
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:7:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 3,
                "unique_term_hits": 3,
            },
        },
    )
    query = "How many video game tournaments has Riley participated in?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_still_drops_weak_count_source_sibling_relation_mismatch() -> None:
    item = _item(
        "generic_tournament_turn",
        "D6:9 Riley talked about weekend practice in general.",
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 1,
                "unique_term_hits": 1,
            },
        },
    )
    query = "How many video game tournaments has Riley participated in?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_precise_temporal_source_sibling_answer_support() -> None:
    item = _item(
        "museum_yesterday_turn",
        (
            "D6:4 Melanie: Yesterday I took the kids to the museum - it was "
            "so cool spending time with them."
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_6:D6:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "distinctive_term_hits": 3,
                "unique_term_hits": 3,
                "source_sibling_closeness": 4,
            },
        },
    )
    query = "When did Melanie go to the museum?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_distant_temporal_source_sibling_answer_evidence() -> None:
    item = _item(
        "picnic_last_week_turn",
        (
            "D6:11 Caroline: My friends and family helped with my transition. "
            "They make all the difference. We even had a picnic last week!"
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_6:D6:11:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 1,
                "unique_term_hits": 1,
                "source_sibling_closeness": 0,
            },
        },
    )
    query = "When did Caroline have a picnic?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_temporal_answer_signal_when_snippet_lost_time_phrase() -> None:
    item = _item(
        "picnic_snippet_turn",
        (
            "D6:11 Caroline: My friends and family helped with my transition. "
            "They make all the difference. We even had a picnic."
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_6:D6:11:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 1,
                "unique_term_hits": 1,
                "source_sibling_closeness": 0,
            },
        },
    )
    query = "When did Caroline have a picnic?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"


def test_restore_exact_source_sibling_answer_evidence_repairs_missing_turn_ref() -> None:
    broad_candidate = _item(
        "session_window",
        "D6:5 D6:6 D6:7 ... D6:1 Caroline discussed transition support.",
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_session",
                source_id="locomo:conversation:session_6",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_6:D6:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_neighbor_chunks",
            "retrieval_sources": ["keyword_neighbor_chunks"],
            "score_signals": {"query_expansion_reason": "decomposition_temporal_answer"},
        },
    )
    exact_source = _item(
        "picnic_last_week_turn",
        (
            "D6:11 Caroline: My friends and family helped with my transition. "
            "They make all the difference. We even had a picnic last week!"
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conversation:session_6:D6:11:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_temporal_answer",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(broad_candidate,),
        source_items=(broad_candidate, exact_source),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conversation:session_6:D6:11:turn" in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_dedupes_same_turn_ref() -> None:
    source_ref = SourceRef(
        source_type="locomo_turn",
        source_id="locomo:conversation:session_6:D6:11:turn",
    )
    session_ref = SourceRef(
        source_type="locomo_session",
        source_id="locomo:conversation:session_6",
    )
    source_items = (
        _item(
            "session_window_a",
            (
                "D6:10 Riley: Did Caroline go to the LGBTQ support group? "
                "D6:11 Caroline: Yes, I went last week."
            ),
            deterministic_reasons=(),
            source_refs=(session_ref, source_ref),
            diagnostics={
                "retrieval_source": "keyword_source_sibling_chunks",
                "retrieval_sources": ["keyword_source_sibling_chunks"],
                "score_signals": {
                    "source_sibling_answer_evidence": 1,
                    "query_expansion_reason": "decomposition_temporal_answer",
                },
            },
        ),
        _item(
            "session_window_b",
            (
                "D6:9 Morgan: Was it before the weekend? "
                "D6:11 Caroline: Yes, I went last week."
            ),
            deterministic_reasons=(),
            source_refs=(session_ref, source_ref),
            diagnostics={
                "retrieval_source": "keyword_source_sibling_chunks",
                "retrieval_sources": ["keyword_source_sibling_chunks"],
                "score_signals": {
                    "source_sibling_answer_evidence": 1,
                    "query_expansion_reason": "decomposition_temporal_answer",
                },
            },
        ),
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=source_items,
    )

    repaired_turn_items = [
        item
        for item in restored
        if item.source_refs and item.source_refs[0].source_id == source_ref.source_id
    ]
    assert len(repaired_turn_items) == 1
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1
    assert diagnostics["exact_source_sibling_answer_evidence_repair_existing"] == 1


def test_restore_exact_source_sibling_answer_evidence_skips_existing_exact_body() -> None:
    source_ref = SourceRef(
        source_type="locomo_turn",
        source_id="locomo:conversation:session_6:D6:11:turn",
    )
    existing = _item(
        "existing_exact_turn",
        "D6:11 Caroline: Yes, I went last week.",
        deterministic_reasons=(),
        source_refs=(source_ref,),
        diagnostics={
            "retrieval_source": "exact_source_ref_hydration",
            "retrieval_sources": ["exact_source_ref_hydration"],
        },
    )
    source_item = _item(
        "session_window",
        (
            "D6:10 Riley: Did Caroline go to the LGBTQ support group? "
            "D6:11 Caroline: Yes, I went last week."
        ),
        deterministic_reasons=(),
        source_refs=(source_ref,),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_temporal_answer",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(existing,),
        source_items=(source_item,),
    )

    assert restored == (existing,)
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 0
    assert diagnostics["exact_source_sibling_answer_evidence_repair_existing"] == 1


def test_restore_exact_source_sibling_answer_evidence_repairs_related_partner_turn() -> None:
    sponsorship_observation = _item(
        "sponsorship_observation",
        (
            "D3:13 Jordan has signed a deal with TrailCore for basketball "
            "shoe and gear and is in talks with HydraFuel for a sponsorship. "
            "Related turns: D3:15.\n"
            "D3:11 Jordan mentioned exploring endorsements."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:synthetic:session_3:observation",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:synthetic:session_3:D3:13:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "charity_brand_sponsorship_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(sponsorship_observation,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    restored_text_by_source_id = {
        ref.source_id: item.text for item in restored for ref in item.source_refs
    }
    assert "locomo:synthetic:session_3:D3:13:turn" in restored_source_ids
    assert "locomo:synthetic:session_3:D3:15:turn" in restored_source_ids
    assert "Related turns: D3:15" in restored_text_by_source_id[
        "locomo:synthetic:session_3:D3:13:turn"
    ]
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_preserves_marker_run_summary() -> None:
    sponsorship_summary = _item(
        "sponsorship_summary",
        (
            "D3:13 D3:15 Jordan: Jordan secures a basketball shoe and gear deal "
            "and is in talks with HydraFuel about a potential sponsorship.\n"
            "D3:17 Jordan is preparing for another game."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_events",
                source_id="locomo:synthetic:session_3:events",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:synthetic:session_3:D3:13:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:synthetic:session_3:D3:15:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "charity_brand_sponsorship_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(sponsorship_summary,),
    )

    restored_text_by_source_id = {
        ref.source_id: item.text for item in restored for ref in item.source_refs
    }
    assert "D3:13 D3:15 Jordan: Jordan secures" in restored_text_by_source_id[
        "locomo:synthetic:session_3:D3:13:turn"
    ]
    assert "D3:13 D3:15 Jordan: Jordan secures" in restored_text_by_source_id[
        "locomo:synthetic:session_3:D3:15:turn"
    ]
    assert "D3:17" not in restored_text_by_source_id[
        "locomo:synthetic:session_3:D3:15:turn"
    ]
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_inference_support_roles() -> None:
    inference_summary = _item(
        "place_recommendation_inference_summary",
        (
            "D4:9 Avery: I went to a real fantasy movie place last year. "
            "The tour was amazing, and I would love to explore more places like that someday.\n"
            "D8:1 Avery: I got accepted into a study abroad program and am "
            "off to Ireland for a semester.\n"
            "D8:3 Avery: I read an article about Ireland.\n"
            "D12:5 Avery: Definitely Aurora Quest! It is my favorite fantasy "
            "film and never gets old."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:3:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_12:D12:5:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "decomposition_inference_support",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_inference_support",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(inference_summary,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert restored_source_ids == {
        "locomo:conv-fixture:session_4:D4:9:turn",
        "locomo:conv-fixture:session_8:D8:1:turn",
        "locomo:conv-fixture:session_12:D12:5:turn",
    }
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 3


def test_restore_exact_source_sibling_answer_evidence_prioritizes_pet_date_anchor_before_cap(
) -> None:
    filler_refs = tuple(
        SourceRef(
            source_type="locomo_turn",
            source_id=f"locomo:conv-fixture:session_9:D9:{index}:turn",
        )
        for index in range(100, 270)
    )
    pet_window = _item(
        "session_9_pet_window",
        (
            "session_9 observations\n"
            "D9:2 Dana: Dana has been revising and perfecting a recipe for "
            "her family. Related turns: D9:4.\n"
            "D9:4 Dana: Dana has a stuffed animal dog named Pippa that was "
            "a gift from Sam. Related turns: D9:6 D9:8."
        ),
        deterministic_reasons=(),
        source_refs=(
            *filler_refs,
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "pet_acquisition_date_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(pet_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_9:D9:2:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_9:D9:4:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_9:D9:100:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_animal_care_repairs() -> None:
    care_window = _item(
        "session_5_care_window",
        (
            "D5:4 Nate image caption: a photography of two tortoises laying on "
            "the ground in a jungle.\n"
            "D5:8 Nate: No, not really. Just keep their area clean, feed them "
            "properly, and make sure they get enough light. It's actually kind of fun."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:8:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "animal_care_instruction_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(care_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_5:D5:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_5:D5:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_volunteering_people_repairs() -> None:
    volunteering_window = _item(
        "session_6_volunteering_window",
        (
            "D6:4 Riley volunteers at a neighborhood shelter on weekends.\n"
            "D6:8 Riley: One of the shelter residents, Morgan, wrote a letter "
            "expressing gratitude for the support they receive."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:8:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "volunteering_people_inventory_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(volunteering_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_6:D6:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_exact_turn_hydration_requests_marker_stub_source_refs() -> None:
    source_group = _item(
        "session_1_activity_window",
        (
            "D1:28 ... "
            "D1:24 Jon image caption: a photo of dancers on a stage. "
            "D1:24 Jon visual query: group dancers performing on stage. "
            "D1:25 Gina: They look graceful."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:28:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:24:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "activity_competition_evidence_bridge",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "activity_competition_evidence_bridge",
            },
        },
    )

    requests = _exact_turn_source_ref_hydration_requests((source_group,))

    assert requests == {
        "locomo:conv-fixture:session_1:D1:28:turn": (
            "activity_competition_evidence_bridge"
        )
    }


def test_exact_turn_hydration_skips_wrong_country_destination_stub_ref() -> None:
    source_group = _item(
        "session_2_country_destination_window",
        (
            "session_2 date: May 2023\n"
            "D2:1 Morgan: I took a roadtrip to Vancouver and spent the week "
            "walking around the waterfront.\n"
            "D2:10 ..."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "decomposition_country_destination",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_country_destination",
                "source_sibling_answer_evidence_query": (
                    "Which country was Morgan visiting in May 2023?"
                ),
            },
        },
    )

    assert _exact_turn_source_ref_hydration_requests((source_group,)) == {}


def test_exact_turn_hydration_skips_existing_body_but_allows_previous_context() -> None:
    hydrated_turn = _item(
        "activity_turn",
        "D1:28 Jon: Yeah, awesome! Glad to be part of it.",
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:28:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "activity_competition_evidence_bridge",
            },
        },
    )

    assert _exact_turn_source_ref_hydration_requests((hydrated_turn,)) == {
        "locomo:conv-fixture:session_1:D1:27:turn": (
            "activity_competition_evidence_bridge"
        )
    }


def test_exact_turn_hydration_drops_unanswerable_next_response_continuation() -> None:
    question_turn = _item(
        "place_question",
        "D4:2 Mira: Where did you go?",
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:2:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "trip_destination_bridge",
            },
        },
    )

    request_plan = _exact_turn_source_ref_hydration_request_plan((question_turn,))
    requested_source_id = "locomo:conv-fixture:session_4:D4:3:turn"

    assert requested_source_id in request_plan.next_answer_source_ids
    assert not _should_use_exact_source_ref_hydration_item(
        source_id=requested_source_id,
        request_plan=request_plan,
        answer_evidence=False,
        text="D4:3 Rowan: Anyway, I started painting again.",
    )
    assert _should_use_exact_source_ref_hydration_item(
        source_id=requested_source_id,
        request_plan=request_plan,
        answer_evidence=True,
        text="D4:3 Rowan: I went to Chicago for the weekend.",
    )


def test_exact_turn_hydration_requires_previous_context_question_or_request() -> None:
    answer_turn = _item(
        "anaphoric_answer",
        "D2:9 Morgan: Yes, they are.",
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "activity_competition_evidence_bridge",
            },
        },
    )

    request_plan = _exact_turn_source_ref_hydration_request_plan((answer_turn,))
    requested_source_id = "locomo:conv-fixture:session_2:D2:8:turn"

    assert requested_source_id in request_plan.previous_question_source_ids
    assert not _should_use_exact_source_ref_hydration_item(
        source_id=requested_source_id,
        request_plan=request_plan,
        answer_evidence=False,
        text="D2:8 Riley: I watched those dancers perform yesterday.",
    )
    assert _should_use_exact_source_ref_hydration_item(
        source_id=requested_source_id,
        request_plan=request_plan,
        answer_evidence=False,
        text="D2:8 Riley: Are they yours at the festival?",
    )


def test_restore_exact_source_sibling_answer_evidence_derives_country_destination_marker() -> None:
    source_group = _item(
        "session_2_country_destination_window",
        (
            "session_2 date: May 2023\n"
            "D2:1 Morgan: I took a roadtrip to Vancouver and spent the week "
            "walking around the waterfront.\n"
            "D2:10 Morgan: Painting helps me handle a stressful week."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "query_expansion_reason": "decomposition_country_destination",
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_country_destination",
                "source_sibling_answer_evidence_query": (
                    "Which country was Morgan visiting in May 2023?"
                ),
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(source_group,),
    )

    restored_by_source_id = {
        str(ref.source_id): item for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_2:D2:1:turn" in restored_by_source_id
    assert "locomo:conv-fixture:session_2:D2:10:turn" not in restored_by_source_id
    restored_text = restored_by_source_id[
        "locomo:conv-fixture:session_2:D2:1:turn"
    ].text
    assert "May 2023" in restored_text
    assert "roadtrip to Vancouver" in restored_text
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_support_origin_repairs() -> None:
    support_window = _item(
        "session_3_support_window",
        (
            "D3:5 Riley: I have been blessed with love and support throughout "
            "this journey, and I want to pass it on to others.\n"
            "D3:11 Riley: My friends, family, and mentors are my rocks and "
            "give me strength to push on."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_3:D3:11:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_3:D3:5:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "support_origin_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(support_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_3:D3:5:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_3:D3:11:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_business_start_reason_repairs(
) -> None:
    business_window = _item(
        "business_start_window",
        (
            "D1:2 Avery: I lost my old job, so I have been thinking about "
            "what comes next.\n"
            "D1:4 Avery: I'm starting a dance studio 'cause I'm passionate "
            "about dancing and want to share it with others.\n"
            "D1:7 Avery: The schedule has been busy this week.\n"
            "D6:8 Blake: I'm passionate about fashion trends and finding "
            "unique pieces. I wanted to blend my love for dance and fashion, "
            "so it was a perfect match."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:7:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:8:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "business_start_reason_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(business_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_1:D1:4:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_1:D1:2:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_1:D1:7:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_public_office_repairs() -> None:
    office_window = _item(
        "office_window",
        (
            "D7:2 John: I'm running for office again. It's been a wild ride, "
            "but I'm more excited than ever.\n"
            "D7:3 Maria: Congrats, John! What made you decide to run again?\n"
            "D7:4 John: After my last run, I saw the impact I could make in "
            "the community through politics. It's rewarding to work towards "
            "positive changes and a better future."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:3:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "public_office_service_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(office_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_7:D7:4:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_7:D7:2:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_7:D7:3:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_recognition_repairs() -> None:
    recognition_window = _item(
        "recognition_window",
        (
            "D29:1 Maria: Hey John, I volunteered at the homeless shelter and "
            "they gave me a medal! It was humbling and I'm really glad I could help.\n"
            "D29:2 John: Congrats on the recognition. It's touching to see "
            "how much you're doing to help out.\n"
            "D29:10 John: We raised awareness and funds for domestic abuse victims."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_29:D29:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_29:D29:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_29:D29:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "recognition_award_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(recognition_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_29:D29:1:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_29:D29:2:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_29:D29:10:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_repairs_visual_certificate() -> None:
    certificate_window = _item(
        "certificate_window",
        (
            "D9:2 John: Hey Maria! Since we spoke last, I've had quite the adventure.\n"
            "image caption: a photo of a certificate of completion "
            "of a university degree\n"
            "visual query: diploma university\n"
            "D9:4 John: Thanks, Maria! It was quite a journey, but definitely "
            "worth it. I graduated last week."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "recognition_award_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(certificate_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_9:D9:2:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_9:D9:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_pet_adjustment_repairs() -> None:
    pet_window = _item(
        "pet_adjustment_window",
        (
            "D31:2 Maria: I just adopted this cute pup from a shelter last week.\n"
            "D31:4 John: What name did you pick for her?\n"
            "D31:10 Maria: Awesome, John! The little one is doing great - "
            "learning commands and house training. image caption: a photo of a dog."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_31:D31:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_31:D31:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_31:D31:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "pet_adjustment_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(pet_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_31:D31:10:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_31:D31:2:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_31:D31:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_lifestyle_inference_repairs() -> None:
    lifestyle_window = _item(
        "lifestyle_window",
        (
            "D7:1 Alex: The dogs liked their new beds in the apartment.\n"
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance.\n"
            "D9:4 Alex: The dogs ate dinner and took a nap."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D7:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:5:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D9:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D10:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "original_query",
                "source_sibling_answer_evidence_query": (
                    "What can Alex do to improve his stress and accommodate "
                    "his living situation with his dogs?"
                ),
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(lifestyle_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_8:D8:5:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_8:D7:1:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_8:D9:4:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_8:D10:9:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_ignores_marker_run_headers() -> None:
    lifestyle_window = _item(
        "lifestyle_window",
        (
            "D8:5 D8:6 ... D8:1 Alex: Hi, it has been a while.\n"
            "D8:4 Sam: Have you been to the park lately?\n"
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance.\n"
            "D8:6 Sam: That sounds frustrating."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:5:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:6:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:1:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "original_query",
                "source_sibling_answer_evidence_query": (
                    "What can Alex do to improve his stress and accommodate "
                    "his living situation with his dogs?"
                ),
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(lifestyle_window,),
    )

    assert len(restored) == 1
    assert restored[0].source_refs[0].source_id == (
        "locomo:conv-fixture:session_8:D8:5:turn"
    )
    assert restored[0].text != "D8:5"
    assert "hard to find open spaces in the city" in restored[0].text
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_planning_tool_repairs() -> None:
    tool_window = _item(
        "planning_tool_window",
        (
            "D13:9 Jon visual query: whiteboard dance moves.\n"
            "D13:10 Gina: Nice one, Jon! How've you been using it?\n"
            "D13:11 Jon: I'm using it to stay organized and motivated. It sets "
            "goals, tracks my achievements and helps me find areas to improve. "
            "image caption: a photo of a notebook with a calendar on it.\n"
            "D16:9 Gina: No worries, Jon! image caption: a photo of a notepad."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_13:D13:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_13:D13:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_13:D13:11:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_16:D16:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "planning_tool_use_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(tool_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_13:D13:11:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_13:D13:9:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_13:D13:10:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_16:D16:9:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_customer_experience_repairs() -> None:
    customer_window = _item(
        "customer_experience_window",
        (
            "D3:8 Gina: I want them to feel like they're in a cool oasis.\n"
            "D3:9 Jon: Creating a special experience for customers is the key "
            "to making them feel welcome and coming back. I think you can "
            "create that space you're imagining.\n"
            "D3:10 Gina: I can make a special shopping experience for my customers."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_3:D3:8:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_3:D3:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_3:D3:10:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "customer_experience_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(customer_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_3:D3:9:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_3:D3:8:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_3:D3:10:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_grand_opening_repairs() -> None:
    opening_window = _item(
        "grand_opening_window",
        (
            "D15:11 Jon: Thanks! Your pride and support mean a lot.\n"
            "D15:12 Gina: I'll be right by your side, Jon. Let's live it up "
            "and make some great memories tomorrow. So excited! image caption: "
            "a photo of a group of people in a dance studio.\n"
            "D15:13 Jon: Yeah! Let's make some awesome memories tomorrow at the "
            "grand opening!"
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_15:D15:11:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_15:D15:12:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_15:D15:13:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "grand_opening_support_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(opening_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_15:D15:12:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_15:D15:11:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_15:D15:13:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_travel_country_repairs() -> None:
    travel_window = _item(
        "travel_country_window",
        (
            "D8:12 Maria: The picture reminds me of decorating at home.\n"
            "D8:15 Maria: I got the idea from that trip to England a few "
            "years ago and was mesmerized by the castles.\n"
            "D18:3 Maria: My family and I went on a road trip to Oregon.\n"
            "D13:24 Maria: Last year I took a solo trip in Spain and "
            "appreciated the small moments more."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:12:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:15:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_18:D18:3:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_13:D13:24:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "travel_country_inventory_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(travel_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_8:D8:15:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_13:D13:24:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_8:D8:12:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_18:D18:3:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_prioritizes_temporal_country_repairs(
) -> None:
    noise_items = tuple(
        _item(
            f"noise_repair_{index:02d}",
            f"D{index}:1 Avery: Generic answer-evidence candidate {index}.",
            deterministic_reasons=(),
            source_refs=(
                SourceRef(
                    source_type="locomo_turn",
                    source_id=(
                        f"locomo:conv-fixture:session_{index}:D{index}:1:turn"
                    ),
                ),
            ),
            diagnostics={
                "retrieval_source": "keyword_source_sibling_chunks",
                "retrieval_sources": ["keyword_source_sibling_chunks"],
                "score_signals": {"source_sibling_answer_evidence": 1},
            },
        )
        for index in range(30, 79)
    )
    country_window = _item(
        "z_country_destination_window",
        (
            "session_2 date: 7:11 pm on 24 May, 2023\n"
            "D2:10 Avery: I have been thinking about trying painting.\n"
            "D2:1 Avery: I took my family on a road trip to Vancouver."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:1:turn",
            ),
        ),
        diagnostics={
            "query_expansion_reason": "decomposition_country_destination",
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_country_destination",
                "source_sibling_answer_evidence_query": (
                    "Which country was Avery visiting in May 2023?"
                ),
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(*noise_items, country_window),
    )

    restored_source_ids = [ref.source_id for item in restored for ref in item.source_refs]
    country_repair = next(
        item
        for item in restored
        if any(
            ref.source_id == "locomo:conv-fixture:session_2:D2:1:turn"
            for ref in item.source_refs
        )
    )
    assert "locomo:conv-fixture:session_2:D2:1:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_2:D2:10:turn" not in restored_source_ids
    assert "24 May, 2023" in country_repair.text
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 48


def test_restore_exact_source_sibling_answer_evidence_filters_common_interest_repairs() -> None:
    interest_window = _item(
        "common_interest_window",
        (
            "D1:10 Jo: Besides writing, I enjoy watching movies and reading.\n"
            "D1:11 Sam: Playing video games and watching movies are my main hobbies.\n"
            "D7:4 Jo: It is fun to meet people who share your interests.\n"
            "D10:9 Jo: I have been testing out dairy-free dessert recipes.\n"
            "D20:2 Jo: I revised one of my old recipes and made this cake."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:11:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_20:D20:2:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "hobby_interest_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(interest_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_1:D1:10:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_1:D1:11:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_10:D10:9:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_20:D20:2:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_7:D7:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 4


def test_restore_exact_source_sibling_answer_evidence_filters_rejection_count_repairs() -> None:
    screenplay_window = _item(
        "screenplay_rejection_window",
        (
            "D14:1 Jo: I heard back about my first screenplay.\n"
            "D14:5 Jo: It was a generic rejection letter from a major company.\n"
            "D20:4 Jo: Writing another script has kept me busy.\n"
            "D24:12 Jo: I had another rejection from a production company."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_14:D14:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_14:D14:5:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_20:D20:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_24:D24:12:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "screenplay_count_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(screenplay_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_14:D14:5:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_24:D24:12:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_14:D14:1:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_20:D20:4:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_preference_repairs() -> None:
    music_window = _item(
        "session_5_music_window",
        (
            "D5:7 Morgan: The outdoor festival was crowded.\n"
            "D5:9 Morgan: I'm a fan of classical music like Bach and Mozart, "
            "and I also enjoy modern songs."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:7:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "classical_music_preference_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(music_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_5:D5:9:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_5:D5:7:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_reminder_repairs() -> None:
    reminder_window = _item(
        "session_4_reminder_window",
        (
            "D4:3 Riley: I painted a lake scene last weekend.\n"
            "D4:5 Riley: The handmade bowl has sentimental value. Its pattern "
            "and colors remind me of art and self-expression."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:3:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:5:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "sentimental_reminder_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(reminder_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:5:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:3:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 1


def test_restore_exact_source_sibling_answer_evidence_filters_outdoor_preference_repairs() -> None:
    outdoor_window = _item(
        "session_10_outdoor_window",
        (
            "D10:10 Morgan: We picked up snacks for the weekend.\n"
            "D10:12 Morgan: We always look forward to our family camping trip. "
            "We roast marshmallows around the campfire; it is the highlight "
            "of our summer.\n"
            "D10:14 Morgan: I'll always remember the camping trip when we saw "
            "a meteor shower and felt at one with the universe."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:10:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:12:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:14:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "outdoor_preference_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(outdoor_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_10:D10:12:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_10:D10:14:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_10:D10:10:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_children_preference_repairs() -> None:
    preference_window = _item(
        "session_children_preference_window",
        (
            "D4:7 Avery: We packed snacks for the drive.\n"
            "D4:8 Avery: The younger kids love nature, campfires, and "
            "hiking outdoors.\n"
            "D6:6 Avery: They were stoked for the dinosaur exhibit. "
            "They love learning about animals and the bones were cool.\n"
            "D6:7 Avery: I need to update the family calendar."
        ),
        deterministic_reasons=(),
        source_refs=(
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
                source_id="locomo:conv-fixture:session_6:D6:6:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_6:D6:7:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "children_preference_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(preference_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:6:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:7:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:7:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_derives_children_list_refs_from_groups(
) -> None:
    preference_window = _item(
        "session_children_preference_observations",
        (
            "D4:7 Avery: We packed snacks for the drive.\n"
            "D4:8 Avery: The younger kids love nature, campfires, and "
            "hiking outdoors.\n"
            "D6:6 Avery: They were stoked for the dinosaur exhibit. "
            "They love learning about animals and the bones were cool.\n"
            "D6:7 Avery: I need to update the family calendar."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_4:observation",
            ),
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_6:observation",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "children_preference_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(preference_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:6:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:7:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_6:D6:7:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_activity_repairs() -> None:
    activity_window = _item(
        "session_activity_window",
        (
            "D5:4 Avery: I just signed up for a pottery class yesterday. "
            "It lets me express myself and get creative.\n"
            "D5:6 Avery: I'm a big fan of pottery; the creativity is awesome.\n"
            "D9:1 Avery: I went camping with my family and enjoyed unplugging "
            "with the kids.\n"
            "D1:18 Avery: I'm off to go swimming with the kids."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:4:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_5:D5:6:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_1:D1:18:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_activity_participation",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(activity_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_5:D5:4:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_9:D9:1:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_1:D1:18:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_5:D5:6:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 3


def test_restore_exact_source_sibling_answer_evidence_derives_activity_list_refs_from_groups(
) -> None:
    activity_window = _item(
        "session_activity_observations",
        (
            "D5:4 Avery: I just signed up for a pottery class yesterday. "
            "It lets me express myself and get creative.\n"
            "D5:6 Avery: I'm a big fan of pottery; the creativity is awesome.\n"
            "D9:1 Avery: I went camping with my family and enjoyed unplugging "
            "with the kids.\n"
            "D1:18 Avery: I'm off to go swimming with the kids."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_5:observation",
            ),
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_9:observation",
            ),
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_1:observation",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_activity_participation",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(activity_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_5:D5:4:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_9:D9:1:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_1:D1:18:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_5:D5:6:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 3


def test_restore_exact_source_sibling_answer_evidence_derives_activity_duration_marker_ref(
) -> None:
    duration_window = _item(
        "session_duration_observation",
        (
            "session_4 observations\n"
            "D4:5 Jordan: Jordan likes gallery openings and sketchbooks. "
            "Related turns: D4:8.\n"
            "D4:6 Jordan: Jordan has been creating art since the age of 17. "
            "Related turns: D4:9.\n"
            "D4:8 Riley: Riley has been creating art for seven years. "
            "Related turns: D4:6."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:5:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:8:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "decomposition_activity_duration",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(duration_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:6:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:5:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 2


def test_restore_exact_source_sibling_answer_evidence_filters_exercise_companion_repairs() -> None:
    activity_window = _item(
        "session_exercise_window",
        (
            "D4:2 Riley: I started a weekend yoga class with a colleague. "
            "It helps me feel more flexible.\n"
            "D4:3 Riley: Yoga improves my focus and breathing after work.\n"
            "D7:8 Riley: My colleague Alex invited me to a beginner yoga class.\n"
            "D7:9 Riley: The studio has calm music and good lighting.\n"
            "D8:5 Riley: I started vinyasa yoga at a small studio downtown.\n"
            "D8:6 Riley: Yoga helps me stretch after work."
        ),
        deterministic_reasons=(),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:3:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:8:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_7:D7:9:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:5:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_8:D8:6:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "exercise_activity_inventory_bridge",
            },
        },
    )

    restored, diagnostics = _restore_exact_source_sibling_answer_evidence_items(
        candidates=(),
        source_items=(activity_window,),
    )

    restored_source_ids = {
        ref.source_id for item in restored for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:2:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_7:D7:8:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_8:D8:5:turn" in restored_source_ids
    assert "locomo:conv-fixture:session_4:D4:3:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_7:D7:9:turn" not in restored_source_ids
    assert "locomo:conv-fixture:session_8:D8:6:turn" not in restored_source_ids
    assert diagnostics["exact_source_sibling_answer_evidence_repair_added"] == 3


def test_requirement_guard_still_drops_weak_temporal_source_sibling_relation_mismatch() -> None:
    item = _item(
        "generic_recent_turn",
        "D6:9 Melanie said the week was busy but did not mention the museum.",
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_6:D6:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "distinctive_term_hits": 1,
                "unique_term_hits": 1,
                "source_sibling_closeness": 1,
            },
        },
    )
    query = "When did Melanie go to the museum?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_precise_activity_companion_source_sibling() -> None:
    item = _item(
        "activity_companion_turn",
        (
            "D4:2 Riley: My colleague Alex invited me to a beginner yoga class "
            "after work."
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:2:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "exercise_activity_inventory_bridge",
            },
        },
    )
    query = "Who did Riley go to yoga with?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 0


def test_requirement_guard_keeps_visual_certificate_source_sibling_answer_evidence() -> None:
    item = _item(
        "visual_certificate_turn",
        (
            "D9:2 John: Hey Maria! I finally have it framed. "
            "image caption: a photo of a certificate of completion of a university degree. "
            "visual query: diploma university"
        ),
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:2:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "recognition_award_bridge",
            },
        },
    )
    query = "What did Maria receive a certificate for?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 0


def test_requirement_guard_still_drops_generic_certificate_relation_mismatch() -> None:
    item = _item(
        "generic_certificate_turn",
        "D9:4 John: I graduated from university and feel proud.",
        deterministic_reasons=("relation_requirement_missing_relation",),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_9:D9:4:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "query_expansion_reason": "recognition_award_bridge",
            },
        },
    )
    query = "What did Maria receive a certificate for?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == (
        "dropped_relation_requirement_mismatch"
    )
    assert diagnostics["requirement_guard_relation_mismatch_drop_count"] == 1


def test_requirement_guard_drops_missing_count_answer_shape_evidence() -> None:
    item = _item(
        "generic_pet_note",
        "Gina loves pets and volunteers at the shelter.",
        deterministic_reasons=("explicit_answer_shape_missing",),
    )
    query = "How many pets does Gina have?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == "dropped_missing_count_answer_shape"
    assert diagnostics["requirement_guard_items_dropped"] == 1
    assert diagnostics["requirement_guard_count_answer_shape_missing_drop_count"] == 1


def test_requirement_guard_keeps_count_answer_shape_evidence() -> None:
    item = _item(
        "enumerated_pet_note",
        "Gina has a rescue dog, a cat, and a turtle at home.",
        deterministic_reasons=("explicit_requirement_covered",),
    )
    query = "How many pets does Gina have?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_requirement_guard_keeps_approximate_total_count_shape_evidence() -> None:
    item = _item(
        "approximate_visit_count",
        "Morgan made several visits to the clinic for follow-up care.",
        deterministic_reasons=("explicit_requirement_covered",),
    )
    query = "What was the total for Morgan's clinic visits?"

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def _item(
    item_id: str,
    text: str,
    *,
    deterministic_reasons: tuple[str, ...],
    source_refs: tuple[SourceRef, ...] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> ContextItem:
    item_diagnostics = {
        "retrieval_source": "keyword_chunks",
        "retrieval_sources": ["keyword_chunks"],
        "provenance": {
            "deterministic_rerank_reasons": list(deterministic_reasons),
        },
    }
    if diagnostics:
        item_diagnostics.update(diagnostics)
        provenance = dict(item_diagnostics.get("provenance", {}))
        provenance["deterministic_rerank_reasons"] = list(deterministic_reasons)
        item_diagnostics["provenance"] = provenance
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.7,
        source_refs=source_refs or (SourceRef(source_type="document", source_id="doc"),),
        diagnostics=item_diagnostics,
    )
