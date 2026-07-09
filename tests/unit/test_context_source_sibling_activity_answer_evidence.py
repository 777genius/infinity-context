from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence,
)


def test_source_sibling_answer_evidence_accepts_parent_childhood_activity() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "What activity did Caroline used to do with her dad? "
            "activity dad father parent childhood child kid younger"
        ),
        expansion_reason="family_activity_bridge",
        text=(
            "D13:7 Caroline: I used to go riding with my dad when I was a kid, "
            "and it was special."
        ),
    )


def test_source_sibling_answer_evidence_accepts_dance_destress_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How do Jon and Gina both like to destress?",
        expansion_reason="destress_activity_bridge",
        text=(
            "D1:7 Gina: Dance is pretty much my go-to for stress relief. "
            "Got any favorite styles?"
        ),
    )


def test_source_sibling_answer_evidence_accepts_dance_escape_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How do Jon and Gina both like to destress?",
        expansion_reason="destress_activity_bridge",
        text=(
            "D1:6 Jon: I've been into dancing since I was a kid, and it has "
            "been my passion and escape."
        ),
    )


def test_source_sibling_answer_evidence_rejects_broad_dance_passion_for_destress() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query="How do Jon and Gina both like to destress?",
        expansion_reason="destress_activity_bridge",
        text="D1:4 Jon: I'm starting a dance studio because I'm passionate about dancing.",
    )
