from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    _load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult


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


def test_official_locomo_loader_preserves_exact_judge_only_ground_truth(
    tmp_path: Path,
) -> None:
    exact_gold = "G" * 300
    dataset = tmp_path / "locomo-exact-gold.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "exact-gold",
                    "conversation": {
                        "speaker_a": "Alice",
                        "session_1": [
                            {"dia_id": "D1:1", "speaker": "Alice", "text": "memory"}
                        ],
                    },
                    "qa": [
                        {
                            "question": "What happened?",
                            "answer": exact_gold,
                            "evidence": ["D1:1"],
                            "category": 4,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_memory_comparison_cases(
        dataset,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )[0]
    answer_prompt = render_mem0_official_answer_prompt(case, ()).user
    judge_prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="generated"),
    ).user

    assert case.metadata["_evaluator_ground_truth"] == exact_gold
    assert case.metadata["answer_preview"] != exact_gold
    assert exact_gold not in answer_prompt
    assert f"Gold answer: {exact_gold}\n" in judge_prompt
