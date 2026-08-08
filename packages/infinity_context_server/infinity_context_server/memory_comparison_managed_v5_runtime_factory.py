"""Exact production composition for the managed-v5 comparison runtime."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_infinity_clean_state_source import (
    create_managed_infinity_clean_state_evidence_channel,
)
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpExecutionAdapter,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpLifecycleAdapter,
    managed_infinity_http_lifecycle_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5CleanStateSnapshotFactoryPort,
    ManagedMem0V5DurableCleanStateFactoryPort,
    ManagedMem0V5StatePaths,
    compose_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_execution_evidence_adapter import (
    ManagedMem0V5ExecutionEvidenceAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_execution_evidence import (  # noqa: E501
    ManagedMem0V5ProductionExecutionEvidenceFacade,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_ports import (
    ManagedV5CutoverLifecyclePorts,
    create_managed_v5_cutover_lifecycle_ports,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runner_adapter import (
    ManagedMem0V5RetrievalAdapter,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    _inspect_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_registry_policy_lifecycle import (
    ManagedComparisonRegistryPolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run import (
    create_managed_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_target_aware_retrieval_router import (
    ManagedTargetAwareRetrievalRouter,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_credentials import (
    ManagedV5InfinityCredentialBundle,
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    _ActivatedManagedV5PublicRun,
)
from infinity_context_server.memory_comparison_managed_v5_owned_resources import (
    ManagedV5OwnedResources,
)
from infinity_context_server.memory_comparison_managed_v5_policy_lifecycle import (
    ManagedInfinityV5PolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_v5_retrieval_factory import (
    create_managed_v5_target_aware_retrieval,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5TransportPort
from infinity_context_server.resumable_operation_journal.domain import OperationRunIdentity
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)

_RUNTIME_TOKEN = object()


class ManagedV5ProductionRuntimeFactoryError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedV5ProductionRuntime:
    """Narrow runtime product; raw credentials and authorities never escape."""

    __slots__ = (
        "__bindings",
        "__composition_binding",
        "__execution_evidence",
        "__lifecycle_ports",
        "__owned_resources",
        "__plan",
        "__policy_delegate",
        "__policy_port",
        "__retrieval",
    )

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        lifecycle_ports: ManagedV5CutoverLifecyclePorts,
        retrieval: ManagedTargetAwareRetrievalRouter,
        execution_evidence: ManagedMem0V5ProductionExecutionEvidenceFacade,
        policy_delegate: ManagedInfinityV5PolicyLifecycleAdapter,
        policy_port: ManagedComparisonRegistryPolicyLifecycleAdapter,
        owned_resources: ManagedV5OwnedResources,
        plan: VerifiedManagedRunPlan,
        bindings: FullComparisonRunBindings,
        _token: object,
    ) -> None:
        if _token is not _RUNTIME_TOKEN:
            _fail("managed_v5_runtime_forged")
        self.__composition_binding = composition_binding
        self.__lifecycle_ports = lifecycle_ports
        self.__retrieval = retrieval
        self.__execution_evidence = execution_evidence
        self.__policy_delegate = policy_delegate
        self.__policy_port = policy_port
        self.__owned_resources = owned_resources
        self.__plan = plan
        self.__bindings = bindings

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return self.__composition_binding

    @property
    def lifecycle_ports(self) -> ManagedV5CutoverLifecyclePorts:
        return self.__lifecycle_ports

    @property
    def retrieval(self) -> ManagedTargetAwareRetrievalRouter:
        return self.__retrieval

    @property
    def execution_evidence(self) -> ManagedMem0V5ProductionExecutionEvidenceFacade:
        return self.__execution_evidence

    @property
    def policy_delegate(self) -> ManagedInfinityV5PolicyLifecycleAdapter:
        return self.__policy_delegate

    @property
    def policy_port(self) -> ManagedComparisonRegistryPolicyLifecycleAdapter:
        return self.__policy_port

    @property
    def owned_resources(self) -> ManagedV5OwnedResources:
        return self.__owned_resources

    @property
    def _plan(self) -> VerifiedManagedRunPlan:
        return self.__plan

    @property
    def _bindings(self) -> FullComparisonRunBindings:
        return self.__bindings

    def __repr__(self) -> str:
        return "ManagedV5ProductionRuntime(<activated>)"

    def __reduce__(self) -> object:
        raise TypeError("managed v5 production runtime is nonserializable")


def create_managed_v5_production_runtime(
    *,
    activated_preparation: object,
    infinity_credentials: ManagedV5InfinityCredentialBundle,
    current_date: str,
    mem0_origin: str,
    timeout_seconds: float,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    budget_policy: ManagedMem0V5BudgetPolicy,
    clean_state_snapshot_factory: ManagedMem0V5CleanStateSnapshotFactoryPort,
    durable_clean_state_factory: ManagedMem0V5DurableCleanStateFactoryPort,
    operation_journal: ResumableOperationJournalService,
    operation_run_identity: OperationRunIdentity,
    benchmark_registry: ManagedBenchmarkRegistryHttpAdapter,
    benchmark_registration: ManagedBenchmarkRunRegistration,
    mem0_transport: Mem0V5TransportPort | None = None,
    infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ManagedV5ProductionRuntime:
    """Compose the exact two-target runtime without legacy adapters or fallback."""

    if (
        type(activated_preparation) is not _ActivatedManagedV5PublicRun
        or type(infinity_credentials) is not ManagedV5InfinityCredentialBundle
        or type(operation_journal) is not ResumableOperationJournalService
        or type(operation_run_identity) is not OperationRunIdentity
        or type(benchmark_registry) is not ManagedBenchmarkRegistryHttpAdapter
        or type(benchmark_registration) is not ManagedBenchmarkRunRegistration
        or not callable(clock)
    ):
        _fail("managed_v5_runtime_composition_invalid")
    material = activated_preparation
    plan = _inspect_verified_managed_run_plan(material.plan)
    if (
        plan.cases != material.cases
        or material.composition_binding.run_id != plan.run_id
        or operation_run_identity.run_id != plan.run_id
        or operation_run_identity.manifest_commitment_sha256
        != material.operation_manifest.commitment_sha256
    ):
        _fail("managed_v5_runtime_activation_invalid")

    owned = ManagedV5OwnedResources((benchmark_registry,))
    infinity_execution: ManagedInfinityHttpExecutionAdapter | None = None
    try:
        credential_now = clock()
        infinity_credentials._bind_activated_preparation(material, now=credential_now)
        composition = compose_managed_mem0_v5(
            cases=material.cases,
            current_date=current_date,
            request=material.request,
            origin=mem0_origin,
            timeout_seconds=timeout_seconds,
            state_paths=state_paths,
            credential_paths=credential_paths,
            runtime_receipt_boundary=runtime_receipt_boundary,
            trusted_runtime_binding=trusted_runtime_binding,
            receipt_authority=material.receipt_authority,
            transport=mem0_transport,
        )
        paired = composition.issue_paired_runtime(
            budget_policy=budget_policy,
            clean_state_snapshot_factory=clean_state_snapshot_factory,
            durable_clean_state_factory=durable_clean_state_factory,
        )
        mem0_lifecycle = ManagedMem0V5LifecycleAdapter(
            composition_binding=material.composition_binding,
            paired_run=paired.paired_run,
            authority=composition.authority,
            request=composition.request,
            cleanup_readback_capability=paired.cleanup_readback_capability,
        )
        corpus_ids = _unique_corpus_ids(material.cases)
        publisher, source = create_managed_infinity_clean_state_evidence_channel(
            composition_binding=material.composition_binding,
            corpus_ids=corpus_ids,
            producer_implementation_sha256=(
                managed_infinity_http_lifecycle_implementation_sha256()
            ),
        )
        evidence = ManagedMem0V5ExecutionEvidenceAdapter(
            composition_binding=material.composition_binding,
            lifecycle=mem0_lifecycle,
            infinity_clean_state_source=source,
        )
        production_lifecycle = ManagedMem0V5ProductionLifecycleAdapter(
            production_authority=material.production_authority,
            composition=composition,
            paired_runtime_bundle=paired,
            composition_binding=material.composition_binding,
            lifecycle=mem0_lifecycle,
            execution_evidence=evidence,
            operation_journal=operation_journal,
            operation_run_identity=operation_run_identity,
            origin=mem0_origin,
            receipt_authority=material.receipt_authority,
            operation_manifest=material.operation_manifest,
        )
        execution_config = infinity_credentials.issue_execution_config(now=credential_now)
        lifecycle_config = infinity_credentials.issue_lifecycle_config(now=credential_now)
        policy_config = infinity_credentials.issue_registry_policy_config(now=credential_now)
        infinity_execution = ManagedInfinityHttpExecutionAdapter(
            composition_binding=material.composition_binding,
            config=execution_config,
            clock=clock,
        )
        owned._register(infinity_execution)
        infinity_lifecycle = ManagedInfinityHttpLifecycleAdapter(
            composition_binding=material.composition_binding,
            cases=material.cases,
            execution=infinity_execution,
            config=lifecycle_config,
            clean_state_publisher=publisher,
            benchmark_registration=benchmark_registration,
            clock=clock,
        )
        lifecycle_ports = create_managed_v5_cutover_lifecycle_ports(
            composition_binding=material.composition_binding,
            cases=material.cases,
            infinity_lifecycle=infinity_lifecycle,
            mem0_lifecycle=production_lifecycle,
            paired_runtime_bundle=paired,
        )
        mem0_retrieval = ManagedMem0V5RetrievalAdapter(
            composition_binding=material.composition_binding,
            paired_run=paired.paired_run,
            authority=composition.authority,
            request=composition.request,
        )
        retrieval = create_managed_v5_target_aware_retrieval(
            composition_binding=material.composition_binding,
            infinity=infinity_execution,
            mem0=mem0_retrieval,
        )
        execution_evidence = ManagedMem0V5ProductionExecutionEvidenceFacade(
            composition_binding=material.composition_binding,
            lifecycle=production_lifecycle,
        )
        bindings = create_managed_comparison_run_bindings(material.plan)
        policy_delegate = ManagedInfinityV5PolicyLifecycleAdapter(
            bindings=bindings,
            cases=material.cases,
            composition_binding=material.composition_binding,
            infinity_lifecycle=infinity_lifecycle,
            mem0_lifecycle=production_lifecycle,
            ingest_port=lifecycle_ports.ingest,
            infinity_config=policy_config,
            deadline=material.composition_binding.deadline,
            infinity_derived_transport_factory=_tracked_factory(
                owned, infinity_derived_transport_factory
            ),
            infinity_cleanup_transport_factory=_tracked_factory(
                owned, infinity_cleanup_transport_factory
            ),
            clock=clock,
        )
        capability = policy_delegate.issue_registry_delegate_capability()
        policy_port = ManagedComparisonRegistryPolicyLifecycleAdapter(
            delegate_capability=capability,
            registry=benchmark_registry,
            bindings=bindings,
            cases=material.cases,
            registration=benchmark_registration,
        )
        return ManagedV5ProductionRuntime(
            composition_binding=material.composition_binding,
            lifecycle_ports=lifecycle_ports,
            retrieval=retrieval,
            execution_evidence=execution_evidence,
            policy_delegate=policy_delegate,
            policy_port=policy_port,
            owned_resources=owned,
            plan=material.plan,
            bindings=bindings,
            _token=_RUNTIME_TOKEN,
        )
    except BaseException as error:
        with suppress(Exception):
            owned.close()
        if not isinstance(error, Exception):
            raise
        if isinstance(
            error,
            (ManagedV5ProductionRuntimeFactoryError, ManagedRuntimeCredentialError),
        ):
            raise
        _fail("managed_v5_runtime_composition_failed")


def _tracked_factory(
    owner: ManagedV5OwnedResources,
    factory: Callable[[], httpx.BaseTransport] | None,
) -> Callable[[], httpx.BaseTransport]:
    def create() -> httpx.BaseTransport:
        transport = (
            httpx.HTTPTransport(retries=0, trust_env=False) if factory is None else factory()
        )
        if not isinstance(transport, httpx.BaseTransport):
            _fail("managed_v5_runtime_transport_invalid")
        owner._register(transport)
        return transport

    return create


def _unique_corpus_ids(cases: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.corpus_id for item in cases))


def _fail(code: str) -> None:
    raise ManagedV5ProductionRuntimeFactoryError(code) from None


__all__ = (
    "ManagedV5ProductionRuntime",
    "ManagedV5ProductionRuntimeFactoryError",
    "create_managed_v5_production_runtime",
)
