from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    source_refs_with_query_snippet,
)
from infinity_context_core.domain.entities import SourceRef


def test_query_focused_snippet_selects_window_around_query_terms() -> None:
    text = (
        "Intro context that is not useful. " * 12
        + "Atlas renewal decision was approved by Alex during the planning call. "
        + "Trailing context that is also not useful. " * 12
    )

    snippet = query_focused_snippet(
        query="Atlas renewal decision Alex",
        text=text,
        window_chars=180,
    )

    assert snippet is not None
    assert "Atlas renewal decision was approved by Alex" in snippet.text
    assert snippet.unique_term_hits == 4
    assert snippet.matched_terms == ("atlas", "renewal", "decision", "alex")
    assert 0 < snippet.char_start < snippet.char_end < len(text)
    assert len(snippet.text) < len(text)


def test_query_focused_snippet_prefers_direct_user_assertion_over_conflicting_paraphrase() -> None:
    text = (
        "Record user: I configured my export batch to contain 12 records per run. "
        "assistant: 20 records per run gives you more room for retries."
    )
    assistant_start = text.index("assistant:")

    snippet = query_focused_snippet(
        query="How many records are in my export batch?",
        text=text,
    )

    assert snippet is not None
    assert "12 records per run" in snippet.text
    assert "20 records per run" not in snippet.text
    assert snippet.char_end == assistant_start
    assert text[snippet.char_start : snippet.char_end].strip() in snippet.text


def test_query_focused_snippet_keeps_non_conflicting_assistant_elaboration() -> None:
    text = (
        "Record user: I configured my export batch to contain 12 records per run. "
        "assistant: Twelve records per run leaves useful room for retries."
    )

    snippet = query_focused_snippet(
        query="How many records are in my export batch?",
        text=text,
    )

    assert snippet is not None
    assert "12 records per run" in snippet.text
    assert "Twelve records per run leaves useful room for retries" in snippet.text


def test_query_focused_snippet_does_not_infer_roles_from_unlabeled_text() -> None:
    text = (
        "The configuration notes that my export batch contains 12 records per run. "
        "A later summary says 20 records per run."
    )

    snippet = query_focused_snippet(
        query="How many records are in my export batch?",
        text=text,
    )

    assert snippet is not None
    assert "12 records per run" in snippet.text
    assert "20 records per run" in snippet.text


def test_role_aware_snippet_preserves_source_provenance_and_projected_char_range() -> None:
    text = (
        "Record user: I configured my export batch to contain 12 records per run. "
        "assistant: 20 records per run gives you more room for retries."
    )
    source_ref = SourceRef(
        source_type="conversation",
        source_id="thread-7",
        chunk_id="turn-pair-3",
        time_start_ms=400,
        time_end_ms=800,
    )
    assistant_ref = SourceRef(
        source_type="conversation_message",
        source_id="thread-7-message-2",
        chunk_id="turn-pair-3",
        quote_preview="20 records per run gives you more room for retries.",
    )
    snippet = query_focused_snippet(
        query="How many records are in my export batch?",
        text=text,
    )

    enriched = source_refs_with_query_snippet(
        (source_ref, assistant_ref),
        snippet,
        include_char_range=True,
    )

    assert snippet is not None
    assert enriched[0].source_type == source_ref.source_type
    assert enriched[0].source_id == source_ref.source_id
    assert enriched[0].chunk_id == source_ref.chunk_id
    assert enriched[0].time_start_ms == source_ref.time_start_ms
    assert enriched[0].time_end_ms == source_ref.time_end_ms
    assert enriched[0].char_start == snippet.char_start
    assert enriched[0].char_end == text.index("assistant:")
    assert enriched[1] == assistant_ref


def test_query_focused_snippet_preserves_nearby_line_evidence_prefix() -> None:
    text = (
        "LoCoMo conv-26 session_4\n\n"
        "D4:5 Caroline: Yep, Melanie! I've got some other stuff with sentimental "
        "value, like my hand-painted bowl. A friend made it for my 18th birthday "
        "ten years ago. The colors remind me of art and self-expression.\n"
        "D4:6 Melanie: That sounds great, Caroline."
    )

    snippet = query_focused_snippet(
        query="How long ago was Caroline's 18th birthday?",
        text=text,
        window_chars=90,
    )

    assert snippet is not None
    assert "D4:5 Caroline:" in snippet.text
    assert "18th birthday ten years ago" in snippet.text
    assert text.index("18th birthday") - text.index("D4:5") > 120
    assert snippet.char_start == text.index("D4:5")


def test_query_focused_snippet_keeps_adjacent_structured_dialog_turns() -> None:
    text = "\n".join(
        [
            "D1:8 Melanie: That's really cool. You've got guts. What now?",
            "D1:9 Caroline: Gonna continue my edu and check out career options "
            "after talking through all the practical next steps.",
            "D1:10 Melanie: Wow, Caroline! What kinda jobs are you thinkin' of?",
            "D1:11 Caroline: I'm keen on counseling or working in mental health "
            "because that connects directly to the people I want to help.",
            "D1:12 Melanie: You'd be a great counselor!",
        ]
    )

    snippet = query_focused_snippet(
        query="Caroline continue edu career options",
        text=text,
        window_chars=110,
    )

    assert snippet is not None
    assert "D1:9 Caroline:" in snippet.text
    assert "D1:11 Caroline:" in snippet.text
    assert "D1:12 Melanie:" not in snippet.text
    assert len(snippet.text) > 360
    assert len(snippet.text) <= 640


