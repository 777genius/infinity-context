"""Normalized public memory benchmark runner.

The runner intentionally talks to Infinity Context through the HTTP API surface, even
when it uses an in-process FastAPI TestClient. This keeps the benchmark close to
how external users exercise the platform while avoiding a hard dependency on a
specific provider adapter.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from infinity_context_core.reporting import with_report_provenance

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_MEMORY_BENCHMARK_SUITE = "public-memory-benchmark"
LOCOMO_BENCHMARK_SUITE = "locomo"
LONGMEMEVAL_BENCHMARK_SUITE = "longmemeval"
SUPPORTED_BENCHMARKS = frozenset({LOCOMO_BENCHMARK_SUITE, LONGMEMEVAL_BENCHMARK_SUITE})
_DEFAULT_MIN_ACCURACY = 0.85


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark dataset cannot be normalized safely."""


class BenchmarkHttpClientPort(Protocol):
    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        """Execute an HTTP POST through the chosen transport."""


class BenchmarkHttpResponsePort(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        """Return decoded JSON response body."""


@dataclass(frozen=True)
class BenchmarkMemoryInput:
    text: str
    kind: str = "note"
    source_external_id: str | None = None


@dataclass(frozen=True)
class BenchmarkDocumentInput:
    title: str
    text: str
    source_type: str = "benchmark_document"
    classification: str = "internal"
    source_external_id: str | None = None


@dataclass(frozen=True)
class PublicBenchmarkCase:
    benchmark: str
    case_id: str
    question: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    memories: tuple[BenchmarkMemoryInput, ...] = ()
    documents: tuple[BenchmarkDocumentInput, ...] = ()
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseRunResult:
    benchmark: str
    case_id: str
    ok: bool
    expected_ok: bool
    forbidden_ok: bool
    missing_terms: tuple[str, ...]
    leaked_terms: tuple[str, ...]
    item_ids: tuple[str, ...]
    latency_ms: float


class _TestClientBenchmarkAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        return self._client.post(path, json=dict(json_body), headers=dict(headers))


class _HttpBenchmarkAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        return self._client.post(path, json=dict(json_body), headers=dict(headers))


def run_public_memory_benchmark(
    *,
    dataset_path: Path,
    api_url: str | None = None,
    auth_token: str | None = None,
    report_out: Path | None = None,
    benchmark: str | None = None,
    min_accuracy: float = _DEFAULT_MIN_ACCURACY,
    max_cases: int | None = None,
) -> dict[str, object]:
    """Run normalized public memory cases and optionally write a JSON report."""

    started = time.perf_counter()
    cases = _load_cases(dataset_path)
    if benchmark:
        canonical_benchmark = _normalize_benchmark_name(benchmark)
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    if max_cases is not None:
        if max_cases < 1:
            raise BenchmarkValidationError("max_cases must be greater than zero")
        cases = cases[:max_cases]

    duplicate_case_keys = _duplicate_case_keys(cases)
    if duplicate_case_keys:
        result = _duplicate_case_failure_result(
            cases=cases,
            duplicate_case_keys=duplicate_case_keys,
        )
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        _write_report(result, report_out)
        return result

    if not cases:
        result = {
            "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
            "status": "failed",
            "ok": False,
            "checks": {
                "dataset_loaded": False,
                "case_count": False,
            },
            "metrics": {
                "case_count": 0,
                "benchmark_count": 0,
                "accuracy": 0.0,
            },
            "benchmarks": [],
            "cases": [],
            "failures": [
                {
                    "case_id": "dataset",
                    "category": "setup",
                    "reason": "no_supported_cases",
                }
            ],
        }
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        _write_report(result, report_out)
        return result

    token = auth_token or (_default_service_token() if api_url else "test-token")
    if not token:
        result = _setup_failure_result(reason="auth_token_required", case_count=len(cases))
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        _write_report(result, report_out)
        return result

    if api_url:
        with httpx.Client(base_url=api_url.rstrip("/"), timeout=30.0) as http_client:
            adapter: BenchmarkHttpClientPort = _HttpBenchmarkAdapter(http_client)
            result = _execute_cases(
                adapter=adapter,
                headers=_auth_headers(token),
                cases=cases,
                dataset_path=dataset_path,
                min_accuracy=min_accuracy,
                started=started,
            )
    else:
        from fastapi.testclient import TestClient

        from infinity_context_server.config import DeployProfile, Settings
        from infinity_context_server.main import create_app

        with tempfile.TemporaryDirectory(prefix="memo-public-benchmark-") as tmp_dir:
            app = create_app(
                Settings(
                    deploy_profile=DeployProfile.TEST,
                    database_url=f"sqlite+aiosqlite:///{Path(tmp_dir) / 'memory.db'}",
                    auto_create_schema=True,
                    service_token=token,
                    qdrant_enabled=False,
                    graphiti_enabled=False,
                    embeddings_enabled=False,
                )
            )
            with TestClient(app) as test_client:
                adapter = _TestClientBenchmarkAdapter(test_client)
                result = _execute_cases(
                    adapter=adapter,
                    headers=_auth_headers(token),
                    cases=cases,
                    dataset_path=dataset_path,
                    min_accuracy=min_accuracy,
                    started=started,
                )

    result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
    _write_report(result, report_out)
    return result


def _default_service_token() -> str:
    from infinity_context_server.config import Settings

    return Settings().service_token


def load_public_benchmark_case_count(
    *,
    dataset_path: Path,
    benchmark: str | None = None,
) -> int:
    """Return the normalized case count without running retrieval or writing data."""

    return int(
        load_public_benchmark_dataset_profile(
            dataset_path=dataset_path,
            benchmark=benchmark,
        )["case_count"]
    )


def load_public_benchmark_dataset_profile(
    *,
    dataset_path: Path,
    benchmark: str | None = None,
) -> dict[str, object]:
    """Return safe normalized dataset profile without running retrieval."""

    cases = _load_cases(dataset_path)
    if benchmark:
        canonical_benchmark = _normalize_benchmark_name(benchmark)
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    case_keys = tuple(f"{case.benchmark}:{case.case_id}" for case in cases)
    unique_case_keys = set(case_keys)
    benchmark_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        benchmark_counts[case.benchmark] += 1
    return {
        "case_count": len(cases),
        "unique_case_id_count": len(unique_case_keys),
        "duplicate_case_id_count": len(case_keys) - len(unique_case_keys),
        "benchmark_counts": dict(sorted(benchmark_counts.items())),
        "dataset_hash": _dataset_hash(dataset_path),
        "dataset_path_label": dataset_path.name,
    }


def _with_public_benchmark_provenance(
    result: dict[str, object],
    *,
    dataset_path: Path,
) -> dict[str, object]:
    return with_report_provenance(
        result,
        generated_by="infinity_context_server.public_benchmark",
        run_id=_dataset_hash(dataset_path)[:16],
        cwd=PROJECT_ROOT,
    )


def _execute_cases(
    *,
    adapter: BenchmarkHttpClientPort,
    headers: Mapping[str, str],
    cases: Sequence[PublicBenchmarkCase],
    dataset_path: Path,
    min_accuracy: float,
    started: float,
) -> dict[str, object]:
    dataset_hash = _dataset_hash(dataset_path)
    scope_slug = f"public-benchmark-{dataset_hash[:16]}"
    run_results: list[CaseRunResult] = []
    failures: list[dict[str, object]] = []
    seeded_source_keys: set[tuple[str, str, str, str]] = set()

    for case in cases:
        try:
            run_results.append(
                _run_case(
                    adapter=adapter,
                    headers=headers,
                    scope_slug=scope_slug,
                    dataset_hash=dataset_hash,
                    case=case,
                    seeded_source_keys=seeded_source_keys,
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "case_id": case.case_id,
                    "category": case.benchmark,
                    "reason": exc.__class__.__name__,
                }
            )
            run_results.append(
                CaseRunResult(
                    benchmark=case.benchmark,
                    case_id=case.case_id,
                    ok=False,
                    expected_ok=False,
                    forbidden_ok=True,
                    missing_terms=case.expected_terms,
                    leaked_terms=(),
                    item_ids=(),
                    latency_ms=0.0,
                )
            )

    benchmarks = _benchmark_summaries(run_results, min_accuracy=min_accuracy)
    accuracy = _accuracy(run_results)
    ok = bool(run_results) and all(item["ok"] is True for item in benchmarks)
    case_keys = tuple(f"{case.benchmark}:{case.case_id}" for case in cases)
    result: dict[str, object] = {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark_scope": "normalized_public_memory_retrieval",
        "evaluation_mode": "retrieved_expected_terms",
        "dataset_path_label": dataset_path.name,
        "dataset_hash": dataset_hash,
        "dataset_sources": {
            summary["name"]: _dataset_source_metadata(
                dataset_path=dataset_path,
                dataset_hash=dataset_hash,
                source_kind="local_dataset",
                case_count=_benchmark_summary_case_count(summary),
            )
            for summary in benchmarks
            if isinstance(summary.get("name"), str)
        },
        "checks": {
            "dataset_loaded": True,
            "case_count": len(run_results) > 0,
            "unique_case_ids": True,
            "minimum_accuracy_met": ok,
            "no_request_failures": not failures,
        },
        "metrics": {
            "benchmark_count": len(benchmarks),
            "case_count": len(run_results),
            "unique_case_id_count": len(set(case_keys)),
            "duplicate_case_id_count": 0,
            "accuracy": accuracy,
            "latency_ms_p95": _p95([item.latency_ms for item in run_results]),
        },
        "benchmarks": benchmarks,
        "cases": [_case_payload(item) for item in run_results],
        "failures": failures + _case_failures(run_results),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    for summary in benchmarks:
        name = summary["name"]
        metrics = summary.get("metrics", {})
        if isinstance(name, str) and isinstance(metrics, dict):
            result["metrics"][f"{name}_accuracy"] = metrics.get("accuracy")
            result["metrics"][f"{name}_case_count"] = metrics.get("case_count")
    return result


def _run_case(
    *,
    adapter: BenchmarkHttpClientPort,
    headers: Mapping[str, str],
    scope_slug: str,
    dataset_hash: str,
    case: PublicBenchmarkCase,
    seeded_source_keys: set[tuple[str, str, str, str]],
) -> CaseRunResult:
    memory_scope_ref = case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
    thread_ref = case.thread_external_ref or f"{case.benchmark}-{case.case_id}"
    for index, memory in enumerate(case.memories):
        source_id = _safe_identifier(
            memory.source_external_id or f"{dataset_hash}:{case.case_id}:memory:{index}",
            max_chars=160,
        )
        seed_key = (memory_scope_ref, thread_ref, "fact", source_id)
        if seed_key not in seeded_source_keys:
            _post_required(
                adapter,
                "/v1/facts",
                headers=headers,
                payload={
                    "space_slug": scope_slug,
                    "memory_scope_external_ref": memory_scope_ref,
                    "thread_external_ref": thread_ref,
                    "text": memory.text,
                    "kind": memory.kind,
                    "source_refs": [
                        {
                            "source_type": "public_benchmark",
                            "source_id": source_id,
                            "quote_preview": memory.text[:240],
                        }
                    ],
                    "classification": "internal",
                },
                idempotency_key=source_id,
            )
            seeded_source_keys.add(seed_key)

    for index, document in enumerate(case.documents):
        source_id = _safe_identifier(
            document.source_external_id or f"{dataset_hash}:{case.case_id}:doc:{index}",
            max_chars=240,
        )
        seed_key = (memory_scope_ref, thread_ref, "document", source_id)
        if seed_key not in seeded_source_keys:
            _post_required(
                adapter,
                "/v1/documents",
                headers=headers,
                payload={
                    "space_slug": scope_slug,
                    "memory_scope_external_ref": memory_scope_ref,
                    "thread_external_ref": thread_ref,
                    "title": document.title,
                    "text": document.text,
                    "source_type": document.source_type,
                    "source_external_id": source_id,
                    "classification": document.classification,
                },
                idempotency_key=source_id,
            )
            seeded_source_keys.add(seed_key)

    started = time.perf_counter()
    response = _post_required(
        adapter,
        "/v1/context",
        headers=headers,
        payload={
            "space_slug": scope_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "thread_external_ref": thread_ref,
            "query": case.question,
            "token_budget": 2000,
            "max_facts": 20,
            "max_chunks": 30,
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    data = _response_data(response)
    evidence_text = _evidence_text(data)
    normalized_evidence = _normalize_text(evidence_text)
    missing = tuple(
        term for term in case.expected_terms if _normalize_text(term) not in normalized_evidence
    )
    leaked = tuple(
        term for term in case.forbidden_terms if _normalize_text(term) in normalized_evidence
    )
    items = data.get("items", [])
    item_ids = tuple(
        str(item.get("item_id")) for item in items if isinstance(item, dict) and item.get("item_id")
    )
    return CaseRunResult(
        benchmark=case.benchmark,
        case_id=case.case_id,
        ok=not missing and not leaked,
        expected_ok=not missing,
        forbidden_ok=not leaked,
        missing_terms=missing,
        leaked_terms=leaked,
        item_ids=item_ids,
        latency_ms=latency_ms,
    )


def _load_cases(dataset_path: Path) -> tuple[PublicBenchmarkCase, ...]:
    if not dataset_path.exists():
        raise BenchmarkValidationError(f"Dataset does not exist: {dataset_path}")
    cases = _cases_from_payload(_load_dataset_payload(dataset_path))
    if not cases:
        raise BenchmarkValidationError("Dataset does not contain benchmark cases")
    return cases


def _load_dataset_payload(dataset_path: Path) -> object:
    text = dataset_path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return ()
    if stripped.startswith("[") or (stripped.startswith("{") and "\n" not in stripped):
        return json.loads(stripped)
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _cases_from_payload(payload: object) -> tuple[PublicBenchmarkCase, ...]:
    if isinstance(payload, Mapping):
        if _is_official_locomo_sample(payload):
            return _official_locomo_cases(payload)
        if _is_official_longmemeval_row(payload):
            return (_official_longmemeval_case(payload),)
        raw_cases = payload.get("cases") or payload.get("data") or payload.get("items")
        if raw_cases is not None:
            return _cases_from_payload(raw_cases)
        return (_normalize_case(payload),)

    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes):
        raise BenchmarkValidationError("Dataset root must be a case list, object or JSONL")

    cases: list[PublicBenchmarkCase] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if _is_official_locomo_sample(item):
            cases.extend(_official_locomo_cases(item))
        elif _is_official_longmemeval_row(item):
            cases.append(_official_longmemeval_case(item))
        else:
            cases.append(_normalize_case(item))
    return tuple(cases)


def _duplicate_case_keys(cases: Sequence[PublicBenchmarkCase]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for case in cases:
        key = f"{case.benchmark}:{case.case_id}"
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return tuple(duplicates)


def _is_official_locomo_sample(raw: Mapping[str, object]) -> bool:
    return isinstance(raw.get("conversation"), Mapping) and isinstance(raw.get("qa"), list)


def _official_locomo_cases(raw: Mapping[str, object]) -> tuple[PublicBenchmarkCase, ...]:
    sample_id = _first_str(raw, "sample_id", "id") or _case_hash(raw)
    documents = _official_locomo_documents(raw, sample_id=sample_id)
    evidence_lookup = _official_locomo_evidence_lookup(raw)
    raw_qas = raw.get("qa")
    cases: list[PublicBenchmarkCase] = []
    if not isinstance(raw_qas, Sequence) or isinstance(raw_qas, str | bytes):
        return ()
    for index, qa in enumerate(raw_qas):
        if not isinstance(qa, Mapping):
            continue
        question = _first_str(qa, "question", "query")
        expected_terms = _official_locomo_evidence_terms(qa, evidence_lookup) or _terms(
            qa,
            "answer",
            "expected_answer",
            "answers",
        )
        if not question or not expected_terms:
            continue
        category = qa.get("category")
        case_id = f"{sample_id}:qa:{index + 1}"
        cases.append(
            PublicBenchmarkCase(
                benchmark=LOCOMO_BENCHMARK_SUITE,
                case_id=case_id,
                question=question,
                expected_terms=expected_terms,
                documents=documents,
                memory_scope_external_ref=f"locomo-{sample_id}",
                thread_external_ref=f"locomo-{sample_id}",
                metadata={
                    "source_format": "official_locomo",
                    "sample_id": sample_id,
                    "qa_index": index,
                    "category": category,
                    "evidence": qa.get("evidence") if isinstance(qa.get("evidence"), list) else [],
                },
            )
        )
    return tuple(cases)


def _official_locomo_evidence_lookup(raw: Mapping[str, object]) -> dict[str, str]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return {}
    lookup: dict[str, str] = {}
    for key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(key):
            continue
        turns = conversation.get(key)
        if not isinstance(turns, Sequence) or isinstance(turns, str | bytes):
            continue
        for turn in turns:
            if not isinstance(turn, Mapping):
                continue
            dia_id = _first_str(turn, "dia_id", "id")
            text = _first_str(turn, "text", "content", "utterance")
            caption = _first_str(turn, "blip_caption", "caption")
            evidence_text = text or caption
            if dia_id and evidence_text:
                lookup[dia_id] = evidence_text
    return lookup


def _official_locomo_evidence_terms(
    qa: Mapping[str, object],
    evidence_lookup: Mapping[str, str],
) -> tuple[str, ...]:
    evidence = qa.get("evidence")
    terms: list[str] = []
    for item in _as_list(evidence):
        if not isinstance(item, str):
            continue
        evidence_id = item.strip()
        if evidence_id and evidence_id in evidence_lookup:
            terms.append(evidence_id)
    return tuple(_unique(terms))


def _official_locomo_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(key):
            continue
        turns = conversation.get(key)
        if not isinstance(turns, Sequence) or isinstance(turns, str | bytes):
            continue
        date_value = conversation.get(f"{key}_date_time")
        lines = [f"{key} date: {date_value}"] if isinstance(date_value, str) else [key]
        for turn in turns:
            if not isinstance(turn, Mapping):
                continue
            dia_id = _first_str(turn, "dia_id", "id")
            speaker = _first_str(turn, "speaker", "role", "author") or "speaker"
            text = _first_str(turn, "text", "content", "utterance")
            if text:
                prefix = f"{dia_id} " if dia_id else ""
                lines.append(f"{prefix}{speaker}: {text}")
            caption = _first_str(turn, "blip_caption", "caption")
            if caption:
                lines.append(f"{speaker} image caption: {caption}")
        if len(lines) > 1:
            documents.append(
                BenchmarkDocumentInput(
                    title=f"LoCoMo {sample_id} {key}",
                    text="\n".join(lines),
                    source_type="locomo_session",
                    source_external_id=f"locomo:{sample_id}:{key}",
                )
            )
    documents.extend(_official_locomo_observation_documents(raw, sample_id=sample_id))
    return tuple(documents)


def _official_locomo_observation_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    observation = raw.get("observation")
    if not isinstance(observation, Mapping):
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(observation, key=_session_sort_key):
        value = observation.get(key)
        if not isinstance(value, Mapping):
            continue
        session_key = key.removesuffix("_observation")
        lines = [f"{session_key} observations"]
        for actor, raw_items in value.items():
            actor_name = str(actor).strip() or "speaker"
            for item in _as_list(raw_items):
                text, evidence_id = _official_locomo_observation_item(item)
                if not text or not evidence_id:
                    continue
                lines.append(f"{evidence_id} {actor_name}: {text}")
        if len(lines) <= 1:
            continue
        documents.append(
            BenchmarkDocumentInput(
                title=f"LoCoMo {sample_id} {session_key} observations",
                text="\n".join(lines),
                source_type="locomo_observation",
                source_external_id=f"locomo:{sample_id}:{session_key}:observation",
            )
        )
    return tuple(documents)


def _official_locomo_observation_item(item: object) -> tuple[str, str]:
    if isinstance(item, Mapping):
        text = _first_str(item, "text", "content", "observation", "summary")
        evidence_id = _first_str(item, "dia_id", "evidence", "evidence_id", "id")
        return text, evidence_id
    if isinstance(item, Sequence) and not isinstance(item, str | bytes):
        values = tuple(str(value).strip() for value in item if isinstance(value, str))
        if len(values) >= 2:
            return values[0], values[1]
    return "", ""


def _is_session_key(value: object) -> bool:
    return (
        isinstance(value, str) and value.startswith("session_") and not value.endswith("_date_time")
    )


def _session_sort_key(value: object) -> tuple[int, str]:
    if not isinstance(value, str):
        return (10**9, "")
    if _is_session_key(value):
        try:
            return (int(value.rsplit("_", 1)[1]), value)
        except ValueError:
            return (10**9, value)
    return (10**9, value)


def _is_official_longmemeval_row(raw: Mapping[str, object]) -> bool:
    return (
        isinstance(raw.get("haystack_sessions"), list)
        and isinstance(raw.get("question"), str)
        and raw.get("answer") is not None
    )


def _official_longmemeval_case(raw: Mapping[str, object]) -> PublicBenchmarkCase:
    question_id = _first_str(raw, "question_id", "id") or _case_hash(raw)
    question = _first_str(raw, "question", "query")
    expected_terms = _official_longmemeval_evidence_terms(raw) or _terms(
        raw,
        "answer",
        "expected_answer",
        "answers",
    )
    if not question or not expected_terms:
        raise BenchmarkValidationError(f"LongMemEval row {question_id} is missing question/answer")
    return PublicBenchmarkCase(
        benchmark=LONGMEMEVAL_BENCHMARK_SUITE,
        case_id=question_id,
        question=question,
        expected_terms=expected_terms,
        documents=_official_longmemeval_documents(raw, question_id=question_id),
        memory_scope_external_ref=f"longmemeval-{question_id}",
        thread_external_ref=f"longmemeval-{question_id}",
        metadata={
            "source_format": "official_longmemeval",
            "question_type": raw.get("question_type"),
            "question_date": raw.get("question_date"),
            "answer_session_ids": raw.get("answer_session_ids")
            if isinstance(raw.get("answer_session_ids"), list)
            else [],
        },
    )


def _official_longmemeval_evidence_terms(raw: Mapping[str, object]) -> tuple[str, ...]:
    answer_session_ids = tuple(
        item.strip()
        for item in _as_list(raw.get("answer_session_ids"))
        if isinstance(item, str) and item.strip()
    )
    if not answer_session_ids:
        return ()
    haystack_session_ids = {
        item.strip()
        for item in _as_list(raw.get("haystack_session_ids"))
        if isinstance(item, str) and item.strip()
    }
    if not haystack_session_ids:
        return tuple(_unique(answer_session_ids))
    return tuple(_unique(item for item in answer_session_ids if item in haystack_session_ids))


def _official_longmemeval_documents(
    raw: Mapping[str, object],
    *,
    question_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    sessions = raw.get("haystack_sessions")
    if not isinstance(sessions, Sequence) or isinstance(sessions, str | bytes):
        return ()
    dates = raw.get("haystack_dates")
    session_ids = raw.get("haystack_session_ids")
    documents: list[BenchmarkDocumentInput] = []
    for index, session in enumerate(sessions):
        session_id = _sequence_str(session_ids, index) or f"session-{index + 1}"
        date_value = _sequence_str(dates, index)
        lines = [f"{session_id} date: {date_value}"] if date_value else [session_id]
        for message in _as_list(session):
            if isinstance(message, Mapping):
                role = _first_str(message, "role", "speaker", "author") or "speaker"
                content = _first_str(message, "content", "text", "message")
                if content:
                    lines.append(f"{role}: {content}")
            elif isinstance(message, str) and message.strip():
                lines.append(message.strip())
        if len(lines) > 1:
            documents.append(
                BenchmarkDocumentInput(
                    title=f"LongMemEval {question_id} {session_id}",
                    text="\n".join(lines),
                    source_type="longmemeval_session",
                    source_external_id=f"longmemeval:{question_id}:{session_id}",
                )
            )
    return tuple(documents)


def _sequence_str(value: object, index: int) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    if index >= len(value):
        return None
    item = value[index]
    return item.strip() if isinstance(item, str) and item.strip() else None


def _normalize_case(raw: Mapping[str, object]) -> PublicBenchmarkCase:
    benchmark = _normalize_benchmark_name(
        _first_str(raw, "benchmark", "source_benchmark", "dataset", "source")
    )
    case_id = _first_str(raw, "case_id", "qa_id", "uid", "id", "sample_id") or _case_hash(raw)
    question = _question(raw)
    expected_terms = _terms(raw, "expected_terms", "expected", "answer_terms")
    if not expected_terms:
        expected_terms = _terms(raw, "answer", "expected_answer", "ground_truth", "gold_answer")
    forbidden_terms = _terms(raw, "forbidden_terms", "forbidden", "must_not_retrieve")
    memories = _memory_inputs(raw)
    documents = _document_inputs(raw)
    if not question:
        raise BenchmarkValidationError(f"Case {case_id} is missing question")
    if not expected_terms:
        raise BenchmarkValidationError(f"Case {case_id} is missing expected_terms or answer")
    if not memories and not documents:
        raise BenchmarkValidationError(f"Case {case_id} is missing memories/documents")
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        forbidden_terms=forbidden_terms,
        memories=memories,
        documents=documents,
        memory_scope_external_ref=_first_str(
            raw, "memory_scope_external_ref", "user_id", "memory_scope_id"
        ),
        thread_external_ref=_first_str(raw, "thread_external_ref", "thread_id", "session_id"),
        metadata=_metadata(raw),
    )


def _normalize_benchmark_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError("Benchmark name is required")
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"locomo", "lo-co-mo", "long-context-memory"}:
        return LOCOMO_BENCHMARK_SUITE
    if normalized in {"longmemeval", "longmem-eval", "long-memory-eval"}:
        return LONGMEMEVAL_BENCHMARK_SUITE
    raise BenchmarkValidationError(f"Unsupported benchmark: {value}")


def _question(raw: Mapping[str, object]) -> str:
    direct = _first_str(raw, "question", "query", "input")
    if direct:
        return direct
    qa = raw.get("qa")
    if isinstance(qa, Mapping):
        return _first_str(qa, "question", "query", "input") or ""
    return ""


def _terms(raw: Mapping[str, object], *keys: str) -> tuple[str, ...]:
    terms: list[str] = []
    for key in keys:
        value = raw.get(key)
        terms.extend(_term_values(value))
        if terms:
            break
    qa = raw.get("qa")
    if not terms and isinstance(qa, Mapping):
        for key in keys:
            terms.extend(_term_values(qa.get(key)))
            if terms:
                break
    return tuple(_unique(terms))


def _term_values(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, int | float | bool):
        return [str(value)]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _memory_inputs(raw: Mapping[str, object]) -> tuple[BenchmarkMemoryInput, ...]:
    values = _first_present(raw, "memories", "facts", "conversation", "messages", "history")
    entries: list[BenchmarkMemoryInput] = []
    for index, value in enumerate(_as_list(values)):
        if isinstance(value, str) and value.strip():
            entries.append(BenchmarkMemoryInput(text=value.strip()))
        elif isinstance(value, Mapping):
            text = _first_str(value, "text", "content", "message", "utterance")
            speaker = _first_str(value, "speaker", "role", "author")
            kind = _first_str(value, "kind", "memory_kind") or "note"
            if text:
                prefix = f"{speaker}: " if speaker else ""
                entries.append(BenchmarkMemoryInput(text=f"{prefix}{text}", kind=kind))
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            nested = " ".join(str(item).strip() for item in value if str(item).strip())
            if nested:
                entries.append(BenchmarkMemoryInput(text=f"session {index}: {nested}"))
    return tuple(entries)


def _document_inputs(raw: Mapping[str, object]) -> tuple[BenchmarkDocumentInput, ...]:
    values = _first_present(raw, "documents", "chunks", "passages", "haystack", "context")
    docs: list[BenchmarkDocumentInput] = []
    for index, value in enumerate(_as_list(values)):
        if isinstance(value, str) and value.strip():
            docs.append(BenchmarkDocumentInput(title=f"benchmark document {index + 1}", text=value))
        elif isinstance(value, Mapping):
            text = _first_str(value, "text", "content", "body", "passage")
            if not text:
                continue
            title = (
                _first_str(value, "title", "name", "session_id")
                or f"benchmark document {index + 1}"
            )
            docs.append(BenchmarkDocumentInput(title=title, text=text))
    return tuple(docs)


def _first_present(raw: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _first_str(raw: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _metadata(raw: Mapping[str, object]) -> Mapping[str, object]:
    value = raw.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _post_required(
    adapter: BenchmarkHttpClientPort,
    path: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    idempotency_key: str | None = None,
) -> BenchmarkHttpResponsePort:
    request_headers = dict(headers)
    if idempotency_key:
        request_headers["Idempotency-Key"] = idempotency_key[:120]
    response = adapter.post(path, json_body=payload, headers=request_headers)
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{path} returned HTTP {response.status_code}")
    return response


def _response_data(response: BenchmarkHttpResponsePort) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _evidence_text(data: Mapping[str, object]) -> str:
    texts: list[str] = []
    rendered = data.get("rendered_text")
    if isinstance(rendered, str):
        texts.append(rendered)
    items = data.get("items")
    if isinstance(items, Sequence) and not isinstance(items, str | bytes):
        for item in items:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return "\n".join(texts)


def _benchmark_summaries(
    run_results: Sequence[CaseRunResult],
    *,
    min_accuracy: float,
) -> list[dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in run_results:
        grouped[item.benchmark].append(item)
    summaries: list[dict[str, object]] = []
    for benchmark in sorted(grouped):
        cases = grouped[benchmark]
        accuracy = _accuracy(cases)
        summaries.append(
            {
                "name": benchmark,
                "suite": benchmark,
                "ok": accuracy >= min_accuracy,
                "metrics": {
                    "accuracy": accuracy,
                    "case_count": len(cases),
                    "expected_recall": _ratio(
                        sum(1 for item in cases if item.expected_ok),
                        len(cases),
                    ),
                    "forbidden_leak_rate": _ratio(
                        sum(1 for item in cases if not item.forbidden_ok),
                        len(cases),
                    ),
                    "latency_ms_p95": _p95([item.latency_ms for item in cases]),
                },
            }
        )
    return summaries


def _case_payload(item: CaseRunResult) -> dict[str, object]:
    return {
        "benchmark": item.benchmark,
        "case_id": item.case_id,
        "status": "ok" if item.ok else "failed",
        "expected_ok": item.expected_ok,
        "forbidden_ok": item.forbidden_ok,
        "missing_terms": list(item.missing_terms),
        "leaked_terms": list(item.leaked_terms),
        "item_ids": list(item.item_ids),
        "latency_ms": item.latency_ms,
    }


def _case_failures(run_results: Sequence[CaseRunResult]) -> list[dict[str, object]]:
    return [
        {
            "case_id": item.case_id,
            "category": item.benchmark,
            "reason": "missing_expected_terms" if item.missing_terms else "forbidden_terms_leaked",
            "missing_terms": list(item.missing_terms),
            "leaked_terms": list(item.leaked_terms),
        }
        for item in run_results
        if not item.ok
    ]


def _accuracy(run_results: Sequence[CaseRunResult]) -> float:
    return _ratio(sum(1 for item in run_results if item.ok), len(run_results))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return round(ordered[index], 2)


def _dataset_hash(dataset_path: Path) -> str:
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()


def _dataset_source_metadata(
    *,
    dataset_path: Path,
    dataset_hash: str,
    source_kind: str,
    case_count: int | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "source_kind": source_kind,
        "path_label": dataset_path.name,
        "sha256": dataset_hash,
        "size_bytes": dataset_path.stat().st_size,
    }
    if isinstance(case_count, int):
        result["case_count"] = case_count
    return result


def _benchmark_summary_case_count(summary: Mapping[str, object]) -> int | None:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    case_count = metrics.get("case_count")
    return case_count if isinstance(case_count, int) else None


def _case_hash(raw: Mapping[str, object]) -> str:
    encoded = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_values.append(value.strip())
    return unique_values


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _safe_identifier(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    prefix = value[: max(1, max_chars - len(digest) - 1)]
    return f"{prefix}:{digest}"


def _setup_failure_result(*, reason: str, case_count: int) -> dict[str, object]:
    return {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": case_count > 0,
            "auth_token_configured": False,
        },
        "metrics": {
            "case_count": case_count,
            "benchmark_count": 0,
            "accuracy": 0.0,
        },
        "benchmarks": [],
        "cases": [],
        "failures": [{"case_id": "suite_setup", "category": "setup", "reason": reason}],
    }


def _duplicate_case_failure_result(
    *,
    cases: Sequence[PublicBenchmarkCase],
    duplicate_case_keys: Sequence[str],
) -> dict[str, object]:
    return {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": bool(cases),
            "unique_case_ids": False,
        },
        "metrics": {
            "case_count": len(cases),
            "benchmark_count": len({case.benchmark for case in cases}),
            "accuracy": 0.0,
            "duplicate_case_id_count": len(duplicate_case_keys),
        },
        "benchmarks": [],
        "cases": [],
        "failures": [
            {
                "case_id": key,
                "category": "setup",
                "reason": "duplicate_case_id",
            }
            for key in duplicate_case_keys[:20]
        ],
    }


def _write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
