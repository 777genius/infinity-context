from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import infinity_context_server.memory_comparison_http as http_module
import pytest
from infinity_context_server import eval as eval_module
from infinity_context_server.memory_comparison_benchmark import (
    MEMORY_COMPARISON_MODE,
    _backend_comparison,
    run_memory_comparison_benchmark,
)
from infinity_context_server.memory_comparison_llm import (
    EvidenceOnlyAnswerer,
    ExpectedTermsJudge,
    OpenAIResponsesAnswerer,
    OpenAIResponsesJudge,
)
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    BackendSearchResult,
    RetrievedMemory,
    TokenCostRate,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)


class _StaticBackend:
    def __init__(
        self,
        name: str,
        memories_by_case: dict[str, tuple[RetrievedMemory, ...]],
    ) -> None:
        self.name = name
        self.memories_by_case = memories_by_case
        self.reset_calls: list[str] = []
        self.ingest_calls: dict[str, int] = defaultdict(int)
        self.search_calls: dict[str, int] = defaultdict(int)

    def reset(self, *, run_id: str) -> None:
        self.reset_calls.append(run_id)

    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        self.ingest_calls[corpus_key] += 1
        return BackendIngestResult(
            items_processed=len(case.documents),
            total_memories_created=len(case.documents),
            latency_ms=3.0,
            metadata={"run_id": run_id, "corpus_key": corpus_key},
        )

    def search(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        top_k: int,
    ) -> BackendSearchResult:
        self.search_calls[case.case_id] += 1
        memories = self.memories_by_case.get(case.case_id, ())
        return BackendSearchResult(
            query=case.question,
            memories=memories[:top_k],
            latency_ms=7.0,
            total_results=len(memories),
            context_token_count=42,
            metadata={"run_id": run_id},
        )


def test_memory_comparison_benchmark_reports_side_by_side_metrics(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Where did Morgan keep the launch checklist?",
        expected_terms=("blue notebook",),
        answer="Morgan kept it in the blue notebook.",
    )
    memo_backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Morgan kept the launch checklist in the blue notebook.",
                    rank=1,
                    score=0.91,
                    item_id="memo-hit",
                ),
            )
        },
    )
    mem0_backend = _StaticBackend(
        "mem0",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Morgan discussed the launch checklist.",
                    rank=1,
                    score=0.52,
                    item_id="mem0-partial",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(memo_backend, mem0_backend),
        answerer=EvidenceOnlyAnswerer(),
        judge=ExpectedTermsJudge(),
        top_k=2,
        top_k_cutoffs=(1, 2),
        run_id="unit-run",
        cases_override=(case,),
        answerer_token_cost_rate=TokenCostRate(
            input_usd_per_1m=2.0,
            output_usd_per_1m=8.0,
        ),
        judge_token_cost_rate=TokenCostRate(
            input_usd_per_1m=3.0,
            output_usd_per_1m=9.0,
        ),
    )

    assert result["evaluation_mode"] == MEMORY_COMPARISON_MODE
    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert result["backend_metrics"]["mem0"]["accuracy"] == 0.0
    assert result["backend_comparison"]["memo_stack_vs_mem0_accuracy_delta"] == 1.0
    assert (
        result["backend_comparison"]["memo_stack_vs_mem0_expected_term_recall_delta"]
        == 1.0
    )
    assert result["backend_comparison"]["memo_stack_vs_mem0_avg_retrieved_count_delta"] == 0.0
    assert result["backend_comparison"]["memo_stack_vs_mem0_latency_delta_ms"] == {
        "ingest": 0.0,
        "search": 0.0,
        "generation": 0.0,
        "judge": 0.0,
    }
    assert result["backend_metrics"]["memo-stack"]["expected_term_recall"] == 1.0
    assert result["backend_metrics"]["mem0"]["expected_term_recall"] == 0.0
    assert result["backend_metrics"]["memo-stack"]["by_group"]["single-hop"]["total"] == 1
    assert result["backend_metrics"]["memo-stack"]["by_category"]["4:single-hop"]["total"] == 1
    assert result["evaluations"][0]["category"] == "4:single-hop"
    assert result["failure_analysis"][0]["backend"] == "mem0"
    assert result["evaluations"][0]["cutoff_results"]["1"]["judgment"]["score"] == 1.0
    token_usage = result["backend_metrics"]["memo-stack"]["token_usage"]["by_stage"]
    token_cost = result["backend_metrics"]["memo-stack"]["token_cost"]
    expected_answerer_cost = round(
        (
            token_usage["answerer"]["prompt_tokens"] * 2.0
            + token_usage["answerer"]["completion_tokens"] * 8.0
        )
        / 1_000_000,
        8,
    )
    expected_judge_cost = round(
        (
            token_usage["judge"]["prompt_tokens"] * 3.0
            + token_usage["judge"]["completion_tokens"] * 9.0
        )
        / 1_000_000,
        8,
    )
    assert token_cost["configured"] is True
    assert token_cost["scope"] == "answerer_judge_only"
    assert token_cost["unmeasured_backend_provider_costs"] is True
    assert token_cost["answerer"]["total_usd"] == expected_answerer_cost
    assert token_cost["judge"]["total_usd"] == expected_judge_cost
    assert token_cost["total_usd"] == round(
        expected_answerer_cost + expected_judge_cost,
        8,
    )
    assert (
        result["backend_comparison"]["memo_stack_vs_mem0_token_cost_total_usd_delta"]
        == round(
            result["backend_metrics"]["memo-stack"]["token_cost"]["total_usd"]
            - result["backend_metrics"]["mem0"]["token_cost"]["total_usd"],
            8,
        )
    )
    assert result["metadata"]["token_cost_scope"] == "answerer_judge_only"
    assert "backend_internal_ingest_provider_cost" in result["metadata"]["unmeasured_costs"]


