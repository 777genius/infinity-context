from __future__ import annotations

import json

from test_memory_comparison_gold_blind import (
    _SECRET,
    _CapturingBackend,
    _case,
    _contract,
    _dispatch_retrieval,
)


def test_longmemeval_answer_session_aliases_remain_evaluator_only() -> None:
    case = _case(
        benchmark="longmemeval",
        metadata={
            "_evaluator_ground_truth": _SECRET,
            "answer_session_aliases": ["session-0001"],
            "question_type": "single-session-user",
        },
    )
    contract, _, ledger = _contract(case)
    backend = _CapturingBackend()

    _dispatch_retrieval(backend, contract, ledger)

    assert "answer_session_aliases" not in json.dumps(backend.requests[0], sort_keys=True)
    assert contract.retrieval_request.public_metadata == {"question_type": "single-session-user"}
