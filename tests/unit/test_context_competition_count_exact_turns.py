from infinity_context_core.application.context_competition_count_exact_turns import (
    exact_competition_count_turn_candidates,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_competition_count_exact_turns_keep_direct_win_events() -> None:
    direct_win = _competition_item(
        "direct_win",
        (
            "D14:8 Riley: I just won another regional video game tournament "
            "last week."
        ),
        source_id="locomo:conv-fixture:session_14:D14:8:turn",
    )
    generic_reference = _competition_item(
        "generic_reference",
        (
            "D26:4 Riley: Recognition feels great, just like when I win a "
            "video game tournament."
        ),
        source_id="locomo:conv-fixture:session_26:D26:4:turn",
    )
    congratulations = _competition_item(
        "congratulations",
        "D14:9 Morgan: Congratulations on your victory in the tournament!",
        source_id="locomo:conv-fixture:session_14:D14:9:turn",
    )

    selected = exact_competition_count_turn_candidates(
        (generic_reference, congratulations, direct_win),
        query="How many tournaments has Riley won?",
        limit=4,
    )

    assert [item.item_id for item in selected] == ["direct_win"]


def test_competition_count_exact_turns_keep_participation_setbacks() -> None:
    participating = _competition_item(
        "participating",
        (
            "D6:7 Riley: I'm currently participating in the video game "
            "tournament again."
        ),
        source_id="locomo:conv-fixture:session_6:D6:7:turn",
    )
    setback = _competition_item(
        "setback",
        (
            "D20:1 Riley: I had a letdown in a video game tourney and "
            "didn't do too great, even though I tried."
        ),
        source_id="locomo:conv-fixture:session_20:D20:1:turn",
    )
    win = _competition_item(
        "win",
        "D22:2 Riley: I won a really big video game tournament last week.",
        source_id="locomo:conv-fixture:session_22:D22:2:turn",
    )

    selected = exact_competition_count_turn_candidates(
        (setback, win, participating),
        query="How many video game tournaments has Riley participated in?",
        limit=4,
    )

    assert [item.item_id for item in selected] == ["participating", "setback", "win"]


def test_competition_count_exact_turns_accept_derived_event_summaries() -> None:
    international_win = _competition_item(
        "international_win",
        (
            "D19:1 Riley: Riley enters and wins an international video game "
            "tournament."
        ),
        source_id="locomo:conv-fixture:session_19:D19:1:turn",
    )
    setback = _competition_item(
        "setback_summary",
        (
            "D20:1 Riley: Riley faces a setback because she doesn't do too "
            "well in a video game tournament."
        ),
        source_id="locomo:conv-fixture:session_20:D20:1:turn",
    )
    generic_reference = _competition_item(
        "generic_reference",
        (
            "D26:4 Riley: Recognition feels great, just like when I win a "
            "video game tournament."
        ),
        source_id="locomo:conv-fixture:session_26:D26:4:turn",
    )

    selected = exact_competition_count_turn_candidates(
        (generic_reference, setback, international_win),
        query="How many video game tournaments has Riley participated in?",
        limit=4,
    )

    assert [item.item_id for item in selected] == [
        "international_win",
        "setback_summary",
    ]


def test_competition_count_exact_turns_focus_marker_runs_with_shared_summary() -> None:
    shared_summary = _competition_item(
        "shared_summary",
        (
            "D3:4 D3:6 Riley: Riley wins the local arcade tournament, which "
            "is her second win in video game tournaments."
        ),
        source_id="locomo:conv-fixture:session_3:D3:4:turn",
    )

    selected = exact_competition_count_turn_candidates(
        (shared_summary,),
        query="How many tournaments has Riley won?",
        limit=4,
    )

    assert [item.item_id for item in selected] == ["shared_summary"]
    assert selected[0].source_refs[0].source_id.endswith("D3:4:turn")
    assert "Riley wins the local arcade tournament" in selected[0].text


def test_context_packer_keeps_tournament_count_exact_turns_before_broad_chunks() -> None:
    exact_turns = (
        _competition_item(
            "first_win",
            "D1:3 Riley: I won my first video game tournament last week.",
            source_id="locomo:conv-fixture:session_1:D1:3:turn",
            score=0.72,
        ),
        _competition_item(
            "regional_win",
            (
                "D14:8 Riley: I just won another regional video game tournament "
                "last week."
            ),
            source_id="locomo:conv-fixture:session_14:D14:8:turn",
            score=0.71,
        ),
        _competition_item(
            "international_win",
            "D19:1 Riley: I won an international tournament yesterday.",
            source_id="locomo:conv-fixture:session_19:D19:1:turn",
            score=0.70,
        ),
    )
    broad_noise = tuple(
        _competition_item(
            f"broad_{index}",
            (
                f"D{index}:1 Riley discussed tournaments, practice, gaming "
                "friends, and schedules."
            ),
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            score=0.99 - index * 0.001,
        )
        for index in range(30, 38)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_tournament_count",
        items=(*broad_noise, *exact_turns),
        query="How many tournaments has Riley won?",
        token_budget=600,
        max_rendered_chars=1400,
    )

    rendered = result.bundle.rendered_text
    assert "D1:3 Riley: I won my first video game tournament" in rendered
    assert "D14:8 Riley: I just won another regional video game tournament" in rendered
    assert "D19:1 Riley: I won an international tournament" in rendered


def _competition_item(
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
                "query_expansion_reason": "tournament_count_bridge",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
