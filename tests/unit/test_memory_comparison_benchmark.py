from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import infinity_context_server.memory_comparison_http as http_module
import infinity_context_server.memory_comparison_rerank as rerank_module
import pytest
from infinity_context_server import eval as eval_module
from infinity_context_server.memory_comparison_benchmark import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    MEMORY_COMPARISON_MODE,
    _backend_comparison,
    _load_memory_comparison_cases,
    run_memory_comparison_benchmark,
    run_memory_comparison_replay,
)
from infinity_context_server.memory_comparison_llm import (
    CodexCliAnswerer,
    CodexCliJudge,
    EvidenceOnlyAnswerer,
    ExpectedTermsJudge,
    OpenAIResponsesAnswerer,
    OpenAIResponsesJudge,
    render_answer_prompt,
)
from infinity_context_server.memory_comparison_models import (
    AnswerResult,
    BackendIngestResult,
    BackendSearchResult,
    IngestionOperation,
    JudgeResult,
    RetrievedMemory,
    TokenCostRate,
)
from infinity_context_server.memory_comparison_query_integrity import (
    query_integrity_diagnostics,
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


class _TimestampingBackend(_StaticBackend):
    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        self.ingest_calls[corpus_key] += 1
        return BackendIngestResult(
            items_processed=1,
            latency_ms=3.0,
            operations=(
                IngestionOperation(
                    step=1,
                    operation_type="fact",
                    success=True,
                    metadata={
                        "run_id": run_id,
                        "source_timestamp": 1683546960,
                        "session_date": "11:56 am on 8 May, 2023",
                    },
                ),
            ),
        )


class _FixedLatencyAnswerer:
    model = "deterministic"

    def __init__(self, latency_ms: float = 5.0) -> None:
        self._delegate = EvidenceOnlyAnswerer()
        self._latency_ms = latency_ms

    def answer(
        self,
        case: PublicBenchmarkCase,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> AnswerResult:
        return replace(
            self._delegate.answer(
                case,
                memories,
                backend_name=backend_name,
                cutoff=cutoff,
            ),
            latency_ms=self._latency_ms,
        )


class _RecordingAnswerer:
    model = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, ...]] = []

    def answer(
        self,
        case: PublicBenchmarkCase,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> AnswerResult:
        del case, backend_name, cutoff
        self.calls.append(tuple(memory.item_id for memory in memories))
        return AnswerResult(answer="\n".join(memory.text for memory in memories))


class _FixedLatencyJudge:
    model = "deterministic"

    def __init__(self, latency_ms: float = 2.0) -> None:
        self._delegate = ExpectedTermsJudge()
        self._latency_ms = latency_ms

    def judge(
        self,
        case: PublicBenchmarkCase,
        answer: AnswerResult,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> JudgeResult:
        return replace(
            self._delegate.judge(
                case,
                answer,
                memories,
                backend_name=backend_name,
                cutoff=cutoff,
            ),
            latency_ms=self._latency_ms,
        )


def test_render_answer_prompt_labels_planned_evidence_context() -> None:
    case = _case(
        case_id="conv-1:qa:prompt",
        question="What note did Morgan move?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    prompt = render_answer_prompt(
        case,
        (
            RetrievedMemory(
                text="D1:1 Morgan moved the blue notebook.",
                rank=4,
                item_id="focused",
                source_refs=("D1:1",),
                metadata={
                    "answer_context_role": "primary",
                    "answer_context_retrieval_order": 4,
                    "answer_context_answerability_score": 0.91,
                    "answer_context_source_locality_score": 1.0,
                    "answer_context_query_roles": ("location_support",),
                    "answer_context_relation_category_hits": (
                        "location_transition",
                    ),
                    "answer_context_entity_hits": ("caroline",),
                    "answer_context_speaker_hits": ("caroline",),
                    "answer_context_bundle_confidence_score": 0.68,
                    "answer_context_bundle_confidence_band": "medium",
                    "answer_context_bundle_bridge_count": 1,
                    "answer_context_bundle_source_proximity_support_count": 1,
                    "answer_context_bundle_source_proximity_closest_distance": 2,
                    "answer_context_bundle_causal_support_count": 1,
                    "answer_context_bundle_event_support_count": 7,
                    "answer_context_bundle_inference_support_count": 2,
                    "answer_context_bundle_location_support_count": 5,
                    "answer_context_bundle_symbolic_meaning_support_count": 6,
                    "answer_context_bundle_preference_support_count": 3,
                    "answer_context_bundle_visual_support_count": 4,
                    "answer_context_bundle_contrast_count": 2,
                    "answer_context_role_requirement_complete": False,
                    "answer_context_missing_required_roles": ("contrast",),
                    "answer_context_bundle_risk_reason_codes": (
                        "risk:missing_required_role",
                        "risk:missing_required_contrast",
                    ),
                    "answer_context_reason_codes": (
                        "role:primary",
                        "query_support",
                    ),
                    "answer_context_backfill_missing_role_hits": ("contrast",),
                },
            ),
        ),
        cutoff=10,
    )

    assert "Planned evidence context, cutoff 10:" in prompt
    assert "role=primary" in prompt
    assert "rank=4" in prompt
    assert "retrieval_order=4" in prompt
    assert "answerability=0.91" in prompt
    assert "locality=1" in prompt
    assert "query_roles=location_support" in prompt
    assert "relations=location_transition" in prompt
    assert "entities=caroline" in prompt
    assert "speakers=caroline" in prompt
    assert "bundle=medium:0.68" in prompt
    assert "bundle_proximity=1" in prompt
    assert "bundle_proximity_closest=2" in prompt
    assert (
        "bundle_support=bridge:1,causal:1,event:7,inference:2,location:5,"
        "symbolic_meaning:6,preference:3,visual:4,contrast:2"
        in prompt
    )
    assert "missing_roles=contrast" in prompt
    assert "backfill_roles=contrast" in prompt
    assert "role_complete=false" in prompt
    assert "reasons=role:primary,query_support" in prompt
    assert (
        "risks=risk:missing_required_role,risk:missing_required_contrast"
        in prompt
    )
    assert "refs=D1:1" in prompt


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
        answerer=_FixedLatencyAnswerer(),
        judge=_FixedLatencyJudge(),
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
    assert result["backend_metrics"]["memo-stack"]["by_cutoff"]["2"][
        "avg_memories_evaluated"
    ] == 1.0
    assert (
        result["backend_metrics"]["memo-stack"]["top_k_gate"][
            "fake_top_k_suspected"
        ]
        is True
    )
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


def test_memory_comparison_locomo_fast_case_set_selects_ten_per_group(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    cases = tuple(
        _case(
            case_id=f"conv-{category}:qa:{index}",
            question=f"Question {category}-{index}?",
            expected_terms=(f"answer-{category}-{index}",),
            answer=f"answer-{category}-{index}",
            category=category,
        )
        for category in (1, 2, 3, 4)
        for index in range(12)
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text=f"The answer is {case.expected_terms[0]}.",
                    rank=1,
                    score=0.9,
                    item_id=case.case_id,
                ),
            )
            for case in cases
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=cases,
        case_set="locomo-fast",
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="fast-unit",
    )

    assert result["metrics"]["case_count"] == 40
    assert result["metrics"]["scored_evaluation_count"] == 40
    assert result["backend_metrics"]["memo-stack"]["passed"] == 40
    assert result["metadata"]["case_set"] == "locomo-fast"
    assert result["metadata"]["case_set_selection"]["selected_by_group"] == {
        "multi-hop": 10,
        "open-domain": 10,
        "single-hop": 10,
        "temporal": 10,
    }


def test_memory_comparison_benchmark_reports_source_mix_gate(
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
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Morgan kept the checklist in the blue notebook.",
                    rank=1,
                    metadata={
                        "diagnostics": {"retrieval_sources": ["postgres_facts"]}
                    },
                ),
                RetrievedMemory(
                    text="Raw turn: the checklist is in the blue notebook.",
                    rank=2,
                    metadata={
                        "diagnostics": {"retrieval_sources": ["keyword_chunks"]}
                    },
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(1, 2),
        run_id="source-mix-unit",
    )

    gate = result["backend_metrics"]["memo-stack"]["source_mix_gate"]
    assert gate["source_mix_ok"] is True
    assert gate["only_postgres_facts"] is False
    assert gate["retrieval_source_counts"] == {
        "keyword_chunks": 1,
        "postgres_facts": 1,
    }


def test_memory_comparison_benchmark_reports_temporal_metadata_gate(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="When did Morgan mention the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
        category=2,
    )
    backend = _TimestampingBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="On 8 May 2023, the checklist was in the blue notebook.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="temporal-metadata-unit",
    )

    gate = result["backend_metrics"]["memo-stack"]["temporal_metadata_gate"]
    assert gate["temporal_metadata_ok"] is True
    assert gate["timestamped_ingestion_operations"] == 1
    assert gate["session_dated_ingestion_operations"] == 1


def test_memory_comparison_benchmark_reports_benchmark_rerank_gate(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )

    class _RerankBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            return BackendSearchResult(
                query=case.question,
                memories=(
                    RetrievedMemory(
                        text="Caroline was researching adoption agencies.",
                        rank=1,
                    ),
                ),
                total_results=1,
                metadata={
                    "query_expansion": {
                        "applied": True,
                        "uses_ground_truth": False,
                    },
                    "benchmark_rerank": {
                        "applied": True,
                        "boosted_memory_count": 1,
                        "max_boost": 0.18,
                        "uses_ground_truth": False,
                    },
                    "multi_query_merge": {
                        "raw_result_count": 3,
                        "unique_result_count": 2,
                        "multi_query_hit_count": 1,
                    },
                },
            )

    backend = _RerankBackend("memo-stack", {})

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="benchmark-rerank-unit",
    )

    gate = result["backend_metrics"]["memo-stack"]["benchmark_rerank_gate"]
    assert gate["benchmark_rerank_ok"] is True
    assert gate["query_expansion_applied_count"] == 1
    assert gate["multi_query_raw_result_count"] == 3
    assert gate["multi_query_unique_result_count"] == 2
    assert gate["multi_query_hit_count"] == 1
    assert gate["applied_count"] == 1
    assert gate["boosted_memory_count"] == 1
    assert gate["max_boost"] == 0.18
    assert gate["uses_ground_truth"] is False


def test_memory_comparison_benchmark_reports_query_integrity_overlap(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )
    high_overlap_case = _case(
        case_id="conv-1:qa:2",
        question="What did Caroline mention?",
        expected_terms=("love", "faith", "strength"),
        answer="love, faith, and strength",
    )

    class _QueryIntegrityBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            memories = self.memories_by_case.get(case.case_id, ())
            added_query = (
                "caroline mention love faith strength"
                if case.case_id == high_overlap_case.case_id
                else "caroline research adoption agencies"
            )
            query_profile = (
                {
                    "relation_terms": ["mention"],
                    "relation_variant_terms": ["talk"],
                }
                if case.case_id == high_overlap_case.case_id
                else {
                    "relation_terms": ["research"],
                    "relation_variant_terms": ["lookup"],
                }
            )
            rerank_profile = (
                {
                    "relation_terms": ["mention"],
                    "relation_variant_terms": ["love", "faith", "strength"],
                }
                if case.case_id == high_overlap_case.case_id
                else {
                    "relation_terms": ["research"],
                    "relation_variant_terms": ["lookup"],
                }
            )
            return BackendSearchResult(
                query=case.question,
                memories=memories[:top_k],
                metadata={
                    "query_decomposition": {
                        "queries": [
                            case.question,
                            added_query,
                        ],
                        "query_profile": query_profile,
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["single_fact"],
                            "risk_flags": [],
                        },
                    },
                    "benchmark_rerank": {
                        "query_profile": rerank_profile,
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["single_fact"],
                            "risk_flags": [],
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _QueryIntegrityBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline was researching adoption agencies.",
                    rank=1,
                ),
            )
        },
    )
    backend.memories_by_case[high_overlap_case.case_id] = (
        RetrievedMemory(
            text="Caroline said the necklace symbolized love, faith, and strength.",
            rank=1,
        ),
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case, high_overlap_case),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["diagnostic_only"] is True
    assert integrity["affects_retrieval"] is False
    assert integrity["query_count"] == 2
    assert integrity["expected_answer_query_overlap_count"] == 2
    assert integrity["expected_answer_query_overlap_terms"] == ["adoption", "agencies"]
    assert integrity["expected_answer_query_profile_overlap_count"] == 0
    assert integrity["expected_answer_query_profile_overlap_terms"] == []
    assert integrity["expected_answer_original_question_overlap_count"] == 0
    assert integrity["retrieval_intent_schema_versions"] == ["retrieval_intent.v1"]
    assert integrity["retrieval_intent_evidence_need"] == ["single_fact"]
    assert integrity["retrieval_intent_risk_flags"] == []
    high_overlap_integrity = result["evaluations"][1]["retrieval"]["metadata"][
        "query_integrity"
    ]
    assert high_overlap_integrity["expected_answer_query_profile_overlap_count"] == 3
    assert high_overlap_integrity["expected_answer_query_profile_overlap_terms"] == [
        "faith",
        "love",
        "strength",
    ]
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["diagnostic_only"] is True
    assert gate["affects_retrieval"] is False
    assert gate["overlap_case_count"] == 2
    assert gate["max_overlap_count"] == 3
    assert gate["profile_overlap_case_count"] == 1
    assert gate["profile_overlap_token_total"] == 3
    assert gate["max_profile_overlap_count"] == 3
    assert gate["query_integrity_clean"] is False
    assert gate["profile_query_integrity_clean"] is False
    assert gate["sample_overlap_case_ids"] == ["conv-1:qa:2", "conv-1:qa:1"]
    assert gate["sample_profile_overlap_case_ids"] == ["conv-1:qa:2"]
    assert gate["overlap_token_total"] == 5
    assert gate["sample_overlap_cases"] == [
        {
            "case_id": "conv-1:qa:2",
            "overlap_count": 3,
            "overlap_terms": ["faith", "love", "strength"],
        },
        {
            "case_id": "conv-1:qa:1",
            "overlap_count": 2,
            "overlap_terms": ["adoption", "agencies"],
        }
    ]
    assert gate["sample_profile_overlap_cases"] == [
        {
            "case_id": "conv-1:qa:2",
            "overlap_count": 3,
            "overlap_terms": ["faith", "love", "strength"],
        }
    ]


