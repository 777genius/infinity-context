from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import infinity_context_server.memory_comparison_http as http_module
import pytest
from infinity_context_server import eval as eval_module
from infinity_context_server.memory_comparison_benchmark import (
    MEMORY_COMPARISON_MODE,
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
    assert token_cost["answerer"]["total_usd"] == expected_answerer_cost
    assert token_cost["judge"]["total_usd"] == expected_judge_cost
    assert token_cost["total_usd"] == round(
        expected_answerer_cost + expected_judge_cost,
        8,
    )


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
    assert result["evaluations"][1]["ingestion"]["reused"] is False


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
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "unit-token")
    monkeypatch.setattr(
        http_module,
        "InfinityContextHttpComparisonBackend",
        lambda **_: _ClosableBackend("memo-stack", closed),
    )
    monkeypatch.setattr(
        http_module,
        "Mem0HttpComparisonBackend",
        lambda **_: _ClosableBackend("mem0", closed),
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

    capsys.readouterr()
    assert closed == ["memo-stack", "mem0"]


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
