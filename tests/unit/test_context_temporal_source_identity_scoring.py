import pytest
from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.context_temporal_source_identity import (
    source_identity_matches,
    source_scope_identity_from_mapping,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_source_scoped_turn_query_penalizes_identified_different_session() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    item = _item(
        "identified_other_session",
        text="D13:6 Riley discussed another session.",
        source_id="locomo:conv-1:session_13:D13:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.702
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item has a different session"
    )


def test_source_scoped_turn_query_diagnostics_keep_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == [
        "locomo:conv-1:session_12:d*:t*:turn"
    ]


def test_separate_source_scope_diagnostics_keep_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns of D12:4 in source "
        "locomo:conv-1:session_12?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == [
        "locomo:conv-1:session_12"
    ]


def test_prefix_source_scope_diagnostics_keep_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in source locomo:conv-1:session_12 "
        "within 2 turns of D12:4?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == [
        "locomo:conv-1:session_12"
    ]


def test_direct_locomo_scope_diagnostics_keep_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in locomo:conv-1:session_12 after D12:4?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == [
        "locomo:conv-1:session_12"
    ]


def test_direct_session_name_does_not_become_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in session_12 after D12:4?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == []


def test_source_scope_identity_mapping_normalizes_explicit_numeric_session_aliases() -> None:
    assert source_scope_identity_from_mapping({"locomo_session_index": 12}) == "session_12"
    assert source_scope_identity_from_mapping({"source_session_index": 12}) == "session_12"
    assert source_scope_identity_from_mapping({"source_session_number": "12"}) == "session_12"
    assert source_scope_identity_from_mapping({"session_index": "12"}) == "session_12"
    assert source_scope_identity_from_mapping({"session_id": 12}) == ""
    assert (
        source_scope_identity_from_mapping(
            {"source_identity_ref": "locomo:conv-1:session_12"}
        )
        == "locomo:conv-1:session_12"
    )


@pytest.mark.parametrize(
    ("mapping", "expected"),
    (
        (
            {"conversation_id": "locomo:conv-1", "session_id": "session_12"},
            "locomo:conv-1:session_12",
        ),
        (
            {"conversation_key": "conv-1", "source_session_number": "12"},
            "conv-1:session_12",
        ),
        ({"conversation_id": 1, "source_session_index": 12}, "conv_1:session_12"),
        (
            {"conversation_key": "conversation_1", "session_number": "12"},
            "conv_1:session_12",
        ),
        ({"conversation_id": 1, "source_dialogue_id": "D12"}, "conv_1:session_12"),
        (
            {"conversation_id": 1, "dialogue_id": "dialogue_12"},
            "conv_1:session_12",
        ),
        (
            {
                "conversation_id": 1,
                "source_turn": {"dialogue_id": 12, "turn_id": 6},
            },
            "conv_1:session_12",
        ),
        (
            {"conversation_id": 1, "source_turn_refs": ["D12:6"]},
            "conv_1:session_12",
        ),
        (
            {
                "source_id": "conversation-summary",
                "conversation_id": 1,
                "session_index": 12,
            },
            "conv_1:session_12",
        ),
        (
            {
                "source_id": "locomo:conv-9:session_99",
                "conversation_id": 1,
                "session_index": 12,
            },
            "locomo:conv-9:session_99",
        ),
        (
            {"conversation_id": "private-run-abc", "session_id": "session_12"},
            "session_12",
        ),
        (
            {"conversation_id": "conversation-private", "session_id": "session_12"},
            "session_12",
        ),
    ),
)
def test_source_scope_identity_mapping_combines_conversation_and_session_aliases(
    mapping: dict[str, object],
    expected: str,
) -> None:
    assert source_scope_identity_from_mapping(mapping) == expected


def test_source_identity_matches_conversation_separator_variants() -> None:
    assert source_identity_matches(
        "conv_1:session_12",
        "locomo:conv-1:session_12:d*:t*:turn",
    )
    assert source_identity_matches(
        "conversation_1:session_12:d*:t*:turn",
        "conv-1-session_12-d*:t*:turn",
    )
    assert not source_identity_matches(
        "conversation_2:session_12:d*:t*:turn",
        "locomo:conv-1:session_12:d*:t*:turn",
    )


