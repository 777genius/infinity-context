from __future__ import annotations

from dataclasses import dataclass

import pytest
from infinity_context_server.ranked_evidence_document_seed_contract import (
    document_seed_response_accepted,
    require_document_seed,
)


@dataclass(frozen=True)
class _Response:
    status_code: int
    payload: object
    text: str = ""

    def json(self) -> object:
        return self.payload


def _response(status_code: int, data: object) -> _Response:
    return _Response(status_code=status_code, payload={"data": data})


def test_fresh_document_creation_is_accepted() -> None:
    assert document_seed_response_accepted(_response(201, {"id": "doc-1"}))


def test_canonical_content_deduplication_is_accepted() -> None:
    assert document_seed_response_accepted(
        _response(
            200,
            {
                "id": "existing-doc",
                "indexing_status": "already_indexed_or_pending",
            },
        )
    )


def test_rejected_response_raises_the_callers_bounded_failure() -> None:
    failure = RuntimeError("document_seed_failed")

    with pytest.raises(RuntimeError, match="document_seed_failed") as captured:
        require_document_seed(_response(200, {"id": "doc-1"}), failure)

    assert captured.value is failure


@pytest.mark.parametrize(
    "response",
    [
        _response(200, {"id": "doc-1", "indexing_status": "pending"}),
        _response(200, {"indexing_status": "already_indexed_or_pending"}),
        _response(201, {"id": " "}),
        _response(204, {"id": "doc-1"}),
        _Response(status_code=201, payload=[]),
    ],
)
def test_malformed_or_ambiguous_success_response_is_rejected(response: _Response) -> None:
    assert not document_seed_response_accepted(response)
