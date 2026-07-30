"""Local provider-free orchestration for ranked-evidence semantic cutoffs."""

from __future__ import annotations

import json
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient

from infinity_context_server import ranked_evidence_document_seed_contract as seed_contract
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from infinity_context_server.memory_comparison_case_loader import (
    load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
    sanitize_source_refs,
    source_ref_payload,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    LOCOMO_INGEST_RICH_DOCUMENTS,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output,
    source_identity_refs_from_dedupe_key,
    source_identity_refs_from_source_refs,
)
from infinity_context_server.public_benchmark_artifacts import write_json_atomic
from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_http import post_required
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
    TestClientBenchmarkAdapter,
)
from infinity_context_server.ranked_evidence_answer_support import (
    RankedEvidenceAnswerSupportObservation,
    ranked_evidence_answer_support_metrics,
)
from infinity_context_server.ranked_evidence_evaluator_helpers import (
    benchmark_memory_source_id,
    evaluator_only_payload,
)
from infinity_context_server.ranked_evidence_retrieval_request import (
    RankedEvidenceRetrievalRequest,
    ranked_evidence_retrieval_request,
)
from infinity_context_server.ranked_evidence_seed_case import (
    RankedEvidenceSeedCase,
    ranked_evidence_seed_case,
)
from infinity_context_server.ranked_evidence_semantic_gate_decision import (
    ranked_evidence_semantic_gate_decision,
)
from infinity_context_server.ranked_evidence_semantic_metrics import (
    RankedEvidenceCutoffSnapshot,
    ranked_evidence_semantic_metrics,
)

_SCHEMA_VERSION = "ranked-evidence-semantic-gate.v1"
_AUTH_TOKEN = "ranked-evidence-semantic-gate-token"
_MAX_EXACT_GOLD_REFS = 10_000
_MAX_EXACT_GOLD_REF_CHARS = 4_096
_MAX_EXACT_GOLD_DEPTH = 8
_TELEMETRY_KEYS = (
    "ranked_evidence_candidate_count",
    "ranked_evidence_selectable_candidate_count",
    "ranked_evidence_eligible_candidate_count",
    "ranked_evidence_returned_count",
    "ranked_evidence_source_diversity_count",
)


