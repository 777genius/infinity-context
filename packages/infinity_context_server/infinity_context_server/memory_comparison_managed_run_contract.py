"""Immutable DTOs and ports for abstract managed comparison orchestration."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, final

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_methodology import (
    FrozenFullComparisonMethodology,
)
from infinity_context_server.memory_comparison_full_profiles import FullComparisonProfile
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    FullComparisonEvidenceIssuer,
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    normalize_full_comparison_scope,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_execution_receipts import (
    ManagedSealedJudgeOutcome,
)
from infinity_context_server.memory_comparison_managed_run_ports import ManagedPortIdentity
from infinity_context_server.memory_comparison_provider_provenance import ProviderRouteAttestation
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ManagedExecutionCaseMaterial = tuple[tuple[str, str], ...]


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
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...]
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
        _validated_execution_case_manifest(
            self.cases,
            self.case_manifest,
            benchmark=self.profile.benchmark,
        )
        _unique_corpora(self.cases)
        object.__setattr__(self, "scope", normalize_full_comparison_scope(self.scope))

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRunPlan is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedAnswerCase:
    case_id: str
    question: str
    temporal_context: Mapping[str, object]

    def __post_init__(self) -> None:
        _identifier(self.case_id, "answer case_id")
        if (
            type(self.question) is not str
            or not self.question
            or self.question != self.question.strip()
        ):
            raise ManagedRunError("answer question is invalid")
        if type(self.temporal_context) is not dict:
            raise ManagedRunError("answer temporal context must be an exact dict")
        frozen = _freeze_json(self.temporal_context)
        if type(frozen) is not MappingProxyType:
            raise ManagedRunError("answer temporal context must be an exact JSON object")
        object.__setattr__(self, "temporal_context", frozen)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedAnswerCase is final")


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
    case_material_sha256: ManagedExecutionCaseMaterial
    quality_outcomes: tuple[ManagedSealedJudgeOutcome, ...] = ()

    def __post_init__(self) -> None:
        if self.gold_blind_validation is None or self.execution_validation is None:
            raise ManagedRunError("execution validations must be live objects")
        if self.gold_blind_validation is self.execution_validation:
            raise ManagedRunError("execution validations must be distinct")
        _digest(self.case_manifest_sha256, "case manifest")
        _validated_case_material_sha256(self.case_material_sha256)
        if type(self.quality_outcomes) is not tuple or any(
            type(item) is not ManagedSealedJudgeOutcome
            for item in self.quality_outcomes
        ):
            raise ManagedRunError("execution quality outcomes must be exact")

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
        query: ManagedAnswerCase,
    ) -> object: ...
    def answer(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object: ...


class ManagedJudgeExecutionPort(ManagedPortIdentity, Protocol):
    def bind_cases(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[PublicBenchmarkCase, ...],
        case_aliases: tuple[str, ...],
    ) -> ManagedExecutionCaseMaterial: ...
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
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        executions: tuple[ManagedCaseExecution, ...],
        case_manifest_sha256: str,
        case_material_sha256: ManagedExecutionCaseMaterial,
    ) -> ManagedExecutionArtifacts: ...


class ManagedPolicyLifecyclePort(ManagedPortIdentity, Protocol):
    def seal_canonical_source(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        ingest_receipts: tuple[object, ...],
        case_manifest_sha256: str,
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
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        receipts: tuple[object, ...],
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


def _validated_execution_case_manifest(
    cases: tuple[ManagedRunCase, ...],
    manifest: object,
    *,
    benchmark: str,
) -> tuple[FullExecutionCaseManifestEntry, ...]:
    if (
        type(manifest) is not tuple
        or len(manifest) != len(cases)
        or any(type(item) is not FullExecutionCaseManifestEntry for item in manifest)
    ):
        raise ManagedRunError("case manifest must exactly cover managed cases")
    trusted = manifest
    expected = tuple((item.case_id, item.corpus_id) for item in cases)
    observed = tuple((item.case_id, item.corpus_id) for item in trusted)
    if observed != expected:
        raise ManagedRunError("case manifest order or case/corpus binding differs")
    execution_case_manifest_sha256(trusted)
    turn_counts = tuple(item.official_turn_count for item in trusted)
    if benchmark == "locomo" and any(count < 1 for count in turn_counts):
        raise ManagedRunError("LoCoMo official turn coverage is empty")
    if benchmark == "longmemeval" and any(count != 0 for count in turn_counts):
        raise ManagedRunError("LongMemEval cannot claim LoCoMo turns")
    if benchmark not in {"locomo", "longmemeval"}:
        raise ManagedRunError("managed execution benchmark is invalid")
    return trusted


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


def _validated_case_material_sha256(value: object) -> ManagedExecutionCaseMaterial:
    if (
        type(value) is not tuple
        or not value
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            for item in value
        )
    ):
        raise ManagedRunError("execution case material must be an exact ordered tuple")
    trusted = value
    for case_alias, digest in trusted:
        _identifier(case_alias, "execution case alias")
        _digest(digest, "execution case material")
    if len({item[0] for item in trusted}) != len(trusted):
        raise ManagedRunError("execution case material alias is duplicated")
    return trusted


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
    "ManagedExecutionCaseMaterial",
    "ManagedExecutionPort",
    "ManagedJudgeExecutionPort",
    "ManagedIngestEvidencePort",
    "ManagedPolicyLifecyclePort",
    "ManagedRunCase",
    "ManagedRunError",
    "ManagedRunPlan",
    "ManagedAnswerCase",
)
