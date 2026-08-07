from __future__ import annotations

import gc
import hashlib
import hmac
import json
import subprocess
import sys
import time
import weakref
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_ingest_receipts as receipt_module,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_lifecycle_adapter as lifecycle_module,
)
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_store import (
    HmacAtomicManagedMem0V5CleanStateStore,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_ingest_receipts import (
    ManagedMem0V5CorpusIngestReceiptSet,
    ManagedMem0V5IngestReceiptError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
    ManagedMem0V5LifecycleAdapterError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedRun,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5RequestBindingV2Context,
    verify_request_binding_v2_payload,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CleanCorpusScope,
    ManagedMem0V5CorpusIngestEvidence,
    ManagedMem0V5CorpusUnitEvidence,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runner_adapter import (
    ManagedMem0V5RetrievalAdapter,
    ManagedMem0V5RetrievalAdapterError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _run as _paired_run,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _set_storage_operation,
)


def _binding(
    *,
    run_id: str = "runner-v5-test",
    profile_id: str = PROFILE_LOCOMO_TOP_50,
) -> ManagedRunnerCompositionBinding:
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    return ManagedRunnerCompositionBinding(
        run_id=run_id,
        profile=profile,
        binding_commitment_sha256="c" * 64,
        deadline=datetime(2026, 8, 8, tzinfo=UTC),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "a" * 64),
            FullComparisonBackendTarget("mem0", "b" * 64),
        ),
        retrieval_top_k=200,
        answer_cutoff=50,
    )


def _authority_and_case() -> tuple[object, ManagedRunCase]:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    case = ManagedRunCase(
        "case-1",
        corpus_id,
        {
            "schema_version": "memory-comparison-managed-corpus.v2",
            "benchmark": "locomo",
            "corpus_id": corpus_id,
            "thread_id": f"locomo-thread-{'b' * 64}",
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
        },
    )
    return (
        ManagedMem0V5ManifestProjector().project((case,), current_date="2026-08-07"),
        case,
    )


def _request(operation_count: int) -> Mem0OssAdmissionRequest:
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    return Mem0OssAdmissionRequest(
        run_id="paired-v5-test",
        route_sha256=digest("route"),
        credential_binding_sha256=digest("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=digest("runtime-source"),
        runtime_base_sha256=digest("runtime-base"),
        expected_operation_count=operation_count,
    )


def test_retrieval_adapter_delegates_exact_profile_and_rejects_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, case = _authority_and_case()
    request = _request(authority.operation_count)
    binding = _binding(run_id=request.run_id)
    paired_run = object.__new__(ManagedMem0V5PairedRun)
    object.__setattr__(paired_run, "_authority", authority)
    object.__setattr__(paired_run, "_request", request)
    calls: list[dict[str, object]] = []
    evidence = (GoldBlindEvidence("record-1", "Alice likes tea.", 1, "2024-03-10"),)

    def search(_self: object, **values: object):
        calls.append(values)
        return evidence

    monkeypatch.setattr(ManagedMem0V5PairedRun, "search", search)
    adapter = ManagedMem0V5RetrievalAdapter(
        composition_binding=binding,
        paired_run=paired_run,
        authority=authority,
        request=request,
    )
    retrieval_authority = adapter.authority_for(
        backend_role="mem0",
        target_identity_sha256="b" * 64,
    )
    result = adapter.retrieve(
        authority=retrieval_authority,
        case=case,
        query=ManagedAnswerCase("case-1", "What does Alice like?", {}),
    )

    assert result.evidence == evidence
    assert calls == [
        {
            "corpus_id": case.corpus_id,
            "query": "What does Alice like?",
            "top_k": 200,
            "cutoff": 50,
        }
    ]
    assert "Alice likes tea." not in repr(dict(result.metadata))
    replacement = object.__new__(ManagedMem0V5PairedRun)
    object.__setattr__(replacement, "_authority", authority)
    object.__setattr__(replacement, "_request", request)
    object.__setattr__(adapter, "_paired_run", replacement)
    with pytest.raises(ManagedMem0V5RetrievalAdapterError, match="composition_invalid"):
        adapter.retrieve(
            authority=retrieval_authority,
            case=case,
            query=ManagedAnswerCase("case-1", "What does Alice like?", {}),
        )
    assert len(calls) == 1


def test_lifecycle_delegate_swap_fails_before_admit_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    request = _request(authority.operation_count)
    binding = _binding(run_id=request.run_id)
    paired_run = object.__new__(ManagedMem0V5PairedRun)
    object.__setattr__(paired_run, "_authority", authority)
    object.__setattr__(paired_run, "_request", request)
    calls: list[str] = []
    monkeypatch.setattr(
        ManagedMem0V5PairedRun,
        "admit",
        lambda _self: calls.append("admit"),
    )

    class CleanupReadback:
        def readback(self, **values: object) -> object:
            return values

    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=binding,
        paired_run=paired_run,
        authority=authority,
        request=request,
        cleanup_readback_capability=CleanupReadback(),
    )
    replacement = object.__new__(ManagedMem0V5PairedRun)
    object.__setattr__(replacement, "_authority", authority)
    object.__setattr__(replacement, "_request", request)
    state = lifecycle_module._STATES[lifecycle]
    object.__setattr__(state, "paired_run", replacement)

    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="composition_invalid"):
        lifecycle.admit()
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "sealed"),
        ("coverage", object()),
        ("receipts", (object(),)),
        ("terminal", object()),
    ],
)
def test_lifecycle_mutable_state_tamper_fails_before_io(
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    request = _request(authority.operation_count)
    paired_run = object.__new__(ManagedMem0V5PairedRun)
    object.__setattr__(paired_run, "_authority", authority)
    object.__setattr__(paired_run, "_request", request)
    calls: list[str] = []
    monkeypatch.setattr(
        ManagedMem0V5PairedRun,
        "admit",
        lambda _self: calls.append("admit"),
    )

    class CleanupReadback:
        def readback(self, **values: object) -> object:
            return values

    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=_binding(run_id=request.run_id),
        paired_run=paired_run,
        authority=authority,
        request=request,
        cleanup_readback_capability=CleanupReadback(),
    )
    object.__setattr__(lifecycle_module._STATES[lifecycle], field, value)

    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="composition_invalid"):
        lifecycle.admit()
    assert calls == []


