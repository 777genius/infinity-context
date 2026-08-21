"""Fail-closed two-stage composition root for the managed-v5 live canary."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
    _consume_verified_managed_live_run_preparation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    _inspect_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_production_composition import (
    MANAGED_PRODUCTION_EXECUTION_V5,
    ManagedV5ProductionExecutionSelection,
)
from infinity_context_server.memory_comparison_managed_run import (
    create_managed_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    ManagedV5PublicRunPreparation,
    _authenticate_managed_v5_public_run_preparation,
    prepare_managed_v5_public_run,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedV5LivePrivateDependencyFactory,
)
from infinity_context_server.memory_comparison_managed_v5_live_public_inputs import (
    ManagedV5LivePublicInputs,
    ManagedV5LiveRootError,
)
from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    activate_managed_v5_production_runtime_with_factory,
)
from infinity_context_server.resumable_operation_journal.domain import OperationManifest

_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_MAX_OUTPUT_TOKENS_PER_CALL = 4096


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LivePrivateInputs:
    """Post-readiness material required to activate one exact runtime."""

    verified_preparation: VerifiedManagedLiveRunPreparation = field(repr=False)
    dependency_factory: ManagedV5LivePrivateDependencyFactory = field(repr=False)
    now: datetime
    wall_clock: Callable[[], datetime]
    monotonic_clock: Callable[[], float]
    infinity_execution_transport: httpx.BaseTransport | None = field(default=None, repr=False)
    infinity_lifecycle_transport: httpx.BaseTransport | None = field(default=None, repr=False)
    infinity_registry_policy_transport: httpx.BaseTransport | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.verified_preparation) is not VerifiedManagedLiveRunPreparation
            or type(self.dependency_factory) is not ManagedV5LivePrivateDependencyFactory
            or type(self.now) is not datetime
            or self.now.tzinfo is None
            or self.now.utcoffset() is None
            or not callable(self.wall_clock)
            or not callable(self.monotonic_clock)
            or any(
                value is not None and not isinstance(value, httpx.BaseTransport)
                for value in (
                    self.infinity_execution_transport,
                    self.infinity_lifecycle_transport,
                    self.infinity_registry_policy_transport,
                )
            )
        ):
            raise ManagedV5LiveRootError("managed_v5_live_private_inputs_invalid")


@final
class PreparedManagedV5LiveRun:
    """Opaque one-shot root capability; public preparation details never escape."""

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "PreparedManagedV5LiveRun(<sealed-one-shot>)"

    def __reduce__(self) -> object:
        raise TypeError("managed v5 live root preparation is nonserializable")


@dataclass(frozen=True, slots=True)
class _PreparedState:
    preparation: ManagedV5PublicRunPreparation = field(repr=False)
    inputs: ManagedV5LivePublicInputs = field(repr=False)
    production_authority: object = field(repr=False)
    operation_manifest: OperationManifest = field(repr=False)
    integrity_mac: bytes = field(repr=False)


_STATES: weakref.WeakKeyDictionary[PreparedManagedV5LiveRun, _PreparedState] = (
    weakref.WeakKeyDictionary()
)


@final
@dataclass(frozen=True, slots=True)
class SelectedManagedV5LiveExecution:
    execution_mode: str
    selection: ManagedV5ProductionExecutionSelection

    def __post_init__(self) -> None:
        if (
            self.execution_mode != MANAGED_PRODUCTION_EXECUTION_V5
            or type(self.selection) is not ManagedV5ProductionExecutionSelection
        ):
            raise ManagedV5LiveRootError("managed_v5_live_selection_invalid")


def prepare_managed_v5_live_run(inputs: ManagedV5LivePublicInputs) -> PreparedManagedV5LiveRun:
    """Finish public validation without secret, readiness, TCP or provider I/O."""

    if type(inputs) is not ManagedV5LivePublicInputs:
        raise ManagedV5LiveRootError("managed_v5_live_public_inputs_invalid")
    try:
        require_managed_mem0_v5_extraction_contract_binding(inputs.extraction_contract_binding)
    except Exception:
        raise ManagedV5LiveRootError("managed_v5_live_public_inputs_invalid") from None
    preparation = prepare_managed_v5_public_run(
        cases=inputs.cases,
        current_date=inputs.current_date,
        request=inputs.request,
        composition_binding=inputs.composition_binding,
        origin=inputs.mem0_origin,
        timeout_seconds=inputs.timeout_seconds,
        state_paths=inputs.state_paths,
        credential_paths=inputs.credential_paths,
        runtime_receipt_boundary=inputs.runtime_receipt_boundary,
        trusted_runtime_binding=inputs.trusted_runtime_binding,
        receipt_authority=inputs.receipt_authority,
        transport=inputs.mem0_transport,
    )
    state = _authenticate_managed_v5_public_run_preparation(preparation)
    prepared = PreparedManagedV5LiveRun()
    root_state = _PreparedState(
        preparation,
        inputs,
        state.production_authority,
        state.operation_manifest,
        b"",
    )
    root_state = replace(root_state, integrity_mac=_state_mac(prepared, root_state))
    with _LOCK:
        _STATES[prepared] = root_state
    return prepared


def activate_managed_v5_live_run(
    prepared: PreparedManagedV5LiveRun,
    private: ManagedV5LivePrivateInputs,
) -> SelectedManagedV5LiveExecution:
    """Activate after readiness and return an explicit v5-only selection."""

    if (
        type(prepared) is not PreparedManagedV5LiveRun
        or type(private) is not ManagedV5LivePrivateInputs
    ):
        raise ManagedV5LiveRootError("managed_v5_live_activation_inputs_invalid")
    with _LOCK:
        state = _STATES.get(prepared)
        if state is None or not hmac.compare_digest(
            state.integrity_mac, _state_mac(prepared, replace(state, integrity_mac=b""))
        ):
            raise ManagedV5LiveRootError("managed_v5_live_preparation_unavailable")
        del _STATES[prepared]
    public = state.inputs
    try:
        if private.dependency_factory.extraction_token_budget != public.extraction_token_budget:
            raise ManagedV5LiveRootError("managed_v5_live_extraction_budget_cross_wired")
        material = _consume_verified_managed_live_run_preparation(
            private.verified_preparation,
            now=private.now,
        )
        plan = _inspect_verified_managed_run_plan(material.plan)
        private_bindings = create_managed_comparison_run_bindings(material.plan)
        _require_private_matches_public(plan, private_bindings, public, material.limits)
        infinity_origin = _backend_origin(material.preflight_request, "infinity-context")
        deadline_monotonic = _monotonic_deadline(
            material.limits.deadline,
            wall_clock=private.wall_clock,
            monotonic_clock=private.monotonic_clock,
        )
        subscription = material.credential_authority.issue_subscription_execution_adapter(
            readiness_claim=material.readiness_claim,
            expected_request=material.preflight_request,
            run_id=plan.run_id,
            subscription_origin=material.preflight_request.provider_route.origin,
            deadline=material.limits.deadline,
            now=private.now,
        )
    except BaseException:
        raise
    try:
        provider = BoundedProviderChatCompletions(
            delegate=subscription,
            budget=BoundedProviderBudget(
                max_total_tokens=material.limits.benchmark_reserved_token_ceiling,
                deadline_monotonic=deadline_monotonic,
                max_calls=material.limits.benchmark_max_provider_calls,
                max_output_tokens_per_call=_MAX_OUTPUT_TOKENS_PER_CALL,
            ),
            monotonic_clock=private.monotonic_clock,
        )
    except BaseException:
        _close_without_masking(subscription)
        raise
    try:
        infinity_credentials = material.credential_authority.issue_managed_v5_infinity_credentials(
            expected_request=material.preflight_request,
            public_preparation=state.preparation,
            run_id=plan.run_id,
            infinity_origin=infinity_origin,
            deadline=material.limits.deadline,
            now=private.now,
            execution_transport=private.infinity_execution_transport,
            lifecycle_transport=private.infinity_lifecycle_transport,
            registry_policy_transport=private.infinity_registry_policy_transport,
        )
        runtime = activate_managed_v5_production_runtime_with_factory(
            state.preparation,
            cases=public.cases,
            request=public.request,
            composition_binding=public.composition_binding,
            receipt_authority=public.receipt_authority,
            production_authority=state.production_authority,
            plan=material.plan,
            run_bindings=private_bindings,
            now=private.now,
            deadline=material.limits.deadline,
            infinity_credentials=infinity_credentials,
            dependency_factory=private.dependency_factory,
            current_date=public.current_date,
            mem0_origin=public.mem0_origin,
            timeout_seconds=public.timeout_seconds,
            state_paths=public.state_paths,
            credential_paths=public.credential_paths,
            runtime_receipt_boundary=public.runtime_receipt_boundary,
            trusted_runtime_binding=public.trusted_runtime_binding,
            mem0_transport=public.mem0_transport,
            clock=private.wall_clock,
        )
    except BaseException:
        _close_without_masking(provider)
        raise
    return SelectedManagedV5LiveExecution(
        MANAGED_PRODUCTION_EXECUTION_V5,
        ManagedV5ProductionExecutionSelection(
            runtime=runtime,
            provider=provider,
            limits=material.limits,
            provider_route=plan.provider_route,
            attestation_port=material.mem0_runtime_port,
            clock=private.wall_clock,
        ),
    )


def _backend_origin(request: object, role: str) -> str:
    try:
        values = tuple(
            item.base_url for item in request.backend_endpoints if item.target.backend_role == role
        )
    except Exception:
        values = ()
    if len(values) != 1 or type(values[0]) is not str or not values[0]:
        raise ManagedV5LiveRootError("managed_v5_live_backend_origin_invalid")
    return values[0]


def _close_without_masking(resource: object) -> None:
    try:
        close = resource.close
        close()
    except BaseException:
        pass


def _require_private_matches_public(
    plan: object,
    private_bindings: object,
    public: ManagedV5LivePublicInputs,
    limits: object,
) -> None:
    try:
        composition = public.composition_binding
        valid = (
            plan.cases == public.cases
            and plan.run_id == public.request.run_id
            and plan.backend_targets == composition.backend_targets
            and private_bindings.binding_commitment_sha256 == composition.binding_commitment_sha256
            and private_bindings.profile_id == composition.profile_id
            and plan.profile.profile_id == composition.profile_id
            and plan.profile.retrieval_top_k == composition.retrieval_top_k
            and plan.profile.answer_cutoff == composition.answer_cutoff
            and limits.benchmark_reserved_token_ceiling
            == public.extraction_token_budget.answer_judge_reserved_token_ceiling
        )
    except Exception:
        valid = False
    if not valid:
        raise ManagedV5LiveRootError("managed_v5_live_private_preparation_cross_wired")


def _monotonic_deadline(
    deadline: datetime,
    *,
    wall_clock: Callable[[], datetime],
    monotonic_clock: Callable[[], float],
) -> float:
    wall_now = wall_clock()
    monotonic_now = monotonic_clock()
    if (
        type(wall_now) is not datetime
        or wall_now.tzinfo is None
        or wall_now.utcoffset() is None
        or isinstance(monotonic_now, bool)
        or not isinstance(monotonic_now, int | float)
        or not math.isfinite(float(monotonic_now))
    ):
        raise ManagedV5LiveRootError("managed_v5_live_clock_invalid")
    remaining = (deadline - wall_now).total_seconds()
    if not math.isfinite(remaining) or remaining <= 0:
        raise ManagedV5LiveRootError("managed_v5_live_deadline_expired")
    return float(monotonic_now) + remaining


def _state_mac(prepared: PreparedManagedV5LiveRun, state: _PreparedState) -> bytes:
    extraction_commitment = _validated_extraction_binding_commitment(
        state.inputs.extraction_contract_binding
    )
    payload = (
        f"{id(prepared)}:{id(state.preparation)}:{id(state.inputs)}:"
        f"{id(state.production_authority)}:{id(state.operation_manifest)}:"
        f"{extraction_commitment}:"
        f"{state.inputs.extraction_token_budget.commitment_sha256}:"
        f"{state.operation_manifest.commitment_sha256}"
    ).encode()
    return hmac.new(_SECRET, payload, hashlib.sha256).digest()


def _validated_extraction_binding_commitment(binding: object) -> str:
    try:
        require_managed_mem0_v5_extraction_contract_binding(binding)
        return binding.commitment_sha256
    except Exception:
        raise ManagedV5LiveRootError("managed_v5_live_extraction_binding_invalid") from None


__all__ = (
    "ManagedV5LivePrivateInputs",
    "ManagedV5LivePublicInputs",
    "ManagedV5LiveRootError",
    "PreparedManagedV5LiveRun",
    "SelectedManagedV5LiveExecution",
    "activate_managed_v5_live_run",
    "prepare_managed_v5_live_run",
)
