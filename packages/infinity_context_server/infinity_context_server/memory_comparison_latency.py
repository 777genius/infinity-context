"""Safe server-stage latency telemetry for memory comparison reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from math import isfinite

from infinity_context_core.application.context_stage_diagnostics import (
    CONTEXT_STAGE_NAMES,
    MAX_CONTEXT_STAGE_DURATION_MS,
)

_COMPARISON_STAGE_NAMES = tuple(
    dict.fromkeys(
        (
            *CONTEXT_STAGE_NAMES,
            "canonical_facts",
            "canonical_keyword_search",
            "canonical_keyword_search_fetch",
            "canonical_keyword_search_rank",
            "canonical_anchor_list",
            "canonical_anchor_lookup",
            "derived_collect",
            "keyword_source_sibling_fetch",
            "keyword_source_sibling_group_prioritize",
            "keyword_source_sibling_backfill",
            "keyword_source_sibling_prefilter",
            "keyword_source_sibling_relevance_rank",
            "keyword_source_sibling_select_items",
        )
    )
)
_MAX_SERVER_DIAGNOSTIC_VALUE = 1_000_000_000.0

_CANONICAL_KEYWORD_REQUIRED_DIAGNOSTIC_FIELDS = (
    "canonical_keyword_search_candidate_sql_ms",
    "canonical_keyword_search_candidate_collect_ms",
    "canonical_keyword_search_rank_ms",
    "canonical_keyword_search_hydrate_ms",
    "canonical_keyword_search_domain_map_ms",
    "canonical_keyword_search_candidate_row_count",
    "canonical_keyword_search_unique_candidate_id_count",
    "canonical_keyword_search_rescore_candidate_count",
    "canonical_keyword_search_hydrated_chunk_id_count",
)
_CANONICAL_KEYWORD_LATENCY_FIELDS = (
    "canonical_keyword_search_candidate_sql_ms",
    "canonical_keyword_search_candidate_collect_ms",
    "canonical_keyword_search_rank_ms",
    "canonical_keyword_search_hydrate_ms",
    "canonical_keyword_search_domain_map_ms",
)
_CANONICAL_KEYWORD_WORKLOAD_FIELDS = (
    "canonical_keyword_search_candidate_row_count",
    "canonical_keyword_search_unique_candidate_id_count",
    "canonical_keyword_search_rescore_candidate_count",
    "canonical_keyword_search_hydrated_chunk_id_count",
)
_STATE_PAIR_DIAGNOSTIC_FIELDS = (
    "state_pair_candidates_considered",
    "state_pair_claims_considered",
    "state_pair_reservations_selected",
    "state_pair_missing_slot_count",
)
_COMPARISON_SERVER_DIAGNOSTIC_KEYS = frozenset(
    (*_CANONICAL_KEYWORD_REQUIRED_DIAGNOSTIC_FIELDS, *_STATE_PAIR_DIAGNOSTIC_FIELDS)
)


def aggregate_server_stage_timings(
    diagnostics: Sequence[object],
) -> dict[str, float]:
    """Sum fixed-name server timings across sequential HTTP search requests."""

    totals: defaultdict[str, float] = defaultdict(float)
    for value in _sequence_values(diagnostics):
        stage_timings = _normalize_stage_timings(_mapping(value).get("stage_timings_ms"))
        for stage, duration_ms in stage_timings.items():
            totals[stage] += duration_ms
    return {
        stage: round(min(MAX_CONTEXT_STAGE_DURATION_MS, totals[stage]), 2)
        for stage in _COMPARISON_STAGE_NAMES
        if stage in totals
    }


def aggregate_server_diagnostics(
    diagnostics: Sequence[object],
) -> dict[str, int | float]:
    """Sum allowlisted numeric server diagnostics across sequential HTTP requests."""

    totals: defaultdict[str, float] = defaultdict(float)
    int_only: dict[str, bool] = {}
    for value in _sequence_values(diagnostics):
        for key, raw_number in _normalize_server_diagnostics(value).items():
            totals[key] += float(raw_number)
            int_only[key] = int_only.get(key, True) and isinstance(raw_number, int)
    return {
        key: (
            int(min(_MAX_SERVER_DIAGNOSTIC_VALUE, total))
            if int_only.get(key, False)
            else round(min(_MAX_SERVER_DIAGNOSTIC_VALUE, total), 4)
        )
        for key, total in sorted(totals.items())
    }


def context_server_diagnostic_metrics(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Aggregate safe fixed-name server counters for latency bottleneck reports."""

    by_key: defaultdict[str, list[float]] = defaultdict(list)
    observed_diagnostics: list[dict[str, int | float]] = []
    observed = 0
    evaluation_input_valid = _is_sequence(evaluations)
    evaluation_values = _sequence_values(evaluations)
    invalid_evaluation_count = sum(
        not isinstance(evaluation, Mapping) for evaluation in evaluation_values
    )
    for evaluation in evaluation_values:
        retrieval = _mapping(_mapping(evaluation).get("retrieval"))
        metadata = _mapping(retrieval.get("metadata"))
        diagnostics = _normalize_server_diagnostics(metadata.get("server_diagnostics"))
        if not diagnostics:
            continue
        observed += 1
        observed_diagnostics.append(diagnostics)
        for key, value in diagnostics.items():
            by_key[key].append(float(value))
    fields = {key: _numeric_summary(values) for key, values in sorted(by_key.items())}
    return {
        "schema_version": "memory-comparison-server-diagnostics.v1",
        **_pending_publication_fields(),
        "evaluation_input_valid": evaluation_input_valid,
        "evaluation_count": len(evaluation_values),
        "invalid_evaluation_count": invalid_evaluation_count,
        "observed_evaluation_count": observed,
        "coverage": (round(observed / len(evaluation_values), 4) if evaluation_values else 0.0),
        "fields": fields,
        "top_latency_fields": _top_latency_fields(fields),
        "canonical_keyword_search_coverage": (
            _canonical_keyword_search_coverage_metrics(observed_diagnostics)
        ),
        "state_pair_coverage": _state_pair_coverage_metrics(observed_diagnostics),
    }


