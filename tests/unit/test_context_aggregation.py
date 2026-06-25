from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_core.application import BuildContextQuery
from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slots,
)
from infinity_context_core.application.context_query_expansion import build_query_expansion_plan
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.use_cases.build_context import (
    _aggregation_evidence_text,
    _aggregation_source_kind_rank,
    _chunk_context_item,
    _dedupe_chunks_by_id,
    _is_dialogue_visual_reference_source_sibling,
    _is_pottery_type_observation_companion,
    _keyword_aggregation_chunk_items,
    _keyword_aggregation_query_kind,
    _prioritized_chunks_for_source_groups,
    _ranked_keyword_chunk_scores,
    _selected_keyword_prompt_items,
    _source_group_seed_turns,
    _source_sibling_candidate_rank_key,
    _source_sibling_companion_extra_slot,
    _source_sibling_distant_answer_evidence_rank,
    _source_sibling_marker_coverage_count,
    _source_sibling_rank,
    _source_sibling_relevance_allowed,
    _source_sibling_score,
    _source_sibling_score_cap,
    _SourceSiblingRank,
    _strict_query_term_hits,
    _strict_query_term_variant_sets,
    _strict_query_variant_hits,
    _strict_query_window_match_counts,
    _weighted_aggregation_query_variant_sets,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_aggregation_evidence_text_prefers_dialogue_window_with_stronger_query_terms() -> None:
    text = "\n".join(
        [
            "D10:1 Caroline: Hey Melanie, anything new in 2023?",
            "D10:2 Melanie: Work has been busy.",
            "D10:3 Caroline: Glad to hear from you.",
            "D10:8 Melanie: We went to the beach recently and the kids had a blast.",
            "D10:9 Caroline: Sounds fun. What was the best part?",
            "D10:10 Melanie: We only go once or twice a year.",
            "D10:11 Caroline: Nice.",
        ]
    )

    snippet = _aggregation_evidence_text(
        query="How many times has Melanie gone to the beach in 2023?",
        text=text,
    )

    assert "D10:8 Melanie:" in snippet
    assert "beach recently" in snippet
    assert "D10:10 Melanie:" in snippet
    assert "D10:1 Caroline:" not in snippet


def test_keyword_aggregation_chunks_still_collect_count_queries() -> None:
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query("How many hikes has Joanna been on?"),
        seed_chunks=(
            _chunk(
                "count_a",
                "D11:5 Joanna went on a hike near the waterfall. D11:6 Joanna loved the trail.",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "count"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert items[0].diagnostics["retrieval_source"] == "keyword_aggregation_chunks"


def test_keyword_aggregation_chunks_collect_list_queries() -> None:
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query("What items has Melanie bought?"),
        seed_chunks=(
            _chunk(
                "list_a",
                (
                    "D19:2 Melanie bought family figurines yesterday. "
                    "D19:3 Caroline asked whether she bought anything else. "
                    "D7:18 Melanie got some new shoes for work."
                ),
                source_external_id="locomo:conv-26:session_19:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "family figurines" in items[0].text
    assert "new shoes" in items[0].text


def test_keyword_aggregation_query_kind_handles_band_list_queries() -> None:
    assert _keyword_aggregation_query_kind("What bands has Melanie seen?") == "list"
    assert (
        _keyword_aggregation_query_kind("What musical artists/bands has Melanie seen?")
        == "list"
    )


def test_keyword_aggregation_query_kind_handles_type_list_queries() -> None:
    assert _keyword_aggregation_query_kind("What types of pottery have Melanie made?") == "list"
    assert _keyword_aggregation_query_kind("Which kinds of documents did Alex save?") == "list"


def test_lgbtq_event_answer_slots_require_nearby_lgbtq_context() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"

    assert aggregation_answer_slots(
        query=query,
        text=(
            "Caroline mentored LGBTQ youth, joined a new LGBTQ activist group, "
            "and organized an LGBTQ art show."
        ),
    ) == frozenset(
        {
            "lgbtq_activist_group",
            "lgbtq_art_show",
            "lgbtq_mentorship_program",
        }
    )
    assert aggregation_answer_slots(
        query=query,
        text="Caroline attended a general art show and later mentored students.",
    ) == frozenset()


def test_inventory_answer_slots_cover_real_locomo_places_and_causes() -> None:
    assert aggregation_answer_slots(
        query="Where has Maria made friends?",
        text=(
            "D4:1 Maria is now friends with a fellow volunteer. "
            "D19:1 Maria joined a gym and the people are awesome. "
            "D14:10 Maria joined a nearby church and community."
        ),
    ) == frozenset(
        {
            "friend_place_church",
            "friend_place_gym",
            "friend_place_volunteering",
        }
    )
    assert aggregation_answer_slots(
        query="What European countries has Maria been to?",
        text="D13:24 Maria took a solo trip to Spain. D8:15 Maria visited England.",
    ) == frozenset({"travel_country_england", "travel_country_spain"})
    assert aggregation_answer_slots(
        query="What shelters does Maria volunteer at?",
        text=(
            "D2:1 Maria donated her car to a homeless shelter. "
            "D17:12 Maria started volunteering at a local dog shelter."
        ),
    ) == frozenset({"volunteer_shelter_dog", "volunteer_shelter_homeless"})
    assert aggregation_answer_slots(
        query="What causes does John feel passionate about supporting?",
        text=(
            "D15:3 John is passionate about veterans and their rights. "
            "D12:5 John supports education reform and infrastructure development."
        ),
    ) == frozenset({"cause_education", "cause_infrastructure", "cause_veterans"})


def test_keyword_aggregation_query_kind_handles_inventory_list_queries() -> None:
    cases = [
        "What European countries has Maria been to?",
        "What areas of the U.S. has John been to or is planning to go to?",
        "What shelters does Maria volunteer at?",
        "What causes does John feel passionate about supporting?",
        "What people has Maria met and helped while volunteering?",
        "What martial arts has John done?",
        "Where has Maria made friends?",
    ]

    for query in cases:
        assert _keyword_aggregation_query_kind(query) == "list"
    assert _keyword_aggregation_query_kind("Where did Caroline move from 4 years ago?") != "list"


def test_keyword_aggregation_source_kind_prefers_observation_over_raw_session() -> None:
    raw = _chunk("raw", "D1:1 raw", source_external_id="locomo:conv-26:session_12")
    observation = _chunk(
        "observation",
        "D12:14 related observation",
        source_external_id="locomo:conv-26:session_12:observation",
    )
    turn = _chunk(
        "turn",
        "D12:4 exact turn",
        source_external_id="locomo:conv-26:session_12:D12:4:turn",
    )

    assert _aggregation_source_kind_rank(observation) < _aggregation_source_kind_rank(turn)
    assert _aggregation_source_kind_rank(turn) < _aggregation_source_kind_rank(raw)


def test_aggregation_evidence_text_preserves_omitted_source_markers() -> None:
    text = "\n".join(
        [
            "D12:2 D12:4 Melanie: Melanie finished another pottery project.",
            "D12:6 D12:8 Melanie: Art has been a source of comfort.",
            "D12:9 D12:10 Melanie: Life is tough but happy moments matter.",
            "D12:11 D12:12 Melanie: Caroline has been supportive.",
            "D12:13 Melanie: Caroline appreciates their friendship.",
            "D12:14 D12:16 Melanie: Melanie appreciates Caroline's friendship.",
        ]
    )

    snippet = _aggregation_evidence_text(
        query="What types of pottery have Melanie and her kids made?",
        text=text,
    )

    assert "D12:4 Melanie" in snippet
    assert "omitted source evidence markers:" in snippet
    assert "D12:14" in snippet


def test_aggregation_evidence_text_reuses_precomputed_query_variants() -> None:
    query = "What types of pottery have Melanie and her kids made?"
    identity_terms = frozenset({"melanie"})
    text = "\n".join(
        [
            "D5:1 Caroline: Did the kids make anything this week?",
            "D5:2 Melanie: They made a clay bowl in the pottery class.",
            "D5:3 Caroline: That is great.",
            "D8:4 Melanie: Later we made a painted cup together at home.",
        ]
    )
    query_variants = _weighted_aggregation_query_variant_sets(
        query,
        identity_terms=identity_terms,
    )

    assert _aggregation_evidence_text(
        query=query,
        text=text,
        identity_terms=identity_terms,
        query_variant_sets=query_variants,
    ) == _aggregation_evidence_text(
        query=query,
        text=text,
        identity_terms=identity_terms,
    )


def test_keyword_aggregation_chunks_preserve_multiple_distinct_list_windows() -> None:
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query("What activities has Melanie done with her family?"),
        seed_chunks=(
            _chunk(
                "list_multi_window",
                (
                    "D1:1 Caroline: How was your week? "
                    "D1:2 Melanie: We went camping with my family and roasted marshmallows. "
                    "D1:3 Caroline: That sounds relaxing. "
                    "D1:4 Melanie: Work has been busy. "
                    "D1:5 Caroline: Same here. "
                    "D1:6 Melanie: The kids had school events. "
                    "D1:7 Caroline: Any creative plans? "
                    "D1:8 Melanie: We painted nature scenes together as a family. "
                    "D1:9 Caroline: Nice. "
                    "D1:10 Melanie: We also went swimming with the kids."
                ),
                source_external_id="locomo:conv-26:session_1:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D1:2 Melanie" in items[0].text
    assert "roasted marshmallows" in items[0].text
    assert "D1:8 Melanie" in items[0].text
    assert "painted nature scenes" in items[0].text
    assert len(items[0].text) < len(
        "D1:1 Caroline: How was your week? "
        "D1:2 Melanie: We went camping with my family and roasted marshmallows. "
        "D1:3 Caroline: That sounds relaxing. "
        "D1:4 Melanie: Work has been busy. "
        "D1:5 Caroline: Same here. "
        "D1:6 Melanie: The kids had school events. "
        "D1:7 Caroline: Any creative plans? "
        "D1:8 Melanie: We painted nature scenes together as a family. "
        "D1:9 Caroline: Nice. "
        "D1:10 Melanie: We also went swimming with the kids."
    )


def test_keyword_aggregation_chunks_use_expansion_query_for_list_evidence_windows() -> None:
    query_text = "What activities has Melanie done with her family?"
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query(query_text),
        query_plan=build_query_expansion_plan(query_text),
        seed_chunks=(
            _chunk(
                "list_expansion_window",
                (
                    "D8:1 Caroline: Hey Mel, what's up? "
                    "D8:2 Melanie: Last Fri I finally took my kids to a pottery workshop. "
                    "We all made our own pots, it was fun and therapeutic! "
                    "D8:3 Caroline: How'd they like it? "
                    "D8:4 Melanie: The kids loved it and made something with clay. "
                    "image caption: a photo of a cup with a dog face on it. "
                    "visual query: kids pottery finished pieces. "
                    "D8:5 Caroline: What other creative projects do you do with them? "
                    "D8:6 Melanie: We love painting together lately."
                ),
                source_external_id="locomo:conv-26:session_8:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D8:4 Melanie" in items[0].text
    assert "kids loved it" in items[0].text
    assert items[0].diagnostics["score_signals"]["query_expansion_reason"] in {
        "decomposition_activity_participation",
        "family_activity_bridge",
        "pottery_type_bridge",
    }


def test_keyword_aggregation_chunks_use_inventory_list_expansion_for_places() -> None:
    query_text = "What European countries has Maria been to?"
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query(query_text),
        query_plan=build_query_expansion_plan(query_text),
        seed_chunks=(
            _chunk(
                "country_inventory",
                (
                    "D8:15 Maria went to England and loved traveling abroad. "
                    "D8:16 John asked whether she had other trips planned. "
                    "D13:24 Maria visited Spain during a school trip."
                ),
                source_external_id="locomo:conv-41:session_13:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D8:15 Maria" in items[0].text
    assert "D13:24 Maria" in items[0].text


def test_inventory_aggregation_ignores_identity_and_scaffold_terms() -> None:
    query_terms = _weighted_aggregation_query_variant_sets(
        (
            "maria countries inventory list evidence observed mentioned answer options "
            "country countries europe european england spain abroad solo trip travel visited"
        ),
        identity_terms=frozenset({"maria"}),
    )

    assert (
        _strict_query_window_match_counts(
            text="Maria inventory evidence observed mentioned answer options.",
            query_variant_sets=query_terms,
        )
        == (0.0, 0.0)
    )
    assert _strict_query_window_match_counts(
        text="D13:24 Maria took a solo trip in Spain.",
        query_variant_sets=query_terms,
    ) == (3.0, 3.0)


def test_strict_query_hits_match_precomputed_query_variants() -> None:
    query = "What did Alex change after the Atlas launch call?"
    text = "D3:5 Alex changed the Atlas launch deadline after the call."
    query_variants = _strict_query_term_variant_sets(query=query)

    assert _strict_query_variant_hits(
        query_term_variants=query_variants,
        text=text,
    ) == _strict_query_term_hits(query=query, text=text)


def test_selected_keyword_prompt_items_keep_high_signal_inventory_tail() -> None:
    generic_items = [
        ContextItem(
            item_id=f"generic_{index}",
            item_type="chunk",
            text=f"D{index}:1 Maria literal friend overlap item {index}.",
            score=0.7,
            source_refs=(SourceRef(source_type="chunk", source_id=f"generic:{index}"),),
        )
        for index in range(8)
    ]
    church = ContextItem(
        item_id="d14_church",
        item_type="chunk",
        text="D14:10 Maria joined a nearby church to feel closer to a community.",
        score=0.82,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-41:session_14:D14:10:turn",
            ),
        ),
    )
    weak_inventory = ContextItem(
        item_id="weak_inventory",
        item_type="chunk",
        text="D30:1 Maria mentioned a place.",
        score=0.78,
        source_refs=(SourceRef(source_type="chunk", source_id="weak"),),
    )
    scored_items = [
        (8 - index, 2, 2, 0.4, 0.8, index, "original_query", item)
        for index, item in enumerate(generic_items)
    ]
    scored_items.extend(
        [
            (0, 7, 7, 0.875, 0.95, 8, "friend_place_church_inventory_bridge", church),
            (0, 3, 3, 0.3, 0.85, 9, "friend_place_church_inventory_bridge", weak_inventory),
        ]
    )

    selected = _selected_keyword_prompt_items(scored_items, limit=8)

    assert [item.item_id for item in selected[:8]] == [
        item.item_id for item in generic_items
    ]
    assert "d14_church" in {item.item_id for item in selected}
    assert "weak_inventory" not in {item.item_id for item in selected}


def test_keyword_aggregation_skips_identity_only_inventory_scaffold() -> None:
    query_text = "What European countries has Maria been to?"
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query(query_text),
        query_plan=build_query_expansion_plan(query_text),
        seed_chunks=(
            _chunk(
                "identity_scaffold",
                "Maria inventory evidence observed mentioned answer options.",
                source_external_id="locomo:conv-41:session_13:observation",
            ),
            _chunk(
                "country_turn",
                "D13:24 Maria took a solo trip in Spain.",
                source_external_id="locomo:conv-41:session_13:D13:24:turn",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert items[0].item_id == "country_turn"
    assert "Spain" in items[0].text
    assert (
        items[0].diagnostics["score_signals"]["query_expansion_reason"]
        == "travel_country_inventory_bridge"
    )


def test_keyword_aggregation_chunks_use_inventory_list_expansion_for_shelters() -> None:
    query_text = "What shelters does Maria volunteer at?"
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query(query_text),
        query_plan=build_query_expansion_plan(query_text),
        seed_chunks=(
            _chunk(
                "shelter_inventory",
                (
                    "D2:1 Maria volunteers at the homeless shelter. "
                    "D2:2 John asked how it was going. "
                    "D11:10 Maria also started volunteering at the dog shelter."
                ),
                source_external_id="locomo:conv-41:session_11:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D2:1 Maria" in items[0].text
    assert "D11:10 Maria" in items[0].text
    assert (
        items[0].diagnostics["score_signals"]["query_expansion_reason"]
        == "decomposition_inventory_list"
    )


def test_keyword_aggregation_chunks_use_inventory_list_expansion_for_where_places() -> None:
    query_text = "Where has Maria made friends?"
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query(query_text),
        query_plan=build_query_expansion_plan(query_text),
        seed_chunks=(
            _chunk(
                "where_place_inventory",
                (
                    "D2:1 Maria made friends at the homeless shelter. "
                    "D4:1 Maria also met friends at the gym. "
                    "D14:10 Maria made friends at church."
                ),
                source_external_id="locomo:conv-41:session_14:observation",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D2:1 Maria" in items[0].text
    assert "D14:10 Maria" in items[0].text
    assert (
        items[0].diagnostics["score_signals"]["query_expansion_reason"]
        == "friend_place_inventory_bridge"
    )


def test_keyword_aggregation_chunks_collect_modified_list_queries() -> None:
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query("What LGBTQ+ events has Caroline participated in?"),
        seed_chunks=(
            _chunk(
                "modified_list_a",
                "D5:1 Caroline went to an LGBTQ+ pride parade and felt like she belonged.",
            ),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == "list"
    assert diagnostics["keyword_aggregation_chunks_used"] == 1
    assert "D5:1 Caroline" in items[0].text


def test_keyword_aggregation_chunks_skip_non_aggregation_queries() -> None:
    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_build_query("Where does Alex live now?"),
        seed_chunks=(
            _chunk("plain_a", "D1:1 Alex lives in Berlin now."),
        ),
    )

    assert diagnostics["keyword_aggregation_query_kind"] == ""
    assert diagnostics["keyword_aggregation_chunks_considered"] == 0
    assert items == ()


def test_source_sibling_seed_order_can_prioritize_used_keyword_chunks() -> None:
    low_rank_used = _chunk("used", "D12:4 pottery bowl")
    high_rank_tail = _chunk("tail", "D15:2 unrelated gym")
    duplicate_used = _chunk("used", "D12:4 pottery bowl duplicate")

    ranked_tail = tuple(
        chunk
        for *_, chunk in _ranked_keyword_chunk_scores(
            [
                (0, 1, 1, 0.1, 0.5, 1, low_rank_used),
                (4, 8, 8, 0.9, 0.99, 0, high_rank_tail),
            ]
        )
    )
    sibling_seed_chunks = _dedupe_chunks_by_id(
        (
            low_rank_used,
            duplicate_used,
            *ranked_tail,
        )
    )

    assert sibling_seed_chunks[0].id == low_rank_used.id
    assert sibling_seed_chunks[1].id == high_rank_tail.id


def test_source_sibling_seed_order_prioritizes_aggregation_source_groups() -> None:
    aggregation_group_chunk = _chunk(
        "session_12",
        "D12:4 pottery bowl",
        source_external_id="locomo:conv-26:session_12",
    )
    unrelated_chunk = _chunk(
        "session_15",
        "D15:2 unrelated gym",
        source_external_id="locomo:conv-26:session_15",
    )

    prioritized = _prioritized_chunks_for_source_groups(
        (unrelated_chunk, aggregation_group_chunk),
        source_groups=("locomo:conv-26:session_12",),
    )

    assert prioritized == (aggregation_group_chunk,)


def test_source_sibling_score_promotes_query_relevant_adjacent_turn() -> None:
    text = (
        "D4:3 Caroline: This necklace is from my home country, Sweden. "
        "It reminds me of my roots and family support."
    )
    relevance = score_query_relevance(
        query="Where did Caroline move from 4 years ago?",
        text=text,
    )

    score = _source_sibling_score(
        rank=_SourceSiblingRank(score=0.948, group_priority=1, turn_distance=2, turn_delta=-2),
        relevance=relevance,
        expansion_query="Where did Caroline move from 4 years ago?",
        expansion_reason="original_query",
        text=text,
    )

    assert score > 0.97


def test_source_sibling_allows_distant_birdwatching_schedule_evidence_turn() -> None:
    seed = _chunk(
        "d20_1",
        "D20:1 Andrew opened the session.",
        source_external_id="locomo:conv-44:session_20:D20:1:turn",
    )
    candidate = _chunk(
        "d20_21",
        (
            "D20:21 Andrew: Nice! Looks like you're prepared. I'll bring my "
            "binos and a notebook to log them at the trip."
        ),
        source_external_id="locomo:conv-44:session_20:D20:21:turn",
    )
    source_groups = _source_group_seed_turns((seed,))
    query = (
        "birdwatching bird watching birds city schedule busy week outdoors "
        "bird feeder binoculars binos notebook log camera"
    )
    reason = "birdwatching_city_schedule_bridge"
    relevance = score_query_relevance(query=query, text=candidate.text)

    assert _source_sibling_rank(candidate, source_groups=source_groups) is None
    rank = _source_sibling_distant_answer_evidence_rank(
        candidate,
        source_groups=source_groups,
        expansion_reason=reason,
        text=candidate.text,
    )

    assert rank is not None
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason=reason,
        text=candidate.text,
    )
    marker_coverage = _source_sibling_marker_coverage_count(
        expansion_reason=reason,
        text=candidate.text,
    )
    assert marker_coverage >= 1
    key = _source_sibling_candidate_rank_key(
        precise_turn=True,
        dialogue_visual_reference=False,
        visual_continuation=False,
        observation_companion=False,
        marker_coverage=marker_coverage,
        relevance=relevance,
        score=_source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason=reason,
            text=candidate.text,
        ),
        rank=rank,
        chunk=candidate,
    )
    assert key[4] < 0


def test_source_sibling_relevance_rejects_single_hit_long_no_candidate_query() -> None:
    text = "Warranty renewal paperwork was archived for Project Atlas."
    query = "unrelated yakutsk cooking recipe quantum aquarium warranty"
    relevance = score_query_relevance(query=query, text=text)
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=1, turn_delta=1)

    assert (
        _source_sibling_relevance_allowed(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="original_query",
            text=text,
        )
        is False
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="original_query",
            text=text,
        )
        == rank.score
    )


def test_source_sibling_allows_activity_duration_answer_turn_only() -> None:
    strong_text = (
        "D4:6 Maria: I started volunteering at the homeless shelter three years ago "
        "and I still help at the front desk."
    )
    weak_text = (
        "D4:7 Maria: The shelter repainted the lobby and the team liked the new sign."
    )
    query = (
        "Maria volunteer shelter duration since for years months weeks days "
        "started began still ongoing"
    )
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=1, turn_delta=1)
    strong_relevance = score_query_relevance(query=query, text=strong_text)
    weak_relevance = score_query_relevance(query=query, text=weak_text)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="decomposition_activity_duration",
        text=strong_text,
    )
    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="decomposition_activity_duration",
        text=weak_text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=strong_relevance,
            expansion_query=query,
            expansion_reason="decomposition_activity_duration",
            text=strong_text,
        )
        > 0.974
    )


def test_source_sibling_allows_frequency_recurrence_answer_turn_only() -> None:
    strong_text = (
        "D9:4 Maria: I volunteer at the homeless shelter every weekend "
        "and usually help on Friday nights too."
    )
    weak_text = (
        "D9:5 Maria: I visited the shelter once for orientation and met the coordinator."
    )
    query = (
        "Maria volunteer shelter frequency recurrence cadence every daily weekly "
        "weekend usually often times per week"
    )
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=1, turn_delta=1)
    strong_relevance = score_query_relevance(query=query, text=strong_text)
    weak_relevance = score_query_relevance(query=query, text=weak_text)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="decomposition_frequency_recurrence",
        text=strong_text,
    )
    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="decomposition_frequency_recurrence",
        text=weak_text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=strong_relevance,
            expansion_query=query,
            expansion_reason="decomposition_frequency_recurrence",
            text=strong_text,
        )
        > 0.974
    )


def test_source_sibling_allows_count_activity_subject_followup_turn() -> None:
    query = (
        "Joanna hikes hike hiking trail waterfall loved spot rush water soothing "
        "sunset saw gorgeous other day buddies weekend new summer fort wayne "
        "photo pic took count times"
    )
    followup = "D14:21 Joanna: Oh? Are you going to invite your tournament friends?"
    wrong_speaker = (
        "D14:20 Nate: Sounds great! Have fun with that. I'm organizing a gaming party."
    )
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=2, turn_delta=2)
    followup_relevance = score_query_relevance(query=query, text=followup)
    wrong_speaker_relevance = score_query_relevance(query=query, text=wrong_speaker)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=followup_relevance,
        expansion_query=query,
        expansion_reason="hike_count_activity_bridge",
        text=followup,
    )
    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=wrong_speaker_relevance,
        expansion_query=query,
        expansion_reason="hike_count_activity_bridge",
        text=wrong_speaker,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=followup_relevance,
            expansion_query=query,
            expansion_reason="hike_count_activity_bridge",
            text=followup,
        )
        > rank.score
    )


