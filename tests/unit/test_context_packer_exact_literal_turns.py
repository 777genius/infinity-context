from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_exact_literal_turns import (
    exact_literal_turn_candidates,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _turn_item(
    item_id: str,
    text: str,
    source_id: str,
    *,
    score: float = 0.8,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={"score_signals": {"query_expansion_reason": "original_query"}},
    )


def _activity_competition_turn_item(
    item_id: str,
    text: str,
    source_id: str,
    *,
    score: float = 0.99,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "score_signals": {
                "query_expansion_reason": "activity_competition_evidence_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 8,
                "phrase_bigram_hits": 2,
            },
        },
    )


def test_exact_literal_candidates_cover_activity_competition_attitude() -> None:
    generic = _turn_item(
        "festival_generic",
        "D4:24 Ari: I rehearsed with dancers for a festival.",
        "locomo:conv-fixture:session_4:D4:24:turn",
        score=0.99,
    )
    attitude = _turn_item(
        "festival_attitude",
        "D4:28 Ari: Yeah, awesome! Glad to be part of it.",
        "locomo:conv-fixture:session_4:D4:28:turn",
        score=0.2,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_literal_activity_attitude",
        items=(generic, attitude),
        token_budget=800,
        query="What is Ari's attitude towards being part of the dance festival?",
        max_rendered_chars=500,
    )

    assert result.bundle.items[0].item_id == "festival_attitude"


def test_exact_literal_turn_is_preserved_before_broad_activity_noise() -> None:
    noisy_activity_turns = tuple(
        _activity_competition_turn_item(
            f"activity_noise_{index}",
            (
                f"D{index}:1 Ari: I'm excited about another dance festival "
                "showcase with dancers performing on stage. The practice has "
                "been intense and the group should impress everyone with "
                "grace and skill."
            ),
            f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
        )
        for index in range(2, 8)
    )
    literal_attitude = _activity_competition_turn_item(
        "literal_attitude",
        "D4:28 Ari: Yeah, awesome! Glad to be part of it.",
        "locomo:conv-fixture:session_4:D4:28:turn",
        score=0.2,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_literal_activity_attitude_noisy",
        items=(*noisy_activity_turns, literal_attitude),
        token_budget=150,
        query="What is Ari's attitude towards being part of the dance festival?",
        max_rendered_chars=650,
    )

    selected_source_ids = {
        str(ref.source_id) for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_4:D4:28:turn" in selected_source_ids


def test_exact_literal_candidates_focus_matching_turn_in_source_group() -> None:
    source_group = _turn_item(
        "festival_group",
        (
            "D4:25 Ari: We'll be at the festival soon. "
            "D4:26 Ari: The dancers will impress with grace and skill. "
            "D4:27 Mira: They look great and it is gonna be awesome! "
            "D4:28 Ari: Yeah, awesome! Glad to be part of it."
        ),
        "locomo:conv-fixture:session_4:D4:25:turn",
        score=0.99,
    )
    source_group = ContextItem(
        item_id=source_group.item_id,
        item_type=source_group.item_type,
        text=source_group.text,
        score=source_group.score,
        source_refs=(
            *source_group.source_refs,
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:26:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:27:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:28:turn",
            ),
        ),
        diagnostics=source_group.diagnostics,
    )

    candidates = exact_literal_turn_candidates(
        [source_group],
        query="What is Ari's attitude towards being part of the dance festival?",
    )

    assert len(candidates) == 1
    assert candidates[0].source_refs[0].source_id.endswith(":D4:28:turn")
    assert candidates[0].text.startswith("D4:28")
    assert "D4:27" not in candidates[0].text


def test_exact_literal_candidates_preserve_attributed_progress_reply() -> None:
    source_group = ContextItem(
        item_id="store_progress_group",
        item_type="chunk",
        text=(
            "D2:1 Riley: I finally found a better place for the shop. "
            "D2:2 Morgan: Wow, Riley! You found the perfect spot for your store. "
            "Way to go, hard work is paying off. "
            "D2:3 Riley: Thanks, I am relieved."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:3:turn",
            ),
        ),
        diagnostics={"score_signals": {"query_expansion_reason": "speaker_turn_bridge"}},
    )

    candidates = exact_literal_turn_candidates(
        [source_group],
        query="What did Morgan say about Riley's progress with her store?",
    )

    assert len(candidates) == 1
    assert candidates[0].source_refs[0].source_id.endswith(":D2:2:turn")
    assert candidates[0].text.startswith("D2:2")
    assert "D2:1" not in candidates[0].text