class _CleanupReadback:
    def readback(self, **values: object) -> object:
        return values


def _real_lifecycle(*, profile_id: str = PROFILE_LOCOMO_TOP_50):
    authority, coordinator, run = _paired_run()
    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=_binding(
            run_id=coordinator.request.run_id,
            profile_id=profile_id,
        ),
        paired_run=run,
        authority=authority,
        request=coordinator.request,
        cleanup_readback_capability=_CleanupReadback(),
    )
    return authority, coordinator, run, lifecycle


def _exact_transport_observations(authority, admission):
    key = b"k" * 32
    observations = []
    for index, unit in enumerate(authority.units):
        operation_id = canonical_sha256(
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "unit_index": index,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )
        context = ManagedMem0V5RequestBindingV2Context.from_authority(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id,
            admission=admission,
        )
        evidence = {
            **context.evidence_payload(),
            "request_body_sha256": hashlib.sha256(f"request-{index}".encode()).hexdigest(),
        }
        unsigned = {
            **evidence,
            "request_binding_evidence_sha256": canonical_sha256(evidence),
        }
        observations.append(
            verify_request_binding_v2_payload(
                payload={
                    **unsigned,
                    "request_binding_hmac_sha256": hmac.new(
                        key,
                        json.dumps(
                            unsigned,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode(),
                        hashlib.sha256,
                    ).hexdigest(),
                },
                context=context,
                hmac_key=key,
            )
        )
    return tuple(observations)


def _seal_lifecycle_with_coverage(*, profile_id: str = PROFILE_LOCOMO_TOP_50):
    authority, coordinator, run, lifecycle = _real_lifecycle(profile_id=profile_id)
    admission = Mem0OssFullRunAdmission(
        request=coordinator.request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    observations = _exact_transport_observations(authority, admission)
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    capability = issue_managed_transport_coverage_capability(
        benchmark=profile.benchmark,
        run_id_sha256=hashlib.sha256(coordinator.request.run_id.encode()).hexdigest(),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    _set_storage_operation(authority, coordinator, observations[0].operation_id_sha256)
    lifecycle.admit()
    lifecycle.dispatch_once()
    lifecycle.consume_transport_coverage(capability)
    return authority, coordinator, run, lifecycle


def test_lifecycle_restore_is_unattempted_only_and_recovers_sealed_run() -> None:
    authority, coordinator, original = _paired_run()
    original.admit()
    original.dispatch()
    restored_run = ManagedMem0V5PairedRun(
        authority=authority,
        request=coordinator.request,
        budget_policy=original._budget_policy,
        coordinator=coordinator,
        clean_state_snapshot_port=original._clean_state_snapshot,
        clean_state_verifier=original._clean_state_verifier,
        durable_clean_state_port=original._durable_clean_state,
        storage_witness_verifier=coordinator.storage_verifier,
    )
    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=_binding(run_id=coordinator.request.run_id),
        paired_run=restored_run,
        authority=authority,
        request=coordinator.request,
        cleanup_readback_capability=_CleanupReadback(),
    )

    restored = lifecycle.restore()

    assert type(restored).__name__ == "Mem0OssRunSeal"
    restore_calls = coordinator.restore_calls
    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="restore_invalid"):
        lifecycle.restore()
    assert coordinator.restore_calls == restore_calls


def test_lifecycle_retries_transient_cleanup_without_redispatch() -> None:
    authority, coordinator, _run, lifecycle = _seal_lifecycle_with_coverage()
    receipt = lifecycle.issue_corpus_receipt(corpus_id=authority.units[0].corpus_id)
    lifecycle.consume_corpus_receipts((receipt,))
    coordinator.cleanup_failures = 1
    dispatch_calls = coordinator.dispatch_calls

    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="cleanup_failed"):
        lifecycle.cleanup_pass1()
    terminal = lifecycle.cleanup_pass1()

    assert terminal is lifecycle.terminal_evidence
    assert coordinator.cleanup_calls == 2
    assert coordinator.dispatch_calls == dispatch_calls