def test_query_integrity_checks_locomo_answer_preview_tokens(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="What does Caroline's necklace symbolize?",
        expected_terms=("D4:1",),
        answer="love, faith, and strength",
    )

    class _AnswerPreviewLeakBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            return BackendSearchResult(
                query=case.question,
                memories=self.memories_by_case.get(case.case_id, ())[:top_k],
                metadata={
                    "query_decomposition": {
                        "queries": [
                            case.question,
                            "caroline necklace love faith",
                        ],
                        "query_profile": {
                            "relation_terms": ["necklace"],
                            "relation_variant_terms": ["strength"],
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _AnswerPreviewLeakBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline described what the necklace meant.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-answer-preview-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["expected_answer_query_overlap_terms"] == ["faith", "love"]
    assert integrity["expected_answer_query_profile_overlap_terms"] == ["strength"]
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["overlap_token_total"] == 2
    assert gate["profile_overlap_token_total"] == 1
    assert gate["query_integrity_clean"] is False


def test_query_integrity_checks_typed_retrieval_intent_tokens(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:typed-intent-leak",
        question="What did Caroline mention?",
        expected_terms=("love", "faith"),
        answer="love and faith",
    )

    class _TypedIntentLeakBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            return BackendSearchResult(
                query=case.question,
                memories=self.memories_by_case.get(case.case_id, ())[:top_k],
                metadata={
                    "query_decomposition": {
                        "queries": [case.question],
                        "query_profile": {"relation_terms": ["mention"]},
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["single_fact"],
                            "risk_flags": [],
                            "relations": {
                                "terms": ["mention"],
                                "intents": [
                                    {
                                        "category": "symbolic_meaning",
                                        "terms": ["mention"],
                                        "variant_terms": ["love", "faith"],
                                    }
                                ],
                            },
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _TypedIntentLeakBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline mentioned love and faith.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-typed-intent-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["expected_answer_query_overlap_count"] == 0
    assert integrity["expected_answer_query_profile_overlap_count"] == 0
    assert integrity["expected_answer_retrieval_intent_overlap_count"] == 2
    assert integrity["expected_answer_retrieval_intent_overlap_terms"] == [
        "faith",
        "love",
    ]
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["query_integrity_clean"] is False
    assert gate["profile_query_integrity_clean"] is True
    assert gate["retrieval_intent_query_integrity_clean"] is False
    assert gate["retrieval_intent_overlap_case_count"] == 1
    assert gate["retrieval_intent_overlap_token_total"] == 2
    assert gate["sample_retrieval_intent_overlap_case_ids"] == [
        "conv-1:qa:typed-intent-leak"
    ]


def test_query_integrity_checks_selected_query_plan_text(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:query-plan-leak",
        question="What did Caroline mention?",
        expected_terms=("love", "faith"),
        answer="love and faith",
    )

    class _QueryPlanLeakBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            return BackendSearchResult(
                query=case.question,
                memories=self.memories_by_case.get(case.case_id, ())[:top_k],
                metadata={
                    "query_decomposition": {
                        "query_profile": {"relation_terms": ["mention"]},
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["single_fact"],
                            "risk_flags": [],
                        },
                        "query_plan": {
                            "schema_version": "query_plan.v2",
                            "selected": [
                                {
                                    "role": "relation_compact",
                                    "query": "caroline mention love faith",
                                }
                            ],
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _QueryPlanLeakBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline mentioned love and faith.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-plan-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["query_count"] == 2
    assert integrity["expected_answer_query_overlap_count"] == 2
    assert integrity["expected_answer_query_overlap_terms"] == ["faith", "love"]
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["query_integrity_clean"] is False
    assert gate["overlap_token_total"] == 2
    assert gate["sample_overlap_case_ids"] == ["conv-1:qa:query-plan-leak"]


def test_query_integrity_checks_query_expansion_typed_intent(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:query-expansion-intent-leak",
        question="What did Caroline mention?",
        expected_terms=("love", "faith"),
        answer="love and faith",
    )

    class _QueryExpansionIntentLeakBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            return BackendSearchResult(
                query=case.question,
                memories=self.memories_by_case.get(case.case_id, ())[:top_k],
                metadata={
                    "query_expansion": {
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["single_fact"],
                            "bundle_evidence_roles": ["primary"],
                            "risk_flags": ["wide_relation_expansion"],
                            "relations": {
                                "terms": ["mention"],
                                "variant_terms": ["love", "faith"],
                                "intents": [
                                    {
                                        "category": "symbolic_meaning",
                                        "terms": ["mention"],
                                        "variant_terms": ["love", "faith"],
                                    }
                                ],
                            },
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _QueryExpansionIntentLeakBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline mentioned love and faith.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-expansion-intent-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["expected_answer_query_overlap_count"] == 0
    assert integrity["expected_answer_retrieval_intent_overlap_count"] == 2
    assert integrity["expected_answer_retrieval_intent_overlap_terms"] == [
        "faith",
        "love",
    ]
    assert integrity["retrieval_intent_schema_versions"] == ["retrieval_intent.v1"]
    assert integrity["retrieval_intent_evidence_need"] == ["single_fact"]
    assert integrity["retrieval_intent_bundle_evidence_roles"] == ["primary"]
    assert integrity["retrieval_intent_risk_flags"] == ["wide_relation_expansion"]
    assert integrity["retrieval_intent_relation_categories"] == [
        "symbolic_meaning"
    ]
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["query_integrity_clean"] is False
    assert gate["retrieval_intent_query_integrity_clean"] is False
    assert gate["retrieval_intent_overlap_token_total"] == 2
    assert gate["sample_retrieval_intent_overlap_case_ids"] == [
        "conv-1:qa:query-expansion-intent-leak"
    ]


def test_query_integrity_ignores_structural_bundle_roles_for_profile_leakage(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Which role labels did Caroline mention?",
        expected_terms=("primary", "bridge", "contrast", "temporal support"),
        answer="primary, bridge, contrast, and temporal support",
    )

    class _StructuralRoleBackend(_StaticBackend):
        def search(
            self,
            case: PublicBenchmarkCase,
            *,
            run_id: str,
            top_k: int,
        ) -> BackendSearchResult:
            self.search_calls[case.case_id] += 1
            bundle_roles = ["primary", "bridge", "contrast", "temporal_support"]
            return BackendSearchResult(
                query=case.question,
                memories=self.memories_by_case.get(case.case_id, ())[:top_k],
                metadata={
                    "query_decomposition": {
                        "queries": [case.question],
                        "query_profile": {
                            "evidence_need": ["multi_hop", "contrast"],
                            "bundle_evidence_roles": bundle_roles,
                            "risk_flags": ["broad_query"],
                        },
                        "retrieval_intent": {
                            "schema_version": "retrieval_intent.v1",
                            "evidence_need": ["multi_hop", "contrast"],
                            "bundle_evidence_roles": bundle_roles,
                            "risk_flags": ["broad_query"],
                        },
                    },
                    "run_id": run_id,
                },
            )

    backend = _StructuralRoleBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Caroline mentioned labels used by the retrieval pipeline.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="query-integrity-structural-roles-unit",
    )

    integrity = result["evaluations"][0]["retrieval"]["metadata"]["query_integrity"]
    assert integrity["retrieval_intent_bundle_evidence_roles"] == [
        "primary",
        "bridge",
        "contrast",
        "temporal_support",
    ]
    assert integrity["expected_answer_query_overlap_terms"] == []
    assert integrity["expected_answer_query_profile_overlap_terms"] == []
    gate = result["backend_metrics"]["memo-stack"]["query_integrity_gate"]
    assert gate["query_integrity_clean"] is True
    assert gate["profile_query_integrity_clean"] is True


def test_memory_comparison_benchmark_aggregates_evidence_recall(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Which notes connect the checklist and studio desk?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1", "D2:3"),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:1 Morgan put the checklist in the blue notebook.",
                    rank=1,
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="evidence-recall-unit",
    )

    metrics = result["backend_metrics"]["memo-stack"]
    assert metrics["evidence_term_recall"] == 0.5
    assert metrics["evidence_term_recall_evaluation_count"] == 1
    assert metrics["by_group"]["multi-hop"]["evidence_term_recall"] == 0.5


def test_memory_comparison_benchmark_builds_multi_hop_evidence_bundle(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Which notes connect Morgan's checklist and the studio desk?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1", "D2:3"),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:1 Morgan put the checklist in the blue notebook.",
                    rank=1,
                    item_id="memory-d1",
                ),
                RetrievedMemory(
                    text="D2:3 The studio desk had the same blue notebook.",
                    rank=2,
                    item_id="memory-d2",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="multi-hop-bundle-unit",
    )

    bundle = result["evaluations"][0]["evidence_bundle"]
    assert bundle["kind"] == "multi_hop_evidence_bundle"
    assert bundle["item_count"] == 2
    assert bundle["supporting_evidence_count"] == 1
    assert bundle["covered_evidence_terms"] == ["D1:1", "D2:3"]
    assert bundle["query_support_term_count"] > 0
    assert bundle["query_support_term_recall"] > 0
    assert "morgan" in bundle["query_support_terms"]
    assert bundle["items"][0]["query_support_terms"]
    assert bundle["bundle_complete"] is True
    gate = result["backend_metrics"]["memo-stack"]["multi_hop_bundle_gate"]
    assert gate["bundle_complete_count"] == 1
    assert gate["avg_bundle_query_support_term_recall"] > 0
    assert gate["multi_hop_bundle_ok"] is True
    ref_gate = result["backend_metrics"]["memo-stack"]["evidence_ref_rank_gate"]
    assert ref_gate["evaluation_count"] == 1
    assert ref_gate["all_refs_top1_count"] == 0
    assert ref_gate["all_refs_top2_count"] == 1
    assert ref_gate["all_refs_top5_ok"] is True
    assert ref_gate["focused_refs_top5_count"] == 1
    quality_diagnostics = result["backend_metrics"]["memo-stack"][
        "quality_diagnostics"
    ]
    assert quality_diagnostics["schema_version"] == "quality_diagnostics.v2"
    assert quality_diagnostics["per_intent"]["need:unknown"]["total"] == 1
    fast_gate = result["backend_metrics"]["memo-stack"]["fast_gate"]
    assert fast_gate["schema_version"] == "fast_gate.v1"
    assert fast_gate["ready_for_full_locomo"] is False
    assert "case_count" in fast_gate["failed_gates"]


def test_memory_comparison_benchmark_answers_from_planned_evidence_context(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:answer-context",
        question="What note did Morgan move?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4, "answer_preview": "blue notebook"},
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:0 Morgan discussed something unrelated.",
                    rank=1,
                    item_id="noise",
                ),
                RetrievedMemory(
                    text="D1:1 Morgan moved the blue notebook.",
                    rank=2,
                    item_id="focused",
                ),
                RetrievedMemory(
                    text="D1:2 A desk was mentioned later.",
                    rank=3,
                    item_id="distractor",
                ),
            )
        },
    )
    answerer = _RecordingAnswerer()

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        answerer=answerer,
        top_k=3,
        top_k_cutoffs=(3,),
        run_id="answer-context-unit",
    )

    cutoff = result["evaluations"][0]["cutoff_results"]["3"]
    answer_context_metrics = result["backend_metrics"]["memo-stack"][
        "answer_context_metrics"
    ]

    assert answerer.calls == [("focused",)]
    assert cutoff["memories_evaluated"] == 3
    assert cutoff["answer_context"]["source"] == "evidence_bundle"
    assert cutoff["answer_context"]["memory_count"] == 1
    assert cutoff["answer_context"]["item_ids"] == ["focused"]
    assert "blue notebook" in cutoff["generation"]["answer"]
    assert "unrelated" not in cutoff["generation"]["answer"]
    assert answer_context_metrics["primary_evidence_bundle_context_rate"] == 1.0
    assert answer_context_metrics["primary_avg_context_memory_count"] == 1.0
    assert answer_context_metrics["primary_avg_context_compression_ratio"] == 0.3333
    assert answer_context_metrics["by_cutoff"]["3"]["source_counts"] == {
        "evidence_bundle": 1
    }
    assert result["evaluations"][0]["judgment"]["score"] == 1.0


def test_memory_comparison_evidence_bundle_uses_source_refs_for_evidence_terms(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Which notes connect Morgan's checklist and the studio desk?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1", "D2:3"),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Morgan put the checklist in the blue notebook.",
                    rank=1,
                    item_id="memory-d1",
                    source_refs=("locomo-conv-1:D1:1",),
                ),
                RetrievedMemory(
                    text="The studio desk had the same blue notebook.",
                    rank=2,
                    item_id="memory-d2",
                    source_refs=("locomo-conv-1:D2:3",),
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="multi-hop-source-ref-evidence-unit",
    )

    evaluation = result["evaluations"][0]
    assert evaluation["retrieval_quality"]["evidence_term_recall"] == 1.0
    assert evaluation["evidence_bundle"]["covered_evidence_terms"] == ["D1:1", "D2:3"]
    assert evaluation["evidence_bundle"]["bundle_complete"] is True


def test_memory_comparison_evidence_ref_matching_uses_token_boundaries(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Where did Morgan place the checklist?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1",),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:10 Morgan put the checklist in the blue notebook.",
                    rank=1,
                    item_id="memory-d1-10",
                    source_refs=("locomo-conv-1:D1:10",),
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="evidence-ref-boundary-unit",
    )

    evaluation = result["evaluations"][0]
    assert evaluation["retrieval_quality"]["evidence_term_recall"] == 0.0
    assert evaluation["evidence_bundle"]["covered_evidence_terms"] == []
    assert evaluation["evidence_bundle"]["bundle_complete"] is False


def test_memory_comparison_expected_term_matching_uses_token_boundaries(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="What object did Morgan mention?",
        expected_terms=("art",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4, "answer_preview": "art"},
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="Morgan planned a party near the studio.",
                    rank=1,
                    item_id="memory-party",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="expected-term-boundary-unit",
    )

    evaluation = result["evaluations"][0]
    assert evaluation["retrieval_quality"]["expected_term_recall"] == 0.0
    assert evaluation["retrieval_quality"]["covered_terms"] == []
    assert evaluation["evidence_bundle"]["covered_expected_terms"] == []


def test_memory_comparison_evidence_bundle_orders_primary_before_support(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:91",
        question="How long have Mel and her husband been married?",
        expected_terms=("5 years",),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "category": 1,
            "answer_preview": "5 years",
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:1 Melanie and her husband discussed marriage.",
                    rank=1,
                    item_id="support-only",
                ),
                RetrievedMemory(
                    text="D2:3 Melanie: My husband and I have been married for 5 years.",
                    rank=2,
                    item_id="primary-duration",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="evidence-bundle-primary-order-unit",
    )

    bundle = result["evaluations"][0]["evidence_bundle"]
    assert bundle["kind"] == "multi_hop_evidence_bundle"
    assert bundle["item_count"] == 2
    assert bundle["primary_evidence_count"] == 1
    assert bundle["supporting_evidence_count"] == 1
    assert bundle["items"][0]["id"] == "primary-duration"
    assert bundle["items"][0]["rank"] == 2
    assert bundle["items"][0]["covered_expected_terms"] == ["5 years"]
    assert "melanie" in bundle["items"][0]["query_support_terms"]
    assert bundle["items"][0]["bundle_strength_score"] > bundle["items"][1][
        "bundle_strength_score"
    ]
    assert "melanie" in bundle["query_support_terms"]
    assert bundle["bundle_complete"] is True


def test_memory_comparison_evidence_bundle_promotes_strongest_primary(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Which notes connect Morgan's checklist and the studio desk?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1", "D2:3"),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="D1:1 Morgan said there was a checklist.",
                    rank=1,
                    item_id="weak-evidence",
                ),
                RetrievedMemory(
                    text="D2:3 The studio desk had the blue notebook checklist.",
                    rank=2,
                    item_id="strong-primary",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="evidence-bundle-strongest-primary-unit",
    )

    bundle = result["evaluations"][0]["evidence_bundle"]
    assert bundle["primary_evidence_count"] == 1
    assert bundle["supporting_evidence_count"] == 1
    assert bundle["items"][0]["id"] == "strong-primary"
    assert bundle["items"][0]["role"] == "primary"
    assert bundle["items"][0]["covered_expected_terms"] == ["blue notebook"]
    assert bundle["items"][0]["covered_evidence_terms"] == ["D2:3"]
    assert bundle["items"][1]["id"] == "weak-evidence"
    assert bundle["items"][1]["role"] == "supporting"
    assert "_primary_signal" not in bundle["items"][0]
    assert bundle["bundle_complete"] is True


def test_memory_comparison_evidence_bundle_prefers_focused_primary_turn(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:4",
        question="What did Caroline research?",
        expected_terms=("D2:8",),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "category": 1,
            "answer_preview": "adoption agencies",
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text=(
                        "session_2 date: 1:14 pm D2:1 Melanie had updates. "
                        "D2:8 Caroline researched adoption agencies. "
                        "D2:10 Caroline wanted a family and support."
                    ),
                    rank=1,
                    item_id="broad-session",
                ),
                RetrievedMemory(
                    text=(
                        "session_2 turn D2:8 session_2 date: 1:14 pm "
                        "D2:8 Caroline: Researching adoption agencies."
                    ),
                    rank=2,
                    item_id="focused-turn",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="evidence-bundle-focused-primary-unit",
    )

    bundle = result["evaluations"][0]["evidence_bundle"]
    assert bundle["bundle_complete"] is True
    assert bundle["items"][0]["id"] == "focused-turn"
    assert bundle["items"][0]["focused_evidence_score"] > 0
    assert bundle["items"][0]["retrieval_order"] == 2
    assert bundle["bundle_planner"]["schema_version"] == "evidence_bundle_planner.v1"
    assert "focused_turn" in bundle["bundle_planner"][
        "primary_selection_reason_codes"
    ]


def test_memory_comparison_evidence_bundle_deduplicates_mirrored_sources(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:91",
        question="How long have Mel and her husband been married?",
        expected_terms=("5 years",),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "category": 1,
            "answer_preview": "5 years",
        },
    )
    duplicated_text = "D4:2 Melanie: We have been married for 5 years."
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text=duplicated_text,
                    rank=1,
                    item_id="fact-copy",
                    source_refs=("locomo-conv-26:D4:2", "locomo-conv-26:session-4"),
                ),
                RetrievedMemory(
                    text=duplicated_text,
                    rank=2,
                    item_id="raw-turn-copy",
                    source_refs=("locomo-conv-26:session-4", "locomo-conv-26:D4:2"),
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=2,
        top_k_cutoffs=(2,),
        run_id="evidence-bundle-dedupe-unit",
    )

    bundle = result["evaluations"][0]["evidence_bundle"]
    assert bundle["candidate_item_count"] == 2
    assert bundle["deduplicated_item_count"] == 1
    assert bundle["item_count"] == 1
    assert bundle["primary_evidence_count"] == 1
    assert bundle["supporting_evidence_count"] == 0
    assert bundle["items"][0]["id"] == "fact-copy"
    assert bundle["bundle_complete"] is False


def test_memory_comparison_evidence_matching_ignores_punctuation_variants(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:87",
        question=(
            "What type of individuals does the adoption agency Caroline "
            "is considering support?"
        ),
        expected_terms=("LGBTQ+ individuals",),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "category": 4,
            "answer_preview": "LGBTQ+ individuals",
            "evidence_terms": ("D7:2",),
        },
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text=(
                        "D7:2 The adoption agency supports LGBTQ individuals "
                        "through inclusive services."
                    ),
                    rank=1,
                    item_id="punctuation-variant",
                ),
            )
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="evidence-punctuation-unit",
    )

    evaluation = result["evaluations"][0]
    assert evaluation["retrieval_quality"]["expected_term_recall"] == 1.0
    assert evaluation["retrieval_quality"]["covered_terms"] == ["LGBTQ+ individuals"]
    bundle = evaluation["evidence_bundle"]
    assert bundle["expected_term_recall"] == 1.0
    assert bundle["items"][0]["covered_expected_terms"] == ["LGBTQ+ individuals"]
    assert bundle["bundle_complete"] is True


def test_memory_comparison_compact_report_omits_heavy_evaluations(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    report = tmp_path / "compact-report.json"
    dataset.write_text("[]", encoding="utf-8")
    passing = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    failing = _case(
        case_id="conv-1:qa:2",
        question="Where is the launch plan?",
        expected_terms=("red folder",),
        answer="red folder",
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            passing.case_id: (
                RetrievedMemory(
                    text="The checklist is in the blue notebook.",
                    rank=1,
                    score=0.9,
                    item_id="hit",
                    metadata={
                        "diagnostics": {"retrieval_sources": ["postgres_facts"]}
                    },
                ),
            ),
            failing.case_id: (
                RetrievedMemory(
                    text="The launch plan was discussed.",
                    rank=1,
                    score=0.4,
                    item_id="miss",
                    metadata={
                        "diagnostics": {"retrieval_sources": ["postgres_facts"]}
                    },
                ),
            ),
        },
    )

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(passing, failing),
        top_k=1,
        top_k_cutoffs=(1,),
        run_id="compact-unit",
        report_out=report,
        report_mode="compact",
        compact_failure_limit=1,
    )

    assert result["metadata"]["report_mode"] == "compact"
    assert result["metadata"]["full_evaluation_count"] == 2
    assert result["evaluations"] == []
    assert len(result["failure_analysis"]) == 1
    assert result["diagnostics"]["backend_summaries"]["memo-stack"][
        "retrieval_source_counts"
    ] == {"postgres_facts": 2}
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["evaluations"] == []
    assert written["metadata"]["report_mode"] == "compact"


def test_memory_comparison_compact_report_preserves_setup_failures(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    dataset.write_text("[]", encoding="utf-8")
    backend = _StaticBackend("memo-stack", {})

    result = run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(),
        run_id="compact-setup-failure-unit",
        report_mode="compact",
    )

    assert result["ok"] is False
    assert result["failure_analysis"] == [
        {
            "case_id": "dataset",
            "backend": "setup",
            "group": "setup",
            "reason": "no_supported_cases",
        }
    ]
    assert result["failures"] == result["failure_analysis"]


def test_memory_comparison_replay_reevaluates_saved_retrievals_offline(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "unused.json"
    source_report = tmp_path / "source-report.json"
    replay_report = tmp_path / "replay-report.json"
    dataset.write_text("[]", encoding="utf-8")
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    backend = _StaticBackend(
        "memo-stack",
        {
            case.case_id: (
                RetrievedMemory(
                    text="The checklist is in the blue notebook.",
                    rank=1,
                    score=0.9,
                    item_id="memory-1",
                ),
            )
        },
    )
    run_memory_comparison_benchmark(
        dataset_path=dataset,
        backends=(backend,),
        cases_override=(case,),
        top_k=1,
        top_k_cutoffs=(1,),
        report_out=source_report,
        run_id="source-unit",
    )
    search_calls_after_source = dict(backend.search_calls)

    result = run_memory_comparison_replay(
        report_path=source_report,
        report_out=replay_report,
        run_id="replay-unit",
    )

    assert backend.search_calls == search_calls_after_source
    assert result["evaluation_mode"] == "evaluate_only_replay"
    assert result["metadata"]["source_run_id"] == "source-unit"
    assert result["metadata"]["replay_scope"] == "answerer_judge_only_no_memory_calls"
    assert result["backend_metrics"]["memo-stack"]["accuracy"] == 1.0
    assert result["evaluations"][0]["replay"]["memory_calls"] == 0
    written = json.loads(replay_report.read_text(encoding="utf-8"))
    assert written["evaluation_mode"] == "evaluate_only_replay"


def test_memory_comparison_replay_rejects_compact_source_report(tmp_path: Path) -> None:
    compact_report = tmp_path / "compact-report.json"
    compact_report.write_text(
        json.dumps(
            {
                "suite": "memory-comparison-benchmark",
                "metadata": {"report_mode": "compact"},
                "evaluations": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkValidationError, match="compact reports cannot"):
        run_memory_comparison_replay(report_path=compact_report)


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
    cutoff_metrics = result["backend_metrics"]["mem0"]["by_cutoff"]["1"]
    assert cutoff_metrics["primary"] is True
    assert cutoff_metrics["total"] == 1
    assert cutoff_metrics["passed"] == 0
    assert cutoff_metrics["failed"] == 1
    assert cutoff_metrics["accuracy"] == 0.0
    assert cutoff_metrics["avg_score"] == 0.0
    assert cutoff_metrics["avg_memories_evaluated"] == 0.0
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


def test_memory_comparison_codex_provider_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEMORY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    answerer, judge = eval_module._memory_comparison_llms_from_args(
        SimpleNamespace(
            answerer_provider="codex",
            judge_provider="codex",
            allow_paid_llm=False,
            openai_api_key_env="MEMORY_OPENAI_API_KEY",
            answerer_model=None,
            judge_model=None,
            codex_command="codex",
            codex_timeout_seconds=12.0,
        )
    )

    assert isinstance(answerer, CodexCliAnswerer)
    assert isinstance(judge, CodexCliJudge)
    assert answerer.model == "gpt-5.5"
    assert judge.model == "gpt-5.5"


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
        assert kwargs["locomo_ingest_mode"] == "official-turns"
        assert kwargs["case_set"] == "locomo-fast"
        assert kwargs["report_mode"] == "compact"
        assert kwargs["compact_failure_limit"] == 7
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
            "--mem0-skip-reset",
            "--locomo-ingest-mode",
            "official-turns",
            "--case-set",
            "locomo-fast",
            "--report-mode",
            "compact",
            "--compact-failure-limit",
            "7",
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
    assert "mem0-unit-key" not in captured.out
    assert "mem0-unit-key" not in captured.err
    assert mem0_backend_kwargs == [
        {
            "base_url": "http://mem0.example",
            "api_key": "mem0-unit-key",
            "reset_user_on_start": False,
            "send_timestamps": False,
        }
    ]


def test_memory_comparison_replay_cli_is_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source_report = tmp_path / "source-report.json"
    replay_report = tmp_path / "replay-report.json"
    source_report.write_text('{"evaluations":[{}]}', encoding="utf-8")
    monkeypatch.delenv("MEMORY_SERVICE_TOKEN", raising=False)

    def fake_run_memory_comparison_replay(**kwargs: object) -> dict[str, object]:
        assert kwargs["report_path"] == source_report
        assert kwargs["report_out"] == replay_report
        assert kwargs["top_k_cutoffs"] == (10, 20)
        assert kwargs["primary_cutoff"] == 20
        assert kwargs["report_mode"] == "compact"
        assert kwargs["compact_failure_limit"] == 3
        assert kwargs["answerer_token_cost_rate"] == TokenCostRate(
            input_usd_per_1m=1.5,
            output_usd_per_1m=2.5,
        )
        assert kwargs["judge_token_cost_rate"] == TokenCostRate(
            input_usd_per_1m=3.5,
            output_usd_per_1m=4.5,
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
        "run_memory_comparison_replay",
        fake_run_memory_comparison_replay,
    )

    eval_module.main(
        [
            "memory-comparison-replay",
            "--report",
            str(source_report),
            "--report-out",
            str(replay_report),
            "--top-k-cutoff",
            "10",
            "--top-k-cutoff",
            "20",
            "--primary-cutoff",
            "20",
            "--report-mode",
            "compact",
            "--compact-failure-limit",
            "3",
            "--answerer-input-usd-per-1m",
            "1.5",
            "--answerer-output-usd-per-1m",
            "2.5",
            "--judge-input-usd-per-1m",
            "3.5",
            "--judge-output-usd-per-1m",
            "4.5",
        ]
    )

    captured = capsys.readouterr()
    assert "MEMORY_SERVICE_TOKEN" not in captured.err


def test_memory_comparison_official_locomo_turn_mode_uses_mem0_style_chunks(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-turns-mini",
                    "conversation": {
                        "speaker_a": "Caroline",
                        "speaker_b": "Melanie",
                        "session_1_date_time": "1:56 pm on 8 May, 2023",
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I put the checklist in the blue notebook.",
                            },
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:2",
                                "text": "I saw it on the studio desk.",
                                "query": "notebook on desk",
                                "blip_caption": "a blue notebook on a studio desk",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": "Where is the checklist?",
                            "answer": "blue notebook",
                            "evidence": ["D1:1"],
                            "category": 4,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_memory_comparison_cases(
        dataset,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )

    assert len(cases) == 1
    case = cases[0]
    assert case.documents == ()
    assert len(case.memories) == 2
    assert case.memories[0].metadata["role"] == "user"
    assert case.memories[1].metadata["role"] == "assistant"
    assert case.memories[0].metadata["timestamp"] == 1683554160
    assert "session_1 date: 1:56 pm on 8 May, 2023" in case.memories[0].text
    assert "D1:1 Caroline:" in case.memories[0].text
    assert "The image shows: a blue notebook on a studio desk" in case.memories[1].text
    assert case.memory_scope_external_ref == "locomo-conv-turns-mini"
    assert case.expected_terms == ("blue notebook",)
    assert case.metadata["answer_preview"] == "blue notebook"
    assert case.metadata["answer_terms"] == ("blue notebook",)
    assert case.metadata["evidence_terms"] == ("D1:1",)


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


def test_infinity_context_http_ingest_mirrors_memory_only_cases_as_documents() -> None:
    seen_requests: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.url.path, json.loads(request.content)))
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
                text="D1:1 Morgan: The checklist is in the blue notebook.",
                source_external_id="locomo:conv-1:session_1:D1-1:turn",
                metadata={
                    "role": "assistant",
                    "timestamp": 1683546960,
                    "session_key": "session_1",
                    "session_date": "11:56 am on 8 May, 2023",
                    "dia_id": "D1:1",
                },
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
    )

    try:
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert [path for path, _ in seen_requests] == ["/v1/facts", "/v1/documents"]
    fact_payload = seen_requests[0][1]
    document_payload = seen_requests[1][1]
    assert fact_payload["source_refs"][0]["time_start_ms"] == 1683546960000
    assert fact_payload["source_refs"][0]["time_end_ms"] == 1683546960000
    assert document_payload["source_type"] == "memory_comparison_raw_turn"
    assert document_payload["text"] == case.memories[0].text
    assert document_payload["source_refs"][0]["time_start_ms"] == 1683546960000
    assert document_payload["source_refs"][0]["time_end_ms"] == 1683546960000
    assert result.items_processed == 2
    assert result.metadata["mirrored_memory_documents_created"] == 1
    assert result.metadata["hybrid_raw_turn_documents_enabled"] is True
    assert result.operations[0].metadata["source_timestamp"] == 1683546960
    assert result.operations[0].metadata["session_key"] == "session_1"


def test_infinity_context_http_search_uses_isolated_context_payload() -> None:
    seen_payloads: list[dict[str, object]] = []
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "fact-1",
                            "item_type": "fact",
                            "text": "Morgan kept the checklist in the blue notebook.",
                            "score": 0.91,
                            "source_refs": [
                                {
                                    "source_id": "memory-1",
                                    "source_type": "memory_comparison_benchmark",
                                }
                            ],
                        }
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
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

    assert seen_paths == ["/v1/context/benchmark-search"]
    assert seen_payloads == [
        {
            "space_slug": "memory-comparison-run-42",
            "memory_scope_external_ref": "locomo-conv-1",
            "thread_external_ref": "locomo-conv-1",
            "query": "Where is the checklist?",
            "token_budget": 2048,
            "max_facts": 7,
            "max_chunks": 7,
        }
    ]
    assert result.total_results == 1
    assert result.memories[0].item_id == "fact-1"
    assert result.memories[0].source_refs == ("memory-1",)
    assert result.context_token_count is not None
    assert result.context_token_count > 0
    assert result.metadata["benchmark_search"] is True
    assert result.metadata["limited_by_http_api_caps"] is False


def test_infinity_context_http_search_keeps_string_source_refs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "raw-turn",
                            "item_type": "chunk",
                            "text": "D3:4 Morgan: The checklist is in the notebook.",
                            "score": 0.91,
                            "source_refs": [
                                "D3:4",
                                {
                                    "source_id": "memory-session-3",
                                    "time_start_ms": 1200,
                                },
                            ],
                        }
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("notebook",),
        answer="notebook",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=7)
    finally:
        backend.close()

    assert result.memories[0].source_refs == ("D3:4", "memory-session-3")
    assert result.memories[0].metadata["source_ref_time_start_ms"] == [1200]
    assert result.memories[0].metadata["has_temporal_source_ref"] is True


