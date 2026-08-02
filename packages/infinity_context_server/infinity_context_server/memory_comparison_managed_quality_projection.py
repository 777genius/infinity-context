"""Privacy-safe paired quality projection from receipt-issued judge proofs."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_profiles import (
    INFINITY_COMPARISON_BACKEND,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    validate_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_execution_receipts import (
    ManagedExecutionReceiptError,
    ManagedSealedJudgeOutcome,
    consume_managed_sealed_judge_outcomes,
)

MANAGED_PAIRED_QUALITY_PROJECTION_SCHEMA_VERSION = (
    "memory-comparison-managed-paired-quality-projection.v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = object()
_LOCK = threading.RLock()
_MEM0_BACKEND = "mem0"
_MEMO_STACK_BACKEND = INFINITY_COMPARISON_BACKEND


class ManagedPairedQualityProjectionError(RuntimeError):
    """Fixed-code failure without benchmark, answer, or provider material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedPairedQualityProjectionInput:
    """Opaque manifest-bound proof set, issued only after receipt consumption."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedPairedQualityProjectionError("quality_input_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPairedQualityProjectionInput is final")

    def __repr__(self) -> str:
        return "ManagedPairedQualityProjectionInput(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedPairedQualityProjectionInput is nonserializable")


@final
class ManagedPairedQualityProjection:
    """Opaque projection whose safe aggregate is recomputed on every read."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedPairedQualityProjectionError("quality_projection_forged")

    def public_payload(self) -> dict[str, object]:
        return _public_payload(_projection_state(self))

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPairedQualityProjection is final")

    def __repr__(self) -> str:
        return "ManagedPairedQualityProjection(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedPairedQualityProjection is nonserializable")


@dataclass(frozen=True, slots=True)
class _ProjectionInputState:
    binding_commitment_sha256: str
    case_manifest_sha256: str
    case_aliases: tuple[str, ...]
    outcomes: tuple[object, ...]


_INPUTS: weakref.WeakKeyDictionary[
    ManagedPairedQualityProjectionInput, _ProjectionInputState
] = weakref.WeakKeyDictionary()
_PROJECTIONS: weakref.WeakKeyDictionary[
    ManagedPairedQualityProjection, _ProjectionInputState
] = weakref.WeakKeyDictionary()


def create_managed_paired_quality_projection_input(
    *,
    bindings: FullComparisonRunBindings,
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
    case_manifest_sha256: str,
    outcomes: tuple[ManagedSealedJudgeOutcome, ...],
) -> ManagedPairedQualityProjectionInput:
    """Consume exact sealed proofs after binding them to exact manifest lanes."""

    trusted = _trusted_bindings(bindings)
    aliases = _validated_manifest(case_manifest, case_manifest_sha256)
    expected_lanes = tuple(
        (alias, role)
        for alias in aliases
        for role in (_MEMO_STACK_BACKEND, _MEM0_BACKEND)
    )
    try:
        sealed = consume_managed_sealed_judge_outcomes(
            outcomes,
            binding_commitment_sha256=trusted.binding_commitment_sha256,
            expected_lanes=expected_lanes,
        )
    except ManagedExecutionReceiptError:
        raise ManagedPairedQualityProjectionError("quality_proof_invalid") from None
    value = ManagedPairedQualityProjectionInput(_token=_TOKEN)
    with _LOCK:
        _INPUTS[value] = _ProjectionInputState(
            binding_commitment_sha256=trusted.binding_commitment_sha256,
            case_manifest_sha256=case_manifest_sha256,
            case_aliases=aliases,
            outcomes=sealed,
        )
    return value


def project_managed_paired_quality(
    value: ManagedPairedQualityProjectionInput,
) -> ManagedPairedQualityProjection:
    """Create an opaque aggregate from an exact proof set."""

    state = _input_state(value)
    _validated_outcomes(state)
    projection = ManagedPairedQualityProjection(_token=_TOKEN)
    with _LOCK:
        _PROJECTIONS[projection] = state
    return projection


def _trusted_bindings(bindings: FullComparisonRunBindings) -> FullComparisonRunBindings:
    try:
        trusted = validate_full_comparison_run_bindings(bindings)
    except Exception:
        raise ManagedPairedQualityProjectionError("quality_bindings_invalid") from None
    if tuple(item.backend_role for item in trusted.backend_targets) != (
        _MEMO_STACK_BACKEND,
        _MEM0_BACKEND,
    ):
        raise ManagedPairedQualityProjectionError("quality_backend_binding_invalid")
    return trusted


def _validated_manifest(
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    expected_sha256: str,
) -> tuple[str, ...]:
    _digest(expected_sha256, "case_manifest_sha256")
    if type(manifest) is not tuple or not manifest:
        raise ManagedPairedQualityProjectionError("quality_manifest_invalid")
    try:
        actual_sha256 = execution_case_manifest_sha256(manifest)
        aliases = tuple(item.case_id for item in manifest)
    except Exception:
        raise ManagedPairedQualityProjectionError("quality_manifest_invalid") from None
    if actual_sha256 != expected_sha256 or len(set(aliases)) != len(aliases):
        raise ManagedPairedQualityProjectionError("quality_manifest_binding_invalid")
    return aliases


