"""Prepare-only composition from live admission to an exact managed run plan.

The sealed preparation intentionally has no public execution seam. A future
composition must prove opaque bounded execution/judge ports before it can consume
the preparation and call the managed runner.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
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
from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAttestationPort,
    ManagedMem0RuntimeAuthorityDescriptor,
    ManagedMem0RuntimeAuthorityError,
    inspect_pending_managed_mem0_runtime_authority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    _inspect_verified_managed_run_plan,
    build_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    ManagedRuntimeCredentialAuthority,
    ManagedRuntimeCredentialError,
    ManagedSubscriptionReadinessClaim,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_context import (
    _inspect_completed_managed_runtime_credential_context,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES,
    VerifiedSubscriptionRuntimeProbe,
    inspect_verified_subscription_runtime_probe,
)

_TOKEN = object()
_LOCK = threading.RLock()
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")


@final
@dataclass(frozen=True, slots=True)
class ManagedLiveExecutionLimits:
    """Immutable answer/judge reservations and non-publishable usage estimates.

    Provider work internal to memory backends is not measured by these limits.
    """

    provider_kind: str
    answerer_model: str
    judge_model: str
    max_cases: int
    benchmark_max_provider_calls: int
    readiness_probe_provider_calls: int
    total_provider_attempt_ceiling: int
    benchmark_reserved_token_ceiling: int
    readiness_probe_estimated_tokens: int
    readiness_probe_usage_source: str
    total_accounted_tokens: int
    token_accounting_publishable: bool
    post_reset_mem0_probe_attempt_ceiling: int
    issued_at: datetime
    deadline: datetime

    def __post_init__(self) -> None:
        if (
            type(self.provider_kind) is not str
            or self.provider_kind != MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME
            or type(self.answerer_model) is not str
            or _IDENTIFIER.fullmatch(self.answerer_model) is None
            or type(self.judge_model) is not str
            or _IDENTIFIER.fullmatch(self.judge_model) is None
            or type(self.max_cases) is not int
            or self.max_cases < 1
            or type(self.benchmark_max_provider_calls) is not int
            or self.benchmark_max_provider_calls != self.max_cases * 4
            or type(self.readiness_probe_provider_calls) is not int
            or self.readiness_probe_provider_calls != 1
            or type(self.total_provider_attempt_ceiling) is not int
            or self.total_provider_attempt_ceiling
            != self.benchmark_max_provider_calls + self.readiness_probe_provider_calls
            or type(self.benchmark_reserved_token_ceiling) is not int
            or self.benchmark_reserved_token_ceiling < 1
            or type(self.readiness_probe_estimated_tokens) is not int
            or self.readiness_probe_estimated_tokens < 1
            or self.readiness_probe_usage_source not in SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES
            or type(self.total_accounted_tokens) is not int
            or self.total_accounted_tokens
            != self.benchmark_reserved_token_ceiling + self.readiness_probe_estimated_tokens
            or self.token_accounting_publishable is not False
            or type(self.post_reset_mem0_probe_attempt_ceiling) is not int
            or self.post_reset_mem0_probe_attempt_ceiling != 1
            or type(self.issued_at) is not datetime
            or self.issued_at.tzinfo is None
            or type(self.deadline) is not datetime
            or self.deadline.tzinfo is None
            or self.issued_at >= self.deadline
        ):
            raise ManagedRunError("managed live execution limits are invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "provider_kind": self.provider_kind,
            "answerer_model": self.answerer_model,
            "judge_model": self.judge_model,
            "max_cases": self.max_cases,
            "benchmark_max_provider_calls": self.benchmark_max_provider_calls,
            "benchmark_provider_call_scope": "answer_judge_only",
            "readiness_probe_provider_calls": self.readiness_probe_provider_calls,
            "total_provider_attempt_ceiling": self.total_provider_attempt_ceiling,
            "total_provider_attempt_ceiling_scope": "answer_judge_and_readiness_only",
            "backend_internal_provider_calls": "unmeasured",
            "backend_internal_provider_cost": "unmeasured",
            "total_provider_calls_claimed": False,
            "benchmark_reserved_token_ceiling": self.benchmark_reserved_token_ceiling,
            "readiness_probe_estimated_tokens": self.readiness_probe_estimated_tokens,
            "readiness_probe_usage_source": self.readiness_probe_usage_source,
            "total_accounted_tokens": self.total_accounted_tokens,
            "token_accounting_publishable": self.token_accounting_publishable,
            "post_reset_mem0_probe_attempt_ceiling": (self.post_reset_mem0_probe_attempt_ceiling),
            "issued_at": _instant_text(self.issued_at),
            "deadline": _instant_text(self.deadline),
        }

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
    run_id: str
    limits: ManagedLiveExecutionLimits
    preflight_request: ManagedPreflightRequest = field(repr=False)
    credential_authority: ManagedRuntimeCredentialAuthority = field(repr=False)
    readiness_claim: ManagedSubscriptionReadinessClaim = field(repr=False)
    provider_probe: VerifiedSubscriptionRuntimeProbe = field(repr=False)
    credential_context_fingerprint: str = field(repr=False)
    mem0_runtime_port: ManagedMem0RuntimeAttestationPort = field(repr=False)
    mem0_runtime_descriptor: ManagedMem0RuntimeAuthorityDescriptor = field(repr=False)
    secret: bytes = field(repr=False)
    commitment: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PreparedLiveRunMaterial:
    plan: VerifiedManagedRunPlan = field(repr=False)
    limits: ManagedLiveExecutionLimits
    preflight_request: ManagedPreflightRequest = field(repr=False)
    credential_authority: ManagedRuntimeCredentialAuthority = field(repr=False)
    readiness_claim: ManagedSubscriptionReadinessClaim = field(repr=False)
    mem0_runtime_port: ManagedMem0RuntimeAttestationPort = field(repr=False)
    mem0_runtime_descriptor: ManagedMem0RuntimeAuthorityDescriptor = field(repr=False)


_PREPARED_RUNS: weakref.WeakKeyDictionary[
    VerifiedManagedLiveRunPreparation, _PreparedLiveRunState
] = weakref.WeakKeyDictionary()


def prepare_verified_managed_live_run(
    admission: VerifiedManagedLiveAdmission,
    *,
    expected_request: ManagedPreflightRequest,
    credential_authority: ManagedRuntimeCredentialAuthority,
    readiness_claim: ManagedSubscriptionReadinessClaim,
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
        runtime_probe_nonce_sha256=material.mem0_runtime_descriptor.probe_nonce_sha256,
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
        answerer_model=material.preflight.answerer_model,
        judge_model=material.preflight.judge_model,
        post_reset_mem0_probe_attempt_ceiling=(material.mem0_runtime_descriptor.max_attempts),
        issued_at=material.issued_at,
        deadline=material.deadline,
    )
    credential_context_fingerprint = _credential_context_fingerprint(
        credential_authority,
        readiness_claim,
        expected_request=expected_request,
        expected_probe=material.live_provider_evidence,
        run_id=material.run_id,
        deadline=material.deadline,
    )
    secret = secrets.token_bytes(32)
    commitment = _state_commitment(
        secret,
        plan=plan,
        run_id=material.run_id,
        limits=limits,
        preflight_request=expected_request,
        credential_authority=credential_authority,
        readiness_claim=readiness_claim,
        provider_probe=material.live_provider_evidence,
        credential_context_fingerprint=credential_context_fingerprint,
        mem0_runtime_port=material.mem0_runtime_port,
        mem0_runtime_descriptor=material.mem0_runtime_descriptor,
    )
    prepared = VerifiedManagedLiveRunPreparation(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _PREPARED_RUNS[prepared] = _PreparedLiveRunState(
            plan=plan,
            run_id=material.run_id,
            limits=limits,
            preflight_request=expected_request,
            credential_authority=credential_authority,
            readiness_claim=readiness_claim,
            provider_probe=material.live_provider_evidence,
            credential_context_fingerprint=credential_context_fingerprint,
            mem0_runtime_port=material.mem0_runtime_port,
            mem0_runtime_descriptor=material.mem0_runtime_descriptor,
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


def _inspect_managed_live_policy_cases(
    prepared: VerifiedManagedLiveRunPreparation,
) -> tuple[ManagedRunCase, ...]:
    """Return exact gold-free policy cases without consuming preparation."""

    with _LOCK:
        state = _trusted_state(prepared)
        plan = _inspect_verified_managed_run_plan(state.plan)
        if plan.run_id != state.run_id:
            raise ManagedRunError("managed live preparation plan differs")
        return plan.cases


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
        _validate_state(prepared, state)
        del _PREPARED_RUNS[prepared]
        if trusted_now < state.limits.issued_at or trusted_now > state.limits.deadline:
            raise ManagedRunError("managed live preparation is expired or not yet current")
        return _PreparedLiveRunMaterial(
            plan=state.plan,
            limits=state.limits,
            preflight_request=state.preflight_request,
            credential_authority=state.credential_authority,
            readiness_claim=state.readiness_claim,
            mem0_runtime_port=state.mem0_runtime_port,
            mem0_runtime_descriptor=state.mem0_runtime_descriptor,
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
    answerer_model: str,
    judge_model: str,
    post_reset_mem0_probe_attempt_ceiling: int,
    issued_at: datetime,
    deadline: datetime,
) -> ManagedLiveExecutionLimits:
    if type(budget) is not ManagedLiveBudget or type(usage) is not ManagedLiveProviderUsageBudget:
        raise ManagedRunError("managed live budget type is invalid")
    if (
        usage.provider_kind != provider_kind
        or usage.benchmark_max_provider_calls != budget.max_provider_calls
        or usage.benchmark_reserved_token_ceiling != budget.max_total_tokens
    ):
        raise ManagedRunError("managed live provider usage differs from admitted budget")
    return ManagedLiveExecutionLimits(
        provider_kind=provider_kind,
        answerer_model=answerer_model,
        judge_model=judge_model,
        max_cases=budget.max_cases,
        benchmark_max_provider_calls=usage.benchmark_max_provider_calls,
        readiness_probe_provider_calls=usage.readiness_probe_provider_calls,
        total_provider_attempt_ceiling=usage.total_provider_attempt_ceiling,
        benchmark_reserved_token_ceiling=usage.benchmark_reserved_token_ceiling,
        readiness_probe_estimated_tokens=usage.readiness_probe_estimated_tokens,
        readiness_probe_usage_source=usage.readiness_probe_usage_source,
        total_accounted_tokens=usage.total_accounted_tokens,
        token_accounting_publishable=usage.token_accounting_publishable,
        post_reset_mem0_probe_attempt_ceiling=post_reset_mem0_probe_attempt_ceiling,
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
        run_id=state.run_id,
        limits=state.limits,
        preflight_request=state.preflight_request,
        credential_authority=state.credential_authority,
        readiness_claim=state.readiness_claim,
        provider_probe=state.provider_probe,
        credential_context_fingerprint=state.credential_context_fingerprint,
        mem0_runtime_port=state.mem0_runtime_port,
        mem0_runtime_descriptor=state.mem0_runtime_descriptor,
    )
    current_credential_fingerprint = _credential_context_fingerprint(
        state.credential_authority,
        state.readiness_claim,
        expected_request=state.preflight_request,
        expected_probe=state.provider_probe,
        run_id=state.run_id,
        deadline=state.limits.deadline,
    )
    if (
        type(observed) is not str
        or not hmac.compare_digest(
            current_credential_fingerprint,
            state.credential_context_fingerprint,
        )
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


def _instant_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _state_commitment(
    secret: bytes,
    *,
    plan: VerifiedManagedRunPlan,
    run_id: str,
    limits: ManagedLiveExecutionLimits,
    preflight_request: ManagedPreflightRequest,
    credential_authority: ManagedRuntimeCredentialAuthority,
    readiness_claim: ManagedSubscriptionReadinessClaim,
    provider_probe: VerifiedSubscriptionRuntimeProbe,
    credential_context_fingerprint: str,
    mem0_runtime_port: ManagedMem0RuntimeAttestationPort,
    mem0_runtime_descriptor: ManagedMem0RuntimeAuthorityDescriptor,
) -> str:
    runtime_identity, descriptor_identity, runtime_fingerprint = _runtime_authority_evidence_key(
        mem0_runtime_port, mem0_runtime_descriptor
    )
    material = "\n".join(
        (
            str(id(plan)),
            run_id,
            str(id(preflight_request)),
            str(id(credential_authority)),
            str(id(readiness_claim)),
            str(id(provider_probe)),
            credential_context_fingerprint,
            runtime_identity,
            descriptor_identity,
            runtime_fingerprint,
            limits.provider_kind,
            limits.answerer_model,
            limits.judge_model,
            str(limits.max_cases),
            str(limits.benchmark_max_provider_calls),
            str(limits.readiness_probe_provider_calls),
            str(limits.total_provider_attempt_ceiling),
            str(limits.benchmark_reserved_token_ceiling),
            str(limits.readiness_probe_estimated_tokens),
            limits.readiness_probe_usage_source,
            str(limits.total_accounted_tokens),
            str(limits.token_accounting_publishable),
            str(limits.post_reset_mem0_probe_attempt_ceiling),
            limits.issued_at.isoformat(),
            limits.deadline.isoformat(),
        )
    ).encode()
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def _credential_context_fingerprint(
    authority: object,
    readiness_claim: object,
    *,
    expected_request: object,
    expected_probe: object,
    run_id: str,
    deadline: datetime,
) -> str:
    try:
        fingerprint = _inspect_completed_managed_runtime_credential_context(
            authority,
            readiness_claim,
            expected_request=expected_request,
            expected_probe=expected_probe,
            run_id=run_id,
            deadline=deadline,
        )
    except ManagedRuntimeCredentialError:
        raise ManagedRunError("managed live credential authority is invalid") from None
    if type(fingerprint) is not str or _SHA256.fullmatch(fingerprint) is None:
        raise ManagedRunError("managed live credential authority is invalid")
    return fingerprint


def _runtime_authority_evidence_key(
    port: object,
    descriptor: object,
) -> tuple[str, str, str]:
    if type(descriptor) is not ManagedMem0RuntimeAuthorityDescriptor:
        raise ManagedRunError("managed live runtime authority type is invalid")
    try:
        current = inspect_pending_managed_mem0_runtime_authority(port)
    except ManagedMem0RuntimeAuthorityError:
        raise ManagedRunError("managed live runtime authority is unavailable") from None
    except Exception:
        raise ManagedRunError("managed live runtime authority integrity failed") from None
    if (
        current is not descriptor
        or type(descriptor.adapter_id) is not str
        or _IDENTIFIER.fullmatch(descriptor.adapter_id) is None
        or type(descriptor.implementation_sha256) is not str
        or _SHA256.fullmatch(descriptor.implementation_sha256) is None
        or type(descriptor.target_identity_sha256) is not str
        or _SHA256.fullmatch(descriptor.target_identity_sha256) is None
        or type(descriptor.probe_nonce_sha256) is not str
        or _SHA256.fullmatch(descriptor.probe_nonce_sha256) is None
        or type(descriptor.probe_token_credential_binding_id) is not str
        or _BINDING.fullmatch(descriptor.probe_token_credential_binding_id) is None
        or type(descriptor.request_timeout_seconds) is not float
        or not isfinite(descriptor.request_timeout_seconds)
        or descriptor.request_timeout_seconds <= 0
        or descriptor.deadline_policy != MANAGED_MEM0_RUNTIME_DEADLINE_POLICY
        or type(descriptor.deadline_budget_seconds) is not float
        or not isfinite(descriptor.deadline_budget_seconds)
        or descriptor.deadline_budget_seconds <= 0
        or type(descriptor.minimum_network_timeout_seconds) is not float
        or not isfinite(descriptor.minimum_network_timeout_seconds)
        or descriptor.minimum_network_timeout_seconds <= 0
        or descriptor.minimum_network_timeout_seconds > descriptor.request_timeout_seconds
        or type(descriptor.max_attempts) is not int
        or descriptor.max_attempts != 1
    ):
        raise ManagedRunError("managed live runtime authority integrity failed")
    fingerprint = hashlib.sha256(
        "\n".join(
            (
                descriptor.adapter_id,
                descriptor.implementation_sha256,
                descriptor.target_identity_sha256,
                descriptor.probe_nonce_sha256,
                descriptor.probe_token_credential_binding_id,
                repr(descriptor.request_timeout_seconds),
                descriptor.deadline_policy,
                repr(descriptor.deadline_budget_seconds),
                repr(descriptor.minimum_network_timeout_seconds),
                str(descriptor.max_attempts),
            )
        ).encode()
    ).hexdigest()
    return str(id(port)), str(id(descriptor)), fingerprint


__all__ = (
    "ManagedLiveExecutionLimits",
    "VerifiedManagedLiveRunPreparation",
    "managed_live_execution_limits",
    "prepare_verified_managed_live_run",
)