def test_infinity_context_http_search_temporal_reranks_timestamped_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "untimed",
                            "item_type": "fact",
                            "text": "Morgan mentioned the checklist.",
                            "score": 0.9,
                            "source_refs": [{"source_id": "memory-untimed"}],
                        },
                        {
                            "item_id": "timed",
                            "item_type": "chunk",
                            "text": "At 11:56 on 8 May, Morgan put it in the notebook.",
                            "score": 0.86,
                            "source_refs": [
                                {
                                    "source_id": "memory-timed",
                                    "time_start_ms": 1683546960000,
                                    "time_end_ms": 1683546960000,
                                }
                            ],
                        },
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="When did Morgan mention the checklist?",
        expected_terms=("11:56",),
        answer="11:56",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert result.memories[0].item_id == "timed"
    assert result.memories[0].metadata["source_ref_time_start_ms"] == [
        1683546960000
    ]
    assert result.memories[0].metadata["diagnostics"]["temporal_rerank_boosted"] is True
    assert result.metadata["temporal_rerank"]["applied"] is True
    assert result.metadata["temporal_rerank"]["timestamped_memory_count"] == 1


def test_infinity_context_http_search_decomposes_temporal_session_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "session date" in payload["query"]:
            items = [
                {
                    "item_id": "session-evidence",
                    "item_type": "chunk",
                    "text": (
                        "session_4 date: Friday 9 June, 2023\n"
                        "D4:3 Morgan: I booked the studio desk after Friday."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-session"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "temporal-distractor",
                    "item_type": "fact",
                    "text": "D2:1 Morgan mentioned the checklist earlier.",
                    "score": 0.88,
                    "source_refs": [{"source_id": "memory-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:2",
        question="What did Morgan do after Friday?",
        expected_terms=("booked the studio desk",),
        answer="booked the studio desk",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What did Morgan do after Friday?",
        "What did Morgan do after Friday?\n"
        "Search focus: entities: morgan; speakers: morgan:; "
        "temporal: after, friday, session, date, time, last, today, yesterday",
        "morgan after friday session date time last today",
    ]
    assert result.memories[0].item_id == "session-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "friday" in query_profile["temporal_surface_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_temporal_sequence_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0


def test_infinity_context_http_search_boosts_relative_temporal_text() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "session date" in payload["query"]:
            items = [
                {
                    "item_id": "relative-temporal-evidence",
                    "item_type": "chunk",
                    "text": "D5:2 Morgan: I visited the studio yesterday.",
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-relative-temporal"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "relative-temporal-distractor",
                    "item_type": "fact",
                    "text": "D1:1 Morgan mentioned a studio checklist.",
                    "score": 0.88,
                    "source_refs": [{"source_id": "memory-relative-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:3",
        question="When did Morgan visit the studio?",
        expected_terms=("yesterday",),
        answer="yesterday",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "When did Morgan visit the studio?",
        "morgan visit visited studio place trip event",
        "morgan when session date time last today yesterday",
    ]
    assert result.memories[0].item_id == "relative-temporal-evidence"
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert "participation_event" in diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ]
    assert diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_temporal_sequence_boost"] == 0
    assert diagnostics["score_signals"]["benchmark_participation_event_boost"] > 0


def test_infinity_context_http_search_reranks_visual_caption_evidence() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "image shows" in payload["query"]:
            items = [
                {
                    "item_id": "visual-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D1:12 Melanie: Look at my painting. "
                        "[Sharing image - query: lake painting. "
                        "The image shows: a watercolor lake sunrise.]"
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-visual"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "visual-distractor",
                    "item_type": "fact",
                    "text": "D1:10 Melanie: I talked about painting classes.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-visual-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:3",
        question="What painting did Melanie show?",
        expected_terms=("lake sunrise",),
        answer="lake sunrise",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What painting did Melanie show?",
        "melanie paint show image shows",
        "melanie paint image picture",
    ]
    assert result.memories[0].item_id == "visual-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "paint" in query_profile["visual_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_visual_evidence_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0


def test_query_decomposition_normalizes_locomo_action_typos() -> None:
    case = _case(
        case_id="conv-26:qa:14",
        question="What career path has Caroline decided to persue?",
        expected_terms=("counseling",),
        answer="counseling",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)

    assert queries == (
        "What career path has Caroline decided to persue?",
        "What career path has Caroline decided to persue?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: career, path, work, working, think, figuring, option, decide",
        "caroline career path work working think figuring",
    )
    query_profile = metadata["query_profile"]
    assert "career" in query_profile["relation_terms"]
    assert "path" in query_profile["relation_terms"]
    assert "decide" in query_profile["relation_terms"]
    assert "pursue" in query_profile["relation_terms"]
    assert "work" in query_profile["relation_variant_terms"]
    assert "think" in query_profile["relation_variant_terms"]
    assert "figur" in query_profile["relation_variant_terms"]

    education_case = _case(
        case_id="conv-26:qa:3",
        question="What fields would Caroline be likely to pursue in her educaton?",
        expected_terms=("psychology",),
        answer="psychology",
    )

    education_queries, education_metadata = rerank_module.decomposed_search_queries(
        education_case
    )

    assert education_queries[2] == "caroline career option work support similar issue"
    assert "field" in education_metadata["query_profile"]["relation_terms"]
    assert "option" in education_metadata["query_profile"]["relation_variant_terms"]
    assert "work" in education_metadata["query_profile"]["relation_variant_terms"]
    assert "support" in education_metadata["query_profile"]["relation_variant_terms"]
    assert "similar" in education_metadata["query_profile"]["relation_variant_terms"]
    assert "issue" in education_metadata["query_profile"]["relation_variant_terms"]
    assert "education" in education_metadata["query_profile"]["lexical_terms"]


def test_query_decomposition_drops_modal_words_from_entities() -> None:
    case = _case(
        case_id="conv-26:qa:15",
        question=(
            "Would Caroline still want to pursue counseling as a career "
            "if she hadn't received support growing up?"
        ),
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)

    query_profile = metadata["query_profile"]
    assert query_profile["entities"] == ("caroline",)
    assert query_profile["entity_surfaces"] == ("caroline",)
    assert queries[1].startswith(
        "Would Caroline still want to pursue counseling as a career"
    )
    assert "entities: would caroline" not in queries[1].casefold()
    assert "speakers: would caroline:" not in queries[1].casefold()
    assert "speakers: caroline:" in queries[1]


def test_query_decomposition_reports_typed_retrieval_intent() -> None:
    relationship_case = _case(
        case_id="conv-26:qa:8",
        question="What is Caroline's relationship status?",
        expected_terms=("single",),
        answer="single",
    )
    kinship_case = _case(
        case_id="conv-26:qa:kinship",
        question="Who is Melanie's husband?",
        expected_terms=("Alex",),
        answer="Alex",
    )
    duration_case = _case(
        case_id="conv-26:qa:11",
        question="How long has Caroline had her current group of friends for?",
        expected_terms=("5 years",),
        answer="5 years",
        category=2,
    )
    contrast_case = _case(
        case_id="conv-26:qa:contrast",
        question="How is Caroline's current career path different from before?",
        expected_terms=("writing",),
        answer="writing",
    )
    explicit_time_case = _case(
        case_id="conv-1:qa:explicit-time",
        question="When did Morgan mention the checklist on Friday?",
        expected_terms=("Friday",),
        answer="Friday",
        category=2,
    )
    relative_time_case = _case(
        case_id="conv-1:qa:relative-time",
        question="When did Morgan visit the studio yesterday?",
        expected_terms=("yesterday",),
        answer="yesterday",
        category=2,
    )
    category_multi_hop_case = _case(
        case_id="conv-26:qa:activity",
        question="What activities does Melanie partake in?",
        expected_terms=("pottery",),
        answer="pottery",
        category=1,
    )

    _, relationship_metadata = rerank_module.decomposed_search_queries(
        relationship_case
    )
    kinship_queries, kinship_metadata = rerank_module.decomposed_search_queries(
        kinship_case
    )
    _, duration_metadata = rerank_module.decomposed_search_queries(duration_case)
    contrast_queries, contrast_metadata = rerank_module.decomposed_search_queries(
        contrast_case
    )
    _, explicit_time_metadata = rerank_module.decomposed_search_queries(
        explicit_time_case
    )
    _, relative_time_metadata = rerank_module.decomposed_search_queries(
        relative_time_case
    )
    _, category_multi_hop_metadata = rerank_module.decomposed_search_queries(
        category_multi_hop_case
    )

    relationship_intent = relationship_metadata["retrieval_intent"]
    assert relationship_intent["schema_version"] == "retrieval_intent.v1"
    assert relationship_intent["uses_ground_truth"] is False
    assert relationship_intent["entities"][0]["canonical"] == "caroline"
    assert "inference_support" in relationship_intent["evidence_need"]
    relationship_facets = relationship_intent["relations"]["intents"]
    assert relationship_facets[0]["category"] == "status_profile"
    assert relationship_facets[0]["evidence_need"] == "inference_support"
    assert "status_profile" in relationship_metadata["query_profile"][
        "relation_categories"
    ]
    assert "single" not in json.dumps(relationship_intent)
    assert relationship_metadata["query_profile"]["evidence_need"] == (
        "inference_support",
    )
    assert relationship_metadata["query_profile"]["bundle_evidence_roles"] == (
        "primary",
        "inference_support",
    )
    assert relationship_metadata["query_profile"]["risk_flags"] == ()
    relationship_plan = relationship_metadata["query_plan"]
    assert relationship_plan["schema_version"] == "query_plan.v2"
    assert relationship_plan["uses_ground_truth"] is False
    assert relationship_plan["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "inference_support",
    ]
    assert relationship_plan["selected_role_families"] == [
        "base_query",
        "expanded_focus",
        "relation_compact",
    ]
    assert relationship_plan["leakage_guard"]["answer_terms_allowed"] is False
    kinship_intent = kinship_metadata["retrieval_intent"]
    kinship_facets = kinship_intent["relations"]["intents"]
    assert kinship_intent["relations"]["terms"] == ["husband"]
    assert kinship_facets[0]["category"] == "status_profile"
    assert kinship_metadata["query_profile"]["risk_flags"] == ()
    assert "status_profile" in kinship_metadata["query_profile"][
        "relation_categories"
    ]
    assert "spouse" in kinship_metadata["query_profile"]["relation_variant_terms"]
    assert kinship_queries[2] == "melanie husband spouse partner wife marry married"

    duration_intent = duration_metadata["retrieval_intent"]
    assert duration_intent["time_intent"]["kind"] == "duration"
    assert "temporal_support" in duration_intent["evidence_need"]
    assert "inference_support" in duration_intent["evidence_need"]
    assert duration_intent["bundle_evidence_roles"] == [
        "primary",
        "temporal_support",
        "inference_support",
    ]
    duration_categories = {
        facet["category"] for facet in duration_intent["relations"]["intents"]
    }
    assert "status_profile" in duration_categories
    assert "temporal" in duration_categories
    assert "inference_support" in duration_metadata["query_plan"]["selected_roles"]
    duration_temporal_candidate = next(
        item
        for item in duration_metadata["query_plan"]["candidates"]
        if item["role"] == "duration_temporal_support"
    )
    assert duration_temporal_candidate["reason_codes"] == [
        "temporal_support",
        "duration_temporal_support",
        "time_kind:duration",
    ]
    assert explicit_time_metadata["retrieval_intent"]["time_intent"]["kind"] == (
        "explicit_time"
    )
    explicit_temporal_candidate = next(
        item
        for item in explicit_time_metadata["query_plan"]["candidates"]
        if item["role"] == "explicit_temporal_support"
    )
    assert "time_kind:explicit_time" in explicit_temporal_candidate["reason_codes"]
    assert relative_time_metadata["retrieval_intent"]["time_intent"]["kind"] == (
        "relative_time"
    )
    assert "relative_temporal_support" in relative_time_metadata["query_plan"][
        "selected_roles"
    ]

    contrast_intent = contrast_metadata["retrieval_intent"]
    assert "contrast" in contrast_intent["evidence_need"]
    assert contrast_intent["bundle_evidence_roles"] == [
        "primary",
        "temporal_support",
        "contrast",
    ]
    contrast_facets = {
        facet["category"]: facet
        for facet in contrast_intent["relations"]["intents"]
    }
    assert contrast_facets["contrast"]["evidence_need"] == "contrast"
    assert "contrast" in contrast_metadata["query_profile"]["evidence_need"]
    assert "contrast" in contrast_metadata["query_profile"]["relation_categories"]
    assert "writing" not in json.dumps(contrast_intent)
    contrast_plan = contrast_metadata["query_plan"]
    assert contrast_plan["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "compact_relation",
        "contrast_support",
    ]
    contrast_query = next(
        item["query"]
        for item in contrast_plan["selected"]
        if item["role"] == "contrast_support"
    )
    assert contrast_queries[-1] == contrast_query
    assert contrast_query == (
        "caroline current career path different now ongoing previous before earlier"
    )
    assert "writing" not in json.dumps(contrast_plan)

    category_multi_hop_intent = category_multi_hop_metadata["retrieval_intent"]
    assert "multi_hop" not in category_multi_hop_intent["evidence_need"]
    assert category_multi_hop_intent["bundle_evidence_roles"] == [
        "primary",
        "bridge",
    ]
    assert "multi_hop" not in category_multi_hop_metadata["query_plan"][
        "selected_role_families"
    ]


def test_query_decomposition_expands_open_domain_inference_queries() -> None:
    writing_case = _case(
        case_id="conv-26:qa:28",
        question="Would Caroline pursue writing as a career option?",
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )
    counseling_case = _case(
        case_id="conv-26:qa:15",
        question=(
            "Would Caroline still want to pursue counseling as a career "
            "if she hadn't received support growing up?"
        ),
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )
    personality_case = _case(
        case_id="conv-26:qa:70",
        question="What personality traits might Melanie say Caroline has?",
        expected_terms=("thoughtful",),
        answer="thoughtful, authentic, driven",
        category=3,
    )
    roadtrip_case = _case(
        case_id="conv-26:qa:78",
        question="Would Melanie go on another roadtrip soon?",
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )

    writing_queries, writing_metadata = rerank_module.decomposed_search_queries(
        writing_case
    )
    counseling_queries, counseling_metadata = rerank_module.decomposed_search_queries(
        counseling_case
    )
    personality_queries, personality_metadata = rerank_module.decomposed_search_queries(
        personality_case
    )
    roadtrip_queries, roadtrip_metadata = rerank_module.decomposed_search_queries(
        roadtrip_case
    )

    assert writing_queries[2] == "caroline write career looking books book support"
    assert "write" in writing_metadata["query_profile"]["relation_terms"]
    assert "career" in writing_metadata["query_profile"]["relation_terms"]
    assert "writing" in writing_metadata["query_profile"]["relation_variant_terms"]
    assert "support" in writing_metadata["query_profile"]["relation_variant_terms"]
    assert "similar" in writing_metadata["query_profile"]["relation_variant_terms"]
    assert counseling_queries[2] == "caroline want counsel support got help growing"
    assert "counsel" in counseling_metadata["query_profile"]["relation_terms"]
    assert "receive" in counseling_metadata["query_profile"]["relation_terms"]
    assert "grow" in counseling_metadata["query_profile"]["relation_terms"]
    assert "exchange" not in counseling_metadata["query_profile"]["relation_categories"]
    assert "mental" in counseling_metadata["query_profile"]["relation_variant_terms"]
    assert personality_queries[2] == (
        "melanie caroline personality trait care real concern thank"
    )
    assert "personality" in personality_metadata["query_profile"]["relation_terms"]
    assert "concern" in personality_metadata["query_profile"]["relation_variant_terms"]
    assert "thank" in personality_metadata["query_profile"]["relation_variant_terms"]
    assert "care" in personality_metadata["query_profile"]["relation_variant_terms"]
    assert "drive" in personality_metadata["query_profile"]["relation_variant_terms"]
    assert roadtrip_queries[2] == "melanie roadtrip trip road weekend past soon"
    assert "roadtrip" in roadtrip_metadata["query_profile"]["relation_terms"]
    assert "travel" in roadtrip_metadata["query_profile"]["relation_variant_terms"]
    assert not {"accident", "son", "family", "safe"}.intersection(
        roadtrip_metadata["query_profile"]["relation_variant_terms"]
    )


def test_query_decomposition_expands_profile_attribute_queries() -> None:
    identity_case = _case(
        case_id="conv-26:qa:5",
        question="What is Caroline's identity?",
        expected_terms=("transgender woman",),
        answer="transgender woman",
    )
    relationship_case = _case(
        case_id="conv-26:qa:8",
        question="What is Caroline's relationship status?",
        expected_terms=("single",),
        answer="single",
    )
    books_case = _case(
        case_id="conv-26:qa:23",
        question="Would Caroline likely have Dr. Seuss books on her bookshelf?",
        expected_terms=("classic children's books",),
        answer="classic children's books",
    )
    read_books_case = _case(
        case_id="conv-26:qa:24",
        question="What books has Melanie read?",
        expected_terms=("Nothing is Impossible", "Charlotte's Web"),
        answer="Nothing is Impossible and Charlotte's Web",
    )
    political_case = _case(
        case_id="conv-26:qa:51",
        question="What would Caroline's political leaning likely be?",
        expected_terms=("liberal",),
        answer="liberal",
    )
    religious_case = _case(
        case_id="conv-26:qa:60",
        question="Would Caroline be considered religious?",
        expected_terms=("somewhat religious",),
        answer="somewhat religious",
    )

    identity_queries, identity_metadata = rerank_module.decomposed_search_queries(
        identity_case
    )
    relationship_queries, relationship_metadata = (
        rerank_module.decomposed_search_queries(relationship_case)
    )
    books_queries, books_metadata = rerank_module.decomposed_search_queries(books_case)
    read_books_queries, read_books_metadata = rerank_module.decomposed_search_queries(
        read_books_case
    )
    political_queries, political_metadata = rerank_module.decomposed_search_queries(
        political_case
    )
    religious_queries, religious_metadata = rerank_module.decomposed_search_queries(
        religious_case
    )

    assert identity_queries[2] == (
        "caroline identity support inspiring story gender accepted"
    )
    assert "caroline'" not in identity_metadata["query_profile"]["lexical_terms"]
    assert "identity" in identity_metadata["query_profile"]["relation_terms"]
    assert "pride" in identity_metadata["query_profile"]["relation_variant_terms"]
    assert "support" in identity_metadata["query_profile"]["relation_variant_terms"]
    assert "inspir" in identity_metadata["query_profile"]["relation_variant_terms"]
    assert "accept" in identity_metadata["query_profile"]["relation_variant_terms"]
    assert not {"transgender", "woman"}.intersection(
        identity_metadata["query_profile"]["relation_variant_terms"]
    )
    assert relationship_queries[2] == (
        "caroline parent breakup family kid friend support"
    )
    assert "status" in relationship_metadata["query_profile"]["relation_terms"]
    assert "parent" in relationship_metadata["query_profile"]["relation_variant_terms"]
    assert "breakup" in relationship_metadata["query_profile"]["relation_variant_terms"]
    assert "family" in relationship_metadata["query_profile"]["relation_variant_terms"]
    assert "support" in relationship_metadata["query_profile"]["relation_variant_terms"]
    assert "single" not in relationship_metadata["query_profile"][
        "relation_variant_terms"
    ]
    assert books_queries[2] == "caroline book books kids stories bookshelf kid"
    assert "book" in books_metadata["query_profile"]["relation_terms"]
    assert "kid" in books_metadata["query_profile"]["relation_variant_terms"]
    assert not {"children", "classic"}.intersection(
        books_metadata["query_profile"]["relation_variant_terms"]
    )
    assert read_books_queries[2] == "melanie book read reading bookshelf kid story"
    assert "book" in read_books_metadata["query_profile"]["relation_terms"]
    assert "read" in read_books_metadata["query_profile"]["relation_terms"]
    assert political_queries[2] == "caroline political rights lgbtq support accepted belief"
    assert "political" in political_metadata["query_profile"]["relation_terms"]
    assert "right" in political_metadata["query_profile"]["relation_variant_terms"]
    assert not {"conservative", "transition", "comment", "hike"}.intersection(
        political_metadata["query_profile"]["relation_variant_terms"]
    )
    assert religious_queries[2] == (
        "caroline religious church think journey changing acceptance"
    )
    assert "religious" in religious_metadata["query_profile"]["relation_terms"]
    assert "journey" in religious_metadata["query_profile"]["relation_variant_terms"]
    assert "chang" in religious_metadata["query_profile"]["relation_variant_terms"]
    assert "acceptance" in religious_metadata["query_profile"]["relation_variant_terms"]
    assert "conservative" not in religious_metadata["query_profile"][
        "relation_variant_terms"
    ]


def test_query_decomposition_expands_locomo_topic_relations() -> None:
    activity_case = _case(
        case_id="conv-26:qa:16",
        question="What activities does Melanie partake in?",
        expected_terms=("pottery", "camping", "painting", "swimming"),
        answer="pottery, camping, painting, swimming",
    )
    camp_case = _case(
        case_id="conv-26:qa:19",
        question="Where has Melanie camped?",
        expected_terms=("beach", "mountains", "forest"),
        answer="beach, mountains, forest",
    )
    kids_case = _case(
        case_id="conv-26:qa:20",
        question="What do Melanie's kids like?",
        expected_terms=("dinosaurs", "nature"),
        answer="dinosaurs and nature",
    )
    adoption_support_case = _case(
        case_id="conv-26:qa:87",
        question=(
            "What type of individuals does the adoption agency Caroline "
            "is considering support?"
        ),
        expected_terms=("LGBTQ+ individuals",),
        answer="LGBTQ+ individuals",
    )
    adoption_choice_case = _case(
        case_id="conv-26:qa:88",
        question="Why did Caroline choose the adoption agency?",
        expected_terms=("because of their inclusivity and support",),
        answer="because of their inclusivity and support",
    )
    adoption_process_case = _case(
        case_id="conv-26:qa:89",
        question="What is Caroline excited about in the adoption process?",
        expected_terms=("creating a family for kids who need one",),
        answer="creating a family for kids who need one",
    )
    adoption_decision_case = _case(
        case_id="conv-26:qa:90",
        question="What does Melanie think about Caroline's decision to adopt?",
        expected_terms=("doing something amazing", "awesome mom"),
        answer="doing something amazing and will be an awesome mom",
    )
    song_case = _case(
        case_id="conv-26:qa:65",
        question='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        expected_terms=("classical music",),
        answer="yes",
    )
    necklace_case = _case(
        case_id="conv-26:qa:92",
        question="What does Caroline's necklace symbolize?",
        expected_terms=("love", "faith", "strength"),
        answer="love, faith, and strength",
    )
    summer_plan_case = _case(
        case_id="conv-26:qa:86",
        question="What are Caroline's plans for the summer?",
        expected_terms=("researching adoption agencies",),
        answer="researching adoption agencies",
    )
    self_care_case = _case(
        case_id="conv-26:qa:85",
        question="How does Melanie prioritize self-care?",
        expected_terms=("me-time", "running", "violin"),
        answer="me-time with running and violin",
    )

    activity_queries, activity_metadata = rerank_module.decomposed_search_queries(
        activity_case
    )
    camp_queries, camp_metadata = rerank_module.decomposed_search_queries(camp_case)
    kids_queries, kids_metadata = rerank_module.decomposed_search_queries(kids_case)
    adoption_queries, adoption_metadata = rerank_module.decomposed_search_queries(
        adoption_support_case
    )
    adoption_choice_queries, adoption_choice_metadata = (
        rerank_module.decomposed_search_queries(adoption_choice_case)
    )
    adoption_process_queries, adoption_process_metadata = (
        rerank_module.decomposed_search_queries(adoption_process_case)
    )
    adoption_decision_queries, adoption_decision_metadata = (
        rerank_module.decomposed_search_queries(adoption_decision_case)
    )
    song_queries, song_metadata = rerank_module.decomposed_search_queries(song_case)
    necklace_queries, necklace_metadata = rerank_module.decomposed_search_queries(
        necklace_case
    )
    summer_plan_queries, summer_plan_metadata = rerank_module.decomposed_search_queries(
        summer_plan_case
    )
    self_care_queries, self_care_metadata = rerank_module.decomposed_search_queries(
        self_care_case
    )

    assert activity_queries[2] == (
        "melanie activity hobby partake class creative fun express refresh"
    )
    assert "activity" in activity_metadata["query_profile"]["relation_terms"]
    assert activity_metadata["query_profile"]["relation_category_terms"][
        "activity"
    ] == (
        "activity",
        "hobby",
        "class",
        "creative",
    )
    assert "hobby" in activity_metadata["query_profile"]["relation_variant_terms"]
    assert "class" in activity_metadata["query_profile"]["relation_variant_terms"]
    assert "creative" in activity_metadata["query_profile"]["relation_variant_terms"]
    assert "expres" in activity_metadata["query_profile"]["relation_variant_terms"]
    assert not {
        "camping",
        "family",
        "kid",
        "paint",
        "photo",
        "pottery",
        "run",
        "swim",
        "violin",
    }.intersection(activity_metadata["query_profile"]["relation_variant_terms"])
    assert not {
        "camping",
        "painting",
        "pottery",
        "swimming",
        "violin",
    }.intersection(
        activity_metadata["query_profile"]["relation_category_terms"]["activity"]
    )
    assert camp_queries[2] == "melanie camp camping family unplug connection close"
    assert "camp" in camp_metadata["query_profile"]["relation_terms"]
    assert "family" in camp_metadata["query_profile"]["relation_variant_terms"]
    assert "unplug" in camp_metadata["query_profile"]["relation_variant_terms"]
    assert not {"beach", "mountains", "forest"}.intersection(
        camp_metadata["query_profile"]["relation_variant_terms"]
    )
    assert kids_queries[2] == "melanie kid like animal exhibit learning family"
    assert "kid" in kids_metadata["query_profile"]["relation_terms"]
    assert "animal" in kids_metadata["query_profile"]["relation_variant_terms"]
    assert "exhibit" in kids_metadata["query_profile"]["relation_variant_terms"]
    assert "preference" in kids_metadata["query_profile"]["relation_variant_terms"]
    assert not {"bone", "dinosaur", "nature", "stoked"}.intersection(
        kids_metadata["query_profile"]["relation_variant_terms"]
    )
    assert adoption_queries[2] == "caroline adoption support help folks individual agency"
    assert "adoption" in adoption_metadata["query_profile"]["relation_terms"]
    assert adoption_metadata["query_profile"]["evidence_need"] == ("single_fact",)
    assert adoption_metadata["query_profile"]["bundle_evidence_roles"] == ("primary",)
    assert "individual" in adoption_metadata["query_profile"]["relation_terms"]
    assert "people" in adoption_metadata["query_profile"]["relation_variant_terms"]
    assert not {"inclusive", "inclusivity", "lgbtq"}.intersection(
        adoption_metadata["query_profile"]["relation_variant_terms"]
    )
    assert adoption_choice_queries[2] == (
        "caroline adoption chose reason cause fit value"
    )
    assert adoption_choice_queries[3] == (
        "caroline adoption chose reason cause fit value because decision"
    )
    assert adoption_choice_metadata["query_plan"]["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "causal_support",
        "multi_hop_bridge",
    ]
    assert "causal_support" in adoption_choice_metadata["query_profile"][
        "evidence_need"
    ]
    assert "causal_support" in adoption_choice_metadata["query_profile"][
        "bundle_evidence_roles"
    ]
    assert "choose" in adoption_choice_metadata["query_profile"]["relation_terms"]
    assert not {"inclusivity", "support", "lgbtq"}.intersection(
        adoption_choice_metadata["query_profile"]["relation_variant_terms"]
    )
    adoption_choice_integrity = query_integrity_diagnostics(
        adoption_choice_case,
        BackendSearchResult(
            query=adoption_choice_case.question,
            memories=(),
            metadata={"query_decomposition": adoption_choice_metadata},
        ),
    )
    assert adoption_choice_integrity["expected_answer_query_overlap_terms"] == []
    assert adoption_process_queries[2] == (
        "caroline excite make create thrilled process adoption"
    )
    assert not {"family", "kid", "lgbtq"}.intersection(
        adoption_process_metadata["query_profile"]["relation_variant_terms"]
    )
    assert "make" in adoption_process_metadata["query_profile"][
        "relation_variant_terms"
    ]
    assert adoption_decision_queries[2] == (
        "melanie caroline think reaction response opinion feel decision"
    )
    assert "decision" in adoption_decision_metadata["query_profile"]["relation_terms"]
    assert "reaction" in adoption_decision_metadata["query_profile"][
        "relation_variant_terms"
    ]
    assert not {"amazing", "awesome", "family", "lovely", "luck", "mom"}.intersection(
        adoption_decision_metadata["query_profile"]["relation_variant_terms"]
    )
    assert song_queries[2] == "melanie enjoy song fan piece composer instrumental"
    assert "song" in song_metadata["query_profile"]["relation_terms"]
    assert "composer" in song_metadata["query_profile"]["relation_variant_terms"]
    assert not {"classical", "music"}.intersection(
        song_metadata["query_profile"]["relation_variant_terms"]
    )
    assert necklace_queries[2] == "caroline necklace symbolize symbol mean gift reminder"
    assert "necklace" in necklace_metadata["query_profile"]["relation_terms"]
    assert necklace_metadata["query_profile"]["relation_categories"] == (
        "symbolic_meaning",
    )
    assert "symbolic_meaning" in necklace_metadata["query_profile"]["evidence_need"]
    assert "symbolic_meaning_support" in necklace_metadata["query_profile"][
        "bundle_evidence_roles"
    ]
    assert necklace_metadata["query_profile"]["relation_category_terms"][
        "symbolic_meaning"
    ] == (
        "necklace",
        "symbolize",
        "symbol",
        "mean",
        "represent",
        "message",
        "value",
        "gift",
        "reminder",
        "family",
        "support",
        "special",
    )
    assert "symbol" in necklace_metadata["query_profile"]["relation_variant_terms"]
    assert "gift" in necklace_metadata["query_profile"]["relation_variant_terms"]
    assert "reminder" in necklace_metadata["query_profile"]["relation_variant_terms"]
    assert not {"faith", "grandma", "love", "root", "roots", "strength"}.intersection(
        necklace_metadata["query_profile"]["relation_variant_terms"]
    )
    assert summer_plan_queries[2] == "caroline plan summer future upcoming season goal"
    assert "summer" in summer_plan_metadata["query_profile"]["relation_terms"]
    assert "future" in summer_plan_metadata["query_profile"]["relation_variant_terms"]
    assert not {
        "adoption",
        "agencies",
        "dream",
        "family",
        "home",
        "lov",
        "researching",
    }.intersection(
        summer_plan_metadata["query_profile"]["relation_variant_terms"]
    )
    assert self_care_queries[2] == (
        "melanie prioritize self-care routine refreshes present balance rest relax"
    )
    assert self_care_queries[3] == (
        "melanie prioritize self-care routine refreshes present balance process support"
    )
    assert "prioritize" in self_care_metadata["query_profile"]["relation_terms"]
    assert "self-care" in self_care_metadata["query_profile"]["relation_terms"]
    assert "refresh" in self_care_metadata["query_profile"]["relation_variant_terms"]
    assert "present" in self_care_metadata["query_profile"]["relation_variant_terms"]
    assert not {"me-time", "running", "violin"}.intersection(
        self_care_metadata["query_profile"]["relation_variant_terms"]
    )


def test_query_decomposition_keeps_activity_answer_terms_out_of_typed_intent() -> None:
    case = _case(
        case_id="conv-26:qa:16",
        question="What activities does Melanie partake in?",
        expected_terms=("pottery", "camping", "painting", "swimming"),
        answer="pottery, camping, painting, swimming",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    integrity = query_integrity_diagnostics(
        case,
        BackendSearchResult(
            query=case.question,
            memories=(),
            metadata={"query_decomposition": metadata},
        ),
    )

    assert queries[2] == "melanie activity hobby partake class creative fun express refresh"
    assert integrity["expected_answer_query_overlap_terms"] == []
    assert integrity["expected_answer_query_profile_overlap_terms"] == []
    assert integrity["expected_answer_retrieval_intent_overlap_terms"] == []


def test_query_decomposition_keeps_topic_entities_out_of_speakers() -> None:
    books_case = _case(
        case_id="conv-26:qa:23",
        question="Would Caroline likely have Dr. Seuss books on her bookshelf?",
        expected_terms=("classic children's books",),
        answer="yes",
    )
    song_case = _case(
        case_id="conv-26:qa:65",
        question='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        expected_terms=("classical music",),
        answer="yes",
    )

    books_query, books_metadata = rerank_module.expanded_search_query(books_case)
    song_query, song_metadata = rerank_module.expanded_search_query(song_case)

    assert "entities: caroline, dr seuss" in books_query
    assert "speakers: caroline:" in books_query
    assert "speakers: caroline:, dr seuss:" not in books_query
    assert books_metadata["query_profile"]["entity_surfaces"] == (
        "caroline",
        "dr seuss",
    )
    assert books_metadata["query_profile"]["speaker_surfaces"] == ("caroline",)
    _, book_signals = rerank_module._benchmark_rerank_boost(
        RetrievedMemory(
            text="D1:1 Morgan: Dr. Seuss books were on the bookshelf.",
            rank=1,
        ),
        books_metadata["query_profile"],
    )
    assert book_signals["candidate_features"]["entity_hits"] == ["dr seuss"]
    assert "entities: melanie, four, seasons, vivaldi" in song_query
    assert "speakers: melanie:" in song_query
    assert "speakers: melanie:, four:, seasons:, vivaldi:" not in song_query
    assert song_metadata["query_profile"]["speaker_surfaces"] == ("melanie",)


def test_query_decomposition_expands_temporal_action_queries() -> None:
    support_group_case = _case(
        case_id="conv-26:qa:1",
        question="When did Caroline go to the LGBTQ support group?",
        expected_terms=("7 May 2023",),
        answer="7 May 2023",
        category=2,
    )
    generic_support_group_case = _case(
        case_id="conv-26:qa:generic-support-group",
        question="When did Caroline go to the support group?",
        expected_terms=("7 May 2023",),
        answer="7 May 2023",
        category=2,
    )
    move_case = _case(
        case_id="conv-26:qa:12",
        question="Where did Caroline move from 4 years ago?",
        expected_terms=("Sweden",),
        answer="Sweden",
    )
    race_case = _case(
        case_id="conv-26:qa:6",
        question="When did Melanie run a charity race?",
        expected_terms=("Sunday before 25 May 2023",),
        answer="Sunday before 25 May 2023",
        category=2,
    )
    meeting_case = _case(
        case_id="conv-26:qa:10",
        question="When did Caroline meet up with her friends, family, and mentors?",
        expected_terms=("week before 9 June 2023",),
        answer="week before 9 June 2023",
        category=2,
    )
    speech_case = _case(
        case_id="conv-26:qa:9",
        question="When did Caroline give a speech at a school?",
        expected_terms=("week before 9 June 2023",),
        answer="week before 9 June 2023",
        category=2,
    )
    friend_duration_case = _case(
        case_id="conv-26:qa:11",
        question="How long has Caroline had her current group of friends for?",
        expected_terms=("4 years",),
        answer="4 years",
        category=2,
    )
    birthday_duration_case = _case(
        case_id="conv-26:qa:13",
        question="How long ago was Caroline's 18th birthday?",
        expected_terms=("10 years",),
        answer="10 years",
        category=2,
    )
    generic_birthday_case = _case(
        case_id="conv-26:qa:generic-birthday",
        question="When is Caroline's birthday?",
        expected_terms=("May",),
        answer="May",
        category=2,
    )
    pottery_case = _case(
        case_id="conv-26:qa:17",
        question="When did Melanie sign up for a pottery class?",
        expected_terms=("2 July 2023",),
        answer="2 July 2023",
        category=2,
    )
    sunrise_case = _case(
        case_id="conv-26:qa:2",
        question="When did Melanie paint a sunrise?",
        expected_terms=("2022",),
        answer="2022",
        category=2,
    )
    conference_case = _case(
        case_id="conv-26:qa:18",
        question="When is Caroline going to the transgender conference?",
        expected_terms=("July 2023",),
        answer="July 2023",
        category=2,
    )
    awareness_case = _case(
        case_id="conv-26:qa:83",
        question="What did the charity race raise awareness for?",
        expected_terms=("mental health",),
        answer="mental health",
        category=4,
    )
    realize_case = _case(
        case_id="conv-26:qa:84",
        question="What did Melanie realize after the charity race?",
        expected_terms=("self-care is important",),
        answer="self-care is important",
        category=4,
    )
    destress_case = _case(
        case_id="conv-26:qa:25",
        question="What does Melanie do to destress?",
        expected_terms=("running", "pottery"),
        answer="running and pottery",
    )

    support_group_queries, support_group_metadata = (
        rerank_module.decomposed_search_queries(support_group_case)
    )
    generic_support_group_queries, generic_support_group_metadata = (
        rerank_module.decomposed_search_queries(generic_support_group_case)
    )
    move_queries, move_metadata = rerank_module.decomposed_search_queries(move_case)
    race_queries, race_metadata = rerank_module.decomposed_search_queries(race_case)
    meeting_queries, meeting_metadata = rerank_module.decomposed_search_queries(
        meeting_case
    )
    speech_queries, speech_metadata = rerank_module.decomposed_search_queries(
        speech_case
    )
    friend_duration_queries, friend_duration_metadata = (
        rerank_module.decomposed_search_queries(friend_duration_case)
    )
    birthday_duration_queries, birthday_duration_metadata = (
        rerank_module.decomposed_search_queries(birthday_duration_case)
    )
    generic_birthday_queries, generic_birthday_metadata = (
        rerank_module.decomposed_search_queries(generic_birthday_case)
    )
    pottery_queries, pottery_metadata = rerank_module.decomposed_search_queries(
        pottery_case
    )
    sunrise_queries, sunrise_metadata = rerank_module.decomposed_search_queries(
        sunrise_case
    )
    conference_queries, conference_metadata = rerank_module.decomposed_search_queries(
        conference_case
    )
    awareness_queries, awareness_metadata = rerank_module.decomposed_search_queries(
        awareness_case
    )
    realize_queries, realize_metadata = rerank_module.decomposed_search_queries(
        realize_case
    )
    destress_queries, destress_metadata = rerank_module.decomposed_search_queries(
        destress_case
    )

    assert support_group_queries[1] == (
        "caroline support group go went lgbtq inclusive"
    )
    assert "go" in support_group_metadata["query_profile"]["relation_terms"]
    assert "went" in support_group_metadata["query_profile"]["relation_variant_terms"]
    assert generic_support_group_queries[1] == (
        "caroline support group go went help friend"
    )
    assert not {"lgbtq", "inclusive", "inclusivity"}.intersection(
        generic_support_group_metadata["query_profile"]["relation_variant_terms"]
    )
    assert move_queries[1] == "caroline move moved home country 4 year ago"
    assert "move" in move_metadata["query_profile"]["relation_terms"]
    assert "4" in move_metadata["query_profile"]["lexical_terms"]
    assert race_queries[1] == "melanie run charity race last ran fundraiser"
    assert "run" in race_metadata["query_profile"]["relation_terms"]
    assert "charity" in race_metadata["query_profile"]["relation_terms"]
    assert "marathon" not in race_metadata["query_profile"]["relation_variant_terms"]
    assert meeting_queries[1] == "caroline meet friend met family mentor gathering"
    assert "meet" in meeting_metadata["query_profile"]["relation_terms"]
    assert speech_queries[1] == "caroline give speech school event talk student"
    assert "speech" in speech_metadata["query_profile"]["relation_terms"]
    assert "event" in speech_metadata["query_profile"]["relation_variant_terms"]
    assert friend_duration_queries[1] == "caroline current group friend known year been"
    assert "current" in friend_duration_metadata["query_profile"]["relation_terms"]
    assert "known" in friend_duration_metadata["query_profile"]["relation_variant_terms"]
    assert "year" in friend_duration_metadata["query_profile"]["relation_variant_terms"]
    assert birthday_duration_queries[1] == "caroline birthday year ago born 18th age"
    assert "18th" in birthday_duration_metadata["query_profile"]["lexical_terms"]
    assert "birthday" in birthday_duration_metadata["query_profile"]["relation_terms"]
    assert generic_birthday_queries[1] == "caroline birthday year ago born age"
    assert "18th" not in generic_birthday_metadata["query_profile"]["lexical_terms"]
    assert "18th" not in generic_birthday_metadata["query_profile"][
        "relation_variant_terms"
    ]
    assert pottery_queries[1] == "melanie sign signed signup class pottery registered"
    assert "sign" in pottery_metadata["query_profile"]["relation_terms"]
    assert "pottery" in pottery_metadata["query_profile"]["lexical_terms"]
    assert "pottery" not in pottery_metadata["query_profile"]["relation_variant_terms"]
    assert sunrise_queries[1] == (
        "melanie paint sunrise painting when date time image caption"
    )
    assert "sunrise" in sunrise_metadata["query_profile"]["lexical_terms"]
    assert "paint" in sunrise_metadata["query_profile"]["relation_terms"]
    assert "sunrise" in sunrise_metadata["query_profile"]["relation_terms"]
    assert conference_queries[1] == (
        "caroline conference transgender going month event attend"
    )
    assert "conference" in conference_metadata["query_profile"]["relation_terms"]
    assert "transgender" in conference_metadata["query_profile"]["lexical_terms"]
    assert "transgender" not in conference_metadata["query_profile"][
        "relation_variant_terms"
    ]
    assert awareness_queries[2] == "charity race raising raised awareness fundraiser"
    assert "raise" in awareness_metadata["query_profile"]["relation_terms"]
    assert "race" in awareness_metadata["query_profile"]["relation_terms"]
    assert realize_queries[1] == "melanie realize lesson reflection thought event journey"
    assert "realize" in realize_metadata["query_profile"]["relation_terms"]
    assert "lesson" in realize_metadata["query_profile"]["relation_variant_terms"]
    assert not {"important", "self-care"}.intersection(
        realize_metadata["query_profile"]["relation_variant_terms"]
    )
    assert destress_queries[2] == (
        "melanie destress stress relax unwind class clear mind run therapy therapeutic"
    )
    assert not {"pottery", "running"}.intersection(
        destress_metadata["query_profile"]["relation_variant_terms"]
    )
    assert "destress" in destress_metadata["query_profile"]["relation_terms"]
    assert "run" in destress_metadata["query_profile"]["relation_variant_terms"]
    assert "class" in destress_metadata["query_profile"]["relation_variant_terms"]
    assert "therapy" in destress_metadata["query_profile"]["relation_variant_terms"]
    assert not {"headspace", "farther"}.intersection(
        destress_metadata["query_profile"]["relation_variant_terms"]
    )


def test_infinity_context_http_search_expands_temporal_action_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "signup" in payload["query"]:
            items = [
                {
                    "item_id": "pottery-date",
                    "item_type": "chunk",
                    "text": (
                        "D4:5 Melanie: I signed up for a pottery class "
                        "on 2 July 2023."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-pottery-date"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "melanie-distractor",
                    "item_type": "fact",
                    "text": "D4:1 Melanie mentioned her weekend plans.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-melanie-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:17",
        question="When did Melanie sign up for a pottery class?",
        expected_terms=("2 July 2023",),
        answer="2 July 2023",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "When did Melanie sign up for a pottery class?",
        "melanie sign signed signup class pottery registered",
        "melanie when session date time last today yesterday",
    ]
    assert result.memories[0].item_id == "pottery-date"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "sign" in query_profile["relation_terms"]
    assert "pottery" in query_profile["lexical_terms"]
    assert "pottery" not in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0


def test_infinity_context_http_search_boosts_standalone_year_evidence() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "paint sunrise" in payload["query"]:
            items = [
                {
                    "item_id": "sunrise-year",
                    "item_type": "chunk",
                    "text": "D1:4 Melanie: I painted a sunrise in 2022.",
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-sunrise-year"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "painting-distractor",
                    "item_type": "fact",
                    "text": "Melanie painted pottery at the studio.",
                    "score": 0.96,
                    "source_refs": [{"source_id": "memory-painting-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:2",
        question="When did Melanie paint a sunrise?",
        expected_terms=("2022",),
        answer="2022",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "When did Melanie paint a sunrise?",
        "melanie paint sunrise painting when date time image caption",
        "melanie paint sunrise image picture",
    ]
    assert result.memories[0].item_id == "sunrise-year"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "paint" in query_profile["relation_terms"]
    assert "sunrise" in query_profile["relation_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert "sunrise" in diagnostics["benchmark_query_overlap_terms"]


def test_infinity_context_http_search_expands_current_friend_duration_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "caroline current group friend known year been":
            items = [
                {
                    "item_id": "known-friends-duration",
                    "item_type": "chunk",
                    "text": (
                        "Caroline has known these friends for 4 years, "
                        "and they have been there through everything."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-known-friends"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "current-group-distractor",
                    "item_type": "fact",
                    "text": "Caroline mentioned a current group chat with friends.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-current-group"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:11",
        question="How long has Caroline had her current group of friends for?",
        expected_terms=("4 years",),
        answer="4 years",
        category=2,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "How long has Caroline had her current group of friends for?",
        "caroline current group friend known year been",
        "caroline how long session date time last today yesterday",
    ]
    assert result.memories[0].item_id == "known-friends-duration"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert query_profile["time_intent_kind"] == "duration"
    assert "current" in query_profile["relation_terms"]
    assert "known" in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0


def test_infinity_context_http_search_expands_contrast_support_queries() -> None:
    seen_payloads: list[dict[str, object]] = []
    contrast_query = (
        "caroline current career path different now ongoing previous before earlier"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == contrast_query:
            items = [
                {
                    "item_id": "career-contrast-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D8:4 Caroline used to think about one career path, "
                        "but now her current path is different and still "
                        "connected to work options."
                    ),
                    "score": 0.88,
                    "source_refs": [{"source_id": "D8:4"}],
                }
            ]
        elif payload["query"] == (
            "How is Caroline's current career path different from before?"
        ):
            items = [
                {
                    "item_id": "career-current-distractor",
                    "item_type": "fact",
                    "text": "Caroline mentioned her current career path briefly.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-current-career"}],
                }
            ]
        else:
            items = []
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:contrast",
        question="How is Caroline's current career path different from before?",
        expected_terms=("writing",),
        answer="writing",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=4)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "How is Caroline's current career path different from before?",
        "How is Caroline's current career path different from before?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: current, career, path, different, known, year, been, exist; "
        "temporal: before, session, date, time, last, today, yesterday, tomorrow",
        "caroline current career path different known year",
        contrast_query,
    ]
    assert result.metadata["query_roles"] == [
        "original_question",
        "expanded_focus",
        "compact_relation",
        "contrast_support",
    ]
    contrast_memory = next(
        memory
        for memory in result.memories
        if memory.item_id == "career-contrast-evidence"
    )
    diagnostics = contrast_memory.metadata["diagnostics"]
    assert diagnostics["benchmark_query_roles"] == ["contrast_support"]
    assert diagnostics["benchmark_candidate_fusion"]["query_roles"] == [
        "contrast_support"
    ]
    assert "writing" not in json.dumps(result.metadata["query_decomposition"])


def test_infinity_context_http_search_reranks_relation_only_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "charity race raising raised awareness fundraiser":
            items = [
                {
                    "item_id": "awareness-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D5:2 The charity race raised awareness for mental health."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-awareness"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "race-distractor",
                    "item_type": "fact",
                    "text": "The charity race registration email arrived.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-race-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:83",
        question="What did the charity race raise awareness for?",
        expected_terms=("mental health",),
        answer="mental health",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What did the charity race raise awareness for?",
        "What did the charity race raise awareness for?\n"
        "Search focus: actions: charity, race, raising, raised, awareness, "
        "fundraiser, raise, support",
        "charity race raising raised awareness fundraiser",
    ]
    assert result.memories[0].item_id == "awareness-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert query_profile["entities"] == ()
    assert "raise" in query_profile["relation_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_variant_hit_count"] > 0
    assert diagnostics["score_signals"]["benchmark_query_overlap_boost"] > 0


def test_infinity_context_http_search_expands_generic_activity_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == (
            "melanie activity hobby partake class creative fun express refresh"
        ):
            items = [
                {
                    "item_id": "creative-activity-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D5:4 Melanie: This class is a fun way to express "
                        "myself and get creative."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-creative-activity"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "activity-distractor",
                    "item_type": "fact",
                    "text": "Melanie asked about activities on Caroline's calendar.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-activity-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:16",
        question="What activities does Melanie partake in?",
        expected_terms=("pottery", "camping", "painting", "swimming"),
        answer="pottery, camping, painting, swimming",
        category=1,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What activities does Melanie partake in?",
        "What activities does Melanie partake in?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: activity, hobby, partake, class, creative, fun, express, refresh",
        "melanie activity hobby partake class creative fun express refresh",
    ]
    assert result.memories[0].item_id == "creative-activity-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "activity" in query_profile["relation_terms"]
    assert "class" in query_profile["relation_variant_terms"]
    assert "creative" in query_profile["relation_variant_terms"]
    assert "expres" in query_profile["relation_variant_terms"]
    assert not {"camping", "paint", "pottery", "run", "swim", "violin"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_variant_hit_count"] >= 3


def test_infinity_context_http_search_expands_camping_place_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "melanie camp camping family unplug connection close":
            items = [
                {
                    "item_id": "camping-context-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D6:16 Melanie: Camping with my family helps us "
                        "unplug, feel close, and build connection."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-camping-context"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "camping-distractor",
                    "item_type": "fact",
                    "text": "Melanie checked the tent site for camp registration.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-camping-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:19",
        question="Where has Melanie camped?",
        expected_terms=("beach", "mountains", "forest"),
        answer="beach, mountains, forest",
        category=1,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "Where has Melanie camped?",
        "Where has Melanie camped?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: camp, camping, family, unplug, connection, close, outdoor, trip",
        "melanie camp camping family unplug connection close",
    ]
    assert result.memories[0].item_id == "camping-context-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "camp" in query_profile["relation_terms"]
    assert "family" in query_profile["relation_variant_terms"]
    assert "unplug" in query_profile["relation_variant_terms"]
    assert not {"beach", "mountains", "forest"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_strong_relation_evidence"] is True


def test_infinity_context_http_search_expands_destress_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == (
            "melanie destress stress relax unwind class clear mind run therapy therapeutic"
        ):
            items = [
                {
                    "item_id": "clear-mind-destress-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D7:22 Melanie: It is a way to de-stress, clear "
                        "my mind, and help my headspace."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-clear-mind-destress"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "destress-distractor",
                    "item_type": "fact",
                    "text": "Melanie mentioned stress while talking to Caroline.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-destress-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:25",
        question="What does Melanie do to destress?",
        expected_terms=("running", "pottery"),
        answer="running and pottery",
        category=1,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What does Melanie do to destress?",
        "What does Melanie do to destress?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: destress, stress, relax, unwind, class, clear, mind, run",
        "melanie destress stress relax unwind class clear mind run therapy therapeutic",
    ]
    assert result.memories[0].item_id == "clear-mind-destress-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "destress" in query_profile["relation_terms"]
    assert "run" in query_profile["relation_variant_terms"]
    assert "class" in query_profile["relation_variant_terms"]
    assert not {"headspace", "farther"}.intersection(
        query_profile["relation_variant_terms"]
    )
    assert not {"pottery", "running"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_variant_hit_count"] >= 2
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0


def test_infinity_context_http_search_expands_self_care_prioritization() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == (
            "melanie prioritize self-care routine refreshes present balance rest relax"
        ):
            items = [
                {
                    "item_id": "self-care-refresh-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D2:5 Melanie: This routine refreshes me and helps "
                        "me stay present for my family."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-self-care-refresh"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "self-care-distractor",
                    "item_type": "fact",
                    "text": "Melanie agreed that self-care can be important.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-self-care-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:85",
        question="How does Melanie prioritize self-care?",
        expected_terms=("me-time", "running", "violin"),
        answer="me-time with running and violin",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "How does Melanie prioritize self-care?",
        "How does Melanie prioritize self-care?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: prioritize, self-care, routine, refreshes, present, balance, "
        "rest, relax; multi-hop markers: how",
        "melanie prioritize self-care routine refreshes present balance rest relax",
        "melanie prioritize self-care routine refreshes present balance process support",
    ]
    assert result.memories[0].item_id == "self-care-refresh-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "prioritize" in query_profile["relation_terms"]
    assert "refresh" in query_profile["relation_variant_terms"]
    assert "present" in query_profile["relation_variant_terms"]
    assert not {"me-time", "running", "reading", "violin"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_preference_evidence_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_variant_hit_count"] >= 3
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0


def test_infinity_context_http_search_expands_realize_after_race_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "lesson" in payload["query"] and "reflection" in payload["query"]:
            items = [
                {
                    "item_id": "self-care-realization",
                    "item_type": "chunk",
                    "text": (
                        "D5:3 Melanie: My lesson and reflection after the "
                        "charity race is that self-care is important."
                    ),
                    "score": 0.86,
                    "source_refs": [{"source_id": "memory-self-care"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "race-distractor",
                    "item_type": "fact",
                    "text": "Melanie registered for a charity race.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-race-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:84",
        question="What did Melanie realize after the charity race?",
        expected_terms=("self-care is important",),
        answer="self-care is important",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What did Melanie realize after the charity race?",
        "melanie realize lesson reflection thought event journey",
        "melanie after session date time last today yesterday",
    ]
    assert result.memories[0].item_id == "self-care-realization"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "realize" in query_profile["relation_terms"]
    assert "charity" in query_profile["relation_terms"]
    assert "lesson" in query_profile["relation_variant_terms"]
    assert not {"important", "self-care"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_direct_speaker_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_query_overlap_boost"] > 0


def test_infinity_context_http_search_expands_roadtrip_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "melanie roadtrip trip road weekend past soon":
            items = [
                {
                    "item_id": "roadtrip-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D18:1 Melanie: The roadtrip involved her son getting "
                        "into an accident, but the family was safe."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-roadtrip"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "melanie-distractor",
                    "item_type": "fact",
                    "text": "Melanie talked about her weekend plans.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-melanie-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:78",
        question="Would Melanie go on another roadtrip soon?",
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "Would Melanie go on another roadtrip soon?",
        "Would Melanie go on another roadtrip soon?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: roadtrip, trip, road, weekend, past, soon, another, travel",
        "melanie roadtrip trip road weekend past soon",
    ]
    assert result.memories[0].item_id == "roadtrip-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "roadtrip" in query_profile["relation_terms"]
    assert "travel" in query_profile["relation_variant_terms"]
    assert not {"accident", "son", "family", "safe"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_roadtrip_incident_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_strong_relation_evidence"] is False


def test_infinity_context_http_search_expands_counterfactual_support_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "caroline want counsel support got help growing":
            items = [
                {
                    "item_id": "received-support-evidence",
                    "item_type": "chunk",
                    "text": (
                        "Caroline received support growing up, and that journey "
                        "made her want to pursue counseling."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-received-support"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "career-distractor",
                    "item_type": "fact",
                    "text": "Caroline mentioned counseling as a possible career.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-career-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:15",
        question=(
            "Would Caroline still want to pursue counseling as a career "
            "if she hadn't received support growing up?"
        ),
        expected_terms=("likely no",),
        answer="likely no",
        category=3,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "Would Caroline still want to pursue counseling as a career "
        "if she hadn't received support growing up?",
        "Would Caroline still want to pursue counseling as a career "
        "if she hadn't received support growing up?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: want, counsel, support, got, help, growing, journey, pursue",
        "caroline want counsel support got help growing",
    ]
    assert result.memories[0].item_id == "received-support-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "receive" in query_profile["relation_terms"]
    assert "grow" in query_profile["relation_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_coverage_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_strong_relation_evidence"] is True


def test_infinity_context_http_search_expands_identity_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "caroline identity support inspiring story gender accepted":
            items = [
                {
                    "item_id": "identity-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D1:5 Caroline: The stories were inspiring and I was "
                        "thankful for the support. D1:7 Caroline: The group "
                        "made me feel accepted and gave me courage to embrace "
                        "my gender identity."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-identity"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "caroline-distractor",
                    "item_type": "fact",
                    "text": "Caroline mentioned her background during the conversation.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-caroline-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:5",
        question="What is Caroline's identity?",
        expected_terms=("transgender woman",),
        answer="transgender woman",
        category=1,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What is Caroline's identity?",
        "What is Caroline's identity?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: identity, support, inspiring, story, gender, accepted, courage, embrace",
        "caroline identity support inspiring story gender accepted",
    ]
    assert result.memories[0].item_id == "identity-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "identity" in query_profile["relation_terms"]
    assert "pride" in query_profile["relation_variant_terms"]
    assert "support" in query_profile["relation_variant_terms"]
    assert "inspir" in query_profile["relation_variant_terms"]
    assert "accept" in query_profile["relation_variant_terms"]
    assert not {"transgender", "woman"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"][
        "benchmark_direct_speaker_relation_evidence"
    ] is True


def test_infinity_context_http_search_expands_political_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "caroline political rights lgbtq support accepted belief":
            items = [
                {
                    "item_id": "political-evidence",
                    "item_type": "chunk",
                    "text": (
                        "Caroline was upset by a conservative comment about "
                        "her transition and said there is work to do for LGBTQ rights. "
                        "She relies on people who accept and support her."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-political"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "belief-distractor",
                    "item_type": "fact",
                    "text": "Caroline shared a personal belief and value.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-belief-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:51",
        question="What would Caroline's political leaning likely be?",
        expected_terms=("liberal",),
        answer="liberal",
        category=3,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What would Caroline's political leaning likely be?",
        "What would Caroline's political leaning likely be?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: political, rights, lgbtq, support, accepted, belief, view, value",
        "caroline political rights lgbtq support accepted belief",
    ]
    assert result.memories[0].item_id == "political-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "political" in query_profile["relation_terms"]
    assert "right" in query_profile["relation_variant_terms"]
    assert not {"conservative", "transition", "comment", "hike"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_strong_relation_evidence"] is True


def test_infinity_context_http_search_expands_personality_trait_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "melanie caroline personality trait care real concern thank":
            items = [
                {
                    "item_id": "personality-evidence",
                    "item_type": "chunk",
                    "text": (
                        "Melanie thanked Caroline for her concern and said "
                        "Caroline really cares about being real."
                    ),
                    "score": 0.84,
                    "source_refs": [{"source_id": "memory-personality"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "name-distractor",
                    "item_type": "fact",
                    "text": "Melanie and Caroline talked about plans for the week.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-name-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:70",
        question="What personality traits might Melanie say Caroline has?",
        expected_terms=("thoughtful",),
        answer="thoughtful, authentic, driven",
        category=3,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What personality traits might Melanie say Caroline has?",
        "What personality traits might Melanie say Caroline has?\n"
        "Search focus: entities: melanie, caroline; speakers: melanie:, caroline:; "
        "actions: personality, trait, care, real, concern, thank, help, drive",
        "melanie caroline personality trait care real concern thank",
    ]
    assert result.memories[0].item_id == "personality-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "personality" in query_profile["relation_terms"]
    assert "concern" in query_profile["relation_variant_terms"]
    assert "thank" in query_profile["relation_variant_terms"]
    assert "care" in query_profile["relation_variant_terms"]
    assert "drive" in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_coverage_boost"] > 0


def test_infinity_context_http_search_expands_relationship_status_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "parent" in payload["query"] and "breakup" in payload["query"]:
            items = [
                {
                    "item_id": "relationship-status",
                    "item_type": "chunk",
                    "text": (
                        "D2:14 Caroline: Family will be a challenge as a parent. "
                        "D3:13 Caroline: Friends supported me after a tough breakup."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-relationship"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "entity-distractor",
                    "item_type": "fact",
                    "text": "Morgan said Caroline wrote a postcard.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-entity-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:8",
        question="What is Caroline's relationship status?",
        expected_terms=("single",),
        answer="single",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What is Caroline's relationship status?",
        "What is Caroline's relationship status?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: parent, breakup, family, kid, friend, support, challenge, dating",
        "caroline parent breakup family kid friend support",
    ]
    assert result.memories[0].item_id == "relationship-status"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "relationship" in query_profile["relation_terms"]
    assert "status" in query_profile["relation_terms"]
    assert "family" in query_profile["relation_variant_terms"]
    assert "single" not in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert (
        diagnostics["score_signals"]["benchmark_relationship_status_context_boost"]
        > 0
    )


def test_infinity_context_http_search_expands_preference_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if payload["query"] == "melanie interest park camping trip story sky":
            items = [
                {
                    "item_id": "outdoor-evidence",
                    "item_type": "chunk",
                    "text": (
                        "D10:12 Melanie: The camping trip includes marshmallows, "
                        "stories around the campfire, and a meteor shower."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-outdoor"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "theme-park-distractor",
                    "item_type": "fact",
                    "text": "Morgan said Melanie walked past a theme park sign.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-theme-park"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:43",
        question=(
            "Would Melanie be more interested in going to a national park "
            "or a theme park?"
        ),
        expected_terms=("national park",),
        answer="national park",
        category=3,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "Would Melanie be more interested in going to a national park "
        "or a theme park?",
        "Would Melanie be more interested in going to a national park "
        "or a theme park?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: interest, park, camping, trip, story, sky, summer, enjoy",
        "melanie interest park camping trip story sky",
    ]
    assert result.memories[0].item_id == "outdoor-evidence"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert query_profile["entities"] == ("melanie",)
    assert "preference" in query_profile["relation_categories"]
    assert "interest" in query_profile["relation_terms"]
    assert "park" in query_profile["relation_terms"]
    assert "camping" in query_profile["relation_variant_terms"]
    assert not {"campfire", "marshmallow", "meteor"}.intersection(
        query_profile["relation_variant_terms"]
    )
    assert "outdoor" in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_preference_evidence_boost"] > 0


def test_query_decomposition_reports_exchange_relation_intent() -> None:
    case = _case(
        case_id="exchange-query",
        question="What items has Melanie bought?",
        expected_terms=("keepsake",),
        answer="keepsake",
        category=1,
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]
    exchange_intent = metadata["retrieval_intent"]["relations"]["intents"][0]

    assert queries == (
        "What items has Melanie bought?",
        "What items has Melanie bought?\n"
        "Search focus: entities: melanie; speakers: melanie:; "
        "actions: bought, got, purchased, buy, purchas",
        "melanie bought got purchased buy purchas",
    )
    assert metadata["query_plan"]["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "exchange_support",
    ]
    assert metadata["query_plan"]["selected_role_families"] == [
        "base_query",
        "expanded_focus",
        "relation_compact",
    ]
    assert query_profile["relation_categories"] == ("exchange",)
    assert query_profile["relation_category_terms"]["exchange"] == (
        "bought",
        "buy",
        "purchas",
        "got",
    )
    assert query_profile["evidence_need"] == ("exchange",)
    assert query_profile["bundle_evidence_roles"] == (
        "primary",
        "bridge",
        "exchange_support",
    )
    assert exchange_intent["category"] == "exchange"
    assert exchange_intent["evidence_need"] == "exchange"
    assert exchange_intent["reason_codes"] == [
        "category:exchange",
        "relation_terms",
        "relation_variants",
    ]


def test_benchmark_rerank_boosts_focused_exchange_evidence() -> None:
    case = _case(
        case_id="exchange-rerank",
        question="What items has Melanie bought?",
        expected_terms=("keepsake",),
        answer="keepsake",
        category=1,
    )
    broad_context = RetrievedMemory(
        item_id="broad-context",
        rank=1,
        score=0.2,
        text=(
            "session_19 date: 9:10 pm D19:1 Caroline: Melanie mentioned "
            "family love and playful pets during the conversation."
        ),
    )
    exchange_turn = RetrievedMemory(
        item_id="exchange-turn",
        rank=2,
        score=0.0,
        text=(
            "session_19 turn D19:2 date: 9:11 pm "
            "D19:2 Melanie: I bought a small keepsake yesterday and got it "
            "after the fair."
        ),
        source_refs=("D19:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (broad_context, exchange_turn),
    )

    assert metadata["applied"] is True
    assert reranked[0].item_id == "exchange-turn"
    diagnostics = reranked[0].metadata["diagnostics"]
    assert diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["exchange"]
    assert "exchange_evidence" in diagnostics["benchmark_candidate_features"][
        "answerability_reason_codes"
    ]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert (
        diagnostics["score_signals"]["benchmark_relation_category_coverage_boost"]
        > 0
    )


def test_query_decomposition_reports_communication_relation_intent() -> None:
    tell_case = _case(
        case_id="communication-tell",
        question="Who did Alex tell about the Project Atlas delay?",
        expected_terms=("maria",),
        answer="Maria",
        category=1,
    )
    ask_case = _case(
        case_id="communication-ask",
        question="Who was asked to send the Project Atlas invoice by Alex?",
        expected_terms=("maria",),
        answer="Maria",
        category=1,
    )
    recommend_case = _case(
        case_id="communication-recommend",
        question="Who recommended that Melanie read Becoming Nicole?",
        expected_terms=("caroline",),
        answer="Caroline",
        category=1,
    )

    tell_queries, tell_metadata = rerank_module.decomposed_search_queries(tell_case)
    ask_queries, ask_metadata = rerank_module.decomposed_search_queries(ask_case)
    recommend_queries, recommend_metadata = rerank_module.decomposed_search_queries(
        recommend_case
    )

    assert tell_metadata["query_profile"]["relation_categories"] == (
        "communication",
    )
    assert tell_metadata["query_profile"]["relation_category_terms"][
        "communication"
    ] == ("tell", "told", "mention")
    assert "communication" in tell_metadata["query_profile"]["evidence_need"]
    assert (
        "communication_support"
        in tell_metadata["query_profile"]["bundle_evidence_roles"]
    )
    assert tell_queries[1].endswith("actions: tell, told, mention, delay")
    assert tell_queries[2] == "alex project atlas tell told mention delay"
    assert "maria" not in " ".join(tell_queries).casefold()
    assert ask_metadata["query_profile"]["relation_terms"] == ("ask",)
    assert ask_metadata["query_profile"]["relation_categories"] == (
        "communication",
    )
    assert "request" in ask_metadata["query_profile"]["relation_category_terms"][
        "communication"
    ]
    assert ask_queries[1].endswith("actions: ask, request, send, invoice, asked")
    assert ask_queries[2] == "project atlas alex ask request send invoice asked"
    assert "maria" not in " ".join(ask_queries).casefold()
    assert recommend_metadata["query_profile"]["relation_categories"] == (
        "activity",
        "communication",
    )
    assert recommend_metadata["query_profile"]["relation_category_terms"][
        "communication"
    ] == ("recommend", "suggest", "advis", "told")
    assert recommend_queries[1].endswith(
        "actions: recommend, read, suggest, advis, told, book, recommended, "
        "suggested"
    )
    assert recommend_queries[2] == (
        "melanie becoming nicole recommend read suggest advis told book recommended "
        "suggested"
    )
    assert "caroline" not in " ".join(recommend_queries).casefold()


def test_query_decomposition_does_not_promote_plain_mention_lookup_to_communication() -> None:
    case = _case(
        case_id="communication-plain-mention",
        question="What status did Morgan mention?",
        expected_terms=("current status",),
        answer="current status",
        category=4,
    )

    _, metadata = rerank_module.decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert "mention" in profile["relation_terms"]
    assert "communication" not in profile["relation_categories"]
    assert "communication" not in profile["evidence_need"]
    assert "communication_support" not in profile["bundle_evidence_roles"]


def test_query_decomposition_reports_registration_event_intent() -> None:
    register_case = _case(
        case_id="registration-query-register",
        question="When did Melanie register for a class?",
        expected_terms=("Friday",),
        answer="Friday",
        category=2,
    )
    enroll_case = _case(
        case_id="registration-query-enroll",
        question="What class did Melanie enroll in?",
        expected_terms=("workshop",),
        answer="workshop",
        category=4,
    )

    register_queries, register_metadata = rerank_module.decomposed_search_queries(
        register_case
    )
    enroll_queries, enroll_metadata = rerank_module.decomposed_search_queries(
        enroll_case
    )

    assert register_queries == (
        "When did Melanie register for a class?",
        "melanie registered signed signup class registration",
        "melanie when session date time last today yesterday",
    )
    register_profile = register_metadata["query_profile"]
    assert register_profile["relation_terms"] == ("register",)
    assert register_profile["relation_categories"] == (
        "registration_event",
        "temporal",
    )
    assert register_profile["relation_category_terms"]["registration_event"] == (
        "register",
        "registration",
        "signup",
        "class",
        "course",
        "lesson",
        "workshop",
    )
    assert register_metadata["retrieval_intent"]["relations"]["intents"][0][
        "evidence_need"
    ] == "registration_event"
    assert "registration_event" in register_profile["evidence_need"]
    assert "event_support" in register_profile["bundle_evidence_roles"]
    assert "Friday" not in json.dumps(register_metadata["retrieval_intent"])

    assert enroll_queries[1].endswith(
        "actions: enroll, signed, signup, class, registered, registration, "
        "enrolled, course"
    )
    assert enroll_queries[2] == (
        "melanie enroll signed signup class registered registration"
    )
    enroll_profile = enroll_metadata["query_profile"]
    assert enroll_profile["relation_terms"] == ("enroll",)
    assert enroll_profile["relation_categories"] == ("registration_event",)
    assert "registration_event" in enroll_profile["evidence_need"]
    assert "event_support" in enroll_profile["bundle_evidence_roles"]
    assert "register" in enroll_profile["relation_variant_terms"]
    assert "workshop" in enroll_profile["relation_variant_terms"]


def test_benchmark_rerank_boosts_registration_event_evidence() -> None:
    case = _case(
        case_id="registration-rerank",
        question="When did Melanie register for a class?",
        expected_terms=("Friday",),
        answer="Friday",
        category=2,
    )
    sign_distractor = RetrievedMemory(
        item_id="sign-distractor",
        rank=1,
        score=0.1,
        text=(
            "session_1 turn D1:2 date: 9:00 am "
            "D1:2 Morgan: Melanie noticed a sign near the studio door."
        ),
        source_refs=("D1:2",),
    )
    registration_evidence = RetrievedMemory(
        item_id="registration-evidence",
        rank=2,
        score=0.0,
        text=(
            "session_4 turn D4:5 date: 6:00 pm "
            "D4:5 Melanie: I registered for the class last Friday after "
            "checking the schedule."
        ),
        source_refs=("D4:5",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (sign_distractor, registration_evidence),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "registration-evidence",
        "sign-distractor",
    ]
    evidence_diagnostics = reranked[0].metadata["diagnostics"]
    distractor_diagnostics = reranked[1].metadata["diagnostics"]
    assert "registration_event" in evidence_diagnostics[
        "benchmark_candidate_features"
    ]["relation_category_hits"]
    assert (
        evidence_diagnostics["score_signals"]["benchmark_registration_event_boost"]
        > 0
    )
    assert (
        distractor_diagnostics["score_signals"]["benchmark_registration_event_boost"]
        == 0
    )


def test_query_decomposition_reports_participation_event_intent() -> None:
    visit_case = _case(
        case_id="participation-query-visit",
        question="When did Morgan visit the studio?",
        expected_terms=("yesterday",),
        answer="yesterday",
        category=2,
    )
    participate_case = _case(
        case_id="participation-query-participate",
        question="What event did Morgan participate in?",
        expected_terms=("meetup",),
        answer="meetup",
        category=4,
    )

    visit_queries, visit_metadata = rerank_module.decomposed_search_queries(visit_case)
    participate_queries, participate_metadata = (
        rerank_module.decomposed_search_queries(participate_case)
    )

    assert visit_queries == (
        "When did Morgan visit the studio?",
        "morgan visit visited studio place trip event",
        "morgan when session date time last today yesterday",
    )
    visit_profile = visit_metadata["query_profile"]
    assert visit_profile["relation_terms"] == ("visit",)
    assert visit_profile["relation_categories"] == (
        "participation_event",
        "temporal",
    )
    assert visit_profile["relation_category_terms"]["participation_event"] == (
        "visit",
        "trip",
        "studio",
        "place",
        "event",
    )
    assert "participation_event" in visit_profile["evidence_need"]
    assert "event_support" in visit_profile["bundle_evidence_roles"]
    assert "yesterday" not in json.dumps(visit_metadata["retrieval_intent"])

    assert participate_queries[2] == (
        "morgan participate participated event group class workshop"
    )
    participate_profile = participate_metadata["query_profile"]
    assert participate_profile["relation_terms"] == ("participate",)
    assert participate_profile["relation_categories"] == ("participation_event",)
    assert "participation_event" in participate_profile["evidence_need"]
    assert "event_support" in participate_profile["bundle_evidence_roles"]
    assert "meetup" not in json.dumps(participate_metadata["retrieval_intent"])


def test_query_decomposition_reports_emotion_response_intent() -> None:
    feel_case = _case(
        case_id="emotion-response-query",
        question="How did Melanie feel about the adoption news?",
        expected_terms=("direct emotion",),
        answer="direct emotion",
        category=4,
    )
    excite_case = _case(
        case_id="emotion-excite-query",
        question="What is Caroline excited about in the adoption process?",
        expected_terms=("direct emotion",),
        answer="direct emotion",
        category=4,
    )

    feel_queries, feel_metadata = rerank_module.decomposed_search_queries(feel_case)
    excite_queries, excite_metadata = rerank_module.decomposed_search_queries(
        excite_case
    )

    assert feel_queries[2] == "melanie feel adoption felt reaction response excited"
    feel_profile = feel_metadata["query_profile"]
    assert "emotion_response" in feel_profile["relation_categories"]
    assert "emotion_response" in feel_profile["evidence_need"]
    assert "emotion_response_support" in feel_profile["bundle_evidence_roles"]
    assert feel_profile["relation_category_terms"]["emotion_response"] == (
        "feel",
        "felt",
        "reaction",
        "response",
        "nervous",
        "relieved",
        "proud",
        "worried",
        "upset",
    )
    assert "direct emotion" not in json.dumps(feel_metadata["retrieval_intent"])

    assert excite_queries[2] == "caroline excite make create thrilled process adoption"
    excite_profile = excite_metadata["query_profile"]
    assert "emotion_response" in excite_profile["relation_categories"]
    assert "emotion_response" in excite_profile["evidence_need"]
    assert "emotion_response_support" in excite_profile["bundle_evidence_roles"]
    assert excite_profile["relation_category_terms"]["emotion_response"] == (
        "excite",
        "enthusiastic",
    )


def test_benchmark_rerank_boosts_participation_event_evidence() -> None:
    case = _case(
        case_id="participation-rerank",
        question="When did Morgan visit the studio?",
        expected_terms=("yesterday",),
        answer="yesterday",
        category=2,
    )
    studio_topic = RetrievedMemory(
        item_id="studio-topic",
        rank=1,
        score=0.05,
        text=(
            "session_2 turn D2:1 date: 10:00 am "
            "D2:1 Morgan: I reviewed the studio schedule and equipment list."
        ),
        source_refs=("D2:1",),
    )
    visit_evidence = RetrievedMemory(
        item_id="visit-evidence",
        rank=2,
        score=0.0,
        text=(
            "session_5 turn D5:2 date: 8:00 pm "
            "D5:2 Morgan: I visited the studio yesterday and checked the setup."
        ),
        source_refs=("D5:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (studio_topic, visit_evidence),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "visit-evidence",
        "studio-topic",
    ]
    evidence_diagnostics = reranked[0].metadata["diagnostics"]
    topic_diagnostics = reranked[1].metadata["diagnostics"]
    assert "participation_event" in evidence_diagnostics[
        "benchmark_candidate_features"
    ]["relation_category_hits"]
    assert (
        evidence_diagnostics["score_signals"]["benchmark_participation_event_boost"]
        > 0
    )
    assert evidence_diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0
    assert (
        topic_diagnostics["score_signals"]["benchmark_participation_event_boost"]
        == 0
    )
    assert topic_diagnostics["score_signals"]["benchmark_temporal_text_boost"] == 0
    assert (
        topic_diagnostics["score_signals"]["benchmark_temporal_sequence_boost"] == 0
    )
    assert topic_diagnostics["score_signals"]["benchmark_typed_temporal_reason"] == (
        "missing_temporal_evidence"
    )


def test_benchmark_rerank_boosts_emotion_response_evidence() -> None:
    case = _case(
        case_id="emotion-response-rerank",
        question="How did Melanie feel about the adoption news?",
        expected_terms=("direct emotion",),
        answer="direct emotion",
        category=4,
    )
    topic_mention = RetrievedMemory(
        item_id="adoption-topic",
        rank=1,
        score=0.15,
        text=(
            "session_1 turn D1:1 date: 9:00 am "
            "D1:1 Melanie: The adoption process has several documents."
        ),
        source_refs=("D1:1",),
    )
    emotion_evidence = RetrievedMemory(
        item_id="emotion-evidence",
        rank=2,
        score=0.0,
        text=(
            "session_2 turn D2:4 date: 9:10 am "
            "D2:4 Melanie: My reaction to the adoption news was nervous "
            "but hopeful."
        ),
        source_refs=("D2:4",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (topic_mention, emotion_evidence),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "emotion-evidence",
        "adoption-topic",
    ]
    evidence_diagnostics = reranked[0].metadata["diagnostics"]
    topic_diagnostics = reranked[1].metadata["diagnostics"]
    assert "emotion_response" in evidence_diagnostics[
        "benchmark_candidate_features"
    ]["relation_category_hits"]
    assert (
        evidence_diagnostics["score_signals"]["benchmark_emotion_response_boost"]
        > 0
    )
    assert (
        topic_diagnostics["score_signals"]["benchmark_emotion_response_boost"] == 0
    )


def test_benchmark_rerank_boosts_symbolic_meaning_evidence() -> None:
    case = _case(
        case_id="symbolic-meaning-rerank",
        question="What does Caroline's necklace symbolize?",
        expected_terms=("keepsake",),
        answer="keepsake",
        category=4,
    )
    object_mention = RetrievedMemory(
        item_id="object-mention",
        rank=1,
        score=0.05,
        text=(
            "session_1 turn D1:1 date: 9:00 am "
            "D1:1 Caroline: I wore the necklace with my jacket."
        ),
        source_refs=("D1:1",),
    )
    meaning_evidence = RetrievedMemory(
        item_id="meaning-evidence",
        rank=2,
        score=0.0,
        text=(
            "session_2 turn D2:4 date: 9:10 am "
            "D2:4 Caroline: The necklace was a gift from grandma and "
            "represents my roots, a special reminder."
        ),
        source_refs=("D2:4",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (object_mention, meaning_evidence),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "meaning-evidence",
        "object-mention",
    ]
    evidence_diagnostics = reranked[0].metadata["diagnostics"]
    object_diagnostics = reranked[1].metadata["diagnostics"]
    assert evidence_diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["symbolic_meaning"]
    assert (
        evidence_diagnostics["score_signals"]["benchmark_symbolic_meaning_boost"]
        > 0
    )
    assert (
        object_diagnostics["score_signals"]["benchmark_symbolic_meaning_boost"]
        == 0
    )
    assert "missing_symbolic_meaning_evidence" in object_diagnostics[
        "benchmark_candidate_features"
    ]["answerability_reason_codes"]
    assert "missing_symbolic_meaning_evidence_cap" in object_diagnostics[
        "score_signals"
    ]["benchmark_provenance_safety_reason_codes"]
    assert "keepsake" not in json.dumps(metadata["retrieval_intent"])


def test_benchmark_rerank_boosts_speaker_grounded_communication_evidence() -> None:
    case = _case(
        case_id="communication-rerank",
        question="Who did Alex tell about the Project Atlas delay?",
        expected_terms=("maria",),
        answer="Maria",
        category=1,
    )
    recipient_turn = RetrievedMemory(
        item_id="recipient-turn",
        rank=1,
        score=0.2,
        text=(
            "session_3 turn D3:5 date: 9:20 pm "
            "D3:5 Maria: I told Alex about the Project Atlas delay after "
            "the invoice approval call."
        ),
        source_refs=("D3:5",),
    )
    speaker_turn = RetrievedMemory(
        item_id="speaker-turn",
        rank=2,
        score=0.0,
        text=(
            "session_2 turn D2:3 date: 9:10 pm "
            "D2:3 Alex: I told Maria about the Project Atlas delay after "
            "the invoice approval call."
        ),
        source_refs=("D2:3",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (recipient_turn, speaker_turn),
    )

    assert metadata["applied"] is True
    assert reranked[0].item_id == "speaker-turn"
    diagnostics = reranked[0].metadata["diagnostics"]
    assert diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["communication"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_grounding_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0


def test_query_decomposition_reports_current_goal_instead_of_location_support() -> None:
    case = _case(
        case_id="current-goal-query",
        question="Would Caroline want to move back to her home country soon?",
        expected_terms=("current goal",),
        answer="No; she has a different current goal.",
        category=3,
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]

    assert queries == (
        "Would Caroline want to move back to her home country soon?",
        "Would Caroline want to move back to her home country soon?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: want, move, hop, hope, plan, goal, future, soon",
        "caroline want move hop hope plan goal",
    )
    assert query_profile["relation_categories"] == (
        "preference",
        "current_goal",
    )
    assert "location_support" not in query_profile["evidence_need"]
    assert "location_transition" not in query_profile["relation_categories"]
    assert query_profile["bundle_evidence_roles"] == (
        "primary",
        "inference_support",
    )
    assert query_profile["relation_category_terms"]["current_goal"] == (
        "want",
        "hop",
        "hope",
        "plan",
        "goal",
        "future",
        "soon",
    )


def test_benchmark_rerank_boosts_current_goal_over_origin_history() -> None:
    case = _case(
        case_id="current-goal-rerank",
        question="Would Caroline want to move back to her home country soon?",
        expected_terms=("current goal",),
        answer="No; she has a different current goal.",
        category=3,
    )
    origin_history = RetrievedMemory(
        item_id="origin-history",
        rank=1,
        score=0.1,
        text=(
            "session_2 turn D2:2 date: 7:00 pm "
            "D2:2 Caroline: I moved from my home country years ago "
            "and still miss it."
        ),
        source_refs=("D2:2",),
    )
    current_goal = RetrievedMemory(
        item_id="current-goal",
        rank=2,
        score=0.0,
        text=(
            "session_19 turn D19:1 date: 9:00 pm "
            "D19:1 Caroline: I passed the final review last Friday. "
            "This is a big move towards my goal for the future."
        ),
        source_refs=("D19:1",),
    )
    future_plan = RetrievedMemory(
        item_id="future-plan",
        rank=3,
        score=0.0,
        text=(
            "session_19 turn D19:3 date: 9:02 pm "
            "D19:3 Caroline: I hope the plan works out soon and changes "
            "what comes next."
        ),
        source_refs=("D19:3",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (origin_history, current_goal, future_plan),
    )

    assert metadata["applied"] is True
    ranked_ids = [memory.item_id for memory in reranked]
    assert ranked_ids[0] == "current-goal"
    assert ranked_ids.index("current-goal") < ranked_ids.index("origin-history")
    diagnostics_by_id = {
        memory.item_id: memory.metadata["diagnostics"] for memory in reranked
    }
    goal_diagnostics = diagnostics_by_id["current-goal"]
    origin_diagnostics = diagnostics_by_id["origin-history"]
    future_plan_diagnostics = diagnostics_by_id["future-plan"]
    assert goal_diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["current_goal"]
    assert future_plan_diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["current_goal"]
    assert origin_diagnostics["benchmark_candidate_features"][
        "relation_category_hits"
    ] == []
    assert "missing_current_goal_evidence" in origin_diagnostics[
        "benchmark_candidate_features"
    ]["answerability_reason_codes"]
    assert (
        goal_diagnostics["score_signals"]["benchmark_current_goal_context_boost"]
        > 0
    )
    assert (
        origin_diagnostics["score_signals"]["benchmark_current_goal_context_boost"]
        == 0
    )
    assert "location_transition" not in metadata["query_profile"][
        "relation_categories"
    ]


def test_benchmark_rerank_prefers_focused_turn_over_broad_session() -> None:
    case = _case(
        case_id="conv-26:qa:43",
        question=(
            "Would Melanie be more interested in going to a national park "
            "or a theme park?"
        ),
        expected_terms=("national park",),
        answer="national park",
        category=3,
    )
    broad_session = RetrievedMemory(
        item_id="broad-session",
        rank=1,
        score=0.0,
        text=(
            "session_10 date: 8:56 pm D10:1 Caroline: Hi Melanie. "
            "D10:2 Melanie: Hey Caroline. D10:3 Caroline: I joined a group. "
            "D10:12 Melanie: We always look forward to our family camping trip. "
            "We roast marshmallows and tell stories around the campfire. "
            "D10:14 Melanie: Our camping trip had a meteor shower."
        ),
    )
    focused_turn = RetrievedMemory(
        item_id="focused-turn",
        rank=2,
        score=0.0,
        text=(
            "session_10 turn D10:12 date: 8:56 pm "
            "D10:12 Melanie: We always look forward to our family camping trip. "
            "We roast marshmallows, tell stories around the campfire and enjoy it."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (broad_session, focused_turn),
    )

    assert metadata["applied"] is True
    assert metadata["retrieval_intent"]["schema_version"] == "retrieval_intent.v1"
    assert "preference" in metadata["retrieval_intent"]["evidence_need"]
    assert metadata["query_profile"]["evidence_need"] == (
        "preference",
        "inference_support",
    )
    assert [memory.item_id for memory in reranked] == ["focused-turn", "broad-session"]
    focused_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    broad_signals = reranked[1].metadata["diagnostics"]["score_signals"]
    focused_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    focused_policy = reranked[0].metadata["diagnostics"]["benchmark_rerank_policy"]
    assert focused_signals["benchmark_focused_turn_boost"] > 0
    assert broad_signals["benchmark_focused_turn_boost"] == 0
    assert focused_features["schema_version"] == "candidate_evidence_features.v1"
    assert focused_features["direct_speaker_turn"] is True
    assert focused_features["focused_turn_score"] == 0.08
    assert focused_features["relation_hits"]
    assert focused_policy["schema_version"] == "benchmark_rerank_policy.v2"
    assert "FocusedTurnPolicy" in focused_policy["reason_codes_by_policy"]
    assert focused_signals["benchmark_direct_provenance_boost"] > 0
    assert reranked[0].score > reranked[1].score


def test_benchmark_rerank_prefers_durable_outdoor_park_preference() -> None:
    case = _case(
        case_id="conv-26:qa:43",
        question=(
            "Would Melanie be more interested in going to a national park "
            "or a theme park?"
        ),
        expected_terms=("national park",),
        answer="national park",
        category=3,
    )
    generic_outdoor = RetrievedMemory(
        item_id="generic-outdoor",
        rank=1,
        score=0.0,
        text=(
            "session_4 turn D4:8 date: 10:37 am "
            "D4:8 Melanie: It was an awesome time, Caroline! We explored nature, "
            "roasted marshmallows around the campfire and even went on a hike."
        ),
    )
    durable_preference = RetrievedMemory(
        item_id="durable-preference",
        rank=2,
        score=0.0,
        text=(
            "session_10 turn D10:12 date: 8:56 pm "
            "D10:12 Melanie: We always look forward to our family camping trip. "
            "We roast marshmallows, tell stories around the campfire and just "
            "enjoy each other's company. It's the highlight of our summer!"
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_outdoor, durable_preference),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "durable-preference",
        "generic-outdoor",
    ]
    focused_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    generic_signals = reranked[1].metadata["diagnostics"]["score_signals"]
    assert focused_signals["benchmark_outdoor_park_preference_boost"] > 0
    assert generic_signals["benchmark_outdoor_park_preference_boost"] == 0


def test_query_decomposition_treats_hike_count_as_activity_evidence() -> None:
    case = _case(
        case_id="hike-count-query",
        question="How many hikes has Joanna been on?",
        expected_terms=("three",),
        answer="Three",
        category=3,
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]
    activity_intent = metadata["retrieval_intent"]["relations"]["intents"][0]

    assert queries == (
        "How many hikes has Joanna been on?",
        "How many hikes has Joanna been on?\n"
        "Search focus: entities: joanna; speakers: joanna:; "
        "actions: hike, trail, waterfall, went, spot, weekend, summer, photo",
        "joanna hike trail waterfall went spot weekend",
    )
    assert query_profile["relation_terms"] == ("hike",)
    assert query_profile["relation_categories"] == ("activity",)
    assert query_profile["relation_category_terms"]["activity"] == (
        "hike",
        "trail",
        "waterfall",
        "went",
        "spot",
        "weekend",
        "summer",
        "photo",
        "pic",
    )
    assert "broad_query" not in query_profile["risk_flags"]
    assert activity_intent["category"] == "activity"
    assert activity_intent["reason_codes"] == [
        "category:activity",
        "relation_terms",
        "relation_variants",
    ]


def test_benchmark_rerank_boosts_hike_occurrence_evidence_over_generic_topic() -> None:
    case = _case(
        case_id="hike-count-rerank",
        question="How many hikes has Joanna been on?",
        expected_terms=("three",),
        answer="Three",
        category=3,
    )
    generic_topic = RetrievedMemory(
        item_id="generic-topic",
        rank=1,
        score=0.05,
        text=(
            "session_10 turn D10:1 date: 8:00 pm "
            "D10:1 Joanna: I like hiking gear and trail maps."
        ),
    )
    hike_photo = RetrievedMemory(
        item_id="hike-photo",
        rank=2,
        score=0.0,
        text=(
            "session_11 turn D11:5 date: 8:15 pm "
            "D11:5 Joanna: Loved this spot on the hike. "
            "The rush of the water was soothing."
        ),
        source_refs=("D11:5",),
    )
    hike_plan = RetrievedMemory(
        item_id="hike-plan",
        rank=3,
        score=0.0,
        text=(
            "session_14 turn D14:19 date: 8:30 pm "
            "D14:19 Joanna: Yep, I'm hiking with buddies this weekend. "
            "We're checking out a new trail with a waterfall."
        ),
        source_refs=("D14:19",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_topic, hike_photo, hike_plan),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "hike-photo",
        "hike-plan",
        "generic-topic",
    ]
    event_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    generic_signals = reranked[2].metadata["diagnostics"]["score_signals"]
    event_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    generic_features = reranked[2].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert event_features["relation_category_hits"] == ["activity"]
    assert generic_features["relation_category_hits"] == []
    assert "missing_activity_evidence" in generic_features[
        "answerability_reason_codes"
    ]
    assert event_signals["benchmark_activity_coverage_shape_boost"] > 0
    assert generic_signals["benchmark_activity_coverage_shape_boost"] == 0
    assert event_signals["benchmark_effective_boost_cap"] > generic_signals[
        "benchmark_effective_boost_cap"
    ]


def test_benchmark_rerank_prefers_focused_song_preference_turn() -> None:
    case = _case(
        case_id="conv-26:qa:65",
        question='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        expected_terms=("classical music",),
        answer="yes",
        category=3,
    )
    generic_preference = RetrievedMemory(
        item_id="generic-preference",
        rank=1,
        score=0.0,
        text=(
            "session_13 turn D13:10 date: 3:31 pm "
            "D13:10 Melanie: Thanks, Caroline! Glad you like it. "
            "Yeah, I love to. It's peaceful and special."
        ),
    )
    song_preference = RetrievedMemory(
        item_id="song-preference",
        rank=2,
        score=0.0,
        text=(
            "session_15 turn D15:28 date: 3:19 pm "
            "D15:28 Melanie: I'm a fan of both Bach and Mozart, "
            "and I like modern songs too."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_preference, song_preference),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "song-preference",
        "generic-preference",
    ]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_song_preference_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_focused_writing_affinity_turn() -> None:
    case = _case(
        case_id="conv-26:qa:28",
        question="Would Caroline pursue writing as a career option?",
        expected_terms=("books",),
        answer="yes",
        category=3,
    )
    generic_career = RetrievedMemory(
        item_id="generic-career",
        rank=1,
        score=0.0,
        text=(
            "session_11 turn D1:11 date: 7:10 pm "
            "D1:11 Caroline: I'm keen on counseling or working in mental health. "
            "I'd love to support those with similar issues."
        ),
    )
    writing_affinity = RetrievedMemory(
        item_id="writing-affinity",
        rank=2,
        score=0.0,
        text=(
            "session_7 turn D7:9 date: 9:42 am "
            "D7:9 Caroline: Books guide me, motivate me and help me discover who I am."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_career, writing_affinity),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "writing-affinity",
        "generic-career",
    ]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_writing_affinity_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_support_motivation_turn() -> None:
    case = _case(
        case_id="conv-26:qa:15",
        question=(
            "Would Caroline still want to pursue counseling as a career if she "
            "hadn't received support growing up?"
        ),
        expected_terms=("support",),
        answer="likely no",
        category=3,
    )
    generic_counseling = RetrievedMemory(
        item_id="generic-counseling",
        rank=1,
        score=0.0,
        text=(
            "session_1 turn D1:11 date: 1:56 pm "
            "D1:11 Caroline: I'm keen on counseling or working in mental health. "
            "I'd love to support those with similar issues."
        ),
    )
    support_motivation = RetrievedMemory(
        item_id="support-motivation",
        rank=2,
        score=0.0,
        text=(
            "session_4 turn D4:15 date: 10:37 am "
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. I saw how counseling and support groups improved my life, "
            "so I started caring more about mental health. Now I'm passionate "
            "about creating a safe, inviting place for people to grow."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_counseling, support_motivation),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "support-motivation",
        "generic-counseling",
    ]
    support_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    generic_features = reranked[1].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert support_features["relation_category_hits"] == ["support_goal"]
    assert generic_features["relation_category_hits"] == []
    assert "missing_support_goal_evidence" in generic_features[
        "answerability_reason_codes"
    ]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_support_motivation_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_direct_research_goal_turn() -> None:
    case = _case(
        case_id="conv-26:qa:4",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
        category=1,
    )
    generic_research = RetrievedMemory(
        item_id="generic-research",
        rank=1,
        score=0.0,
        text=(
            "session_17 turn D17:7 date: 10:31 am "
            "D17:7 Caroline: Do your research and find an adoption agency or "
            "lawyer. They'll help with the process and documents."
        ),
    )
    direct_goal = RetrievedMemory(
        item_id="direct-goal",
        rank=2,
        score=0.0,
        text=(
            "session_2 turn D2:8 date: 1:14 pm "
            "D2:8 Caroline: Researching adoption agencies - it's been a dream "
            "to have a family and give a loving home to kids who need it."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_research, direct_goal),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == ["direct-goal", "generic-research"]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_research_goal_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_visual_identity_turn() -> None:
    case = _case(
        case_id="conv-26:qa:5",
        question="What is Caroline's identity?",
        expected_terms=("transgender woman",),
        answer="transgender woman",
        category=1,
    )
    generic_identity = RetrievedMemory(
        item_id="generic-identity",
        rank=1,
        score=0.0,
        text=(
            "session_3 turn D3:3 date: 7:55 pm "
            "D3:3 Caroline: Conversations about gender identity and inclusion "
            "are necessary. I'm thankful to give a voice to the trans community."
        ),
    )
    visual_identity = RetrievedMemory(
        item_id="visual-identity",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:5 date: 1:56 pm "
            "D1:5 Caroline: The transgender stories were so inspiring! I was "
            "thankful for all the support. visual query: transgender pride flag mural"
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_identity, visual_identity),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == ["visual-identity", "generic-identity"]
    visual_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    generic_features = reranked[1].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert visual_features["relation_category_hits"] == ["identity_profile"]
    assert generic_features["relation_category_hits"] == []
    assert "missing_identity_profile_evidence" in generic_features[
        "answerability_reason_codes"
    ]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_identity_visual_identity_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_political_context_turn() -> None:
    case = _case(
        case_id="conv-26:qa:51",
        question="What would Caroline's political leaning likely be?",
        expected_terms=("liberal",),
        answer="liberal",
        category=3,
    )
    general_rights = RetrievedMemory(
        item_id="general-rights",
        rank=1,
        score=0.0,
        text=(
            "session_10 turn D10:3 date: 8:56 pm "
            "D10:3 Caroline: I joined a new LGBTQ activist group. "
            "I'm meeting people who are passionate about rights and support."
        ),
    )
    political_context = RetrievedMemory(
        item_id="political-context",
        rank=2,
        score=0.0,
        text=(
            "session_12 turn D12:1 date: 1:50 pm "
            "D12:1 Caroline: I had a not-so-great experience on a hike. "
            "I ran into religious conservatives who said something that upset me. "
            "It made me think how much work we still have to do for LGBTQ rights. "
            "It's helpful to have people around me who accept and support me."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (general_rights, political_context),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "political-context",
        "general-rights",
    ]
    political_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    general_features = reranked[1].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert political_features["relation_category_hits"] == ["identity_profile"]
    assert general_features["relation_category_hits"] == ["identity_profile"]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_political_context_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_adoption_agency_support_turn() -> None:
    case = _case(
        case_id="conv-26:qa:87",
        question=(
            "What type of individuals does the adoption agency Caroline is "
            "considering support?"
        ),
        expected_terms=("LGBTQ+ individuals",),
        answer="LGBTQ+ individuals",
        category=1,
    )
    agency_setup = RetrievedMemory(
        item_id="agency-setup",
        rank=1,
        score=0.0,
        text=(
            "session_2 turn D2:10 date: 1:14 pm "
            "D2:10 Caroline: Here's one of the adoption agencies I'm looking into. "
            "It's a lot to take in, but I'm feeling hopeful and optimistic."
        ),
    )
    agency_support = RetrievedMemory(
        item_id="agency-support",
        rank=2,
        score=0.0,
        text=(
            "session_2 turn D2:12 date: 1:14 pm "
            "D2:12 Caroline: I chose them because they help LGBTQ+ folks with "
            "adoption. Their inclusivity and support really spoke to me."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (agency_setup, agency_support),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == ["agency-support", "agency-setup"]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_adoption_agency_support_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_prefers_conference_plan_time_turn() -> None:
    case = _case(
        case_id="conv-26:qa:18",
        question="When is Caroline going to the transgender conference?",
        expected_terms=("July 2023",),
        answer="July 2023",
        category=2,
    )
    generic_transgender = RetrievedMemory(
        item_id="generic-transgender",
        rank=1,
        score=0.0,
        text=(
            "session_3 turn D3:1 date: 7:55 pm "
            "D3:1 Caroline: I wanted to tell you about my school event last week. "
            "It was awesome! I talked about my transgender journey."
        ),
    )
    conference_plan = RetrievedMemory(
        item_id="conference-plan",
        rank=2,
        score=0.0,
        text=(
            "session_5 turn D5:13 date: 1:36 pm "
            "D5:13 Caroline: I'm going to a transgender conference this month. "
            "I'm excited to meet other people in the community and learn more "
            "about advocacy."
        ),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_transgender, conference_plan),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == [
        "conference-plan",
        "generic-transgender",
    ]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals["benchmark_conference_plan_time_boost"] > 0
    assert signals["benchmark_focused_turn_boost"] > 0


@pytest.mark.parametrize(
    ("case_id", "question", "generic_text", "evidence_text", "signal_key"),
    (
        (
            "conv-26:qa:20",
            "What do Melanie's kids like?",
            "D3:10 Melanie: Your courage is inspiring. My family motivate me "
            "and give me love.",
            "D6:6 Melanie: They were stoked for the dinosaur exhibit! They "
            "love learning about animals and the bones were so cool.",
            "benchmark_kids_preference_shape_boost",
        ),
        (
            "conv-26:qa:23",
            "Would Caroline likely have Dr. Seuss books on her bookshelf?",
            "D6:7 Caroline: I'm creating a library for when I have kids. "
            "I'm looking forward to reading to them.",
            "D6:9 Caroline: I've got lots of kids' books - classics, stories "
            "from different cultures, educational books.",
            "benchmark_bookshelf_collection_boost",
        ),
        (
            "conv-26:qa:70",
            "What personality traits might Melanie say Caroline has?",
            "D3:8 Melanie: I'm proud to be part of the difference you're making.",
            "D13:16 Melanie: You really care about being real and helping "
            "others. Wishing you the best on your adoption journey!",
            "benchmark_personality_trait_shape_boost",
        ),
        (
            "conv-26:qa:78",
            "Would Melanie go on another roadtrip soon?",
            "D8:32 Melanie: My family's been great. We went on another camping "
            "trip in the forest.",
            "D18:3 Melanie: Our trip got off to a bad start. I was really "
            "scared when we got into the accident.",
            "benchmark_roadtrip_incident_boost",
        ),
        (
            "conv-26:qa:84",
            "What did Melanie realize after the charity race?",
            "D2:1 Melanie: I ran a charity race for mental health last Saturday.",
            "D2:3 Melanie: The event was thought-provoking. I'm starting to "
            "realize that self-care is really important.",
            "benchmark_realization_self_care_boost",
        ),
        (
            "conv-26:qa:89",
            "What is Caroline excited about in the adoption process?",
            "D2:10 Caroline: My goal is to give kids a loving home. Here's one "
            "of the adoption agencies I'm looking into.",
            "D2:14 Caroline: I'm thrilled to make a family for kids who need one.",
            "benchmark_excited_outcome_boost",
        ),
        (
            "conv-26:qa:90",
            "What does Melanie think about Caroline's decision to adopt?",
            "D17:4 Melanie: A buddy of mine adopted last year. It was a long "
            "process.",
            "D2:15 Melanie: You're doing something amazing! Creating a family "
            "for those kids is so lovely. You'll be an awesome mom.",
            "benchmark_adoption_reaction_boost",
        ),
        (
            "conv-26:qa:11",
            "How long has Caroline had her current group of friends for?",
            "D3:11 Caroline: My friends, family and mentors are my rocks.",
            "D3:13 Caroline: I've known these friends for 4 years, since I "
            "moved from my home country.",
            "benchmark_friend_duration_boost",
        ),
        (
            "conv-26:qa:13",
            "How long ago was Caroline's 18th birthday?",
            "D3:1 Caroline: I talked about my school event last week.",
            "D4:5 Caroline: My hand-painted bowl from a friend for my 18th "
            "birthday is something I still treasure years later.",
            "benchmark_birthday_memory_boost",
        ),
        (
            "conv-26:qa:16",
            "What activities does Melanie partake in?",
            "D8:2 Melanie: We talked about the school calendar with the kids.",
            "D1:18 Melanie: I'm off to go swimming with the kids. Talk to you soon!",
            "benchmark_activity_coverage_shape_boost",
        ),
        (
            "conv-26:qa:16",
            "What activities does Melanie partake in?",
            "D10:8 Melanie: We went to the beach recently and the kids had a blast.",
            "D9:1 Melanie: I had a quiet weekend after we went camping with my "
            "family. It was great to unplug and hang with the kids.",
            "benchmark_activity_coverage_shape_boost",
        ),
        (
            "conv-26:qa:25",
            "What does Melanie do to destress?",
            "D1:16 Melanie: Painting helps me relax and get creative.",
            "D7:22 Melanie: I've been running farther to de-stress, which has "
            "been great for my headspace.",
            "benchmark_destress_running_shape_boost",
        ),
        (
            "conv-26:qa:28",
            "Would Caroline pursue writing as a career option?",
            "D7:9 Caroline: Books guide me, motivate me and help me discover "
            "who I am.",
            "D7:5 Caroline: I'm still looking into counseling and mental health "
            "jobs. It's important that people have someone to talk to.",
            "benchmark_career_contrast_shape_boost",
        ),
        (
            "conv-26:qa:70",
            "What personality traits might Melanie say Caroline has?",
            "D3:8 Melanie: I'm proud to be part of the difference you're making.",
            "D16:18 Melanie: Thank you for your concern, you're so thoughtful!",
            "benchmark_personality_trait_shape_boost",
        ),
    ),
)
def test_benchmark_rerank_prefers_focused_evidence_shapes(
    case_id: str,
    question: str,
    generic_text: str,
    evidence_text: str,
    signal_key: str,
) -> None:
    case = _case(
        case_id=case_id,
        question=question,
        expected_terms=("evidence",),
        answer="evidence",
        category=3,
    )
    generic = RetrievedMemory(
        item_id="generic",
        rank=1,
        score=0.0,
        text=f"session_1 turn D1:1 date: 1:00 pm {generic_text}",
    )
    evidence = RetrievedMemory(
        item_id="evidence",
        rank=2,
        score=0.0,
        text=f"session_2 turn D2:2 date: 1:00 pm {evidence_text}",
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic, evidence),
    )

    assert metadata["applied"] is True
    assert [memory.item_id for memory in reranked] == ["evidence", "generic"]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert signals[signal_key] > 0
    if signal_key == "benchmark_activity_coverage_shape_boost":
        assert signals["benchmark_relation_category_coverage_boost"] > 0
    elif signal_key == "benchmark_adoption_reaction_boost":
        assert "causal" in signals["benchmark_relation_category_hits"]
    else:
        assert signals["benchmark_focused_turn_boost"] > 0


def test_benchmark_rerank_matches_speaker_alias_without_expanding_query() -> None:
    case = _case(
        case_id="conv-26:qa:speaker-alias",
        question="What did Melanie paint?",
        expected_terms=("sunrise",),
        answer="sunrise",
        category=4,
    )
    distractor = RetrievedMemory(
        item_id="distractor",
        rank=1,
        score=0.0,
        text="D1:1 Morgan: Melanie mentioned an art supply order.",
    )
    evidence = RetrievedMemory(
        item_id="evidence",
        rank=2,
        score=0.0,
        text="D1:2 Mel: I painted a sunrise in watercolor.",
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (distractor, evidence),
    )

    assert metadata["query_profile"]["entity_surfaces"] == ("melanie",)
    assert [memory.item_id for memory in reranked] == ["evidence", "distractor"]
    diagnostics = reranked[0].metadata["diagnostics"]
    assert diagnostics["benchmark_candidate_features"]["speaker_hits"] == ["mel"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0


def test_benchmark_rerank_does_not_match_person_alias_inside_words() -> None:
    case = _case(
        case_id="conv-26:qa:speaker-alias-boundary",
        question="What did Mel paint?",
        expected_terms=("sunrise",),
        answer="sunrise",
        category=4,
    )
    distractor = RetrievedMemory(
        item_id="distractor",
        rank=1,
        score=0.0,
        text="D1:1 Morgan: The melody was painted on a poster.",
    )
    evidence = RetrievedMemory(
        item_id="evidence",
        rank=2,
        score=0.0,
        text="D1:2 Mel: I painted a sunrise in watercolor.",
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (distractor, evidence),
    )
    _, distractor_signals = rerank_module._benchmark_rerank_boost(
        distractor,
        metadata["query_profile"],
    )

    assert metadata["query_profile"]["entity_surfaces"] == ("mel", "melanie")
    assert [memory.item_id for memory in reranked] == ["evidence", "distractor"]
    distractor_features = distractor_signals["candidate_features"]
    assert distractor_features["entity_hits"] == []
    assert distractor_features["speaker_hits"] == []
    evidence_diagnostics = reranked[0].metadata["diagnostics"]
    assert evidence_diagnostics["benchmark_candidate_features"]["speaker_hits"] == [
        "mel"
    ]


def test_infinity_context_http_search_expands_person_alias_and_duration() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "year" in payload["query"] or "wed" in payload["query"]:
            items = [
                {
                    "item_id": "melanie-married",
                    "item_type": "chunk",
                    "text": (
                        "D3:16 Mel: 5 years already! Time flies. "
                        "This was my wedding dress from the day I was a bride."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-melanie-married"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "married-distractor",
                    "item_type": "fact",
                    "text": "D5:2 Morgan: Mel mentioned a wedding venue.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-married-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:91",
        question="How long have Mel and her husband been married?",
        expected_terms=("5 years",),
        answer="5 years",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "How long have Mel and her husband been married?",
        "mel melanie wed year already bride dress married",
        "mel melanie how long session date time last today yesterday",
    ]
    assert result.memories[0].item_id == "melanie-married"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert query_profile["entity_surfaces"] == ("mel", "melanie")
    assert query_profile["temporal_terms"] == ("how long",)
    assert "year" in query_profile["relation_variant_terms"]
    assert "wed" in query_profile["relation_variant_terms"]
    assert "bride" in query_profile["relation_variant_terms"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_temporal_text_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0


def test_infinity_context_http_search_reranks_query_entity_action_overlap() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "look" in payload["query"] or "check" in payload["query"]:
            items = [
                {
                    "item_id": "entity-action",
                    "item_type": "chunk",
                    "text": "D2:8 Caroline: I looked into adoption agencies for summer.",
                    "score": 0.78,
                    "source_refs": [{"source_id": "memory-action"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "entity-only",
                    "item_type": "fact",
                    "text": "D2:7 Melanie: Caroline mentioned a watercolor painting.",
                    "score": 0.88,
                    "source_refs": [{"source_id": "memory-entity"}],
                }
            ]
        return httpx.Response(
            200,
            json={"data": {"items": items}},
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What did Caroline research?",
        "What did Caroline research?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: research, researching, look, check",
        "caroline research researching look check",
    ]
    assert result.memories[0].item_id == "entity-action"
    assert result.metadata["query_expansion"]["applied"] is True
    assert result.metadata["query_decomposition"]["query_count"] == 3
    assert result.metadata["multi_query_merge"]["unique_result_count"] == 2
    assert result.metadata["multi_query_merge"]["multi_query_hit_count"] == 1
    assert result.metadata["query_expansion"]["uses_ground_truth"] is False
    assert result.metadata["benchmark_rerank"]["applied"] is True
    assert result.metadata["benchmark_rerank"]["uses_ground_truth"] is False
    query_profile = result.metadata["benchmark_rerank"]["query_profile"]
    assert "research" in query_profile["lexical_terms"]
    assert "look" in query_profile["relation_variant_terms"]
    assert "caroline" in query_profile["entities"]
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["benchmark_rerank_boosted"] is True
    assert diagnostics["benchmark_query_overlap_terms"] == ["caroline"]
    assert diagnostics["benchmark_query_entities"] == ["caroline"]
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_variant_hit_count"] > 0
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0


def test_infinity_context_http_search_dedupes_source_refs_independent_of_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "look" in payload["query"] or "check" in payload["query"]:
            refs = [{"source_id": "session-2"}, {"source_id": "D2:8"}]
            score = 0.72
        else:
            refs = [{"source_id": "D2:8"}, {"source_id": "session-2"}]
            score = 0.7
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_type": "chunk",
                            "text": (
                                "D2:8 Caroline: I looked into adoption agencies "
                                "for summer."
                            ),
                            "score": score,
                            "source_refs": refs,
                        }
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert result.metadata["multi_query_merge"]["raw_result_count"] == 3
    assert result.metadata["multi_query_merge"]["schema_version"] == "candidate_fusion.v1"
    assert result.metadata["multi_query_merge"]["unique_result_count"] == 1
    assert result.metadata["multi_query_merge"]["multi_query_hit_count"] == 1
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["benchmark_query_match_count"] == 3
    assert diagnostics["benchmark_candidate_fusion"]["schema_version"] == (
        "candidate_fusion.v1"
    )
    assert diagnostics["score_signals"]["benchmark_multi_query_match_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_rrf_fusion_boost"] > 0


def test_infinity_context_http_search_preserves_fused_non_winning_source_refs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        query = str(payload["query"])
        if "\nSearch focus:" in query:
            item_type = "chunk"
            refs = [{"source_id": "chunk-ref"}]
            source = "semantic_chunks"
            score = 0.91
        elif query == "caroline research researching look check":
            item_type = "raw_turn"
            refs = [{"source_id": "D2:8"}]
            source = "raw_turns"
            score = 0.82
        else:
            item_type = "fact"
            refs = [{"source_id": "fact-ref"}]
            source = "postgres_facts"
            score = 0.7
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "adoption-support",
                            "item_type": item_type,
                            "text": (
                                "D2:8 Caroline: I looked into adoption agencies "
                                "for summer."
                            ),
                            "score": score,
                            "source_refs": refs,
                            "diagnostics": {"retrieval_sources": [source]},
                        }
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert result.metadata["multi_query_merge"]["unique_result_count"] == 1
    assert result.memories[0].source_refs == ("chunk-ref", "fact-ref", "D2:8")
    diagnostics = result.memories[0].metadata["diagnostics"]
    fusion = diagnostics["benchmark_candidate_fusion"]
    assert fusion["source_refs"] == ["chunk-ref", "fact-ref", "D2:8"]
    assert fusion["source_types"] == ["fact", "chunk", "raw_turn"]
    assert fusion["retrieval_sources"] == [
        "postgres_facts",
        "semantic_chunks",
        "raw_turns",
    ]


def test_infinity_context_http_search_reads_nested_metadata_diagnostics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        query = str(payload["query"])
        if "\nSearch focus:" in query:
            source = "semantic_chunks"
            score = 0.91
        elif query == "caroline research researching look check":
            source = "raw_turns"
            score = 0.82
        else:
            source = "postgres_facts"
            score = 0.7
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "adoption-support",
                            "item_type": "chunk",
                            "text": (
                                "D2:8 Caroline: I looked into adoption agencies "
                                "for summer."
                            ),
                            "score": score,
                            "source_refs": [{"source_id": source}],
                            "metadata": {
                                "diagnostics": {"retrieval_sources": [source]}
                            },
                        }
                    ]
                }
            },
        )

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        answer="adoption agencies",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    fusion = result.memories[0].metadata["diagnostics"]["benchmark_candidate_fusion"]
    assert fusion["retrieval_sources"] == [
        "postgres_facts",
        "semantic_chunks",
        "raw_turns",
    ]
    assert result.metadata["retrieval_source_counts"] == {
        "postgres_facts": 1,
        "raw_turns": 1,
        "semantic_chunks": 1,
    }


def test_infinity_context_http_search_reranks_topic_relation_overlap() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "individual" in payload["query"] and "support" in payload["query"]:
            items = [
                {
                    "item_id": "agency-support",
                    "item_type": "chunk",
                    "text": (
                        "The adoption agency supports LGBTQ+ individuals "
                        "through inclusive services."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-agency-support"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "caroline-distractor",
                    "item_type": "fact",
                    "text": "Caroline planned a summer trip and mentioned an agency.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-caroline-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:87",
        question=(
            "What type of individuals does the adoption agency Caroline "
            "is considering support?"
        ),
        expected_terms=("LGBTQ+ individuals",),
        answer="LGBTQ+ individuals",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What type of individuals does the adoption agency Caroline "
        "is considering support?",
        "What type of individuals does the adoption agency Caroline "
        "is considering support?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: adoption, support, help, folks, individual, agency, people, adopt",
        "caroline adoption support help folks individual agency",
    ]
    assert result.memories[0].item_id == "agency-support"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "individual" in query_profile["relation_terms"]
    assert "adoption" in query_profile["relation_terms"]
    assert "people" in query_profile["relation_variant_terms"]
    assert not {"inclusive", "inclusivity", "lgbtq"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["benchmark_query_entities"] == []
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_query_overlap_boost"] > 0


def test_infinity_context_http_search_expands_adoption_process_queries() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "create" in payload["query"] and "thrilled" in payload["query"]:
            items = [
                {
                    "item_id": "adoption-process-family",
                    "item_type": "chunk",
                    "text": (
                        "D2:14 Caroline: I'm thrilled to make a family "
                        "for kids who need one."
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-adoption-process"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "agency-distractor",
                    "item_type": "fact",
                    "text": "Caroline researched an adoption agency with inclusive support.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-agency-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:89",
        question="What is Caroline excited about in the adoption process?",
        expected_terms=("creating a family for kids who need one",),
        answer="creating a family for kids who need one",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What is Caroline excited about in the adoption process?",
        "What is Caroline excited about in the adoption process?\n"
        "Search focus: entities: caroline; speakers: caroline:; "
        "actions: excite, make, create, thrilled, process, adoption, look",
        "caroline excite make create thrilled process adoption",
    ]
    assert result.memories[0].item_id == "adoption-process-family"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "excite" in query_profile["relation_terms"]
    assert "adoption" in query_profile["relation_terms"]
    assert not {"family", "kid", "lgbtq"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_query_overlap_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_excited_outcome_boost"] > 0


def test_infinity_context_http_search_expands_adoption_decision_reactions() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        if "reaction" in payload["query"] and "response" in payload["query"]:
            items = [
                {
                    "item_id": "adoption-decision-reaction",
                    "item_type": "chunk",
                    "text": (
                        "D2:15 Melanie: My reaction to Caroline's decision is this: "
                        "Creating a family is so lovely. Good luck!"
                    ),
                    "score": 0.82,
                    "source_refs": [{"source_id": "memory-adoption-decision"}],
                }
            ]
        else:
            items = [
                {
                    "item_id": "adoption-decision-distractor",
                    "item_type": "fact",
                    "text": "Caroline mentioned an adoption agency decision.",
                    "score": 0.9,
                    "source_refs": [{"source_id": "memory-adoption-distractor"}],
                }
            ]
        return httpx.Response(200, json={"data": {"items": items}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-26:qa:90",
        question="What does Melanie think about Caroline's decision to adopt?",
        expected_terms=("doing something amazing", "awesome mom"),
        answer="doing something amazing and will be an awesome mom",
        category=4,
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=2)
    finally:
        backend.close()

    assert [payload["query"] for payload in seen_payloads] == [
        "What does Melanie think about Caroline's decision to adopt?",
        "What does Melanie think about Caroline's decision to adopt?\n"
        "Search focus: entities: melanie, caroline; speakers: melanie:, caroline:; "
        "actions: think, reaction, response, opinion, feel, decision, adopt, thought",
        "melanie caroline think reaction response opinion feel decision",
    ]
    assert result.memories[0].item_id == "adoption-decision-reaction"
    query_profile = result.metadata["query_decomposition"]["query_profile"]
    assert "think" in query_profile["relation_terms"]
    assert "decision" in query_profile["relation_terms"]
    assert "reaction" in query_profile["relation_variant_terms"]
    assert not {"amazing", "awesome", "family", "lovely", "luck", "mom"}.intersection(
        query_profile["relation_variant_terms"]
    )
    diagnostics = result.memories[0].metadata["diagnostics"]
    assert diagnostics["score_signals"]["benchmark_relation_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_query_overlap_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_speaker_boost"] > 0
    assert diagnostics["score_signals"]["benchmark_focused_turn_boost"] > 0


def test_infinity_context_http_search_uses_benchmark_top_k_by_default() -> None:
    seen_payloads: list[dict[str, object]] = []
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"items": []}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=200)
    finally:
        backend.close()

    assert seen_paths == ["/v1/context/benchmark-search"]
    assert seen_payloads[0]["token_budget"] == 25600
    assert seen_payloads[0]["max_facts"] == 200
    assert seen_payloads[0]["max_chunks"] == 200
    assert result.metadata["requested_top_k"] == 200
    assert result.metadata["applied_max_facts"] == 200
    assert result.metadata["applied_token_budget"] == 25600
    assert result.metadata["limited_by_http_api_caps"] is False


def test_infinity_context_http_search_can_use_public_api_caps() -> None:
    seen_payloads: list[dict[str, object]] = []
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"items": []}})

    backend = http_module.InfinityContextHttpComparisonBackend(
        base_url="http://memo.test",
        auth_token="unit-token",
        use_benchmark_search=False,
        transport=httpx.MockTransport(handler),
    )
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )

    try:
        result = backend.search(case, run_id="Run 42", top_k=200)
    finally:
        backend.close()

    assert seen_paths == ["/v1/context"]
    assert seen_payloads[0]["token_budget"] == 16000
    assert seen_payloads[0]["max_facts"] == 100
    assert seen_payloads[0]["max_chunks"] == 200
    assert result.metadata["requested_top_k"] == 200
    assert result.metadata["applied_max_facts"] == 100
    assert result.metadata["applied_token_budget"] == 16000
    assert result.metadata["limited_by_http_api_caps"] is True


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
        "source_external_id": "conv-1-doc",
        "source_id": "conv-1-doc",
    }


def test_mem0_http_ingest_reports_created_memory_count_from_results() -> None:
    response_results = [
        [{"id": "m1", "memory": "Checklist in blue notebook."}, {"id": "m2"}],
        [{"id": "m3", "memory": "Morgan repeated the location."}],
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": response_results.pop(0)})

    backend = http_module.Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    case = _case_with_memory_and_document()

    try:
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert result.items_processed == 2
    assert result.items_failed == 0
    assert result.total_memories_created == 3
    assert [operation.metadata["created_memory_count"] for operation in result.operations] == [
        2,
        1,
    ]


def test_mem0_http_ingest_sends_memory_role_without_timestamp_by_default() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "m1", "memory": "Saved."}]})

    backend = http_module.Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(handler),
    )
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="D1:1 Morgan: The checklist is in the blue notebook.",
                source_external_id="locomo:conv-1:session_1:D1:1:turn",
                metadata={
                    "role": "assistant",
                    "timestamp": 1683546960,
                    "session_key": "session_1",
                    "session_date": "2023-05-08",
                    "dia_id": "D1:1",
                    "speaker": "Morgan",
                },
            ),
        ),
    )

    try:
        backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert seen_payloads == [
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "D1:1 Morgan: The checklist is in the blue notebook.",
                }
            ],
            "user_id": "memo-stack-comparison-run-42",
            "run_id": "Run 42",
            "metadata": {
                "benchmark": "locomo",
                "case_id": "conv-1:qa:1",
                "corpus_key": "corpus-a",
                "source_external_id": "locomo:conv-1:session_1:D1:1:turn",
                "source_id": "locomo:conv-1:session_1:D1:1:turn",
                "session_key": "session_1",
                "session_date": "2023-05-08",
                "dia_id": "D1:1",
                "role": "assistant",
                "speaker": "Morgan",
                "locomo_evidence_ref": "D1:1",
            },
        }
    ]


def test_mem0_http_ingest_can_send_timestamp_when_enabled() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "m1", "memory": "Saved."}]})

    backend = http_module.Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        send_timestamps=True,
        transport=httpx.MockTransport(handler),
    )
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text="D1:1 Morgan: The checklist is in the blue notebook.",
                metadata={"role": "assistant", "timestamp": 1683546960},
            ),
        ),
    )

    try:
        result = backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    assert seen_payloads[0]["timestamp"] == 1683546960
    assert result.metadata["timestamps_sent"] is True


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
                        "source_refs": [{"source_id": "raw-turn-ref"}],
                        "metadata": {
                            "source_id": "locomo-conv-1-D1-1-turn",
                            "locomo_evidence_ref": "D1:1",
                        },
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
            "limit": 7,
            "top_k": 7,
        }
    ]
    assert seen_api_keys == ["mem0-unit-key"]
    assert result.total_results == 1
    assert result.memories[0].text == "The checklist is in the blue notebook."
    assert result.memories[0].source_refs == (
        "raw-turn-ref",
        "locomo-conv-1-D1-1-turn",
        "D1:1",
    )


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


def test_codex_cli_llm_adapters_use_safe_exec_args_and_parse_fake_runner() -> None:
    case = _case(
        case_id="conv-1:qa:1",
        question="Where is the checklist?",
        expected_terms=("blue notebook",),
        answer="blue notebook",
    )
    memories = (RetrievedMemory(text="The checklist is in the blue notebook.", rank=1),)
    calls: list[dict[str, object]] = []

    def fake_runner(
        args: Sequence[str],
        prompt: str,
        timeout_seconds: float,
        cwd: Path | None,
    ) -> str:
        calls.append(
            {
                "args": tuple(args),
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
                "cwd": cwd,
            }
        )
        assert "--ignore-user-config" in args
        assert "--ignore-rules" in args
        assert "--skip-git-repo-check" in args
        assert "read-only" in args
        assert 'approval_policy="never"' in args
        if "memory benchmark answerer" in prompt:
            return "It is in the blue notebook."
        return '```json\n{"verdict":"correct","score":1,"reason":"Supported."}\n```'

    answerer = CodexCliAnswerer(
        model="gpt-5.5",
        codex_command="unit-codex",
        timeout_seconds=9.0,
        command_runner=fake_runner,
        cwd=Path("/tmp"),
    )
    judge = CodexCliJudge(
        model="gpt-5.5",
        codex_command="unit-codex",
        timeout_seconds=9.0,
        command_runner=fake_runner,
        cwd=Path("/tmp"),
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
    assert answer.metadata["provider"] == "codex-cli"
    assert judgment.verdict == "correct"
    assert judgment.score == 1.0
    assert tuple(calls[0]["args"])[0] == "unit-codex"
    assert tuple(calls[0]["args"])[-1] == "-"
    assert calls[0]["timeout_seconds"] == 9.0
    assert calls[0]["cwd"] == Path("/tmp")


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