def test_ambiguous_prefix_source_scope_does_not_choose_first_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in source locomo:conv-1:session_12 and "
        "in source locomo:conv-2:session_12 after D12:4?"
    )

    assert intent.diagnostics()["temporal_query_source_turn_identities"] == []


def test_source_scoped_turn_query_penalizes_identified_different_conversation() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    item = _item(
        "identified_other_conversation",
        text="D12:6 Riley discussed another conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.694
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_source_scoped_turn_query_uses_structured_diagnostic_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = ContextItem(
        item_id="structured_same_source",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "source_id": "locomo:conv-1:session_12",
            "source_dialogue_id": 12,
            "source_turn_id": 6,
        },
    )
    different_source = ContextItem(
        item_id="structured_different_source",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "source_id": "locomo:conv-2:session_12",
            "source_dialogue_id": 12,
            "source_turn_id": 6,
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["structured_same_source"].score == 0.76
    assert by_id["structured_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["structured_different_source"].score == 0.694
    assert by_id["structured_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_uses_nested_metadata_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = ContextItem(
        item_id="metadata_same_source",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "source_id": "locomo:conv-1:session_12",
                "source_turn": {"dialogue_id": 12, "source_turn": 6},
            },
        },
    )
    different_source = ContextItem(
        item_id="metadata_different_source",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "source_id": "locomo:conv-2:session_12",
                "source_turn": {"dialogue_id": 12, "source_turn": 6},
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_same_source"].score == 0.76
    assert by_id["metadata_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_different_source"].score == 0.694
    assert by_id["metadata_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_uses_source_external_id_metadata_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = _metadata_item(
        "metadata_source_external_id_same_source",
        metadata={
            "source_external_id": "locomo:conv-1:session_12",
            "dia_id": "D12:6",
        },
    )
    different_source = _metadata_item(
        "metadata_source_external_id_different_source",
        text="Riley discussed a different conversation.",
        metadata={
            "source_external_id": "locomo:conv-2:session_12",
            "dia_id": "D12:6",
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_source_external_id_same_source"].score == 0.76
    assert by_id["metadata_source_external_id_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_source_external_id_different_source"].score == 0.694
    assert by_id["metadata_source_external_id_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_uses_source_identity_ref_metadata_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = _metadata_item(
        "metadata_source_identity_ref_same_source",
        metadata={
            "source_identity_ref": "locomo:conv-1:session_12",
            "dia_id": "D12:6",
        },
    )
    different_source = _metadata_item(
        "metadata_source_identity_ref_different_source",
        text="Riley discussed a different conversation.",
        metadata={
            "source_identity_ref": "locomo:conv-2:session_12",
            "dia_id": "D12:6",
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_source_identity_ref_same_source"].score == 0.76
    assert by_id["metadata_source_identity_ref_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_source_identity_ref_different_source"].score == 0.694
    assert by_id["metadata_source_identity_ref_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_uses_session_key_metadata_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after D12:4 in source session_12?"
    )
    same_session = _metadata_item(
        "metadata_session_key_same_source",
        metadata={"session_key": "session_12", "dia_id": "D12:6"},
    )
    different_session = _metadata_item(
        "metadata_session_key_different_source",
        text="Riley discussed a different session.",
        metadata={"session_key": "session_13", "dia_id": "D12:6"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, same_session),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_session_key_same_source"].score == 0.76
    assert by_id["metadata_session_key_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_session_key_different_source"].score == 0.694
    assert by_id["metadata_session_key_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


SESSION_ALIAS_METADATA_CASES = (
    (
        "metadata_locomo_session_key_same_source",
        {"locomo_session_key": "session_12", "dia_id": "D12:6"},
    ),
    (
        "metadata_locomo_session_number_same_source",
        {"locomo_session_number": 12, "turn_id": 6},
    ),
    (
        "metadata_locomo_session_index_same_source",
        {"locomo_session_index": 12, "turn_id": 6},
    ),
    (
        "official_metadata_source",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_key": "session_4",
            "dia_id": "D4:5",
        },
    ),
    (
        "metadata_numeric_session_key_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_key": "12",
            "turn_id": 6,
        },
    ),
    (
        "metadata_session_number_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_number": 12,
            "turn_id": 6,
        },
    ),
    (
        "metadata_session_order_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_order": 12,
            "turn_id": 6,
        },
    ),
    (
        "metadata_session_index_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_index": 12,
            "turn_id": 6,
        },
    ),
    (
        "metadata_numeric_source_session_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "source_session_id": 12,
            "turn_id": 6,
        },
    ),
    (
        "metadata_source_session_index_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "source_session_index": 12,
            "turn_id": 6,
        },
    ),
    (
        "metadata_source_session_number_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "source_session_number": "12",
            "turn_id": 6,
        },
    ),
    (
        "metadata_string_numeric_source_session_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "source_session_id": "12",
            "turn_id": 6,
        },
    ),
    (
        "metadata_source_dia_id_turn_id",
        {
            "source_external_id": "locomo:conv-private:turn-secret",
            "session_key": "session_12",
            "source_dia_id": "D12",
            "turn_id": 6,
        },
    ),
)