def test_source_sibling_score_allows_nearby_visual_referent_turn() -> None:
    text = (
        "D5:6 Melanie: I'm a big fan of pottery - the creativity and skill is "
        "awesome. Plus, making it is so calming. Look at this!"
    )
    relevance = score_query_relevance(
        query="What types of pottery have Melanie and her kids made?",
        text=text,
    )
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=2, turn_delta=-2)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query="What types of pottery have Melanie and her kids made?",
        expansion_reason="decomposition_artifact_evidence",
        text=text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query="What types of pottery have Melanie and her kids made?",
            expansion_reason="decomposition_artifact_evidence",
            text=text,
        )
        > 0.96
    )


def test_source_sibling_score_rejects_subject_only_visual_reference_noise() -> None:
    text = "D15:13 Caroline: Wow! Did you see that band?"
    query = "Caroline transgender conference supportive professionals advocacy"
    relevance = score_query_relevance(query=query, text=text)
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=7,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="symbol_importance_bridge",
        text=text,
    ) is False


def test_source_sibling_score_allows_recommendation_source_turn() -> None:
    text = (
        "D9:2 Caroline: I recommended Becoming Nicole to Melanie. "
        "D9:3 Melanie: I followed Caroline's recommendation and read it."
    )
    expansion_query = (
        "Caroline Melanie Becoming Nicole recommendation suggestion advice "
        "source actor recipient to from because of followed read watched tried used"
    )
    relevance = score_query_relevance(query=expansion_query, text=text)
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=1, turn_delta=1)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason="decomposition_recommendation_source",
        text=text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason="decomposition_recommendation_source",
            text=text,
        )
        > 0.976
    )


