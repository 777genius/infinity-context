"""Execution-evidence port gated by the PR45 production lifecycle."""

from __future__ import annotations

from typing import final

from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_full_run_evidence import FullComparisonRunBindings
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)


class ManagedMem0V5ProductionExecutionEvidenceError(RuntimeError):
    pass


@final
class ManagedMem0V5ProductionExecutionEvidenceFacade:
    """Expose the neutral port without leaking the underlying evidence authority."""

    __slots__ = ("_binding", "_lifecycle")

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        lifecycle: ManagedMem0V5ProductionLifecycleAdapter,
    ) -> None:
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(lifecycle) is not ManagedMem0V5ProductionLifecycleAdapter
            or lifecycle.composition_binding is not composition_binding
        ):
            raise ManagedMem0V5ProductionExecutionEvidenceError(
                "production_execution_evidence_composition_invalid"
            )
        self._binding = composition_binding
        self._lifecycle = lifecycle

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return self._binding

    def consume_ready_evidence(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        self._require_binding(composition_binding)
        lifecycle = self._trusted_lifecycle()
        lifecycle.consume_ready_execution_evidence(
            composition_binding=composition_binding,
            bindings=bindings,
            cases=cases,
        )

    def seal_execution_validation(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        benchmark: str,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        required_model: str,
        required_route: ProviderRouteAttestation,
        provider_calls: tuple[FullExecutionProviderCall, ...],
        session_verifier: RunScopedSessionHmacKey,
        session_evidence: tuple[SessionIdentityEvidence, ...],
    ) -> VerifiedFullExecutionValidation:
        self._require_binding(composition_binding)
        return self._trusted_lifecycle().seal_execution_validation(
            composition_binding=composition_binding,
            bindings=bindings,
            benchmark=benchmark,
            case_manifest=case_manifest,
            required_model=required_model,
            required_route=required_route,
            provider_calls=provider_calls,
            session_verifier=session_verifier,
            session_evidence=session_evidence,
        )

    def _require_binding(self, value: object) -> None:
        if value is not self._binding:
            raise ManagedMem0V5ProductionExecutionEvidenceError(
                "production_execution_evidence_binding_invalid"
            )

    def _trusted_lifecycle(self) -> ManagedMem0V5ProductionLifecycleAdapter:
        try:
            valid = (
                type(self._lifecycle) is ManagedMem0V5ProductionLifecycleAdapter
                and self._lifecycle.composition_binding is self._binding
            )
        except Exception:
            valid = False
        if not valid:
            raise ManagedMem0V5ProductionExecutionEvidenceError(
                "production_execution_evidence_composition_invalid"
            )
        return self._lifecycle


__all__ = (
    "ManagedMem0V5ProductionExecutionEvidenceError",
    "ManagedMem0V5ProductionExecutionEvidenceFacade",
)
