from __future__ import annotations

from infinity_context_server.memory_comparison_source_identity import (
    source_identity_audit_gap_codes,
    source_identity_refs_from_text,
)


def test_source_identity_refs_qualify_parenthetical_session_after_turn() -> None:
    refs = source_identity_refs_from_text(
        "D2:8 (session 2) Priya confirmed the plan.",
        source_refs=("conversation-summary",),
    )

    assert refs == (
        "source_session_turn_refs:session_2:D2:8",
        "source_turn_refs:D2:8",
    )
    assert source_identity_audit_gap_codes(
        source_refs=("locomo:conversation:session_2", "D2:8"),
        text="D2:8 (session 2) Priya confirmed the plan.",
    ) == ()


def test_source_identity_refs_do_not_qualify_mismatched_parenthetical_session() -> None:
    refs = source_identity_refs_from_text(
        "D2:8 (session 3) Priya confirmed the plan.",
        source_refs=("conversation-summary",),
    )

    assert refs == ("source_turn_refs:D2:8",)
    assert source_identity_audit_gap_codes(
        source_refs=("locomo:conversation:session_2", "D2:8"),
        text="D2:8 (session 3) Priya confirmed the plan.",
    ) == ("source_text_session_turn_mismatch",)


def test_source_identity_audit_flags_split_session_turn_source_mismatch() -> None:
    assert source_identity_audit_gap_codes(
        source_refs=("locomo:conversation:session_2", "D3:8"),
        text="D3:8 Priya confirmed the plan.",
    ) == ("source_session_turn_mismatch",)
