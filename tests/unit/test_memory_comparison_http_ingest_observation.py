from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_http_ingest_observation import (
    HttpIngestIdentityManifest,
    HttpIngestIdentityObservation,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

_FACT_HASH = "a" * 64
_DOCUMENT_HASH = "b" * 64
_MEM0_HASH_1 = "c" * 64
_MEM0_HASH_2 = "d" * 64


def test_locomo_infinity_ingest_preserves_exact_ordered_response_identities() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/facts":
            return httpx.Response(
                201,
                headers={"x-request-id": "infinity-fact-request-1"},
                json={
                    "data": {
                        "id": "fact-server-1",
                        "space_id": "space-server-1",
                        "memory_scope_id": "scope-server-1",
                        "thread_id": "thread-server-1",
                        "status": "active",
                        "version": 3,
                        "indexing_status": "indexed",
                        "source_refs": [
                            {
                                "source_id": "locomo-source-1",
                                "source_sha256": _FACT_HASH,
                            }
                        ],
                    }
                },
            )
        assert request.url.path == "/v1/documents"
        return httpx.Response(
            201,
            headers={"x-request-id": "infinity-document-request-1"},
            json={
                "data": {
                    "id": "document-server-1",
                    "space_id": "space-server-1",
                    "memory_scope_id": "scope-server-1",
                    "thread_id": "thread-server-1",
                    "status": "active",
                    "version": 1,
                    "indexing_status": "indexed",
                    "source_external_id": "locomo-source-1:raw-turn-document",
                    "content_hash": _DOCUMENT_HASH,
                    "chunks": 2,
                    "chunk_ids": ["chunk-server-1", "chunk-server-2"],
                }
            },
        )

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(_locomo_case(), run_id="run-1", corpus_key="corpus-1")
    finally:
        backend.close()

    assert seen_paths == ["/v1/facts", "/v1/documents"]
    assert result.operations[0].item_id == "locomo-source-1"
    assert result.operations[1].item_id == "locomo-source-1:raw-turn-document"
    manifest = result.metadata["ingest_identity_manifest"]
    assert manifest["complete"] is True
    assert manifest["canonical_record_ids"] == ["fact-server-1", "document-server-1"]
    assert manifest["fact_ids"] == ["fact-server-1"]
    assert manifest["document_ids"] == ["document-server-1"]
    assert manifest["chunk_ids"] == ["chunk-server-1", "chunk-server-2"]
    assert manifest["space_id"] == "space-server-1"
    assert manifest["memory_scope_id"] == "scope-server-1"
    assert manifest["thread_id"] == "thread-server-1"
    assert manifest["source_ids"] == [
        "locomo-source-1",
        "locomo-source-1:raw-turn-document",
    ]
    assert manifest["source_sha256"] == [_FACT_HASH, _DOCUMENT_HASH]
    assert [item["version"] for item in manifest["operations"]] == [3, 1]


def test_longmemeval_infinity_document_manifest_is_complete_and_exact() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/documents"
        return httpx.Response(
            201,
            headers={"x-request-id": "long-document-request"},
            json={
                "data": {
                    "id": "long-document-server",
                    "space_id": "space-server-2",
                    "memory_scope_id": "scope-server-2",
                    "thread_id": "thread-server-2",
                    "status": "active",
                    "indexing_status": "indexed",
                    "source_external_id": "long-source-1",
                    "content_hash": _DOCUMENT_HASH,
                    "chunks": 1,
                    "chunk_ids": ["long-chunk-server"],
                }
            },
        )

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _longmemeval_case(), run_id="run-2", corpus_key="corpus-2"
        )
    finally:
        backend.close()

    manifest = result.metadata["ingest_identity_manifest"]
    assert result.operations[0].metadata["ingest_identity_observation"]["version"] is None
    assert manifest == {
        "schema_version": "http_ingest_identity_manifest.v2",
        "complete": True,
        "operation_count": 1,
        "issues": [],
        "operations": [result.operations[0].metadata["ingest_identity_observation"]],
        "canonical_record_ids": ["long-document-server"],
        "fact_ids": [],
        "document_ids": ["long-document-server"],
        "chunk_ids": ["long-chunk-server"],
        "space_id": "space-server-2",
        "memory_scope_id": "scope-server-2",
        "thread_id": "thread-server-2",
        "observed_memory_ids": [],
        "created_memory_ids": [],
        "source_ids": ["long-source-1"],
        "source_sha256": [_DOCUMENT_HASH],
    }


