"""Unsupported public benchmark case diagnostics.

This module keeps optional case-selection diagnostics out of the benchmark runner.
The runner remains the source of truth for dataset normalization and passes small
callbacks so unsupported-case reporting cannot drift from supported-case parsing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from infinity_context_server.public_benchmark_selection import (
    case_selection_missing_case_ids,
    missing_case_id_failures,
)

LoadDatasetPayload = Callable[[Path], object]
IsLocomoSample = Callable[[Mapping[str, object]], bool]
LocomoCaseIds = Callable[[Mapping[str, object]], Sequence[str]]
FirstString = Callable[[Mapping[str, object], str, str], str | None]
CaseHash = Callable[[Mapping[str, object]], str]


def augment_case_selection_with_unsupported_requested_cases(
    *,
    dataset_path: Path,
    benchmark: str | None,
    requested_case_ids: Sequence[str],
    case_selection: Mapping[str, object],
    locomo_benchmark: str,
    load_dataset_payload: LoadDatasetPayload,
    is_official_locomo_sample: IsLocomoSample,
    official_locomo_case_ids: LocomoCaseIds,
    first_str: FirstString,
    case_hash: CaseHash,
) -> dict[str, object]:
    missing_case_ids = case_selection_missing_case_ids(case_selection)
    if not missing_case_ids:
        return dict(case_selection)
    unsupported_reasons = _unsupported_requested_case_reasons(
        dataset_path=dataset_path,
        benchmark=benchmark,
        requested_case_ids=missing_case_ids,
        locomo_benchmark=locomo_benchmark,
        load_dataset_payload=load_dataset_payload,
        is_official_locomo_sample=is_official_locomo_sample,
        official_locomo_case_ids=official_locomo_case_ids,
        first_str=first_str,
        case_hash=case_hash,
    )
    if not unsupported_reasons:
        return dict(case_selection)
    unsupported_case_ids = [
        case_id for case_id in missing_case_ids if case_id in unsupported_reasons
    ]
    if not unsupported_case_ids:
        return dict(case_selection)
    augmented = dict(case_selection)
    augmented["unsupported_case_ids"] = unsupported_case_ids
    augmented["unsupported_case_id_count"] = len(unsupported_case_ids)
    augmented["unsupported_case_id_reasons"] = [
        {"case_id": case_id, "reason": unsupported_reasons[case_id]}
        for case_id in unsupported_case_ids
    ]
    return augmented


def missing_case_id_failures_for_selection(
    case_selection: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    missing_case_ids = case_selection_missing_case_ids(case_selection)
    unsupported_reasons = _case_selection_unsupported_case_reasons(case_selection)
    failures: list[dict[str, object]] = []
    for case_id in missing_case_ids:
        if case_id in unsupported_reasons:
            continue
        failures.extend(missing_case_id_failures((case_id,)))
    return failures


def unsupported_case_reports_for_selection(
    case_selection: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    unsupported_reasons = _case_selection_unsupported_case_reasons(case_selection)
    return [
        {
            "case_id": case_id,
            "category": "unsupported",
            "reason": "requested_case_id_not_supported",
            "unsupported_reason": unsupported_reason,
        }
        for case_id, unsupported_reason in unsupported_reasons.items()
    ]


def _case_selection_unsupported_case_reasons(
    case_selection: Mapping[str, object] | None,
) -> dict[str, str]:
    if not isinstance(case_selection, Mapping):
        return {}
    raw_items = case_selection.get("unsupported_case_id_reasons")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, str | bytes):
        return {}
    reasons: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        case_id = str(item.get("case_id") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if case_id and reason:
            reasons[case_id] = reason
    return reasons


def _unsupported_requested_case_reasons(
    *,
    dataset_path: Path,
    benchmark: str | None,
    requested_case_ids: Sequence[str],
    locomo_benchmark: str,
    load_dataset_payload: LoadDatasetPayload,
    is_official_locomo_sample: IsLocomoSample,
    official_locomo_case_ids: LocomoCaseIds,
    first_str: FirstString,
    case_hash: CaseHash,
) -> dict[str, str]:
    if not requested_case_ids or benchmark not in {None, locomo_benchmark}:
        return {}
    try:
        payload = load_dataset_payload(dataset_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    unsupported_by_case_id = _unsupported_official_locomo_case_reasons(
        payload,
        is_official_locomo_sample=is_official_locomo_sample,
        official_locomo_case_ids=official_locomo_case_ids,
        first_str=first_str,
        case_hash=case_hash,
    )
    if not unsupported_by_case_id:
        return {}
    unsupported: dict[str, str] = {}
    for case_id in requested_case_ids:
        normalized_case_id = _strip_benchmark_case_id_prefix(
            case_id,
            benchmark=locomo_benchmark,
        )
        reason = unsupported_by_case_id.get(normalized_case_id)
        if reason:
            unsupported[case_id] = reason
    return unsupported


def _unsupported_official_locomo_case_reasons(
    payload: object,
    *,
    is_official_locomo_sample: IsLocomoSample,
    official_locomo_case_ids: LocomoCaseIds,
    first_str: FirstString,
    case_hash: CaseHash,
) -> dict[str, str]:
    if isinstance(payload, Mapping):
        if is_official_locomo_sample(payload):
            return _unsupported_official_locomo_sample_case_reasons(
                payload,
                official_locomo_case_ids=official_locomo_case_ids,
                first_str=first_str,
                case_hash=case_hash,
            )
        raw_cases = payload.get("cases") or payload.get("data") or payload.get("items")
        if raw_cases is not None:
            return _unsupported_official_locomo_case_reasons(
                raw_cases,
                is_official_locomo_sample=is_official_locomo_sample,
                official_locomo_case_ids=official_locomo_case_ids,
                first_str=first_str,
                case_hash=case_hash,
            )
        return {}
    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes):
        return {}
    unsupported: dict[str, str] = {}
    for item in payload:
        if isinstance(item, Mapping) and is_official_locomo_sample(item):
            unsupported.update(
                _unsupported_official_locomo_sample_case_reasons(
                    item,
                    official_locomo_case_ids=official_locomo_case_ids,
                    first_str=first_str,
                    case_hash=case_hash,
                )
            )
    return unsupported


def _unsupported_official_locomo_sample_case_reasons(
    raw: Mapping[str, object],
    *,
    official_locomo_case_ids: LocomoCaseIds,
    first_str: FirstString,
    case_hash: CaseHash,
) -> dict[str, str]:
    sample_id = first_str(raw, "sample_id", "id") or case_hash(raw)
    supported_case_ids = set(official_locomo_case_ids(raw))
    raw_qas = raw.get("qa")
    if not isinstance(raw_qas, Sequence) or isinstance(raw_qas, str | bytes):
        return {}
    unsupported: dict[str, str] = {}
    for index, qa in enumerate(raw_qas):
        if not isinstance(qa, Mapping):
            continue
        case_id = f"{sample_id}:qa:{index + 1}"
        if case_id in supported_case_ids:
            continue
        reason = (
            "official_locomo.missing_question"
            if not first_str(qa, "question", "query")
            else "official_locomo.no_retrieval_terms"
        )
        unsupported[case_id] = reason
    return unsupported


def _strip_benchmark_case_id_prefix(case_id: str, *, benchmark: str) -> str:
    prefix = f"{benchmark}:"
    return case_id.removeprefix(prefix)