def test_exact_literal_candidates_focus_who_said_quoted_text() -> None:
    source_group = ContextItem(
        item_id="store_progress_group",
        item_type="chunk",
        text=(
            "D2:1 Riley: I finally found a better place for the shop. "
            "D2:2 Morgan: Wow, Riley! You found the perfect spot for your store. "
            "Way to go, hard work is paying off. "
            "D2:3 Riley: Thanks, I am relieved."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:1:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:2:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_2:D2:3:turn",
            ),
        ),
        diagnostics={"score_signals": {"query_expansion_reason": "original_query"}},
    )

    candidates = exact_literal_turn_candidates(
        [source_group],
        query='Who said "hard work is paying off"?',
    )

    assert len(candidates) == 1
    assert candidates[0].source_refs[0].source_id.endswith(":D2:2:turn")
    assert candidates[0].text.startswith("D2:2 Morgan:")
    assert "D2:1" not in candidates[0].text
    assert candidates[0].diagnostics["score_signals"]["exact_literal_turn"] == 1
    assert (
        candidates[0].diagnostics["score_signals"]["quote_attribution_exact_turn"]
        == 1
    )


def test_exact_literal_candidates_require_specific_unquoted_quote_attribution() -> None:
    project_turn = _turn_item(
        "project_turn",
        "D5:7 Alex: Project Atlas billing call is still waiting on invoices.",
        "locomo:conv-fixture:session_5:D5:7:turn",
    )

    candidates = exact_literal_turn_candidates(
        [project_turn],
        query="Who said Project Atlas?",
    )

    assert candidates == ()


def test_exact_literal_candidates_do_not_lift_non_attribution_quoted_text() -> None:
    project_turn = _turn_item(
        "project_turn",
        "D5:7 Alex: Project Atlas billing call is still waiting on invoices.",
        "locomo:conv-fixture:session_5:D5:7:turn",
    )

    candidates = exact_literal_turn_candidates(
        [project_turn],
        query='What changed after "Project Atlas billing call"?',
    )

    assert candidates == ()


def test_context_packer_preserves_who_said_source_window_over_noise() -> None:
    noisy_turns = tuple(
        _turn_item(
            f"noise_{index}",
            (
                f"D{index}:1 Riley: The store project has invoices, planning, "
                "new shelves, and several updates about the perfect location."
            ),
            f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            score=1.0,
        )
        for index in range(3, 8)
    )
    quoted_turn = _turn_item(
        "quoted_turn",
        "D2:2 Morgan: Way to go, hard work is paying off.",
        "locomo:conv-fixture:session_2:D2:2:turn",
        score=0.2,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_who_said_quote_source_window",
        items=(*noisy_turns, quoted_turn),
        token_budget=120,
        query='Who said "hard work is paying off"?',
        max_rendered_chars=500,
    )

    selected_source_ids = {
        str(ref.source_id) for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_2:D2:2:turn" in selected_source_ids


def test_exact_literal_candidates_skip_marker_header_when_focusing_group() -> None:
    source_group = ContextItem(
        item_id="festival_group_header",
        item_type="chunk",
        text=(
            "D4:28 D4:24 D4:25 D4:26 D4:27 ... "
            "D4:24 Ari: I rehearsed with dancers for the festival. "
            "D4:26 Ari: The dancers will impress with grace and skill. "
            "D4:27 Mira: They look great and it is gonna be awesome! "
            "D4:28 Ari: Yeah, awesome! Glad to be part of it."
        ),
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:28:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:24:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:25:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:26:turn",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_4:D4:27:turn",
            ),
        ),
        diagnostics={"score_signals": {"query_expansion_reason": "original_query"}},
    )

    candidates = exact_literal_turn_candidates(
        [source_group],
        query="What is Mira's attitude towards participating in the dance festival?",
    )

    assert len(candidates) == 1
    assert candidates[0].source_refs[0].source_id.endswith(":D4:28:turn")
    assert candidates[0].text.startswith("D4:28 Ari:")