@dataclass(frozen=True, slots=True)
class _GateConfig:
    dataset_path: Path
    benchmark: str
    case_ids: tuple[str, ...]
    cutoffs: tuple[int, ...]
    reference_cutoff: int
    token_budget: int
    max_facts: int
    max_chunks: int
    locomo_ingest_mode: str
    local_database_url: str | None
    report_out: Path | None

    def public_payload(self) -> dict[str, object]:
        """Return only reproducible, non-secret configuration."""

        return {
            "benchmark": self.benchmark,
            "case_ids": list(self.case_ids),
            "cutoffs": list(self.cutoffs),
            "reference_cutoff": self.reference_cutoff,
            "token_budget": self.token_budget,
            "max_facts": self.max_facts,
            "max_chunks": self.max_chunks,
            "locomo_ingest_mode": self.locomo_ingest_mode,
            "transport": "local_in_process_testclient",
            "database_url_scheme": "sqlite+aiosqlite",
            "providers_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class _PendingSnapshot:
    cutoff: int
    item_ids: tuple[str, ...]
    observations: tuple[RankedEvidenceAnswerSupportObservation, ...]
    telemetry: Mapping[str, object]


class _GateFailure(RuntimeError):
    """Bounded internal failure whose code is safe for the public report."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def run_ranked_evidence_semantic_gate(
    dataset_path: Path,
    benchmark: str,
    case_ids: Sequence[str],
    cutoffs: Sequence[int] = (10, 20, 50, 200),
    reference_cutoff: int = 200,
    token_budget: int = 25_600,
    max_facts: int = 200,
    max_chunks: int = 200,
    locomo_ingest_mode: str = "official-turns",
    local_database_url: str | None = None,
    report_out: Path | None = None,
) -> dict[str, object]:
    """Measure ranked source coverage using only the local HTTP boundary.

    Dataset evidence labels are read only after every retrieval response for a
    case has been received. They can therefore score the response but cannot
    influence retrieval requests, ranking inputs, or source seeding.
    """

    try:
        _validate_report_target_aliases(
            dataset_path=dataset_path,
            local_database_url=local_database_url,
            report_out=report_out,
        )
    except _GateFailure as exc:
        return _failed_report(
            reason=exc.reason,
            benchmark=benchmark if isinstance(benchmark, str) else None,
        )

    try:
        config = _validated_config(
            dataset_path=dataset_path,
            benchmark=benchmark,
            case_ids=case_ids,
            cutoffs=cutoffs,
            reference_cutoff=reference_cutoff,
            token_budget=token_budget,
            max_facts=max_facts,
            max_chunks=max_chunks,
            locomo_ingest_mode=locomo_ingest_mode,
            local_database_url=local_database_url,
            report_out=report_out,
        )
    except _GateFailure as exc:
        result = _failed_report(
            reason=exc.reason,
            benchmark=benchmark if isinstance(benchmark, str) else None,
        )
        _write_report_if_requested(result, report_out)
        return result

    try:
        cases = _load_selected_cases(config)
        result = _run_local_gate(config, cases)
    except (BenchmarkValidationError, OSError, ValueError) as exc:
        result = _failed_report(
            reason=_bounded_execution_reason(exc),
            benchmark=config.benchmark,
            config=config,
        )
    except _GateFailure as exc:
        result = _failed_report(
            reason=exc.reason,
            benchmark=config.benchmark,
            config=config,
        )
    except Exception:
        result = _failed_report(
            reason="gate_execution_failed",
            benchmark=config.benchmark,
            config=config,
        )
    _write_report_if_requested(result, config.report_out)
    return result


def _validated_config(
    *,
    dataset_path: object,
    benchmark: object,
    case_ids: object,
    cutoffs: object,
    reference_cutoff: object,
    token_budget: object,
    max_facts: object,
    max_chunks: object,
    locomo_ingest_mode: object,
    local_database_url: object,
    report_out: object,
) -> _GateConfig:
    if not isinstance(dataset_path, Path):
        raise _GateFailure("invalid_dataset_path")
    try:
        if not dataset_path.is_file():
            raise _GateFailure("invalid_dataset_path")
    except OSError as exc:
        raise _GateFailure("invalid_dataset_path") from exc
    normalized_benchmark = _non_empty_string(benchmark)
    normalized_case_ids = _unique_strings(case_ids)
    normalized_cutoffs = _positive_ints(cutoffs)
    if normalized_benchmark not in {"locomo", "longmemeval"}:
        raise _GateFailure("invalid_benchmark")
    if normalized_case_ids is None or not normalized_case_ids:
        raise _GateFailure("invalid_case_ids")
    if (
        normalized_cutoffs is None
        or not normalized_cutoffs
        or any(
            left >= right
            for left, right in zip(
                normalized_cutoffs,
                normalized_cutoffs[1:],
                strict=False,
            )
        )
    ):
        raise _GateFailure("invalid_cutoffs")
    if not _is_exact_positive_int(reference_cutoff) or reference_cutoff != normalized_cutoffs[-1]:
        raise _GateFailure("invalid_reference_cutoff")
    if not _is_exact_positive_int(token_budget) or not 64 <= token_budget <= 64_000:
        raise _GateFailure("invalid_token_budget")
    if not _is_exact_positive_int(max_facts) or max_facts > 200:
        raise _GateFailure("invalid_max_facts")
    if not _is_exact_positive_int(max_chunks) or max_chunks > 200:
        raise _GateFailure("invalid_max_chunks")
    normalized_ingest_mode = _non_empty_string(locomo_ingest_mode)
    if normalized_ingest_mode not in {
        LOCOMO_INGEST_OFFICIAL_TURNS,
        LOCOMO_INGEST_RICH_DOCUMENTS,
    }:
        raise _GateFailure("invalid_locomo_ingest_mode")
    if local_database_url is not None:
        database_path = _sqlite_database_path(local_database_url)
        if database_path is None:
            raise _GateFailure("invalid_local_database_url")
        if _resolved_path(database_path) == _resolved_path(dataset_path):
            raise _GateFailure("database_aliases_dataset")
        _require_scratch_database(database_path)
    if report_out is not None and not isinstance(report_out, Path):
        raise _GateFailure("invalid_report_out")
    return _GateConfig(
        dataset_path=dataset_path,
        benchmark=normalized_benchmark,
        case_ids=normalized_case_ids,
        cutoffs=normalized_cutoffs,
        reference_cutoff=reference_cutoff,
        token_budget=token_budget,
        max_facts=max_facts,
        max_chunks=max_chunks,
        locomo_ingest_mode=normalized_ingest_mode,
        local_database_url=local_database_url,
        report_out=report_out,
    )


def _load_selected_cases(config: _GateConfig) -> tuple[PublicBenchmarkCase, ...]:
    loaded = load_memory_comparison_cases(
        config.dataset_path,
        locomo_ingest_mode=config.locomo_ingest_mode,
    )
    by_id: dict[str, PublicBenchmarkCase] = {}
    for case in loaded:
        if case.benchmark != config.benchmark:
            continue
        if case.case_id in by_id:
            raise _GateFailure("duplicate_selected_case_id")
        by_id[case.case_id] = case
    if any(case_id not in by_id for case_id in config.case_ids):
        raise _GateFailure("selected_case_not_found")
    return tuple(by_id[case_id] for case_id in config.case_ids)


def _run_local_gate(
    config: _GateConfig,
    cases: Sequence[PublicBenchmarkCase],
) -> dict[str, object]:
    if config.local_database_url is not None:
        case_results = _execute_with_database(config, cases, config.local_database_url)
    else:
        with tempfile.TemporaryDirectory(prefix="ranked-evidence-semantic-gate-") as tmp_dir:
            database_url = f"sqlite+aiosqlite:///{Path(tmp_dir) / 'semantic-gate.db'}"
            case_results = _execute_with_database(config, cases, database_url)
    retrieval_miss_counts = tuple(_case_retrieval_miss_count(result) for result in case_results)
    if any(count is None for count in retrieval_miss_counts):
        raise _GateFailure("malformed_case_metrics")
    passed_count = sum(result.get("ok") is True for result in case_results)
    failed_count = len(case_results) - passed_count
    reference_recalls = tuple(
        recall for result in case_results if (recall := _reference_recall(result)) is not None
    )
    ok = bool(case_results) and failed_count == 0
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "passed" if ok else "failed",
        "ok": ok,
        "benchmark": config.benchmark,
        "config": config.public_payload(),
        "metrics": {
            "case_count": len(case_results),
            "passed_case_count": passed_count,
            "failed_case_count": failed_count,
            "mean_reference_recall": _mean(reference_recalls),
            "retrieval_miss_ref_count": sum(
                count for count in retrieval_miss_counts if count is not None
            ),
        },
        "gates": {
            "configuration_valid": True,
            "cases_selected": bool(case_results),
            "all_cases_passed": failed_count == 0,
        },
        "cases": list(case_results),
        "failures": [
            {
                "case_id": result.get("case_id"),
                "reason": result.get("failure_reason", "semantic_metrics_mismatch"),
            }
            for result in case_results
            if result.get("ok") is not True
        ],
    }


def _execute_with_database(
    config: _GateConfig,
    cases: Sequence[PublicBenchmarkCase],
    database_url: str,
) -> tuple[dict[str, object], ...]:
    with tempfile.TemporaryDirectory(prefix="ranked-evidence-semantic-gate-assets-") as asset_dir:
        return _execute_with_database_and_assets(
            config,
            cases,
            database_url,
            asset_storage_dir=Path(asset_dir),
        )


def _execute_with_database_and_assets(
    config: _GateConfig,
    cases: Sequence[PublicBenchmarkCase],
    database_url: str,
    *,
    asset_storage_dir: Path,
) -> tuple[dict[str, object], ...]:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database_url,
            auto_create_schema=True,
            service_token=_AUTH_TOKEN,
            ui_enabled=False,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_enabled=False,
            asset_storage_dir=str(asset_storage_dir),
        )
    )
    with TestClient(app) as client:
        adapter = TestClientBenchmarkAdapter(client)
        headers = {"Authorization": f"Bearer {_AUTH_TOKEN}"}
        return tuple(
            _run_case(
                adapter=adapter,
                headers=headers,
                config=config,
                case=case,
                case_index=index,
            )
            for index, case in enumerate(cases, start=1)
        )


def _run_case(
    *,
    adapter: TestClientBenchmarkAdapter,
    headers: Mapping[str, str],
    config: _GateConfig,
    case: PublicBenchmarkCase,
    case_index: int,
) -> dict[str, object]:
    seed_case = ranked_evidence_seed_case(case)
    request_case = ranked_evidence_retrieval_request(case)
    slug = _case_scope_slug(seed_case, case_index=case_index)
    _create_isolated_space(adapter, headers=headers, slug=slug)
    _seed_case_once(adapter, headers=headers, slug=slug, seed_case=seed_case)
    pending = tuple(
        _request_cutoff(
            adapter,
            headers=headers,
            slug=slug,
            request_case=request_case,
            config=config,
            cutoff=cutoff,
        )
        for cutoff in config.cutoffs
    )

    # Gold evidence becomes visible only after every response is immutable here.
    evaluator_payload = evaluator_only_payload(case)
    ground_truth = evaluator_payload.get("ground_truth")
    expected_terms = _answer_support_expected_terms(ground_truth)
    expected_refs = _exact_case_evidence_refs(case)
    answer_support = ranked_evidence_answer_support_metrics(
        tuple(observation for snapshot in pending for observation in snapshot.observations),
        question=request_case.question,
        expected_terms=expected_terms,
        expected_refs=expected_refs,
    )
    snapshots = tuple(
        RankedEvidenceCutoffSnapshot(
            cutoff=snapshot.cutoff,
            item_ids=snapshot.item_ids,
            covered_refs=_covered_expected_refs(
                snapshot.observations,
                expected_refs=expected_refs,
            ),
            ranked_telemetry=snapshot.telemetry,
        )
        for snapshot in pending
    )
    metrics = ranked_evidence_semantic_metrics(
        snapshots,
        expected_refs=expected_refs,
        reference_cutoff=config.reference_cutoff,
    )
    decision = ranked_evidence_semantic_gate_decision(
        metrics,
        answer_support,
        expected_cutoffs=config.cutoffs,
        reference_cutoff=config.reference_cutoff,
    )
    return {
        "case_id": case.case_id,
        "benchmark": case.benchmark,
        "ok": decision.ok,
        "failure_reason": decision.failure_reason,
        "snapshots": [
            {
                "cutoff": snapshot.cutoff,
                "item_ids": list(snapshot.item_ids),
                "covered_refs": list(snapshot.covered_refs),
                "ranked_telemetry": dict(snapshot.ranked_telemetry),
            }
            for snapshot in snapshots
        ],
        "metrics": metrics,
        "answer_support": answer_support,
    }


def _create_isolated_space(
    adapter: TestClientBenchmarkAdapter,
    *,
    headers: Mapping[str, str],
    slug: str,
) -> None:
    response = post_required(
        adapter,
        "/v1/spaces",
        headers=headers,
        payload={"slug": slug, "name": slug},
    )
    payload = response.json()
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if response.status_code != 201 or not isinstance(data, Mapping) or data.get("slug") != slug:
        raise _GateFailure("space_creation_failed")


def _seed_case_once(
    adapter: TestClientBenchmarkAdapter,
    *,
    headers: Mapping[str, str],
    slug: str,
    seed_case: RankedEvidenceSeedCase,
) -> None:
    memory_scope_ref = seed_case.memory_scope_external_ref
    thread_ref = seed_case.thread_external_ref
    if seed_case.conversations:
        documents = conversation_documents(seed_case)
    else:
        documents = seed_case.documents
        for step, memory in enumerate(seed_case.memories, start=1):
            source_id = benchmark_memory_source_id(seed_case, memory, step=step)
            response = post_required(
                adapter,
                "/v1/facts",
                headers=headers,
                payload={
                    "space_slug": slug,
                    "memory_scope_external_ref": memory_scope_ref,
                    "thread_external_ref": thread_ref,
                    "text": memory.text,
                    "kind": memory.kind,
                    "classification": "internal",
                    "source_refs": [
                        source_ref_payload(
                            source_type="memory_comparison_benchmark",
                            source_id=source_id,
                            quote_preview=memory.text,
                        )
                    ],
                },
                idempotency_key=source_id,
            )
            if response.status_code != 201:
                raise _GateFailure("fact_seed_failed")
    for step, document in enumerate(documents, start=1):
        _seed_document(
            adapter,
            headers=headers,
            slug=slug,
            seed_case=seed_case,
            document=document,
            step=step,
        )


def _seed_document(
    adapter: TestClientBenchmarkAdapter,
    *,
    headers: Mapping[str, str],
    slug: str,
    seed_case: RankedEvidenceSeedCase,
    document: BenchmarkDocumentInput,
    step: int,
) -> None:
    source_id = safe_identifier(
        document.source_external_id or f"{seed_case.case_id}:document:{step}",
        max_chars=240,
    )
    response = post_required(
        adapter,
        "/v1/documents",
        headers=headers,
        payload={
            "space_slug": slug,
            "memory_scope_external_ref": seed_case.memory_scope_external_ref,
            "thread_external_ref": seed_case.thread_external_ref,
            "title": document.title,
            "text": document.text,
            "source_type": document.source_type,
            "source_external_id": source_id,
            "classification": document.classification,
            "source_refs": sanitize_source_refs(document.source_refs),
        },
        idempotency_key=source_id,
    )
    seed_contract.require_document_seed(response, _GateFailure("document_seed_failed"))


def _request_cutoff(
    adapter: TestClientBenchmarkAdapter,
    *,
    headers: Mapping[str, str],
    slug: str,
    request_case: RankedEvidenceRetrievalRequest,
    config: _GateConfig,
    cutoff: int,
) -> _PendingSnapshot:
    response = adapter.post(
        "/v1/context/benchmark-search",
        json_body={
            "space_slug": slug,
            "memory_scope_external_ref": request_case.memory_scope_external_ref,
            "thread_external_ref": request_case.thread_external_ref,
            "query": request_case.question,
            "token_budget": config.token_budget,
            "max_facts": config.max_facts,
            "max_chunks": config.max_chunks,
            "max_evidence_items": cutoff,
        },
        headers=headers,
    )
    if response.status_code != 200:
        raise _GateFailure("benchmark_search_failed")
    try:
        payload = response.json()
    except Exception as exc:
        raise _GateFailure("malformed_benchmark_response") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
        raise _GateFailure("malformed_benchmark_response")
    data = payload["data"]
    items = data.get("items")
    diagnostics = data.get("diagnostics")
    if (
        not _is_sequence(items)
        or not isinstance(diagnostics, Mapping)
        or diagnostics.get("scope_not_found") is True
        or diagnostics.get("retrieval_disabled") is True
    ):
        raise _GateFailure("malformed_benchmark_response")
    item_mappings = tuple(item for item in items if isinstance(item, Mapping))
    if len(item_mappings) != len(items):
        raise _GateFailure("malformed_benchmark_response")
    database_item_ids = tuple(item.get("item_id") for item in item_mappings)
    if any(not isinstance(item_id, str) or not item_id.strip() for item_id in database_item_ids):
        raise _GateFailure("malformed_benchmark_response")
    item_ids = _public_evidence_fingerprints(item_mappings)
    observations = tuple(
        RankedEvidenceAnswerSupportObservation(
            cutoff=cutoff,
            fingerprint=fingerprint,
            text=str(item["text"]),
            source_refs=_observed_source_refs(item),
        )
        for fingerprint, item in zip(item_ids, item_mappings, strict=True)
    )
    telemetry = {key: diagnostics.get(key) for key in _TELEMETRY_KEYS}
    return _PendingSnapshot(
        cutoff=cutoff,
        item_ids=item_ids,
        observations=observations,
        telemetry=telemetry,
    )


def _covered_expected_refs(
    observations: Sequence[RankedEvidenceAnswerSupportObservation],
    *,
    expected_refs: Sequence[str],
) -> tuple[str, ...]:
    observed = {ref for observation in observations for ref in observation.source_refs}
    return tuple(
        expected
        for expected in expected_refs
        if observed.intersection(_reference_equivalents(expected))
    )


def _observed_source_refs(item: Mapping[str, object]) -> tuple[str, ...]:
    observed = list(safe_source_refs_for_output((item,)))
    observed.extend(
        source_identity_refs_from_source_refs(
            (item,),
            include_exact_turn_refs=True,
        )
    )
    for key in ("source_ref_dedupe_key", "dedupe_key"):
        observed.extend(source_identity_refs_from_dedupe_key(item.get(key)))
    return tuple(dict.fromkeys(observed))


def _reference_equivalents(value: str) -> frozenset[str]:
    return frozenset(
        (
            value,
            *safe_source_refs_for_output((value,)),
            *source_identity_refs_from_source_refs(
                (value,),
                include_exact_turn_refs=True,
            ),
        )
    )


def _exact_case_evidence_refs(case: PublicBenchmarkCase) -> tuple[str, ...]:
    metadata = case.metadata
    if not isinstance(metadata, Mapping):
        raise _GateFailure("malformed_gold_evidence")
    raw_evidence = metadata.get("evidence")
    if raw_evidence is None or raw_evidence == () or raw_evidence == []:
        raw_evidence = metadata.get("evidence_terms")
    flattened = _exact_gold_scalars(raw_evidence, depth=0)
    if not flattened:
        raise _GateFailure("malformed_gold_evidence")
    refs: list[str] = []
    for value in flattened:
        if not isinstance(value, str):
            raise _GateFailure("malformed_gold_evidence")
        ref = value.strip()
        if len(ref) > _MAX_EXACT_GOLD_REF_CHARS:
            raise _GateFailure("gold_evidence_overflow")
        if not ref or "\x00" in ref:
            raise _GateFailure("malformed_gold_evidence")
        if ref not in refs:
            refs.append(ref)
        if len(refs) > _MAX_EXACT_GOLD_REFS:
            raise _GateFailure("gold_evidence_overflow")
    return tuple(refs)


def _exact_gold_scalars(value: object, *, depth: int) -> tuple[object, ...]:
    if depth > _MAX_EXACT_GOLD_DEPTH:
        raise _GateFailure("gold_evidence_overflow")
    if isinstance(value, (Mapping, bytes, bytearray)):
        raise _GateFailure("malformed_gold_evidence")
    if _is_sequence(value):
        if len(value) > _MAX_EXACT_GOLD_REFS:
            raise _GateFailure("gold_evidence_overflow")
        flattened: list[object] = []
        for item in value:
            flattened.extend(_exact_gold_scalars(item, depth=depth + 1))
            if len(flattened) > _MAX_EXACT_GOLD_REFS:
                raise _GateFailure("gold_evidence_overflow")
        return tuple(flattened)
    return (value,)


def _public_evidence_fingerprints(
    items: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    occurrences: dict[str, int] = {}
    fingerprints: list[str] = []
    for item in items:
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise _GateFailure("malformed_benchmark_response")
        identity_refs = source_identity_refs_from_source_refs(
            (item.get("source_refs"),),
            include_exact_turn_refs=True,
        )
        payload = {
            "kind": _normalized_public_text(item.get("kind")),
            "source_identity_refs": sorted(identity_refs),
            "text": _normalized_public_text(text),
        }
        digest = sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        occurrence = occurrences.get(digest, 0) + 1
        occurrences[digest] = occurrence
        fingerprints.append(f"evidence-sha256:{digest}:{occurrence}")
    return tuple(fingerprints)


def _normalized_public_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _case_scope_slug(
    case: PublicBenchmarkCase | RankedEvidenceSeedCase,
    *,
    case_index: int,
) -> str:
    digest = sha256(
        f"{case.benchmark}\0{case.case_id}\0{case_index}\0{token_hex(8)}".encode()
    ).hexdigest()[:16]
    return f"ranked-evidence-semantic-{case_index}-{digest}"


def _failed_report(
    *,
    reason: str,
    benchmark: str | None,
    config: _GateConfig | None = None,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "failed",
        "ok": False,
        "benchmark": benchmark,
        "config": config.public_payload() if config is not None else {},
        "metrics": {
            "case_count": 0,
            "passed_case_count": 0,
            "failed_case_count": 0,
            "mean_reference_recall": 0.0,
            "retrieval_miss_ref_count": 0,
        },
        "gates": {
            "configuration_valid": config is not None,
            "cases_selected": False,
            "all_cases_passed": False,
        },
        "cases": [],
        "failures": [{"case_id": "suite_setup", "reason": reason}],
    }


def _write_report_if_requested(
    result: Mapping[str, object],
    report_out: object,
) -> None:
    if isinstance(report_out, Path):
        write_json_atomic(report_out, result)


def _bounded_execution_reason(exc: Exception) -> str:
    if isinstance(exc, BenchmarkValidationError):
        return "dataset_invalid"
    if isinstance(exc, OSError):
        return "local_io_failed"
    return "gate_configuration_invalid"


def _reference_recall(result: Mapping[str, object]) -> float | None:
    cutoffs = _mapping(result.get("metrics")).get("cutoffs")
    if not _is_sequence(cutoffs) or not cutoffs:
        return None
    reference = cutoffs[-1]
    if not isinstance(reference, Mapping):
        return None
    recall = reference.get("recall")
    return recall if isinstance(recall, float) and 0.0 <= recall <= 1.0 else None


def _case_retrieval_miss_count(result: object) -> int | None:
    if not isinstance(result, Mapping) or not isinstance(result.get("ok"), bool):
        return None
    metrics = result.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    count = metrics.get("retrieval_miss_ref_count")
    return count if _is_exact_non_negative_int(count) else None


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_strings(value: object) -> tuple[str, ...] | None:
    if not _is_sequence(value):
        return None
    strings = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in strings) or len(
        frozenset(strings)
    ) != len(strings):
        return None
    return strings


def _positive_ints(value: object) -> tuple[int, ...] | None:
    if not _is_sequence(value):
        return None
    values = tuple(value)
    return values if all(_is_exact_positive_int(item) and item <= 200 for item in values) else None


def _validate_report_target_aliases(
    *,
    dataset_path: object,
    local_database_url: object,
    report_out: object,
) -> None:
    if not isinstance(report_out, Path):
        return
    report_path = _resolved_path(report_out)
    if isinstance(dataset_path, Path) and report_path == _resolved_path(dataset_path):
        raise _GateFailure("report_out_aliases_dataset")
    database_path = _sqlite_database_path(local_database_url)
    if database_path is not None and report_path == _resolved_path(database_path):
        raise _GateFailure("report_out_aliases_database")


def _sqlite_database_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value)
    prefix = "sqlite+aiosqlite:///"
    if (
        parsed.scheme != "sqlite+aiosqlite"
        or parsed.netloc
        or not value.startswith(prefix)
        or parsed.fragment
    ):
        return None
    encoded_path = value[len(prefix) :].split("?", maxsplit=1)[0]
    try:
        decoded_path = unquote(encoded_path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if not decoded_path or decoded_path == ":memory:" or "\x00" in decoded_path:
        return None
    return Path(decoded_path)


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise _GateFailure("invalid_local_path") from exc


def _require_scratch_database(database_path: Path) -> None:
    resolved = _resolved_path(database_path)
    related_paths = (
        resolved,
        Path(f"{resolved}-wal"),
        Path(f"{resolved}-shm"),
        Path(f"{resolved}-journal"),
    )
    try:
        for path in related_paths:
            if path.exists() and (not path.is_file() or path.stat().st_size != 0):
                raise _GateFailure("local_database_not_scratch")
    except OSError as exc:
        raise _GateFailure("invalid_local_database_url") from exc


def _answer_support_expected_terms(ground_truth: object) -> tuple[str, ...]:
    """Normalize only exact answer shapes supported by answer-unit policies."""

    if isinstance(ground_truth, str):
        return (ground_truth,)
    if isinstance(ground_truth, int) and not isinstance(ground_truth, bool):
        return (str(ground_truth),)
    if not _is_sequence(ground_truth):
        return ()
    terms = tuple(ground_truth)
    return terms if all(isinstance(term, str) for term in terms) else ()


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_exact_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_exact_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