def test_lifecycle_retries_failed_abort_without_readmit_or_redispatch() -> None:
    _authority, coordinator, _run, lifecycle = _real_lifecycle()
    lifecycle.admit()
    coordinator.dispatch_failures = 1
    coordinator.abort_failures = 1

    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="dispatch_failed"):
        lifecycle.dispatch_once()
    admit_calls = coordinator.admit_calls
    dispatch_calls = coordinator.dispatch_calls
    terminal = lifecycle.retry_abort()

    assert terminal is lifecycle.terminal_evidence
    assert coordinator.abort_calls == 2
    assert coordinator.admit_calls == admit_calls
    assert coordinator.dispatch_calls == dispatch_calls


@pytest.mark.parametrize(
    ("profile_id", "coverage_benchmark"),
    [
        (PROFILE_LOCOMO_TOP_50, "longmemeval"),
        (PROFILE_LONGMEMEVAL_TOP_50, "locomo"),
    ],
)
def test_coverage_benchmark_mismatch_fails_before_consumption_or_receipt_io(
    profile_id: str,
    coverage_benchmark: str,
) -> None:
    authority, coordinator, _run, lifecycle = _real_lifecycle(profile_id=profile_id)
    admission = Mem0OssFullRunAdmission(
        request=coordinator.request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    observations = _exact_transport_observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark=coverage_benchmark,
        run_id_sha256=hashlib.sha256(coordinator.request.run_id.encode()).hexdigest(),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    _set_storage_operation(authority, coordinator, observations[0].operation_id_sha256)
    lifecycle.admit()
    lifecycle.dispatch_once()

    with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="benchmark_invalid"):
        lifecycle.consume_transport_coverage(capability)

    assert capability._consumed is False
    assert coordinator.storage_observations