def test_exact_literal_candidates_cover_certificate_completion() -> None:
    certificate = _turn_item(
        "certificate",
        "D14:2 Lina shared an image captioned certificate of completion.",
        "locomo:conv-fixture:session_14:D14:2:turn",
    )

    candidates = exact_literal_turn_candidates(
        [certificate],
        query="What did Lina receive a certificate for?",
    )

    assert [item.item_id for item in candidates] == ["certificate"]


def test_exact_literal_candidates_cover_accident_timing() -> None:
    accident = _turn_item(
        "accident",
        "D21:3 Maria: Not so great happened yesterday. My car was damaged in an accident.",
        "locomo:conv-fixture:session_21:D21:3:turn",
    )

    candidates = exact_literal_turn_candidates(
        [accident],
        query="When did Maria's car accident happen?",
    )

    assert [item.item_id for item in candidates] == ["accident"]


def test_exact_literal_candidates_cover_creative_production_job_duties() -> None:
    production_turn = _turn_item(
        "production_turn",
        (
            "D6:3 Maya: I'm finally filming my own movie from the road-trip "
            "script. The clap board on set made it feel real. "
            "D6:4 Lee: That sounds exciting."
        ),
        "locomo:conv-fixture:session_6:D6:4:turn",
    )
    writing_context = _turn_item(
        "writing_context",
        "D5:2 Maya: I finished editing another movie script last week.",
        "locomo:conv-fixture:session_5:D5:2:turn",
        score=0.99,
    )

    candidates = exact_literal_turn_candidates(
        [writing_context, production_turn],
        query=(
            "What kind of job is Maya beginning to perform the duties of "
            "because of her movie scripts?"
        ),
    )

    assert [item.source_refs[0].source_id for item in candidates] == [
        "locomo:conv-fixture:session_6:D6:3:turn"
    ]


def test_exact_literal_candidates_cover_place_feeling() -> None:
    place_feeling = _turn_item(
        "place_feeling",
        "D18:7 Maria: It felt like a fairy tale being at the desert in Oregon.",
        "locomo:conv-fixture:session_18:D18:7:turn",
    )

    candidates = exact_literal_turn_candidates(
        [place_feeling],
        query="What did Maria say it was like being at the Oregon desert?",
    )

    assert [item.item_id for item in candidates] == ["place_feeling"]


def test_exact_literal_candidates_cover_shared_destress_confirmation() -> None:
    shared = _turn_item(
        "shared_destress",
        "D14:7 Gray: Same here! Dance is pretty much my go-to for stress relief.",
        "locomo:conv-fixture:session_14:D14:7:turn",
    )
    generic = _turn_item(
        "generic_dance",
        "D8:5 Lee: Dance classes are busy this week.",
        "locomo:conv-fixture:session_8:D8:5:turn",
        score=0.99,
    )

    candidates = exact_literal_turn_candidates(
        [generic, shared],
        query="How do Lee and Gray both like to destress?",
    )

    assert [item.item_id for item in candidates] == ["shared_destress"]


def test_exact_literal_candidates_cover_shared_journey_description() -> None:
    journey = _turn_item(
        "journey",
        "D17:25 Caroline: It has been an ongoing adventure of learning and growing.",
        "locomo:conv-fixture:session_17:D17:25:turn",
    )

    candidates = exact_literal_turn_candidates(
        [journey],
        query="How do Caroline and Melanie describe their journey through life together?",
    )

    assert [item.item_id for item in candidates] == ["journey"]


