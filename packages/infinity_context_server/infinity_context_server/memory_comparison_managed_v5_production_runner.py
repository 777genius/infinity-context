"""Two-stage production root for one exact managed-v5 comparison."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
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
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    ManagedV5PublicRunPreparation,
    _activate_managed_v5_public_run,
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
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

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
    return outcome


def _fail(code: str) -> None:
    raise ManagedV5ProductionRunnerError(code) from None


__all__ = (
    "MANAGED_V5_PRODUCTION_ASSEMBLER_ADAPTER_ID",
    "MANAGED_V5_PRODUCTION_CLOCK_ADAPTER_ID",
    "MANAGED_V5_PRODUCTION_RUNNER_ADAPTER_ID",
    "ManagedV5ProductionClockPort",
    "ManagedV5ProductionRunnerError",
    "activate_managed_v5_production_runtime",
    "run_verified_managed_v5_production_execution",
)