def test_source_sibling_score_allows_fantasy_book_preference_evidence_turns() -> None:
    expansion_query = (
        "books author C S Lewis Narnia Chronicles wardrobe fantasy magical world "
        "Harry Potter universe characters spells magical creatures wizarding world "
        "Potter places London tour movie explore fan friend project"
    )
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=2, turn_delta=-2)
    fan_project_text = (
        "D1:14 Tim talked to a friend who is a fan of Harry Potter and "
        "got lost in that magical world."
    )
    places_text = (
        "D1:18 Tim went to London places that felt like walking into a "
        "Harry Potter movie and wants to explore real Potter places."
    )

    for text in (fan_project_text, places_text):
        relevance = score_query_relevance(query=expansion_query, text=text)

        assert _source_sibling_relevance_allowed(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason="book_suggestion_bridge",
            text=text,
        )
        assert (
            _source_sibling_score(
                rank=rank,
                relevance=relevance,
                expansion_query=expansion_query,
                expansion_reason="book_suggestion_bridge",
                text=text,
            )
            > 0.965
        )


def test_source_sibling_score_allows_inventory_list_turn() -> None:
    text = (
        "D13:24 Maria visited Spain during a school trip. "
        "D13:25 Maria said she went to England too and loved traveling abroad."
    )
    expansion_query = (
        "Maria countries inventory list evidence place area country state city "
        "been to visited went travel trip vacation planning go destination abroad"
    )
    relevance = score_query_relevance(query=expansion_query, text=text)
    rank = _SourceSiblingRank(score=0.948, group_priority=1, turn_distance=1, turn_delta=1)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason="decomposition_inventory_list",
        text=text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason="decomposition_inventory_list",
            text=text,
        )
        > 0.976
    )


