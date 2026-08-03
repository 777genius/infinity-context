"""Production composition root for one verified managed comparison.

This module owns dependency composition and resource lifetime. Benchmark
orchestration and provider/backend behavior stay in their existing modules.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpConfig,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_composite_assembler import (
    ManagedFullComparisonAssembler,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    ManagedComparisonHttpPolicyLifecycleAdapter,
    managed_http_policy_production_blockers,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
    _consume_verified_managed_live_run_preparation,
    _inspect_managed_live_policy_cases,
)
from infinity_context_server.memory_comparison_managed_llm_execution import (
    create_managed_comparison_execution_ports,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    _inspect_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_production_ports import (
    create_managed_production_lifecycle_ports,
)
from infinity_context_server.memory_comparison_managed_registry_policy_lifecycle import (
    ManagedComparisonRegistryPolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedRunOutcome,
    create_managed_comparison_run_bindings,
    run_managed_comparison_with_bindings,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)

MANAGED_PRODUCTION_RUNNER_ADAPTER_ID = "managed-production-runner-v1"
MANAGED_PRODUCTION_CLOCK_ADAPTER_ID = "managed-production-clock-v1"
MANAGED_PRODUCTION_ASSEMBLER_ADAPTER_ID = "managed-production-assembler-v1"
MANAGED_PRODUCTION_MAX_OUTPUT_TOKENS_PER_CALL = 4096

_CLOCK_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"memory-comparison-managed-production-clock.v1"
).hexdigest()
_ASSEMBLER_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"memory-comparison-managed-production-assembler.v1"
).hexdigest()


class ManagedProductionRunnerError(RuntimeError):
    """Fixed-code production composition failure without private material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class _ManagedProductionClockPort:
    __slots__ = ("_clock",)

    def __init__(self, clock: Callable[[], datetime]) -> None:
        if not callable(clock):
            raise ManagedProductionRunnerError("managed_production_clock_invalid")
        self._clock = clock
        self.now()

    @property
    def adapter_id(self) -> str:
        return MANAGED_PRODUCTION_CLOCK_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _CLOCK_IMPLEMENTATION_SHA256

    def now(self) -> datetime:
        try:
            return _aware(self._clock())
        except ManagedProductionRunnerError:
            raise
        except Exception:
            raise ManagedProductionRunnerError("managed_production_clock_invalid") from None

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("_ManagedProductionClockPort is final")


def run_verified_managed_production_execution(
    prepared: VerifiedManagedLiveRunPreparation,
) -> ManagedRunOutcome:
    """Consume one verified preparation using production-owned clocks."""

    return _run_verified_managed_production_execution(
        prepared,
        now=_production_wall_clock(),
        wall_clock=_production_wall_clock,
        monotonic_clock=time.monotonic,
    )