def test_memory_comparison_backend_comparison_tolerates_malformed_metric_values() -> None:
    comparison = _backend_comparison(
        {
            "memo-stack": {
                "accuracy": "not-a-number",
                "expected_term_recall": True,
                "avg_retrieved_count": "2.5",
                "avg_context_tokens": None,
                "avg_ingest_latency_ms": "bad",
                "avg_search_latency_ms": 12,
                "avg_generation_latency_ms": 4,
                "avg_judge_latency_ms": 2,
                "token_cost": {"total_usd": "bad"},
            },
            "mem0": {
                "accuracy": 0.25,
                "expected_term_recall": 0.1,
                "avg_retrieved_count": 1,
                "avg_context_tokens": 9,
                "avg_ingest_latency_ms": 3,
                "avg_search_latency_ms": 10,
                "avg_generation_latency_ms": 4,
                "avg_judge_latency_ms": 5,
                "token_cost": {"total_usd": 0.125},
            },
        }
    )

    assert comparison["ranked_by_accuracy"] == ["mem0", "memo-stack"]
    assert comparison["memo_stack_vs_mem0_accuracy_delta"] == -0.25
    assert comparison["memo_stack_vs_mem0_expected_term_recall_delta"] == -0.1
    assert comparison["memo_stack_vs_mem0_avg_retrieved_count_delta"] == 1.5
    assert comparison["memo_stack_vs_mem0_avg_context_tokens_delta"] == -9.0
    assert comparison["memo_stack_vs_mem0_latency_delta_ms"] == {
        "ingest": -3.0,
        "search": 2.0,
        "generation": 0.0,
        "judge": -3.0,
    }
    assert comparison["memo_stack_vs_mem0_token_cost_total_usd_delta"] == -0.125


def test_memory_comparison_benchmark_reuses_ingested_corpus(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    shared_document_text = (
        "Morgan said the checklist is in the blue notebook, and Morgan owns it."
    )
    first = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
        document_text=shared_document_text,
    )
    second = _case(
        case_id="conv-1:qa:2",
        question="Who owns the checklist?",
        expected_terms=("Morgan",),
        answer="Morgan",
        document_text=shared_document_text,
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            first.case_id: (RetrievedMemory(text="blue notebook", rank=1),),
            second.case_id: (RetrievedMemory(text="Morgan owns it", rank=1),),
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(first, second),
    )

    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert sum(backend.ingest_calls.values()) == 1
    assert result["evaluations"][1]["ingestion"]["reused"] is True


