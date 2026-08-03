"""Exact recomputed scope policy for full comparisons and diagnostic canaries."""

from __future__ import annotations

import math
from collections.abc import Mapping

from infinity_context_server.public_benchmark_models import BenchmarkValidationError

FULL_COMPARISON_SCOPE_FULL = "full"
FULL_COMPARISON_SCOPE_CANARY = "canary"
FULL_COMPARISON_SCOPES = (FULL_COMPARISON_SCOPE_FULL, FULL_COMPARISON_SCOPE_CANARY)
FULL_COMPARISON_CANARY_SCHEMA_VERSION = "memory-comparison-full-canary-scope.v1"
_INVALID_BLOCKER_CODE = "invalid_blocker_contract"
_CANARY_ALLOWED_BLOCKERS = frozenset(
    {
        "dataset_scope_mismatch",
        "dataset_distribution_mismatch",
        "corpus_count_mismatch",
    }
)


def normalize_full_comparison_scope(value: str | None) -> str:
    if value is not None and type(value) is not str:
        raise BenchmarkValidationError("full comparison scope must be a string")
    scope = (value or FULL_COMPARISON_SCOPE_FULL).strip().casefold()
    if scope not in FULL_COMPARISON_SCOPES:
        choices = ", ".join(FULL_COMPARISON_SCOPES)
        raise BenchmarkValidationError(
            f"unsupported full comparison scope {value!r}; choose one of: {choices}"
        )
    return scope


def publishable_full_comparison(scope: str) -> bool:
    return normalize_full_comparison_scope(scope) == FULL_COMPARISON_SCOPE_FULL


def full_comparison_scope_blockers(
    blockers: object,
    *,
    scope: str,
) -> tuple[dict[str, object], ...]:
    """Reparse root blockers and waive only three exact dataset objects."""

    normalized_scope = normalize_full_comparison_scope(scope)
    normalized = _exact_root_blockers(blockers)
    if normalized_scope == FULL_COMPARISON_SCOPE_FULL:
        return normalized
    return tuple(blocker for blocker in normalized if not _exact_relaxable_dataset_blocker(blocker))


def annotate_full_comparison_contract(
    contract: Mapping[str, object],
    *,
    scope: str,
) -> dict[str, object]:
    if type(contract) is not dict:
        raise BenchmarkValidationError("full comparison contract must be an exact dict")
    normalized_scope = normalize_full_comparison_scope(scope)
    root_blockers = _exact_root_blockers(contract.get("blockers"))
    annotated = dict(contract)
    annotated["blockers"] = [dict(blocker) for blocker in root_blockers]
    annotated["scope"] = normalized_scope
    annotated["publishable"] = normalized_scope == FULL_COMPARISON_SCOPE_FULL
    if normalized_scope == FULL_COMPARISON_SCOPE_CANARY:
        annotated["diagnostic_canary"] = _diagnostic_canary(root_blockers)
    else:
        annotated.pop("diagnostic_canary", None)
    return annotated


