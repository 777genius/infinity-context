from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_corpus_user_id,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_retrieval_policy import (
    INFINITY_TUNED_RETRIEVAL_POLICY,
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler.contracts import SchedulerBenchmark
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
    SchedulerRetrievalCaptureError,
    deterministic_retrieval_memories,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_http_adapters import (
    InfinityContextSchedulerRetrievalAdapter,
    Mem0SchedulerRetrievalAdapter,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerOfficialCaseKey,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _case_key() -> SchedulerOfficialCaseKey:
    return SchedulerOfficialCaseKey(
        suite_authority_sha256=_sha("suite"),
        run_authority_sha256=_sha("run"),
        run_binding_commitment_sha256=_sha("binding"),
        run_id="run-locomo",
        benchmark=SchedulerBenchmark.LOCOMO,
        scheduler_profile_id="scheduler-locomo",
        publishable_profile_id="publishable-priority-v4",
        publishable_profile_sha256=_sha("publishable-profile"),
        methodology_sha256=_sha("methodology"),
        dataset_sha256=_sha("dataset"),
        case_manifest_sha256=_sha("case-manifest"),
        case_index=7,
        case_id="locomo-case-0007",
        case_alias="locomo-alias-0007",
        authority_root_sha256=_sha("case-root"),
    )


def _request(
    *, backend_index: int, backend_role: str, target: str
) -> SchedulerBackendRetrievalRequest:
    return SchedulerBackendRetrievalRequest(
        case_key=_case_key(),
        case_material_sha256=_sha("case-material"),
        backend_index=backend_index,
        backend_role=backend_role,
        target_identity_sha256=target,
        question="Which database is current?",
        memory_scope_external_ref="scope-locomo-7",
        thread_external_ref="thread-locomo-7",
    )


def test_infinity_adapter_uses_one_neutral_exact_http_search_without_gold() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "item-1",
                            "text": "Postgres is current.",
                            "score": 0.9,
                            "source_refs": [{"source_id": "source-1"}],
                            "metadata": {},
                        },
                        {
                            "item_id": "item-2",
                            "text": "SQLite was previous.",
                            "score": 0.8,
                            "source_refs": [{"source_id": "source-2"}],
                            "metadata": {},
                        },
                    ]
                }
            },
        )

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://127.0.0.1:7788",
        auth_token="test-token",
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        mirror_memories_as_documents=False,
        transport=httpx.MockTransport(handler),
    )
    adapter = InfinityContextSchedulerRetrievalAdapter(backend)
    request = _request(
        backend_index=0,
        backend_role="infinity-context",
        target=adapter.target_identity_sha256,
    )
    result = adapter.retrieve_exact(request=request)
    assert result.is_bound_to(request)
    assert tuple(item.rank for item in result.memories) == (1, 2)
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/context/benchmark-search"
    payload = json.loads(requests[0].content)
    assert payload == {
        "max_chunks": 200,
        "max_evidence_items": 200,
        "max_facts": 200,
        "memory_scope_external_ref": "scope-locomo-7",
        "query": "Which database is current?",
        "space_slug": "memory-comparison-run-locomo",
        "thread_external_ref": "thread-locomo-7",
        "token_budget": 25_600,
    }
    wire = requests[0].content.decode()
    assert "expected_terms" not in wire
    assert "forbidden_terms" not in wire
    assert "evaluator_ground_truth" not in wire

    wrong_target = _request(
        backend_index=0,
        backend_role="infinity-context",
        target=_sha("wrong-target"),
    )
    with pytest.raises(SchedulerRetrievalCaptureError, match="request_invalid"):
        adapter.retrieve_exact(request=wrong_target)
    assert len(requests) == 1
    backend.close()


