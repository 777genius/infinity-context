from __future__ import annotations

import hashlib
import threading
from dataclasses import fields

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    HmacSha256ManagedMem0V5CheckpointSigner,
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5CheckpointUnit,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchReceipt,
    ManagedMem0V5SearchRecord,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5AuthenticatedSearchWitness,
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedEvidenceProjector,
    ManagedMem0V5PairedRun,
    _expected_clean_scopes,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssFullRunState,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationResult,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    Mem0OssTerminalBasis,
    cleanup_request_commitment,
)
from test_memory_comparison_managed_mem0_v5_transport_evidence import (
    _observations as _transport_observations,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(identity_seed: str | None = None) -> ManagedMem0V5ManifestAuthority:
    identity = "a" * 64 if identity_seed is None else _sha(identity_seed)
    thread_identity = "b" * 64 if identity_seed is None else _sha(f"thread:{identity_seed}")
    corpus_id = f"locomo-corpus-{identity}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{thread_identity}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice likes tea.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    return ManagedMem0V5ManifestProjector().project(
        (
            ManagedRunCase(
                "case-1" if identity_seed is None else f"case-{identity[:16]}",
                corpus_id,
                record,
            ),
        ),
        current_date="2026-08-07",
    )


def _request(operation_count: int, *, run_id: str = "paired-v5-test") -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(
        run_id=run_id,
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("runtime-source"),
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=operation_count,
    )


def _admission(authority: ManagedMem0V5ManifestAuthority, request: Mem0OssAdmissionRequest) -> str:
    return Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    ).commitment_sha256


def _seal(authority: ManagedMem0V5ManifestAuthority, admission: str) -> Mem0OssRunSeal:
    return Mem0OssRunSeal(
        admission_commitment_sha256=admission,
        operation_count=authority.operation_count,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        operation_root_sha256=_sha("operation-root"),
        provider_observed_extraction_calls=authority.operation_count,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
    )


def _terminal(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    *,
    terminal_state: str = Mem0OssFullRunState.DELETED.value,
) -> Mem0OssTerminalCleanupEvidence:
    seal = _seal(authority, admission)
    aborted = terminal_state == Mem0OssFullRunState.ABORTED.value
    return Mem0OssTerminalCleanupEvidence(
        terminal_state=terminal_state,
        admission_commitment_sha256=admission,
        seal_commitment_sha256=None if aborted else seal.commitment_sha256,
        operation_root_sha256=None if aborted else seal.operation_root_sha256,
        operation_inventory_root_sha256=_sha("inventory"),
        deleted_operation_count=0 if aborted else authority.operation_count,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=authority.operation_count,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
        failed_receipts=(),
    )


def _checkpoint(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    phase: ManagedMem0V5RunPhase,
    *,
    aborting: bool = False,
) -> ManagedMem0V5Checkpoint:
    seal = _seal(authority, admission)
    unit_phase = (
        ManagedMem0V5CheckpointPhase.RESERVED
        if phase is ManagedMem0V5RunPhase.ACTIVE
        else ManagedMem0V5CheckpointPhase.COMMITTED
    )
    unit = (
        ManagedMem0V5CheckpointUnit(0, _sha("operation"), unit_phase)
        if unit_phase is ManagedMem0V5CheckpointPhase.RESERVED
        else ManagedMem0V5CheckpointUnit(
            0,
            _sha("operation"),
            unit_phase,
            _sha("receipt"),
            _sha("observation"),
            (),
        )
    )
    cleanup_context = None
    basis = None
    terminal = None
    cleanup_commitment = None
    phase_seal = seal if phase is not ManagedMem0V5RunPhase.ACTIVE and not aborting else None
    if phase in {
        ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
        ManagedMem0V5RunPhase.TERMINAL,
    }:
        cleanup_context = CleanupVerificationContext(
            admission,
            None if aborting else seal.commitment_sha256,
            None if aborting else seal.operation_root_sha256,
            _sha("inventory"),
            authority.operation_count,
            aborting,
        )
        cleanup_commitment = cleanup_request_commitment(cleanup_context)
        basis = Mem0OssTerminalBasis(
            (Mem0OssFullRunState.ABORTED.value if aborting else Mem0OssFullRunState.DELETED.value),
            cleanup_context,
            authority.operation_count,
            10,
            5,
            (),
        )
        if phase is ManagedMem0V5RunPhase.TERMINAL:
            terminal = _terminal(
                authority,
                admission,
                terminal_state=(
                    Mem0OssFullRunState.ABORTED.value
                    if aborting
                    else Mem0OssFullRunState.DELETED.value
                ),
            )
    return ManagedMem0V5Checkpoint.create(
        authority_commitment_sha256=authority.authority_commitment_sha256,
        admission_commitment_sha256=admission,
        generation=0,
        previous_checkpoint_commitment_sha256=None,
        units=(unit,),
        run_phase=phase,
        seal=phase_seal,
        cleanup_context=cleanup_context,
        cleanup_request_commitment_sha256=cleanup_commitment,
        terminal_basis=basis,
        terminal_evidence=terminal,
        signer=HmacSha256ManagedMem0V5CheckpointSigner(key=b"k" * 32),
    )


