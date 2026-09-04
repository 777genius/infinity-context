from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as core
import pytest
from infinity_context_server.api.v1 import context_retrieval
from infinity_context_server.api.v1.context_retrieval import _check_deadline, _compact_bytes
from infinity_context_server.features.context_building.retrieval_mappers import (
    retrieval_response_to_contract,
)

FORBIDDEN = {
    "text",
    "snippet",
    "rendered_context",
    "citation",
    "citations",
    "alias",
    "aliases",
    "metadata",
    "authorized",
    "authorization",
}


def test_wire_response_is_locator_only_at_every_depth() -> None:
    contribution = core.LocatorScoreContribution(
        "postgres_keyword", "q1", 1, 1_000_000, 1_000_000, 16_393_442_623, "relevance", 2.0
    )
    neighbor = core.LocatorNeighbor(
        "locator-2", "source", "document", "chunk-2", "chunk-2", 1, "active", "neighbor", 1
    )
    candidate = core.LocatorResultCandidate(
        locator="locator-1",
        source_key="source",
        document_key="document",
        chunk_key="chunk-1",
        canonical_identity="chunk-1",
        canonical_version=1,
        lifecycle_status="active",
        provider_rank=1,
        fused_score=0.016393442623,
        matched_query_ids=("q1",),
        contributions=(contribution,),
        base_score_picos=16_393_442_623,
        neighbors=(neighbor,),
    )
    response = core.LocatorRetrievalResponse(
        status="available",
        capability_fingerprint="f" * 64,
        profile_id="profile",
        applied_bounds=core.LocatorAppliedBounds(10, 1, 1, 16384, 2000, 1, 1),
        candidates=(candidate,),
        provider_outcomes=(core.LocatorProviderOutcome("postgres_keyword", "available"),),
    )
    payload = retrieval_response_to_contract(response).to_dict()
    _assert_forbidden_absent(payload)
    assert payload["candidates"][0]["preference_score_micros"] == 0
    assert payload["candidates"][0]["preference_boost_micros"] == 0
    assert payload["candidates"][0]["rerank_score_picos"] == 16_393_442_623
    assert set(payload) == {
        "contract_version",
        "ranking_policy",
        "status",
        "capability_fingerprint",
        "profile_id",
        "coverage",
        "applied_bounds",
        "candidates",
        "provider_outcomes",
        "degradation_reason_codes",
    }


def test_maximum_response_serialization_checks_deadline_after_encoding() -> None:
    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        body = {"padding": "x" * (1_048_576 - 20)}
        encoded = _compact_bytes(body)
        assert len(encoded) <= 1_048_576
        with pytest.raises(TimeoutError):
            _check_deadline(loop.time())

    asyncio.run(exercise())


def test_slow_incomplete_request_body_is_inside_server_deadline(monkeypatch) -> None:
    class SlowRequest:
        headers = {"content-type": "application/json"}

        async def stream(self):
            await asyncio.Event().wait()
            yield b""

    monkeypatch.setattr(context_retrieval, "MAX_DEADLINE_SECONDS", 0.01)
    response = asyncio.run(context_retrieval.retrieve_context(SlowRequest(), SimpleNamespace()))
    assert response.status_code == 504
    assert json.loads(response.body)["error"]["code"] == (
        "memory.context_retrieval_deadline_exceeded"
    )


def _assert_forbidden_absent(value: object) -> None:
    if isinstance(value, dict):
        assert FORBIDDEN.isdisjoint(value)
        for nested in value.values():
            _assert_forbidden_absent(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_forbidden_absent(nested)
