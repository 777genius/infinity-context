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


def test_source_refs_from_quality_payloads_qualify_locomo_evidence_ref_alias() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "session_key": "session_4",
        "locomo_evidence_ref": "D4:5",
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    assert bundle_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_quality_payloads_qualify_source_evidence_refs() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "session_key": "session_4",
        "source_evidence_refs": ["locomo:conv-private:D4:5"],
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    assert bundle_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_quality_payloads_qualify_supporting_evidence_refs() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "session_key": "session_4",
        "supporting_evidence": [
            {"source_evidence_ref": "locomo:conv-private:D4:5"}
        ],
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    assert bundle_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_quality_payloads_qualify_supporting_fact_refs() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "session_key": "session_4",
        "supporting_facts": [
            {"source_evidence_ref": "locomo:conv-private:D4:5"}
        ],
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    assert bundle_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_quality_payloads_qualify_nested_evidence_refs() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "session_key": "session_4",
        "evidence": [{"source_evidence_ref": "locomo:conv-private:D4:5"}],
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D4:5 Alex confirmed the workshop date.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    assert bundle_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_source_refs_from_quality_payloads_qualify_dialogue_index_aliases() -> None:
    payload = {
        "source_external_id": "locomo:conv-private:turn-secret",
        "source_dialogue_index": "D12",
        "source_turn_index": "6",
    }

    memory_refs = source_refs_from_memory(
        {
            "text": "D12:6 Riley confirmed the studio visit.",
            "metadata": {"source_ref_payloads": [payload]},
        }
    )
    bundle_refs = source_refs_from_bundle_item({"source_ref_payloads": [payload]})

    assert memory_refs == ("source_turn_refs:D12:6",)
    assert bundle_refs == ("source_turn_refs:D12:6",)
    serialized = json.dumps((memory_refs, bundle_refs))
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
