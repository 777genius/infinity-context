"""Failure diagnostics for side-by-side memory comparison reports."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_bundle_item as _source_refs_from_bundle_item,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_memory as _source_refs_from_memory,
)
from infinity_context_server.memory_comparison_temporal_grounding import (
    temporal_grounding_table as _temporal_grounding_table,
)

_TURN_REF_RE = re.compile(
    r"\b(?:(?P<session>session_\d+):)?D(?P<source>\d+):(?P<turn>\d+)\b",
    re.IGNORECASE,
)
_MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES = 5
_MAX_MISSING_EVIDENCE_SOURCE_IDS = 12
_MAX_MISSING_EVIDENCE_REF_WINDOWS = 8
_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+:\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session_\d+):"
    r"(?P<session_turn_ref>D\d+:\d+))$",
    re.IGNORECASE,
)
_MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_REFS = 8
_MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_ITEMS = 8
_MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_REFS_PER_ITEM = 4


def failure_diagnostics(evaluation: Mapping[str, object]) -> dict[str, object]:
    retrieval = _mapping(evaluation.get("retrieval"))
    retrieval_quality = _mapping(evaluation.get("retrieval_quality"))
    evidence_bundle = _mapping(evaluation.get("evidence_bundle"))
    generation = _mapping(evaluation.get("generation"))
    judgment = _mapping(evaluation.get("judgment"))
    answer_context = _primary_answer_context(evaluation)
    bundle_planner = _mapping(evidence_bundle.get("bundle_planner"))
    bundle_quality = _mapping(bundle_planner.get("bundle_quality"))
    bundle_items = _bundle_items(evidence_bundle)
    bundle_source_ref_stats = _selected_bundle_source_ref_stats(
        bundle_items,
        bundle_quality=bundle_quality,
    )
    source_refs = tuple(
        dict.fromkeys(
            source_ref
            for item in _retrieval_results(evaluation)
            for source_ref in _result_source_refs(item)
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
        "missing_evidence_source_locality": _missing_evidence_source_locality(
            _str_tuple(retrieval_quality.get("missing_evidence_terms")),
            retrieval_results=_retrieval_results(evaluation),
            bundle_items=bundle_items,
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
            **bundle_source_ref_stats,
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
                _selected_weak_source_locality_count(
                    bundle_items,
                    bundle_quality=bundle_quality,
                )
            ),
            "reason_codes": _str_tuple(bundle_quality.get("reason_codes")),
        },
        "answer_context": _answer_context_failure_summary(answer_context),
        "temporal_grounding": _temporal_grounding_failure_summary(evaluation),
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
    missing_evidence_locality = _mapping(
        diagnostics.get("missing_evidence_source_locality")
    )
    if (_positive_int(missing_evidence_locality.get("missing_turn_ref_count")) or 0) > 0:
        if (
            _positive_int(missing_evidence_locality.get("source_absent_count")) or 0
        ) > 0:
            reason_codes.append("missing_evidence_source_absent")
        if (
            _positive_int(missing_evidence_locality.get("near_retrieved_window_count"))
            or 0
        ) > 0:
            reason_codes.append("missing_evidence_source_window_miss")
        elif (
            _positive_int(missing_evidence_locality.get("same_source_missing_count"))
            or 0
        ) > 0:
            reason_codes.append("missing_evidence_same_source_miss")
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
    if (
        _positive_int(bundle.get("selected_bundle_source_refless_item_count")) or 0
    ) > 0:
        reason_codes.append("selected_bundle_source_refless_evidence")
    temporal_grounding = _mapping(diagnostics.get("temporal_grounding"))
    if (
        _positive_int(temporal_grounding.get("issue_item_count")) or 0
    ) > 0:
        reason_codes.append("selected_temporal_grounding_issues")
    if any(
        str(reason).startswith("risk:")
        for reason in _str_tuple(bundle.get("reason_codes"))
    ):
        reason_codes.append("bundle_risk_reasons_present")
    answer_context = _mapping(diagnostics.get("answer_context"))
    if answer_context.get("present") is True:
        if str(answer_context.get("source") or "") == "retrieval_slice" or str(
            answer_context.get("fallback_reason") or ""
        ):
            reason_codes.append("answer_context_fallback")
        if (
            (_positive_int(answer_context.get("source_refless_item_count")) or 0) > 0
            or (
                (_positive_int(answer_context.get("memory_count")) or 0) > 0
                and _metric_value(answer_context, "source_ref_coverage_rate") <= 0
            )
        ):
            reason_codes.append("answer_context_source_refless")
        if answer_context.get("role_requirement_complete") is False:
            reason_codes.append("answer_context_missing_required_roles")
        if (
            _positive_int(answer_context.get("backfilled_retrieval_item_count")) or 0
        ) > 0:
            reason_codes.append("answer_context_backfilled_retrieval")
        if _str_tuple(answer_context.get("risk_reason_codes")):
            reason_codes.append("answer_context_risk_reasons_present")
    return list(dict.fromkeys(reason_codes or ["retrieval_or_judgment_failed"]))


def _temporal_grounding_failure_summary(
    evaluation: Mapping[str, object],
) -> dict[str, object]:
    table = _temporal_grounding_table((evaluation,))
    issue_sample_limit = (
        _positive_int(table.get("selected_temporal_grounding_issue_sample_limit"))
        or _MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES
    )
    issue_samples = list(
        _sequence(table.get("selected_temporal_grounding_issue_samples"))
    )[:_MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES]
    issue_sample_count = _positive_int(
        table.get("selected_temporal_grounding_issue_sample_count")
    ) or len(issue_samples)
    issue_item_count = (
        _positive_int(table.get("selected_temporal_grounding_issue_item_count"))
        or 0
    )
    return {
        "schema_version": "failure_temporal_grounding.v1",
        "temporal_case": _positive_int(table.get("temporal_case_count")) is not None,
        "selected_item_count": _positive_int(table.get("selected_item_count")) or 0,
        "strong_item_count": (
            _positive_int(table.get("selected_strong_temporal_grounding_item_count"))
            or 0
        ),
        "issue_item_count": issue_item_count,
        "issue_reason_counts": _mapping(
            table.get("selected_temporal_grounding_issue_reason_counts")
        ),
        "issue_sample_limit": min(
            issue_sample_limit,
            _MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES,
        ),
        "issue_sample_count": min(
            issue_sample_count,
            _MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES,
        ),
        "issue_sample_omitted_count": max(
            0,
            issue_item_count
            - min(issue_sample_count, _MAX_TEMPORAL_GROUNDING_ISSUE_SAMPLES),
        ),
        "issue_samples": issue_samples,
    }


def _primary_answer_context(
    evaluation: Mapping[str, object],
) -> tuple[int | str | None, Mapping[str, object]] | None:
    direct_context = _mapping(evaluation.get("answer_context"))
    if direct_context:
        return None, direct_context

    contexts: list[tuple[int, str, Mapping[str, object]]] = []
    for cutoff, payload in _mapping(evaluation.get("cutoff_results")).items():
        context = _mapping(_mapping(payload).get("answer_context"))
        if not context:
            continue
        contexts.append((_positive_int(cutoff) or -1, str(cutoff), context))
    if not contexts:
        return None

    numeric_cutoff, cutoff_label, context = max(
        contexts,
        key=lambda item: (item[0], item[1]),
    )
    return (numeric_cutoff if numeric_cutoff >= 0 else cutoff_label), context


def _answer_context_failure_summary(
    answer_context: tuple[int | str | None, Mapping[str, object]] | None,
) -> dict[str, object]:
    if answer_context is None:
        return {"present": False}

    cutoff, context = answer_context
    risk_reason_codes = tuple(
        dict.fromkeys(
            (
                *_str_tuple(context.get("risk_reason_codes")),
                *_str_tuple(context.get("bundle_risk_reason_codes")),
            )
        )
    )
    source_identity_refs = _safe_source_identity_refs(
        context.get("source_identity_refs")
    )
    source_identity_items = _safe_source_identity_items(
        context.get("source_identity_items")
    )
    return {
        "present": True,
        "cutoff": cutoff,
        "source": str(context.get("source") or "unknown"),
        "fallback_reason": str(context.get("fallback_reason") or "") or None,
        "memory_count": _positive_int(context.get("memory_count")) or 0,
        "source_ref_count": _positive_int(context.get("source_ref_count")) or 0,
        "source_ref_item_count": _positive_int(context.get("source_ref_item_count")) or 0,
        "source_refless_item_count": (
            _positive_int(context.get("source_refless_item_count")) or 0
        ),
        "source_identity_ref_count": (
            _positive_int(context.get("source_identity_ref_count"))
            or len(source_identity_refs)
        ),
        "source_identity_item_count": (
            _positive_int(context.get("source_identity_item_count"))
            or len(source_identity_items)
        ),
        "source_identity_refs": source_identity_refs,
        "source_identity_items": source_identity_items,
        "source_ref_coverage_rate": _metric_value(context, "source_ref_coverage_rate"),
        "selected_bundle_item_count": (
            _positive_int(context.get("selected_bundle_item_count")) or 0
        ),
        "skipped_bundle_item_count": (
            _positive_int(context.get("skipped_bundle_item_count")) or 0
        ),
        "backfilled_retrieval_item_count": (
            _positive_int(context.get("backfilled_retrieval_item_count")) or 0
        ),
        "role_requirement_complete": (
            context.get("role_requirement_complete")
            if isinstance(context.get("role_requirement_complete"), bool)
            else None
        ),
        "missing_required_roles": _str_tuple(context.get("missing_required_roles")),
        "risk_reason_codes": risk_reason_codes,
        "item_ids": _str_tuple(context.get("item_ids"))[:8],
        "retrieval_orders": tuple(
            order
            for raw_order in _sequence(context.get("retrieval_orders"))
            for order in (_positive_int(raw_order),)
            if order is not None
        )[:8],
    }


def _safe_source_identity_refs(value: object, *, limit: int | None = None) -> tuple[str, ...]:
    bounded_limit = limit or _MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_REFS
    refs = tuple(
        dict.fromkeys(
            ref
            for raw_ref in _sequence(value)
            for ref in (_safe_source_identity_ref(raw_ref),)
            if ref
        )
    )
    return refs[:bounded_limit]


def _safe_source_identity_items(value: object) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    for raw_item in _sequence(value):
        item = _mapping(raw_item)
        if not item:
            continue
        refs = _safe_source_identity_refs(
            item.get("source_identity_refs"),
            limit=_MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_REFS_PER_ITEM,
        )
        if not refs:
            continue
        payload: dict[str, object] = {"source_identity_refs": refs}
        item_id = _bounded_string(item.get("item_id"), limit=120)
        if item_id:
            payload["item_id"] = item_id
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is not None:
            payload["retrieval_order"] = retrieval_order
        items.append(payload)
        if len(items) >= _MAX_ANSWER_CONTEXT_SOURCE_IDENTITY_ITEMS:
            break
    return tuple(items)


def _safe_source_identity_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > 80:
        return None
    match = _SAFE_SOURCE_IDENTITY_REF_RE.fullmatch(ref)
    if match is None:
        return None
    if match.group("turn_ref"):
        return f"source_turn_refs:{match.group('turn_ref').upper()}"
    return (
        "source_session_turn_refs:"
        f"{match.group('session').lower()}:{match.group('session_turn_ref').upper()}"
    )


def _bounded_string(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:limit]


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


def _missing_evidence_source_locality(
    missing_evidence_terms: Sequence[str],
    *,
    retrieval_results: Sequence[Mapping[str, object]],
    bundle_items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    missing_refs = _turn_refs(missing_evidence_terms)
    retrieval_turns = _source_turns(
        source_ref
        for result in retrieval_results
        for source_ref in _result_source_refs(result)
    )
    bundle_turns = _source_turns(
        source_ref
        for item in bundle_items
        for source_ref in _bundle_item_source_refs(item)
    )
    windows = [
        _missing_ref_window(ref, retrieval_turns=retrieval_turns, bundle_turns=bundle_turns)
        for ref in missing_refs
    ]
    retrieved_source_ids = sorted(retrieval_turns)
    bundle_source_ids = sorted(bundle_turns)
    same_source_missing_count = sum(
        1 for window in windows if window["retrieved_same_source"] is True
    )
    near_retrieved_window_count = sum(
        1
        for window in windows
        if (
            isinstance(window.get("nearest_retrieved_turn_distance"), int)
            and int(window["nearest_retrieved_turn_distance"]) <= 2
        )
    )
    cause_counts: dict[str, int] = defaultdict(int)
    for window in windows:
        cause_counts[str(window.get("cause") or "unknown")] += 1
    return {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": len(missing_refs),
        "retrieved_source_id_count": len(retrieved_source_ids),
        "retrieved_source_ids": retrieved_source_ids[:_MAX_MISSING_EVIDENCE_SOURCE_IDS],
        "bundle_source_id_count": len(bundle_source_ids),
        "bundle_source_ids": bundle_source_ids[:_MAX_MISSING_EVIDENCE_SOURCE_IDS],
        "same_source_missing_count": same_source_missing_count,
        "near_retrieved_window_count": near_retrieved_window_count,
        "source_absent_count": len(missing_refs) - same_source_missing_count,
        "cause_counts": dict(sorted(cause_counts.items())),
        "missing_ref_window_count": len(windows),
        "missing_ref_window_omitted_count": max(
            0,
            len(windows) - _MAX_MISSING_EVIDENCE_REF_WINDOWS,
        ),
        "missing_ref_windows": windows[:_MAX_MISSING_EVIDENCE_REF_WINDOWS],
    }


def _missing_ref_window(
    ref: tuple[str, int],
    *,
    retrieval_turns: Mapping[str, tuple[int, ...]],
    bundle_turns: Mapping[str, tuple[int, ...]],
) -> dict[str, object]:
    source_id, turn = ref
    nearest_retrieved = _nearest_turn(source_id, turn, retrieval_turns)
    nearest_bundle = _nearest_turn(source_id, turn, bundle_turns)
    window: dict[str, object] = {
        "ref": f"{source_id}:{turn}",
        "source_id": source_id,
        "retrieved_same_source": source_id in retrieval_turns,
        "bundle_same_source": source_id in bundle_turns,
    }
    if nearest_retrieved is not None:
        nearest_turn, distance = nearest_retrieved
        window["nearest_retrieved_turn_ref"] = f"{source_id}:{nearest_turn}"
        window["nearest_retrieved_turn_distance"] = distance
    if nearest_bundle is not None:
        nearest_turn, distance = nearest_bundle
        window["nearest_bundle_turn_ref"] = f"{source_id}:{nearest_turn}"
        window["nearest_bundle_turn_distance"] = distance
    if nearest_retrieved is None:
        window["cause"] = "source_absent"
    elif nearest_retrieved[1] <= 2:
        window["cause"] = "near_retrieved_window"
    else:
        window["cause"] = "same_source_miss"
    return window


def _nearest_turn(
    source_id: str,
    turn: int,
    source_turns: Mapping[str, tuple[int, ...]],
) -> tuple[int, int] | None:
    turns = source_turns.get(source_id)
    if not turns:
        return None
    nearest = min(turns, key=lambda candidate: (abs(candidate - turn), candidate))
    return nearest, abs(nearest - turn)


def _source_turns(values: Iterable[str]) -> dict[str, tuple[int, ...]]:
    turns_by_source: dict[str, set[int]] = defaultdict(set)
    for source_id, turn in _turn_refs(values):
        turns_by_source[source_id].add(turn)
    return {
        source_id: tuple(sorted(turns))
        for source_id, turns in sorted(turns_by_source.items())
    }


def _turn_refs(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    refs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        for match in _TURN_REF_RE.finditer(str(value)):
            source_id = f"D{match.group('source')}"
            session_id = str(match.group("session") or "").strip().lower()
            if session_id:
                source_id = f"{session_id}:{source_id}"
            ref = (source_id, int(match.group("turn")))
            if ref in seen:
                continue
            refs.append(ref)
            seen.add(ref)
    return tuple(refs)


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
    *,
    bundle_quality: Mapping[str, object],
) -> int:
    counted_items = sum(
        1
        for item in bundle_items
        if _is_measured_weak_source_locality(
            _metric_value(item, "source_locality_score")
        )
    )
    return counted_items or int(
        _metric_value(bundle_quality, "weak_source_locality_count")
    )


def _selected_bundle_source_ref_stats(
    bundle_items: Sequence[Mapping[str, object]],
    *,
    bundle_quality: Mapping[str, object],
) -> dict[str, object]:
    item_ref_counts = [len(_bundle_item_source_refs(item)) for item in bundle_items]
    source_ref_item_count = sum(1 for count in item_ref_counts if count > 0)
    source_ref_count = len(
        tuple(
            dict.fromkeys(
                source_ref
                for item in bundle_items
                for source_ref in _bundle_item_source_refs(item)
            )
        )
    )
    source_refless_item_count = len(bundle_items) - source_ref_item_count
    if not bundle_items:
        source_ref_item_count = (
            _positive_int(bundle_quality.get("selected_bundle_source_ref_item_count"))
            or _positive_int(bundle_quality.get("source_ref_item_count"))
            or 0
        )
        source_ref_count = (
            _positive_int(bundle_quality.get("selected_bundle_source_ref_count"))
            or _positive_int(bundle_quality.get("source_ref_count"))
            or 0
        )
        source_refless_item_count = (
            _positive_int(
                bundle_quality.get("selected_bundle_source_refless_item_count")
            )
            or _positive_int(bundle_quality.get("source_refless_item_count"))
            or 0
        )
    return {
        "selected_bundle_source_ref_count": source_ref_count,
        "selected_bundle_source_ref_item_count": source_ref_item_count,
        "selected_bundle_source_refless_item_count": source_refless_item_count,
        "selected_bundle_source_ref_coverage_rate": _ratio(
            source_ref_item_count,
            len(bundle_items) or source_ref_item_count + source_refless_item_count,
        ),
    }


def _result_source_refs(result: Mapping[str, object]) -> tuple[str, ...]:
    return _str_tuple(result.get("source_refs")) or _source_refs_from_memory(result)


def _bundle_item_source_refs(item: Mapping[str, object]) -> tuple[str, ...]:
    return _str_tuple(item.get("source_refs")) or _source_refs_from_bundle_item(item)


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


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