def _record(*, record_id: str, source_id: str, source_sha256: str):
    memory = f"retrieved {record_id}"
    return ManagedMem0V5SearchRecord(
        record_id,
        memory,
        _sha(memory),
        source_id,
        source_sha256,
        0.9,
    )


def _receipt(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    *,
    query: str,
    limit: int,
    source_id: str | None = None,
    source_sha256: str | None = None,
) -> ManagedMem0V5SearchReceipt:
    unit = authority.units[0]
    records = tuple(
        _record(
            record_id=f"record-{index:03d}",
            source_id=source_id or unit.source_id,
            source_sha256=source_sha256 or unit.source_sha256,
        )
        for index in range(limit)
    )
    root = canonical_sha256(
        {"results": [record.public_payload(rank) for rank, record in enumerate(records)]}
    )
    return ManagedMem0V5SearchReceipt(
        admission,
        unit.corpus_id,
        canonical_sha256({"query": query}),
        limit,
        records,
        root,
        _sha("verified-evidence"),
    )


class _ReceiptVerifier:
    def mark_outcome_unknown(self, *, context: object) -> None:
        del context

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert payload == {"receipt": "dispatch"}
        return RuntimeReceiptVerificationResult(
            context.admission_commitment_sha256,
            context.operation_id_sha256,
            context.unit_identity_sha256,
            context.unit_sha256,
            context.route_sha256,
            context.scope_sha256,
            _sha("provider-receipt"),
            0,
            _sha("request-body"),
            _sha("output-text"),
            _sha("runtime-binding"),
            Mem0OssReceiptDisposition.COMPLETED,
            1,
            0,
            10,
            5,
        )

    verify_status_readback = verify_dispatch_receipt


class _StorageVerifier:
    def verify(
        self, *, payload: object, context: StorageVerificationContext
    ) -> StorageVerificationResult:
        assert type(payload) is ManagedMem0V5AuthenticatedStorageWitness
        return StorageVerificationResult(
            context.admission_commitment_sha256,
            context.operation_id_sha256,
            context.unit_identity_sha256,
            context.unit_sha256,
            context.route_sha256,
            context.scope_sha256,
            context.provider_receipt_sha256,
            payload.storage_commitment_sha256,
            len(payload.created_record_ids),
        )


class _CleanupVerifier:
    def verify(
        self, *, payload: object, context: CleanupVerificationContext
    ) -> CleanupVerificationResult:
        assert payload == {"cleanup": context.aborting}
        return CleanupVerificationResult(
            context.admission_commitment_sha256,
            context.seal_commitment_sha256,
            context.operation_root_sha256,
            context.operation_inventory_root_sha256,
            context.expected_operation_count,
            0,
            MEM0_OSS_EMPTY_ROOT_SHA256,
        )


class _VerifiedSearchLane:
    def __init__(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        *,
        query: str,
        limit: int,
        receipt_admission: str,
    ) -> None:
        self.authority = authority
        self.query = query
        self.limit = limit
        self.receipt_admission = receipt_admission
        self.issuer, _ = create_managed_mem0_v5_storage_witness_authority()

    def admit(self, **kwargs: object) -> None:
        del kwargs

    def dispatch(self, **kwargs: object) -> object:
        del kwargs
        return {"receipt": "dispatch"}

    def status(self, **kwargs: object) -> object:
        del kwargs
        return {"receipt": "dispatch"}

    def inspect_storage(self, **kwargs: object):
        unit = kwargs["unit"]
        return self.issuer.issue_authenticated_storage(
            operation_id_sha256=kwargs["operation_id_sha256"],
            unit_identity_sha256=unit.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=tuple(f"record-{index:03d}" for index in range(200)),
            source_pairs=((unit.source_id, unit.source_sha256),),
        )

    def search(self, **kwargs: object) -> ManagedMem0V5SearchReceipt:
        assert kwargs["query"] == self.query
        assert kwargs["limit"] == self.limit
        return _receipt(
            self.authority,
            self.receipt_admission,
            query=self.query,
            limit=self.limit,
        )

    def cleanup(self, **kwargs: object) -> object:
        return {"cleanup": kwargs["aborting"]}


