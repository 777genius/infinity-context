"""Execution helpers for public memory benchmark cases."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from infinity_context_server.public_benchmark_case_diagnostics import (
    case_answer_preview as _case_answer_preview,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_evidence_refs as _case_evidence_refs,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_expected_terms_preview as _case_expected_terms_preview,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_question_preview as _case_question_preview,
)
from infinity_context_server.public_benchmark_checkpoint import (
    BenchmarkSeedStats,
    CaseRunResult,
    case_result_key,
)

MAX_PUBLIC_BENCHMARK_PARALLELISM = 32
SourceKey = tuple[str, str, str, str]
CorpusIdentity = tuple[str, str, str]
CaseCapabilityResolver = Callable[[Any], str]
RunCase = Callable[
    [
        Any,
        set[SourceKey],
        set[CorpusIdentity],
        dict[tuple[int, int], Any],
        BenchmarkSeedStats,
        Any | None,
        int | None,
        int | None,
    ],
    CaseRunResult,
]


class BenchmarkValidationErrorFactory(Protocol):
    def __call__(self, message: str) -> Exception:
        """Create the benchmark module's validation exception."""


class BenchmarkCaseProgressPort(Protocol):
    total_case_count: int

    def event(self, event_type: str, **fields: object) -> None:
        """Record a progress event."""


@dataclass(frozen=True)
class CaseExecutionEntry:
    case_index: int
    case: Any


@dataclass(frozen=True)
class CaseExecutionGroup:
    group_index: int
    context_ref: tuple[str, str]
    entries: tuple[CaseExecutionEntry, ...]


@dataclass(frozen=True)
class CaseExecutionOutcome:
    entry: CaseExecutionEntry
    result: CaseRunResult
    failure: dict[str, object] | None
    seeded_source_keys: frozenset[SourceKey]
    seeded_corpus_identities: frozenset[CorpusIdentity]
    seed_stats: BenchmarkSeedStats


@dataclass(frozen=True)
class CaseExecutionGroupOutcome:
    group: CaseExecutionGroup
    case_outcomes: tuple[CaseExecutionOutcome, ...]
    seeded_source_keys: frozenset[SourceKey]
    seeded_corpus_identities: frozenset[CorpusIdentity]
    seed_stats: BenchmarkSeedStats


def execute_case_sequentially(
    *,
    entry: CaseExecutionEntry,
    run_case: RunCase,
    capability_resolver: CaseCapabilityResolver,
    seeded_source_keys: set[SourceKey],
    seeded_corpus_identities: set[CorpusIdentity],
    seed_corpus_metadata_cache: dict[tuple[int, int], Any],
    seed_stats: BenchmarkSeedStats,
    progress: BenchmarkCaseProgressPort,
    total_case_count: int,
    run_results: list[CaseRunResult],
    failures: list[dict[str, object]],
    effective_parallelism: int,
) -> None:
    case = entry.case
    emit_case_started(
        progress=progress,
        entry=entry,
        capability_resolver=capability_resolver,
        total_case_count=total_case_count,
        effective_parallelism=effective_parallelism,
    )
    try:
        result = run_case(
            case,
            seeded_source_keys,
            seeded_corpus_identities,
            seed_corpus_metadata_cache,
            seed_stats,
            progress,
            entry.case_index,
            total_case_count,
        )
        run_results.append(result)
        emit_case_completed(
            progress=progress,
            entry=entry,
            result=result,
            seeded_source_count=len(seeded_source_keys),
            seed_cache_hit_count=seed_stats.seed_cache_hit_count,
            effective_parallelism=effective_parallelism,
        )
    except Exception as exc:
        failure = case_exception_failure(case, exc)
        failures.append(failure)
        run_results.append(case_error_result(case, capability_resolver))
        emit_case_failed(
            progress=progress,
            entry=entry,
            reason=str(failure["reason"]),
            seeded_source_count=len(seeded_source_keys),
            seed_cache_hit_count=seed_stats.seed_cache_hit_count,
            effective_parallelism=effective_parallelism,
        )


def execute_case_with_isolated_state(
    *,
    entry: CaseExecutionEntry,
    run_case: RunCase,
    capability_resolver: CaseCapabilityResolver,
) -> CaseExecutionOutcome:
    seeded_source_keys: set[SourceKey] = set()
    seeded_corpus_identities: set[CorpusIdentity] = set()
    seed_stats = BenchmarkSeedStats()
    try:
        result = run_case(
            entry.case,
            seeded_source_keys,
            seeded_corpus_identities,
            {},
            seed_stats,
            None,
            entry.case_index,
            None,
        )
        failure = None
    except Exception as exc:
        result = case_error_result(entry.case, capability_resolver)
        failure = case_exception_failure(entry.case, exc)
    return CaseExecutionOutcome(
        entry=entry,
        result=result,
        failure=failure,
        seeded_source_keys=frozenset(seeded_source_keys),
        seeded_corpus_identities=frozenset(seeded_corpus_identities),
        seed_stats=seed_stats,
    )


