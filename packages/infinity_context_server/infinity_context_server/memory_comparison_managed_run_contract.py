"""Immutable DTOs and ports for abstract managed comparison orchestration."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, final

from infinity_context_server.memory_comparison_full_methodology import (
    FrozenFullComparisonMethodology,
)
from infinity_context_server.memory_comparison_full_profiles import FullComparisonProfile
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    FullComparisonEvidenceIssuer,
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_run_ports import ManagedPortIdentity
from infinity_context_server.memory_comparison_provider_provenance import ProviderRouteAttestation

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedRunError(RuntimeError):
    """Raised when the managed lifecycle cannot be safely completed."""


@final
@dataclass(frozen=True, slots=True)
class ManagedRunCase:
    case_id: str
    corpus_id: str
    record: Mapping[str, object]

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.corpus_id, "corpus_id")
        if type(self.record) is not dict:
            raise ManagedRunError("case record must be an exact dict")
        frozen = _freeze_json(self.record)
        if type(frozen) is not MappingProxyType:
            raise ManagedRunError("case record must be an exact JSON object")
        object.__setattr__(self, "record", frozen)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRunCase is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedRunPlan:
    run_id: str
    run_nonce_commitment_sha256: str
    runtime_probe_nonce_sha256: str
    profile: FullComparisonProfile
    methodology: FrozenFullComparisonMethodology
    dataset_sha256: str
    selection_fingerprint_sha256: str
    backend_targets: tuple[FullComparisonBackendTarget, ...]
    provider_route: ProviderRouteAttestation
    cases: tuple[ManagedRunCase, ...]
    scope: str = "full"

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        for value, name in (
            (self.run_nonce_commitment_sha256, "run nonce"),
            (self.runtime_probe_nonce_sha256, "runtime probe nonce"),
            (self.dataset_sha256, "dataset"),
            (self.selection_fingerprint_sha256, "selection"),
        ):
            _digest(value, name)
        if type(self.backend_targets) is not tuple:
            raise ManagedRunError("backend_targets must be an exact tuple")
        if type(self.provider_route) is not ProviderRouteAttestation:
            raise ManagedRunError("provider route type must be exact")
        if (
            type(self.cases) is not tuple
            or not self.cases
            or any(type(item) is not ManagedRunCase for item in self.cases)
        ):
            raise ManagedRunError("cases must be a nonempty exact typed tuple")
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ManagedRunError("case_id is duplicated")
        _unique_corpora(self.cases)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRunPlan is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedCaseExecution:
    backend_role: str
    target_identity_sha256: str
    case_id: str
    retrieval_receipt: object
    answer_receipt: object
    judge_receipt: object

    def __post_init__(self) -> None:
        _identifier(self.backend_role, "execution backend_role")
        _digest(self.target_identity_sha256, "execution target identity")
        _identifier(self.case_id, "execution case_id")
        receipts = self.retrieval_receipt, self.answer_receipt, self.judge_receipt
        if any(item is None for item in receipts) or len({id(item) for item in receipts}) != 3:
            raise ManagedRunError("execution receipts must be distinct live objects")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedCaseExecution is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedExecutionArtifacts:
    gold_blind_validation: object
    execution_validation: object
    case_manifest_sha256: str

    def __post_init__(self) -> None:
        if self.gold_blind_validation is None or self.execution_validation is None:
            raise ManagedRunError("execution validations must be live objects")
        if self.gold_blind_validation is self.execution_validation:
            raise ManagedRunError("execution validations must be distinct")
        _digest(self.case_manifest_sha256, "case manifest")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedExecutionArtifacts is final")


class ManagedIngestEvidencePort(ManagedPortIdentity, Protocol):
    """Ingest one corpus and return a live policy-consumed receipt."""

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> object: ...


class ManagedExecutionPort(ManagedPortIdentity, Protocol):
    def retrieve(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
    ) -> object: ...
    def answer(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        retrieval_receipt: object,
    ) -> object: ...
    def judge(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        answer_receipt: object,
    ) -> object: ...
    def seal_execution(
        self,
        *,
        bindings: FullComparisonRunBindings,
        executions: tuple[ManagedCaseExecution, ...],
        case_manifest_sha256: str,
    ) -> ManagedExecutionArtifacts: ...


class ManagedPolicyLifecyclePort(ManagedPortIdentity, Protocol):
    def seal_canonical_source(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        ingest_receipts: tuple[object, ...],
        execution: ManagedExecutionArtifacts,
    ) -> tuple[object, ...]: ...
    def terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        pass_index: int,
    ) -> object: ...
    def seal_terminal_delete(
        self, *, bindings: FullComparisonRunBindings, receipts: tuple[object, ...]
    ) -> object: ...
    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> object: ...


class ManagedCompositeAssemblerPort(ManagedPortIdentity, Protocol):
    """Pending-wiring seam for the exact nine ordered evidence slots."""

    def assemble_components(
        self,
        *,
        bindings: FullComparisonRunBindings,
        issuer: FullComparisonEvidenceIssuer,
        managed_attestation: VerifiedManagedCompositionAttestation,
        execution_validation: object,
        gold_blind_validation: object,
        policy_validation: object,
        case_manifest_sha256: str,
    ) -> tuple[object, ...]: ...
    def seal_verdict(
        self,
        *,
        bindings: FullComparisonRunBindings,
        issuer: FullComparisonEvidenceIssuer,
        components: tuple[object, ...],
    ) -> object: ...
    def public_verdict(self, verdict: object) -> Mapping[str, object]: ...


def _unique_corpora(
    cases: tuple[ManagedRunCase, ...],
) -> tuple[tuple[str, MappingProxyType[str, object]], ...]:
    records: dict[str, MappingProxyType[str, object]] = {}
    order: list[str] = []
    for case in cases:
        record = case.record
        if type(record) is not MappingProxyType:
            raise ManagedRunError("case record integrity changed")
        current = records.get(case.corpus_id)
        if current is None:
            records[case.corpus_id] = record
            order.append(case.corpus_id)
        elif current != record:
            raise ManagedRunError("one corpus has conflicting records")
    return tuple((corpus_id, records[corpus_id]) for corpus_id in order)


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ManagedRunError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedRunError(f"{name} must be SHA-256")
    return value


def _freeze_json(value: object, *, depth: int = 0) -> object:
    if depth > 16:
        raise ManagedRunError("JSON nesting is too deep")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ManagedRunError("JSON number must be finite")
        return value
    if type(value) in {dict, MappingProxyType}:
        if len(value) > 1_000:
            raise ManagedRunError("JSON mapping is too large")
        return MappingProxyType(
            {_json_key(key): _freeze_json(item, depth=depth + 1) for key, item in value.items()}
        )
    if type(value) in {list, tuple}:
        if len(value) > 1_000:
            raise ManagedRunError("JSON sequence is too large")
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    raise ManagedRunError("value is not exact JSON")


def _thaw_json(value: object, *, depth: int = 0) -> object:
    if depth > 16:
        raise ManagedRunError("JSON nesting is too deep")
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if type(value) in {dict, MappingProxyType}:
        return {_json_key(key): _thaw_json(item, depth=depth + 1) for key, item in value.items()}
    if type(value) in {list, tuple}:
        return [_thaw_json(item, depth=depth + 1) for item in value]
    raise ManagedRunError("value is not exact JSON")


def _json_key(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ManagedRunError("JSON key is invalid")
    return value


__all__ = (
    "ManagedCaseExecution",
    "ManagedCompositeAssemblerPort",
    "ManagedExecutionArtifacts",
    "ManagedExecutionPort",
    "ManagedIngestEvidencePort",
    "ManagedPolicyLifecyclePort",
    "ManagedRunCase",
    "ManagedRunError",
    "ManagedRunPlan",
)
