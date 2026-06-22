"""Checkpoint and resume state helpers for public memory benchmarks."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CaseRunResult:
    benchmark: str
    case_id: str
    capability: str
    ok: bool
    expected_ok: bool
    forbidden_ok: bool
    missing_terms: tuple[str, ...]
    leaked_terms: tuple[str, ...]
    item_ids: tuple[str, ...]
    latency_ms: float


@dataclass
class BenchmarkSeedStats:
    source_attempt_count: int = 0
    seeded_source_count: int = 0
    seed_cache_hit_count: int = 0


@dataclass(frozen=True)
class SeedCorpusMetadata:
    reusable_by_identity: bool
    source_count: int
    source_kind_counts: Mapping[str, int]


@dataclass(frozen=True)
class BenchmarkResumeState:
    run_results: tuple[CaseRunResult, ...]
    failures: tuple[Mapping[str, object], ...]
    seeded_source_keys: frozenset[tuple[str, str, str, str]]
    seeded_corpus_identities: frozenset[tuple[str, str, int, int]]
    seed_stats: BenchmarkSeedStats


@dataclass(frozen=True)
class BenchmarkResumeLoadResult:
    state: BenchmarkResumeState | None
    status: str
    reason: str
    selected_case_count: int
    checkpoint_case_count: int = 0


def load_checkpoint_resume_state(
    *,
    checkpoint_out: Path | None,
    dataset_hash: str,
    case_selection: Mapping[str, object] | None,
    cases: Sequence[Any],
) -> BenchmarkResumeState | None:
    return load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint_out,
        dataset_hash=dataset_hash,
        case_selection=case_selection,
        cases=cases,
    ).state


def load_checkpoint_resume_state_with_diagnostics(
    *,
    checkpoint_out: Path | None,
    dataset_hash: str,
    case_selection: Mapping[str, object] | None,
    cases: Sequence[Any],
) -> BenchmarkResumeLoadResult:
    selected_case_count = len(cases)
    if checkpoint_out is None or not checkpoint_out.exists():
        return _resume_load_skipped(
            "checkpoint_missing" if checkpoint_out is not None else "checkpoint_not_configured",
            selected_case_count=selected_case_count,
        )
    try:
        payload = json.loads(checkpoint_out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _resume_load_skipped(
            "checkpoint_unreadable",
            selected_case_count=selected_case_count,
        )
    if not isinstance(payload, Mapping):
        return _resume_load_skipped(
            "checkpoint_payload_invalid",
            selected_case_count=selected_case_count,
        )
    if payload.get("schema_version") != "public-benchmark-checkpoint-v1":
        return _resume_load_skipped(
            "checkpoint_schema_mismatch",
            selected_case_count=selected_case_count,
        )
    if payload.get("dataset_hash") != dataset_hash:
        return _resume_load_skipped(
            "dataset_hash_mismatch",
            selected_case_count=selected_case_count,
        )
    if dict(_as_mapping(payload.get("case_selection"))) != dict(case_selection or {}):
        return _resume_load_skipped(
            "case_selection_mismatch",
            selected_case_count=selected_case_count,
        )
    selected_cases = {case_result_key(case.benchmark, case.case_id): case for case in cases}
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, str | bytes):
        return _resume_load_skipped(
            "checkpoint_cases_invalid",
            selected_case_count=selected_case_count,
        )
    run_results: list[CaseRunResult] = []
    seen: set[tuple[str, str]] = set()
    for raw_case in raw_cases:
        result = _case_run_result_from_payload(raw_case)
        if result is None:
            continue
        key = case_result_key(result.benchmark, result.case_id)
        if key not in selected_cases or key in seen:
            continue
        run_results.append(result)
        seen.add(key)
    if not run_results:
        return _resume_load_skipped(
            "no_selected_case_results",
            selected_case_count=selected_case_count,
            checkpoint_case_count=len(raw_cases),
        )
    seeded_source_keys, seeded_corpus_identities = resume_seed_state(
        cases=(selected_cases[key] for key in seen),
        dataset_hash=dataset_hash,
    )
    progress = _as_mapping(payload.get("progress"))
    seed_stats = BenchmarkSeedStats(
        source_attempt_count=_int_field(
            progress,
            "seed_source_attempt_count",
            default=len(seeded_source_keys),
        ),
        seeded_source_count=max(
            len(seeded_source_keys),
            _int_field(progress, "seeded_source_count", default=len(seeded_source_keys)),
        ),
        seed_cache_hit_count=_int_field(progress, "seed_cache_hit_count", default=0),
    )
    failures = tuple(
        dict(item)
        for item in _as_sequence(payload.get("failures"))
        if isinstance(item, Mapping)
    )
    return BenchmarkResumeLoadResult(
        state=BenchmarkResumeState(
            run_results=tuple(run_results),
            failures=failures,
            seeded_source_keys=frozenset(seeded_source_keys),
            seeded_corpus_identities=frozenset(seeded_corpus_identities),
            seed_stats=seed_stats,
        ),
        status="loaded",
        reason="compatible_checkpoint",
        selected_case_count=selected_case_count,
        checkpoint_case_count=len(raw_cases),
    )


def _resume_load_skipped(
    reason: str,
    *,
    selected_case_count: int,
    checkpoint_case_count: int = 0,
) -> BenchmarkResumeLoadResult:
    return BenchmarkResumeLoadResult(
        state=None,
        status="skipped",
        reason=reason,
        selected_case_count=selected_case_count,
        checkpoint_case_count=checkpoint_case_count,
    )


def resume_seed_state(
    *,
    cases: Iterable[Any],
    dataset_hash: str,
) -> tuple[set[tuple[str, str, str, str]], set[tuple[str, str, int, int]]]:
    source_keys: set[tuple[str, str, str, str]] = set()
    corpus_identities: set[tuple[str, str, int, int]] = set()
    metadata_cache: dict[tuple[int, int], SeedCorpusMetadata] = {}
    for case in cases:
        memory_scope_ref = case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
        thread_ref = case.thread_external_ref or f"{case.benchmark}-{case.case_id}"
        for index, memory in enumerate(case.memories):
            source_id = safe_identifier(
                memory.source_external_id
                or f"{dataset_hash}:{case.case_id}:memory:{index}",
                max_chars=160,
            )
            source_keys.add((memory_scope_ref, thread_ref, "fact", source_id))
        for index, document in enumerate(case.documents):
            source_id = safe_identifier(
                document.source_external_id
                or f"{dataset_hash}:{case.case_id}:doc:{index}",
                max_chars=240,
            )
            source_keys.add((memory_scope_ref, thread_ref, "document", source_id))
        metadata = seed_corpus_metadata(case, cache=metadata_cache)
        if metadata.reusable_by_identity:
            corpus_identities.add(
                seed_corpus_identity(
                    case,
                    memory_scope_ref=memory_scope_ref,
                    thread_ref=thread_ref,
                )
            )
    return source_keys, corpus_identities


def case_result_key(benchmark: str, case_id: str) -> tuple[str, str]:
    return benchmark, case_id


def seed_corpus_identity(
    case: Any,
    *,
    memory_scope_ref: str,
    thread_ref: str,
) -> tuple[str, str, int, int]:
    return (
        memory_scope_ref,
        thread_ref,
        id(case.memories),
        id(case.documents),
    )


def seed_corpus_metadata(
    case: Any,
    *,
    cache: dict[tuple[int, int], SeedCorpusMetadata],
) -> SeedCorpusMetadata:
    cache_key = (id(case.memories), id(case.documents))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    kind_counts: dict[str, int] = defaultdict(int)
    kind_counts["fact"] += len(case.memories)
    kind_counts["document"] += len(case.documents)
    metadata = SeedCorpusMetadata(
        reusable_by_identity=(
            bool(case.memories or case.documents)
            and all(source.source_external_id for source in (*case.memories, *case.documents))
        ),
        source_count=len(case.memories) + len(case.documents),
        source_kind_counts={
            key: count for key, count in kind_counts.items() if count > 0
        },
    )
    cache[cache_key] = metadata
    return metadata


def safe_identifier(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    prefix = value[: max(1, max_chars - len(digest) - 1)]
    return f"{prefix}:{digest}"


def _case_run_result_from_payload(raw: object) -> CaseRunResult | None:
    if not isinstance(raw, Mapping):
        return None
    benchmark = _non_empty_str(raw.get("benchmark"))
    case_id = _non_empty_str(raw.get("case_id"))
    if benchmark is None or case_id is None:
        return None
    status = str(raw.get("status") or "")
    expected_ok = _bool_field(raw, "expected_ok", default=status == "ok")
    forbidden_ok = _bool_field(raw, "forbidden_ok", default=status == "ok")
    return CaseRunResult(
        benchmark=benchmark,
        case_id=case_id,
        capability=str(raw.get("capability") or "unknown"),
        ok=status == "ok" and expected_ok and forbidden_ok,
        expected_ok=expected_ok,
        forbidden_ok=forbidden_ok,
        missing_terms=_str_tuple(raw.get("missing_terms")),
        leaked_terms=_str_tuple(raw.get("leaked_terms")),
        item_ids=_str_tuple(raw.get("item_ids")),
        latency_ms=_float_field(raw, "latency_ms", default=0.0),
    )


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _str_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in _as_sequence(value) if item is not None)


def _bool_field(
    raw: Mapping[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    value = raw.get(key)
    return value if isinstance(value, bool) else default


def _int_field(
    raw: Mapping[str, object],
    key: str,
    *,
    default: int,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, value)
    return default


def _float_field(
    raw: Mapping[str, object],
    key: str,
    *,
    default: float,
) -> float:
    value = raw.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return default