def _verified_witness(
    authority: ManagedMem0V5ManifestAuthority,
    request: Mem0OssAdmissionRequest,
    *,
    query: str,
    limit: int,
    receipt_admission: str,
) -> ManagedMem0V5AuthenticatedSearchWitness:
    lane = _VerifiedSearchLane(
        authority,
        query=query,
        limit=limit,
        receipt_admission=receipt_admission,
    )
    coordinator = ManagedMem0V5LaneCoordinator(
        service=Mem0OssFullRunService(
            manifest_port=ManagedMem0V5ManifestProjector(),
            receipt_port=_ReceiptVerifier(),
            storage_port=_StorageVerifier(),
            cleanup_port=_CleanupVerifier(),
        ),
        lane_port=lane,
    )
    coordinator.admit(
        authority=authority,
        request=request,
        budget_policy=ManagedMem0V5BudgetPolicy(10_000),
    )
    coordinator.dispatch_pending()
    witness = coordinator.search_authenticated_evidence(
        corpus_id=authority.units[0].corpus_id,
        query=query,
        limit=limit,
    )
    coordinator.cleanup()
    return witness


class _Coordinator:
    def __init__(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
    ) -> None:
        self.authority = authority
        self.request = request
        self.admission = _admission(authority, request)
        self.restore_phase = ManagedMem0V5RunPhase.SEALED
        self.restore_aborting = False
        self.admit_calls = 0
        self.dispatch_calls = 0
        self.restore_calls = 0
        self.seal_restored_calls = 0
        self.search_calls: list[int] = []
        self.cleanup_calls = 0
        self.abort_calls = 0
        self.cleanup_failures = 0
        self.abort_failures = 0
        self.dispatch_failures = 0
        (
            self.storage_issuer,
            self.storage_verifier,
        ) = create_managed_mem0_v5_storage_witness_authority()
        self.storage_values: tuple[ManagedMem0V5AuthenticatedStorageWitness, ...] = ()
        self.start_gate: threading.Event | None = None
        self.release_gate: threading.Event | None = None

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        return _terminal(
            self.authority,
            self.admission,
            terminal_state=(
                Mem0OssFullRunState.ABORTED.value
                if self.restore_aborting
                else Mem0OssFullRunState.DELETED.value
            ),
        )

    @property
    def storage_observations(self) -> tuple[ManagedMem0V5AuthenticatedStorageWitness, ...]:
        return self.storage_values

    def admit(self, **kwargs: object) -> None:
        assert kwargs["authority"] is self.authority
        self.admit_calls += 1

    def dispatch_pending(self) -> Mem0OssRunSeal:
        self.dispatch_calls += 1
        self._block_if_configured()
        if self.dispatch_failures:
            self.dispatch_failures -= 1
            raise RuntimeError("dispatch failed")
        return _seal(self.authority, self.admission)

    def restore(self, **kwargs: object) -> ManagedMem0V5Checkpoint:
        assert kwargs["authority"] is self.authority
        self.restore_calls += 1
        return _checkpoint(
            self.authority,
            self.admission,
            self.restore_phase,
            aborting=self.restore_aborting,
        )

    def seal_restored_completed(self) -> Mem0OssRunSeal:
        self.seal_restored_calls += 1
        return _seal(self.authority, self.admission)

    def search_authenticated_evidence(
        self, *, corpus_id: str, query: str, limit: int
    ) -> ManagedMem0V5AuthenticatedSearchWitness:
        assert corpus_id == self.authority.units[0].corpus_id
        self.search_calls.append(limit)
        self._block_if_configured()
        return _verified_witness(
            self.authority,
            self.request,
            query=query,
            limit=limit,
            receipt_admission=self.admission,
        )

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        self.cleanup_calls += 1
        if self.cleanup_failures:
            self.cleanup_failures -= 1
            raise RuntimeError("cleanup failed")
        return _terminal(self.authority, self.admission)

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        self.abort_calls += 1
        if self.abort_failures:
            self.abort_failures -= 1
            raise RuntimeError("abort failed")
        return _terminal(
            self.authority,
            self.admission,
            terminal_state=Mem0OssFullRunState.ABORTED.value,
        )

    def _block_if_configured(self) -> None:
        if self.start_gate is not None:
            self.start_gate.set()
        if self.release_gate is not None:
            assert self.release_gate.wait(timeout=2)


