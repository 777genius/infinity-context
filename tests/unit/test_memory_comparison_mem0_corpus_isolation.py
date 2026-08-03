from __future__ import annotations

import json
from collections import defaultdict

import httpx
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_corpus_user_id,
)
from infinity_context_server.memory_comparison_http import Mem0HttpComparisonBackend
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)


def _case(*, case_id: str, corpus: str, text: str) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id=case_id,
        question="Where is the item?",
        expected_terms=(),
        memories=(BenchmarkMemoryInput(text=text, source_external_id=f"{corpus}-source"),),
        memory_scope_external_ref=corpus,
        thread_external_ref=corpus,
    )


def test_mem0_search_isolated_per_corpus_and_rerun_cleans_exact_user_scope() -> None:
    run_id = "managed-isolation-run"
    alpha = _case(case_id="alpha:qa:1", corpus="corpus-alpha", text="alpha-only evidence")
    beta = _case(case_id="beta:qa:1", corpus="corpus-beta", text="beta-only evidence")
    stored: dict[str, list[str]] = defaultdict(list)
    deletes: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            user_id = str(request.url.params["user_id"])
            observed_run = str(request.url.params["run_id"])
            deletes.append((user_id, observed_run))
            stored.pop(user_id, None)
            return httpx.Response(204)
        payload = json.loads(request.content)
        if request.url.path == "/memories":
            user_id = str(payload["user_id"])
            stored[user_id].extend(str(item["content"]) for item in payload["messages"])
            return httpx.Response(200, json={"results": [{"id": "memory-1"}]})
        assert request.url.path == "/search"
        filters = payload["filters"]
        assert filters == {"user_id": filters["user_id"], "run_id": run_id}
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": f"memory-{index}", "memory": text}
                    for index, text in enumerate(stored[filters["user_id"]], start=1)
                ]
            },
        )

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        backend.reset(run_id=run_id)
        backend.ingest(alpha, run_id=run_id, corpus_key="corpus-alpha")
        backend.ingest(beta, run_id=run_id, corpus_key="corpus-beta")

        alpha_results = backend.search(alpha, run_id=run_id, top_k=10)
        beta_results = backend.search(beta, run_id=run_id, top_k=10)

        backend.reset(run_id=run_id)
        backend.ingest(alpha, run_id=run_id, corpus_key="corpus-alpha")
    finally:
        backend.close()

    alpha_user = mem0_benchmark_corpus_user_id(run_id, "corpus-alpha")
    beta_user = mem0_benchmark_corpus_user_id(run_id, "corpus-beta")
    assert alpha_user != beta_user
    assert [item.text for item in alpha_results.memories] == ["alpha-only evidence"]
    assert [item.text for item in beta_results.memories] == ["beta-only evidence"]
    assert all("beta-only evidence" not in item.text for item in alpha_results.memories)
    assert all("alpha-only evidence" not in item.text for item in beta_results.memories)
    assert deletes == [
        (alpha_user, run_id),
        (beta_user, run_id),
        (alpha_user, run_id),
        (beta_user, run_id),
    ]
    assert stored[alpha_user] == ["alpha-only evidence"]
    assert beta_user not in stored