def _input_state(value: object) -> _ProjectionInputState:
    if type(value) is not ManagedPairedQualityProjectionInput:
        raise ManagedPairedQualityProjectionError("quality_input_invalid")
    with _LOCK:
        state = _INPUTS.get(value)
    if state is None:
        raise ManagedPairedQualityProjectionError("quality_input_invalid")
    return state


def _projection_state(value: object) -> _ProjectionInputState:
    if type(value) is not ManagedPairedQualityProjection:
        raise ManagedPairedQualityProjectionError("quality_projection_invalid")
    with _LOCK:
        state = _PROJECTIONS.get(value)
    if state is None:
        raise ManagedPairedQualityProjectionError("quality_projection_invalid")
    return state


def _validated_outcomes(
    state: _ProjectionInputState,
) -> tuple[tuple[object, ...], str]:
    expected = {
        (alias, role)
        for alias in state.case_aliases
        for role in (_MEMO_STACK_BACKEND, _MEM0_BACKEND)
    }
    observed = tuple(
        (_outcome_alias(item), _outcome_role(item)) for item in state.outcomes
    )
    if len(state.outcomes) != len(expected) or set(observed) != expected:
        raise ManagedPairedQualityProjectionError("quality_lane_coverage_invalid")
    if len(set(observed)) != len(observed):
        raise ManagedPairedQualityProjectionError("quality_lane_duplicate")
    digest = _json_sha256(
        [
            {
                "backend_role": _outcome_role(item),
                "case_alias": _outcome_alias(item),
                "judge_result_sha256": _outcome_hash(item),
                "score": _outcome_score(item),
                "verdict": _outcome_verdict(item),
            }
            for item in sorted(
                state.outcomes,
                key=lambda item: (_outcome_alias(item), _outcome_role(item)),
            )
        ]
    )
    return state.outcomes, digest


def _public_payload(state: _ProjectionInputState) -> dict[str, object]:
    outcomes, judge_outcomes_sha256 = _validated_outcomes(state)
    by_lane = {
        (_outcome_alias(item), _outcome_role(item)): item
        for item in outcomes
    }
    memo = tuple(by_lane[(alias, _MEMO_STACK_BACKEND)] for alias in state.case_aliases)
    mem0 = tuple(by_lane[(alias, _MEM0_BACKEND)] for alias in state.case_aliases)
    memo_metrics = _backend_metrics(memo)
    mem0_metrics = _backend_metrics(mem0)
    paired = {
        "memo_stack_win_count": sum(
            1
            for left, right in zip(memo, mem0, strict=True)
            if _outcome_score(left) > _outcome_score(right)
        ),
        "tie_count": sum(
            1
            for left, right in zip(memo, mem0, strict=True)
            if _outcome_score(left) == _outcome_score(right)
        ),
        "mem0_win_count": sum(
            1
            for left, right in zip(memo, mem0, strict=True)
            if _outcome_score(left) < _outcome_score(right)
        ),
        "accuracy_delta": memo_metrics["accuracy"] - mem0_metrics["accuracy"],
    }
    coverage = {
        "case_count": len(state.case_aliases),
        "expected_lane_count": len(state.case_aliases) * 2,
        "observed_lane_count": len(outcomes),
        "complete": True,
    }
    commitment_body = {
        "schema_version": MANAGED_PAIRED_QUALITY_PROJECTION_SCHEMA_VERSION,
        "binding_commitment_sha256": state.binding_commitment_sha256,
        "case_manifest_sha256": state.case_manifest_sha256,
        "judge_outcomes_sha256": judge_outcomes_sha256,
        "backends": {"memo_stack": memo_metrics, "mem0": mem0_metrics},
        "paired": paired,
        "coverage": coverage,
    }
    return {
        **commitment_body,
        "completeness_commitment_sha256": _json_sha256(commitment_body),
    }


def _backend_metrics(outcomes: tuple[object, ...]) -> dict[str, float | int]:
    total = len(outcomes)
    correct = sum(1 for item in outcomes if _outcome_verdict(item) == "correct")
    return {"total": total, "correct": correct, "accuracy": correct / total}


def _outcome_alias(value: object) -> str:
    return _outcome_field(value, "case_alias", str)


def _outcome_role(value: object) -> str:
    return _outcome_field(value, "backend_role", str)


def _outcome_verdict(value: object) -> str:
    return _outcome_field(value, "verdict", str)


def _outcome_hash(value: object) -> str:
    return _outcome_field(value, "judge_result_sha256", str)


def _outcome_score(value: object) -> float:
    return _outcome_field(value, "score", float)


def _outcome_field(value: object, name: str, expected: type[object]):
    try:
        field = getattr(value, name)
    except (AttributeError, TypeError):
        raise ManagedPairedQualityProjectionError("quality_proof_invalid") from None
    if type(field) is not expected:
        raise ManagedPairedQualityProjectionError("quality_proof_invalid")
    return field


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedPairedQualityProjectionError(f"quality_{field}_invalid")
    return value


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


__all__ = (
    "MANAGED_PAIRED_QUALITY_PROJECTION_SCHEMA_VERSION",
    "ManagedPairedQualityProjection",
    "ManagedPairedQualityProjectionError",
    "ManagedPairedQualityProjectionInput",
    "ManagedSealedJudgeOutcome",
    "create_managed_paired_quality_projection_input",
    "project_managed_paired_quality",
)