def _run(*, identity_seed: str | None = None, corpus_seed: str | None = None):
    authority = _authority(identity_seed if corpus_seed is None else corpus_seed)
    request = _request(
        authority.operation_count,
        run_id=(
            "paired-v5-test"
            if identity_seed is None
            else f"paired-v5-evidence-{_sha(identity_seed)[:24]}"
        ),
    )
    coordinator = _Coordinator(authority, request)
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    scopes = _expected_clean_scopes(
        authority=authority,
        admission_commitment_sha256=coordinator.admission,
    )

    class CleanState:
        def prove_empty_scopes(self, **values: object):
            return issuer.issue_authenticated_clean_state(
                admission_commitment_sha256=values["expected_admission_commitment_sha256"],
                run_id_sha256=values["expected_run_id_sha256"],
                authority_commitment_sha256=values["expected_authority_commitment_sha256"],
                scopes=values["expected_scopes"],
            )

    class Durable:
        witness = issuer.issue_authenticated_clean_state(
            admission_commitment_sha256=coordinator.admission,
            run_id_sha256=_sha(request.run_id),
            authority_commitment_sha256=authority.authority_commitment_sha256,
            scopes=scopes,
        )

        def save_original(self, witness: object) -> None:
            self.witness = witness

        def load_original(self, **values: object):
            assert values["expected_admission_commitment_sha256"] == coordinator.admission
            assert values["expected_run_id_sha256"] == _sha(request.run_id)
            assert values["expected_authority_commitment_sha256"] == (
                authority.authority_commitment_sha256
            )
            assert values["expected_evidence_commitment_sha256"] == (
                self.witness.evidence_commitment_sha256
            )
            return self.witness

    return (
        authority,
        coordinator,
        ManagedMem0V5PairedRun(
            authority=authority,
            request=request,
            budget_policy=ManagedMem0V5BudgetPolicy(10_000),
            coordinator=coordinator,
            clean_state_snapshot_port=CleanState(),
            clean_state_verifier=verifier,
            durable_clean_state_port=Durable(),
            storage_witness_verifier=coordinator.storage_verifier,
        ),
    )


@pytest.mark.parametrize(("top_k", "cutoff"), [(50, 50), (200, 50), (200, 200)])
def test_run_projects_top_slices_with_authoritative_time(top_k: int, cutoff: int) -> None:
    authority, coordinator, run = _run()
    run.start()
    evidence = run.search(
        corpus_id=authority.units[0].corpus_id,
        query="What does Alice like?",
        top_k=top_k,
        cutoff=cutoff,
    )
    assert len(evidence) == cutoff
    assert tuple(item.rank for item in evidence) == tuple(range(1, cutoff + 1))
    assert {item.created_at for item in evidence} == {"2024-03-10"}
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_run_admits_clean_state_before_dispatch() -> None:
    _authority_value, coordinator, run = _run()

    clean = run.admit()

    assert run.clean_state_evidence is clean
    assert coordinator.admit_calls == 1
    assert coordinator.dispatch_calls == 0
    run.dispatch()
    assert coordinator.dispatch_calls == 1


@pytest.mark.parametrize(
    "mutate",
    (
        lambda run: object.__setattr__(run._request, "route_sha256", _sha("mutated-route")),
        lambda run: object.__setattr__(
            run._budget_policy,
            "maximum_total_call_count",
            run._budget_policy.maximum_total_call_count + 1,
        ),
        lambda run: object.__setattr__(
            run._corpus_projector,
            "_admission",
            _sha("mutated-admission"),
        ),
        lambda run: run._projector._sources.clear(),
    ),
)
def test_deep_delegate_mutation_fails_before_admit_io(mutate) -> None:
    _authority_value, coordinator, run = _run()
    mutate(run)

    with pytest.raises(ManagedRunError, match="binding differs"):
        run.admit()

    assert coordinator.admit_calls == 0


