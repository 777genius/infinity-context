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


def test_source_identity_refs_read_official_turn_metadata_mapping() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "session_key": "session_4",
                "dia_id": "D4:3",
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
    )


def test_safe_source_refs_canonicalizes_split_official_turn_metadata() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "dia_id": "D4:3",
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
    )


def test_safe_source_refs_canonicalizes_split_session_and_turn_refs() -> None:
    refs = safe_source_refs_for_output(
        ("document:profile-note", "session_4", "D4:3")
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
        "document:profile-note",
    )


def test_source_identity_refs_read_structured_dialogue_turn_fields() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "source_dialogue_id": 12,
                "source_turn_id": 6,
            },
        )
    )

    assert refs == ("source_turn_refs:D12:6",)


def test_source_identity_refs_qualify_numeric_turn_id_with_session_key() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "session_key": "session_12",
                "turn_id": "6",
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    )
