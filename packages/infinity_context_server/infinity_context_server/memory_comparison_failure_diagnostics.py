"""Failure diagnostics for side-by-side memory comparison reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


def failure_diagnostics(evaluation: Mapping[str, object]) -> dict[str, object]:
    retrieval = _mapping(evaluation.get("retrieval"))
    retrieval_quality = _mapping(evaluation.get("retrieval_quality"))
    evidence_bundle = _mapping(evaluation.get("evidence_bundle"))
    generation = _mapping(evaluation.get("generation"))
    judgment = _mapping(evaluation.get("judgment"))
    bundle_planner = _mapping(evidence_bundle.get("bundle_planner"))
    bundle_quality = _mapping(bundle_planner.get("bundle_quality"))
    bundle_items = _bundle_items(evidence_bundle)
    source_refs = tuple(
        dict.fromkeys(
            source_ref
            for item in _retrieval_results(evaluation)
            for source_ref in _str_tuple(item.get("source_refs"))
        )
    )
    missing_required_roles = tuple(
        dict.fromkeys(
            (
                *_str_tuple(evidence_bundle.get("missing_required_roles")),
                *_str_tuple(bundle_quality.get("missing_required_roles")),
            )
        )
    )
    bundle_roles = tuple(
        dict.fromkeys(
            role
            for item in bundle_items
            for role in (
                *_str_tuple(item.get("role")),
                *_str_tuple(item.get("roles")),
            )
        )
    )
    return {
        "schema_version": "memory_comparison_failure_diagnostics.v1",
        "retrieved_item_count": len(_retrieval_results(evaluation)),
        "total_results": int(_metric_value(retrieval, "total_results")),
        "context_token_count": int(_metric_value(retrieval, "context_token_count")),
        "source_ref_count": len(source_refs),
        "retrieval_source_counts": _retrieval_source_counts(evaluation),
        "token_usage": {
            "answerer": _token_usage_mapping(generation),
            "judge": _token_usage_mapping(judgment),
        },
        "cost": {
            "scope": "answerer_judge_token_usage",
            "unmeasured_backend_provider_costs": True,
        },
        "expected_term_recall": _metric_value(
            retrieval_quality,
            "expected_term_recall",
        ),
        "evidence_term_recall": _metric_value(
            retrieval_quality,
            "evidence_term_recall",
        ),
        "missing_expected_terms": _str_tuple(retrieval_quality.get("missing_terms")),
        "missing_evidence_terms": _str_tuple(
            retrieval_quality.get("missing_evidence_terms")
        ),
        "partial_expected_support": _partial_support(
            _metric_value(retrieval_quality, "expected_term_recall")
        ),
        "partial_evidence_support": _partial_support(
            _metric_value(retrieval_quality, "evidence_term_recall")
        ),
        "bundle": {
            "complete": bool(evidence_bundle.get("bundle_complete")),
            "item_count": _positive_int(evidence_bundle.get("item_count"))
            or len(bundle_items),
            "roles": sorted(bundle_roles),
            "missing_required_roles": missing_required_roles,
            "primary_evidence_count": (
                _positive_int(evidence_bundle.get("primary_evidence_count")) or 0
            ),
            "supporting_evidence_count": (
                _positive_int(evidence_bundle.get("supporting_evidence_count")) or 0
            ),
            "confidence_score": round(
                _metric_value(bundle_quality, "confidence_score"),
                6,
            ),
            "confidence_band": str(
                bundle_quality.get("confidence_band") or "unknown"
            ),
            "selected_low_answerability_count": _selected_low_answerability_count(
                bundle_items,
                bundle_quality=bundle_quality,
            ),
            "selected_weak_source_locality_count": (
                _selected_weak_source_locality_count(bundle_items)
            ),
            "reason_codes": _str_tuple(bundle_quality.get("reason_codes")),
        },
    }


def failure_diagnostic_reason_codes(
    evaluation: Mapping[str, object],
    *,
    score: float,
    retrieval_recall: float,
    diagnostics: Mapping[str, object],
) -> list[str]:
    retrieval_quality = _mapping(evaluation.get("retrieval_quality"))
    bundle = _mapping(diagnostics.get("bundle"))
    reason_codes: list[str] = []
    if score < 1.0:
        reason_codes.append("judge_score_below_threshold")
    if retrieval_recall <= 0:
        reason_codes.append("no_expected_term_support")
    elif retrieval_recall < 1.0:
        reason_codes.append("partial_expected_term_support")
    if _str_tuple(retrieval_quality.get("missing_terms")):
        reason_codes.append("missing_expected_terms")
    if _str_tuple(retrieval_quality.get("missing_evidence_terms")):
        reason_codes.append("missing_evidence_refs")
    evidence_recall = _metric_value(retrieval_quality, "evidence_term_recall")
    if 0 < evidence_recall < 1.0:
        reason_codes.append("partial_evidence_ref_support")
    if (_positive_int(diagnostics.get("retrieved_item_count")) or 0) == 0:
        reason_codes.append("no_retrieved_items")
    if not bool(bundle.get("complete")):
        reason_codes.append("bundle_incomplete")
    if _str_tuple(bundle.get("missing_required_roles")):
        reason_codes.append("missing_required_roles")
    if str(bundle.get("confidence_band") or "") in {"none", "low"}:
        reason_codes.append("weak_evidence_bundle")
    if (_positive_int(bundle.get("selected_low_answerability_count")) or 0) > 0:
        reason_codes.append("selected_low_answerability_evidence")
    if (_positive_int(bundle.get("selected_weak_source_locality_count")) or 0) > 0:
        reason_codes.append("selected_weak_source_locality_evidence")
    if any(
        str(reason).startswith("risk:")
        for reason in _str_tuple(bundle.get("reason_codes"))
    ):
        reason_codes.append("bundle_risk_reasons_present")
    return list(dict.fromkeys(reason_codes or ["retrieval_or_judgment_failed"]))


def _retrieval_source_counts(evaluation: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for result in _retrieval_results(evaluation):
        for source in _result_retrieval_sources(result):
            counts[source] += 1
    return dict(sorted(counts.items()))


def _retrieval_results(item: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    retrieval = _mapping(item.get("retrieval"))
    return tuple(
        result
        for result in _sequence(retrieval.get("results"))
        if isinstance(result, Mapping)
    )


def _result_retrieval_sources(result: Mapping[str, object]) -> tuple[str, ...]:
    metadata = _mapping(result.get("metadata"))
    diagnostics = _mapping(metadata.get("diagnostics"))
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, str | bytes):
        return tuple(str(source or "unknown") for source in sources)
    return (str(diagnostics.get("retrieval_source") or "unknown"),)


def _bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in _sequence(bundle.get("items")) if isinstance(item, Mapping))


def _partial_support(value: float) -> bool:
    return 0.0 < value < 1.0


def _selected_low_answerability_count(
    bundle_items: Sequence[Mapping[str, object]],
    *,
    bundle_quality: Mapping[str, object],
) -> int:
    counted_items = sum(
        1
        for item in bundle_items
        if _is_measured_low_answerability(_metric_value(item, "answerability_score"))
    )
    return counted_items or int(
        _metric_value(bundle_quality, "low_answerability_count")
    )


def _selected_weak_source_locality_count(
    bundle_items: Sequence[Mapping[str, object]],
) -> int:
    return sum(
        1
        for item in bundle_items
        if _is_measured_weak_source_locality(
            _metric_value(item, "source_locality_score")
        )
    )


def _is_measured_low_answerability(score: float) -> bool:
    return 0.0 < score < 0.55


def _is_measured_weak_source_locality(score: float) -> bool:
    return 0.0 < score < 0.45


def _token_usage_mapping(stage: Mapping[str, object]) -> dict[str, int]:
    usage = _mapping(stage.get("token_usage"))
    return {
        "prompt_tokens": int(_metric_value(usage, "prompt_tokens")),
        "completion_tokens": int(_metric_value(usage, "completion_tokens")),
        "total_tokens": int(_metric_value(usage, "total_tokens")),
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    return tuple(str(item) for item in _sequence(value) if str(item).strip())


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
