from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server.memory_comparison_case_loader import (
    load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    LOCOMO_INGEST_RICH_DOCUMENTS,
)


def _longmemeval_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "question_id": "question-1",
        "question": "What did I save?",
        "answer": "the launch notes",
        "answer_session_ids": ["late-session"],
        "question_type": "single-session-user",
        "haystack_session_ids": ["late-session"],
        "haystack_dates": ["2023/05/03 (Wed) 09:00"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I saved the launch notes."},
                {"role": "assistant", "content": "I will remember that."},
            ]
        ],
    }
    row.update(overrides)
    return row


def _write_dataset(tmp_path: Path, payload: object, *, name: str = "dataset.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_longmemeval_sessions_are_chronological_and_pair_boundaries_are_preserved(
    tmp_path: Path,
) -> None:
    row = _longmemeval_row(
        question_id=None,
        haystack_session_ids=["late-session", "early-session", "undated-session"],
        haystack_dates=[
            "2023/05/03 (Wed) 09:00",
            "2023/05/01 (Mon) 09:00",
            "not-a-date",
        ],
        haystack_sessions=[
            [
                {"role": "user", "content": "late user", "has_answer": True},
                {"role": "assistant", "content": "late assistant", "has_answer": False},
            ],
            [
                {"role": "user", "content": "early user", "has_answer": False},
                {"role": "assistant", "content": "early assistant", "has_answer": False},
                {"role": "user", "content": "early odd trailing", "has_answer": True},
            ],
            [
                {"role": "user", "content": "undated user", "has_answer": False},
                {"role": "assistant", "content": "undated assistant", "has_answer": False},
            ],
        ],
    )
    path = _write_dataset(tmp_path, {"data": [row]})

    case = load_memory_comparison_cases(
        path,
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]

    assert len(case.case_id) == 16
    assert (
        case.case_id
        == load_memory_comparison_cases(
            path,
            locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
        )[0].case_id
    )
    assert case.memories == ()
    assert case.documents == ()
    assert [item.session_external_id for item in case.conversations] == [
        "early-session",
        "early-session",
        "late-session",
        "undated-session",
    ]
    assert [[message.content for message in item.messages] for item in case.conversations] == [
        ["early user", "early assistant"],
        ["early odd trailing"],
        ["late user", "late assistant"],
        ["undated user", "undated assistant"],
    ]
    assert all(message.metadata == {} for pair in case.conversations for message in pair.messages)
    assert "has_answer" not in str(case.conversations)
    assert "haystack_sessions" not in case.metadata


def test_longmemeval_case_identity_ignores_non_message_annotations(tmp_path: Path) -> None:
    base = _longmemeval_row(question_id=None)
    annotated = _longmemeval_row(
        question_id=None,
        haystack_sessions=[
            [
                {"role": "user", "content": "I saved the launch notes.", "has_answer": True},
                {
                    "role": "assistant",
                    "content": "I will remember that.",
                    "has_answer": False,
                },
            ]
        ],
    )
    base_case = load_memory_comparison_cases(
        _write_dataset(tmp_path, [base], name="base.json"),
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]
    annotated_case = load_memory_comparison_cases(
        _write_dataset(tmp_path, [annotated], name="annotated.json"),
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]

    assert annotated_case.case_id == base_case.case_id
    assert annotated_case.conversations == base_case.conversations


def test_longmemeval_invalid_messages_do_not_repair_across_original_pairs(
    tmp_path: Path,
) -> None:
    row = _longmemeval_row(
        haystack_sessions=[
            [
                {"role": "user", "content": "pair one valid"},
                {"role": "assistant", "content": "   "},
                {"role": "assistant", "content": "pair two first"},
                {"role": "user", "content": "pair two second"},
                {"role": "unsupported", "content": "ignored"},
                {"role": "assistant", "content": "pair three valid"},
                {"role": "user", "content": "odd trailing valid"},
            ]
        ]
    )
    case = load_memory_comparison_cases(
        _write_dataset(tmp_path, [row]),
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]

    assert [[message.content for message in pair.messages] for pair in case.conversations] == [
        ["pair one valid"],
        ["pair two first", "pair two second"],
        ["pair three valid"],
        ["odd trailing valid"],
    ]
    assert [pair.metadata["pair_index"] for pair in case.conversations] == [0, 1, 2, 3]


def test_longmemeval_keeps_every_pair_in_a_large_session(tmp_path: Path) -> None:
    messages = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"turn {index + 1}",
        }
        for index in range(132)
    ]
    case = load_memory_comparison_cases(
        _write_dataset(tmp_path, [_longmemeval_row(haystack_sessions=[messages])]),
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]

    assert len(case.conversations) == 66
    assert [message.content for message in case.conversations[0].messages] == [
        "turn 1",
        "turn 2",
    ]
    assert [message.content for message in case.conversations[-1].messages] == [
        "turn 131",
        "turn 132",
    ]
    assert len({pair.source_external_id for pair in case.conversations}) == 66


def test_generic_loader_preserves_normalized_and_locomo_modes(tmp_path: Path) -> None:
    generic_path = _write_dataset(
        tmp_path,
        [
            {
                "benchmark": "longmemeval",
                "case_id": "generic-1",
                "question": "Where are the notes?",
                "expected_terms": ["binder"],
                "memories": ["The notes are in the binder."],
            }
        ],
        name="generic.json",
    )
    generic_case = load_memory_comparison_cases(
        generic_path,
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]
    assert generic_case.case_id == "generic-1"
    assert generic_case.conversations == ()
    assert [memory.text for memory in generic_case.memories] == ["The notes are in the binder."]

    locomo = {
        "sample_id": "locomo-mini",
        "conversation": {
            "speaker_a": "Alice",
            "session_1": [
                {"speaker": "Alice", "dia_id": "D1:1", "text": "I chose tea."},
                {"speaker": "Bob", "dia_id": "D1:2", "text": "Tea sounds good."},
            ],
        },
        "qa": [
            {
                "question": "What did Alice choose?",
                "answer": "tea",
                "evidence": ["D1:1"],
                "category": 4,
            }
        ],
    }
    locomo_path = _write_dataset(tmp_path, {"items": [locomo]}, name="locomo.json")
    turn_case = load_memory_comparison_cases(
        locomo_path,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )[0]
    rich_case = load_memory_comparison_cases(
        locomo_path,
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )[0]

    assert [memory.metadata["role"] for memory in turn_case.memories] == [
        "user",
        "assistant",
    ]
    assert turn_case.conversations == ()
    assert rich_case.conversations == ()
    assert rich_case.documents