def execute_case_group_with_isolated_state(
    *,
    group: CaseExecutionGroup,
    run_case: RunCase,
    capability_resolver: CaseCapabilityResolver,
) -> CaseExecutionGroupOutcome:
    seeded_source_keys: set[SourceKey] = set()
    seeded_corpus_identities: set[CorpusIdentity] = set()
    seed_corpus_metadata_cache: dict[tuple[int, int], Any] = {}
    seed_stats = BenchmarkSeedStats()
    case_outcomes: list[CaseExecutionOutcome] = []
    for entry in group.entries:
        try:
            result = run_case(
                entry.case,
                seeded_source_keys,
                seeded_corpus_identities,
                seed_corpus_metadata_cache,
                seed_stats,
                None,
                entry.case_index,
                None,
            )
            failure = None
        except Exception as exc:
            result = case_error_result(entry.case, capability_resolver)
            failure = case_exception_failure(entry.case, exc)
        case_outcomes.append(
            CaseExecutionOutcome(
                entry=entry,
                result=result,
                failure=failure,
                seeded_source_keys=frozenset(),
                seeded_corpus_identities=frozenset(),
                seed_stats=BenchmarkSeedStats(),
            )
        )
    return CaseExecutionGroupOutcome(
        group=group,
        case_outcomes=tuple(case_outcomes),
        seeded_source_keys=frozenset(seeded_source_keys),
        seeded_corpus_identities=frozenset(seeded_corpus_identities),
        seed_stats=seed_stats,
    )


def case_exception_outcome(
    entry: CaseExecutionEntry,
    exc: Exception,
    *,
    capability_resolver: CaseCapabilityResolver,
) -> CaseExecutionOutcome:
    return CaseExecutionOutcome(
        entry=entry,
        result=case_error_result(entry.case, capability_resolver),
        failure=case_exception_failure(entry.case, exc),
        seeded_source_keys=frozenset(),
        seeded_corpus_identities=frozenset(),
        seed_stats=BenchmarkSeedStats(),
    )


def merge_case_execution_outcome(
    *,
    outcome: CaseExecutionOutcome,
    seeded_source_keys: set[SourceKey],
    seeded_corpus_identities: set[CorpusIdentity],
    seed_stats: BenchmarkSeedStats,
) -> None:
    seeded_source_keys.update(outcome.seeded_source_keys)
    seeded_corpus_identities.update(outcome.seeded_corpus_identities)
    seed_stats.source_attempt_count += outcome.seed_stats.source_attempt_count
    seed_stats.seeded_source_count = len(seeded_source_keys)
    seed_stats.seed_cache_hit_count += outcome.seed_stats.seed_cache_hit_count


def merge_case_execution_group_outcome(
    *,
    outcome: CaseExecutionGroupOutcome,
    seeded_source_keys: set[SourceKey],
    seeded_corpus_identities: set[CorpusIdentity],
    seed_stats: BenchmarkSeedStats,
) -> None:
    seeded_source_keys.update(outcome.seeded_source_keys)
    seeded_corpus_identities.update(outcome.seeded_corpus_identities)
    seed_stats.source_attempt_count += outcome.seed_stats.source_attempt_count
    seed_stats.seeded_source_count = len(seeded_source_keys)
    seed_stats.seed_cache_hit_count += outcome.seed_stats.seed_cache_hit_count


def emit_case_started(
    *,
    progress: BenchmarkCaseProgressPort,
    entry: CaseExecutionEntry,
    capability_resolver: CaseCapabilityResolver,
    total_case_count: int,
    effective_parallelism: int,
) -> None:
    case = entry.case
    progress.event(
        "case_started",
        case_index=entry.case_index,
        total_case_count=total_case_count,
        case_id=case.case_id,
        benchmark=case.benchmark,
        capability=capability_resolver(case),
        memory_count=len(case.memories),
        document_count=len(case.documents),
        effective_parallelism=effective_parallelism,
    )


