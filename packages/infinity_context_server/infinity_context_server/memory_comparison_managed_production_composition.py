"""Fail-closed production entrypoint for managed memory comparison.

Orchestrators evaluate the pure pre-readiness gate before credentials, provider
or backend calls. A verified preparation is consumed only by the concrete
production runner after the same policy gate remains GO.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    managed_http_policy_production_blockers,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
    VerifiedManagedLiveRunPreparation,
    _inspect_managed_live_policy_cases,
)
from infinity_context_server.memory_comparison_managed_production_runner import (
    run_verified_managed_production_execution,
)
from infinity_context_server.memory_comparison_managed_run import ManagedRunOutcome
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    run_verified_managed_v5_production_execution,
)
from infinity_context_server.memory_comparison_managed_v5_runtime_factory import (
    ManagedV5ProductionRuntime,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION = (
    "memory-comparison-managed-production-composition.v1"
)
MANAGED_PRODUCTION_EXECUTION_LEGACY_HTTP = "managed-http-v1"
MANAGED_PRODUCTION_EXECUTION_V5 = "managed-v5"


class ManagedProductionCompositionError(RuntimeError):
    """Fixed-code failure without credentials, gold, prompts, or provider text."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedProductionCompositionDecision:
    """Secret-free decision produced before any additional benchmark/backend I/O."""

    schema_version: str
    decision: str
    blockers: tuple[str, ...]
    preparation_consumed: bool
    readiness_provider_calls_already_performed: int
    additional_provider_calls_performed: int
    additional_backend_calls_performed: int

    def __post_init__(self) -> None:
        if (
            self.schema_version != MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION
            or self.decision not in {"go", "no-go"}
            or type(self.blockers) is not tuple
            or any(type(item) is not str or not item for item in self.blockers)
            or len(set(self.blockers)) != len(self.blockers)
            or (self.decision == "go" and self.blockers)
            or (self.decision == "no-go" and not self.blockers)
            or self.preparation_consumed is not False
            or type(self.readiness_provider_calls_already_performed) is not int
            or self.readiness_provider_calls_already_performed not in (0, 1)
            or type(self.additional_provider_calls_performed) is not int
            or self.additional_provider_calls_performed != 0
            or type(self.additional_backend_calls_performed) is not int
            or self.additional_backend_calls_performed != 0
        ):
            raise ManagedProductionCompositionError("managed_production_decision_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision,
            "blockers": list(self.blockers),
            "preparation_consumed": self.preparation_consumed,
            "readiness_provider_calls_already_performed": (
                self.readiness_provider_calls_already_performed
            ),
            "additional_provider_calls_performed": self.additional_provider_calls_performed,
            "additional_backend_calls_performed": self.additional_backend_calls_performed,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProductionCompositionDecision is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedV5ProductionExecutionSelection:
    """Exact v5 execution inputs for the explicit public cutover selector."""

    runtime: ManagedV5ProductionRuntime = field(repr=False)
    provider: BoundedProviderChatCompletions = field(repr=False)
    limits: ManagedLiveExecutionLimits
    provider_route: ProviderRouteAttestation
    attestation_port: object = field(repr=False)
    clock: Callable[[], datetime] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.runtime) is not ManagedV5ProductionRuntime
            or type(self.provider) is not BoundedProviderChatCompletions
            or type(self.limits) is not ManagedLiveExecutionLimits
            or type(self.provider_route) is not ProviderRouteAttestation
            or self.attestation_port is None
            or not callable(self.clock)
        ):
            raise ManagedProductionCompositionError("managed_production_v5_selection_invalid")


def run_verified_managed_production_comparison(
    prepared: VerifiedManagedLiveRunPreparation,
) -> ManagedRunOutcome:
    """Execute one verified preparation after the pure production gate stays GO."""

    if type(prepared) is not VerifiedManagedLiveRunPreparation:
        raise ManagedProductionCompositionError("managed_production_preparation_invalid")
    try:
        cases = _inspect_managed_live_policy_cases(prepared)
        blockers = _production_blockers(cases)
    except ManagedProductionCompositionError:
        raise
    except Exception:
        raise ManagedProductionCompositionError("managed_production_preflight_failed") from None
    if blockers:
        raise ManagedProductionCompositionError("managed_production_blocked")
    return run_verified_managed_production_execution(prepared)


def run_selected_managed_production_comparison(
    *,
    execution_mode: str,
    legacy_prepared: VerifiedManagedLiveRunPreparation | None = None,
    v5_execution: ManagedV5ProductionExecutionSelection | None = None,
) -> ManagedRunOutcome:
    """Route one explicit production mode; never fall back across implementations."""

    if execution_mode == MANAGED_PRODUCTION_EXECUTION_V5:
        if (
            legacy_prepared is not None
            or type(v5_execution) is not ManagedV5ProductionExecutionSelection
        ):
            raise ManagedProductionCompositionError("managed_production_v5_selection_invalid")
        return run_verified_managed_v5_production_execution(
            v5_execution.runtime,
            provider=v5_execution.provider,
            limits=v5_execution.limits,
            provider_route=v5_execution.provider_route,
            attestation_port=v5_execution.attestation_port,
            clock=v5_execution.clock,
        )
    if execution_mode == MANAGED_PRODUCTION_EXECUTION_LEGACY_HTTP:
        if (
            type(legacy_prepared) is not VerifiedManagedLiveRunPreparation
            or v5_execution is not None
        ):
            raise ManagedProductionCompositionError("managed_production_legacy_selection_invalid")
        return run_verified_managed_production_comparison(legacy_prepared)
    raise ManagedProductionCompositionError("managed_production_execution_mode_invalid")


def evaluate_managed_production_pre_readiness(
    cases: tuple[ManagedRunCase, ...],
) -> ManagedProductionCompositionDecision:
    """Return static GO/NO-GO before credentials, readiness, providers, or backends."""

    try:
        blockers = _production_blockers(cases)
    except Exception:
        raise ManagedProductionCompositionError("managed_production_pre_readiness_failed") from None
    return ManagedProductionCompositionDecision(
        schema_version=MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION,
        decision="no-go" if blockers else "go",
        blockers=blockers,
        preparation_consumed=False,
        readiness_provider_calls_already_performed=0,
        additional_provider_calls_performed=0,
        additional_backend_calls_performed=0,
    )


def _production_blockers(cases: tuple[ManagedRunCase, ...]) -> tuple[str, ...]:
    return managed_http_policy_production_blockers(cases)


__all__ = (
    "MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION",
    "MANAGED_PRODUCTION_EXECUTION_LEGACY_HTTP",
    "MANAGED_PRODUCTION_EXECUTION_V5",
    "ManagedProductionCompositionDecision",
    "ManagedProductionCompositionError",
    "ManagedV5ProductionExecutionSelection",
    "evaluate_managed_production_pre_readiness",
    "run_verified_managed_production_comparison",
    "run_selected_managed_production_comparison",
)
