from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    _load_memory_comparison_cases,
)


def test_memory_comparison_locomo_official_turns_accept_items_wrapped_session(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-items-wrapped-session.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "mini",
                    "conversation": {
                        "speaker_a": "Alice",
                        "speaker_b": "Bob",
                        "session_1": {
                            "date": "2023-01-01",
                            "items": [
                                {
                                    "dia_id": "D1",
                                    "speaker": "Alice",
                                    "text": "Alice bought green tea.",
                                },
                                "ignored non-turn value",
                                {
                                    "dia_id": "D2",
                                    "speaker": "Bob",
                                    "text": "Bob brought biscuits.",
                                },
                            ],
                        },
                    },
                    "qa": [
                        {
                            "question": "What did Alice buy?",
                            "answer": "green tea",
                            "evidence": ["D1"],
                            "category": 4,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_memory_comparison_cases(
        dataset,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )

    assert len(cases) == 1