def _corpus_evidence(
    corpus_id: str,
    *,
    run_id: str = "runner-v5-test",
    storage_tag: str = "",
) -> ManagedMem0V5CorpusIngestEvidence:
    unit = ManagedMem0V5CorpusUnitEvidence(
        unit_identity_sha256=canonical_sha256({"unit": corpus_id}),
        source_id=f"source-{corpus_id}",
        source_sha256=canonical_sha256({"source": corpus_id}),
        observation_date="2026-08-07",
        created_record_ids=(f"record-{corpus_id}",),
        storage_evidence_commitment_sha256=canonical_sha256(
            {"storage": corpus_id, "tag": storage_tag}
        ),
    )
    payload = {
        "run_id": run_id,
        "target_identity_sha256": "b" * 64,
        "corpus_id": corpus_id,
        "authority_commitment_sha256": "d" * 64,
        "seal_commitment_sha256": "e" * 64,
        "units": [unit.payload()],
    }
    return ManagedMem0V5CorpusIngestEvidence(
        **{key: value for key, value in payload.items() if key != "units"},
        units=(unit,),
        evidence_commitment_sha256=canonical_sha256(payload),
    )


def _forge_corpus_evidence(
    evidence: ManagedMem0V5CorpusIngestEvidence,
) -> ManagedMem0V5CorpusIngestEvidence:
    forged_unit = replace(
        evidence.units[0],
        storage_evidence_commitment_sha256=canonical_sha256({"forged": evidence.corpus_id}),
    )
    payload = evidence.commitment_payload()
    payload["units"] = [forged_unit.payload(), *[item.payload() for item in evidence.units[1:]]]
    return replace(
        evidence,
        units=(forged_unit, *evidence.units[1:]),
        evidence_commitment_sha256=canonical_sha256(payload),
    )


def test_receipts_are_identity_bound_atomic_one_shot_and_ordered() -> None:
    receipt_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    first = receipt_set.issue(_corpus_evidence("corpus-a"))
    second = receipt_set.issue(_corpus_evidence("corpus-b"))
    foreign_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    foreign_first = foreign_set.issue(_corpus_evidence("corpus-a"))
    foreign_set.issue(_corpus_evidence("corpus-b"))

    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((second, first))
    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((foreign_first, second))
    consumed = receipt_set.consume_exact_ordered((first, second))

    assert tuple(item.corpus_id for item in consumed) == ("corpus-a", "corpus-b")
    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((first, second))


@pytest.mark.parametrize("field", ["evidence", "owner_ref", "ordinal", "phase"])
def test_receipt_state_mutation_fails_closed_before_consumption(field: str) -> None:
    receipt_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    first = receipt_set.issue(_corpus_evidence("corpus-a"))
    second = receipt_set.issue(_corpus_evidence("corpus-b"))
    foreign_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(run_id="foreign-run"),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    state = receipt_module._RECEIPTS[first]
    mutation = {
        "evidence": _forge_corpus_evidence(state.evidence),
        "owner_ref": weakref.ref(foreign_set),
        "ordinal": 1,
        "phase": "consumed",
    }[field]
    object.__setattr__(state, field, mutation)

    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((first, second))


def test_receipt_registry_set_swap_and_cross_run_attacks_fail_closed() -> None:
    receipt_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    first = receipt_set.issue(_corpus_evidence("corpus-a"))
    second = receipt_set.issue(_corpus_evidence("corpus-b"))
    foreign_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(run_id="foreign-run"),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    foreign_first = foreign_set.issue(_corpus_evidence("corpus-a", run_id="foreign-run"))
    foreign_set.issue(_corpus_evidence("corpus-b", run_id="foreign-run"))

    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((foreign_first, second))

    receipt_module._RECEIPTS[first] = receipt_module._RECEIPTS[foreign_first]
    with pytest.raises(ManagedMem0V5IngestReceiptError, match="consume_invalid"):
        receipt_set.consume_exact_ordered((first, second))

    fresh_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    fresh_first = fresh_set.issue(_corpus_evidence("corpus-a"))
    fresh_second = fresh_set.issue(_corpus_evidence("corpus-b"))
    receipt_module._SETS[fresh_set] = receipt_module._SETS[foreign_set]
    with pytest.raises(ManagedMem0V5IngestReceiptError, match="invalid"):
        fresh_set.consume_exact_ordered((fresh_first, fresh_second))


