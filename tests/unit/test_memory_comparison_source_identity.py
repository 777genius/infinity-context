from __future__ import annotations

from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output,
    source_identity_audit_gap_codes,
    source_identity_refs_from_source_refs,
    source_identity_refs_from_text,
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


def test_safe_source_refs_preserves_wrapped_source_identity_order() -> None:
    refs = safe_source_refs_for_output(
        (
            "source_identity:"
            "source_session_turn_refs:session-2:D2-6|"
            "source_turn_refs:D2-6",
        )
    )

    assert refs == (
        "source_session_turn_refs:session_2:D2:6",
        "source_turn_refs:D2:6",
    )


def test_source_identity_refs_preserve_wrapped_source_identity_session() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            "source_identity:"
            "source_session_turn_refs:session-2:D2-6|"
            "source_turn_refs:D2-6",
        )
    )

    assert refs == (
        "source_session_turn_refs:session_2:D2:6",
        "source_turn_refs:D2:6",
    )


def test_safe_source_refs_reads_structured_source_identity_refs() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "source_identity_refs": [
                        "source_session_turn_refs:session-7:D7-2",
                        "source_turn_refs:D7-2",
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_7:D7:2",
        "source_turn_refs:D7:2",
    )


def test_safe_source_refs_reads_nested_source_identity_items() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "source_identity_items": [
                        {
                            "source_identity_refs": [
                                "source_session_turn_refs:session-7:D7-2"
                            ],
                        }
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_7:D7:2",
        "source_turn_refs:D7:2",
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


def test_source_identity_refs_read_locomo_evidence_ref_alias() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "session_key": "session_4",
                "locomo_evidence_ref": "D4:3",
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:3",
        "source_turn_refs:D4:3",
    )


def test_source_identity_refs_qualify_numeric_evidence_aliases_with_session() -> None:
    for evidence_key in (
        "evidence_ref",
        "evidence_id",
        "locomo_evidence_ref",
        "source_evidence_ref",
    ):
        refs = safe_source_refs_for_output(
            (
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    evidence_key: "5",
                },
            )
        )

        assert refs == (
            "source_session_turn_refs:session_4:D4:5",
            "source_turn_refs:D4:5",
        )


def test_source_identity_refs_qualify_numeric_plural_evidence_aliases_with_session() -> None:
    for evidence_key in (
        "evidence_refs",
        "evidence_ids",
        "locomo_evidence_refs",
        "source_evidence_refs",
        "turn_ids",
    ):
        refs = safe_source_refs_for_output(
            (
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    evidence_key: ("5", "6"),
                },
            )
        )

        assert refs == (
            "source_session_turn_refs:session_4:D4:5",
            "source_session_turn_refs:session_4:D4:6",
            "source_turn_refs:D4:5",
            "source_turn_refs:D4:6",
        )


def test_source_identity_refs_suppress_broad_numeric_evidence_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "session_key": "session_4",
                "source_evidence_refs": ("1", "2", "3", "4"),
            },
        )
    )

    assert refs == ("session_4",)


def test_source_identity_refs_read_plural_evidence_alias_turn_refs() -> None:
    for evidence_key in ("evidence_ids", "turn_ids"):
        refs = safe_source_refs_for_output(
            (
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    evidence_key: ("D4:5", "D4:6"),
                },
            )
        )

        assert refs == (
            "source_session_turn_refs:session_4:D4:5",
            "source_session_turn_refs:session_4:D4:6",
            "source_turn_refs:D4:5",
            "source_turn_refs:D4:6",
        )


def test_source_identity_refs_read_evidence_ref_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "source_evidence_refs": ("locomo:conv-private:D4:5",),
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )


def test_source_identity_refs_read_nested_supporting_evidence_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "supporting_evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )


def test_source_identity_refs_read_nested_supporting_fact_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "supporting_facts": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )


def test_source_identity_refs_read_nested_evidence_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )


def test_source_identity_refs_qualify_nested_numeric_evidence_aliases() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_4",
                    "supporting_evidence": [
                        {"source_evidence_ref": "5"},
                        {"turn_ids": ("6",)},
                    ],
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:5",
        "source_turn_refs:D4:6",
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


def test_safe_source_refs_preserves_auth_ref_turn_order() -> None:
    bearer_payload = "Bearer " + ("a" * 16)

    refs = safe_source_refs_for_output(
        (
            f"authorization {bearer_payload} D2:3",
            f"https://user-{('b' * 16)}@example.invalid:session_4:D4:5:turn",
        )
    )

    assert refs == (
        "source_turn_refs:D2:3",
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )


def test_safe_source_refs_preserves_safe_turn_like_labels() -> None:
    refs = safe_source_refs_for_output(
        ("chunk-D2-6", "document:D3-7", "safe-note-D4:8")
    )

    assert refs == ("chunk-D2-6", "document:D3-7", "safe-note-D4:8")


def test_safe_source_refs_do_not_qualify_safe_hyphen_label_with_session() -> None:
    refs = safe_source_refs_for_output(("session_4", "chunk-D4-3"))

    assert refs == ("session_4", "chunk-D4-3")
    assert source_identity_refs_from_source_refs(("session_4", "chunk-D4-3")) == ()


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


def test_source_identity_refs_build_turn_ref_from_dialogue_and_turn_fields() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "dia_id": "D12",
                "turn_id": "6",
            },
        )
    )

    assert refs == ("source_turn_refs:D12:6",)


def test_source_identity_refs_build_turn_ref_from_source_dia_and_turn_index() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "source_dia_id": "D12",
                "source_turn_index": "6",
            },
        )
    )

    assert refs == ("source_turn_refs:D12:6",)


def test_source_identity_refs_build_turn_ref_from_dialogue_index_aliases() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "source_dialogue_index": "D12",
                "source_turn_index": "6",
            },
        )
    )

    assert refs == ("source_turn_refs:D12:6",)


def test_source_identity_refs_build_turn_ref_from_session_dialogue_alias() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            {
                "source_external_id": "locomo:conv-private:turn-secret",
                "source_dialogue_id": "session_12",
                "source_turn_index": "6",
            },
        )
    )

    assert refs == ("source_turn_refs:D12:6",)


def test_safe_source_refs_suppress_split_dialogue_and_turn_fields() -> None:
    refs = safe_source_refs_for_output(
        (
            {
                "source_id": "locomo:conv-private:turn-secret",
                "metadata": {
                    "session_key": "session_12",
                    "dia_id": "D12",
                    "turn_id": "6",
                },
            },
        )
    )

    assert refs == (
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    )


def test_source_identity_refs_qualify_reversed_punctuated_session_text() -> None:
    refs = source_identity_refs_from_text(
        "D2:8, session 2, Priya confirmed the plan.",
        source_refs=("conversation-summary",),
    )

    assert refs == (
        "source_session_turn_refs:session_2:D2:8",
        "source_turn_refs:D2:8",
    )
    assert source_identity_audit_gap_codes(
        source_refs=("locomo:conversation:session_2", "D2:8"),
        text="D2:8, session 2, Priya confirmed the plan.",
    ) == ()
    assert source_identity_audit_gap_codes(
        source_refs=("locomo:conversation:session_2", "D2:8"),
        text="D2:8, session 3, Priya confirmed the plan.",
    ) == ("source_text_session_turn_mismatch",)


def test_source_identity_refs_qualify_session_parenthetical_turn_text() -> None:
    refs = source_identity_refs_from_text(
        "Session 2 (D2:8): Priya confirmed the plan.",
        source_refs=("conversation-summary",),
    )

    assert refs == (
        "source_session_turn_refs:session_2:D2:8",
        "source_turn_refs:D2:8",
    )
    assert source_identity_refs_from_source_refs(("session 2 (D2:8)",)) == (
        "source_session_turn_refs:session_2:D2:8",
        "source_turn_refs:D2:8",
    )
    assert safe_source_refs_for_output(("session 2 (D2:8)",)) == (
        "source_session_turn_refs:session_2:D2:8",
        "source_turn_refs:D2:8",
    )


def test_source_identity_refs_accept_dialogue_as_session_surface() -> None:
    assert source_identity_refs_from_text(
        "Dialogue 3 turn D3:6 Alex confirmed the planning date.",
        source_refs=("profile:alex-summary",),
    ) == (
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    )
    assert source_identity_refs_from_source_refs(
        ("conversation dialogue #4", "D4:8")
    ) == (
        "source_session_turn_refs:session_4:D4:8",
        "source_turn_refs:D4:8",
    )
    assert safe_source_refs_for_output(("dialogue #4", "D4:8")) == (
        "source_session_turn_refs:session_4:D4:8",
        "source_turn_refs:D4:8",
    )


def test_source_identity_refs_accept_dialog_as_session_surface() -> None:
    assert source_identity_refs_from_text(
        "Dialog 3 turn D3:6 Alex confirmed the planning date.",
        source_refs=("profile:alex-summary",),
    ) == (
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    )
    assert source_identity_refs_from_source_refs(
        ("conversation dialog #4", "D4:8")
    ) == (
        "source_session_turn_refs:session_4:D4:8",
        "source_turn_refs:D4:8",
    )
    assert safe_source_refs_for_output(("dialog #4", "D4:8")) == (
        "source_session_turn_refs:session_4:D4:8",
        "source_turn_refs:D4:8",
    )
