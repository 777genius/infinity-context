from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from infinity_context_server.memory_comparison_infinity_ingestion_contracts import (
    InfinityIngestionError,
)
from infinity_context_server.memory_comparison_infinity_ingestion_http import (
    InfinityEpisodeHttpAdapter,
)
from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionMessage,
    IngestionUnitMetadata,
    make_ingestion_unit,
    opaque_ingestion_corpus_id,
    opaque_ingestion_source_id,
)

RUN_ID = "run-sealed-infinity-r1"
MANIFEST = "a" * 64


def _unit(*, ordinal: int = 0, role: str = "user", text: str = "Exact user text"):
    corpus_id = opaque_ingestion_corpus_id(corpus_identity={"sample": "one"})
    source_id = opaque_ingestion_source_id(source_identity={"turn": ordinal})
    return make_ingestion_unit(
        ordinal=ordinal,
        corpus_id=corpus_id,
        message=IngestionMessage(role=role, content=text),
        metadata=IngestionUnitMetadata(source_id=source_id, timestamp=1_700_000_000 + ordinal),
    )


def _response(*, replay: bool = False, episode_id: str = "episode_1") -> dict[str, object]:
    return {
        "data": {
            "chunk_ids": ["chunk_1"],
            "created_suggestions": 0,
            "duplicate_chunks": 1 if replay else 0,
            "durability": "durable",
            "episode_id": episode_id,
            "memory_scope_id": "scope_1",
            "space_id": "space_1",
            "stored_chunks": 0 if replay else 1,
            "suggestion_ids": [],
            "thread_id": "thread_1",
        }
    }


def _adapter(handler) -> InfinityEpisodeHttpAdapter:
    return InfinityEpisodeHttpAdapter(
        origin="http://127.0.0.1:8080",
        service_token="test-only-token",
        transport=httpx.MockTransport(handler),
    )


def test_exact_payload_has_no_private_or_gold_data() -> None:
    observed: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:8080/v1/episodes"
        assert request.headers["authorization"] == "Bearer test-only-token"
        observed.append(json.loads(request.content))
        return httpx.Response(200, json=_response())

    unit = _unit(text="Question and gold must stay opaque")
    receipt = _adapter(handler).ingest(unit, run_id=RUN_ID, manifest_sha256=MANIFEST)
    payload = observed[0]
    assert payload == {
        "idempotency_key": unit.metadata.source_id,
        "kind_hint": "raw_transcript_chunk",
        "memory_scope_external_ref": unit.corpus_id,
        "occurred_at": "2023-11-14T22:13:20Z",
        "source_external_id": unit.metadata.source_id,
        "source_type": "transcript",
        "space_slug": "benchmark-" + hashlib.sha256(RUN_ID.encode()).hexdigest()[:32],
        "speaker": "user",
        "text": "Question and gold must stay opaque",
        "thread_external_ref": unit.corpus_id,
        "trust_level": "medium",
    }
    serialized_receipt = repr(receipt)
    assert "Question and gold" not in serialized_receipt
    for forbidden in ("question", "answer", "gold", "qa", "category", "metadata"):
        assert forbidden not in payload


def test_lost_response_then_idempotent_replay_returns_stable_ids() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        assert payload["idempotency_key"] == payload["source_external_id"]
        if calls == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(200, json=_response(replay=True))

    unit = _unit()
    with pytest.raises(InfinityIngestionError, match="transport failed"):
        _adapter(handler).ingest(unit, run_id=RUN_ID, manifest_sha256=MANIFEST)
    receipt = _adapter(handler).ingest(unit, run_id=RUN_ID, manifest_sha256=MANIFEST)
    assert calls == 2
    assert receipt.episode_id == "episode_1"
    assert receipt.chunk_ids == ("chunk_1",)


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:8080",
        "http://localhost:8080",
        "http://example.com:8080",
        "http://127.0.0.1:8080/",
        "http://user@127.0.0.1:8080",
        "http://127.0.0.1:8080?",
        "http://127.0.0.1:8080#",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:not-a-port",
        "http://[::1:8080",
    ],
)
def test_non_exact_loopback_origin_is_rejected(origin: str) -> None:
    with pytest.raises(InfinityIngestionError, match="loopback"):
        InfinityEpisodeHttpAdapter(origin=origin, service_token="secret")