def test_source_sibling_score_allows_event_visual_reference_followup() -> None:
    text = "D15:13 Caroline: Wow! Did you see that band?"
    query = "Caroline transgender conference supportive professionals advocacy"
    relevance = score_query_relevance(query=query, text=text)
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=7,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="transgender_conference_event_bridge",
        text=text,
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="transgender_conference_event_bridge",
        text=text,
    ) > rank.score


def test_source_sibling_score_allows_explicit_visual_reference_question() -> None:
    text = "D15:13 Caroline: Wow! Did you see that band?"
    query = "What band did Caroline see in the picture?"
    relevance = score_query_relevance(query=query, text=text)
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=7,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="original_query",
        text=text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="original_query",
            text=text,
        )
        > rank.score
    )


def test_source_sibling_score_caps_low_signal_precise_bridge_noise() -> None:
    weak_text = (
        "D14:11 Caroline: Wow, Mel, you're amazing. "
        "image caption: a crowd walking with a rainbow flag."
    )
    strong_text = (
        "D14:15 Caroline: The rainbow flag mural is important to me. "
        "The eagle symbolizes freedom and pride."
    )
    query = "symbols important Caroline rainbow flag mural eagle symbolizes freedom pride"
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)

    weak_score = _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="symbol_importance_bridge",
        text=weak_text,
    )
    strong_score = _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="symbol_importance_bridge",
        text=strong_text,
    )
    weak_recency_score = _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query="latest conversation alex call",
        expansion_reason="decomposition_conversation_recency",
        text=weak_text,
    )

    assert weak_score < strong_score
    assert weak_recency_score <= 0.976
    assert strong_score == 0.99


