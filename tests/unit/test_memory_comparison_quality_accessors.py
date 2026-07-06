from __future__ import annotations

import json

from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_bundle_item,
    source_refs_from_memory,
)


def test_source_refs_from_memory_reads_official_turn_metadata_payloads() -> None:
    refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {
                "source_ref_payloads": [
                    {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "dia_id": "D4:5",
                    }
                ]
            },
        }
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps(refs)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_bundle_item_reads_official_turn_metadata_payloads() -> None:
    refs = source_refs_from_bundle_item(
        {
            "role": "primary",
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "dia_id": "D4:5",
                }
            ],
        }
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps(refs)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_memory_qualifies_numeric_session_turn_payloads() -> None:
    refs = source_refs_from_memory(
        {
            "text": "D12:6 Riley confirmed the studio visit.",
            "metadata": {
                "source_ref_payloads": [
                    {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_12",
                        "turn_id": "6",
                    }
                ]
            },
        }
    )

    assert refs == (
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    )