def _canonical_keyword_search_coverage_metrics(
    diagnostics_values: Sequence[Mapping[str, int | float]],
) -> dict[str, object]:
    telemetry_count = 0
    complete_count = 0
    missing_field_counts: defaultdict[str, int] = defaultdict(int)
    latency_values: defaultdict[str, list[float]] = defaultdict(list)
    workload_values: defaultdict[str, list[float]] = defaultdict(list)
    for diagnostics in diagnostics_values:
        has_keyword_telemetry = any(
            str(key).startswith("canonical_keyword_search_") for key in diagnostics
        )
        if has_keyword_telemetry:
            telemetry_count += 1
        missing_fields = tuple(
            field
            for field in _CANONICAL_KEYWORD_REQUIRED_DIAGNOSTIC_FIELDS
            if field not in diagnostics
        )
        if missing_fields:
            for field in missing_fields:
                missing_field_counts[field] += 1
        else:
            complete_count += 1
        for field in _CANONICAL_KEYWORD_LATENCY_FIELDS:
            if field in diagnostics:
                latency_values[field].append(_float_value(diagnostics[field]))
        for field in _CANONICAL_KEYWORD_WORKLOAD_FIELDS:
            if field in diagnostics:
                workload_values[field].append(_float_value(diagnostics[field]))
    return {
        "schema_version": "memory-comparison-canonical-keyword-search-coverage.v1",
        "observed_diagnostic_count": len(diagnostics_values),
        "telemetry_evaluation_count": telemetry_count,
        "complete_evaluation_count": complete_count,
        "missing_evaluation_count": max(0, len(diagnostics_values) - complete_count),
        "complete_rate": round(complete_count / len(diagnostics_values), 4)
        if diagnostics_values
        else 0.0,
        "required_fields": list(_CANONICAL_KEYWORD_REQUIRED_DIAGNOSTIC_FIELDS),
        "missing_field_counts": dict(sorted(missing_field_counts.items())),
        "latency_ms": {
            field: _numeric_summary(values) for field, values in sorted(latency_values.items())
        },
        "workload": {
            field: _numeric_summary(values) for field, values in sorted(workload_values.items())
        },
    }