def test_query_focused_snippet_preserves_long_structured_evidence_prefix() -> None:
    text = (
        "D10:10 D10:12 D10:14 D10:16 Melanie: "
        + "background detail " * 35
        + "The family watched the Perseid meteor shower during a camping trip."
    )

    snippet = query_focused_snippet(
        query="meteor shower camping trip",
        text=text,
        window_chars=120,
    )

    assert snippet is not None
    assert snippet.text.startswith("D10:10 D10:12 D10:14 D10:16")
    assert "meteor shower during a camping trip" in snippet.text


def test_query_focused_snippet_keeps_bounded_previous_structured_turns() -> None:
    text = "\n".join(
        [
            "D4:3 Caroline: This necklace is from my grandma in Sweden and "
            "reminds me of my roots.",
            "D4:4 Melanie: That's gorgeous. Got any other treasured objects?",
            "D4:5 Caroline: A friend made a bowl for my 18th birthday ten years ago.",
            "D4:6 Melanie: That sounds great.",
        ]
    )

    snippet = query_focused_snippet(
        query="How long ago was Caroline's 18th birthday?",
        text=text,
        window_chars=90,
    )

    assert snippet is not None
    assert "D4:3 Caroline:" in snippet.text
    assert "Sweden" in snippet.text
    assert "D4:5 Caroline:" in snippet.text


def test_query_focused_snippet_keeps_inline_dialogue_marker_window() -> None:
    text = (
        "LoCoMo conv-26 session_4 D4:3 Caroline: This necklace is from my "
        "grandma in Sweden and reminds me of my roots. D4:4 Melanie: That's "
        "gorgeous. Got any other treasured objects? D4:5 Caroline: A friend "
        "made a bowl for my 18th birthday ten years ago. D4:6 Melanie: That "
        "sounds great."
    )

    snippet = query_focused_snippet(
        query="How long ago was Caroline's 18th birthday?",
        text=text,
        window_chars=90,
    )

    assert snippet is not None
    assert "D4:3 Caroline:" in snippet.text
    assert "Sweden" in snippet.text
    assert "D4:5 Caroline:" in snippet.text


def test_query_focused_snippet_preserves_truncated_inline_following_markers() -> None:
    text = (
        "LoCoMo conv-42 session_14 D14:15 Joanna: Sounds like fun! "
        "D14:16 Nate: They asked for gaming tips, so I said I could help. "
        "D14:17 Joanna: Good on you for helping strangers out. "
        "D14:18 Nate: Do you have any plans for the weekend? "
        "D14:19 Joanna: Yep, I'm hiking with some buddies this weekend. "
        "We're checking out a new trail with a rad waterfall. Can't wait! "
        "Do you have any fun plans? "
        "D14:20 Nate: Sounds great! "
        + "I'm organizing a gaming party with friends and teammates. " * 12
        + "D14:21 Joanna: Oh? Are you going to invite your tournament friends? "
        "D14:22 Nate: Definitely. "
    )

    snippet = query_focused_snippet(
        query="How many hikes has Joanna been on?",
        text=text,
        window_chars=320,
    )

    assert snippet is not None
    assert "hiking with some buddies" in snippet.text
    assert "D14:21" in snippet.text
    assert len(snippet.text) <= 640


def test_query_focused_snippet_preserves_truncated_structured_following_markers() -> None:
    text = "\n".join(
        [
            "D14:15 Joanna: Sounds like fun! It's good to have friends.",
            "D14:16 Nate: They asked for gaming tips, so I said I could help.",
            "D14:17 Joanna: Good on you for helping strangers out.",
            "D14:18 Nate: Do you have any plans for the weekend?",
            (
                "D14:19 Joanna: Yep, I'm hiking with some buddies this weekend. "
                "We're checking out a new trail with a rad waterfall. Can't wait!"
            ),
            "D14:20 Nate: Sounds great! "
            + "I'm organizing a gaming party with friends and teammates. " * 12,
            "D14:21 Joanna: Oh? Are you going to invite your tournament friends?",
            "D14:22 Nate: Definitely.",
        ]
    )

    snippet = query_focused_snippet(
        query="How many hikes has Joanna been on?",
        text=text,
        window_chars=320,
    )

    assert snippet is not None
    assert "hiking with some buddies" in snippet.text
    assert "D14:21" in snippet.text
    assert len(snippet.text) <= 640