@pytest.mark.parametrize("after_cleanup_failure", [False, True])
def test_consumed_receipt_evidence_mutation_blocks_cleanup_io(
    after_cleanup_failure: bool,
) -> None:
    authority, coordinator, _run, lifecycle = _seal_lifecycle_with_coverage()
    receipt = lifecycle.issue_corpus_receipt(corpus_id=authority.units[0].corpus_id)
    lifecycle.consume_corpus_receipts((receipt,))
    if after_cleanup_failure:
        coordinator.cleanup_failures = 1
        with pytest.raises(ManagedMem0V5LifecycleAdapterError, match="cleanup_failed"):
            lifecycle.cleanup_pass1()
    state = receipt_module._RECEIPTS[receipt]
    object.__setattr__(state, "evidence", _forge_corpus_evidence(state.evidence))
    cleanup_calls = coordinator.cleanup_calls

    with pytest.raises(
        ManagedMem0V5LifecycleAdapterError,
        match="receipt_snapshot_invalid",
    ):
        lifecycle.cleanup_pass1()

    assert coordinator.cleanup_calls == cleanup_calls


def _released_receipt_set_refs(*, consumed: bool) -> tuple[weakref.ReferenceType[object], ...]:
    receipt_set = ManagedMem0V5CorpusIngestReceiptSet(
        composition_binding=_binding(),
        corpus_ids=("corpus-a", "corpus-b"),
        authority_commitment_sha256="d" * 64,
    )
    first = receipt_set.issue(_corpus_evidence("corpus-a"))
    second = receipt_set.issue(_corpus_evidence("corpus-b"))
    references = (weakref.ref(receipt_set), weakref.ref(first), weakref.ref(second))
    if consumed:
        receipt_set.consume_exact_ordered((first, second))
    return references


@pytest.mark.parametrize("consumed", [False, True])
def test_receipt_registries_do_not_root_completed_sets(consumed: bool) -> None:
    gc.collect()
    set_count = len(receipt_module._SETS)
    receipt_count = len(receipt_module._RECEIPTS)

    references = _released_receipt_set_refs(consumed=consumed)
    gc.collect()

    assert all(reference() is None for reference in references)
    assert len(receipt_module._SETS) == set_count
    assert len(receipt_module._RECEIPTS) == receipt_count


def test_repeated_receipt_runs_have_bounded_registry_cleanup() -> None:
    gc.collect()
    set_count = len(receipt_module._SETS)
    receipt_count = len(receipt_module._RECEIPTS)
    references = tuple(
        reference
        for index in range(64)
        for reference in _released_receipt_set_refs(consumed=index % 2 == 0)
    )

    gc.collect()

    assert all(reference() is None for reference in references)
    assert len(receipt_module._SETS) == set_count
    assert len(receipt_module._RECEIPTS) == receipt_count


def test_clean_state_store_reissues_after_restart_and_rejects_tamper(tmp_path) -> None:
    path = (tmp_path / "clean-state.json").resolve()
    key = b"k" * 32
    issuer_a, verifier_a = create_managed_mem0_v5_clean_state_witness_authority()
    scope = ManagedMem0V5CleanCorpusScope(
        corpus_identity_sha256="a" * 64,
        scope_identity_sha256="b" * 64,
        source_scope_count=2,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
    )
    witness = issuer_a.issue_authenticated_clean_state(
        admission_commitment_sha256="c" * 64,
        run_id_sha256="d" * 64,
        authority_commitment_sha256="e" * 64,
        scopes=(scope,),
    )
    HmacAtomicManagedMem0V5CleanStateStore(
        path=path,
        hmac_key=key,
        issuer=issuer_a,
        verifier=verifier_a,
    ).save_original(witness)

    issuer_b, verifier_b = create_managed_mem0_v5_clean_state_witness_authority()
    restarted = HmacAtomicManagedMem0V5CleanStateStore(
        path=path,
        hmac_key=key,
        issuer=issuer_b,
        verifier=verifier_b,
    )
    restored = restarted.load_original(
        expected_admission_commitment_sha256="c" * 64,
        expected_run_id_sha256="d" * 64,
        expected_authority_commitment_sha256="e" * 64,
        expected_evidence_commitment_sha256=witness.evidence_commitment_sha256,
    )
    assert verifier_b.authenticate_clean_state(restored) is restored
    assert restored is not witness

    document = json.loads(path.read_text())
    document["payload"]["run_id_sha256"] = "f" * 64
    path.write_text(json.dumps(document))
    with pytest.raises(ManagedRunError, match="authentication failed"):
        restarted.load_original(
            expected_admission_commitment_sha256="c" * 64,
            expected_run_id_sha256="d" * 64,
            expected_authority_commitment_sha256="e" * 64,
            expected_evidence_commitment_sha256=witness.evidence_commitment_sha256,
        )


