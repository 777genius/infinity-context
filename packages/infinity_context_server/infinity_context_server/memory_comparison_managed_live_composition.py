"""Prepare-only composition from live admission to an exact managed run plan.

The sealed preparation intentionally has no public execution seam. A future
composition must prove opaque bounded execution/judge ports before it can consume
the preparation and call the managed runner.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final

from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_live_admission import (
    MANAGED_PROVIDER_OPENAI_API_KEY,
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedLiveAdmissionError,
    ManagedLiveBudget,
    ManagedLiveProviderUsageBudget,
    VerifiedManagedLiveAdmission,
    _consume_verified_managed_live_admission,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    build_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    VerifiedSubscriptionRuntimeProbe,
    inspect_verified_subscription_runtime_probe,
)

_TOKEN = object()
_LOCK = threading.RLock()


@final
@dataclass(frozen=True, slots=True)
class ManagedLiveExecutionLimits:
    """Immutable admitted ceilings, including readiness probe usage."""

    provider_kind: str
    max_cases: int
    benchmark_max_provider_calls: int
    readiness_probe_provider_calls: int
    total_provider_attempt_ceiling: int
    benchmark_max_total_tokens: int
    readiness_probe_observed_tokens: int
    total_token_ceiling: int
    issued_at: datetime
    deadline: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedLiveExecutionLimits is final")


@final
class VerifiedManagedLiveRunPreparation:
    """Opaque, noncopyable authority awaiting verified bounded execution ports."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedRunError("managed live preparations must be built authoritatively")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedManagedLiveRunPreparation is final")

    def __repr__(self) -> str:
        return "VerifiedManagedLiveRunPreparation(<sealed-one-shot>)"

    def __copy__(self) -> object:
        raise TypeError("managed live preparation is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed live preparation is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed live preparation is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed live preparation is nonserializable")


@dataclass(frozen=True, slots=True)
class _PreparedLiveRunState:
    plan: VerifiedManagedRunPlan = field(repr=False)
    limits: ManagedLiveExecutionLimits
    runtime_validation: VerifiedMem0RuntimeAttestationValidation = field(repr=False)
    secret: bytes = field(repr=False)
    commitment: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PreparedLiveRunMaterial:
    plan: VerifiedManagedRunPlan = field(repr=False)
    limits: ManagedLiveExecutionLimits
    runtime_validation: VerifiedMem0RuntimeAttestationValidation = field(repr=False)


_PREPARED_RUNS: weakref.WeakKeyDictionary[
    VerifiedManagedLiveRunPreparation, _PreparedLiveRunState
] = weakref.WeakKeyDictionary()