def test_query_focused_snippet_prefers_animal_care_facet_over_generic_career() -> None:
    plan = build_query_expansion_plan("What alternative career might Nate consider after gaming?")
    text = (
        "session_5 date: today "
        "D5:1 Nate: I worked hard on a game project and thought about what comes next. "
        "D5:2 Joanna: That sounds like a career turning point. "
        "D5:6 Nate: I'm drawn to turtles because they are calming. "
        "D5:7 Joanna: Is taking care of them tough? "
        "D5:8 Nate: No, just keep their area clean, feed them properly, "
        "and make sure they get enough light. "
        "D5:10 Nate: Pets bring joy and are cute companions."
    )

    query, reason, _ = best_query_relevance(plan, text=text)
    snippet = query_focused_snippet(query=query, text=text)

    assert reason == "animal_care_instruction_bridge"
    assert snippet is not None
    assert "D5:8 Nate:" in snippet.text
    assert "feed them properly" in snippet.text


def test_source_refs_with_query_snippet_preserves_location_metadata() -> None:
    source_ref = SourceRef(
        source_type="asset_extraction",
        source_id="artifact_1",
        chunk_id="transcript:1",
        quote_preview="old quote",
        time_start_ms=1200,
        time_end_ms=5400,
    )
    snippet = query_focused_snippet(
        query="Atlas renewal",
        text="Intro. Atlas renewal was approved. Outro.",
    )

    enriched = source_refs_with_query_snippet((source_ref,), snippet)

    assert snippet is not None
    assert enriched[0].quote_preview == snippet.text
    assert enriched[0].time_start_ms == 1200
    assert enriched[0].time_end_ms == 5400
    assert enriched[0].char_start is None
    assert enriched[0].char_end is None


def test_source_refs_with_query_snippet_can_include_snippet_char_range() -> None:
    source_ref = SourceRef(
        source_type="extraction_artifact",
        source_id="artifact_1",
        chunk_id="transcript:1",
        quote_preview="old quote",
        time_start_ms=1200,
        time_end_ms=5400,
    )
    text = "Intro before the useful detail. Atlas renewal was approved. Outro."
    snippet = query_focused_snippet(query="Atlas renewal", text=text)

    enriched = source_refs_with_query_snippet(
        (source_ref,),
        snippet,
        include_char_range=True,
    )

    assert snippet is not None
    assert enriched[0].quote_preview == snippet.text
    assert enriched[0].char_start == snippet.char_start
    assert enriched[0].char_end == snippet.char_end
    assert enriched[0].time_start_ms == 1200
    assert enriched[0].time_end_ms == 5400


def test_source_refs_with_query_snippet_keeps_secondary_quotes_bounded() -> None:
    primary = SourceRef(
        source_type="locomo_observation",
        source_id="locomo:conv-26:session_7:observation",
        chunk_id="chunk-1",
        quote_preview="old observation quote",
    )
    secondary = SourceRef(
        source_type="locomo_observation",
        source_id="locomo:conv-26:session_7:D7:4:turn",
        chunk_id="chunk-1",
        quote_preview="D7:4 Melanie praises Caroline's drive.",
        char_start=40,
        char_end=90,
    )
    text = "Intro. D7:4 Melanie praises Caroline's drive to help. Outro."
    snippet = query_focused_snippet(query="Caroline drive help", text=text)

    enriched = source_refs_with_query_snippet(
        (primary, secondary),
        snippet,
        include_char_range=True,
    )

    assert snippet is not None
    assert enriched[0].quote_preview == snippet.text
    assert enriched[0].char_start == snippet.char_start
    assert enriched[1].quote_preview == "D7:4 Melanie praises Caroline's drive."
    assert enriched[1].char_start == 40
    assert enriched[1].source_id.endswith(":D7:4:turn")


def test_query_focused_snippet_matches_russian_case_variants() -> None:
    text = (
        "Шум до полезного фрагмента. " * 10
        + "Встреча с Алексом по проекту Атлас завершилась решением сохранить запись. "
        + "Шум после полезного фрагмента. " * 10
    )

    snippet = query_focused_snippet(
        query="встречу Алекс проектом Атласом",
        text=text,
        window_chars=180,
    )

    assert snippet is not None
    assert "Встреча с Алексом по проекту Атлас" in snippet.text
    assert snippet.unique_term_hits == 4
    assert snippet.matched_terms == ("встречу", "алекс", "проектом", "атласом")


def test_query_focused_snippet_matches_english_plural_variants() -> None:
    snippet = query_focused_snippet(
        query="renewal meetings approvals",
        text="The renewal meeting approval was linked to the Atlas scope.",
    )

    assert snippet is not None
    assert "renewal meeting approval" in snippet.text
    assert snippet.unique_term_hits == 3
    assert snippet.matched_terms == ("renewal", "meetings", "approvals")


def test_query_focused_snippet_matches_cross_language_multimodal_aliases() -> None:
    snippet = query_focused_snippet(
        query="скриншот инвойса владелец Атлас Алекс",
        text=(
            "Background noise. The screenshot invoice owner Alex approved the "
            "Project Atlas renewal. More background noise."
        ),
    )

    assert snippet is not None
    assert "screenshot invoice owner Alex" in snippet.text
    assert "Project Atlas" in snippet.text
    assert snippet.unique_term_hits == 5
    assert set(snippet.matched_terms) == {
        "скриншот",
        "инвойса",
        "владелец",
        "атлас",
        "алекс",
    }
