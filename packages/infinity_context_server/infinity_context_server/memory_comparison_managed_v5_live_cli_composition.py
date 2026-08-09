"""Executable managed-v5-only live CLI composition.

The public stage is deliberately complete before ``env`` is inspected.  The
private stage is kept behind a narrow function seam so tests can prove that a
public rejection performs no credential, readiness, registry, TCP or provider
work.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_scope import FULL_COMPARISON_SCOPE_CANARY
from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    expected_managed_mem0_runtime_mode,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
    ManagedMem0V5ExtractionContractBindingError,
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    ManagedMem0V5ExpectedRuntimeAuthority,
    expected_managed_mem0_v5_runtime_authority_from_pin,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_production_composition import (
    MANAGED_PRODUCTION_EXECUTION_V5,
    evaluate_managed_production_pre_readiness,
    run_selected_managed_production_comparison,
)
from infinity_context_server.memory_comparison_managed_run import public_managed_run
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    ManagedV5LiveRuntimeAuthority,
    validate_managed_v5_live_public_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_public_composition import (
    ManagedV5LivePublicComposition,
    compose_managed_v5_live_public_inputs,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_prepare import (
    ManagedV5LiveRecoveryPrepareError,
    initialize_managed_v5_live_recovery_journal,
    prepare_managed_v5_live_cleanup_plan,
)
from infinity_context_server.memory_comparison_managed_v5_live_root import (
    PreparedManagedV5LiveRun,
    prepare_managed_v5_live_run,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    managed_v5_live_config_commitment_sha256,
)

_MAX_DATASET_BYTES = 402_653_184


class ManagedV5LiveCliCompositionError(RuntimeError):
    __slots__ = ("code", "sealed_result")

    def __init__(
        self,
        code: str,
        *,
        sealed_result: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.sealed_result = None if sealed_result is None else dict(sealed_result)
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveCliCompositionRequest:
    dataset_path: Path
    profile_id: str
    selected_case_ids: tuple[str, ...]
    run_id: str
    infinity_api_url: str
    mem0_api_url: str
    subscription_runtime_url: str
    max_extraction_tokens: int
    max_total_tokens: int
    mem0_runtime_implementation_sha256: str
    managed_v5_config: ManagedV5LiveConfig
    extraction_contract_file: Path
    extraction_contract_sha256: str
    mem0_local_auth_disabled_managed: bool
    mem0_oss_ingress_protected: bool
    allowed_mem0_hosts: tuple[str, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    run_timeout_seconds: float

    def __post_init__(self) -> None:
        paths = (self.dataset_path, self.extraction_contract_file)
        text = (
            self.profile_id,
            self.run_id,
            self.infinity_api_url,
            self.mem0_api_url,
            self.subscription_runtime_url,
        )
        if (
            any(not isinstance(value, Path) for value in paths)
            or any(type(value) is not str or not value for value in text)
            or type(self.selected_case_ids) is not tuple
            or not self.selected_case_ids
            or any(type(value) is not str or not value for value in self.selected_case_ids)
            or type(self.managed_v5_config) is not ManagedV5LiveConfig
            or not _is_sha256(self.extraction_contract_sha256)
            or not _is_sha256(self.mem0_runtime_implementation_sha256)
            or type(self.max_extraction_tokens) is not int
            or self.max_extraction_tokens < 1
            or type(self.max_total_tokens) is not int
            or self.max_total_tokens < 1
            or type(self.mem0_local_auth_disabled_managed) is not bool
            or type(self.mem0_oss_ingress_protected) is not bool
            or type(self.allowed_mem0_hosts) is not tuple
            or any(type(value) is not str or not value for value in self.allowed_mem0_hosts)
            or any(
                not _positive_finite(value)
                for value in (
                    self.connect_timeout_seconds,
                    self.request_timeout_seconds,
                    self.run_timeout_seconds,
                )
            )
        ):
            _fail("managed_v5_live_cli_request_invalid")


@final
@dataclass(frozen=True, slots=True)
class PreparedManagedV5LiveCliPublicStage:
    request: ManagedV5LiveCliCompositionRequest = field(repr=False)
    profile: FullComparisonProfile
    dataset_bytes: bytes = field(repr=False)
    projection: ManagedPublicRunProjection
    runtime_authority: ManagedV5LiveRuntimeAuthority
    extraction_contract_binding: ManagedMem0V5ExtractionContractBinding
    public_composition: ManagedV5LivePublicComposition = field(repr=False)
    root_preparation: PreparedManagedV5LiveRun = field(repr=False)
    run_nonce_commitment_sha256: str
    runtime_probe_nonce: str = field(repr=False)
    runtime_attestation_authority: ManagedMem0V5ExpectedRuntimeAuthority = field(repr=False)
    recovery_authority: ManagedV5LiveRecoveryAuthority
    issued_at: datetime
    deadline: datetime

    def __post_init__(self) -> None:
        if (
            type(self.request) is not ManagedV5LiveCliCompositionRequest
            or type(self.profile) is not FullComparisonProfile
            or type(self.dataset_bytes) is not bytes
            or type(self.projection) is not ManagedPublicRunProjection
            or type(self.runtime_authority) is not ManagedV5LiveRuntimeAuthority
            or type(self.extraction_contract_binding) is not ManagedMem0V5ExtractionContractBinding
            or type(self.public_composition) is not ManagedV5LivePublicComposition
            or type(self.root_preparation) is not PreparedManagedV5LiveRun
            or not _is_sha256(self.run_nonce_commitment_sha256)
            or not _is_sha256(self.runtime_probe_nonce)
            or type(self.runtime_attestation_authority) is not ManagedMem0V5ExpectedRuntimeAuthority
            or type(self.recovery_authority) is not ManagedV5LiveRecoveryAuthority
            or self.issued_at.tzinfo is None
            or self.deadline <= self.issued_at
        ):
            _fail("managed_v5_live_cli_public_stage_invalid")


@final
@dataclass(frozen=True, slots=True)
class ActivatedManagedV5LiveCliPrivateStage:
    selected: object = field(repr=False)
    mem0_probe_token: str = field(repr=False)
    mem0_ingress_authority: object | None = field(default=None, repr=False)
    recovery_journal: object = field(default=None, repr=False)
    recovery_authority: ManagedV5LiveRecoveryAuthority | None = field(default=None, repr=False)
    cleanup_plan_sha256: str = field(default="", repr=False)
    recovery_clock: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            self.selected is None
            or type(self.mem0_probe_token) is not str
            or not self.mem0_probe_token
            or not callable(getattr(self.recovery_journal, "append", None))
            or type(self.recovery_authority) is not ManagedV5LiveRecoveryAuthority
            or not _is_sha256(self.cleanup_plan_sha256)
            or not callable(self.recovery_clock)
        ):
            _fail("managed_v5_live_cli_private_stage_invalid")


def prepare_managed_v5_live_cli_public_stage(
    request: ManagedV5LiveCliCompositionRequest,
    *,
    now: datetime | None = None,
) -> PreparedManagedV5LiveCliPublicStage:
    """Finish every gold-free and provider-free gate before secret access."""

    if type(request) is not ManagedV5LiveCliCompositionRequest:
        _fail("managed_v5_live_cli_request_invalid")
    from infinity_context_server.memory_comparison_subscription_chat import (
        _validated_loopback_origin,
    )

    try:
        _validated_loopback_origin(request.subscription_runtime_url)
    except ValueError:
        _fail("subscription_runtime_url_invalid")
    if request.mem0_api_url != request.managed_v5_config.runtime.mem0_adapter_origin:
        _fail("managed_v5_live_mem0_origin_cross_wire")
    try:
        extraction_contract_binding = ManagedMem0V5ExtractionContractBinding(
            request.extraction_contract_file,
            request.extraction_contract_sha256,
        )
        require_managed_mem0_v5_extraction_contract_binding(extraction_contract_binding)
    except ManagedMem0V5ExtractionContractBindingError:
        _fail("managed_v5_live_extraction_contract_invalid")
    issued_at = datetime.now(UTC) if now is None else _aware(now)
    deadline = issued_at + timedelta(seconds=float(request.run_timeout_seconds))
    profile = _profile(request.profile_id)
    dataset_bytes = _dataset_bytes(request.dataset_path)
    runtime_authority = _validated_public_runtime(request.managed_v5_config)
    expected_mode = expected_managed_mem0_runtime_mode(
        data_plane_auth_mode=(
            MANAGED_MEM0_DATA_PLANE_AUTH_NONE
            if request.mem0_local_auth_disabled_managed
            else MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
        ),
        profile_runtime_mode=profile.required_mem0_runtime_mode,
    )
    targets = _public_backend_targets(request)
    run_nonce_commitment = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    runtime_probe_nonce = secrets.token_hex(32)
    projection = build_managed_public_run_projection(
        run_id=request.run_id,
        run_nonce_commitment_sha256=run_nonce_commitment,
        runtime_probe_nonce_sha256=hashlib.sha256(runtime_probe_nonce.encode("ascii")).hexdigest(),
        profile=profile,
        dataset_bytes=dataset_bytes,
        backend_targets=targets,
        scope=FULL_COMPARISON_SCOPE_CANARY,
        mem0_expected_runtime_mode=expected_mode,
        selected_case_ids=request.selected_case_ids,
    )
    decision = evaluate_managed_production_pre_readiness(projection.cases)
    if decision.decision != "go":
        _fail("pre_readiness_no_go")
    composition = compose_managed_v5_live_public_inputs(
        projection=projection,
        profile=profile,
        deadline=deadline,
        current_date=issued_at.date().isoformat(),
        extraction_contract_binding=extraction_contract_binding,
        operator_extraction_token_ceiling=request.max_extraction_tokens,
        operator_total_token_ceiling=request.max_total_tokens,
        runtime_authority=runtime_authority,
        config=request.managed_v5_config,
        timeout_seconds=float(request.request_timeout_seconds),
    )
    root_preparation = prepare_managed_v5_live_run(composition.inputs)
    trusted_binding = composition.inputs.trusted_runtime_binding
    subscription_binding = getattr(trusted_binding, "commitment_sha256", None)
    if not _is_sha256(subscription_binding):
        _fail("managed_v5_live_runtime_authority_cross_wire")
    filesystem = request.managed_v5_config.filesystem
    runtime_attestation_authority = expected_managed_mem0_v5_runtime_authority_from_pin(
        runtime_pin_file=filesystem.adapter_runtime_pin_file,
        runtime_pin_sha256=filesystem.adapter_runtime_pin_sha256,
        runtime_source_sha256=runtime_authority.runtime_source_sha256,
        runtime_route_binding_sha256=runtime_authority.route_binding_sha256,
        subscription_runtime_binding_commitment_sha256=subscription_binding,
        expected_account_binding_hmac_sha256=runtime_authority.account_binding_hmac_sha256,
        expected_base_instructions_sha256=runtime_authority.base_instructions_sha256,
    )
    infinity_target = next(
        target.target_identity_sha256
        for target in projection.bindings.backend_targets
        if target.backend_role == "infinity-context"
    )
    state_paths = composition.inputs.state_paths
    recovery_authority = ManagedV5LiveRecoveryAuthority(
        run_id=request.run_id,
        run_id_sha256=hashlib.sha256(request.run_id.encode("utf-8")).hexdigest(),
        binding_commitment_sha256=projection.bindings.binding_commitment_sha256,
        infinity_target_identity_sha256=infinity_target,
        space_slug=_managed_space_slug(request.run_id),
        profile_id=request.profile_id,
        selected_case_ids=request.selected_case_ids,
        current_date=issued_at.date().isoformat(),
        issued_at=_rfc3339(issued_at),
        deadline=_rfc3339(deadline),
        run_nonce_commitment_sha256=run_nonce_commitment,
        runtime_probe_nonce_sha256=projection.bindings.runtime_probe_nonce_sha256,
        dataset_path=request.dataset_path,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        managed_v5_config_commitment_sha256=managed_v5_live_config_commitment_sha256(
            config=request.managed_v5_config,
            extraction_contract_file=request.extraction_contract_file,
            extraction_contract_sha256=request.extraction_contract_sha256,
        ),
        extraction_contract_file=request.extraction_contract_file,
        extraction_contract_sha256=request.extraction_contract_sha256,
        infinity_origin=request.infinity_api_url,
        mem0_origin=request.mem0_api_url,
        max_extraction_tokens=request.max_extraction_tokens,
        max_total_tokens=request.max_total_tokens,
        mem0_runtime_implementation_sha256=request.mem0_runtime_implementation_sha256,
        mem0_local_auth_disabled_managed=request.mem0_local_auth_disabled_managed,
        mem0_oss_ingress_protected=request.mem0_oss_ingress_protected,
        allowed_mem0_hosts=request.allowed_mem0_hosts,
        connect_timeout_seconds=request.connect_timeout_seconds,
        request_timeout_seconds=request.request_timeout_seconds,
        run_timeout_seconds=request.run_timeout_seconds,
        adapter_runtime_pin_sha256=filesystem.adapter_runtime_pin_sha256,
        state_root=filesystem.state_root,
        checkpoint_file=state_paths.checkpoint,
        checkpoint_head_file=state_paths.local_checkpoint_head,
        dispatch_journal=filesystem.dispatch_journal,
        operation_journal=filesystem.operation_journal,
        durable_clean_state=filesystem.durable_clean_state,
    )
    return PreparedManagedV5LiveCliPublicStage(
        request,
        profile,
        dataset_bytes,
        projection,
        runtime_authority,
        extraction_contract_binding,
        composition,
        root_preparation,
        run_nonce_commitment,
        runtime_probe_nonce,
        runtime_attestation_authority,
        recovery_authority,
        issued_at,
        deadline,
    )


def run_managed_v5_live_cli_composition(
    request: ManagedV5LiveCliCompositionRequest,
    *,
    env: Mapping[str, str],
) -> dict[str, object]:
    """Run the explicit v5 selector; there is no legacy execution argument."""

    public = prepare_managed_v5_live_cli_public_stage(request)
    private = _prepare_and_activate_private_stage(public, env=env)
    try:
        private.recovery_journal.append(
            expected_authority=private.recovery_authority,
            kind="execution_started",
            recorded_at=_rfc3339(private.recovery_clock()),
            details={"cleanup_plan_sha256": private.cleanup_plan_sha256},
        )
        outcome = run_selected_managed_production_comparison(
            execution_mode=MANAGED_PRODUCTION_EXECUTION_V5,
            v5_execution=private.selected.selection,
        )
        result = public_managed_run(outcome)
        return _append_required_usage_attestation(public, private, result)
    finally:
        private.recovery_journal.close()


def _prepare_and_activate_private_stage(
    public: PreparedManagedV5LiveCliPublicStage,
    *,
    env: Mapping[str, str],
) -> ActivatedManagedV5LiveCliPrivateStage:
    if type(public) is not PreparedManagedV5LiveCliPublicStage or not isinstance(env, Mapping):
        _fail("managed_v5_live_cli_private_inputs_invalid")
    recovery_journal, recovery_secret_sha256 = _initialize_recovery_journal(public)
    try:
        return _activate_private_stage_after_recovery_prepare(
            public,
            env=env,
            recovery_journal=recovery_journal,
            recovery_secret_sha256=recovery_secret_sha256,
        )
    except BaseException:
        recovery_journal.close()
        raise


def _activate_private_stage_after_recovery_prepare(
    public: PreparedManagedV5LiveCliPublicStage,
    *,
    env: Mapping[str, str],
    recovery_journal: object,
    recovery_secret_sha256: str,
) -> ActivatedManagedV5LiveCliPrivateStage:
    """Read secrets, prove readiness and activate the exact public capability."""

    from infinity_context_server.memory_comparison_full_methodology import (
        full_comparison_methodology_contract,
    )
    from infinity_context_server.memory_comparison_managed_live_admission import (
        MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        ManagedLiveBudget,
        issue_verified_managed_live_admission,
    )
    from infinity_context_server.memory_comparison_managed_live_composition import (
        prepare_verified_managed_live_run,
    )
    from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
        ManagedUtcClockPort,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
        ManagedMem0V5Budget,
        ManagedMem0V5BudgetPolicy,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation_http import (
        ManagedMem0V5RuntimeAttestationPort,
    )
    from infinity_context_server.memory_comparison_managed_preflight import (
        MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
        ManagedPreflightRequest,
        ManagedPreflightTimeouts,
        managed_dataset_metadata_from_bytes,
    )
    from infinity_context_server.memory_comparison_managed_runtime_credentials import (
        issue_managed_runtime_credential_authority,
    )
    from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
        ManagedV5LivePrivateDependencyFactory,
    )
    from infinity_context_server.memory_comparison_managed_v5_live_root import (
        ManagedV5LivePrivateInputs,
        activate_managed_v5_live_run,
    )
    from infinity_context_server.memory_comparison_subscription_chat import (
        _validated_loopback_origin,
    )

    if type(public) is not PreparedManagedV5LiveCliPublicStage or not isinstance(env, Mapping):
        _fail("managed_v5_live_cli_private_inputs_invalid")
    request = public.request
    try:
        subscription_origin = _validated_loopback_origin(request.subscription_runtime_url)
    except ValueError:
        _fail("subscription_runtime_url_invalid")
    infinity_token = _required_secret(env, "MEMORY_EVAL_AUTH_TOKEN", "MEMORY_SERVICE_TOKEN")
    cleanup_plan, cleanup_target_authority_sha256 = _prepare_cleanup_plan(
        public,
        infinity_token=infinity_token,
        recovery_journal=recovery_journal,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
        _read_private_secret,
        _validate_text_secret,
        _wipe,
    )

    secret = _read_private_secret(
        request.managed_v5_config.filesystem.runtime_attestation_secret_file
    )
    try:
        _validate_text_secret(secret.value)
        if hashlib.sha256(secret.value).hexdigest() != (
            request.managed_v5_config.filesystem.runtime_attestation_secret_sha256
        ):
            _fail("managed_v5_live_runtime_attestation_secret_mismatch")
        probe_token = bytes(secret.value).decode("utf-8")
    finally:
        _wipe(secret.value)
    subscription_token = _required_secret(env, "SUBSCRIPTION_RUNTIME_BRIDGE_BEARER_TOKEN")
    auth_mode = (
        MANAGED_MEM0_DATA_PLANE_AUTH_NONE
        if request.mem0_local_auth_disabled_managed
        else MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
    )
    mem0_api_key = (
        None
        if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE
        else _required_secret(env, "MEM0_API_KEY")
    )
    ingress_authority = _mem0_ingress_authority(request, env)
    clock = ManagedUtcClockPort()
    now = clock.now()
    authority = issue_managed_runtime_credential_authority(
        run_id=request.run_id,
        infinity_origin=request.infinity_api_url,
        infinity_auth_token=infinity_token,
        mem0_origin=request.mem0_api_url,
        mem0_api_key=mem0_api_key,
        mem0_probe_token=probe_token,
        subscription_origin=subscription_origin,
        subscription_bearer_token=subscription_token,
        request_timeout_seconds=float(request.request_timeout_seconds),
        issued_at=public.issued_at,
        deadline=public.deadline,
        mem0_data_plane_auth_mode=auth_mode,
        mem0_oss_ingress_authority=ingress_authority,
    )
    material = authority.preflight_material()
    expected_targets = public.projection.bindings.backend_targets
    if tuple(item.target for item in material.backend_endpoints) != expected_targets:
        _fail("managed_v5_live_private_target_cross_wire")
    preflight_request = ManagedPreflightRequest(
        profile=public.profile,
        methodology=full_comparison_methodology_contract(public.profile),
        dataset=managed_dataset_metadata_from_bytes(
            profile=public.profile,
            dataset_bytes=public.dataset_bytes,
        ),
        provider_route=material.provider_route,
        answerer_model=public.runtime_authority.model,
        judge_model=public.runtime_authority.model,
        openai_credential=material.provider_credential,
        backend_endpoints=material.backend_endpoints,
        timeouts=ManagedPreflightTimeouts(
            connect_seconds=float(request.connect_timeout_seconds),
            request_seconds=float(request.request_timeout_seconds),
            run_seconds=float(request.run_timeout_seconds),
        ),
        scope=FULL_COMPARISON_SCOPE_CANARY,
        provider_kind=MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
        mem0_data_plane_auth_mode=material.mem0_data_plane_auth_mode,
    )
    authority.bind_preflight_request(
        preflight_request,
        run_id=request.run_id,
        deadline=public.deadline,
    )
    readiness_claim = authority.issue_subscription_readiness_claim(
        expected_request=preflight_request,
        run_id=request.run_id,
        subscription_origin=subscription_origin,
        deadline=public.deadline,
        now=now,
    )
    prevalidated_at = clock.now()
    remaining = (public.deadline - prevalidated_at).total_seconds()
    if not math.isfinite(remaining) or remaining <= 0.001:
        _fail("managed_v5_live_deadline_expired")
    runtime_port = ManagedMem0V5RuntimeAttestationPort(
        base_url=request.mem0_api_url,
        runtime_attestation_root_secret=probe_token,
        probe_nonce_sha256=public.projection.bindings.runtime_probe_nonce_sha256,
        expected_authority=public.runtime_attestation_authority,
        timeout_seconds=float(request.request_timeout_seconds),
        deadline_budget_seconds=remaining - 0.001,
        monotonic_clock=time.monotonic,
        expected_implementation_sha256=request.mem0_runtime_implementation_sha256,
        allowed_target_hosts=request.allowed_mem0_hosts,
    )
    target_identity_sha256 = next(
        target.target_identity_sha256
        for target in public.projection.bindings.backend_targets
        if target.backend_role == "mem0"
    )
    provider_probe = _prevalidate_before_paid_readiness(
        prevalidate=lambda: runtime_port.prevalidate(
            run_id=request.run_id,
            probe_nonce_sha256=public.projection.bindings.runtime_probe_nonce_sha256,
            target_identity_sha256=target_identity_sha256,
        ),
        run_readiness=lambda: readiness_claim.run(
            model=public.runtime_authority.model, clock=clock.now
        ),
    )
    admitted_at = clock.now()
    admission = issue_verified_managed_live_admission(
        request=preflight_request,
        allow_live=True,
        allow_paid_llm=True,
        allow_full_run=False,
        run_id=request.run_id,
        run_nonce_commitment_sha256=public.run_nonce_commitment_sha256,
        canary_case_ids=request.selected_case_ids,
        mem0_probe_credential=material.mem0_probe_credential,
        mem0_runtime_port=runtime_port,
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        live_provider_evidence=provider_probe,
        budget=ManagedLiveBudget(
            max_cases=len(request.selected_case_ids),
            max_provider_calls=len(request.selected_case_ids) * 4,
            max_total_tokens=(
                public.public_composition.extraction_token_budget.answer_judge_reserved_token_ceiling
            ),
        ),
        issued_at=admitted_at,
        deadline=public.deadline,
        now=admitted_at,
    )
    verified = prepare_verified_managed_live_run(
        admission,
        expected_request=preflight_request,
        credential_authority=authority,
        readiness_claim=readiness_claim,
        dataset_bytes=public.dataset_bytes,
        now=clock.now(),
    )
    budget = ManagedMem0V5Budget.for_authority(public.public_composition.manifest_authority)
    dependency_factory = ManagedV5LivePrivateDependencyFactory(
        config=request.managed_v5_config,
        budget_policy=ManagedMem0V5BudgetPolicy(
            budget.total_call_count,
            public.public_composition.extraction_token_budget,
        ),
        cleanup_plan=cleanup_plan,
        cleanup_target_authority_sha256=cleanup_target_authority_sha256,
        recovery_authority=public.recovery_authority,
        recovery_journal=recovery_journal,
        recovery_secret_sha256=recovery_secret_sha256,
    )
    selected = activate_managed_v5_live_run(
        public.root_preparation,
        ManagedV5LivePrivateInputs(
            verified_preparation=verified,
            dependency_factory=dependency_factory,
            now=clock.now(),
            wall_clock=clock.now,
            monotonic_clock=time.monotonic,
        ),
    )
    return ActivatedManagedV5LiveCliPrivateStage(
        selected=selected,
        mem0_probe_token=probe_token,
        mem0_ingress_authority=ingress_authority,
        recovery_journal=recovery_journal,
        recovery_authority=public.recovery_authority,
        cleanup_plan_sha256=cleanup_plan.sha256,
        recovery_clock=clock.now,
    )


def _prevalidate_before_paid_readiness(
    *, prevalidate: Callable[[], None], run_readiness: Callable[[], object]
) -> object:
    """Keep the provider-paid readiness call strictly behind v5 attestation."""

    prevalidate()
    return run_readiness()


def _initialize_recovery_journal(
    public: PreparedManagedV5LiveCliPublicStage,
) -> tuple[object, str]:
    try:
        return initialize_managed_v5_live_recovery_journal(
            filesystem=public.request.managed_v5_config.filesystem,
            recovery_authority=public.recovery_authority,
        )
    except ManagedV5LiveRecoveryPrepareError as exc:
        _fail(exc.code)


def _prepare_cleanup_plan(
    public: PreparedManagedV5LiveCliPublicStage,
    *,
    infinity_token: str,
    recovery_journal: object,
) -> tuple[object, str]:
    request = public.request
    try:
        return prepare_managed_v5_live_cleanup_plan(
            infinity_api_url=request.infinity_api_url,
            infinity_token=infinity_token,
            infinity_target_identity_sha256=(
                public.recovery_authority.infinity_target_identity_sha256
            ),
            request_timeout_seconds=float(request.request_timeout_seconds),
            benchmark_deadline=public.deadline,
            projection=public.projection,
            manifest_authority=public.public_composition.manifest_authority,
            admission=public.public_composition.admission,
            profile_id=public.profile.profile_id,
            run_id=request.run_id,
            recovery_journal=recovery_journal,
        )
    except ManagedV5LiveRecoveryPrepareError as exc:
        _fail(exc.code)


def _public_backend_targets(
    request: ManagedV5LiveCliCompositionRequest,
) -> tuple[FullComparisonBackendTarget, ...]:
    return tuple(
        FullComparisonBackendTarget(
            role,
            managed_backend_target_identity_sha256(backend_role=role, base_url=origin),
        )
        for role, origin in (
            ("infinity-context", request.infinity_api_url),
            ("mem0", request.mem0_api_url),
        )
    )


def _managed_space_slug(run_id: str) -> str:
    from infinity_context_server.memory_comparison_managed_http_lifecycle import (
        managed_http_lifecycle_space_slug,
    )

    return managed_http_lifecycle_space_slug(run_id)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _required_secret(
    env: Mapping[str, str],
    name: str,
    fallback: str | None = None,
) -> str:
    value = env.get(name)
    if (not isinstance(value, str) or not value.strip()) and fallback is not None:
        value = env.get(fallback)
    if not isinstance(value, str) or not value.strip():
        _fail("credential_missing")
    return value.strip()


def _mem0_ingress_authority(
    request: ManagedV5LiveCliCompositionRequest,
    env: Mapping[str, str],
) -> object | None:
    from infinity_context_server.memory_comparison_mem0_oss_ingress import (
        MEM0_OSS_INGRESS_API_KEY_ENV,
        Mem0OssIngressCredentialError,
        issue_mem0_oss_ingress_credential_authority,
    )

    value = env.get(MEM0_OSS_INGRESS_API_KEY_ENV)
    configured = isinstance(value, str) and bool(value.strip())
    if not request.mem0_local_auth_disabled_managed:
        if request.mem0_oss_ingress_protected or configured:
            _fail("mem0_oss_ingress_configuration_invalid")
        return None
    if not request.mem0_oss_ingress_protected:
        if configured:
            _fail("mem0_oss_ingress_configuration_invalid")
        return None
    if not configured:
        _fail("credential_missing")
    try:
        return issue_mem0_oss_ingress_credential_authority(
            run_id=request.run_id,
            base_url=request.mem0_api_url,
            ingress_api_key=value.strip(),
            allowed_target_hosts=request.allowed_mem0_hosts,
        )
    except Mem0OssIngressCredentialError:
        _fail("mem0_oss_ingress_configuration_invalid")


def _append_required_usage_attestation(
    public: PreparedManagedV5LiveCliPublicStage,
    private: ActivatedManagedV5LiveCliPrivateStage,
    sealed_result: dict[str, object],
) -> dict[str, object]:
    """Prove OSS/no-paid-key usage after sealing; never rerun on failure."""

    from infinity_context_server.memory_comparison_managed_mem0_oss_usage_http import (
        ManagedMem0OssUsageAttestationPort,
    )
    from infinity_context_server.memory_comparison_mem0_oss_ingress import (
        inspect_mem0_oss_ingress_authority,
    )

    try:
        required = private.selected.selection.attestation_port.usage_attestation_required()
        if type(required) is not bool:
            raise TypeError
        if not required:
            return sealed_result
        if private.mem0_ingress_authority is None:
            raise TypeError
        descriptor = inspect_mem0_oss_ingress_authority(private.mem0_ingress_authority)
        port = ManagedMem0OssUsageAttestationPort(
            base_url=public.request.mem0_api_url,
            benchmark_probe_token=private.mem0_probe_token,
            probe_nonce=secrets.token_hex(32),
            ingress_authority=private.mem0_ingress_authority,
            timeout_seconds=float(public.request.request_timeout_seconds),
            deadline=public.deadline,
            clock=lambda: datetime.now(UTC),
            allowed_target_hosts=public.request.allowed_mem0_hosts,
        )
        usage = port.attest(
            run_id=public.request.run_id,
            target_identity_sha256=descriptor.target_identity_sha256,
        )
        result = dict(sealed_result)
        result["mem0_oss_usage_attestation"] = usage.public_payload()
        return result
    except Exception:
        raise ManagedV5LiveCliCompositionError(
            "mem0_oss_usage_attestation_failed",
            sealed_result=sealed_result,
        ) from None


def _validated_public_runtime(config: ManagedV5LiveConfig) -> ManagedV5LiveRuntimeAuthority:
    try:
        return validate_managed_v5_live_public_config(config)
    except Exception:
        _fail("managed_v5_live_public_config_invalid")


def _profile(profile_id: str) -> FullComparisonProfile:
    try:
        profile = resolve_full_comparison_profile(profile_id)
        if profile is None:
            raise TypeError
        return frozen_full_comparison_profile(profile)
    except Exception:
        _fail("profile_invalid")


def _dataset_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_DATASET_BYTES + 1)
    except OSError:
        _fail("dataset_unreadable")
    if not payload or len(payload) > _MAX_DATASET_BYTES:
        _fail("dataset_unreadable")
    return payload


def _aware(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail("managed_v5_live_clock_invalid")
    return value


def _positive_finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(code: str) -> None:
    raise ManagedV5LiveCliCompositionError(code) from None


__all__ = (
    "ManagedV5LiveCliCompositionRequest",
    "ManagedV5LiveCliCompositionError",
    "PreparedManagedV5LiveCliPublicStage",
    "prepare_managed_v5_live_cli_public_stage",
    "run_managed_v5_live_cli_composition",
)