def test_exact_literal_candidates_cover_pet_adoption_interval() -> None:
    first_adoption = _turn_item(
        "first_adoption",
        "D30:1 Maria: Guess what - I got a puppy two weeks ago.",
        "locomo:conv-fixture:session_30:D30:1:turn",
        score=0.2,
    )
    second_adoption = _turn_item(
        "second_adoption",
        "D31:2 Maria: I just adopted this cute pup from a shelter last week.",
        "locomo:conv-fixture:session_31:D31:2:turn",
        score=0.99,
    )
    second_adoption_group_duplicate = _turn_item(
        "second_adoption_group",
        (
            "D31:1 Owen: I'm volunteering as a mentor. "
            "D31:2 Maria: I just adopted this cute pup from a shelter last week. "
            "D31:3 Owen: That's wonderful."
        ),
        "locomo:conv-fixture:session_31:D31:2:turn",
        score=1.0,
    )
    unrelated_pet_memory = _turn_item(
        "pet_memory",
        "D30:6 Owen: I cherish memories of my pet from a camping trip.",
        "locomo:conv-fixture:session_30:D30:6:turn",
        score=1.0,
    )

    candidates = exact_literal_turn_candidates(
        [
            second_adoption_group_duplicate,
            second_adoption,
            unrelated_pet_memory,
            first_adoption,
        ],
        query="How many weeks passed between adopting two dogs?",
    )

    assert len(candidates) == 2
    assert {
        str(item.source_refs[0].source_id)
        for item in candidates
    } == {
        "locomo:conv-fixture:session_30:D30:1:turn",
        "locomo:conv-fixture:session_31:D31:2:turn",
    }


def test_exact_literal_candidates_cover_travel_area_inventory() -> None:
    visited_area = _turn_item(
        "visited_area",
        "D22:6 Owen: We explored the coast and hit some cool national parks.",
        "locomo:conv-fixture:session_22:D22:6:turn",
        score=0.5,
    )
    planned_area = _turn_item(
        "planned_area",
        "D24:9 Owen: I'm planning a trip to the coast next month.",
        "locomo:conv-fixture:session_24:D24:9:turn",
        score=0.4,
    )
    vague_trip = _turn_item(
        "vague_trip",
        "D13:2 Owen: I might take a trip after work calms down.",
        "locomo:conv-fixture:session_13:D13:2:turn",
        score=1.0,
    )
    flood_area = _turn_item(
        "flood_area",
        "D14:3 Owen: My old area was hit by a flood last week.",
        "locomo:conv-fixture:session_14:D14:3:turn",
        score=1.0,
    )
    civic_area = _turn_item(
        "civic_area",
        (
            "D15:1 Owen: I went to that community meeting and heard how "
            "the issue affects our area."
        ),
        "locomo:conv-fixture:session_15:D15:1:turn",
        score=1.0,
    )

    candidates = exact_literal_turn_candidates(
        [civic_area, flood_area, vague_trip, planned_area, visited_area],
        query="What areas of the U.S. has Owen been to or is planning to go to?",
    )

    assert {item.item_id for item in candidates} == {
        "planned_area",
        "visited_area",
    }


def test_exact_literal_candidates_cover_city_location_inventory() -> None:
    future_city = _turn_item(
        "future_city",
        (
            "D32:4 Rowan: I'm excited for my game there next month. "
            "It's one of my favorite cities to explore."
        ),
        "locomo:conv-fixture:session_32:D32:4:turn",
        score=0.5,
    )
    visited_city = _turn_item(
        "visited_city",
        (
            "D34:2 Rowan: I was in a bright lakeside city last spring, "
            "and it was great to experience other cultures."
        ),
        "locomo:conv-fixture:session_34:D34:2:turn",
        score=0.4,
    )
    generic_travel = _turn_item(
        "generic_travel",
        "D35:3 Rowan: I like planning trips and reading maps.",
        "locomo:conv-fixture:session_35:D35:3:turn",
        score=1.0,
    )
    other_speaker_city = _turn_item(
        "other_speaker_city",
        "D36:5 Mira: I was in a busy coastal city for a conference.",
        "locomo:conv-fixture:session_36:D36:5:turn",
        score=1.0,
    )

    candidates = exact_literal_turn_candidates(
        [other_speaker_city, generic_travel, future_city, visited_city],
        query="Which cities has Rowan been to or mentioned visiting?",
    )

    assert {item.item_id for item in candidates} == {
        "future_city",
        "visited_city",
    }
