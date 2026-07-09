from infinity_context_core.application.context_causal_reason_rerank import (
    yoga_delay_gaming_answer_rank,
)
from infinity_context_core.application.context_english_activity_displacement_answer_support import (
    english_activity_displacement_turn_candidates,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_yoga_delay_gaming_rank_prefers_planned_alternative_activity() -> None:
    assert (
        yoga_delay_gaming_answer_rank(
            "D2:4 Sam: We planned to play the console with my partner."
        )
        == 0
    )
    assert (
        yoga_delay_gaming_answer_rank(
            'D3:2 Sam: We are planning to play "Space Trail" next Saturday.'
        )
        == 0
    )
    assert (
        yoga_delay_gaming_answer_rank(
            'D1:9 Sam: We were gaming last week and played "Drift City" on the console.'
        )
        == 1
    )
    assert (
        yoga_delay_gaming_answer_rank(
            "D4:1 Sam image caption: a photo of a new game console beside a figure."
        )
        > 1
    )


def test_activity_displacement_candidates_prefer_planned_gaming_turns() -> None:
    broad_recent_gaming = _activity_displacement_item(
        "recent_gaming",
        'D1:9 Sam: We were gaming last week and played "Drift City" on the console.',
        source_id="locomo:fixture:session_1:D1:9:turn",
        score=0.99,
    )
    planned_console = _activity_displacement_item(
        "planned_console",
        "D2:4 Sam: Well, we planned to play the console with my partner.",
        source_id="locomo:fixture:session_2:D2:4:turn",
        score=0.91,
    )
    planned_named_game = _activity_displacement_item(
        "planned_named_game",
        'D3:2 Sam: We are planning to play "Space Trail" next Saturday.',
        source_id="locomo:fixture:session_3:D3:2:turn",
        score=0.9,
    )

    candidates = english_activity_displacement_turn_candidates(
        [broad_recent_gaming, planned_console, planned_named_game],
        query="Why did Sam sometimes put off doing yoga?",
        limit=3,
    )

    assert tuple(item.item_id for item in candidates[:2]) == (
        "planned_console",
        "planned_named_game",
    )


def test_context_packer_keeps_planned_gaming_evidence_for_yoga_delay() -> None:
    broad_recent_gaming = _activity_displacement_item(
        "recent_gaming",
        'D1:9 Sam: We were gaming last week and played "Drift City" on the console.',
        source_id="locomo:fixture:session_1:D1:9:turn",
        score=0.99,
    )
    yoga_context = _activity_displacement_item(
        "yoga_context",
        "D4:5 Sam: Yoga usually helped me feel calm after a busy week.",
        source_id="locomo:fixture:session_4:D4:5:turn",
        score=0.98,
    )
    planned_console = _activity_displacement_item(
        "planned_console",
        "D2:4 Sam: Well, we planned to play the console with my partner.",
        source_id="locomo:fixture:session_2:D2:4:turn",
        score=0.91,
    )
    planned_named_game = _activity_displacement_item(
        "planned_named_game",
        'D3:2 Sam: We are planning to play "Space Trail" next Saturday.',
        source_id="locomo:fixture:session_3:D3:2:turn",
        score=0.9,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_activity_displacement",
        items=(broad_recent_gaming, yoga_context, planned_console, planned_named_game),
        query="Why did Sam sometimes put off doing yoga?",
        token_budget=180,
        max_rendered_chars=900,
    )

    rendered = result.bundle.rendered_text
    assert "D2:4" in rendered
    assert "planned to play the console" in rendered
    assert "D3:2" in rendered
    assert "Space Trail" in rendered


def _activity_displacement_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    score: float,
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
                chunk_id=item_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "query_expansion_reason": "yoga_delay_gaming_bridge",
        },
    )
