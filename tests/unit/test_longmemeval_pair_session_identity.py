from __future__ import annotations

from dataclasses import asdict

import pytest
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
)
from infinity_context_server.memory_comparison_longmemeval_cases import (
    official_longmemeval_pair_case,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError
from infinity_context_server.ranked_evidence_evaluator_helpers import (
    evaluator_only_payload,
)
from infinity_context_server.ranked_evidence_retrieval_request import (
    ranked_evidence_retrieval_request,
)
from infinity_context_server.ranked_evidence_seed_case import ranked_evidence_seed_case
from infinity_context_server.ranked_evidence_semantic_gate import (
    _exact_case_evidence_refs,
)

_RAW_IDS = (
    "answer-primary-upstream-secret",
    "distractor-upstream-secret",
    "answer-secondary-upstream-secret",
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "question_id": "longmemeval-neutral-identity",
        "question_type": "multi-session",
        "question": "How many clothing errands remain?",
        "answer": 3,
        "answer_session_ids": [_RAW_IDS[2], _RAW_IDS[0]],
        "haystack_session_ids": list(_RAW_IDS),
        "haystack_dates": ["2024-01-03", "2024-01-01", "2024-01-02"],
        "haystack_sessions": [
            [{"role": "user", "content": "Return the boots."}],
            [{"role": "assistant", "content": "Unrelated note."}],
            [{"role": "user", "content": "Pick up the blazer and shoes."}],
        ],
    }
    row.update(overrides)
    return row


def test_pair_loader_integrates_neutral_aliases_as_exact_gate_evidence() -> None:
    case = official_longmemeval_pair_case(_row())
    expected_aliases = ("session-0003", "session-0001")

    assert case.expected_terms == ("3",)
    assert case.metadata["answer_session_aliases"] == list(expected_aliases)
    assert case.metadata["evidence"] == list(expected_aliases)
    assert case.metadata["session_identity_schema"] == "longmemeval_neutral_ordinal_v1"
    assert "answer_session_ids" not in case.metadata
    assert _exact_case_evidence_refs(case) == expected_aliases
    assert evaluator_only_payload(case)["ground_truth"] == 3

    assert [conversation.session_external_id for conversation in case.conversations] == [
        "session-0002",
        "session-0003",
        "session-0001",
    ]
    source_ids = {
        ref["source_id"]
        for document in conversation_documents(case)
        for ref in document.source_refs
    }
    assert set(expected_aliases) <= source_ids


def test_pair_loader_keeps_raw_ids_and_gold_out_of_retrieval_boundaries() -> None:
    case = official_longmemeval_pair_case(_row(answer="evaluator-only-gold-answer"))
    request = ranked_evidence_retrieval_request(case)
    seed = ranked_evidence_seed_case(case)

    boundary_text = repr(request) + repr(seed)
    assert request.question == "How many clothing errands remain?"
    assert not hasattr(request, "expected_terms")
    assert not hasattr(request, "metadata")
    assert not hasattr(seed, "question")
    assert not hasattr(seed, "expected_terms")
    assert "evaluator-only-gold-answer" not in boundary_text
    assert all(raw_id not in boundary_text for raw_id in _RAW_IDS)
    assert all(
        raw_id not in repr(asdict(conversation))
        for raw_id in _RAW_IDS
        for conversation in case.conversations
    )


def test_pair_loader_allows_duplicate_non_answer_fillers() -> None:
    case = official_longmemeval_pair_case(
        _row(
            haystack_session_ids=["duplicate", "duplicate", "answer-unique"],
            answer_session_ids=["answer-unique"],
        )
    )

    assert {item.session_external_id for item in case.conversations} == {
        "session-0001",
        "session-0002",
        "session-0003",
    }
    assert case.metadata["evidence"] == ["session-0003"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"haystack_session_ids": None},
        {"haystack_session_ids": ["only-one"]},
        {
            "haystack_session_ids": ["duplicate", "duplicate", "third"],
            "answer_session_ids": ["duplicate"],
        },
        {"answer_session_ids": None},
        {"answer_session_ids": []},
        {"answer_session_ids": ["unknown-session"]},
        {"answer_session_ids": [_RAW_IDS[0], _RAW_IDS[0]]},
    ],
)
def test_pair_loader_fails_closed_on_invalid_session_identity(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(BenchmarkValidationError, match="session identity is invalid"):
        official_longmemeval_pair_case(_row(**overrides))