def test_source_sibling_score_caps_low_signal_pottery_type_noise() -> None:
    weak_text = (
        "D8:28 Melanie: I'm getting there, Caroline. Creativity and family keep me "
        "at peace. image caption: a photo of a frisbee basket."
    )
    strong_text = (
        "D8:4 Melanie: The kids loved the pottery workshop, made something with "
        "clay, and the image shows a cup with a dog face."
    )
    query = "Melanie pottery types pieces made clay finished ceramic bowl bowls cup mug kids"
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)

    weak_score = _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="pottery_type_bridge",
        text=weak_text,
    )
    strong_score = _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="pottery_type_bridge",
        text=strong_text,
    )

    assert (
        _source_sibling_relevance_allowed(
            rank=rank,
            relevance=weak_relevance,
            expansion_query=query,
            expansion_reason="pottery_type_bridge",
            text=weak_text,
        )
        is False
    )
    assert weak_score <= 0.965
    assert weak_score < strong_score


def test_source_sibling_filters_animal_care_instruction_noise() -> None:
    weak_text = (
        "D10:8 Nate: It was super awesome! So much adrenaline went into that "
        "last match. Enough about me though, how about you?"
    )
    strong_text = (
        "D5:8 Nate: No, not really. Just keep their area clean, feed them "
        "properly, and make sure they get enough light. It's actually kind of fun."
    )
    query = (
        "Nate animal care instructions clean area clean tank feed properly "
        "enough light habitat routine responsible pets reptiles turtles keeper zoo"
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)

    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="animal_care_instruction_bridge",
        text=weak_text,
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="animal_care_instruction_bridge",
        text=strong_text,
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="animal_care_instruction_bridge",
        text=strong_text,
    ) > _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="animal_care_instruction_bridge",
        text=weak_text,
    )


