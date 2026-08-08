"""Two-stage production root for one exact managed-v5 comparison."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_composite_assembler import (
    ManagedFullComparisonAssembler,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
)
from infinity_context_server.memory_comparison_managed_llm_execution import (
    create_managed_comparison_execution_ports,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5StatePaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    ManagedMem0V5ProductionAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedRunOutcome,
    run_managed_comparison_with_bindings,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_credentials import (
    ManagedV5InfinityCredentialBundle,
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    ManagedV5PublicRunPreparation,
    _activate_managed_v5_public_run,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedV5LivePrivateDependencyError,
    ManagedV5LivePrivateDependencyFactory,
    ManagedV5LivePrivateDependencyMaterial,
    ManagedV5RegistryRecoveryEnvelope,
)
from infinity_context_server.memory_comparison_managed_v5_owned_resources import (
    ManagedV5OwnedResourcesError,
)
from infinity_context_server.memory_comparison_managed_v5_runtime_factory import (
    ManagedV5ProductionRuntime,
    ManagedV5ProductionRuntimeFactoryError,
    create_managed_v5_production_runtime,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5TransportPort
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.resumable_operation_journal.domain import OperationRunIdentity

MANAGED_V5_PRODUCTION_RUNNER_ADAPTER_ID = "managed-v5-production-runner-v1"
MANAGED_V5_PRODUCTION_CLOCK_ADAPTER_ID = "managed-v5-production-clock-v1"
MANAGED_V5_PRODUCTION_ASSEMBLER_ADAPTER_ID = "managed-v5-production-assembler-v1"

_CLOCK_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"memory-comparison-managed-v5-production-clock.v1"
).hexdigest()
_ASSEMBLER_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"memory-comparison-managed-v5-production-assembler.v1"
).hexdigest()


class ManagedV5ProductionRunnerError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedV5ProductionRecoveryRequiredError(RuntimeError):
    """Secret-safe ownership transfer for an unproven registry cleanup."""

    __slots__ = ("code", "envelope")

    def __init__(
        self,
        *,
        envelope: ManagedV5RegistryRecoveryEnvelope,
    ) -> None:
        if type(envelope) is not ManagedV5RegistryRecoveryEnvelope:
            raise ManagedV5ProductionRunnerError(
                "managed_v5_production_recovery_state_invalid"
            ) from None
        self.code = "managed_v5_production_cleanup_required"
        self.envelope = envelope
        super().__init__(self.code)

    @property
    def recovery_registry(self) -> ManagedBenchmarkRegistryHttpAdapter:
        return self.envelope.recovery_registry

    @property
    def registration(self) -> ManagedBenchmarkRunRegistration | None:
        return self.envelope.registration

    @property
    def cleanup_receipt(
        self,
    ) -> ManagedBenchmarkCleanupReceipt | ManagedBenchmarkPersistedCleanupReceipt | None:
        return self.envelope.cleanup_receipt

    @property
    def cleanup_stage(self) -> str:
        return self.envelope.stage

    @property
    def primary_code(self) -> str:
        return self.envelope.primary_reason_code

    def __reduce__(self) -> object:
        raise TypeError("managed v5 production recovery error is nonserializable")


@final
class ManagedV5ProductionClockPort:
    __slots__ = ("_clock",)

    def __init__(self, clock: Callable[[], datetime]) -> None:
        if not callable(clock):
            _fail("managed_v5_production_clock_invalid")
        self._clock = clock
        self.now()

    @property
    def adapter_id(self) -> str:
        return MANAGED_V5_PRODUCTION_CLOCK_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _CLOCK_IMPLEMENTATION_SHA256

    def now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            _fail("managed_v5_production_clock_invalid")
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            _fail("managed_v5_production_clock_invalid")
        return value.astimezone(UTC)


def activate_managed_v5_production_runtime(
    preparation: ManagedV5PublicRunPreparation,
    *,
    cases: tuple[ManagedRunCase, ...],
    request: Mem0OssAdmissionRequest,
    composition_binding: ManagedRunnerCompositionBinding,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    production_authority: ManagedMem0V5ProductionAuthority,
    plan: VerifiedManagedRunPlan,
    now: datetime,
    **runtime_dependencies: object,
) -> ManagedV5ProductionRuntime:
    """Burn public preparation only after readiness, then compose exact runtime."""

    try:
        activated = _activate_managed_v5_public_run(
            preparation,
            cases=cases,
            request=request,
            composition_binding=composition_binding,
            receipt_authority=receipt_authority,
            production_authority=production_authority,
            plan=plan,
            now=now,
        )
        return create_managed_v5_production_runtime(
            activated_preparation=activated,
            **runtime_dependencies,
        )
    except (
        ManagedV5ProductionRunnerError,
        ManagedV5ProductionRuntimeFactoryError,
        ManagedRuntimeCredentialError,
    ):
        raise
    except Exception:
        _fail("managed_v5_production_activation_failed")


def activate_managed_v5_production_runtime_with_factory(
    preparation: ManagedV5PublicRunPreparation,
    *,
    cases: tuple[ManagedRunCase, ...],
    request: Mem0OssAdmissionRequest,
    composition_binding: ManagedRunnerCompositionBinding,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    production_authority: ManagedMem0V5ProductionAuthority,
    plan: VerifiedManagedRunPlan,
    run_bindings: FullComparisonRunBindings,
    now: datetime,
    deadline: datetime,
    infinity_credentials: ManagedV5InfinityCredentialBundle,
    dependency_factory: ManagedV5LivePrivateDependencyFactory,
    current_date: str,
    mem0_origin: str,
    timeout_seconds: float,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    mem0_transport: Mem0V5TransportPort | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ManagedV5ProductionRuntime:
    """Activate once, materialize deferred private dependencies, then compose."""

    if (
        type(dependency_factory) is not ManagedV5LivePrivateDependencyFactory
        or type(run_bindings) is not FullComparisonRunBindings
        or type(infinity_credentials) is not ManagedV5InfinityCredentialBundle
    ):
        _fail("managed_v5_production_factory_activation_invalid")
    dependencies: ManagedV5LivePrivateDependencyMaterial | None = None
    try:
        activated = _activate_managed_v5_public_run(
            preparation,
            cases=cases,
            request=request,
            composition_binding=composition_binding,
            receipt_authority=receipt_authority,
            production_authority=production_authority,
            plan=plan,
            now=now,
        )
        dependencies = dependency_factory.create(
            activated_preparation=activated,
            plan=plan,
            run_bindings=run_bindings,
            infinity_credentials=infinity_credentials,
            credential_paths=credential_paths,
            deadline=deadline,
            now=now,
            clock=clock,
        )
        operation_run_identity = OperationRunIdentity(
            run_id=request.run_id,
            operation_namespace="managed_mem0_v5_production",
            manifest_commitment_sha256=activated.operation_manifest.commitment_sha256,
            policy_commitment_sha256=(dependencies.operation_policy_commitment_sha256),
            signer_key_id=dependencies.operation_signer_key_id,
            expected_operation_count=len(activated.operation_manifest.operations),
        )
        return create_managed_v5_production_runtime(
            activated_preparation=activated,
            infinity_credentials=infinity_credentials,
            current_date=current_date,
            mem0_origin=mem0_origin,
            timeout_seconds=timeout_seconds,
            state_paths=state_paths,
            credential_paths=credential_paths,
            runtime_receipt_boundary=runtime_receipt_boundary,
            trusted_runtime_binding=trusted_runtime_binding,
            mem0_transport=mem0_transport,
            clock=clock,
            budget_policy=dependencies.budget_policy,
            clean_state_snapshot_factory=dependencies.clean_state_snapshot_factory,
            durable_clean_state_factory=dependencies.durable_clean_state_factory,
            operation_journal=dependencies.operation_journal,
            operation_run_identity=operation_run_identity,
            operation_receipt_authority=dependencies.operation_receipt_authority,
            mem0_credential_capabilities=dependencies.mem0_credential_capabilities,
            benchmark_registry=dependencies.benchmark_registry,
            benchmark_registration=dependencies.benchmark_registration,
            infinity_derived_transport_factory=dependencies.infinity_derived_transport_factory,
            infinity_cleanup_transport_factory=dependencies.infinity_cleanup_transport_factory,
        )
    except BaseException as primary:
        if dependencies is not None:
            _compensate_unsealed_registration(dependencies, primary=primary)
        elif (
            type(primary) is ManagedV5LivePrivateDependencyError
            and primary.recovery_envelope is not None
        ):
            raise ManagedV5ProductionRecoveryRequiredError(
                envelope=primary.recovery_envelope
            ) from None
        raise


def _compensate_unsealed_registration(
    dependencies: ManagedV5LivePrivateDependencyMaterial,
    *,
    primary: BaseException,
) -> None:
    """Prove abort or transfer the exact live recovery authority to the caller."""

    registry = dependencies.benchmark_registry
    registration = dependencies.benchmark_registration
    with suppress(BaseException):
        dependencies.mem0_credential_capabilities.close()
    receipt = registry.cleanup_receipt
    try:
        if registration.state != "active":
            return
        if receipt is None:
            receipt = registry.begin_cleanup()
    except BaseException:
        current_receipt = receipt
        with suppress(BaseException):
            current_receipt = registry.cleanup_receipt or current_receipt
        raise _recovery_required(
            registry=registry,
            registration=registration,
            cleanup_receipt=current_receipt,
            cleanup_stage="begin_cleanup",
            primary=primary,
        ) from None
    if receipt.projection_cleanup != "blocked":
        raise _recovery_required(
            registry=registry,
            registration=registration,
            cleanup_receipt=receipt,
            cleanup_stage="awaiting_projection_cleanup",
            primary=primary,
        ) from None
    try:
        registry.finalize_unsealed_abort(
            cleanup_initiation_receipt_sha256=receipt.receipt_sha256,
        )
    except BaseException:
        current_receipt = receipt
        with suppress(BaseException):
            current_receipt = registry.cleanup_receipt or current_receipt
        raise _recovery_required(
            registry=registry,
            registration=registration,
            cleanup_receipt=current_receipt,
            cleanup_stage="finalize_unsealed_abort",
            primary=primary,
        ) from None


def _recovery_required(
    *,
    registry: ManagedBenchmarkRegistryHttpAdapter,
    registration: ManagedBenchmarkRunRegistration,
    cleanup_receipt: ManagedBenchmarkCleanupReceipt
    | ManagedBenchmarkPersistedCleanupReceipt
    | None,
    cleanup_stage: str,
    primary: BaseException,
) -> ManagedV5ProductionRecoveryRequiredError:
    envelope = ManagedV5RegistryRecoveryEnvelope(
        stage=cleanup_stage,
        primary_reason_code=_safe_primary_code(primary),
        run_id_sha256=registration.run_id_sha256,
        binding_commitment_sha256=registration.binding_commitment_sha256,
        infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
        space_slug=registration.space_slug,
        recovery_registry=registry,
        registration=registration,
        cleanup_receipt=cleanup_receipt,
    )
    return ManagedV5ProductionRecoveryRequiredError(envelope=envelope)


def _safe_primary_code(primary: BaseException) -> str:
    if type(primary) in {
        ManagedV5ProductionRunnerError,
        ManagedV5ProductionRuntimeFactoryError,
        ManagedRuntimeCredentialError,
        ManagedV5LivePrivateDependencyError,
    }:
        code = primary.code
        if type(code) is str and code.startswith("managed_"):
            return code
    return "managed_v5_production_activation_failed"


def run_verified_managed_v5_production_execution(
    runtime: ManagedV5ProductionRuntime,
    *,
    provider: BoundedProviderChatCompletions,
    limits: ManagedLiveExecutionLimits,
    provider_route: ProviderRouteAttestation,
    attestation_port: object,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ManagedRunOutcome:
    """Execute an activated runtime; lifecycle policy owns cleanup, close does not."""

    if (
        type(runtime) is not ManagedV5ProductionRuntime
        or type(provider) is not BoundedProviderChatCompletions
        or type(limits) is not ManagedLiveExecutionLimits
        or type(provider_route) is not ProviderRouteAttestation
    ):
        _fail("managed_v5_production_execution_invalid")
    clock_port = ManagedV5ProductionClockPort(clock)
    primary: BaseException | None = None
    outcome: ManagedRunOutcome | None = None
    try:
        runtime.owned_resources._register(provider)
        execution = create_managed_comparison_execution_ports(
            composition_binding=runtime.composition_binding,
            retrieval=runtime.retrieval,
            execution_evidence=runtime.execution_evidence,
            retrieval_adapter_id=runtime.retrieval.adapter_id,
            retrieval_implementation_sha256=runtime.retrieval.implementation_sha256,
            provider=provider,
            limits=limits,
            provider_route=provider_route,
        )
        assembler = ManagedFullComparisonAssembler(
            adapter_id=MANAGED_V5_PRODUCTION_ASSEMBLER_ADAPTER_ID,
            implementation_sha256=_ASSEMBLER_IMPLEMENTATION_SHA256,
            reset_port=runtime.lifecycle_ports.reset,
            attestation_port=attestation_port,
            ingest_port=runtime.lifecycle_ports.ingest,
            clock=clock_port,
        )
        outcome = run_managed_comparison_with_bindings(
            runtime._plan,
            bindings=runtime._bindings,
            reset_port=runtime.lifecycle_ports.reset,
            attestation_port=attestation_port,
            ingest_port=runtime.lifecycle_ports.ingest,
            clock=clock_port,
            execution_port=execution.execution_port,
            judge_port=execution.judge_port,
            policy_port=runtime.policy_port,
            assembler=assembler,
        )
        completion = runtime.policy_port.terminal_completion_receipt
        if completion is None or completion.state != "cleanup_complete":
            _fail("managed_v5_production_registry_incomplete")
    except BaseException as error:
        primary = error
    close_failed = False
    try:
        runtime.owned_resources.close()
    except ManagedV5OwnedResourcesError:
        close_failed = True
    if primary is not None:
        if isinstance(primary, ManagedV5ProductionRunnerError):
            raise primary
        if not isinstance(primary, Exception):
            raise primary
        _fail("managed_v5_production_execution_failed")
    if close_failed:
        _fail("managed_v5_production_close_failed")
    if type(outcome) is not ManagedRunOutcome:
        _fail("managed_v5_production_outcome_invalid")
    observed_token_error = runtime.observed_extraction_verifier.verify()
    if observed_token_error is not None:
        _fail(observed_token_error)
    return outcome


def _fail(code: str) -> None:
    raise ManagedV5ProductionRunnerError(code) from None


__all__ = (
    "MANAGED_V5_PRODUCTION_ASSEMBLER_ADAPTER_ID",
    "MANAGED_V5_PRODUCTION_CLOCK_ADAPTER_ID",
    "MANAGED_V5_PRODUCTION_RUNNER_ADAPTER_ID",
    "ManagedV5ProductionClockPort",
    "ManagedV5ProductionRecoveryRequiredError",
    "ManagedV5ProductionRunnerError",
    "activate_managed_v5_production_runtime",
    "activate_managed_v5_production_runtime_with_factory",
    "run_verified_managed_v5_production_execution",
)
