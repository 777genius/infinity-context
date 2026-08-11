"""Run-aware scheduler retrieval over authenticated managed Mem0 v5 search."""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_projector import (
    ManagedMem0V5PairedEvidenceProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5AdmissionReceipt,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as extraction_composition,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBenchmark,
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
    SchedulerRetrievalCaptureError,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_http_adapters import (
    gold_blind_retrieval_case,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    is_sha256,
)

PublishableFullExtractionSuiteConfiguration = (
    extraction_composition.PublishableFullExtractionSuiteConfiguration
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class _ManagedMem0V5RetrievalRunBinding:
    benchmark: SchedulerBenchmark
    case_count: int
    run_id: str
    target_identity_sha256: str
    expected_runtime_binding_sha256: str
    manifest: ManagedMem0V5ManifestAuthority = field(repr=False)
    admission: Mem0OssFullRunAdmission = field(repr=False)
    lane: ManagedMem0V5HttpLane = field(repr=False)
    corpus_ids: frozenset[str] = field(init=False, repr=False)
    projector: ManagedMem0V5PairedEvidenceProjector = field(init=False, repr=False)
    _admission_lock: threading.RLock = field(init=False, repr=False, compare=False)
    _admitted: bool = field(init=False, repr=False, compare=False, default=False)

    def __post_init__(self) -> None:
        if (
            type(self.benchmark) is not SchedulerBenchmark
            or type(self.case_count) is not int
            or self.case_count < 1
            or type(self.run_id) is not str
            or not self.run_id
            or not is_sha256(self.target_identity_sha256)
            or not is_sha256(self.expected_runtime_binding_sha256)
            or type(self.manifest) is not ManagedMem0V5ManifestAuthority
            or type(self.admission) is not Mem0OssFullRunAdmission
            or type(self.lane) is not ManagedMem0V5HttpLane
        ):
            _fail("scheduler_managed_mem0_v5_binding_invalid")
        try:
            self.manifest.__post_init__()
            self.admission.__post_init__()
            lane_target = mem0_runtime_target_identity_sha256(
                object.__getattribute__(self.lane, "_origin")
            )
            corpus_ids = frozenset(unit.corpus_id for unit in self.manifest.units)
            projector = ManagedMem0V5PairedEvidenceProjector(
                authority=self.manifest,
                expected_admission_commitment_sha256=self.admission.commitment_sha256,
            )
        except Exception:
            _fail("scheduler_managed_mem0_v5_binding_invalid")
        prefix = f"{self.benchmark.value}-corpus-"
        if (
            self.admission.request.run_id != self.run_id
            or not hmac.compare_digest(lane_target, self.target_identity_sha256)
            or self.manifest.case_count != self.case_count
            or self.manifest.corpus_count != len(corpus_ids)
            or not corpus_ids
            or any(not corpus_id.startswith(prefix) for corpus_id in corpus_ids)
            or self.admission.ingestion_manifest_sha256 != self.manifest.ingestion_manifest_sha256
            or self.admission.ingestion_root_sha256 != self.manifest.ingestion_root_sha256
            or self.admission.ingestion_unit_count != self.manifest.operation_count
            or self.admission.request.expected_operation_count != self.manifest.operation_count
        ):
            _fail("scheduler_managed_mem0_v5_binding_cross_wire")
        object.__setattr__(self, "corpus_ids", corpus_ids)
        object.__setattr__(self, "projector", projector)
        object.__setattr__(self, "_admission_lock", threading.RLock())

    def verify_live_binding(self) -> None:
        try:
            lane_target = mem0_runtime_target_identity_sha256(
                object.__getattribute__(self.lane, "_origin")
            )
            admitted_runtime_binding = object.__getattribute__(
                self.lane, "_admitted_runtime_binding"
            )
            valid = (
                type(self.manifest) is ManagedMem0V5ManifestAuthority
                and type(self.admission) is Mem0OssFullRunAdmission
                and type(self.lane) is ManagedMem0V5HttpLane
                and self.admission.request.run_id == self.run_id
                and self.admission.ingestion_manifest_sha256
                == self.manifest.ingestion_manifest_sha256
                and self.admission.ingestion_root_sha256 == self.manifest.ingestion_root_sha256
                and self.admission.ingestion_unit_count == self.manifest.operation_count
                and hmac.compare_digest(lane_target, self.target_identity_sha256)
                and type(self._admitted) is bool
                and (
                    not self._admitted
                    or admitted_runtime_binding
                    == (
                        self.admission.commitment_sha256,
                        self.expected_runtime_binding_sha256,
                    )
                )
            )
        except Exception:
            valid = False
        if not valid:
            _fail("scheduler_managed_mem0_v5_binding_cross_wire")

    def ensure_admitted(self) -> None:
        """Lazily authenticate this run exactly once before its first search."""

        with self._admission_lock:
            if self._admitted:
                return
            try:
                receipt = self.lane.admit(
                    authority=self.manifest,
                    admission=self.admission,
                )
            except Exception:
                _fail("scheduler_managed_mem0_v5_admission_failed")
            if (
                type(receipt) is not Mem0V5AdmissionReceipt
                or receipt.accepted is not True
                or not hmac.compare_digest(
                    receipt.admission_commitment_sha256,
                    self.admission.commitment_sha256,
                )
                or not hmac.compare_digest(
                    receipt.runtime_binding_commitment_sha256,
                    self.expected_runtime_binding_sha256,
                )
            ):
                _fail("scheduler_managed_mem0_v5_admission_cross_wire")
            object.__setattr__(self, "_admitted", True)


@final
class ManagedMem0V5SchedulerRetrievalAdapter:
    """Select the exact run admission and call only authenticated v5 search."""

    __slots__ = ("_bindings", "_target")

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        configuration: PublishableFullExtractionSuiteConfiguration,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(configuration) is not PublishableFullExtractionSuiteConfiguration
        ):
            _fail("scheduler_managed_mem0_v5_adapter_invalid")
        target = suite.ordered_backend_identities[1].target_identity_sha256
        configs = (configuration.locomo, configuration.longmemeval)
        try:
            bindings = tuple(
                _ManagedMem0V5RetrievalRunBinding(
                    benchmark=run.profile.benchmark,
                    case_count=run.profile.case_count,
                    run_id=run.run_id,
                    target_identity_sha256=config.runtime_target_identity_sha256,
                    expected_runtime_binding_sha256=(
                        config.expected_runtime.subscription_runtime_binding_commitment_sha256
                    ),
                    manifest=config.manifest_authority,
                    admission=config.admission,
                    lane=config.http_lane,
                )
                for run, config in zip(suite.ordered_runs, configs, strict=True)
            )
        except SchedulerRetrievalCaptureError:
            raise
        except Exception:
            _fail("scheduler_managed_mem0_v5_adapter_invalid")
        if (
            len(bindings) != 2
            or any(item.target_identity_sha256 != target for item in bindings)
            or len({item.run_id for item in bindings}) != 2
            or len({item.admission.commitment_sha256 for item in bindings}) != 2
        ):
            _fail("scheduler_managed_mem0_v5_adapter_cross_wire")
        self._bindings = bindings
        self._target = target

    @property
    def backend_role(self) -> str:
        return "mem0"

    @property
    def target_identity_sha256(self) -> str:
        self._verify_live_bindings()
        return self._target

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult:
        binding = self._binding_for(request)
        case = gold_blind_retrieval_case(request)
        try:
            corpus_id, _thread_id = _managed_corpus_identity(case)
        except Exception:
            _fail("scheduler_managed_mem0_v5_request_invalid")
        if corpus_id not in binding.corpus_ids:
            _fail("scheduler_managed_mem0_v5_corpus_cross_wire")
        binding.ensure_admitted()
        try:
            witness = binding.lane.search_authenticated(
                admission=binding.admission,
                corpus_id=corpus_id,
                query=request.question,
                limit=request.retrieval_limit,
            )
        except Exception:
            _fail("scheduler_managed_mem0_v5_search_failed")
        try:
            projected = binding.projector.project(
                authenticated_receipt=witness,
                corpus_id=corpus_id,
                query=request.question,
                top_k=request.retrieval_limit,
                cutoff=request.retrieval_limit,
            )
            memories = tuple(
                RetrievedMemory(
                    text=item.text,
                    rank=item.rank,
                    score=0.0,
                    item_id=item.item_id,
                    created_at=item.created_at,
                )
                for item in projected
            )
            return SchedulerBackendRetrievalResult.bind(
                request=request,
                memories=memories,
            )
        except SchedulerRetrievalCaptureError:
            raise
        except Exception:
            _fail("scheduler_managed_mem0_v5_search_cross_wire")

    def _binding_for(self, request: object) -> _ManagedMem0V5RetrievalRunBinding:
        self._verify_live_bindings()
        if (
            type(request) is not SchedulerBackendRetrievalRequest
            or request.backend_index != 1
            or request.backend_role != self.backend_role
            or request.target_identity_sha256 != self._target
        ):
            _fail("scheduler_managed_mem0_v5_request_invalid")
        matching = tuple(item for item in self._bindings if item.run_id == request.case_key.run_id)
        if len(matching) != 1 or matching[0].benchmark is not request.case_key.benchmark:
            _fail("scheduler_managed_mem0_v5_run_cross_wire")
        return matching[0]

    def _verify_live_bindings(self) -> None:
        for binding in self._bindings:
            binding.verify_live_binding()
        if any(binding.target_identity_sha256 != self._target for binding in self._bindings):
            _fail("scheduler_managed_mem0_v5_adapter_cross_wire")

    def __repr__(self) -> str:
        return "ManagedMem0V5SchedulerRetrievalAdapter(<two-run-target-bound>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("managed Mem0 v5 scheduler retrieval adapters are nonserializable")


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code) from None


__all__ = ("ManagedMem0V5SchedulerRetrievalAdapter",)