def prepare_verified_managed_live_run(
    admission: VerifiedManagedLiveAdmission,
    *,
    expected_request: ManagedPreflightRequest,
    dataset_bytes: bytes,
    now: datetime,
) -> VerifiedManagedLiveRunPreparation:
    """Burn one live admission and prepare its exact managed run plan."""

    material = _consume_verified_managed_live_admission(
        admission,
        expected_request=expected_request,
        now=now,
    )
    if type(dataset_bytes) is not bytes:
        raise ManagedRunError("managed live dataset must be exact bytes")
    if not hmac.compare_digest(
        hashlib.sha256(dataset_bytes).hexdigest(),
        material.preflight.dataset_sha256,
    ):
        raise ManagedRunError("managed live dataset differs from admitted preflight")

    profile = resolve_full_comparison_profile(material.preflight.profile_id)
    if profile is None:
        raise ManagedRunError("managed live profile is unavailable")
    provider_route = _provider_route(
        material.provider_kind,
        material.live_provider_evidence,
        now=now,
    )
    plan = build_verified_managed_run_plan(
        run_id=material.run_id,
        run_nonce_commitment_sha256=material.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=material.runtime_probe_nonce_sha256,
        profile=profile,
        dataset_bytes=dataset_bytes,
        backend_targets=tuple(endpoint.target for endpoint in material.preflight.backend_endpoints),
        provider_route=provider_route,
        scope=material.preflight.scope,
        selected_case_ids=material.canary_case_ids,
    )
    limits = _execution_limits(
        material.provider_kind,
        material.budget,
        material.provider_usage_budget,
        issued_at=material.issued_at,
        deadline=material.deadline,
    )
    secret = secrets.token_bytes(32)
    commitment = _state_commitment(
        secret,
        plan=plan,
        limits=limits,
        runtime_validation=material.runtime_validation,
    )
    prepared = VerifiedManagedLiveRunPreparation(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _PREPARED_RUNS[prepared] = _PreparedLiveRunState(
            plan=plan,
            limits=limits,
            runtime_validation=material.runtime_validation,
            secret=secret,
            commitment=commitment,
        )
    return prepared


def managed_live_execution_limits(
    prepared: VerifiedManagedLiveRunPreparation,
) -> ManagedLiveExecutionLimits:
    """Read admitted ceilings without exposing or consuming the run plan."""

    with _LOCK:
        state = _trusted_state(prepared)
        return state.limits


def _consume_verified_managed_live_run_preparation(
    prepared: VerifiedManagedLiveRunPreparation,
    *,
    now: datetime,
) -> _PreparedLiveRunMaterial:
    """Private fail-closed seam for a future verified bounded-port composition."""

    trusted_now = _aware_instant(now)
    if type(prepared) is not VerifiedManagedLiveRunPreparation:
        raise ManagedRunError("managed live preparation authority type is invalid")
    with _LOCK:
        state = _PREPARED_RUNS.get(prepared)
        if state is None:
            raise ManagedRunError("managed live preparation is unavailable or consumed")
        del _PREPARED_RUNS[prepared]
        _validate_state(prepared, state)
        if trusted_now < state.limits.issued_at or trusted_now > state.limits.deadline:
            raise ManagedRunError("managed live preparation is expired or not yet current")
        return _PreparedLiveRunMaterial(
            plan=state.plan,
            limits=state.limits,
            runtime_validation=state.runtime_validation,
        )


def _provider_route(
    provider_kind: str,
    evidence: object,
    *,
    now: datetime,
) -> ProviderRouteAttestation:
    if provider_kind == MANAGED_PROVIDER_OPENAI_API_KEY:
        if type(evidence) is not ProviderRouteAttestation:
            raise ManagedLiveAdmissionError("official provider evidence type is invalid")
        return evidence
    if (
        provider_kind != MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME
        or type(evidence) is not VerifiedSubscriptionRuntimeProbe
    ):
        raise ManagedLiveAdmissionError("subscription provider evidence type is invalid")
    return inspect_verified_subscription_runtime_probe(evidence, now=now).route


def _execution_limits(
    provider_kind: str,
    budget: ManagedLiveBudget,
    usage: ManagedLiveProviderUsageBudget,
    *,
    issued_at: datetime,
    deadline: datetime,
) -> ManagedLiveExecutionLimits:
    if type(budget) is not ManagedLiveBudget or type(usage) is not ManagedLiveProviderUsageBudget:
        raise ManagedRunError("managed live budget type is invalid")
    if (
        usage.benchmark_max_provider_calls != budget.max_provider_calls
        or usage.benchmark_max_total_tokens != budget.max_total_tokens
    ):
        raise ManagedRunError("managed live provider usage differs from admitted budget")
    return ManagedLiveExecutionLimits(
        provider_kind=provider_kind,
        max_cases=budget.max_cases,
        benchmark_max_provider_calls=usage.benchmark_max_provider_calls,
        readiness_probe_provider_calls=usage.readiness_probe_provider_calls,
        total_provider_attempt_ceiling=usage.total_provider_attempt_ceiling,
        benchmark_max_total_tokens=usage.benchmark_max_total_tokens,
        readiness_probe_observed_tokens=usage.readiness_probe_observed_tokens,
        total_token_ceiling=usage.total_token_ceiling,
        issued_at=issued_at,
        deadline=deadline,
    )


def _trusted_state(prepared: object) -> _PreparedLiveRunState:
    if type(prepared) is not VerifiedManagedLiveRunPreparation:
        raise ManagedRunError("managed live preparation authority type is invalid")
    state = _PREPARED_RUNS.get(prepared)
    if state is None:
        raise ManagedRunError("managed live preparation is unavailable or consumed")
    _validate_state(prepared, state)
    return state


def _validate_state(
    prepared: VerifiedManagedLiveRunPreparation,
    state: _PreparedLiveRunState,
) -> None:
    try:
        observed = prepared._VerifiedManagedLiveRunPreparation__commitment
    except (AttributeError, TypeError) as exc:
        raise ManagedRunError("managed live preparation integrity failed") from exc
    expected = _state_commitment(
        state.secret,
        plan=state.plan,
        limits=state.limits,
        runtime_validation=state.runtime_validation,
    )
    if (
        type(observed) is not str
        or not hmac.compare_digest(observed, state.commitment)
        or not hmac.compare_digest(expected, state.commitment)
    ):
        raise ManagedRunError("managed live preparation integrity failed")


def _aware_instant(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ManagedRunError("managed live preparation clock is invalid")
    normalized = value.astimezone(UTC)
    if not 1970 <= normalized.year <= 2100:
        raise ManagedRunError("managed live preparation clock is invalid")
    return normalized


def _state_commitment(
    secret: bytes,
    *,
    plan: VerifiedManagedRunPlan,
    limits: ManagedLiveExecutionLimits,
    runtime_validation: VerifiedMem0RuntimeAttestationValidation,
) -> str:
    runtime_identity, runtime_fingerprint = _runtime_validation_evidence_key(runtime_validation)
    material = "\n".join(
        (
            str(id(plan)),
            runtime_identity,
            runtime_fingerprint,
            limits.provider_kind,
            str(limits.max_cases),
            str(limits.benchmark_max_provider_calls),
            str(limits.readiness_probe_provider_calls),
            str(limits.total_provider_attempt_ceiling),
            str(limits.benchmark_max_total_tokens),
            str(limits.readiness_probe_observed_tokens),
            str(limits.total_token_ceiling),
            limits.issued_at.isoformat(),
            limits.deadline.isoformat(),
        )
    ).encode()
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def _runtime_validation_evidence_key(
    validation: object,
) -> tuple[str, str]:
    if type(validation) is not VerifiedMem0RuntimeAttestationValidation:
        raise ManagedRunError("managed live runtime validation type is invalid")
    try:
        validation.__post_init__()
    except Exception:
        raise ManagedRunError("managed live runtime validation integrity failed") from None
    fingerprint = validation._payload_fingerprint_sha256
    if type(fingerprint) is not str or len(fingerprint) != 64:
        raise ManagedRunError("managed live runtime validation integrity failed")
    return str(id(validation)), fingerprint


__all__ = (
    "ManagedLiveExecutionLimits",
    "VerifiedManagedLiveRunPreparation",
    "managed_live_execution_limits",
    "prepare_verified_managed_live_run",
)