def _state_pair_coverage_metrics(
    diagnostics_values: Sequence[Mapping[str, int | float]],
) -> dict[str, object]:
    telemetry_count = 0
    intent_count = 0
    complete_count = 0
    missing_slot_count = 0
    reservation_counts: list[float] = []
    candidate_counts: list[float] = []
    for diagnostics in diagnostics_values:
        if any(str(key).startswith("state_pair_") for key in diagnostics):
            telemetry_count += 1
        reservations = _float_value(diagnostics.get("state_pair_reservations_selected"))
        missing_slots = _float_value(diagnostics.get("state_pair_missing_slot_count"))
        candidates = _float_value(diagnostics.get("state_pair_candidates_considered"))
        claims = _float_value(diagnostics.get("state_pair_claims_considered"))
        has_intent_evidence = any(
            value > 0.0 for value in (reservations, missing_slots, candidates, claims)
        )
        if not has_intent_evidence:
            continue
        intent_count += 1
        reservation_counts.append(reservations)
        candidate_counts.append(candidates)
        if missing_slots > 0.0:
            missing_slot_count += 1
        else:
            complete_count += 1
    return {
        "schema_version": "memory-comparison-state-pair-coverage.v1",
        "observed_diagnostic_count": len(diagnostics_values),
        "telemetry_evaluation_count": telemetry_count,
        "intent_evaluation_count": intent_count,
        "complete_evaluation_count": complete_count,
        "missing_slot_evaluation_count": missing_slot_count,
        "full_reservation_rate": round(complete_count / intent_count, 4) if intent_count else 0.0,
        "avg_reservations_selected": round(sum(reservation_counts) / intent_count, 4)
        if intent_count
        else 0.0,
        "avg_candidates_considered": round(sum(candidate_counts) / intent_count, 4)
        if intent_count
        else 0.0,
    }