def test_source_sibling_promotes_pottery_observation_companion() -> None:
    chunk = SimpleNamespace(
        source_external_id="locomo:conv-26:session_12:observation",
    )
    text = (
        "D12:8 Melanie: Melanie's pottery project was a source of happiness. "
        "Related turns: D12:2 D12:4 D12:10. "
        "D12:14 Melanie: Melanie values friendship with Caroline."
    )
    query = "Melanie pottery types pieces made clay finished ceramic bowl bowls cup mug kids"
    relevance = score_query_relevance(query=query, text=text)
    rank = _SourceSiblingRank(
        score=0.955,
        group_priority=10,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=False,
    )

    assert _is_pottery_type_observation_companion(
        chunk=chunk,
        expansion_reason="pottery_type_bridge",
        text=text,
    )
    assert not _is_pottery_type_observation_companion(
        chunk=chunk,
        expansion_reason="original_query",
        text=text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="pottery_type_bridge",
            text=text,
        )
        >= 0.99
    )


def test_source_sibling_marker_coverage_prefers_richer_pottery_observation_window() -> None:
    early = (
        "D12:2 Melanie: Melanie finished another pottery project. "
        "Related turns: D12:4. "
        "D12:8 Melanie: Melanie's pottery project was fulfilling. "
        "Related turns: D12:2 D12:4 D12:10."
    )
    later = (
        "D12:8 Melanie: Melanie's pottery project was a source of happiness. "
        "Related turns: D12:2 D12:4 D12:10. "
        "D12:14 Melanie: Melanie values friendship with Caroline. "
        "Related turns: D12:6 D12:16."
    )

    assert _source_sibling_marker_coverage_count(
        expansion_reason="pottery_type_bridge",
        text=later,
    ) > _source_sibling_marker_coverage_count(
        expansion_reason="pottery_type_bridge",
        text=early,
    )
    assert _source_sibling_marker_coverage_count(
        expansion_reason="decomposition_inventory_list",
        text=later,
    ) == _source_sibling_marker_coverage_count(
        expansion_reason="pottery_type_bridge",
        text=later,
    )
    assert (
        _source_sibling_marker_coverage_count(
            expansion_reason="original_query",
            text=later,
        )
        == 0
    )


def test_source_sibling_rank_key_prefers_answer_observation_window_over_generic_turn() -> None:
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=7,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    query = "Melanie pottery types pieces made clay finished ceramic bowl bowls cup mug kids"
    observation_chunk = _chunk(
        "observation",
        (
            "D12:8 Melanie: Melanie's pottery project was a source of happiness. "
            "Related turns: D12:2 D12:4 D12:10. "
            "D12:14 Melanie: Melanie values friendship with Caroline. "
            "Related turns: D12:6 D12:16."
        ),
        source_external_id="locomo:conv-26:session_12:observation",
    )
    precise_turn = _chunk(
        "precise",
        (
            "D16:8 Melanie: Seven years now, and I've finally found my real muses: "
            "painting and pottery. It's so calming."
        ),
        source_external_id="locomo:conv-26:session_16:D16:8:turn",
    )

    observation_relevance = score_query_relevance(query=query, text=observation_chunk.text)
    precise_relevance = score_query_relevance(query=query, text=precise_turn.text)

    observation_key = _source_sibling_candidate_rank_key(
        precise_turn=False,
        dialogue_visual_reference=False,
        visual_continuation=False,
        observation_companion=True,
        marker_coverage=_source_sibling_marker_coverage_count(
            expansion_reason="decomposition_inventory_list",
            text=observation_chunk.text,
        ),
        relevance=observation_relevance,
        score=0.976,
        rank=rank,
        chunk=observation_chunk,
    )
    precise_key = _source_sibling_candidate_rank_key(
        precise_turn=True,
        dialogue_visual_reference=False,
        visual_continuation=False,
        observation_companion=False,
        marker_coverage=0,
        relevance=precise_relevance,
        score=0.99,
        rank=rank,
        chunk=precise_turn,
    )

    assert observation_key < precise_key


def test_source_sibling_companion_extra_slot_distinguishes_observation_windows() -> None:
    chunk = _chunk(
        "pottery_observation_split",
        (
            "D12:8 Melanie: Melanie's pottery project was a source of happiness. "
            "Related turns: D12:2 D12:4 D12:10. "
            "D12:14 Melanie: Melanie values friendship with Caroline. "
            "Related turns: D12:6 D12:16."
        ),
        source_external_id="locomo:conv-26:session_12:observation",
    )

    assert _source_sibling_companion_extra_slot(
        chunk=chunk,
        text=chunk.text,
    ) == "locomo:conv-26:session_12:observation:D12:8:D12:16"


def test_source_sibling_companion_item_can_preserve_full_marker_window() -> None:
    text = (
        "D12:8 Melanie: Melanie's pottery project was a source of happiness. "
        "Related turns: D12:2 D12:4 D12:10. "
        "D12:14 Melanie: Melanie values friendship with Caroline. "
        "Related turns: D12:6 D12:16."
    )
    chunk = _chunk(
        "pottery_observation_full_marker_window",
        text,
        source_external_id="locomo:conv-26:session_12:observation",
    )

    item = _chunk_context_item(
        chunk=chunk,
        text=text,
        retrieval_source="keyword_source_sibling_chunks",
        base_score=0.74,
        score=0.989,
        relevance=score_query_relevance(
            query="Melanie pottery types pieces made clay finished ceramic bowl bowls cup",
            text=text,
        ),
        query_text="Melanie pottery types pieces made clay finished ceramic bowl bowls cup",
        query_expansion_reason="pottery_type_bridge",
        use_query_snippet=False,
    )

    assert "D12:8" in item.text
    assert "D12:14" in item.text


def test_source_sibling_caps_generic_volunteer_career_noise() -> None:
    weak_text = (
        "D25:9 John: Keep up the awesome work. "
        "visual query: volunteer orientation shelter"
    )
    strong_text = (
        "D32:14 Maria: I spent time at the shelter volunteering at the front desk. "
        "Seeing people get food or a bed made me feel good."
    )
    query = (
        "Maria future job career started volunteering volunteer shelter homeless "
        "front desk talks residents bed fulfilling counselor coordinator compliments"
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)

    weak_score = _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="volunteer_career_inference_bridge",
        text=weak_text,
    )
    strong_score = _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="volunteer_career_inference_bridge",
        text=strong_text,
    )

    assert weak_score <= 0.976
    assert strong_score > weak_score


