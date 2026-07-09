from infinity_context_core.application.context_creative_work_count_exact_turns import (
    exact_creative_work_count_turn_candidates,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_creative_work_count_exact_turns_keep_authored_ordinals() -> None:
    first_script = _creative_item(
        "first_script",
        "D2:3 Dana: I finished my first screenplay for a workshop.",
        source_id="locomo:conv-fixture:session_2:D2:3:turn",
    )
    second_script = _creative_item(
        "second_script",
        "D5:1 Dana: I wrapped up my second script last night.",
        source_id="locomo:conv-fixture:session_5:D5:1:turn",
    )
    third_question = _creative_item(
        "third_question",
        "D12:13 Morgan: Wow Dana, is that your third one?",
        source_id="locomo:conv-fixture:session_12:D12:13:turn",
    )
    third_confirmation = _creative_item(
        "third_confirmation",
        (
            "D12:14 Dana: Yep! I chose to write this story after thinking "
            "about my family."
        ),
        source_id="locomo:conv-fixture:session_12:D12:14:turn",
    )
    contributed_noise = _creative_item(
        "contributed_noise",
        (
            "D25:2 Dana: Another movie script I contributed to was shown on "
            "the big screen."
        ),
        source_id="locomo:conv-fixture:session_25:D25:2:turn",
    )
    in_progress_noise = _creative_item(
        "in_progress_noise",
        "D27:6 Dana: I'm writing another movie script this month.",
        source_id="locomo:conv-fixture:session_27:D27:6:turn",
    )
    book_noise = _creative_item(
        "book_noise",
        "D28:4 Dana: I finished writing the book about a family story.",
        source_id="locomo:conv-fixture:session_28:D28:4:turn",
    )
    blog_noise = _creative_item(
        "blog_noise",
        "D29:5 Dana: Someone wrote after reading my blog post about loss.",
        source_id="locomo:conv-fixture:session_29:D29:5:turn",
    )

    selected = exact_creative_work_count_turn_candidates(
        (
            contributed_noise,
            in_progress_noise,
            book_noise,
            blog_noise,
            third_question,
            second_script,
            third_confirmation,
            first_script,
        ),
        query="How many screenplays has Dana written?",
        limit=8,
    )

    assert [item.item_id for item in selected] == [
        "first_script",
        "second_script",
        "third_question",
        "third_confirmation",
    ]


def test_creative_work_count_exact_turns_focus_marker_runs() -> None:
    shared_summary = _creative_item(
        "shared_summary",
        (
            "D3:4 D3:6 Dana: Dana finished her second script and printed it "
            "for a table read. D3:7 Morgan: The rehearsal starts tomorrow."
        ),
        source_id="locomo:conv-fixture:session_3:D3:4:turn",
    )

    selected = exact_creative_work_count_turn_candidates(
        (shared_summary,),
        query="How many scripts has Dana written?",
        limit=4,
    )

    assert len(selected) == 1
    assert selected[0].item_id.startswith("shared_summary")
    assert selected[0].source_refs[0].source_id.endswith("D3:4:turn")
    assert "Dana finished her second script" in selected[0].text
    assert "rehearsal starts tomorrow" not in selected[0].text


def test_creative_work_count_exact_turns_infer_visible_neighbor_markers() -> None:
    anchored_chunk = _creative_item(
        "anchored_chunk",
        (
            "D8:2 Dana: The notebook photo shows my draft on the desk. "
            "D8:3 Morgan: Wow Dana, is that your third one? "
            "D8:4 Dana: Yep! I chose to write this story after thinking "
            "about my family."
        ),
        source_id="locomo:conv-fixture:session_8:D8:2:turn",
    )

    selected = exact_creative_work_count_turn_candidates(
        (anchored_chunk,),
        query="How many screenplays has Dana written?",
        limit=4,
    )

    selected_source_ids = {str(item.source_refs[0].source_id) for item in selected}
    assert "locomo:conv-fixture:session_8:D8:3:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_8:D8:4:turn" in selected_source_ids
    assert any("is that your third one" in item.text for item in selected)
    assert any("chose to write this story" in item.text for item in selected)


def test_context_packer_keeps_creative_work_count_turns_before_broad_chunks() -> None:
    exact_turns = (
        _creative_item(
            "first_script",
            "D2:3 Dana: I finished my first screenplay for a workshop.",
            source_id="locomo:conv-fixture:session_2:D2:3:turn",
            score=0.72,
        ),
        _creative_item(
            "second_script",
            "D5:1 Dana: I wrapped up my second script last night.",
            source_id="locomo:conv-fixture:session_5:D5:1:turn",
            score=0.71,
        ),
        _creative_item(
            "third_question",
            "D12:13 Morgan: Wow Dana, is that your third one?",
            source_id="locomo:conv-fixture:session_12:D12:13:turn",
            score=0.70,
        ),
        _creative_item(
            "third_confirmation",
            (
                "D12:14 Dana: Yep! I chose to write this story after "
                "thinking about my family."
            ),
            source_id="locomo:conv-fixture:session_12:D12:14:turn",
            score=0.69,
        ),
    )
    broad_noise = tuple(
        _creative_item(
            f"broad_{index}",
            (
                f"D{index}:1 Dana discussed screenplays, production feedback, "
                "festival schedules, and movie script planning."
            ),
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            score=0.99 - index * 0.001,
        )
        for index in range(30, 38)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_creative_work_count",
        items=(*broad_noise, *exact_turns),
        query="How many screenplays has Dana written?",
        token_budget=500,
        max_rendered_chars=1300,
    )

    rendered = result.bundle.rendered_text
    assert "D2:3 Dana: I finished my first screenplay" in rendered
    assert "D5:1 Dana: I wrapped up my second script" in rendered
    assert "D12:13 Morgan: Wow Dana, is that your third one?" in rendered
    assert "D12:14 Dana: Yep! I chose to write this story" in rendered


def _creative_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    score: float = 0.9,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "screenplay-count-bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