def test_infinity_adapter_rejects_benchmark_aware_reranking_client() -> None:
    backend = InfinityContextHttpComparisonBackend(
        base_url="http://127.0.0.1:7788",
        auth_token="test-token",
        retrieval_policy=INFINITY_TUNED_RETRIEVAL_POLICY,
        mirror_memories_as_documents=True,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    try:
        with pytest.raises(SchedulerRetrievalCaptureError, match="adapter_invalid"):
            InfinityContextSchedulerRetrievalAdapter(backend)
    finally:
        backend.close()


def test_mem0_adapter_reuses_exact_corpus_binding_and_cuts_200_to_50() -> None:
    searches: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and request.url.path == "/memories":
            return httpx.Response(204)
        if request.url.path == "/memories":
            return httpx.Response(200, json={"results": []})
        assert request.url.path == "/search"
        searches.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"mem-{index:03d}",
                        "memory": f"memory-{index:03d}",
                        "score": 1 / index,
                        "created_at": f"2024-01-{(index % 28) + 1:02d}T00:00:00Z",
                        "metadata": {"source_id": f"source-{index:03d}"},
                    }
                    for index in range(1, 56)
                ]
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://127.0.0.1:8888",
        transport=httpx.MockTransport(handler),
    )
    binding_case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="locomo-case-0007",
        question="unused during ingest",
        expected_terms=("private-gold",),
        memories=(
            BenchmarkMemoryInput(
                text="source memory",
                source_external_id="source-memory-7",
            ),
        ),
        memory_scope_external_ref="scope-locomo-7",
        thread_external_ref="thread-locomo-7",
        metadata={"_evaluator_ground_truth": "private-gold"},
    )
    ingest = backend.ingest(binding_case, run_id="run-locomo", corpus_key="corpus-7")
    assert ingest.items_failed == 0
    adapter = Mem0SchedulerRetrievalAdapter(backend)
    request = _request(
        backend_index=1,
        backend_role="mem0",
        target=adapter.target_identity_sha256,
    )
    result = adapter.retrieve_exact(request=request)
    assert result.is_bound_to(request)
    assert len(result.memories) == 50
    assert tuple(item.rank for item in result.memories) == tuple(range(1, 51))
    assert result.memories[-1].item_id == "mem-050"
    assert len(searches) == 1
    assert searches[0]["query"] == "Which database is current?"
    assert searches[0]["limit"] == SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
    assert searches[0]["top_k"] == SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
    assert searches[0]["filters"] == {
        "user_id": mem0_benchmark_corpus_user_id("run-locomo", "corpus-7"),
        "run_id": "run-locomo",
    }
    wire = json.dumps(searches[0], sort_keys=True)
    assert "private-gold" not in wire
    assert "expected_terms" not in wire
    backend.close()


def test_rank_policy_preserves_backend_rank_and_has_stable_tie_break() -> None:
    memories = (
        RetrievedMemory(text="b", rank=1, score=0.5, item_id="b", metadata={}),
        RetrievedMemory(text="a", rank=1, score=0.5, item_id="a", metadata={}),
        RetrievedMemory(text="z", rank=1, score=0.9, item_id="z", metadata={}),
        RetrievedMemory(text="first", rank=2, score=1.0, item_id="first", metadata={}),
    )
    ranked = deterministic_retrieval_memories(memories, cutoff=50)
    assert tuple(item.item_id for item in ranked) == ("z", "a", "b", "first")
    assert tuple(item.rank for item in ranked) == (1, 2, 3, 4)
    request = _request(
        backend_index=0,
        backend_role="infinity-context",
        target=_sha("target"),
    )
    result = SchedulerBackendRetrievalResult.bind(
        request=request,
        memories=memories,
    )
    assert result.memories == ranked
    for crosswired in (
        replace(result, query_identity_sha256=_sha("wrong-query")),
        replace(result, case_material_sha256=_sha("wrong-case")),
        replace(result, run_id="wrong-run"),
        replace(result, target_identity_sha256=_sha("wrong-target")),
    ):
        assert not crosswired.is_bound_to(request)