def context_stage_latency_metrics(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Aggregate server stage latency without exposing request-derived labels."""

    by_stage: defaultdict[str, list[float]] = defaultdict(list)
    transport_overhead: list[float] = []
    derived_parallelism_saved: list[float] = []
    observed = 0
    evaluation_input_valid = _is_sequence(evaluations)
    evaluation_values = _sequence_values(evaluations)
    invalid_evaluation_count = sum(
        not isinstance(evaluation, Mapping) for evaluation in evaluation_values
    )
    for evaluation in evaluation_values:
        retrieval = _mapping(_mapping(evaluation).get("retrieval"))
        metadata = _mapping(retrieval.get("metadata"))
        timings = _normalize_stage_timings(metadata.get("server_stage_timings_ms"))
        if not timings:
            continue
        observed += 1
        for stage, duration_ms in timings.items():
            by_stage[stage].append(duration_ms)
        server_total = timings.get("total")
        if server_total is not None:
            transport_overhead.append(
                round(
                    max(
                        0.0,
                        _bounded_float(
                            retrieval.get("latency_ms"),
                            maximum=MAX_CONTEXT_STAGE_DURATION_MS,
                            digits=2,
                        )
                        - server_total,
                    ),
                    2,
                )
            )
        derived_saved = _derived_parallelism_saved_ms(timings)
        if derived_saved is not None:
            derived_parallelism_saved.append(derived_saved)
    stage_summaries = {
        stage: _numeric_summary(by_stage[stage])
        for stage in _COMPARISON_STAGE_NAMES
        if stage in by_stage
    }
    return {
        "schema_version": "memory-comparison-context-stage-latency.v1",
        **_pending_publication_fields(),
        "evaluation_input_valid": evaluation_input_valid,
        "evaluation_count": len(evaluation_values),
        "invalid_evaluation_count": invalid_evaluation_count,
        "observed_evaluation_count": observed,
        "coverage": (round(observed / len(evaluation_values), 4) if evaluation_values else 0.0),
        "stages": stage_summaries,
        "top_bottleneck_stages": _top_bottleneck_stages(stage_summaries),
        "client_transport_overhead_ms": _numeric_summary(transport_overhead),
        "derived_parallelism_saved_ms": _numeric_summary(derived_parallelism_saved),
    }


def _top_latency_fields(
    field_summaries: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key, summary in field_summaries.items():
        if not key.endswith("_ms"):
            continue
        avg_ms = _float_value(summary.get("avg"))
        if avg_ms <= 0:
            continue
        rows.append(
            {
                "field": key,
                "avg_ms": round(avg_ms, 4),
                "max_ms": round(_float_value(summary.get("max")), 4),
            }
        )
    return sorted(rows, key=lambda row: (-float(row["avg_ms"]), str(row["field"])))[:8]


def _top_bottleneck_stages(
    stage_summaries: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    total_avg = _float_value(_mapping(stage_summaries.get("total")).get("avg"))
    rows: list[dict[str, object]] = []
    for stage, summary in stage_summaries.items():
        if stage == "total":
            continue
        avg_ms = _float_value(summary.get("avg"))
        if avg_ms <= 0:
            continue
        row: dict[str, object] = {
            "stage": stage,
            "avg_ms": round(avg_ms, 4),
            "max_ms": round(_float_value(summary.get("max")), 4),
        }
        if total_avg > 0:
            row["share_of_total_avg"] = round(avg_ms / total_avg, 4)
        rows.append(row)
    return sorted(rows, key=lambda row: (-float(row["avg_ms"]), str(row["stage"])))[:8]


def _derived_parallelism_saved_ms(timings: Mapping[str, float]) -> float | None:
    stages = ("vector_collect", "graph_collect", "rag_collect")
    if "derived_collect" not in timings or not all(stage in timings for stage in stages):
        return None
    sequential_ms = sum(timings[stage] for stage in stages)
    return round(max(0.0, sequential_ms - timings["derived_collect"]), 2)


def _float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    if isinstance(value, int):
        return float(min(int(_MAX_SERVER_DIAGNOSTIC_VALUE), max(0, value)))
    number = float(value)
    if not isfinite(number) or number < 0:
        return 0.0
    return min(_MAX_SERVER_DIAGNOSTIC_VALUE, number)


def _normalize_stage_timings(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    return {
        stage: _bounded_float(value[stage], maximum=MAX_CONTEXT_STAGE_DURATION_MS, digits=2)
        for stage in _COMPARISON_STAGE_NAMES
        if stage in value
    }


def _normalize_server_diagnostics(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, int | float] = {}
    for key in sorted(_COMPARISON_SERVER_DIAGNOSTIC_KEYS):
        raw_value = value.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            continue
        if isinstance(raw_value, int):
            normalized[key] = min(int(_MAX_SERVER_DIAGNOSTIC_VALUE), max(0, raw_value))
            continue
        if not isfinite(raw_value):
            continue
        normalized[key] = _bounded_float(
            raw_value,
            maximum=_MAX_SERVER_DIAGNOSTIC_VALUE,
            digits=4,
        )
    return normalized


def _bounded_float(value: object, *, maximum: float, digits: int) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    if isinstance(value, int):
        return round(float(min(int(maximum), max(0, value))), digits)
    number = float(value)
    if not isfinite(number):
        return 0.0
    return round(min(maximum, max(0.0, number)), digits)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _is_sequence(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Sequence)
        and not isinstance(value, str | bytes | bytearray)
    )


def _sequence_values(value: object) -> tuple[object, ...]:
    if not _is_sequence(value):
        return ()
    return tuple(value)


def _numeric_summary(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _pending_publication_fields() -> dict[str, object]:
    return {
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
    }


__all__ = (
    "aggregate_server_diagnostics",
    "aggregate_server_stage_timings",
    "context_server_diagnostic_metrics",
    "context_stage_latency_metrics",
)