def _run_verified_managed_production_execution(
    prepared: VerifiedManagedLiveRunPreparation,
    *,
    now: datetime,
    wall_clock: Callable[[], datetime],
    monotonic_clock: Callable[[], float],
) -> ManagedRunOutcome:
    """Private deterministic seam for unit tests of production composition."""

    if type(prepared) is not VerifiedManagedLiveRunPreparation:
        raise ManagedProductionRunnerError("managed_production_preparation_invalid")
    trusted_now = _aware(now)

    provider: BoundedProviderChatCompletions | None = None
    subscription = None
    http: ManagedComparisonHttpExecutionAdapter | None = None
    registry: ManagedBenchmarkRegistryHttpAdapter | None = None
    run_id_sha256: str | None = None
    binding_commitment_sha256: str | None = None
    space_slug: str | None = None
    registration = None
    outcome: ManagedRunOutcome | None = None
    primary: BaseException | None = None

    try:
        cases = _inspect_managed_live_policy_cases(prepared)
        if managed_http_policy_production_blockers(cases):
            raise ManagedProductionRunnerError("managed_production_runner_blocked")

        material = _consume_verified_managed_live_run_preparation(prepared, now=trusted_now)
        plan = _inspect_verified_managed_run_plan(material.plan)
        if plan.cases != cases or any(
            actual is not expected for actual, expected in zip(plan.cases, cases, strict=True)
        ):
            raise ManagedProductionRunnerError("managed_production_plan_changed")
        bindings = create_managed_comparison_run_bindings(material.plan)
        clock_port = _ManagedProductionClockPort(wall_clock)
        infinity_origin, mem0_origin = _backend_origins(material.preflight_request)
        deadline_monotonic = _monotonic_deadline(
            material.limits.deadline,
            wall_clock=clock_port.now,
            monotonic_clock=monotonic_clock,
        )

        subscription = material.credential_authority.issue_subscription_execution_adapter(
            readiness_claim=material.readiness_claim,
            expected_request=material.preflight_request,
            run_id=plan.run_id,
            subscription_origin=material.preflight_request.provider_route.origin,
            deadline=material.limits.deadline,
            now=trusted_now,
        )
        provider = BoundedProviderChatCompletions(
            delegate=subscription,
            budget=BoundedProviderBudget(
                max_total_tokens=material.limits.benchmark_reserved_token_ceiling,
                deadline_monotonic=deadline_monotonic,
                max_calls=material.limits.benchmark_max_provider_calls,
                max_output_tokens_per_call=MANAGED_PRODUCTION_MAX_OUTPUT_TOKENS_PER_CALL,
            ),
            monotonic_clock=monotonic_clock,
        )
        backend_credentials = material.credential_authority.issue_backend_credential_material(
            expected_request=material.preflight_request,
            run_id=plan.run_id,
            infinity_origin=infinity_origin,
            mem0_origin=mem0_origin,
            deadline=material.limits.deadline,
            now=trusted_now,
            mem0_send_timestamps=plan.profile.benchmark == "locomo",
        )
        registry_credential = backend_credentials.consume_for_benchmark_registry(
            expected_request=material.preflight_request,
            run_id=plan.run_id,
            deadline=material.limits.deadline,
        )
        registry = ManagedBenchmarkRegistryHttpAdapter(
            ManagedBenchmarkRegistryHttpConfig(
                base_url=registry_credential.base_url,
                admin_bearer_token=registry_credential.auth_token,
                target_identity_sha256=registry_credential.target_identity_sha256,
                timeout_seconds=registry_credential.timeout_seconds,
                benchmark_deadline=material.limits.deadline,
                cleanup_recovery_timeout_seconds=registry_credential.timeout_seconds,
                transport=registry_credential.transport,
                clock=clock_port.now,
            )
        )
        run_id_sha256 = hashlib.sha256(plan.run_id.encode()).hexdigest()
        binding_commitment_sha256 = bindings.binding_commitment_sha256
        space_slug = managed_http_lifecycle_space_slug(plan.run_id)
        registration = registry.register(
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
        )
        if registration.created is not True:
            raise ManagedProductionRunnerError("managed_production_registry_replay")
        http = ManagedComparisonHttpExecutionAdapter(
            preflight_request=material.preflight_request,
            run_id=plan.run_id,
            deadline=material.limits.deadline,
            credential_material=backend_credentials,
            retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
            clock=clock_port.now,
        )
        lifecycle = ManagedComparisonHttpLifecycleAdapter(
            run_id=plan.run_id,
            binding_commitment_sha256=bindings.binding_commitment_sha256,
            admitted_targets=plan.backend_targets,
            cases=plan.cases,
            deadline=material.limits.deadline,
            execution=http,
            preflight_request=material.preflight_request,
            credential_material=backend_credentials,
            benchmark_registration=registration,
            clock=clock_port.now,
        )
        runtime_ports = create_managed_production_lifecycle_ports(lifecycle)
        policy = ManagedComparisonHttpPolicyLifecycleAdapter(
            bindings=bindings,
            cases=plan.cases,
            preflight_request=material.preflight_request,
            credential_material=backend_credentials,
            deadline=material.limits.deadline,
            clock=clock_port.now,
        )
        registry_policy = ManagedComparisonRegistryPolicyLifecycleAdapter(
            delegate=policy,
            registry=registry,
            bindings=bindings,
            cases=plan.cases,
            registration=registration,
        )
        execution_ports = create_managed_comparison_execution_ports(
            http=http,
            provider=provider,
            limits=material.limits,
            provider_route=plan.provider_route,
            lifecycle=lifecycle,
        )
        assembler = ManagedFullComparisonAssembler(
            adapter_id=MANAGED_PRODUCTION_ASSEMBLER_ADAPTER_ID,
            implementation_sha256=_ASSEMBLER_IMPLEMENTATION_SHA256,
            reset_port=runtime_ports.reset,
            attestation_port=material.mem0_runtime_port,
            ingest_port=runtime_ports.ingest,
            clock=clock_port,
        )
        outcome = run_managed_comparison_with_bindings(
            material.plan,
            bindings=bindings,
            reset_port=runtime_ports.reset,
            attestation_port=material.mem0_runtime_port,
            ingest_port=runtime_ports.ingest,
            clock=clock_port,
            execution_port=execution_ports.execution_port,
            judge_port=execution_ports.judge_port,
            policy_port=registry_policy,
            assembler=assembler,
        )
        completion = registry_policy.terminal_completion_receipt
        if completion is None or completion.state != "cleanup_complete":
            raise ManagedProductionRunnerError("managed_production_registry_incomplete")
    except BaseException as exc:
        primary = exc

    if (
        primary is not None
        and registry is not None
        and run_id_sha256 is not None
        and binding_commitment_sha256 is not None
        and space_slug is not None
        and (registration is None or registration.created is True)
    ):
        _compensate_unsealed_registration(
            registry,
            registration=registration,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
        )
    cleanup_failed = _close_owned(
        provider=provider,
        subscription=subscription,
        http=http,
        registry=registry,
    )
    if primary is not None:
        if isinstance(primary, ManagedProductionRunnerError):
            raise primary
        if not isinstance(primary, Exception):
            raise primary
        raise ManagedProductionRunnerError("managed_production_runner_failed") from None
    if cleanup_failed:
        raise ManagedProductionRunnerError("managed_production_runner_cleanup_failed")
    if type(outcome) is not ManagedRunOutcome:
        raise ManagedProductionRunnerError("managed_production_outcome_invalid")
    return outcome