def test_redirect_is_rejected_without_following() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(307, headers={"location": "http://127.0.0.1:8081/stolen"})

    with pytest.raises(InfinityIngestionError, match="redirects are forbidden"):
        _adapter(handler).ingest(_unit(), run_id=RUN_ID, manifest_sha256=MANIFEST)
    assert seen == ["http://127.0.0.1:8080/v1/episodes"]


def test_wrong_or_ambiguous_response_is_rejected() -> None:
    with pytest.raises(InfinityIngestionError, match="schema"):
        _adapter(lambda _: httpx.Response(200, json={"data": {"episode_id": "episode_1"}})).ingest(
            _unit(), run_id=RUN_ID, manifest_sha256=MANIFEST
        )
    with pytest.raises(InfinityIngestionError, match="ambiguous"):
        _adapter(
            lambda _: httpx.Response(
                200,
                json=_response()
                | {"data": _response()["data"] | {"stored_chunks": 1, "duplicate_chunks": 1}},
            )
        ).ingest(_unit(), run_id=RUN_ID, manifest_sha256=MANIFEST)


def test_suggestions_are_forbidden_on_sealed_ingestion_boundary() -> None:
    for created_suggestions, suggestion_ids in ((1, ["suggestion_1"]), (0, ["suggestion_1"])):
        payload = _response()
        payload["data"] = payload["data"] | {
            "created_suggestions": created_suggestions,
            "suggestion_ids": suggestion_ids,
        }
        with pytest.raises(InfinityIngestionError, match="forbidden suggestions"):
            _adapter(lambda _, value=payload: httpx.Response(200, json=value)).ingest(
                _unit(), run_id=RUN_ID, manifest_sha256=MANIFEST
            )


def test_inconsistent_or_malformed_chunk_inventory_is_rejected() -> None:
    for chunks, stored, error in (
        (["chunk_1", "chunk_1"], 2, "chunk_ids"),
        ([{"id": "chunk_1"}], 1, "chunk_ids"),
        (["chunk_1", "chunk_2"], 1, "chunk count"),
    ):
        payload = _response()
        payload["data"] = payload["data"] | {
            "chunk_ids": chunks,
            "stored_chunks": stored,
        }
        with pytest.raises(InfinityIngestionError, match=error):
            _adapter(lambda _, value=payload: httpx.Response(200, json=value)).ingest(
                _unit(), run_id=RUN_ID, manifest_sha256=MANIFEST
            )


def test_oversized_response_is_rejected_before_json_parsing() -> None:
    adapter = _adapter(
        lambda _: httpx.Response(
            200,
            headers={"content-length": "65537"},
            content=b"{}",
        )
    )
    with pytest.raises(InfinityIngestionError, match="byte limit"):
        adapter.ingest(_unit(), run_id=RUN_ID, manifest_sha256=MANIFEST)


def test_duplicate_conflict_is_not_interpreted_as_replay() -> None:
    adapter = _adapter(lambda _: httpx.Response(409, json={"detail": "idempotency conflict"}))
    with pytest.raises(InfinityIngestionError, match="returned 409"):
        adapter.ingest(_unit(), run_id=RUN_ID, manifest_sha256=MANIFEST)


def test_receipt_tamper_fails_closed() -> None:
    receipt = _adapter(lambda _: httpx.Response(200, json=_response())).ingest(
        _unit(), run_id=RUN_ID, manifest_sha256=MANIFEST
    )
    with pytest.raises(InfinityIngestionError, match="commitment"):
        replace(receipt, episode_id="episode_tampered")


def test_system_message_is_rejected_before_http() -> None:
    adapter = _adapter(lambda _: pytest.fail("HTTP must not run"))
    with pytest.raises(InfinityIngestionError, match="user/assistant"):
        adapter.ingest(_unit(role="system"), run_id=RUN_ID, manifest_sha256=MANIFEST)