def test_sealed_run_projects_corpus_storage_evidence() -> None:
    authority, coordinator, run = _run()
    source = authority.units[0]
    coordinator.storage_values = (
        coordinator.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": coordinator.admission,
                    "unit_index": 0,
                    "unit_identity_sha256": source.unit_identity_sha256,
                }
            ),
            unit_identity_sha256=source.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("record-1",),
            source_pairs=((source.source_id, source.source_sha256),),
        ),
    )
    run.start()

    evidence = run.corpus_ingest_evidence(corpus_id=source.corpus_id)

    assert evidence.corpus_id == source.corpus_id
    assert evidence.units[0].created_record_ids == ("record-1",)


def test_transport_coverage_rejects_forged_result_and_consumes_once() -> None:
    authority, coordinator, run = _run()
    source = authority.units[0]
    operation_id = canonical_sha256(
        {
            "admission_commitment_sha256": coordinator.admission,
            "unit_index": 0,
            "unit_identity_sha256": source.unit_identity_sha256,
        }
    )
    coordinator.storage_values = (
        coordinator.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=operation_id,
            unit_identity_sha256=source.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("record-1",),
            source_pairs=((source.source_id, source.source_sha256),),
        ),
    )

    class Capability:
        def consume_complete_transport_coverage(self, **values: object):
            assert values["expected_admission_commitment_sha256"] == coordinator.admission
            assert values["expected_operation_ids"] == (operation_id,)
            return "verified"

    run.start()
    with pytest.raises(ManagedRunError, match="witness differs"):
        run.consume_transport_coverage(Capability())  # type: ignore[arg-type]
    with pytest.raises(ManagedRunError, match="already consumed"):
        run.consume_transport_coverage(Capability())  # type: ignore[arg-type]


def _transport_coverage_for(
    authority: ManagedMem0V5ManifestAuthority,
    request: Mem0OssAdmissionRequest,
):
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    observations = _transport_observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark="locomo",
        run_id_sha256=_sha(request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    return admission, observations, capability


def _set_storage_operation(
    authority: ManagedMem0V5ManifestAuthority,
    coordinator: _Coordinator,
    operation_id_sha256: str,
) -> None:
    source = authority.units[0]
    coordinator.storage_values = (
        coordinator.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=operation_id_sha256,
            unit_identity_sha256=source.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("record-1",),
            source_pairs=((source.source_id, source.source_sha256),),
        ),
    )


def test_transport_coverage_reauthenticates_before_bridge_acceptance() -> None:
    authority, coordinator, run = _run()
    admission, observations, capability = _transport_coverage_for(authority, coordinator.request)
    _set_storage_operation(authority, coordinator, observations[0].operation_id_sha256)
    coverage = capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=admission.commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
    )
    object.__setattr__(coverage, "authority_commitment_sha256", _sha("stale-authority"))
    object.__setattr__(
        coverage,
        "evidence_commitment_sha256",
        canonical_sha256(coverage.commitment_payload()),
    )

    class Capability:
        def consume_complete_transport_coverage(self, **values: object):
            del values
            return coverage

    run.start()
    with pytest.raises(ManagedRunError, match="witness differs"):
        run.consume_transport_coverage(Capability())  # type: ignore[arg-type]


def test_transport_coverage_rejects_authenticated_foreign_authority() -> None:
    authority, coordinator, run = _run()
    local_admission, local_observations, _capability = _transport_coverage_for(
        authority, coordinator.request
    )
    del local_admission
    _set_storage_operation(authority, coordinator, local_observations[0].operation_id_sha256)
    foreign_record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": f"locomo-corpus-{'c' * 64}",
        "thread_id": f"locomo-thread-{'d' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Mallory",
                "session_date": "2024-03-11",
                "text": "Foreign fact.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    foreign_authority = ManagedMem0V5ManifestProjector().project(
        (ManagedRunCase("foreign-case", foreign_record["corpus_id"], foreign_record),),
        current_date="2026-08-07",
    )
    foreign_admission, foreign_observations, foreign_capability = _transport_coverage_for(
        foreign_authority, coordinator.request
    )
    foreign_coverage = foreign_capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=foreign_admission.commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in foreign_observations),
    )

    class Capability:
        def consume_complete_transport_coverage(self, **values: object):
            del values
            return foreign_coverage

    run.start()
    with pytest.raises(ManagedRunError, match="witness differs"):
        run.consume_transport_coverage(Capability())  # type: ignore[arg-type]


