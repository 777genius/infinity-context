from __future__ import annotations

from infinity_context_server.memory_comparison_quality_selected_weakness import (
    selected_evidence_weakness_breakdown,
)


def test_selected_weakness_keeps_session_qualified_identity_ref_compact() -> None:
    breakdown = selected_evidence_weakness_breakdown(
        (
            {
                "case_id": "case-source-session-ref",
                "group": "multi-hop",
                "scored": True,
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "selected",
                            "role": "support",
                            "answerability_score": 0.4,
                            "source_refs": [
                                "source_session_turn_refs:session_2:D2:3",
                            ],
                        }
                    ]
                },
            },
        )
    )

    assert breakdown["samples"][0]["source_refs"] == [
        "source_session_turn_refs:session_2:D2:3",
    ]
    assert breakdown["samples"][0]["source_ref_count"] == 1


def test_selected_weakness_preserves_explicit_turn_ref_with_session_ref() -> None:
    breakdown = selected_evidence_weakness_breakdown(
        (
            {
                "case_id": "case-explicit-turn-ref",
                "group": "multi-hop",
                "scored": True,
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "selected",
                            "role": "support",
                            "answerability_score": 0.4,
                            "source_refs": [
                                "source_session_turn_refs:session_2:D2:3",
                                "source_turn_refs:D2:3",
                            ],
                        }
                    ]
                },
            },
        )
    )

    assert breakdown["samples"][0]["source_refs"] == [
        "source_session_turn_refs:session_2:D2:3",
        "source_turn_refs:D2:3",
    ]
    assert breakdown["samples"][0]["source_ref_count"] == 2