def test_memory_comparison_benchmark_reports_category_five_as_unscored(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    scored = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
        category=4,
    )
    unscored = _case(
        case_id="conv-1:qa:adversarial",
        question="What color was never mentioned?",
        expected_terms=("purple binder",),
        answer="purple binder",
        category=5,
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            scored.case_id: (RetrievedMemory(text="blue notebook", rank=1),),
            unscored.case_id: (RetrievedMemory(text="purple binder", rank=1),),
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(scored, unscored),
    )

    metrics = result["backend_metrics"]["memo-stack"]
    assert metrics["total"] == 1
    assert metrics["unscored"] == 1
    assert metrics["by_category"]["4:single-hop"]["total"] == 1
    assert metrics["by_category"]["5:adversarial"]["total"] == 1
    assert metrics["by_category"]["5:adversarial"]["scored"] == 0
    assert metrics["by_category"]["5:adversarial"]["unscored"] == 1
    assert metrics["by_category"]["5:adversarial"]["passed"] == 0
    assert metrics["by_category"]["5:adversarial"]["accuracy"] == 0.0
    assert result["evaluations"][1]["scored"] is False
    assert result["evaluations"][1]["category"] == "5:adversarial"


def test_memory_comparison_benchmark_does_not_reuse_changed_corpus(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    first = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    second = _case(
        case_id="conv-1:qa:2",
        question="Where is the checklist now?",
        expected_terms=("red folder",),
        answer="red folder",
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            first.case_id: (RetrievedMemory(text="blue notebook", rank=1),),
            second.case_id: (RetrievedMemory(text="red folder", rank=1),),
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(first, second),
    )

    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert sum(backend.ingest_calls.values()) == 2
    assert result["evaluations"][1]["ingestion"]["reused"] is False


def test_memory_comparison_benchmark_does_not_cache_failed_ingest(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    first = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    second = _case(
        case_id="conv-1:qa:2",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    backend = _FailingFirstIngestBackend(
        "memo-stack",
        {
            first.case_id: (RetrievedMemory(text="blue notebook", rank=1),),
            second.case_id: (RetrievedMemory(text="blue notebook", rank=1),),
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(first, second),
    )

    assert sum(backend.ingest_calls.values()) == 2
    assert result["evaluations"][0]["ingestion"]["items_failed"] == 1
    assert result["evaluations"][0]["judgment"]["verdict"] == "error"
    assert result["evaluations"][0]["judgment"]["reason"] == "ingest_failed"
    assert result["evaluations"][0]["retrieval"]["total_results"] == 0
    assert result["evaluations"][1]["ingestion"]["reused"] is False
    assert backend.search_calls[first.case_id] == 0
    assert backend.search_calls[second.case_id] == 1


def test_memory_comparison_benchmark_rejects_duplicate_backend_names(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )

    with pytest.raises(BenchmarkValidationError, match="must be unique"):
        run_memory_comparison_benchmark(
            dataset_path=dataset,
            backends=(
                _StaticBackend("memo-stack", {}),
                _StaticBackend("memo-stack", {}),
            ),
            cases_override=(case,),
        )


def test_memory_comparison_benchmark_records_search_failures(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    good_backend = _StaticBackend(
        "memo-stack",
        {case.case_id: (RetrievedMemory(text="blue notebook", rank=1),)},
    )
    failing_backend = _SearchFailingBackend("mem0", {})

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(good_backend, failing_backend),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(case,),
    )

    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert result["backend_metrics"]["mem0"]["accuracy"] == 0.0
    assert result["backend_metrics"]["mem0"]["by_cutoff"]["1"] == {
        "primary": True,
        "total": 1,
        "passed": 0,
        "failed": 1,
        "accuracy": 0.0,
        "avg_score": 0.0,
    }
    assert result["failure_analysis"][0]["backend"] == "mem0"
    assert result["failure_analysis"][0]["reason"] == "search_failed"
    assert result["evaluations"][1]["judgment"]["verdict"] == "error"


def test_memory_comparison_benchmark_records_reset_failures_without_stopping_others(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    good_backend = _StaticBackend(
        "memo-stack",
        {case.case_id: (RetrievedMemory(text="blue notebook", rank=1),)},
    )
    failing_backend = _ResetFailingBackend("mem0", {})

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(good_backend, failing_backend),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="unit-run",
        cases_override=(case,),
    )

    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert result["backend_metrics"]["mem0"]["accuracy"] == 0.0
    assert result["failure_analysis"][0]["backend"] == "mem0"
    assert result["failure_analysis"][0]["reason"] == "reset_failed"
    assert result["evaluations"][1]["judgment"]["verdict"] == "error"
    assert sum(failing_backend.ingest_calls.values()) == 0


def test_memory_comparison_cli_is_manual_live_gated(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        eval_module.main(
            [
                "memory-comparison-benchmark",
                "--dataset",
                str(dataset),
                "--memo-api-url",
                "http://memo.example",
                "--mem0-url",
                "http://mem0.example",
            ]
        )

    assert "--allow-live" in str(exc_info.value)


def test_memory_comparison_cli_paid_llm_is_separately_gated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "unit-token")

    with pytest.raises(SystemExit) as exc_info:
        eval_module.main(
            [
                "memory-comparison-benchmark",
                "--dataset",
                str(dataset),
                "--memo-api-url",
                "http://memo.example",
                "--mem0-url",
                "http://mem0.example",
                "--allow-live",
                "--answerer-provider",
                "openai",
                "--answerer-model",
                "unit-answerer",
            ]
        )

    assert "--allow-paid-llm" in str(exc_info.value)


def test_memory_comparison_cli_closes_live_backend_clients(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    closed: list[str] = []
    mem0_backend_kwargs: list[dict[str, object]] = []
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "unit-token")
    monkeypatch.setenv("MEM0_API_KEY", "mem0-unit-key")
    monkeypatch.setattr(
        http_module,
        "InfinityContextHttpComparisonBackend",
        lambda **_: _ClosableBackend("memo-stack", closed),
    )

    def fake_mem0_backend(**kwargs: object) -> _ClosableBackend:
        mem0_backend_kwargs.append(dict(kwargs))
        return _ClosableBackend("mem0", closed)

    monkeypatch.setattr(
        http_module,
        "Mem0HttpComparisonBackend",
        fake_mem0_backend,
    )

    def fake_run_memory_comparison_benchmark(**kwargs: object) -> dict[str, object]:
        backends = kwargs["backends"]
        assert tuple(backend.name for backend in backends) == ("memo-stack", "mem0")
        assert kwargs["capabilities"] == ("single-hop", "temporal")
        assert kwargs["answerer_token_cost_rate"] == TokenCostRate(
            input_usd_per_1m=2.5,
            output_usd_per_1m=10.0,
        )
        assert kwargs["judge_token_cost_rate"] == TokenCostRate(
            input_usd_per_1m=3.5,
            output_usd_per_1m=12.0,
        )
        return {
            "suite": "memory-comparison-benchmark",
            "ok": True,
            "status": "ok",
            "metrics": {},
            "failures": [],
        }

    monkeypatch.setattr(
        eval_module,
        "run_memory_comparison_benchmark",
        fake_run_memory_comparison_benchmark,
    )

    eval_module.main(
        [
            "memory-comparison-benchmark",
            "--dataset",
            str(dataset),
            "--memo-api-url",
            "http://memo.example",
            "--mem0-url",
            "http://mem0.example",
            "--allow-live",
            "--capability",
            "single-hop",
            "--capability",
            "temporal",
            "--answerer-input-usd-per-1m",
            "2.5",
            "--answerer-output-usd-per-1m",
            "10",
            "--judge-input-usd-per-1m",
            "3.5",
            "--judge-output-usd-per-1m",
            "12",
        ]
    )

    captured = capsys.readouterr()
    assert closed == ["memo-stack", "mem0"]
    assert mem0_backend_kwargs == [
        {"base_url": "http://mem0.example", "api_key": "mem0-unit-key"}
    ]
    assert "mem0-unit-key" not in captured.out
    assert "mem0-unit-key" not in captured.err


def test_infinity_context_http_ingest_uses_isolated_state_and_redacts_errors() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        if request.url.path == "/v1/facts":
            return httpx.Response(503, text=f"upstream leaked Bearer {raw_secret}")
        return httpx.Response(201, json={"data": {"id": "doc-1"}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case_with_memory_and_document()

    try:
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert result.items_processed == 2
    assert result.items_failed == 1
    failed_metadata = result.operations[0].metadata
    assert failed_metadata["status_code"] == 503
    assert raw_secret not in str(failed_metadata["error_preview"])
    assert "[redacted]" in str(failed_metadata["error_preview"])
    assert {payload["space_slug"] for payload in seen_payloads} == {
        "memory-comparison-run-42"
    }
    assert {payload["memory_scope_external_ref"] for payload in seen_payloads} == {
        "locomo-conv-1"
    }
    assert {payload["thread_external_ref"] for payload in seen_payloads} == {
        "locomo-conv-1"
    }


def test_infinity_context_http_ingest_bounds_source_ids_for_public_api() -> None:
    raw_fact_id = "fact-" + ("x" * 220)
    raw_document_id = "document-" + ("y" * 300)
    seen_requests: list[tuple[dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(201, json={"data": {"id": "created"}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="Morgan kept the checklist in the blue notebook.",
                source_external_id=raw_fact_id,
            ),
        ),
        documents=(
            BenchmarkDocumentInput(
                title="Conversation",
                text="Morgan repeated that the checklist is in the blue notebook.",
                source_external_id=raw_document_id,
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
    )

    try:
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    fact_headers, fact_payload = seen_requests[0]
    document_headers, document_payload = seen_requests[1]
    fact_source_id = fact_payload["source_refs"][0]["source_id"]
    document_source_id = document_payload["source_external_id"]

    assert result.items_failed == 0
    assert len(str(fact_source_id)) == 160
    assert raw_fact_id not in str(fact_source_id)
    assert fact_headers["idempotency-key"] == fact_source_id
    assert len(str(document_source_id)) == 240
    assert raw_document_id not in str(document_source_id)
    assert document_headers["idempotency-key"] == document_source_id


def test_mem0_http_ingest_uses_run_isolated_user_and_redacts_errors() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    seen_requests: list[tuple[str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            seen_requests.append((str(request.url), None))
            return httpx.Response(204)
        payload = json.loads(request.content)
        seen_requests.append((str(request.url), payload))
        return httpx.Response(502, text=f"provider token={raw_secret} failed")

    backend = http_module.Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )

    try:
        backend.reset(run_id="Run 42")
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert "user_id=memo-stack-comparison-run-42" in seen_requests[0][0]
    assert "run_id=Run+42" in seen_requests[0][0]
    assert result.items_processed == 1
    assert result.items_failed == 1
    failed_metadata = result.operations[0].metadata
    assert failed_metadata["status_code"] == 502
    assert raw_secret not in str(failed_metadata["error_preview"])
    assert "[redacted]" in str(failed_metadata["error_preview"])
    posted_payload = seen_requests[1][1]
    assert posted_payload is not None
    assert posted_payload["user_id"] == "memo-stack-comparison-run-42"
    assert posted_payload["run_id"] == "Run 42"
    assert posted_payload["metadata"] == {
        "benchmark": "locomo",
        "case_id": "conv-1:qa:1",
        "corpus_key": "corpus-a",
    }


def test_mem0_http_search_uses_current_filters_and_top_k_payload() -> None:
    seen_payloads: list[dict[str, object]] = []
    seen_api_keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        seen_api_keys.append(request.headers.get("X-API-Key"))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "memory-1",
                        "memory": "The checklist is in the blue notebook.",
                        "score": 0.82,
                        "created_at": "2026-01-15T10:30:00Z",
                    }
                ]
            },
        )

    backend = http_module.Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        api_key="mem0-unit-key",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=7)
    finally:
        backend.close()

    assert seen_payloads == [
        {
            "query": "Where is the checklist?",
            "filters": {
                "user_id": "memo-stack-comparison-run-42",
                "run_id": "Run 42",
            },
            "top_k": 7,
        }
    ]
    assert seen_api_keys == ["mem0-unit-key"]
    assert result.total_results == 1
    assert result.memories[0].text == "The checklist is in the blue notebook."


def test_openai_responses_llm_adapters_parse_fake_client() -> None:
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    memories = (RetrievedMemory(text="The checklist is in the blue notebook.", rank=1),)
    fake_client = _FakeOpenAIClient(
        (
            SimpleNamespace(
                output_text="It is in the blue notebook.",
                usage=SimpleNamespace(input_tokens=11, output_tokens=7),
            ),
            SimpleNamespace(
                output_text='{"verdict":"correct","score":1,"reason":"Supported."}',
                usage=SimpleNamespace(input_tokens=13, output_tokens=5),
            ),
        )
    )
    answerer = OpenAIResponsesAnswerer(
        api_key="",
        model="unit-answerer",
        client_factory=lambda: fake_client,
    )
    judge = OpenAIResponsesJudge(
        api_key="",
        model="unit-judge",
        client_factory=lambda: fake_client,
    )

    answer = answerer.answer(case, memories, backend_name="memo-stack", cutoff=1)
    judgment = judge.judge(
        case,
        answer,
        memories,
        backend_name="memo-stack",
        cutoff=1,
    )

    assert answer.answer == "It is in the blue notebook."
    assert answer.token_usage.total_tokens == 18
    assert judgment.verdict == "correct"
    assert judgment.score == 1.0
    assert fake_client.responses.calls[0]["store"] is False
    assert fake_client.responses.calls[1]["text"]["format"]["type"] == "json_schema"


def _case(
    *,
    case_id: str,
    question: str,
    expected_terms: tuple[str, ...],
    answer: str,
    document_text: str | None = None,
    category: int = 4,
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        documents=(
            BenchmarkDocumentInput(
                title="Conversation",
                text=document_text or f"Morgan said: {answer}",
                source_external_id="conv-1-doc",
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": category, "answer_preview": answer},
    )


def _case_with_memory_and_document() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="Morgan kept the checklist in the blue notebook.",
                source_external_id="memory-1",
            ),
        ),
        documents=(
            BenchmarkDocumentInput(
                title="Conversation",
                text="Morgan repeated that the checklist is in the blue notebook.",
                source_external_id="document-1",
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4},
    )


class _FakeResponses:
    def __init__(self, responses: tuple[object, ...]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return self._responses.pop(0)


class _FakeOpenAIClient:
    def __init__(self, responses: tuple[object, ...]) -> None:
        self.responses = _FakeResponses(responses)


class _ClosableBackend:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self._closed = closed

    def close(self) -> None:
        self._closed.append(self.name)


class _FailingFirstIngestBackend(_StaticBackend):
    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        result = super().ingest(case, run_id=run_id, corpus_key=corpus_key)
        if sum(self.ingest_calls.values()) == 1:
            return BackendIngestResult(
                items_processed=result.items_processed,
                items_failed=1,
                total_memories_created=0,
                latency_ms=result.latency_ms,
                metadata=result.metadata,
            )
        return result


class _SearchFailingBackend(_StaticBackend):
    def search(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        top_k: int,
    ) -> BackendSearchResult:
        del case, top_k
        raise RuntimeError(f"search failed for token {run_id}")


class _ResetFailingBackend(_StaticBackend):
    def reset(self, *, run_id: str) -> None:
        raise RuntimeError(f"reset failed for token {run_id}")