def test_source_sibling_allows_degree_policy_inference_turn() -> None:
    weak_text = "D9:2 John shared a diploma image after finishing his university degree."
    strong_text = (
        "D9:6 John: I'm considering going into policymaking because of my "
        "degree and my passion for making a positive impact."
    )
    query = (
        "John degree policymaking policy political science public administration "
        "public affairs positive impact opportunities improvements"
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)

    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="degree_policy_inference_bridge",
        text=weak_text,
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="degree_policy_inference_bridge",
        text=strong_text,
    )
    assert _source_sibling_score_cap(
        expansion_reason="degree_policy_inference_bridge",
        relevance=weak_relevance,
        text=weak_text,
    ) == 0.976
    assert (
        _source_sibling_score_cap(
            expansion_reason="degree_policy_inference_bridge",
            relevance=strong_relevance,
            text=strong_text,
        )
        is None
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="degree_policy_inference_bridge",
        text=strong_text,
    ) > _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="degree_policy_inference_bridge",
        text=weak_text,
    )


def test_source_sibling_filters_visual_noise_for_pottery_inventory_query() -> None:
    query = (
        "melanie types pottery kids made type kind finished created project "
        "piece visual image caption cup bowl pot plate inventory list"
    )
    visual_noise = (
        "D14:11 Caroline: Wow, Mel, you're amazing! "
        "image caption: a photo of a crowd walking with a rainbow flag. "
        "visual query: volunteering pride event."
    )
    pottery_evidence = (
        "D8:4 Melanie: The kids loved the pottery workshop, made something "
        "with clay, and the image shows a cup with a dog face."
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )

    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=score_query_relevance(query=query, text=visual_noise),
        expansion_query=query,
        expansion_reason="decomposition_inventory_list",
        text=visual_noise,
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=score_query_relevance(query=query, text=pottery_evidence),
        expansion_query=query,
        expansion_reason="decomposition_inventory_list",
        text=pottery_evidence,
    )


def test_source_sibling_filters_post_event_activity_timing_noise() -> None:
    weak_text = (
        "D2:5 Melanie: I carve out me-time each day with running, reading, "
        "and violin after work."
    )
    strong_text = (
        "D18:17 Melanie: Yup, we just did it yesterday! The kids loved it "
        "and it was a nice way to relax after the road trip."
    )
    visual_companion = (
        "D18:15 Melanie: Having my family around helps a lot. "
        "image caption: a woman and child walking on a trail. "
        "visual query: family hiking mountains."
    )
    query = (
        "Melanie roadtrip road trip after hike hiking family mountains trail "
        "picture pic recent yesterday just did it kids loved nice way relax"
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=1,
        turn_delta=1,
        group_level_seed=True,
    )
    weak_relevance = score_query_relevance(query=query, text=weak_text)
    strong_relevance = score_query_relevance(query=query, text=strong_text)
    visual_relevance = score_query_relevance(query=query, text=visual_companion)

    assert (
        _source_sibling_relevance_allowed(
            rank=rank,
            relevance=weak_relevance,
            expansion_query=query,
            expansion_reason="post_event_activity_timing_bridge",
            text=weak_text,
        )
        is False
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="post_event_activity_timing_bridge",
        text=strong_text,
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=visual_relevance,
        expansion_query=query,
        expansion_reason="post_event_activity_timing_bridge",
        text=visual_companion,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=weak_relevance,
            expansion_query=query,
            expansion_reason="post_event_activity_timing_bridge",
            text=weak_text,
        )
        <= 0.976
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=strong_relevance,
        expansion_query=query,
        expansion_reason="post_event_activity_timing_bridge",
        text=strong_text,
    ) > _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="post_event_activity_timing_bridge",
        text=weak_text,
    )


def test_source_sibling_allows_shoe_usage_question_turn() -> None:
    question_text = "D7:19 Caroline: Love that purple color! For walking or running?"
    weak_text = "D16:6 Melanie: The yellow leaves in that photo are cozy and pretty."
    query = "Melanie new shoes purple walking running used for walk run love color sneakers"
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=1,
        turn_delta=1,
        group_level_seed=True,
    )
    question_relevance = score_query_relevance(query=query, text=question_text)
    weak_relevance = score_query_relevance(query=query, text=weak_text)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=question_relevance,
        expansion_query=query,
        expansion_reason="shoe_usage_bridge",
        text=question_text,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=weak_relevance,
            expansion_query=query,
            expansion_reason="shoe_usage_bridge",
            text=weak_text,
        )
        <= 0.976
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=question_relevance,
        expansion_query=query,
        expansion_reason="shoe_usage_bridge",
        text=question_text,
    ) > _source_sibling_score(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="shoe_usage_bridge",
        text=weak_text,
    )


def test_source_sibling_allows_running_reason_question_turn() -> None:
    question_text = "D7:21 Caroline: Wow! What got you into running?"
    answer_text = (
        "D7:22 Melanie: I've been running farther to de-stress, "
        "which has been great for my headspace."
    )
    weak_text = (
        "D17:12 Melanie: The sunset painting was calming and helped "
        "Caroline talk about feelings."
    )
    query = (
        "Melanie running run farther longer de-stress destress clear mind "
        "headspace mood boost shoes purple walking or running what got into running"
    )
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=1,
        turn_delta=1,
        group_level_seed=True,
    )
    question_relevance = score_query_relevance(query=query, text=question_text)
    answer_relevance = score_query_relevance(query=query, text=answer_text)
    weak_relevance = score_query_relevance(query=query, text=weak_text)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=question_relevance,
        expansion_query=query,
        expansion_reason="running_reason_bridge",
        text=question_text,
    )
    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=answer_relevance,
        expansion_query=query,
        expansion_reason="running_reason_bridge",
        text=answer_text,
    )
    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=weak_relevance,
        expansion_query=query,
        expansion_reason="running_reason_bridge",
        text=weak_text,
    )
    assert _source_sibling_score(
        rank=rank,
        relevance=question_relevance,
        expansion_query=query,
        expansion_reason="running_reason_bridge",
        text=question_text,
    ) > 0.96
    assert _source_sibling_score(
        rank=rank,
        relevance=answer_relevance,
        expansion_query=query,
        expansion_reason="running_reason_bridge",
        text=answer_text,
    ) > 0.96