def _production_wall_clock() -> datetime:
    return datetime.now(UTC)


def _backend_origins(request: object) -> tuple[str, str]:
    try:
        endpoints = {item.target.backend_role: item.base_url for item in request.backend_endpoints}
    except Exception:
        raise ManagedProductionRunnerError("managed_production_endpoints_invalid") from None
    if set(endpoints) != {"infinity-context", "mem0"}:
        raise ManagedProductionRunnerError("managed_production_endpoints_invalid")
    return endpoints["infinity-context"], endpoints["mem0"]


def _monotonic_deadline(
    deadline: datetime,
    *,
    wall_clock: Callable[[], datetime],
    monotonic_clock: Callable[[], float],
) -> float:
    remaining = (_aware(deadline) - _aware(wall_clock())).total_seconds()
    try:
        monotonic = monotonic_clock()
    except Exception:
        raise ManagedProductionRunnerError("managed_production_clock_invalid") from None
    if (
        remaining <= 0
        or isinstance(monotonic, bool)
        or not isinstance(monotonic, int | float)
        or not math.isfinite(monotonic)
        or monotonic <= 0
    ):
        raise ManagedProductionRunnerError("managed_production_deadline_expired")
    return float(monotonic) + remaining


def _close_owned(
    *,
    provider: object | None,
    subscription: object | None,
    http: object | None,
    registry: object | None,
) -> bool:
    failed = False
    if provider is not None:
        try:
            provider.close()
        except Exception:
            failed = True
    elif subscription is not None:
        try:
            subscription.close()
        except Exception:
            failed = True
    if http is not None:
        try:
            http.close()
        except Exception:
            failed = True
    if registry is not None:
        try:
            registry.close()
            if getattr(registry, "close_warning_code", None) is not None:
                failed = True
        except Exception:
            failed = True
    return failed


def _compensate_unsealed_registration(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    *,
    registration: object | None,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    space_slug: str,
) -> None:
    """Best-effort bounded compensation; server state remains recoverable on failure."""

    try:
        if registration is None:
            registration = registry.register(
                run_id_sha256=run_id_sha256,
                binding_commitment_sha256=binding_commitment_sha256,
                space_slug=space_slug,
            )
        if getattr(registration, "created", None) not in {True, False}:
            return
        receipt = registry.cleanup_receipt
        if receipt is None:
            receipt = registry.begin_cleanup()
        if receipt.projection_cleanup == "blocked":
            registry.finalize_unsealed_abort(
                cleanup_initiation_receipt_sha256=receipt.receipt_sha256,
            )
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            return
        if isinstance(error, SystemExit):
            return
        return


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedProductionRunnerError("managed_production_clock_invalid")
    return value.astimezone(UTC)


__all__ = (
    "MANAGED_PRODUCTION_ASSEMBLER_ADAPTER_ID",
    "MANAGED_PRODUCTION_CLOCK_ADAPTER_ID",
    "MANAGED_PRODUCTION_MAX_OUTPUT_TOKENS_PER_CALL",
    "MANAGED_PRODUCTION_RUNNER_ADAPTER_ID",
    "ManagedProductionRunnerError",
    "run_verified_managed_production_execution",
)