def emit_case_completed(
    *,
    progress: BenchmarkCaseProgressPort,
    entry: CaseExecutionEntry,
    result: CaseRunResult,
    seeded_source_count: int,
    seed_cache_hit_count: int,
    effective_parallelism: int,
) -> None:
    progress.event(
        "case_completed",
        case_index=entry.case_index,
        total_case_count=progress.total_case_count,
        case_id=entry.case.case_id,
        benchmark=entry.case.benchmark,
        capability=result.capability,
        ok=result.ok,
        missing_term_count=len(result.missing_terms),
        leaked_term_count=len(result.leaked_terms),
        latency_ms=result.latency_ms,
        seeded_source_count=seeded_source_count,
        seed_cache_hit_count=seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )


def emit_case_failed(
    *,
    progress: BenchmarkCaseProgressPort,
    entry: CaseExecutionEntry,
    reason: str,
    seeded_source_count: int,
    seed_cache_hit_count: int,
    effective_parallelism: int,
) -> None:
    progress.event(
        "case_failed",
        case_index=entry.case_index,
        total_case_count=progress.total_case_count,
        case_id=entry.case.case_id,
        benchmark=entry.case.benchmark,
        reason=reason,
        seeded_source_count=seeded_source_count,
        seed_cache_hit_count=seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )


def case_error_result(
    case: Any,
    capability_resolver: CaseCapabilityResolver,
) -> CaseRunResult:
    return CaseRunResult(
        benchmark=case.benchmark,
        case_id=case.case_id,
        capability=capability_resolver(case),
        ok=False,
        expected_ok=False,
        forbidden_ok=True,
        missing_terms=case.expected_terms,
        leaked_terms=(),
        item_ids=(),
        latency_ms=0.0,
        question_preview=_case_question_preview(case),
        answer_preview=_case_answer_preview(case),
        expected_terms_preview=_case_expected_terms_preview(case),
        evidence_refs=_case_evidence_refs(case),
    )


def case_exception_failure(case: Any, exc: Exception) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": case.case_id,
        "category": case.benchmark,
        "reason": exc.__class__.__name__,
    }
    question_preview = _case_question_preview(case)
    if question_preview:
        payload["question_preview"] = question_preview
    answer_preview = _case_answer_preview(case)
    if answer_preview:
        payload["answer_preview"] = answer_preview
    evidence_refs = _case_evidence_refs(case)
    if evidence_refs:
        payload["evidence_refs"] = list(evidence_refs)
    return payload


def ordered_run_results(
    cases: Sequence[Any],
    result_by_key: Mapping[tuple[str, str], CaseRunResult],
) -> list[CaseRunResult]:
    ordered: list[CaseRunResult] = []
    for case in cases:
        result = result_by_key.get(case_result_key(case.benchmark, case.case_id))
        if result is not None:
            ordered.append(result)
    return ordered


def case_execution_parallelism(
    entries: Sequence[CaseExecutionEntry],
    *,
    requested_parallelism: int,
) -> tuple[int, str | None]:
    groups = case_execution_groups(entries)
    if requested_parallelism <= 1 or len(entries) <= 1:
        return 1, None
    if len(groups) <= 1:
        return 1, "shared_case_context_refs"
    effective_parallelism = min(requested_parallelism, len(groups))
    if effective_parallelism < requested_parallelism:
        return effective_parallelism, "case_context_group_limit"
    return effective_parallelism, None


def case_execution_groups(
    entries: Sequence[CaseExecutionEntry],
) -> tuple[CaseExecutionGroup, ...]:
    grouped: OrderedDict[tuple[str, str], list[CaseExecutionEntry]] = OrderedDict()
    for entry in entries:
        grouped.setdefault(case_context_ref(entry.case), []).append(entry)
    return tuple(
        CaseExecutionGroup(
            group_index=index,
            context_ref=context_ref,
            entries=tuple(group_entries),
        )
        for index, (context_ref, group_entries) in enumerate(grouped.items(), start=1)
    )


def case_context_ref(case: Any) -> tuple[str, str]:
    memory_scope_ref = case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
    thread_ref = case.thread_external_ref or f"{case.benchmark}-{case.case_id}"
    return memory_scope_ref, thread_ref


def normalize_parallelism(
    value: int,
    *,
    error_factory: BenchmarkValidationErrorFactory,
) -> int:
    if isinstance(value, bool) or value < 1:
        raise error_factory("parallelism must be greater than zero")
    if value > MAX_PUBLIC_BENCHMARK_PARALLELISM:
        raise error_factory(
            "parallelism must be less than or equal to "
            f"{MAX_PUBLIC_BENCHMARK_PARALLELISM}"
        )
    return value