def test_locomo_mem0_manifest_preserves_created_ids_events_sources_and_requests() -> None:
    responses = [
        {
            "request_id": "mem0-request-1",
            "results": [
                {
                    "id": "mem0-created-1",
                    "event": "ADD",
                    "metadata": {
                        "source_id": "locomo-source-1",
                        "source_sha256": _MEM0_HASH_1,
                    },
                }
            ],
        },
        {
            "request_id": "mem0-request-2",
            "results": [
                {
                    "id": "mem0-created-2",
                    "event": "ADD",
                    "metadata": {
                        "source_id": "locomo-source-2",
                        "source_sha256": _MEM0_HASH_2,
                    },
                }
            ],
        },
    ]
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        assert request.url.path == "/memories"
        payload = json.loads(request.content)
        assert payload["metadata"]["corpus_key"] == "corpus-1"
        response = httpx.Response(200, json=responses[call_count])
        call_count += 1
        return response

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _locomo_two_memory_case(), run_id="run-1", corpus_key="corpus-1"
        )
    finally:
        backend.close()

    assert call_count == 2
    manifest = result.metadata["ingest_identity_manifest"]
    assert manifest["complete"] is True
    assert manifest["observed_memory_ids"] == ["mem0-created-1", "mem0-created-2"]
    assert manifest["created_memory_ids"] == ["mem0-created-1", "mem0-created-2"]
    assert manifest["source_ids"] == ["locomo-source-1", "locomo-source-2"]
    assert manifest["source_sha256"] == [_MEM0_HASH_1, _MEM0_HASH_2]
    assert [item["request_id"] for item in manifest["operations"]] == [
        "mem0-request-1",
        "mem0-request-2",
    ]
    assert [item["events"] for item in manifest["operations"]] == [["ADD"], ["ADD"]]


def test_malformed_infinity_response_is_explicit_and_never_invents_ids() -> None:
    raw_secret = "sk-live-secret-material"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": " invalid-id ",
                    "status": "active",
                    "version": 0,
                    "indexing_status": "indexed",
                    "source_external_id": "long-source-1",
                    "content_hash": raw_secret,
                    "chunks": 2,
                    "chunk_ids": ["duplicate", "duplicate"],
                    "text": "evaluator gold must not escape",
                }
            },
        )

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _longmemeval_case(), run_id="run-2", corpus_key="corpus-2"
        )
    finally:
        backend.close()

    observation = result.operations[0].metadata["ingest_identity_observation"]
    manifest = result.metadata["ingest_identity_manifest"]
    assert observation["complete"] is False
    assert "canonical_record_id_missing_or_invalid" in observation["issues"]
    assert "version_missing_or_invalid" in observation["issues"]
    assert "source_sha256_missing_or_invalid" in observation["issues"]
    assert "chunk_id_duplicate" in observation["issues"]
    assert manifest["canonical_record_ids"] == []
    assert manifest["document_ids"] == []
    assert manifest["chunk_ids"] == ["duplicate", "duplicate"]
    assert raw_secret not in str(observation)
    assert "evaluator gold" not in str(observation)


def test_duplicate_mem0_ids_across_operations_make_manifest_policy_rejectable() -> None:
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "request_id": f"request-{call_count}",
                "results": [
                    {
                        "id": "same-created-id",
                        "event": "ADD",
                        "metadata": {
                            "source_id": f"source-{call_count}",
                            "source_sha256": _MEM0_HASH_1,
                        },
                    }
                ],
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _locomo_two_memory_case(), run_id="run-1", corpus_key="corpus-1"
        )
    finally:
        backend.close()

    manifest = result.metadata["ingest_identity_manifest"]
    assert manifest["complete"] is False
    assert manifest["created_memory_ids"] == ["same-created-id", "same-created-id"]
    assert "created_memory_id_duplicate" in manifest["issues"]


