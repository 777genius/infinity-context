"""Distinct managed runner facades over one private execution coordinator."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_llm_execution_dispatch import (
    ManagedLlmExecutionError,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedCaseExecution,
    ManagedExecutionArtifacts,
    ManagedRunCase,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE = False
MANAGED_PRODUCTION_METHODOLOGY_STATUS = "canary_nonpublishable_identical_methodology_unproven"
_EXECUTION_ADAPTER_ID = "managed-comparison-production-answer-v1"
_JUDGE_ADAPTER_ID = "managed-comparison-production-stateful-judge-v1"


class _Coordinator(Protocol):
    def bind_cases(
        self,
        bindings: FullComparisonRunBindings,
        cases: tuple[PublicBenchmarkCase, ...],
        aliases: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]: ...

    def retrieve(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> object: ...

    def answer(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object: ...

    def judge(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        answer_receipt: object,
    ) -> object: ...

    def seal_execution(
        self,
        bindings: FullComparisonRunBindings,
        manifest: tuple[FullExecutionCaseManifestEntry, ...],
        executions: tuple[ManagedCaseExecution, ...],
        manifest_sha256: str,
        material: tuple[tuple[str, str], ...],
    ) -> ManagedExecutionArtifacts: ...


@final
class ManagedComparisonCandidateExecutionPort:
    """Gold-free retrieval and candidate-answer facade."""

    __slots__ = ("_coordinator",)

    def __init__(self, coordinator: _Coordinator) -> None:
        self._coordinator = coordinator

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonCandidateExecutionPort is final")

    @property
    def adapter_id(self) -> str:
        return _EXECUTION_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _implementation_sha256(_EXECUTION_ADAPTER_ID)

    def retrieve(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> object:
        return self._coordinator.retrieve(
            bindings, backend_role, target_identity_sha256, case, query
        )

    def answer(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object:
        return self._coordinator.answer(
            bindings,
            backend_role,
            target_identity_sha256,
            case,
            query,
            retrieval_receipt,
        )


@final
class ManagedComparisonJudgeExecutionPort:
    """Private case binding, stateful judge, and terminal evidence facade."""

    __slots__ = ("_coordinator",)

    def __init__(self, coordinator: _Coordinator) -> None:
        self._coordinator = coordinator

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonJudgeExecutionPort is final")

    @property
    def adapter_id(self) -> str:
        return _JUDGE_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _implementation_sha256(_JUDGE_ADAPTER_ID)

    def bind_cases(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[PublicBenchmarkCase, ...],
        case_aliases: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]:
        return self._coordinator.bind_cases(bindings, cases, case_aliases)

    def judge(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        answer_receipt: object,
    ) -> object:
        return self._coordinator.judge(
            bindings, backend_role, target_identity_sha256, case, answer_receipt
        )

    def seal_execution(
        self,
        *,
        bindings: FullComparisonRunBindings,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        executions: tuple[ManagedCaseExecution, ...],
        case_manifest_sha256: str,
        case_material_sha256: tuple[tuple[str, str], ...],
    ) -> ManagedExecutionArtifacts:
        return self._coordinator.seal_execution(
            bindings,
            case_manifest,
            executions,
            case_manifest_sha256,
            case_material_sha256,
        )


@final
@dataclass(frozen=True, slots=True)
class ManagedComparisonExecutionPorts:
    """Distinct runner ports backed by one serial authority."""

    execution_port: ManagedComparisonCandidateExecutionPort
    judge_port: ManagedComparisonJudgeExecutionPort

    def __post_init__(self) -> None:
        if (
            type(self.execution_port) is not ManagedComparisonCandidateExecutionPort
            or type(self.judge_port) is not ManagedComparisonJudgeExecutionPort
        ):
            raise ManagedLlmExecutionError("managed_execution_ports_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonExecutionPorts is final")


def _implementation_sha256(adapter_id: str) -> str:
    return hashlib.sha256(
        f"{adapter_id}\0{MANAGED_PRODUCTION_METHODOLOGY_STATUS}".encode()
    ).hexdigest()


__all__ = (
    "MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE",
    "MANAGED_PRODUCTION_METHODOLOGY_STATUS",
    "ManagedComparisonCandidateExecutionPort",
    "ManagedComparisonExecutionPorts",
    "ManagedComparisonJudgeExecutionPort",
)