def full_comparison_contract_blocks_result(
    contract: Mapping[str, object],
    *,
    scope: str,
) -> bool:
    """Recompute from exact root state on every call and reject all divergence."""

    normalized_scope = normalize_full_comparison_scope(scope)
    if type(contract) is not dict or type(contract.get("eligible")) is not bool:
        return True
    blockers_value = contract.get("blockers")
    if type(blockers_value) is not list:
        return True
    root_blockers = _exact_root_blockers(blockers_value)
    if any(blocker.get("code") == _INVALID_BLOCKER_CODE for blocker in root_blockers):
        return True
    if contract.get("eligible") is not (not root_blockers):
        return True
    if contract.get("scope") != normalized_scope:
        return True
    expected_publishable = normalized_scope == FULL_COMPARISON_SCOPE_FULL
    if type(contract.get("publishable")) is not bool:
        return True
    if contract.get("publishable") is not expected_publishable:
        return True
    if normalized_scope == FULL_COMPARISON_SCOPE_FULL:
        return bool(root_blockers or contract.get("eligible") is not True)

    diagnostic = contract.get("diagnostic_canary")
    expected_diagnostic = _diagnostic_canary(root_blockers)
    if type(diagnostic) is not dict or diagnostic != expected_diagnostic:
        return True
    remaining = full_comparison_scope_blockers(
        blockers_value,
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    return bool(remaining or expected_diagnostic["eligible"] is not True)


def _diagnostic_canary(
    root_blockers: tuple[dict[str, object], ...],
) -> dict[str, object]:
    waived = tuple(
        blocker for blocker in root_blockers if _exact_relaxable_dataset_blocker(blocker)
    )
    remaining = tuple(
        blocker for blocker in root_blockers if not _exact_relaxable_dataset_blocker(blocker)
    )
    return {
        "schema_version": FULL_COMPARISON_CANARY_SCHEMA_VERSION,
        "publishable": False,
        "eligible": not remaining,
        "blockers": [_exact_json_copy(blocker) for blocker in remaining],
        "waived_blockers": [_exact_json_copy(blocker) for blocker in waived],
        "allowed_non_publishable_blockers": sorted(_CANARY_ALLOWED_BLOCKERS),
    }


def _exact_root_blockers(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not list:
        return ({"code": _INVALID_BLOCKER_CODE},)
    normalized: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for raw_blocker in value:
        if type(raw_blocker) is not dict or not _exact_json_object(raw_blocker):
            normalized.append({"code": _INVALID_BLOCKER_CODE})
            continue
        code = raw_blocker.get("code")
        if (
            type(code) is not str
            or not code
            or code != code.strip()
            or len(code) > 128
            or code in seen_codes
        ):
            normalized.append({"code": _INVALID_BLOCKER_CODE})
            continue
        seen_codes.add(code)
        blocker = _exact_json_copy(raw_blocker)
        if code in _CANARY_ALLOWED_BLOCKERS and not _exact_relaxable_dataset_blocker(blocker):
            normalized.append({"code": _INVALID_BLOCKER_CODE})
            continue
        normalized.append(blocker)
    return tuple(normalized)


def _exact_relaxable_dataset_blocker(blocker: dict[str, object]) -> bool:
    code = blocker.get("code")
    if code == "corpus_count_mismatch":
        return bool(
            set(blocker) == {"code", "expected", "actual"}
            and _positive_exact_int(blocker["expected"])
            and _nonnegative_exact_int(blocker["actual"])
        )
    if code not in {"dataset_scope_mismatch", "dataset_distribution_mismatch"}:
        return False
    if set(blocker) != {"code", "expected", "actual"}:
        return False
    expected = blocker["expected"]
    actual = blocker["actual"]
    return bool(
        _exact_count_mapping(expected, require_positive_counts=True)
        and _exact_count_mapping(actual, require_positive_counts=False)
    )


def _exact_count_mapping(value: object, *, require_positive_counts: bool) -> bool:
    if type(value) is not dict or (require_positive_counts and not value):
        return False
    for key, count in value.items():
        if type(key) is not str or not key or key != key.strip() or len(key) > 128:
            return False
        if type(count) is not int or count < (1 if require_positive_counts else 0):
            return False
    return True


def _exact_json_object(value: dict[object, object], *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    return all(
        type(key) is str and key and key == key.strip() and _exact_json_value(item, depth=depth + 1)
        for key, item in value.items()
    )


def _exact_json_value(value: object, *, depth: int) -> bool:
    if depth > 8:
        return False
    if value is None or type(value) in {str, bool, int}:
        return not (type(value) is str and len(value) > 1024)
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return len(value) <= 100 and all(_exact_json_value(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        return len(value) <= 100 and _exact_json_object(value, depth=depth)
    return False


def _exact_json_copy(value: dict[str, object]) -> dict[str, object]:
    return {key: _copy_json_value(item) for key, item in value.items()}


def _copy_json_value(value: object) -> object:
    if type(value) is dict:
        return {key: _copy_json_value(item) for key, item in value.items()}
    if type(value) is list:
        return [_copy_json_value(item) for item in value]
    return value


def _positive_exact_int(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative_exact_int(value: object) -> bool:
    return type(value) is int and value >= 0


__all__ = (
    "FULL_COMPARISON_CANARY_SCHEMA_VERSION",
    "FULL_COMPARISON_SCOPES",
    "FULL_COMPARISON_SCOPE_CANARY",
    "FULL_COMPARISON_SCOPE_FULL",
    "annotate_full_comparison_contract",
    "full_comparison_contract_blocks_result",
    "full_comparison_scope_blockers",
    "normalize_full_comparison_scope",
    "publishable_full_comparison",
)
