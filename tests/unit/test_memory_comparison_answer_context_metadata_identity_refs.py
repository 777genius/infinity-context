from __future__ import annotations

import json

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_answer_context_qualifies_numeric_key_value_source_identity_text_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D12:6 Riley confirmed the studio visit.",
                rank=1,
                item_id="numeric-key-value-source-identity-text",
                source_refs=(
                    "provider-private session_id=12 source_turn_id=turn_6",
                ),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    )
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    ]
    serialized = json.dumps((context.memories[0].source_refs, diagnostics))
    assert "provider-private" not in serialized


def test_answer_context_reads_structured_source_identity_metadata_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D7:2 Riley confirmed the studio visit.",
                rank=1,
                item_id="structured-source-identity-metadata",
                metadata={
                    "source_identity_items": [
                        {
                            "source_identity_refs": [
                                "source_session_turn_refs:session-7:D7-2"
                            ],
                            "raw_payload": "locomo:conv-private:turn-secret",
                        }
                    ]
                },
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_7:D7:2",
        "source_turn_refs:D7:2",
    )
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_7:D7:2",
        "source_turn_refs:D7:2",
    ]
    serialized = json.dumps((context.memories[0].source_refs, diagnostics))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_answer_context_diagnostics_filters_raw_provider_item_ids() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="session_1 turn D1:2 raw note should not expose provider ids.",
                rank=1,
                item_id="locomo:conv-private:session_1:D1:2:turn-secret",
                source_refs=(
                    "locomo:conv-private:session_1:D1:2:turn-secret",
                ),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    )
    assert diagnostics["item_ids"] == []
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    ]
    assert "item_id" not in diagnostics["source_identity_items"][0]
    serialized = json.dumps(diagnostics)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