def _clean_authority(tag: str):
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    scope = ManagedMem0V5CleanCorpusScope(
        corpus_identity_sha256=hashlib.sha256(f"corpus-{tag}".encode()).hexdigest(),
        scope_identity_sha256=hashlib.sha256(f"scope-{tag}".encode()).hexdigest(),
        source_scope_count=1,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
    )
    witness = issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=hashlib.sha256(f"admission-{tag}".encode()).hexdigest(),
        run_id_sha256=hashlib.sha256(f"run-{tag}".encode()).hexdigest(),
        authority_commitment_sha256=hashlib.sha256(f"authority-{tag}".encode()).hexdigest(),
        scopes=(scope,),
    )
    return issuer, verifier, witness


def test_clean_state_store_multi_instance_compare_under_process_lock(tmp_path) -> None:
    path = (tmp_path / "clean-state-cas.json").resolve()
    key = b"z" * 32
    issuer_a, verifier_a, witness_a = _clean_authority("a")
    issuer_b, verifier_b, witness_b = _clean_authority("b")
    first = HmacAtomicManagedMem0V5CleanStateStore(
        path=path,
        hmac_key=key,
        issuer=issuer_a,
        verifier=verifier_a,
    )
    second = HmacAtomicManagedMem0V5CleanStateStore(
        path=path,
        hmac_key=key,
        issuer=issuer_b,
        verifier=verifier_b,
    )

    first.save_original(witness_a)
    with pytest.raises(ManagedRunError, match="original differs"):
        second.save_original(witness_b)

    document = json.loads(path.read_text())
    assert document["payload"]["run_id_sha256"] == witness_a.run_id_sha256


def test_clean_state_store_subprocess_race_commits_exactly_one_original(tmp_path) -> None:
    path = (tmp_path / "clean-state-race.json").resolve()
    gate = (tmp_path / "race-go").resolve()
    script = r"""
import hashlib
import sys
import time
from pathlib import Path
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_store import (
    HmacAtomicManagedMem0V5CleanStateStore,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CleanCorpusScope,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
)
path, tag, gate = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
scope = ManagedMem0V5CleanCorpusScope(
    digest("corpus-" + tag),
    digest("scope-" + tag),
    1,
    0,
    MEM0_OSS_EMPTY_ROOT_SHA256,
)
witness = issuer.issue_authenticated_clean_state(
    admission_commitment_sha256=digest("admission-" + tag),
    run_id_sha256=digest("run-" + tag),
    authority_commitment_sha256=digest("authority-" + tag),
    scopes=(scope,),
)
store = HmacAtomicManagedMem0V5CleanStateStore(
    path=path,
    hmac_key=b"z" * 32,
    issuer=issuer,
    verifier=verifier,
)
while not gate.exists():
    time.sleep(0.002)
try:
    store.save_original(witness)
except ManagedRunError:
    print("rejected", flush=True)
else:
    print("committed", flush=True)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), tag, str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for tag in ("a", "b")
    ]
    time.sleep(0.05)
    gate.touch()
    results = [process.communicate(timeout=10) for process in processes]

    assert [process.returncode for process in processes] == [0, 0]
    assert sorted(stdout.strip() for stdout, _stderr in results) == ["committed", "rejected"]
    document = json.loads(path.read_text())
    payload = document["payload"]
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    restored = HmacAtomicManagedMem0V5CleanStateStore(
        path=path,
        hmac_key=b"z" * 32,
        issuer=issuer,
        verifier=verifier,
    ).load_original(
        expected_admission_commitment_sha256=payload["admission_commitment_sha256"],
        expected_run_id_sha256=payload["run_id_sha256"],
        expected_authority_commitment_sha256=payload["authority_commitment_sha256"],
        expected_evidence_commitment_sha256=payload["evidence_commitment_sha256"],
    )
    assert verifier.authenticate_clean_state(restored) is restored
