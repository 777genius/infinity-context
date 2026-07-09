from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    reason: str,
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
            "query_expansion_reason": reason,
            "source_sibling_answer_evidence": 1 if "signed" in text.casefold() else 0,
        },
    )


def test_context_packer_keeps_exact_collectible_object_evidence_before_sports_noise() -> None:
    noise = tuple(
        _item(
            item_id=f"sports_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:3:turn",
            text=(
                f"D{index}:3 Jordan: Basketball practice was intense and the "
                "team played with a strong bond."
            ),
            reason="decomposition_activity_participation",
            score=0.99 - index * 0.001,
        )
        for index in range(1, 8)
    )
    collectible_items = (
        _item(
            item_id="signed_team_ball",
            source_id="locomo:conv-fixture:session_9:D9:7:turn",
            text=(
                "D9:7 Jordan: My teammates gave me a basketball signed by "
                "everyone. It is a reminder of our friendship and appreciation."
            ),
            reason="decomposition_collectible_object",
            score=0.78,
        ),
        _item(
            item_id="prized_player_ball",
            source_id="locomo:conv-fixture:session_16:D16:7:turn",
            text=(
                "D16:7 Avery: I have a prized possession too - a basketball "
                "signed by my favorite player."
            ),
            reason="decomposition_collectible_object",
            score=0.77,
        ),
    )

    result = ContextPacker().pack(
        bundle_id="ctx_collectible_object",
        items=(*noise, *collectible_items),
        query="What similar sports collectible do Avery and Jordan own?",
        token_budget=220,
        max_rendered_chars=3000,
    )

    rendered = result.bundle.rendered_text
    assert "basketball signed by everyone" in rendered
    assert "basketball signed by my favorite player" in rendered
    first_noise = rendered.index("chunk:sports_noise_1")
    assert rendered.index("chunk:signed_team_ball") < first_noise
    assert rendered.index("chunk:prized_player_ball") < first_noise
