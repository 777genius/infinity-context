"""Focused composition for managed benchmark registry lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application import (
    CleanupBenchmarkRunUseCase,
    FinalizeBenchmarkRunCleanupUseCase,
    FinalizeUnsealedBenchmarkAbortUseCase,
    GetBenchmarkRunLifecycleUseCase,
    RegisterBenchmarkRunUseCase,
    SealProjectionManifestUseCase,
)
from infinity_context_core.domain.errors import MemoryInfrastructureError
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort
from sqlalchemy.ext.asyncio import AsyncEngine

from infinity_context_server.benchmark_projection_absence import (
    ServerBenchmarkProjectionAbsence,
)
from infinity_context_server.benchmark_unsealed_projection_absence import (
    ServerBenchmarkUnsealedProjectionAbsence,
)
from infinity_context_server.benchmark_unsealed_recovery_inventory import (
    ServerBenchmarkUnsealedRecoveryInventory,
)
from infinity_context_server.derived_identity_evidence import DerivedIdentityEvidenceCoordinator
from infinity_context_server.derived_provider_composition import DerivedProviderBundle


@dataclass(frozen=True, slots=True)
class BenchmarkRunUseCases:
    register: RegisterBenchmarkRunUseCase
    seal_manifest: SealProjectionManifestUseCase
    begin_cleanup: CleanupBenchmarkRunUseCase
    get_lifecycle: GetBenchmarkRunLifecycleUseCase
    finalize_sealed: FinalizeBenchmarkRunCleanupUseCase
    finalize_unsealed: FinalizeUnsealedBenchmarkAbortUseCase


class UnavailableBenchmarkRecoveryEvidence:
    async def delete_benchmark_space_two_pass(self, **_: object) -> object:
        raise MemoryInfrastructureError("Benchmark recovery evidence is unavailable")


def build_benchmark_run_use_cases(
    *,
    engine: AsyncEngine,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    sealed_evidence: DerivedIdentityEvidenceCoordinator,
    derived_providers: DerivedProviderBundle,
) -> BenchmarkRunUseCases:
    sealed_absence = ServerBenchmarkProjectionAbsence(sealed_evidence)
    unavailable = UnavailableBenchmarkRecoveryEvidence()
    unsealed_absence = ServerBenchmarkUnsealedProjectionAbsence(
        inventory=ServerBenchmarkUnsealedRecoveryInventory(engine),
        qdrant=derived_providers.vector_evidence or unavailable,
        graphiti=derived_providers.graph_evidence or unavailable,
        qdrant_target_commitment_sha256=(derived_providers.qdrant_target_commitment_sha256),
        graphiti_target_commitment_sha256=(derived_providers.graphiti_target_commitment_sha256),
    )
    return BenchmarkRunUseCases(
        register=RegisterBenchmarkRunUseCase(uow_factory=uow_factory, clock=clock),
        seal_manifest=SealProjectionManifestUseCase(uow_factory=uow_factory, clock=clock),
        begin_cleanup=CleanupBenchmarkRunUseCase(uow_factory=uow_factory, clock=clock),
        get_lifecycle=GetBenchmarkRunLifecycleUseCase(uow_factory=uow_factory),
        finalize_sealed=FinalizeBenchmarkRunCleanupUseCase(
            uow_factory=uow_factory,
            clock=clock,
            projection_absence=sealed_absence,
        ),
        finalize_unsealed=FinalizeUnsealedBenchmarkAbortUseCase(
            uow_factory=uow_factory,
            clock=clock,
            projection_absence=unsealed_absence,
        ),
    )


__all__ = ("BenchmarkRunUseCases", "build_benchmark_run_use_cases")
