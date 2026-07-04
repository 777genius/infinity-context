"""Summarize LoCoMo public benchmark failures from an existing report.

The script is intentionally report-only: it does not inspect datasets or answers
outside the benchmark output, so it can be used for targeted reruns without
introducing benchmark leakage into application code.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

_BOUNDED_LIST_COUNT_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b"
)
_LIST_QUESTION_MARKERS = (
    " activities",
    " areas",
    " books",
    " cities",
    " countries",
    " events",
    " friends",
    " hobbies",
    " items",
    " people",
    " places",
    " projects",
    " reasons",
    " restaurants",
    " songs",
    " things",
    " ways",
)
_MAX_TEMPORAL_GROUNDING_EXAMPLES = 5
_MAX_TEMPORAL_GROUNDING_SAMPLE_EXAMPLES = 2
_TEMPORAL_GROUNDING_SAMPLE_KEYS = (
    "case_id",
    "group",
    "item_id",
    "role",
    "query_roles",
    "source_refs",
    "issue_reasons",
    "grounding_signals",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary-out", type=Path, default=None)
    parser.add_argument("--case-id-out", type=Path, default=None)
    parser.add_argument("--benchmark-args-out", type=Path, default=None)
    parser.add_argument(
        "--capability",
        action="append",
        default=None,
        help=(
            "Include only matching capabilities/categories. Can be repeated or "
            "comma-separated, for example locomo_category_1,category_3."
        ),
    )
    parser.add_argument(
        "--reason",
        action="append",
        default=None,
        help="Include only matching failure reasons. Can be repeated or comma-separated.",
    )
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit selected failures after filtering; useful for small canary reruns.",
    )
    args = parser.parse_args(argv)

    report = _load_report(args.report)
    failures = _filter_failures(
        _failures(report),
        capabilities=_normalize_filters(args.capability),
        reasons=_normalize_filters(args.reason),
    )
    if args.limit is not None:
        failures = failures[: max(0, args.limit)]
    case_ids = [str(item.get("case_id") or "") for item in failures if item.get("case_id")]
    if args.case_id_out is not None:
        args.case_id_out.parent.mkdir(parents=True, exist_ok=True)
        args.case_id_out.write_text(
            "\n".join(case_ids) + ("\n" if case_ids else ""),
            encoding="utf-8",
        )
    if args.benchmark_args_out is not None:
        args.benchmark_args_out.parent.mkdir(parents=True, exist_ok=True)
        args.benchmark_args_out.write_text(_benchmark_args(case_ids), encoding="utf-8")

    summary = _summary(failures, top=args.top)
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _load_report(path: Path) -> Mapping[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise SystemExit(f"report must be a JSON object: {path}")
    return value


def _failures(report: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    failures = report.get("failures")
    if isinstance(failures, list):
        return tuple(item for item in failures if isinstance(item, Mapping))
    cases = report.get("cases")
    if isinstance(cases, list):
        return tuple(
            item
            for item in cases
            if isinstance(item, Mapping) and str(item.get("status") or "") != "ok"
        )
    return ()


def _summary(failures: Sequence[Mapping[str, object]], *, top: int) -> dict[str, object]:
    capabilities: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    missing_terms: Counter[str] = Counter()
    missing_evidence_refs: Counter[str] = Counter()
    missing_evidence_ref_previews: Counter[str] = Counter()
    capability_reasons: dict[str, Counter[str]] = defaultdict(Counter)
    answer_shapes: Counter[str] = Counter()
    answer_shape_components: Counter[str] = Counter()
    failure_patterns: Counter[tuple[str, str]] = Counter()
    query_patterns: Counter[str] = Counter()
    query_pattern_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    primary_root_causes: Counter[str] = Counter()
    root_cause_tags: Counter[str] = Counter()
    root_cause_examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    provenance_gap_causes: Counter[str] = Counter()
    answer_context_provenance: Counter[str] = Counter()
    temporal_grounding_issue_reasons: Counter[str] = Counter()
    temporal_grounding_issue_examples: dict[str, list[dict[str, object]]] = (
        defaultdict(list)
    )
    for failure in failures:
        capability = str(failure.get("capability") or failure.get("category") or "unknown")
        reason = str(failure.get("reason") or "unknown")
        answer_shape = _answer_shape(failure)
        root_tags = _root_cause_tags(failure)
        primary_root_cause = root_tags[0]
        capabilities[capability] += 1
        reasons[reason] += 1
        capability_reasons[capability][reason] += 1
        answer_shapes[answer_shape] += 1
        answer_shape_components.update(_answer_shape_components(failure))
        primary_root_causes[primary_root_cause] += 1
        root_cause_tags.update(root_tags)
        provenance_gap_causes.update(_provenance_gap_cause_counts(failure))
        answer_context_provenance.update(
            _answer_context_provenance_counts(failure)
        )
        if len(root_cause_examples[primary_root_cause]) < 5:
            root_cause_examples[primary_root_cause].append(
                _root_cause_example(failure, root_tags)
            )
        temporal_counts = _temporal_grounding_issue_reason_counts(failure)
        temporal_grounding_issue_reasons.update(temporal_counts)
        for issue_reason in temporal_counts:
            examples = temporal_grounding_issue_examples[issue_reason]
            if len(examples) < _MAX_TEMPORAL_GROUNDING_EXAMPLES:
                examples.append(_temporal_grounding_issue_example(failure, issue_reason))
        patterns = _query_patterns(failure)
        query_patterns.update(patterns)
        question = _question_text(failure)
        case_id = str(failure.get("case_id") or "")
        for pattern in patterns:
            if question and len(query_pattern_examples[pattern]) < 5:
                query_pattern_examples[pattern].append(
                    {"case_id": case_id, "question": question}
                )
        failure_patterns[(capability, reason)] += 1
        missing_terms.update(_strings(failure.get("missing_terms")))
        missing_evidence_refs.update(_missing_evidence_refs(failure))
        missing_evidence_ref_previews.update(
            _strings(failure.get("missing_evidence_ref_previews"))
        )

    return {
        "failure_count": len(failures),
        "case_ids": [str(item.get("case_id")) for item in failures[:top] if item.get("case_id")],
        "capability_failure_count": dict(capabilities.most_common()),
        "reason_count": dict(reasons.most_common()),
        "answer_shape_count": dict(answer_shapes.most_common()),
        "answer_shape_component_count": dict(answer_shape_components.most_common()),
        "failure_pattern_count": {
            f"{capability}:{reason}": count
            for (capability, reason), count in failure_patterns.most_common(top)
        },
        "primary_root_cause_count": dict(primary_root_causes.most_common(top)),
        "root_cause_tag_count": dict(root_cause_tags.most_common(top)),
        "provenance_gap_cause_count": dict(provenance_gap_causes.most_common(top)),
        "answer_context_provenance_count": dict(
            answer_context_provenance.most_common(top)
        ),
        "root_cause_examples": {
            root_cause: examples
            for root_cause, examples in sorted(root_cause_examples.items())
        },
        "temporal_grounding_issue_reason_count": dict(
            temporal_grounding_issue_reasons.most_common(top)
        ),
        "temporal_grounding_issue_examples": {
            issue_reason: examples
            for issue_reason, examples in sorted(
                temporal_grounding_issue_examples.items()
            )
        },
        "query_pattern_count": dict(query_patterns.most_common(top)),
        "query_pattern_examples": {
            pattern: examples
            for pattern, examples in sorted(query_pattern_examples.items())
        },
        "capability_reason_count": {
            capability: dict(counter.most_common())
            for capability, counter in sorted(capability_reasons.items())
        },
        "top_missing_terms": dict(missing_terms.most_common(top)),
        "top_missing_evidence_refs": dict(missing_evidence_refs.most_common(top)),
        "top_missing_evidence_ref_previews": dict(
            missing_evidence_ref_previews.most_common(top)
        ),
    }


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


def _missing_evidence_refs(failure: Mapping[str, object]) -> tuple[str, ...]:
    direct = _strings(failure.get("missing_evidence_refs"))
    if direct:
        return direct
    diagnostics = _mapping(failure.get("diagnostics"))
    return _strings(diagnostics.get("missing_evidence_terms"))


def _diagnostic_reason_codes(failure: Mapping[str, object]) -> tuple[str, ...]:
    return _strings(failure.get("diagnostic_reason_codes"))


def _root_cause_tags(failure: Mapping[str, object]) -> tuple[str, ...]:
    reason_codes = set(_diagnostic_reason_codes(failure))
    diagnostics = _mapping(failure.get("diagnostics"))
    bundle = _mapping(diagnostics.get("bundle"))
    tags: list[str] = []
    if "no_retrieved_items" in reason_codes:
        tags.append("retrieval:no_retrieved_items")
    if "no_expected_term_support" in reason_codes:
        tags.append("retrieval:no_expected_term_support")
    elif "partial_expected_term_support" in reason_codes:
        tags.append("retrieval:partial_expected_term_support")
    if "missing_evidence_refs" in reason_codes:
        tags.append("evidence:missing_refs")
        missing_locality = _mapping(
            diagnostics.get("missing_evidence_source_locality")
        )
        if (
            _positive_int(missing_locality.get("source_absent_count")) or 0
        ) > 0:
            tags.append("evidence:missing_source_absent")
        if (
            _positive_int(missing_locality.get("near_retrieved_window_count")) or 0
        ) > 0:
            tags.append("evidence:source_window_miss")
        elif (
            _positive_int(missing_locality.get("same_source_missing_count")) or 0
        ) > 0:
            tags.append("evidence:same_source_miss")
    elif "partial_evidence_ref_support" in reason_codes:
        tags.append("evidence:partial_refs")
    if "selected_low_answerability_evidence" in reason_codes:
        tags.append("evidence:selected_low_answerability")
    if "selected_weak_source_locality_evidence" in reason_codes:
        tags.append("evidence:selected_weak_source_locality")
    if "selected_bundle_source_refless_evidence" in reason_codes:
        tags.append("evidence:selected_bundle_source_refless")
    temporal_grounding_counts = _temporal_grounding_issue_reason_counts(failure)
    if temporal_grounding_counts:
        tags.append("temporal_grounding:issue")
    for reason in temporal_grounding_counts:
        tags.append(f"temporal_grounding:{_normalize_tag_value(reason)}")
    if "answer_context_fallback" in reason_codes:
        tags.append("answer_context:fallback")
    if "answer_context_source_refless" in reason_codes:
        tags.append("answer_context:source_refless")
    if "answer_context_missing_required_roles" in reason_codes:
        tags.append("answer_context:missing_required_roles")
    if "answer_context_backfilled_retrieval" in reason_codes:
        tags.append("answer_context:backfilled_retrieval")
    if "answer_context_risk_reasons_present" in reason_codes:
        tags.append("answer_context:risk_reasons")
    for role in _strings(bundle.get("missing_required_roles")):
        tags.append(f"bundle:missing_role:{_normalize_tag_value(role)}")
    if "bundle_incomplete" in reason_codes:
        tags.append("bundle:incomplete")
    if "weak_evidence_bundle" in reason_codes:
        tags.append("bundle:weak")
    for reason in _strings(bundle.get("reason_codes")):
        if reason.startswith("risk:"):
            tags.append(f"bundle:{_normalize_tag_value(reason)}")
    if "judge_score_below_threshold" in reason_codes:
        tags.append("judgment:score_below_threshold")
    if not tags:
        tags.append(f"reason:{_normalize_tag_value(_reason_key(failure))}")
    return tuple(dict.fromkeys(tags))


def _root_cause_example(
    failure: Mapping[str, object],
    root_tags: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": str(failure.get("case_id") or ""),
        "capability": str(
            failure.get("capability") or failure.get("category") or "unknown"
        ),
        "reason": str(failure.get("reason") or "unknown"),
        "root_cause_tags": list(root_tags),
    }
    question = _question_text(failure)
    if question:
        payload["question"] = question
    diagnostic_reason_codes = _diagnostic_reason_codes(failure)
    if diagnostic_reason_codes:
        payload["diagnostic_reason_codes"] = list(diagnostic_reason_codes)
    bundle = _mapping(_mapping(failure.get("diagnostics")).get("bundle"))
    missing_roles = _strings(bundle.get("missing_required_roles"))
    if missing_roles:
        payload["missing_required_roles"] = list(missing_roles)
    missing_evidence_refs = _missing_evidence_refs(failure)
    if missing_evidence_refs:
        payload["missing_evidence_ref_count"] = len(missing_evidence_refs)
    missing_locality = _missing_evidence_source_locality_summary(failure)
    if missing_locality:
        payload["missing_evidence_source_locality"] = missing_locality
    selected_weakness = _selected_evidence_weakness_summary(failure)
    if selected_weakness:
        payload["selected_evidence_weakness"] = selected_weakness
    answer_context = _answer_context_summary(failure)
    if answer_context:
        payload["answer_context"] = answer_context
    temporal_grounding = _temporal_grounding_summary(failure)
    if temporal_grounding:
        payload["temporal_grounding"] = temporal_grounding
    return payload


def _missing_evidence_source_locality_summary(
    failure: Mapping[str, object],
) -> dict[str, object] | None:
    locality = _mapping(
        _mapping(failure.get("diagnostics")).get("missing_evidence_source_locality")
    )
    if not locality:
        return None
    summary = {
        "missing_turn_ref_count": _positive_int(locality.get("missing_turn_ref_count"))
        or 0,
        "same_source_missing_count": _positive_int(
            locality.get("same_source_missing_count")
        )
        or 0,
        "near_retrieved_window_count": _positive_int(
            locality.get("near_retrieved_window_count")
        )
        or 0,
        "source_absent_count": _positive_int(locality.get("source_absent_count")) or 0,
    }
    cause_counts = _provenance_gap_cause_counts(failure)
    if cause_counts:
        summary["cause_counts"] = dict(cause_counts)
    return summary if any(summary.values()) else None


def _provenance_gap_cause_counts(failure: Mapping[str, object]) -> Counter[str]:
    locality = _mapping(
        _mapping(failure.get("diagnostics")).get("missing_evidence_source_locality")
    )
    if not locality:
        return Counter()
    cause_counts = Counter(
        {
            str(cause): count
            for cause, count in _count_mapping(locality.get("cause_counts")).items()
            if count > 0
        }
    )
    if cause_counts:
        return cause_counts

    source_absent_count = _positive_int(locality.get("source_absent_count")) or 0
    near_retrieved_window_count = (
        _positive_int(locality.get("near_retrieved_window_count")) or 0
    )
    same_source_count = _positive_int(locality.get("same_source_missing_count")) or 0
    same_source_miss_count = max(same_source_count - near_retrieved_window_count, 0)
    return Counter(
        {
            cause: count
            for cause, count in {
                "source_absent": source_absent_count,
                "near_retrieved_window": near_retrieved_window_count,
                "same_source_miss": same_source_miss_count,
            }.items()
            if count > 0
        }
    )


def _count_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        count = _positive_int(raw_count) or 0
        if count > 0:
            counts[str(key)] = count
    return counts


def _answer_context_summary(failure: Mapping[str, object]) -> dict[str, object] | None:
    context = _mapping(_mapping(failure.get("diagnostics")).get("answer_context"))
    if context.get("present") is not True:
        return None
    summary: dict[str, object] = {
        "source": str(context.get("source") or "unknown"),
        "memory_count": _positive_int(context.get("memory_count")) or 0,
        "source_ref_item_count": _positive_int(context.get("source_ref_item_count"))
        or 0,
        "source_refless_item_count": _positive_int(
            context.get("source_refless_item_count")
        )
        or 0,
        "backfilled_retrieval_item_count": _positive_int(
            context.get("backfilled_retrieval_item_count")
        )
        or 0,
    }
    source_ref_count = _positive_int(context.get("source_ref_count")) or 0
    if source_ref_count:
        summary["source_ref_count"] = source_ref_count
    source_identity_ref_count = (
        _positive_int(context.get("source_identity_ref_count")) or 0
    )
    if source_identity_ref_count:
        summary["source_identity_ref_count"] = source_identity_ref_count
    source_identity_item_count = (
        _positive_int(context.get("source_identity_item_count")) or 0
    )
    if source_identity_item_count:
        summary["source_identity_item_count"] = source_identity_item_count
    fallback_reason = str(context.get("fallback_reason") or "")
    if fallback_reason:
        summary["fallback_reason"] = fallback_reason
    missing_roles = _strings(context.get("missing_required_roles"))
    if missing_roles:
        summary["missing_required_roles"] = list(missing_roles)
    risk_reasons = _strings(context.get("risk_reason_codes"))
    if risk_reasons:
        summary["risk_reason_codes"] = list(risk_reasons)
    return summary


def _answer_context_provenance_counts(failure: Mapping[str, object]) -> Counter[str]:
    context = _mapping(_mapping(failure.get("diagnostics")).get("answer_context"))
    if context.get("present") is not True:
        return Counter()
    source_ref_item_count = _positive_int(context.get("source_ref_item_count")) or 0
    source_refless_item_count = (
        _positive_int(context.get("source_refless_item_count")) or 0
    )
    source_identity_ref_count = (
        _positive_int(context.get("source_identity_ref_count")) or 0
    )
    source_identity_item_count = (
        _positive_int(context.get("source_identity_item_count")) or 0
    )
    backfilled_count = (
        _positive_int(context.get("backfilled_retrieval_item_count")) or 0
    )
    counts = Counter({"present": 1})
    if source_ref_item_count > 0:
        counts["source_refs_present"] += 1
    if source_refless_item_count > 0:
        counts["source_refless_items_present"] += 1
    if source_identity_ref_count > 0:
        counts["source_identity_refs_present"] += 1
    if source_identity_item_count > 0:
        counts["source_identity_items_present"] += 1
    if str(context.get("fallback_reason") or ""):
        counts["fallback_present"] += 1
    if backfilled_count > 0:
        counts["backfilled_retrieval_present"] += 1
    if context.get("role_requirement_complete") is False:
        counts["missing_required_roles_present"] += 1
    return counts


def _selected_evidence_weakness_summary(
    failure: Mapping[str, object],
) -> dict[str, int] | None:
    bundle = _mapping(_mapping(failure.get("diagnostics")).get("bundle"))
    summary = {
        "selected_low_answerability_count": _positive_int(
            bundle.get("selected_low_answerability_count")
        )
        or 0,
        "selected_weak_source_locality_count": _positive_int(
            bundle.get("selected_weak_source_locality_count")
        )
        or 0,
    }
    return summary if any(summary.values()) else None


def _temporal_grounding_summary(
    failure: Mapping[str, object],
) -> dict[str, object] | None:
    temporal_grounding = _failure_temporal_grounding(failure)
    if not temporal_grounding:
        return None
    issue_item_count = _positive_int(temporal_grounding.get("issue_item_count")) or 0
    if issue_item_count <= 0:
        return None
    summary: dict[str, object] = {
        "issue_item_count": issue_item_count,
        "issue_reason_counts": dict(
            sorted(_temporal_grounding_issue_reason_counts(failure).items())
        ),
    }
    samples = _temporal_grounding_issue_samples(failure)
    if samples:
        summary["issue_samples"] = samples[:_MAX_TEMPORAL_GROUNDING_SAMPLE_EXAMPLES]
    return summary


def _temporal_grounding_issue_reason_counts(
    failure: Mapping[str, object],
) -> dict[str, int]:
    counts = _mapping(_failure_temporal_grounding(failure).get("issue_reason_counts"))
    return {
        str(reason): count
        for reason, raw_count in counts.items()
        if (count := _positive_int(raw_count)) is not None
    }


def _temporal_grounding_issue_example(
    failure: Mapping[str, object],
    issue_reason: str,
) -> dict[str, object]:
    counts = _temporal_grounding_issue_reason_counts(failure)
    payload: dict[str, object] = {
        "case_id": str(failure.get("case_id") or ""),
        "capability": str(
            failure.get("capability") or failure.get("category") or "unknown"
        ),
        "reason": str(failure.get("reason") or "unknown"),
        "issue_reason": issue_reason,
        "issue_reason_count": counts.get(issue_reason, 0),
    }
    samples = _temporal_grounding_issue_samples(failure, issue_reason=issue_reason)
    if samples:
        payload["issue_samples"] = samples[
            :_MAX_TEMPORAL_GROUNDING_SAMPLE_EXAMPLES
        ]
    return payload


def _temporal_grounding_issue_samples(
    failure: Mapping[str, object],
    *,
    issue_reason: str | None = None,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for raw_sample in _sequence(_failure_temporal_grounding(failure).get("issue_samples")):
        sample = _mapping(raw_sample)
        reasons = _strings(sample.get("issue_reasons"))
        if issue_reason is not None and issue_reason not in reasons:
            continue
        samples.append(_safe_temporal_grounding_issue_sample(sample))
    return samples


def _safe_temporal_grounding_issue_sample(
    sample: Mapping[str, object],
) -> dict[str, object]:
    return {
        key: sample[key]
        for key in _TEMPORAL_GROUNDING_SAMPLE_KEYS
        if key in sample
    }


def _failure_temporal_grounding(failure: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_mapping(failure.get("diagnostics")).get("temporal_grounding"))


def _normalize_tag_value(value: object) -> str:
    normalized = str(value or "unknown").strip().lower().replace(" ", "_")
    return normalized or "unknown"


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _filter_failures(
    failures: Sequence[Mapping[str, object]],
    *,
    capabilities: Sequence[str],
    reasons: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    if not capabilities and not reasons:
        return tuple(failures)
    capability_set = frozenset(capabilities)
    reason_set = frozenset(reasons)
    return tuple(
        failure
        for failure in failures
        if (not capability_set or _capability_key(failure) in capability_set)
        and (not reason_set or _reason_key(failure) in reason_set)
    )


def _normalize_filters(values: Sequence[str] | None) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    if not values:
        return ()
    for raw_value in values:
        for item in str(raw_value).split(","):
            normalized = item.strip().lower()
            if not normalized:
                continue
            if normalized.startswith("category_"):
                normalized = f"locomo_{normalized}"
            if normalized.startswith("category-"):
                normalized = "locomo_" + normalized.replace("-", "_")
            if normalized not in seen:
                selected.append(normalized)
                seen.add(normalized)
    return tuple(selected)


def _capability_key(failure: Mapping[str, object]) -> str:
    return str(failure.get("capability") or failure.get("category") or "unknown").lower()


def _reason_key(failure: Mapping[str, object]) -> str:
    return str(failure.get("reason") or "unknown").lower()


def _answer_shape(failure: Mapping[str, object]) -> str:
    raw = failure.get("answer_shape") or failure.get("question_type")
    if isinstance(raw, str) and raw:
        return raw
    question = _question_text(failure).casefold()
    if question.startswith(("how many", "number of", "count ")):
        return "count"
    if question.startswith(("when", "what date", "which date")):
        return "when"
    if question.startswith("where"):
        return "where"
    if question.startswith("why"):
        return "why"
    if question.startswith(("did ", "does ", "do ", "is ", "are ", "was ", "were ")):
        return "yes_no"
    if question.startswith(("what ", "which ")):
        if _question_requests_list(question):
            return "list"
        return "what"
    if question.startswith(("who are ", "who were ", "who did ")):
        return "list"
    return "unknown"


def _answer_shape_components(failure: Mapping[str, object]) -> tuple[str, ...]:
    primary = _answer_shape(failure)
    question = _question_text(failure).casefold()
    components = [primary]
    if _question_requests_list(question) or question.startswith(
        ("who are ", "who were ", "who did ")
    ):
        components.append("list")
    if (
        primary == "count"
        or question.startswith(("how many", "number of", "count "))
        or (
            _question_requests_list(question)
            and _BOUNDED_LIST_COUNT_RE.search(question[:120])
        )
    ):
        components.append("count")
    return tuple(dict.fromkeys(component for component in components if component))


def _question_requests_list(question: str) -> bool:
    return question.startswith(("what ", "which ")) and any(
        marker in question for marker in _LIST_QUESTION_MARKERS
    )


def _query_patterns(failure: Mapping[str, object]) -> tuple[str, ...]:
    question = _question_text(failure).casefold()
    patterns: list[str] = []
    if "persue" in question or "pursu" in question:
        patterns.append("pursue_typo_or_stem")
    if "preform" in question:
        patterns.append("perform_typo")
    if "reminder of" in question or "remind" in question:
        patterns.append("sentimental_reminder")
    if "motivat" in question or question.startswith("why "):
        patterns.append("motivation_or_reason")
    if question.startswith("when ") or "how long" in question:
        patterns.append("temporal_answer")
    if any(
        marker in question
        for marker in (
            "what books",
            "what activities",
            "what games",
            "what recipes",
            "what events",
        )
    ):
        patterns.append("list_inventory")
    if any(marker in question for marker in ("both", "common", "share")):
        patterns.append("commonality")
    if any(marker in question for marker in ("lgbtq", "transgender", "identity")):
        patterns.append("identity_community")
    return tuple(patterns or ("other",))


def _question_text(failure: Mapping[str, object]) -> str:
    return str(
        failure.get("question")
        or failure.get("question_preview")
        or failure.get("query")
        or ""
    )


def _benchmark_args(case_ids: Sequence[str]) -> str:
    return "".join(f"--case-id {case_id}\n" for case_id in case_ids)


if __name__ == "__main__":
    raise SystemExit(main())
