"""Pure one-shot authorization boundary for managed live comparisons.

This module performs no I/O. A composition root obtains live provider and Mem0
runtime evidence, then exchanges those capabilities for one bounded authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from typing import final

from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
)
from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAttestationPort,
    ManagedMem0RuntimeAuthorityDescriptor,
    ManagedMem0RuntimeAuthorityError,
    inspect_pending_managed_mem0_runtime_authority,
    reserve_pending_managed_mem0_runtime_authority,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedCredentialBinding,
    ManagedPreflightRequest,
    ManagedPreflightResult,
    validate_managed_preflight,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    SUBSCRIPTION_BRIDGE_ENDPOINT_PATH,
    SUBSCRIPTION_BRIDGE_TRANSPORT,
    SUBSCRIPTION_RUNTIME_ENDPOINT_PATH,
    SUBSCRIPTION_RUNTIME_ORIGIN,
    SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    SUBSCRIPTION_RUNTIME_TRANSPORT,
    SUBSCRIPTION_RUNTIME_TRUST,
    SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES,
    SubscriptionRuntimeProbeError,
    VerifiedSubscriptionRuntimeProbe,
    inspect_verified_subscription_runtime_probe,
    reserve_verified_subscription_runtime_probe,
)

MANAGED_LIVE_ADMISSION_SCHEMA_VERSION = "memory-comparison-managed-live-admission.v1"
MANAGED_CANARY_MAX_CASES = 8
MANAGED_LIVE_MAX_PROVIDER_CALLS = 100_000
MANAGED_LIVE_MAX_TOTAL_TOKENS = 2_000_000_000
MANAGED_LIVE_MAX_DEADLINE_SECONDS = 172_800
MANAGED_SUBSCRIPTION_MAX_TOTAL_TOKENS = 2_000_000
MANAGED_SUBSCRIPTION_MAX_DEADLINE_SECONDS = 7_200

MANAGED_PROVIDER_OPENAI_API_KEY = "openai-api-key"
MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME = "subscription-runtime"

_TOKEN = object()
_LOCK = threading.RLock()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_CASE_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")


class ManagedLiveAdmissionError(ValueError):
    """Secret-safe rejection of a live execution authorization."""


@final
@dataclass(frozen=True, slots=True)
class ManagedLiveBudget:
    """Hard answer/judge bounds carried into the live composition.

    Backend-internal provider work is deliberately outside this budget.
    """

    max_cases: int
    max_provider_calls: int
    max_total_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.max_cases) is not int
            or not 1 <= self.max_cases <= 10_000
            or type(self.max_provider_calls) is not int
            or not 1 <= self.max_provider_calls <= MANAGED_LIVE_MAX_PROVIDER_CALLS
            or type(self.max_total_tokens) is not int
            or not 1 <= self.max_total_tokens <= MANAGED_LIVE_MAX_TOTAL_TOKENS
        ):
            _fail("managed live budget is invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedLiveBudget is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedLiveProviderUsageBudget:
    """Hard answer/judge reservations plus non-publishable readiness estimates.

    Backend-internal provider calls and costs are intentionally unmeasured.
    """

    provider_kind: str
    benchmark_max_provider_calls: int
    readiness_probe_provider_calls: int
    total_provider_attempt_ceiling: int
    benchmark_reserved_token_ceiling: int
    readiness_probe_estimated_tokens: int
    readiness_probe_usage_source: str
    total_accounted_tokens: int
    token_accounting_publishable: bool

    def __post_init__(self) -> None:
        if (
            self.provider_kind != MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME
            or type(self.benchmark_max_provider_calls) is not int
            or self.benchmark_max_provider_calls < 1
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
        ):
            _fail("managed live provider usage budget is invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "provider_kind": self.provider_kind,
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
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedLiveProviderUsageBudget is final")


@final
class VerifiedManagedLiveAdmission:
    """Opaque, noncopyable and single-use authority for one exact live run."""

    __slots__ = ("__commitment", "__nonce", "__weakref__")

    def __init__(self, *, commitment: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed live admissions must be issued authoritatively")
        self.__commitment = commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedManagedLiveAdmission is final")

    def __repr__(self) -> str:
        return "VerifiedManagedLiveAdmission(<sealed-one-shot>)"

    def __copy__(self) -> object:
        raise TypeError("managed live admission is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed live admission is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed live admission is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed live admission is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed live admission is nonserializable")


@dataclass(frozen=True, slots=True)
class _ManagedLiveAdmissionMaterial:
    request: ManagedPreflightRequest = field(repr=False)
    preflight: ManagedPreflightResult = field(repr=False)
    run_id: str
    run_nonce_commitment_sha256: str
    canary_case_ids: tuple[str, ...]
    mem0_probe_credential: ManagedCredentialBinding = field(repr=False)
    mem0_runtime_port: ManagedMem0RuntimeAttestationPort = field(repr=False)
    mem0_runtime_descriptor: ManagedMem0RuntimeAuthorityDescriptor = field(repr=False)
    provider_kind: str
    live_provider_evidence: object = field(repr=False)
    budget: ManagedLiveBudget
    provider_usage_budget: ManagedLiveProviderUsageBudget
    issued_at: datetime
    deadline: datetime


@dataclass(frozen=True, slots=True)
class _AdmissionState:
    material: _ManagedLiveAdmissionMaterial
    snapshot: bytes = field(repr=False)
    secret: bytes = field(repr=False)
    commitment: str = field(repr=False)
    nonce: str = field(repr=False)


_ADMISSIONS: weakref.WeakKeyDictionary[VerifiedManagedLiveAdmission, _AdmissionState] = (
    weakref.WeakKeyDictionary()
)
_RESERVED_OFFICIAL_PROVIDER_EVIDENCE: dict[int, ProviderRouteAttestation] = {}


def issue_verified_managed_live_admission(
    *,
    request: ManagedPreflightRequest,
    allow_live: bool,
    allow_paid_llm: bool,
    allow_full_run: bool,
    run_id: str,
    run_nonce_commitment_sha256: str,
    canary_case_ids: tuple[str, ...],
    mem0_probe_credential: ManagedCredentialBinding,
    mem0_runtime_port: ManagedMem0RuntimeAttestationPort,
    provider_kind: str,
    live_provider_evidence: object,
    budget: ManagedLiveBudget,
    issued_at: datetime,
    deadline: datetime,
    now: datetime,
) -> VerifiedManagedLiveAdmission:
    """Revalidate exact capabilities and issue one bounded execution authority."""

    # Operator gates deliberately run before any extensible validation seam.
    if allow_live is not True:
        _fail("explicit live authorization is required")
    if allow_paid_llm is not True:
        _fail("explicit paid LLM authorization is required")
    if type(allow_full_run) is not bool:
        _fail("full-run authorization flag is invalid")

    trusted_now = _aware_instant(now, "managed live now")
    trusted_issued_at = _aware_instant(issued_at, "managed live issued_at")
    trusted_deadline = _aware_instant(deadline, "managed live deadline")
    if trusted_issued_at != trusted_now:
        _fail("managed live issued_at must equal the supplied clock instant")
    if not trusted_issued_at < trusted_deadline:
        _fail("managed live deadline must follow issuance")
    if type(request) is not ManagedPreflightRequest:
        _fail("managed live preflight request type is invalid")

    preflight = _trusted_preflight(request)
    scope = preflight.scope
    if request.scope != scope or scope not in {
        FULL_COMPARISON_SCOPE_FULL,
        FULL_COMPARISON_SCOPE_CANARY,
    }:
        _fail("managed live scope must be exact")
    selected = _scope_case_ids(scope, canary_case_ids, allow_full_run=allow_full_run)
    trusted_budget = _budget_for_scope(preflight, budget, selected)
    maximum_duration = min(
        float(preflight.timeouts.run_seconds),
        float(MANAGED_LIVE_MAX_DEADLINE_SECONDS),
    )
    if (trusted_deadline - trusted_issued_at).total_seconds() > maximum_duration:
        _fail("managed live deadline exceeds the preflight budget")

    trusted_run_id = _identifier(run_id, "managed live run_id")
    run_nonce = _digest(run_nonce_commitment_sha256, "managed run nonce commitment")
    probe_credential = _probe_credential(mem0_probe_credential, preflight)
    runtime_descriptor = _runtime_authority_descriptor(
        mem0_runtime_port,
        preflight=preflight,
        probe_credential=probe_credential,
        admitted_wall_budget_seconds=(trusted_deadline - trusted_issued_at).total_seconds(),
    )
    trusted_provider_kind = _provider_kind(provider_kind, scope=scope)
    if trusted_provider_kind == MANAGED_PROVIDER_OPENAI_API_KEY:
        _fail("official provider live admission requires opaque call evidence")
    if trusted_provider_kind == MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME and (
        trusted_budget.max_provider_calls != len(selected) * 4
        or trusted_budget.max_total_tokens > MANAGED_SUBSCRIPTION_MAX_TOTAL_TOKENS
        or (trusted_deadline - trusted_issued_at).total_seconds()
        > MANAGED_SUBSCRIPTION_MAX_DEADLINE_SECONDS
    ):
        _fail("subscription runtime canary budget is invalid")
    provider_payload = _provider_evidence_payload(
        trusted_provider_kind,
        live_provider_evidence,
        preflight=preflight,
        now=trusted_now,
    )
    provider_usage_budget = _provider_usage_budget(
        trusted_budget,
        provider_kind=trusted_provider_kind,
        provider_payload=provider_payload,
    )
    runtime_payload = _runtime_authority_payload(runtime_descriptor)
    material = _ManagedLiveAdmissionMaterial(
        request=request,
        preflight=preflight,
        run_id=trusted_run_id,
        run_nonce_commitment_sha256=run_nonce,
        canary_case_ids=selected,
        mem0_probe_credential=probe_credential,
        mem0_runtime_port=mem0_runtime_port,
        mem0_runtime_descriptor=runtime_descriptor,
        provider_kind=trusted_provider_kind,
        live_provider_evidence=live_provider_evidence,
        budget=trusted_budget,
        provider_usage_budget=provider_usage_budget,
        issued_at=trusted_issued_at,
        deadline=trusted_deadline,
    )
    snapshot = _admission_snapshot(
        material,
        provider_payload=provider_payload,
        runtime_payload=runtime_payload,
    )
    secret = secrets.token_bytes(32)
    nonce = secrets.token_hex(32)
    commitment = _state_commitment(secret, snapshot, material=material, nonce=nonce)
    admission = VerifiedManagedLiveAdmission(
        commitment=commitment,
        nonce=nonce,
        _token=_TOKEN,
    )
    with _LOCK:
        _reserve_live_evidence(
            provider_kind=trusted_provider_kind,
            provider_evidence=live_provider_evidence,
            mem0_runtime_port=mem0_runtime_port,
            runtime_descriptor=runtime_descriptor,
            now=trusted_now,
        )
        _ADMISSIONS[admission] = _AdmissionState(
            material=material,
            snapshot=snapshot,
            secret=secret,
            commitment=commitment,
            nonce=nonce,
        )
    return admission


def _consume_verified_managed_live_admission(
    admission: VerifiedManagedLiveAdmission,
    *,
    expected_request: ManagedPreflightRequest,
    now: datetime,
) -> _ManagedLiveAdmissionMaterial:
    """Private one-shot seam for the later managed plan composition."""

    if type(admission) is not VerifiedManagedLiveAdmission:
        _fail("managed live admission type is invalid")
    trusted_now = _aware_instant(now, "managed live consume now")
    with _LOCK:
        state = _ADMISSIONS.get(admission)
        if state is None:
            _fail("managed live admission is unavailable or consumed")
        # Any consume attempt burns the authority, including failed revalidation.
        del _ADMISSIONS[admission]
        material = state.material
        if expected_request is not material.request:
            _fail("managed live preflight request identity differs")
        if trusted_now < material.issued_at or trusted_now > material.deadline:
            _fail("managed live admission is expired or not yet current")

        current_preflight = _trusted_preflight(material.request)
        if current_preflight != material.preflight:
            _fail("managed live preflight changed after issuance")
        provider_payload = _provider_evidence_payload(
            material.provider_kind,
            material.live_provider_evidence,
            preflight=current_preflight,
            now=trusted_now,
        )
        runtime_descriptor = _runtime_authority_descriptor(
            material.mem0_runtime_port,
            preflight=current_preflight,
            probe_credential=material.mem0_probe_credential,
            admitted_wall_budget_seconds=(material.deadline - material.issued_at).total_seconds(),
        )
        if runtime_descriptor is not material.mem0_runtime_descriptor:
            _fail("managed Mem0 runtime authority changed after issuance")
        runtime_payload = _runtime_authority_payload(runtime_descriptor)
        current_snapshot = _admission_snapshot(
            material,
            provider_payload=provider_payload,
            runtime_payload=runtime_payload,
        )
        _validate_opaque(admission, state)
        expected_commitment = _state_commitment(
            state.secret,
            current_snapshot,
            material=material,
            nonce=state.nonce,
        )
        if current_snapshot != state.snapshot or not hmac.compare_digest(
            expected_commitment, state.commitment
        ):
            _fail("managed live admission integrity failed")
        return material


def _trusted_preflight(request: ManagedPreflightRequest) -> ManagedPreflightResult:
    try:
        result = validate_managed_preflight(request)
    except Exception:
        _fail("managed live preflight validation failed")
    if type(result) is not ManagedPreflightResult or result.ready is not True:
        _fail("managed live preflight result is invalid")
    return result


def _scope_case_ids(
    scope: str,
    case_ids: object,
    *,
    allow_full_run: bool,
) -> tuple[str, ...]:
    if scope == FULL_COMPARISON_SCOPE_FULL:
        if allow_full_run is not True:
            _fail("full managed run requires explicit authorization")
        if case_ids != ():
            _fail("full managed run cannot accept canary case IDs")
        return ()
    if allow_full_run is not False:
        _fail("canary admission cannot carry full-run authorization")
    return _canary_case_ids(case_ids)


def _canary_case_ids(value: object) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not 1 <= len(value) <= MANAGED_CANARY_MAX_CASES
        or any(
            type(item) is not str or item != item.strip() or _CASE_ID.fullmatch(item) is None
            for item in value
        )
        or len(set(value)) != len(value)
    ):
        _fail("managed canary case IDs are invalid")
    return value


def _budget_for_scope(
    preflight: ManagedPreflightResult,
    budget: object,
    canary_case_ids: tuple[str, ...],
) -> ManagedLiveBudget:
    if type(budget) is not ManagedLiveBudget:
        _fail("managed live budget type is invalid")
    expected_cases = (
        preflight.dataset_case_count
        if preflight.scope == FULL_COMPARISON_SCOPE_FULL
        else len(canary_case_ids)
    )
    if budget.max_cases != expected_cases or budget.max_provider_calls != expected_cases * 4:
        _fail("managed live budget differs from selected scope")
    return budget


def _provider_usage_budget(
    budget: ManagedLiveBudget,
    *,
    provider_kind: str,
    provider_payload: dict[str, object],
) -> ManagedLiveProviderUsageBudget:
    if provider_kind != MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME:
        _fail("managed provider usage accounting is unavailable")
    probe_calls = provider_payload.get("provider_call_count")
    probe_tokens = provider_payload.get("total_tokens")
    usage_source = provider_payload.get("usage_source")
    if (
        type(probe_calls) is not int
        or probe_calls != 1
        or type(probe_tokens) is not int
        or probe_tokens < 1
        or type(usage_source) is not str
        or usage_source not in SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES
    ):
        _fail("subscription readiness usage evidence is invalid")
    return ManagedLiveProviderUsageBudget(
        provider_kind=provider_kind,
        benchmark_max_provider_calls=budget.max_provider_calls,
        readiness_probe_provider_calls=probe_calls,
        total_provider_attempt_ceiling=budget.max_provider_calls + probe_calls,
        benchmark_reserved_token_ceiling=budget.max_total_tokens,
        readiness_probe_estimated_tokens=probe_tokens,
        readiness_probe_usage_source=usage_source,
        total_accounted_tokens=budget.max_total_tokens + probe_tokens,
        token_accounting_publishable=False,
    )


def _reserve_live_evidence(
    *,
    provider_kind: str,
    provider_evidence: object,
    mem0_runtime_port: object,
    runtime_descriptor: object,
    now: datetime,
) -> None:
    if type(runtime_descriptor) is not ManagedMem0RuntimeAuthorityDescriptor:
        _fail("managed Mem0 runtime authority descriptor type is invalid")
    try:
        reserve_pending_managed_mem0_runtime_authority(
            mem0_runtime_port,
            runtime_descriptor,
        )
    except ManagedMem0RuntimeAuthorityError as exc:
        _fail(str(exc))

    if provider_kind == MANAGED_PROVIDER_OPENAI_API_KEY:
        if type(provider_evidence) is not ProviderRouteAttestation:
            _fail("official provider evidence type is invalid")
        provider_identity = id(provider_evidence)
        if provider_identity in _RESERVED_OFFICIAL_PROVIDER_EVIDENCE:
            _fail("official provider evidence was already reserved")
    elif provider_kind == MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME:
        if type(provider_evidence) is not VerifiedSubscriptionRuntimeProbe:
            _fail("subscription runtime validation type is invalid")
        try:
            reserve_verified_subscription_runtime_probe(provider_evidence, now=now)
        except SubscriptionRuntimeProbeError as exc:
            _fail(str(exc))
    else:
        _fail("managed provider kind is invalid")

    if provider_kind == MANAGED_PROVIDER_OPENAI_API_KEY:
        _RESERVED_OFFICIAL_PROVIDER_EVIDENCE[id(provider_evidence)] = provider_evidence


def _probe_credential(
    value: object,
    preflight: ManagedPreflightResult,
) -> ManagedCredentialBinding:
    if (
        type(value) is not ManagedCredentialBinding
        or value.credential_name != "mem0-probe"
        or value.configured is not True
        or type(value.binding_id) is not str
        or _BINDING.fullmatch(value.binding_id) is None
    ):
        _fail("managed Mem0 probe credential binding is invalid")
    bindings = tuple(item.binding_id for item in preflight.credentials)
    if value.binding_id in bindings:
        _fail("managed Mem0 probe credential must be separately bound")
    return value


def _provider_kind(value: object, *, scope: str) -> str:
    if type(value) is not str or value not in {
        MANAGED_PROVIDER_OPENAI_API_KEY,
        MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    }:
        _fail("managed provider kind is invalid")
    if value == MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME and scope != FULL_COMPARISON_SCOPE_CANARY:
        _fail("subscription runtime is admitted only for bounded canaries")
    return value


def _provider_evidence_payload(
    provider_kind: str,
    evidence: object,
    *,
    preflight: ManagedPreflightResult,
    now: datetime,
) -> dict[str, object]:
    if provider_kind == MANAGED_PROVIDER_OPENAI_API_KEY:
        if type(evidence) is not ProviderRouteAttestation:
            _fail("official provider evidence type is invalid")
        route = evidence
        planned = preflight.provider_route
        if (
            route.trust != planned.trust
            or route.origin != planned.origin
            or route.endpoint_path != planned.endpoint_path
            or route.route_sha256 != planned.route_sha256
            or route.transport_evidence != planned.transport_evidence
            or route.request_method != planned.request_method
            or type(route.response_status) is not int
            or not 200 <= route.response_status < 300
            or route.credential_binding_id != planned.credential_binding_id
        ):
            _fail("official provider live route differs from preflight")
        openai = tuple(item for item in preflight.credentials if item.credential_name == "openai")
        if (
            len(openai) != 1
            or openai[0].configured is not True
            or openai[0].binding_id != route.credential_binding_id
        ):
            _fail("official provider credential binding differs")
        public = route.public_payload()
        if (
            public.get("credential_binding_id") != route.credential_binding_id
            or public.get("response_status") != route.response_status
        ):
            _fail("official provider evidence is invalid")
        return {"provider_kind": provider_kind, "route": public}

    if type(evidence) is not VerifiedSubscriptionRuntimeProbe:
        _fail("subscription runtime validation type is invalid")
    subscription_credentials = tuple(
        item for item in preflight.credentials if item.credential_name == "subscription-runtime"
    )
    if (
        len(subscription_credentials) != 1
        or subscription_credentials[0].configured is not True
        or subscription_credentials[0].binding_id is None
        or preflight.provider_route.credential_binding_id != subscription_credentials[0].binding_id
    ):
        _fail("subscription runtime credential binding is required")
    try:
        observation = inspect_verified_subscription_runtime_probe(
            evidence,
            now=now,
        )
    except SubscriptionRuntimeProbeError as exc:
        _fail(str(exc))
    planned = preflight.provider_route
    observed_route = observation.route
    if (
        planned.trust != observed_route.trust
        or planned.origin != observed_route.origin
        or planned.endpoint_path != observed_route.endpoint_path
        or planned.route_sha256 != observed_route.route_sha256
        or planned.transport_evidence != observed_route.transport_evidence
        or planned.request_method != observed_route.request_method
        or getattr(planned, "credential_binding_id", None) != observed_route.credential_binding_id
        or observation.model != preflight.answerer_model
        or observation.model != preflight.judge_model
    ):
        _fail("subscription runtime validation differs from preflight")
    return {
        "provider_kind": provider_kind,
        **observation.public_payload(),
    }


def _runtime_authority_descriptor(
    port: object,
    *,
    preflight: ManagedPreflightResult,
    probe_credential: ManagedCredentialBinding,
    admitted_wall_budget_seconds: float,
) -> ManagedMem0RuntimeAuthorityDescriptor:
    try:
        descriptor = inspect_pending_managed_mem0_runtime_authority(port)
    except ManagedMem0RuntimeAuthorityError as exc:
        _fail(str(exc))
    if type(descriptor) is not ManagedMem0RuntimeAuthorityDescriptor:
        _fail("managed Mem0 runtime authority descriptor type is invalid")
    mem0_targets = tuple(
        item.target.target_identity_sha256
        for item in preflight.backend_endpoints
        if item.target.backend_role == "mem0"
    )
    if (
        len(mem0_targets) != 1
        or type(descriptor.adapter_id) is not str
        or not descriptor.adapter_id
        or type(descriptor.implementation_sha256) is not str
        or _SHA256.fullmatch(descriptor.implementation_sha256) is None
        or descriptor.target_identity_sha256 != mem0_targets[0]
        or type(descriptor.probe_nonce_sha256) is not str
        or _SHA256.fullmatch(descriptor.probe_nonce_sha256) is None
        or descriptor.probe_token_credential_binding_id != probe_credential.binding_id
        or descriptor.deadline_policy != MANAGED_MEM0_RUNTIME_DEADLINE_POLICY
        or descriptor.max_attempts != 1
    ):
        _fail("managed Mem0 runtime authority binding differs")
    timeout = descriptor.request_timeout_seconds
    deadline_budget = descriptor.deadline_budget_seconds
    minimum_timeout = descriptor.minimum_network_timeout_seconds
    if (
        type(timeout) is not float
        or not isfinite(timeout)
        or timeout <= 0
        or type(deadline_budget) is not float
        or not isfinite(deadline_budget)
        or deadline_budget <= 0
        or type(minimum_timeout) is not float
        or not isfinite(minimum_timeout)
        or minimum_timeout <= 0
        or minimum_timeout > timeout
        or not isfinite(admitted_wall_budget_seconds)
        or admitted_wall_budget_seconds <= 0
        or timeout > float(preflight.timeouts.request_seconds)
        or deadline_budget > float(preflight.timeouts.run_seconds)
        or deadline_budget > admitted_wall_budget_seconds
    ):
        _fail("managed Mem0 runtime authority deadline is invalid")
    return descriptor


def _runtime_authority_payload(
    descriptor: ManagedMem0RuntimeAuthorityDescriptor,
) -> dict[str, object]:
    return {
        "status": "pending_post_reset",
        "adapter_id": descriptor.adapter_id,
        "implementation_sha256": descriptor.implementation_sha256,
        "target_identity_sha256": descriptor.target_identity_sha256,
        "probe_nonce_sha256": descriptor.probe_nonce_sha256,
        "probe_token_credential_binding_id": (descriptor.probe_token_credential_binding_id),
        "request_timeout_seconds": descriptor.request_timeout_seconds,
        "deadline_policy": descriptor.deadline_policy,
        "deadline_budget_seconds": descriptor.deadline_budget_seconds,
        "minimum_network_timeout_seconds": descriptor.minimum_network_timeout_seconds,
        "post_reset_mem0_probe_attempt_ceiling": descriptor.max_attempts,
    }


def _admission_snapshot(
    material: _ManagedLiveAdmissionMaterial,
    *,
    provider_payload: dict[str, object],
    runtime_payload: dict[str, object],
) -> bytes:
    preflight = material.preflight
    payload = {
        "schema_version": MANAGED_LIVE_ADMISSION_SCHEMA_VERSION,
        "preflight": preflight.public_payload(),
        "credential_commitments": [
            [item.credential_name, item.configured, item.binding_id]
            for item in preflight.credentials
        ],
        "mem0_probe_credential": [
            material.mem0_probe_credential.credential_name,
            material.mem0_probe_credential.binding_id,
        ],
        "backend_endpoints": [
            {
                "backend_role": item.target.backend_role,
                "target_identity_sha256": item.target.target_identity_sha256,
                "base_url": item.base_url,
                "credential_binding_id": item.credential.binding_id,
            }
            for item in preflight.backend_endpoints
        ],
        "run_id": material.run_id,
        "run_nonce_commitment_sha256": material.run_nonce_commitment_sha256,
        "scope": preflight.scope,
        "canary_case_ids": list(material.canary_case_ids),
        "provider": provider_payload,
        "runtime": runtime_payload,
        "budget": {
            "max_cases": material.budget.max_cases,
            "max_provider_calls": material.budget.max_provider_calls,
            "max_total_tokens": material.budget.max_total_tokens,
            "provider_usage": material.provider_usage_budget.public_payload(),
            "post_reset_mem0_probe_attempt_ceiling": 1,
        },
        "issued_at": _instant_text(material.issued_at),
        "deadline": _instant_text(material.deadline),
    }
    return _canonical_json(payload)


def _state_commitment(
    secret: bytes,
    snapshot: bytes,
    *,
    material: _ManagedLiveAdmissionMaterial,
    nonce: str,
) -> str:
    identities = _canonical_json(
        {
            "request_identity": id(material.request),
            "preflight_identity": id(material.preflight),
            "provider_evidence_identity": id(material.live_provider_evidence),
            "mem0_runtime_port_identity": id(material.mem0_runtime_port),
            "mem0_runtime_descriptor_identity": id(material.mem0_runtime_descriptor),
            "nonce": nonce,
        }
    )
    return hmac.new(secret, snapshot + b"\n" + identities, hashlib.sha256).hexdigest()


def _validate_opaque(
    admission: VerifiedManagedLiveAdmission,
    state: _AdmissionState,
) -> None:
    try:
        commitment = admission._VerifiedManagedLiveAdmission__commitment
        nonce = admission._VerifiedManagedLiveAdmission__nonce
    except (AttributeError, TypeError):
        _fail("managed live admission integrity failed")
    if (
        type(commitment) is not str
        or type(nonce) is not str
        or not hmac.compare_digest(commitment, state.commitment)
        or not hmac.compare_digest(nonce, state.nonce)
    ):
        _fail("managed live admission integrity failed")


def _identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"{field_name} is invalid")
    return value


def _digest(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{field_name} is invalid")
    return value


def _aware_instant(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        _fail(f"{field_name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if not 1970 <= normalized.year <= 2100:
        _fail(f"{field_name} is outside the supported range")
    return normalized


def _instant_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _fail(message: str) -> None:
    raise ManagedLiveAdmissionError(message)


__all__ = (
    "SUBSCRIPTION_BRIDGE_ENDPOINT_PATH",
    "SUBSCRIPTION_BRIDGE_TRANSPORT",
    "SUBSCRIPTION_RUNTIME_ENDPOINT_PATH",
    "SUBSCRIPTION_RUNTIME_ORIGIN",
    "SUBSCRIPTION_RUNTIME_ROUTE_SHA256",
    "SUBSCRIPTION_RUNTIME_TRANSPORT",
    "SUBSCRIPTION_RUNTIME_TRUST",
    "MANAGED_CANARY_MAX_CASES",
    "MANAGED_LIVE_ADMISSION_SCHEMA_VERSION",
    "MANAGED_PROVIDER_OPENAI_API_KEY",
    "MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME",
    "ManagedLiveAdmissionError",
    "ManagedLiveBudget",
    "ManagedLiveProviderUsageBudget",
    "VerifiedManagedLiveAdmission",
    "VerifiedSubscriptionRuntimeProbe",
    "issue_verified_managed_live_admission",
)
