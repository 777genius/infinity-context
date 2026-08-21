"""Managed benchmark guards around the feature-first fact handlers."""

from __future__ import annotations

import infinity_context_core.features.memory_facts.public as memory_facts_feature
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkFactMutationBlocker,
    ManagedBenchmarkRememberFactAdmission,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4FactAuthorityPort,
)


def build_managed_memory_fact_use_cases(
    *,
    benchmark_uow_factory: object,
    memory_fact_uow_factory: object,
    clock: object,
    ids: object,
    strict_v4_fact_authority: ManagedBenchmarkStrictV4FactAuthorityPort | None = None,
) -> tuple[
    memory_facts_feature.MemoryFactLifecycleUseCases,
    memory_facts_feature.MemoryFactTemporalUseCases,
]:
    lifecycle = memory_facts_feature.MemoryFactLifecycleUseCases(
        remember_fact=ManagedBenchmarkRememberFactAdmission(
            uow_factory=benchmark_uow_factory,
            strict_v4_authority=strict_v4_fact_authority,
            inner=memory_facts_feature.RememberFactHandler(
                uow_factory=memory_fact_uow_factory,
                clock=clock,
                ids=ids,
            ),
        ),
        update_fact=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.UpdateFactHandler(
                uow_factory=memory_fact_uow_factory,
                clock=clock,
                ids=ids,
            ),
            uow_factory=benchmark_uow_factory,
        ),
        forget_fact=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.ForgetFactHandler(
                uow_factory=memory_fact_uow_factory,
                clock=clock,
                ids=ids,
            ),
            uow_factory=benchmark_uow_factory,
        ),
    )
    temporal = memory_facts_feature.MemoryFactTemporalUseCases(
        confirm_fact=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.ConfirmFactHandler(
                uow_factory=memory_fact_uow_factory, clock=clock, ids=ids
            ),
        ),
        end_validity=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.EndFactValidityHandler(
                uow_factory=memory_fact_uow_factory, clock=clock, ids=ids
            ),
        ),
        supersede_fact=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.SupersedeFactHandler(
                uow_factory=memory_fact_uow_factory, clock=clock, ids=ids
            ),
        ),
        dispute_facts=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.DisputeFactsHandler(
                uow_factory=memory_fact_uow_factory, clock=clock, ids=ids
            ),
        ),
        reinstate_supersession=ManagedBenchmarkFactMutationBlocker(
            inner=memory_facts_feature.ReinstateSupersededFactHandler(
                uow_factory=memory_fact_uow_factory, clock=clock, ids=ids
            ),
        ),
    )
    return lifecycle, temporal


__all__ = ("build_managed_memory_fact_use_cases",)
