from __future__ import annotations

from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output,
    source_identity_refs_from_source_refs,
)


def test_source_identity_refs_preserve_session_for_bare_locomo_turn_ref() -> None:
    refs = source_identity_refs_from_source_refs(
        ("locomo:conv-1:session_4:D4:3",),
        include_exact_turn_refs=True,
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
    )


def test_safe_source_refs_normalizes_bare_private_locomo_turn_ref() -> None:
    refs = safe_source_refs_for_output(("locomo:conv-private:session_4:D4:3",))

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
    )
