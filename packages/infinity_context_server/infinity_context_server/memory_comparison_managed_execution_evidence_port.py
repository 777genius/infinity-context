"""Neutral port for ready execution evidence and full-validation sealing."""

from __future__ import annotations

from typing import Protocol

from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
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


class ManagedExecutionEvidencePort(Protocol):
    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding: ...

    def consume_ready_evidence(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None: ...

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
    ) -> VerifiedFullExecutionValidation: ...


__all__ = ("ManagedExecutionEvidencePort",)