@pytest.mark.parametrize("phase", tuple(ManagedMem0V5RunPhase))
def test_restore_routes_each_exact_checkpoint_phase(phase: ManagedMem0V5RunPhase) -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = phase
    result = run.restore()
    assert coordinator.restore_calls == 1
    if phase is ManagedMem0V5RunPhase.ACTIVE:
        assert type(result) is Mem0OssRunSeal
        assert coordinator.dispatch_calls == 1
        assert coordinator.seal_restored_calls == 0
    elif phase is ManagedMem0V5RunPhase.SEALED:
        assert type(result) is Mem0OssRunSeal
        assert coordinator.dispatch_calls == 0
        assert coordinator.seal_restored_calls == 1
    else:
        assert type(result) is Mem0OssTerminalCleanupEvidence
        assert coordinator.dispatch_calls == coordinator.seal_restored_calls == 0
        assert run.cleanup() is result


def test_restore_replays_original_clean_witness_after_storage_is_filled() -> None:
    authority, coordinator, run = _run()
    source = authority.units[0]
    coordinator.storage_values = (
        coordinator.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": coordinator.admission,
                    "unit_index": 0,
                    "unit_identity_sha256": source.unit_identity_sha256,
                }
            ),
            unit_identity_sha256=source.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("record-after-clean-snapshot",),
            source_pairs=((source.source_id, source.source_sha256),),
        ),
    )

    run.restore()

    assert run.clean_state_evidence.scopes[0].residual_record_count == 0


@pytest.mark.parametrize(
    "phase",
    [ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED, ManagedMem0V5RunPhase.TERMINAL],
)
def test_restore_accepts_exact_aborted_terminal_phases(
    phase: ManagedMem0V5RunPhase,
) -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = phase
    coordinator.restore_aborting = True

    result = run.restore()

    assert type(result) is Mem0OssTerminalCleanupEvidence
    assert result.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert result.seal_commitment_sha256 is None
    assert result.operation_root_sha256 is None
    assert coordinator.dispatch_calls == coordinator.seal_restored_calls == 0
    with pytest.raises(ManagedRunError, match="cleanup terminal is not deleted"):
        run.cleanup()


def test_projector_rejects_raw_self_consistent_receipt() -> None:
    authority, coordinator, _run_value = _run()
    projector = ManagedMem0V5PairedEvidenceProjector(
        authority=authority,
        expected_admission_commitment_sha256=coordinator.admission,
    )
    receipt = _receipt(authority, coordinator.admission, query="query", limit=1)
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        projector.project(  # type: ignore[arg-type]
            authenticated_receipt=receipt,
            corpus_id=authority.units[0].corpus_id,
            query="query",
            top_k=1,
            cutoff=1,
        )


def test_projector_rejects_mutated_witness_records_over_limit() -> None:
    authority, coordinator, _run_value = _run()
    witness = _verified_witness(
        authority,
        coordinator.request,
        query="query",
        limit=1,
        receipt_admission=coordinator.admission,
    )
    receipt = witness.receipt
    object.__setattr__(receipt, "records", receipt.records * 2)
    projector = ManagedMem0V5PairedEvidenceProjector(
        authority=authority,
        expected_admission_commitment_sha256=coordinator.admission,
    )

    with pytest.raises(ManagedRunError, match="witness differs"):
        projector.project(
            authenticated_receipt=witness,
            corpus_id=authority.units[0].corpus_id,
            query="query",
            top_k=1,
            cutoff=1,
        )


def test_run_rejects_foreign_admission_receipt() -> None:
    authority, coordinator, run = _run()
    run.start()
    coordinator.admission = _sha("foreign-admission")
    with pytest.raises(ManagedRunError, match="search evidence binding differs"):
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)


def test_projection_fails_closed_for_source_and_manifest_tampering() -> None:
    authority, coordinator, run = _run()
    run.start()
    original = coordinator.search_authenticated_evidence

    def structural_fake(*, corpus_id: str, query: str, limit: int):
        del corpus_id
        return _receipt(
            authority,
            coordinator.admission,
            query=query,
            limit=limit,
        )

    coordinator.search_authenticated_evidence = structural_fake  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)
    coordinator.search_authenticated_evidence = original  # type: ignore[method-assign]

    forged = object.__new__(ManagedMem0V5ManifestAuthority)
    for field in fields(ManagedMem0V5ManifestAuthority):
        value = getattr(authority, field.name)
        if field.name == "units":
            value = (authority.units[0], authority.units[0])
        object.__setattr__(forged, field.name, value)
    with pytest.raises(ManagedRunError, match="manifest authority is invalid"):
        ManagedMem0V5PairedEvidenceProjector(
            authority=forged,
            expected_admission_commitment_sha256=coordinator.admission,
        )
