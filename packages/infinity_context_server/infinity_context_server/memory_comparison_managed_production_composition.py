"""Fail-closed production entrypoint for managed memory comparison.

The managed policy lifecycle is production-capable, but this composition root
does not yet own an execution and judge runner. It reports that exact typed
blocker before consuming the prepared run or opening any additional
benchmark/backend lane. One readiness provider probe has already happened
during preparation. Partial production runs would spend more tokens without a
publishable verdict.

Orchestrators must evaluate the pure pre-readiness gate first so current static
blockers cost zero provider tokens.  The prepared-run root is a defensive
fallback for already-probed preparations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    managed_http_policy_production_blockers,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
    _inspect_managed_live_policy_cases,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION = (
    "memory-comparison-managed-production-composition.v1"
)
MANAGED_PRODUCTION_EXECUTION_RUNNER_UNAVAILABLE = (
    "managed_production_execution_runner_unavailable"
)


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
            or self.decision != "no-go"
            or type(self.blockers) is not tuple
            or not self.blockers
            or any(type(item) is not str or not item for item in self.blockers)
            or len(set(self.blockers)) != len(self.blockers)
            or self.preparation_consumed is not False
            or type(self.readiness_provider_calls_already_performed) is not int
            or self.readiness_provider_calls_already_performed not in (0, 1)
            or type(self.additional_provider_calls_performed) is not int
            or self.additional_provider_calls_performed != 0
            or type(self.additional_backend_calls_performed) is not int
            or self.additional_backend_calls_performed != 0
        ):
            raise ManagedProductionCompositionError(
                "managed_production_decision_invalid"
            )

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


def run_verified_managed_production_comparison(
    prepared: VerifiedManagedLiveRunPreparation,
) -> ManagedProductionCompositionDecision:
    """Return NO-GO before consuming preparation while the runner is unavailable."""

    if type(prepared) is not VerifiedManagedLiveRunPreparation:
        raise ManagedProductionCompositionError(
            "managed_production_preparation_invalid"
        )
    try:
        cases = _inspect_managed_live_policy_cases(prepared)
        blockers = _production_blockers(cases)
    except ManagedProductionCompositionError:
        raise
    except Exception:
        raise ManagedProductionCompositionError(
            "managed_production_preflight_failed"
        ) from None
    return ManagedProductionCompositionDecision(
        schema_version=MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION,
        decision="no-go",
        blockers=blockers,
        preparation_consumed=False,
        readiness_provider_calls_already_performed=1,
        additional_provider_calls_performed=0,
        additional_backend_calls_performed=0,
    )


def evaluate_managed_production_pre_readiness(
    cases: tuple[ManagedRunCase, ...],
) -> ManagedProductionCompositionDecision:
    """Return static NO-GO before credentials, readiness, providers, or backends."""

    try:
        blockers = _production_blockers(cases)
    except Exception:
        raise ManagedProductionCompositionError(
            "managed_production_pre_readiness_failed"
        ) from None
    return ManagedProductionCompositionDecision(
        schema_version=MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION,
        decision="no-go",
        blockers=blockers,
        preparation_consumed=False,
        readiness_provider_calls_already_performed=0,
        additional_provider_calls_performed=0,
        additional_backend_calls_performed=0,
    )


def _production_blockers(cases: tuple[ManagedRunCase, ...]) -> tuple[str, ...]:
    lifecycle_blockers = managed_http_policy_production_blockers(cases)
    return (
        *lifecycle_blockers,
        MANAGED_PRODUCTION_EXECUTION_RUNNER_UNAVAILABLE,
    )


__all__ = (
    "MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION",
    "MANAGED_PRODUCTION_EXECUTION_RUNNER_UNAVAILABLE",
    "ManagedProductionCompositionDecision",
    "ManagedProductionCompositionError",
    "evaluate_managed_production_pre_readiness",
    "run_verified_managed_production_comparison",
)