@pytest.mark.parametrize(("item_id", "metadata"), SESSION_ALIAS_METADATA_CASES)
def test_source_scoped_turn_query_uses_session_alias_metadata_identity(
    item_id: str,
    metadata: dict[str, object],
) -> None:
    if item_id == "official_metadata_source":
        intent = build_temporal_query_intent(
            "What did Riley mention after D4:3 in source session_4?"
        )
    else:
        intent = build_temporal_query_intent(
            "What did Riley mention after D12:4 in source session_12?"
        )
    item = _metadata_item(item_id, metadata=metadata)

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.76
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )


def test_source_scoped_turn_query_combines_session_key_with_numeric_turn_id() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after D12:4 in source session_12?"
    )
    same_session = _metadata_item(
        "metadata_session_key_turn_id_same_source",
        metadata={"session_key": "session_12", "turn_id": 6},
    )
    different_session = _metadata_item(
        "metadata_session_key_turn_id_different_source",
        text="Riley discussed a different session.",
        metadata={"session_key": "session_13", "turn_id": 6},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, same_session),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_session_key_turn_id_same_source"].score == 0.76
    assert by_id["metadata_session_key_turn_id_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_session_key_turn_id_different_source"].score == 0.702
    assert by_id["metadata_session_key_turn_id_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item has a different session"


def test_source_scoped_turn_query_ignores_opaque_session_id_as_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    item = ContextItem(
        item_id="opaque_session_id",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {"session_id": "private-run-abc", "dia_id": "D12:6"},
        },
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics


def test_source_scoped_turn_query_combines_source_scope_with_numeric_turn_id() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = ContextItem(
        item_id="metadata_scope_turn_id_same_source",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "session_id": "private-run-abc",
                "source_external_id": "locomo:conv-1:session_12",
                "turn_id": 6,
            },
        },
    )
    different_source = ContextItem(
        item_id="metadata_scope_turn_id_different_source",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "session_id": "private-run-abc",
                "source_external_id": "locomo:conv-2:session_12",
                "turn_id": 6,
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_scope_turn_id_same_source"].score == 0.76
    assert by_id["metadata_scope_turn_id_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_scope_turn_id_different_source"].score == 0.694
    assert by_id["metadata_scope_turn_id_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_combines_source_identity_with_numeric_turn_id() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = ContextItem(
        item_id="metadata_source_identity_turn_id_same_source",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "source_identity": "locomo:conv-1:session_12",
                "turn_id": 6,
            },
        },
    )
    different_source = ContextItem(
        item_id="metadata_source_identity_turn_id_different_source",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "metadata": {
                "source_identity": "locomo:conv-2:session_12",
                "turn_id": 6,
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["metadata_source_identity_turn_id_same_source"].score == 0.76
    assert by_id["metadata_source_identity_turn_id_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["metadata_source_identity_turn_id_different_source"].score == 0.694
    assert by_id["metadata_source_identity_turn_id_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


CONVERSATION_SOURCE_IDENTITY_CASES = (
    (
        "conversation_session_turn_id",
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?",
        {"conversation_id": "conv-1", "session_id": "session_12", "turn_id": 6},
        {"conversation_id": "conv-2", "session_id": "session_12", "turn_id": 6},
        (),
    ),
    (
        "numeric_conversation_session_turn_id",
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?",
        {"conversation_id": 1, "session_index": 12, "turn_id": 6},
        {"conversation_id": 2, "session_index": 12, "turn_id": 6},
        (),
    ),
    (
        "conversation_label_source_ref",
        "What did Riley mention after source ref conversation_1:session_12:D12:4:turn?",
        {"conversation_id": 1, "session_index": 12, "turn_id": 6},
        {"conversation_id": 2, "session_index": 12, "turn_id": 6},
        (),
    ),
    (
        "direct_conversation_label_scope",
        "What did Riley mention after D12:4 in conversation_1:session_12?",
        {"conversation_id": 1, "session_index": 12, "turn_id": 6},
        {"conversation_id": 2, "session_index": 12, "turn_id": 6},
        ("conv_1:session_12",),
    ),
    (
        "conversation_dialogue_turn_id",
        "What did Riley mention after source ref conversation_1:session_12:D12:4:turn?",
        {"conversation_id": 1, "source_dialogue_id": "D12", "turn_id": 6},
        {"conversation_id": 2, "source_dialogue_id": "D12", "turn_id": 6},
        (),
    ),
    (
        "conversation_nested_source_turn",
        "What did Riley mention after source ref conversation_1:session_12:D12:4:turn?",
        {"conversation_id": 1, "source_turn": {"dialogue_id": 12, "turn_id": 6}},
        {"conversation_id": 2, "source_turn": {"dialogue_id": 12, "turn_id": 6}},
        (),
    ),
    (
        "conversation_source_turn_refs",
        "What did Riley mention after source ref conversation_1:session_12:D12:4:turn?",
        {"conversation_id": 1, "source_turn_refs": ["D12:6"]},
        {"conversation_id": 2, "source_turn_refs": ["D12:6"]},
        (),
    ),
    (
        "generic_source_id_with_conversation_metadata",
        "What did Riley mention after source ref conversation_1:session_12:D12:4:turn?",
        {
            "source_id": "conversation-summary",
            "conversation_id": 1,
            "session_index": 12,
            "turn_id": 6,
        },
        {
            "source_id": "conversation-summary",
            "conversation_id": 2,
            "session_index": 12,
            "turn_id": 6,
        },
        (),
    ),
)


@pytest.mark.parametrize(
    (
        "case_id",
        "query",
        "same_metadata",
        "different_metadata",
        "expected_query_identities",
    ),
    CONVERSATION_SOURCE_IDENTITY_CASES,
)
def test_source_scoped_turn_query_combines_conversation_source_identity_shapes(
    case_id: str,
    query: str,
    same_metadata: dict[str, object],
    different_metadata: dict[str, object],
    expected_query_identities: tuple[str, ...],
) -> None:
    intent = build_temporal_query_intent(query)
    same_source = _metadata_item(f"{case_id}_same_source", metadata=same_metadata)
    different_source = _metadata_item(
        f"{case_id}_different_source",
        text="Riley discussed a different conversation.",
        metadata=different_metadata,
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    if expected_query_identities:
        assert intent.diagnostics()["temporal_query_source_turn_identities"] == list(
            expected_query_identities
        )
    assert by_id[f"{case_id}_same_source"].score == 0.76
    assert by_id[f"{case_id}_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id[f"{case_id}_different_source"].score == 0.694
    assert by_id[f"{case_id}_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_uses_nested_provenance_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = _structured_source_item(
        "provenance_same_source",
        source_id="locomo:conv-1:session_12",
        diagnostics_key="provenance",
    )
    different_source = _structured_source_item(
        "provenance_different_source",
        source_id="locomo:conv-2:session_12",
        diagnostics_key="provenance",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["provenance_same_source"].score == 0.76
    assert by_id["provenance_same_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["provenance_different_source"].score == 0.694
    assert by_id["provenance_different_source"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_source_scoped_turn_query_leaves_bare_different_session_neutral() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    item = _item(
        "bare_other_session",
        text="D13:6 Riley discussed an unidentified session.",
        source_id="manual-note",
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics


def test_prefix_source_scope_radius_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in source locomo:conv-1:session_12 "
        "within 2 turns of D12:4?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.742
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn is within radius"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_prefix_source_scope_after_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention from source locomo:conv-1:session_12 after D12:4?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_direct_locomo_scope_after_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in locomo:conv-1:session_12 after D12:4?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_direct_locomo_scope_near_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention around D12:4 in locomo:conv-1:session_12?"
    )
    same_source = _item(
        "same_source",
        text="D12:4 Riley mentioned the studio visit.",
        source_id="locomo:conv-1:session_12:D12:4:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:4 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:4:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn matches boundary"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_direct_locomo_scope_radius_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in locomo:conv-1:session_12 "
        "within 2 turns of D12:4?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.742
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn is within radius"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_prefix_source_scope_window_query_does_not_cross_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention in source locomo:conv-1:session_12 "
        "between D12:4 and D12:8?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_mixed_directional_window_shares_unambiguous_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn before D12:8?"
    )
    assert intent.source_turn_sequence.before_turns[0].source_identity == (
        intent.source_turn_sequence.after_turns[0].source_identity
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_mixed_directional_window_shares_source_identity_from_second_boundary() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after D12:4 before source ref "
        "locomo:conv-1:session_12:D12:8:turn?"
    )
    assert intent.source_turn_sequence.after_turns[0].source_identity == (
        intent.source_turn_sequence.before_turns[0].source_identity
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12:D12:6:turn",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12:D12:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_source_scoped_radius_query_penalizes_identified_different_session() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns of D12:4 in source "
        "locomo:conv-1:session_12?"
    )
    item = _item(
        "identified_other_session",
        text="D13:6 Riley discussed another session.",
        source_id="locomo:conv-1:session_13:D13:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.702
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item has a different session"
    )


def test_source_scoped_window_query_penalizes_identified_different_session() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8 in source "
        "locomo:conv-1:session_12?"
    )
    item = _item(
        "identified_other_session",
        text="D13:6 Riley discussed another session.",
        source_id="locomo:conv-1:session_13:D13:6:turn",
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.702
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item has a different session"
    )


def test_source_ref_scope_applies_to_item_text_turn_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source = _item(
        "same_source",
        text="D12:6 Riley said Morgan confirmed the studio visit.",
        source_id="locomo:conv-1:session_12",
    )
    different_source = _item(
        "different_source",
        text="D12:6 Riley discussed a different conversation.",
        source_id="locomo:conv-2:session_12",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source, same_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source"].score == 0.76
    assert by_id["same_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source"].score == 0.694
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def test_ambiguous_source_ref_scopes_do_not_apply_to_item_text_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    item = ContextItem(
        item_id="ambiguous_source_refs",
        item_type="fact",
        text="D12:6 Riley mentioned the studio visit.",
        score=0.72,
        source_refs=(
            SourceRef(source_type="document", source_id="locomo:conv-1:session_12"),
            SourceRef(source_type="document", source_id="locomo:conv-2:session_12"),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts((item,), intent=intent)

    assert boosted[0].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics

def _metadata_item(
    item_id: str,
    *,
    metadata: dict[str, object],
    text: str = "Riley said Morgan confirmed the studio visit.",
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=text,
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={"retrieval_source": "keyword_chunks", "metadata": metadata},
    )


def _item(item_id: str, *, text: str, source_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=text,
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id=source_id),),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )


def _structured_source_item(
    item_id: str,
    *,
    source_id: str,
    diagnostics_key: str,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            diagnostics_key: {
                "source_id": source_id,
                "source_turn": {"dialogue_id": 12, "source_turn": 6},
            },
        },
    )