@pytest.mark.parametrize(
    ("event", "expected_created_ids", "expected_complete"),
    (
        ("ADD", ["mem0-event-id"], True),
        ("UPDATE", [], True),
        ("DELETE", [], True),
        ("UNKNOWN", [], False),
        (None, [], False),
    ),
)
def test_mem0_created_ids_are_exactly_add_events(
    event: str | None,
    expected_created_ids: list[str],
    expected_complete: bool,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "request_id": "request-event-1",
                "results": [
                    {
                        "id": "mem0-event-id",
                        "event": event,
                        "metadata": {
                            "source_id": "source-event-1",
                            "source_sha256": _MEM0_HASH_1,
                        },
                    }
                ],
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(_locomo_case(), run_id="run-1", corpus_key="corpus-1")
    finally:
        backend.close()

    observation = result.operations[0].metadata["ingest_identity_observation"]
    assert observation["observed_memory_ids"] == ["mem0-event-id"]
    assert observation["created_memory_ids"] == expected_created_ids
    assert observation["complete"] is expected_complete
    assert observation["events"] == ([event] if event in {"ADD", "UPDATE", "DELETE"} else [])
    if not expected_complete:
        assert "results[0].event_missing_or_invalid" in observation["issues"]


def test_reflected_secret_and_gold_like_mem0_fields_are_rejected_without_leak() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "request_id": "evaluator-gold",
                "results": [
                    {
                        "id": "sk-live-secret-material",
                        "event": "ADD",
                        "metadata": {
                            "source_id": "evaluator_gold",
                            "source_sha256": _MEM0_HASH_1,
                        },
                    }
                ],
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(_locomo_case(), run_id="run-1", corpus_key="corpus-1")
    finally:
        backend.close()

    observation = result.operations[0].metadata["ingest_identity_observation"]
    assert observation["complete"] is False
    assert observation["observed_memory_ids"] == []
    assert observation["created_memory_ids"] == []
    assert observation["source_ids"] == []
    assert observation["request_id"] is None
    rendered = str(observation)
    assert "sk-live-secret-material" not in rendered
    assert "evaluator-gold" not in rendered
    assert "evaluator_gold" not in rendered


def test_reflected_secret_and_gold_like_infinity_fields_are_rejected_without_leak() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"x-request-id": "sk-live-secret-material"},
            json={
                "data": {
                    "id": "evaluator_gold",
                    "status": "evaluator gold",
                    "version": 1,
                    "indexing_status": "sk-live-secret-material",
                    "source_external_id": "reference_answer",
                    "content_hash": _DOCUMENT_HASH,
                    "chunks": 1,
                    "chunk_ids": ["ground_truth"],
                }
            },
        )

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _longmemeval_case(), run_id="run-2", corpus_key="corpus-2"
        )
    finally:
        backend.close()

    observation = result.operations[0].metadata["ingest_identity_observation"]
    assert observation["complete"] is False
    assert observation["canonical_record_ids"] == []
    assert observation["document_ids"] == []
    assert observation["chunk_ids"] == []
    assert observation["source_ids"] == []
    assert observation["status"] is None
    assert observation["indexing_status"] is None
    assert observation["request_id"] is None
    rendered = str(observation)
    for reflected in (
        "sk-live-secret-material",
        "evaluator gold",
        "evaluator_gold",
        "reference_answer",
        "ground_truth",
    ):
        assert reflected not in rendered


def test_direct_observation_cannot_serialize_unsafe_reflected_identity() -> None:
    safe = HttpIngestIdentityObservation(
        backend="mem0",
        operation_type="messages",
        complete=True,
        issues=(),
        observed_memory_ids=("safe-memory-id",),
        created_memory_ids=("safe-memory-id",),
        source_ids=("safe-source-id",),
        source_sha256=(_MEM0_HASH_1,),
        request_id="safe-request-id",
        events=("ADD",),
    )

    with pytest.raises(ValueError, match="identity lane is invalid"):
        replace(safe, source_ids=("sk-live-secret-material",))
    with pytest.raises(ValueError, match="request ID is invalid"):
        replace(safe, request_id="evaluator_gold")


def test_failed_http_ingest_is_not_retried_and_observation_excludes_error_body() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            text="secret error payload with evaluator gold and expected answer",
            extensions={
                "reason_phrase": b"evaluator gold sk-live-secret-material",
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(_locomo_case(), run_id="run-1", corpus_key="corpus-1")
    finally:
        backend.close()

    assert calls == 1
    operation_metadata = result.operations[0].metadata
    observation = operation_metadata["ingest_identity_observation"]
    assert observation["complete"] is False
    assert "http_status_not_success" in observation["issues"]
    assert operation_metadata["reason_phrase"] == "Service Unavailable"
    assert operation_metadata["error_preview"] == "[redacted]"
    rendered = str(operation_metadata)
    assert "secret error payload" not in rendered
    assert "evaluator gold" not in rendered
    assert "expected answer" not in rendered
    assert "sk-live-secret-material" not in rendered


def test_ingest_observation_contract_types_are_frozen() -> None:
    assert HttpIngestIdentityObservation.__dataclass_params__.frozen is True
    assert HttpIngestIdentityManifest.__dataclass_params__.frozen is True


def _locomo_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="locomo-case-1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="The checklist is in the blue notebook.",
                source_external_id="locomo-source-1",
            ),
        ),
        memory_scope_external_ref="locomo-scope-1",
        thread_external_ref="locomo-thread-1",
    )


def _locomo_two_memory_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="locomo-case-1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="The checklist is in the blue notebook.",
                source_external_id="locomo-source-1",
            ),
            BenchmarkMemoryInput(
                text="Morgan confirmed the checklist location.",
                source_external_id="locomo-source-2",
            ),
        ),
        memory_scope_external_ref="locomo-scope-1",
        thread_external_ref="locomo-thread-1",
    )


def _longmemeval_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="long-case-1",
        question="Which notebook contains the checklist?",
        expected_terms=("blue",),
        documents=(
            BenchmarkDocumentInput(
                title="Checklist note",
                text="The checklist is in the blue notebook.",
                source_external_id="long-source-1",
            ),
        ),
        memory_scope_external_ref="long-scope-1",
        thread_external_ref="long-thread-1",
    )
