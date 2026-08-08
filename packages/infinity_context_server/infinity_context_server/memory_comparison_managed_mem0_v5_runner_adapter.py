"""Provider-free managed-runner retrieval adapter for the Mem0 v5 lane."""

from __future__ import annotations

import hashlib
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedRun,
    managed_mem0_v5_paired_run_fingerprint,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)


class ManagedMem0V5RetrievalAdapterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _AdapterState:
    binding: ManagedRunnerCompositionBinding
    paired_run: ManagedMem0V5PairedRun
    authority: ManagedMem0V5ManifestAuthority
    request: Mem0OssAdmissionRequest
    mem0_target_identity_sha256: str
    corpus_ids: frozenset[str]
    admission_commitment_sha256: str
    paired_run_fingerprint_sha256: str


_LOCK = threading.RLock()
_STATES: weakref.WeakKeyDictionary[ManagedMem0V5RetrievalAdapter, _AdapterState]


@final
class ManagedMem0V5RetrievalAdapter:
    """Structural ``ManagedRetrievalPort`` over one sealed paired run."""

    __slots__ = ("__weakref__", "_authority", "_binding", "_paired_run", "_request")

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        paired_run: ManagedMem0V5PairedRun,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
    ) -> None:
        target = _validate_composition(
            composition_binding=composition_binding,
            paired_run=paired_run,
            authority=authority,
            request=request,
        )
        admission = Mem0OssFullRunAdmission(
            request=request,
            ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
            ingestion_root_sha256=authority.ingestion_root_sha256,
            ingestion_unit_count=authority.operation_count,
        )
        self._binding = composition_binding
        self._paired_run = paired_run
        self._authority = authority
        self._request = request
        state = _AdapterState(
            composition_binding,
            paired_run,
            authority,
            request,
            target,
            frozenset(item.corpus_id for item in authority.units),
            admission.commitment_sha256,
            managed_mem0_v5_paired_run_fingerprint(paired_run),
        )
        with _LOCK:
            _STATES[self] = state

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _state(self).binding

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        state = _state(self)
        if backend_role != "mem0" or target_identity_sha256 != state.mem0_target_identity_sha256:
            raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_authority_invalid")
        return _issue_managed_retrieval_authority(
            state.binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult:
        state = _state(self)
        if (
            type(case) is not ManagedRunCase
            or type(query) is not ManagedAnswerCase
            or case.case_id != query.case_id
            or case.corpus_id not in state.corpus_ids
        ):
            raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_request_invalid")
        try:
            backend_role, target_identity = _validate_managed_retrieval_authority(
                authority,
                composition_binding=state.binding,
            )
        except Exception:
            raise ManagedMem0V5RetrievalAdapterError(
                "managed_mem0_v5_retrieval_authority_invalid"
            ) from None
        if backend_role != "mem0" or target_identity != state.mem0_target_identity_sha256:
            raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_authority_invalid")
        try:
            evidence = state.paired_run.search(
                corpus_id=case.corpus_id,
                query=query.question,
                top_k=state.binding.retrieval_top_k,
                cutoff=state.binding.answer_cutoff,
            )
            identity = gold_blind_evidence_identity(evidence)
            return ManagedRetrievalResult(
                evidence=evidence,
                retrieval_identity=identity,
                metadata={
                    "adapter_id": "managed-mem0-v5.paired-retrieval.v1",
                    "run_id_sha256": hashlib.sha256(state.binding.run_id.encode()).hexdigest(),
                    "backend_role": "mem0",
                    "target_identity_sha256": state.mem0_target_identity_sha256,
                    "corpus_id_sha256": canonical_sha256({"corpus_id": case.corpus_id}),
                    "case_id_sha256": canonical_sha256({"case_id": case.case_id}),
                    "query_commitment_sha256": canonical_sha256({"query": query.question}),
                    "admission_commitment_sha256": state.admission_commitment_sha256,
                    "authority_commitment_sha256": state.authority.authority_commitment_sha256,
                    "ingestion_manifest_sha256": state.authority.ingestion_manifest_sha256,
                    "retrieval_top_k": state.binding.retrieval_top_k,
                    "answer_cutoff": state.binding.answer_cutoff,
                },
            )
        except ManagedMem0V5RetrievalAdapterError:
            raise
        except Exception:
            raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_failed") from None

    def __repr__(self) -> str:
        return "ManagedMem0V5RetrievalAdapter(<opaque>)"


def _validate_composition(
    *,
    composition_binding: object,
    paired_run: object,
    authority: object,
    request: object,
) -> str:
    if (
        type(composition_binding) is not ManagedRunnerCompositionBinding
        or type(paired_run) is not ManagedMem0V5PairedRun
        or type(authority) is not ManagedMem0V5ManifestAuthority
        or type(request) is not Mem0OssAdmissionRequest
        or paired_run._authority is not authority
        or paired_run._request is not request
        or request.run_id != composition_binding.run_id
        or request.expected_operation_count != authority.operation_count
    ):
        raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_composition_invalid")
    authority.__post_init__()
    targets = tuple(
        item.target_identity_sha256
        for item in composition_binding.backend_targets
        if item.backend_role == "mem0"
    )
    if len(targets) != 1:
        raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_composition_invalid")
    return targets[0]


def _state(value: object) -> _AdapterState:
    if type(value) is not ManagedMem0V5RetrievalAdapter:
        raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_composition_invalid")
    with _LOCK:
        state = _STATES.get(value)
    try:
        current_fingerprint = (
            None if state is None else managed_mem0_v5_paired_run_fingerprint(state.paired_run)
        )
    except Exception:
        current_fingerprint = None
    if (
        state is None
        or value._binding is not state.binding
        or value._paired_run is not state.paired_run
        or value._authority is not state.authority
        or value._request is not state.request
        or state.paired_run_fingerprint_sha256 != current_fingerprint
    ):
        raise ManagedMem0V5RetrievalAdapterError("managed_mem0_v5_retrieval_composition_invalid")
    _validate_composition(
        composition_binding=state.binding,
        paired_run=state.paired_run,
        authority=state.authority,
        request=state.request,
    )
    return state


_STATES = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedMem0V5RetrievalAdapter",
    "ManagedMem0V5RetrievalAdapterError",
)