def test_dialogue_visual_reference_priority_requires_dialogue_reference() -> None:
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=7,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    dialogue_relevance = score_query_relevance(
        query="Caroline transgender conference",
        text="D15:13 Caroline: Wow! Did you see that band?",
    )
    caption_relevance = score_query_relevance(
        query="Caroline transgender conference",
        text="D15:13 Caroline image caption: a photo of a band playing on stage",
    )

    assert _is_dialogue_visual_reference_source_sibling(
        rank=rank,
        relevance=dialogue_relevance,
        expansion_query="What band did Caroline see in the picture?",
        expansion_reason="original_query",
        text="D15:13 Caroline: Wow! Did you see that band?",
    )
    assert not _is_dialogue_visual_reference_source_sibling(
        rank=rank,
        relevance=caption_relevance,
        expansion_query="What band did Caroline see in the picture?",
        expansion_reason="original_query",
        text="D15:13 Caroline image caption: a photo of a band playing on stage",
    )


def test_source_sibling_rank_keeps_primary_seed_turn_available_for_hybrid_boost() -> None:
    seed = SimpleNamespace(source_external_id="locomo:conv-26:session_7:D7:4:turn")
    source_groups = _source_group_seed_turns((seed,))

    rank = _source_sibling_rank(seed, source_groups=source_groups)

    assert rank is not None
    assert rank.turn_distance == 0
    assert rank.turn_delta == 0
    assert rank.score > 0.96


def test_source_sibling_rank_uses_session_events_as_group_level_seed() -> None:
    seed = SimpleNamespace(source_external_id="locomo:conv-41:session_24:events")
    candidate = SimpleNamespace(source_external_id="locomo:conv-41:session_24:D24:3:turn")
    source_groups = _source_group_seed_turns((seed,))

    rank = _source_sibling_rank(candidate, source_groups=source_groups)

    assert tuple(source_groups) == ("locomo:conv-41:session_24",)
    assert rank is not None
    assert rank.group_level_seed is True
    assert rank.turn_distance == 0
    assert rank.turn_delta == 0
    assert rank.score > 0.96


def test_source_sibling_rank_allows_session_observation_pages_as_group_siblings() -> None:
    seed = SimpleNamespace(source_external_id="locomo:conv-26:session_12:D12:4:turn")
    candidate = SimpleNamespace(source_external_id="locomo:conv-26:session_12:observation")
    source_groups = _source_group_seed_turns((seed,))

    rank = _source_sibling_rank(candidate, source_groups=source_groups)

    assert tuple(source_groups) == ("locomo:conv-26:session_12",)
    assert rank is not None
    assert rank.group_level_seed is False
    assert rank.turn_distance == 0
    assert rank.turn_delta == 0
    assert rank.score >= 0.955


def test_source_sibling_allows_generic_behavior_inference_turn() -> None:
    query = "Would Alex be considered reliable?"
    text = "D4:9 Alex kept his promises, followed through, and prepared the launch notes early."
    rank = _SourceSiblingRank(score=0.935, group_priority=1, turn_distance=1, turn_delta=1)
    relevance = score_query_relevance(query=query, text=text)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="generic_behavior_inference_bridge",
        text=text,
    )
    assert (
        _source_sibling_score_cap(
            expansion_reason="generic_behavior_inference_bridge",
            relevance=relevance,
            text=text,
        )
        is None
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="generic_behavior_inference_bridge",
            text=text,
        )
        >= 0.974
    )


def test_source_sibling_rejects_generic_behavior_topic_only_turn() -> None:
    query = "Would Alex be considered reliable?"
    text = "D4:8 Alex discussed reliability as a product metric in the backend review."
    rank = _SourceSiblingRank(score=0.935, group_priority=1, turn_distance=1, turn_delta=1)
    relevance = score_query_relevance(query=query, text=text)

    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="generic_behavior_inference_bridge",
        text=text,
    )
    assert _source_sibling_score_cap(
        expansion_reason="generic_behavior_inference_bridge",
        relevance=relevance,
        text=text,
    ) == 0.976


def test_source_sibling_allows_birdwatching_city_schedule_context_turn() -> None:
    query = "Andrew birdwatching city schedule busy week outdoors bird feeder window nearby park"
    text = "D20:5 Andrew: That spot looks ideal for them to play. Where did you take them?"
    unrelated = "D20:5 Andrew: The deployment dashboard had a quiet afternoon."
    rank = _SourceSiblingRank(
        score=0.968,
        group_priority=1,
        turn_distance=0,
        turn_delta=0,
        group_level_seed=True,
    )
    relevance = score_query_relevance(query=query, text=text)
    unrelated_relevance = score_query_relevance(query=query, text=unrelated)

    assert _source_sibling_relevance_allowed(
        rank=rank,
        relevance=relevance,
        expansion_query=query,
        expansion_reason="birdwatching_city_schedule_bridge",
        text=text,
    )
    assert not _source_sibling_relevance_allowed(
        rank=rank,
        relevance=unrelated_relevance,
        expansion_query=query,
        expansion_reason="birdwatching_city_schedule_bridge",
        text=unrelated,
    )
    assert (
        _source_sibling_score(
            rank=rank,
            relevance=relevance,
            expansion_query=query,
            expansion_reason="birdwatching_city_schedule_bridge",
            text=text,
        )
        >= 0.972
    )


def test_source_sibling_rank_does_not_treat_plain_summary_as_source_group_seed() -> None:
    seed = SimpleNamespace(source_external_id="notes:release:summary")

    assert _source_group_seed_turns((seed,)) == {}


def _build_query(query: str) -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space_test"),
        memory_scope_ids=(MemoryScopeId("scope_test"),),
        query=query,
        max_chunks=10,
    )


def _chunk(
    chunk_id: str,
    text: str,
    *,
    source_external_id: str | None = None,
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        document_id=MemoryDocumentId(f"{chunk_id}_document"),
        source_type="document",
        source_external_id=source_external_id or f"locomo:conv-26:session_1:{chunk_id}:turn",
        source_hash=f"{chunk_id}_hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=max(1, len(text.split())),
        now=now,
    )
