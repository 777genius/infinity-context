"""Provider-free durability tests for fresh Mem0 retrieval and cleanup state."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_evidence import (
    ManagedMem0V5SearchReceipt,
    ManagedMem0V5SearchRecord,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_search_witness import (
    _issue_managed_mem0_v5_authenticated_search_witness,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5CleanupReceipt
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallFailure,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainRetrievalHandoff,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainFailureDisposition,
    provider_disposition_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_lifecycle import (
    OperatorLocalHmacFreshChainLifecycleJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_one_shot import (
    FreshChainMem0RetrievalCleanup,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_retrieval_authority import (
    FreshChainMem0RetrievalMaterial,
    FreshChainMem0RetrievalRecord,
)
from publishable_full_extraction_managed_mem0_v5_test_support import synthetic_manifest

_KEY = bytes(range(32))
_NAMESPACE_ID = "fresh-chain-lifecycle-test"
_NAMESPACE_SHA = hashlib.sha256(b"namespace").hexdigest()
_SOURCE_SHA = hashlib.sha256(b"source").hexdigest()
_SOURCE_PROJECTION_SHA = hashlib.sha256(b"source projection").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _private_path(tmp_path: Path) -> Path:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    os.chmod(private, 0o700)
    return private / "mem0-lifecycle.json"


def _journal(path: Path) -> OperatorLocalHmacFreshChainLifecycleJournal:
    return OperatorLocalHmacFreshChainLifecycleJournal(
        path,
        authentication_key=_KEY,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
    )


def _extraction(*, result_label: str = "result") -> FreshChainCallResult:
    return FreshChainCallResult(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=_sha("intent"),
        result_sha256=_sha(result_label),
        physical_receipt_sha256=_sha("receipt"),
        receipt_id="mem0-extraction-receipt",
        usage=FreshChainUsage(9, 3, 12),
        transport_dispatched=True,
        output_text="authenticated extraction",
        commitments={"operation_id_sha256": _sha("operation")},
    )


def _storage() -> ManagedMem0V5AuthenticatedStorageWitness:
    payload = {
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": _sha("unit identity"),
        "storage_commitment_sha256": _sha("storage"),
        "created_record_ids": ["record-1", "record-2"],
        "source_pairs": [{"source_id": "source-1", "source_sha256": _sha("source one")}],
    }
    return ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=payload["operation_id_sha256"],
        unit_identity_sha256=payload["unit_identity_sha256"],
        storage_commitment_sha256=payload["storage_commitment_sha256"],
        created_record_ids=tuple(payload["created_record_ids"]),
        source_pairs=(("source-1", _sha("source one")),),
        evidence_commitment_sha256=canonical_sha256(payload),
    )


def _retrieval_material(
    memories: tuple[RetrievedMemory, ...] | None = None,
) -> FreshChainMem0RetrievalMaterial:
    selected = _memories() if memories is None else memories
    records = tuple(
        FreshChainMem0RetrievalRecord(
            rank=item.rank,
            record_id=item.item_id,
            memory=item.text,
            memory_sha256=item.metadata["memory_sha256"],
            source_id=item.source_refs[0],
            source_sha256=item.metadata["source_sha256"],
            score=float(item.score),
        )
        for item in selected
    )
    return FreshChainMem0RetrievalMaterial(
        admission_commitment_sha256=_sha("admission"),
        answer_cutoff=50,
        evidence_commitment_sha256=_sha("search evidence"),
        limit=200,
        query_commitment_sha256=_sha("query"),
        records=records,
        result_count=len(records),
        result_root_sha256=_sha("result root"),
    )


def _handoff(
    extraction: FreshChainCallResult,
    *,
    storage: ManagedMem0V5AuthenticatedStorageWitness | None = None,
    retrieval_material: FreshChainMem0RetrievalMaterial | None = None,
) -> FreshChainRetrievalHandoff:
    known_storage = _storage() if storage is None else storage
    known_retrieval = _retrieval_material() if retrieval_material is None else retrieval_material
    memory_authority = canonical_sha256(
        {
            "extraction_receipt_sha256": extraction.physical_receipt_sha256,
            "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            "storage": known_storage.public_payload(),
        }
    )
    retrieval_material_sha256 = canonical_sha256(known_retrieval.payload())
    return FreshChainRetrievalHandoff(
        extraction_intent_sha256=extraction.intent_sha256,
        extraction_result_sha256=extraction.result_sha256,
        extraction_receipt_sha256=extraction.physical_receipt_sha256,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        memory_authority_sha256=memory_authority,
        retrieval_authority_sha256=canonical_sha256(
            {
                "memory_authority_sha256": memory_authority,
                "retrieval_material_sha256": retrieval_material_sha256,
            }
        ),
        retrieval_material_sha256=retrieval_material_sha256,
        memory_count=len(known_retrieval.records),
    )


def _memories() -> tuple[RetrievedMemory, ...]:
    return (
        RetrievedMemory(
            text="first fresh memory",
            rank=0,
            score=0.9,
            item_id="record-1",
            source_refs=("source-1",),
            metadata={
                "memory_sha256": _sha("first fresh memory"),
                "source_sha256": _sha("source one"),
            },
        ),
        RetrievedMemory(
            text="second fresh memory",
            rank=1,
            score=0.8,
            item_id="record-2",
            source_refs=("source-1",),
            metadata={
                "memory_sha256": _sha("second fresh memory"),
                "source_sha256": _sha("source one"),
            },
        ),
    )


def _record_retrieval(
    journal: OperatorLocalHmacFreshChainLifecycleJournal,
) -> FreshChainCallResult:
    extraction = _extraction()
    journal.record_retrieval(
        extraction=extraction,
        handoff=_handoff(extraction),
        memories=_memories(),
        storage=_storage(),
        retrieval_material=_retrieval_material(),
    )
    return extraction


def _cleanup_result() -> FreshChainCleanupResult:
    return FreshChainCleanupResult(
        namespace_commitment_sha256=_NAMESPACE_SHA,
        cleanup_authority_sha256=_sha("cleanup authority"),
        receipt_id="mem0-cleanup-receipt",
        receipt_sha256=_sha("cleanup receipt"),
        outcome_sha256=_sha("cleanup outcome"),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )


def test_retrieval_handoff_and_memories_reopen_without_provider_readback(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path)
    first = _journal(path)
    extraction = _record_retrieval(first)

    reopened = _journal(path)
    state = reopened.retrieval(replace(extraction, transport_dispatched=False))

    assert state is not None
    assert reopened.source_projection_commitment_sha256 == _SOURCE_PROJECTION_SHA
    assert state.extraction == extraction
    assert state.handoff == _handoff(extraction)
    assert state.handoff.source_projection_commitment_sha256 == _SOURCE_PROJECTION_SHA
    assert state.memories == _memories()
    assert state.storage == _storage()
    assert state.retrieval_material == _retrieval_material()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_bytes())["source_projection_commitment_sha256"] == (
        _SOURCE_PROJECTION_SHA
    )
    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_lifecycle_retrieval_replay_conflict",
    ):
        reopened.retrieval(_extraction(result_label="conflicting result"))

    mismatched_projection = OperatorLocalHmacFreshChainLifecycleJournal(
        path,
        authentication_key=_KEY,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_sha("different source projection"),
    )
    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_lifecycle_journal_invalid",
    ):
        mismatched_projection.retrieval(extraction)


def test_handoff_count_tracks_retrieved_memories_not_all_stored_records(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path)
    extraction = _extraction()
    memories = _memories()[:1]
    retrieval_material = _retrieval_material(memories)
    handoff = _handoff(extraction, retrieval_material=retrieval_material)

    persisted = _journal(path).record_retrieval(
        extraction=extraction,
        handoff=handoff,
        memories=memories,
        storage=_storage(),
        retrieval_material=retrieval_material,
    )

    assert len(persisted.storage.created_record_ids) == 2
    assert persisted.handoff.memory_count == len(persisted.memories) == 1


def _capture_authority():
    manifest = synthetic_manifest(profile_id="mem0-locomo-top50-v1", operation_count=1)
    unit = manifest.units[0]
    admission = Mem0OssFullRunAdmission(
        request=Mem0OssAdmissionRequest(
            run_id="fresh-chain-capture-test",
            route_sha256=_sha("route"),
            credential_binding_sha256=_sha("credential"),
            model="gpt-5.6-sol",
            reasoning_effort="high",
            service_tier="priority",
            runtime_source_revision="fresh-chain-test",
            runtime_source_sha256=_sha("runtime source"),
            runtime_base_sha256=_sha("runtime base"),
            expected_operation_count=1,
        ),
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    return manifest, unit, admission


def test_concrete_capture_uses_top_200_selects_50_and_binds_created_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest, unit, admission = _capture_authority()
    record_ids = tuple(f"fresh-record-{index}" for index in range(55))
    storage_base = {
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("capture storage"),
        "created_record_ids": list(record_ids),
        "source_pairs": [{"source_id": unit.source_id, "source_sha256": unit.source_sha256}],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=storage_base["operation_id_sha256"],
        unit_identity_sha256=storage_base["unit_identity_sha256"],
        storage_commitment_sha256=storage_base["storage_commitment_sha256"],
        created_record_ids=record_ids,
        source_pairs=((unit.source_id, unit.source_sha256),),
        evidence_commitment_sha256=canonical_sha256(storage_base),
    )
    records = tuple(
        ManagedMem0V5SearchRecord(
            record_id=record_id,
            memory=f"fresh memory {index}",
            memory_sha256=_sha(f"fresh memory {index}"),
            source_id=unit.source_id,
            source_sha256=unit.source_sha256,
            score=float(100 - index) / 100,
        )
        for index, record_id in enumerate(record_ids)
    )
    question = "What was freshly remembered?"
    result_root = canonical_sha256(
        {"results": [item.public_payload(rank) for rank, item in enumerate(records)]}
    )
    witness = _issue_managed_mem0_v5_authenticated_search_witness(
        ManagedMem0V5SearchReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            corpus_id=unit.corpus_id,
            query_commitment_sha256=canonical_sha256({"query": question}),
            limit=200,
            records=records,
            result_root_sha256=result_root,
            evidence_commitment_sha256=_sha("search evidence"),
        )
    )
    observed_limits: list[int] = []
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "inspect_storage",
        lambda *_args, **_kwargs: storage,
    )

    def search(*_args: object, **kwargs: object):
        observed_limits.append(kwargs["limit"])
        return witness

    monkeypatch.setattr(ManagedMem0V5HttpLane, "search_authenticated", search)
    boundary = FreshChainMem0RetrievalCleanup(
        lane=object.__new__(ManagedMem0V5HttpLane),
        admission=admission,
        manifest=manifest,
        unit=unit,
        operation_id_sha256=_sha("operation"),
        case_question=question,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        journal=_journal(path),
    )
    extraction = _extraction()

    handoff = boundary.capture(
        extraction=extraction,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
    )
    persisted = _journal(path).retrieval(extraction)

    assert observed_limits == [200]
    assert boundary.source_projection_commitment_sha256 == _SOURCE_PROJECTION_SHA
    assert handoff.memory_count == 50
    assert handoff.source_projection_commitment_sha256 == _SOURCE_PROJECTION_SHA
    assert handoff.memory_authority_sha256 == canonical_sha256(
        {
            "extraction_receipt_sha256": extraction.physical_receipt_sha256,
            "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            "storage": storage.public_payload(),
        }
    )
    assert len(boundary.retrieved_memories) == 50
    assert persisted is not None
    assert persisted.retrieval_material.answer_cutoff == 50
    assert persisted.retrieval_material.result_count == 55
    assert {item.record_id for item in persisted.retrieval_material.records}.issubset(
        set(persisted.storage.created_record_ids)
    )


def test_concrete_capture_rejects_foreign_search_record_not_created_by_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest, unit, admission = _capture_authority()
    storage_base = {
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("capture storage"),
        "created_record_ids": ["fresh-record"],
        "source_pairs": [{"source_id": unit.source_id, "source_sha256": unit.source_sha256}],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=storage_base["operation_id_sha256"],
        unit_identity_sha256=storage_base["unit_identity_sha256"],
        storage_commitment_sha256=storage_base["storage_commitment_sha256"],
        created_record_ids=("fresh-record",),
        source_pairs=((unit.source_id, unit.source_sha256),),
        evidence_commitment_sha256=canonical_sha256(storage_base),
    )
    question = "What was freshly remembered?"
    foreign = ManagedMem0V5SearchRecord(
        record_id="foreign-preexisting-record",
        memory="foreign memory",
        memory_sha256=_sha("foreign memory"),
        source_id=unit.source_id,
        source_sha256=unit.source_sha256,
        score=1.0,
    )
    witness = _issue_managed_mem0_v5_authenticated_search_witness(
        ManagedMem0V5SearchReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            corpus_id=unit.corpus_id,
            query_commitment_sha256=canonical_sha256({"query": question}),
            limit=200,
            records=(foreign,),
            result_root_sha256=canonical_sha256({"results": [foreign.public_payload(0)]}),
            evidence_commitment_sha256=_sha("search evidence"),
        )
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "inspect_storage",
        lambda *_args, **_kwargs: storage,
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "search_authenticated",
        lambda *_args, **_kwargs: witness,
    )
    boundary = FreshChainMem0RetrievalCleanup(
        lane=object.__new__(ManagedMem0V5HttpLane),
        admission=admission,
        manifest=manifest,
        unit=unit,
        operation_id_sha256=_sha("operation"),
        case_question=question,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        journal=_journal(path),
    )

    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_retrieval_evidence_invalid",
    ):
        boundary.capture(
            extraction=_extraction(),
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        )


def test_concrete_capture_rejects_contaminated_storage_source_witness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest, unit, admission = _capture_authority()
    source_pairs = (
        (unit.source_id, unit.source_sha256),
        ("foreign-source", _sha("foreign source")),
    )
    storage_base = {
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("contaminated storage"),
        "created_record_ids": ["fresh-record"],
        "source_pairs": [
            {"source_id": source_id, "source_sha256": source_sha256}
            for source_id, source_sha256 in source_pairs
        ],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=storage_base["operation_id_sha256"],
        unit_identity_sha256=storage_base["unit_identity_sha256"],
        storage_commitment_sha256=storage_base["storage_commitment_sha256"],
        created_record_ids=("fresh-record",),
        source_pairs=source_pairs,
        evidence_commitment_sha256=canonical_sha256(storage_base),
    )
    question = "What was freshly remembered?"
    record = ManagedMem0V5SearchRecord(
        record_id="fresh-record",
        memory="fresh memory",
        memory_sha256=_sha("fresh memory"),
        source_id=unit.source_id,
        source_sha256=unit.source_sha256,
        score=1.0,
    )
    witness = _issue_managed_mem0_v5_authenticated_search_witness(
        ManagedMem0V5SearchReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            corpus_id=unit.corpus_id,
            query_commitment_sha256=canonical_sha256({"query": question}),
            limit=200,
            records=(record,),
            result_root_sha256=canonical_sha256({"results": [record.public_payload(0)]}),
            evidence_commitment_sha256=_sha("search evidence"),
        )
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "inspect_storage",
        lambda *_args, **_kwargs: storage,
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "search_authenticated",
        lambda *_args, **_kwargs: witness,
    )
    boundary = FreshChainMem0RetrievalCleanup(
        lane=object.__new__(ManagedMem0V5HttpLane),
        admission=admission,
        manifest=manifest,
        unit=unit,
        operation_id_sha256=_sha("operation"),
        case_question=question,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        journal=_journal(path),
    )

    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_retrieval_evidence_invalid",
    ):
        boundary.capture(
            extraction=_extraction(),
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        )


def test_lifecycle_journal_rejects_authenticated_material_tamper(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    extraction = _record_retrieval(_journal(path))
    payload = json.loads(path.read_bytes())
    payload["retrieval"]["memories"][0]["text"] = "tampered memory"
    path.write_text(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)

    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_lifecycle_journal_invalid",
    ):
        _journal(path).retrieval(extraction)


def test_lifecycle_recomputes_retrieval_authority_after_valid_hmac_tamper(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path)
    extraction = _record_retrieval(_journal(path))
    payload = json.loads(path.read_bytes())
    replacement = "operator-rewritten memory"
    replacement_sha = hashlib.sha256(replacement.encode()).hexdigest()
    payload["retrieval"]["retrieval_material"]["records"][0]["memory"] = replacement
    payload["retrieval"]["retrieval_material"]["records"][0]["memory_sha256"] = replacement_sha
    payload["retrieval"]["memories"][0]["text"] = replacement
    payload["retrieval"]["memories"][0]["metadata"]["memory_sha256"] = replacement_sha
    unsigned = {key: value for key, value in payload.items() if key != "journal_hmac_sha256"}
    encoded_unsigned = json.dumps(
        unsigned,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    payload["journal_hmac_sha256"] = hmac.new(_KEY, encoded_unsigned, hashlib.sha256).hexdigest()
    path.write_text(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)

    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_lifecycle_retrieval_replay_conflict",
    ):
        _journal(path).retrieval(extraction)


def test_cleanup_intent_survives_restart_and_terminal_replay_is_zero_action(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path)
    first = _journal(path)
    _record_retrieval(first)
    intent = {
        "cleanup_context_sha256": _sha("cleanup context"),
        "idempotency_material_sha256": _sha("fixed cleanup idempotency material"),
    }

    assert first.begin_cleanup(intent) is None
    # None after reopen means the exact cleanup is claimed but not durably
    # terminal; the caller recovers it through the same idempotency material.
    recovering = _journal(path)
    assert recovering.begin_cleanup(intent) is None
    terminal = recovering.record_cleanup_terminal(
        cleanup_intent=intent,
        result=_cleanup_result(),
    )

    completed = _journal(path)
    assert completed.begin_cleanup(intent) == terminal
    assert (
        completed.record_cleanup_terminal(
            cleanup_intent=intent,
            result=terminal,
        )
        == terminal
    )
    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_mem0_lifecycle_cleanup_replay_conflict",
    ):
        completed.begin_cleanup({"cleanup_context_sha256": _sha("different")})


def test_known_failed_extraction_abort_cleanup_is_durable_and_replay_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest = synthetic_manifest(profile_id="mem0-locomo-top50-v1", operation_count=1)
    unit = manifest.units[0]
    admission = Mem0OssFullRunAdmission(
        request=Mem0OssAdmissionRequest(
            run_id="fresh-chain-failed-cleanup",
            route_sha256=_sha("route"),
            credential_binding_sha256=_sha("credential"),
            model="gpt-4.1-mini",
            reasoning_effort="high",
            service_tier="default",
            runtime_source_revision="fresh-chain-test",
            runtime_source_sha256=_sha("runtime source"),
            runtime_base_sha256=_sha("runtime base"),
            expected_operation_count=1,
        ),
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    request_sha = _sha("failed request")
    disposition = FreshChainFailureDisposition.PROVIDER_FAILED
    failure = FreshChainCallFailure(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=_sha("failed intent"),
        physical_receipt_sha256=_sha("failed receipt"),
        receipt_id="failed-extraction-receipt",
        usage=FreshChainUsage(4, 2, 6),
        provider_disposition=disposition,
        transport_dispatched=True,
        commitments={
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": _sha("operation"),
            "output_text_sha256": _sha("failed output"),
            "provider_disposition_sha256": provider_disposition_sha256(disposition),
            "request_body_sha256": request_sha,
            "run_identity_commitment_sha256": _sha("run identity"),
            "runtime_binding_commitment_sha256": _sha("runtime binding"),
            "scope_sha256": unit.scope_sha256,
            "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
        },
    )
    calls: list[object] = []

    def cleanup(*_args: object, **kwargs: object) -> Mem0V5CleanupReceipt:
        calls.append(kwargs)
        context = kwargs["context"]
        assert kwargs["seal"] is None
        assert kwargs["aborting"] is True
        return Mem0V5CleanupReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            seal_commitment_sha256=None,
            operation_root_sha256=None,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=0,
            residual_record_count=0,
            residual_root_sha256=hashlib.sha256(b"").hexdigest(),
        )

    monkeypatch.setattr(ManagedMem0V5HttpLane, "cleanup", cleanup)

    def opened() -> FreshChainMem0RetrievalCleanup:
        return FreshChainMem0RetrievalCleanup(
            lane=object.__new__(ManagedMem0V5HttpLane),
            admission=admission,
            manifest=manifest,
            unit=unit,
            operation_id_sha256=_sha("operation"),
            case_question="What failed?",
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            journal=_journal(path),
        )

    result = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        failure=failure,
    )
    replay = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        failure=replace(failure, transport_dispatched=False),
    )

    assert result == replay
    assert len(calls) == 1
    payload = json.loads(path.read_bytes())
    assert payload["retrieval"] is None
    assert payload["cleanup"]["intent"]["failure"]["publishable"] is False


def test_cleanup_restart_uses_exact_idempotent_recovery_then_zero_action_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest = synthetic_manifest(profile_id="mem0-locomo-top50-v1", operation_count=1)
    unit = manifest.units[0]
    admission = Mem0OssFullRunAdmission(
        request=Mem0OssAdmissionRequest(
            run_id="fresh-chain-cleanup-recovery",
            route_sha256=_sha("route"),
            credential_binding_sha256=_sha("credential"),
            model="gpt-4.1-mini",
            reasoning_effort="high",
            service_tier="default",
            runtime_source_revision="fresh-chain-test",
            runtime_source_sha256=_sha("runtime source"),
            runtime_base_sha256=_sha("runtime base"),
            expected_operation_count=1,
        ),
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    extraction = _extraction()
    storage_payload = {
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("storage for cleanup"),
        "created_record_ids": ["record-1"],
        "source_pairs": [{"source_id": unit.source_id, "source_sha256": unit.source_sha256}],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=storage_payload["operation_id_sha256"],
        unit_identity_sha256=storage_payload["unit_identity_sha256"],
        storage_commitment_sha256=storage_payload["storage_commitment_sha256"],
        created_record_ids=("record-1",),
        source_pairs=((unit.source_id, unit.source_sha256),),
        evidence_commitment_sha256=canonical_sha256(storage_payload),
    )
    memory = RetrievedMemory(
        text="fresh cleanup memory",
        rank=0,
        score=1.0,
        item_id="record-1",
        source_refs=(unit.source_id,),
        metadata={
            "memory_sha256": _sha("fresh cleanup memory"),
            "source_sha256": unit.source_sha256,
        },
    )
    retrieval_material = _retrieval_material((memory,))
    handoff = _handoff(
        extraction,
        storage=storage,
        retrieval_material=retrieval_material,
    )
    _journal(path).record_retrieval(
        extraction=extraction,
        handoff=handoff,
        memories=(memory,),
        storage=storage,
        retrieval_material=retrieval_material,
    )

    calls: list[str] = []

    def exact_cleanup(
        _lane: ManagedMem0V5HttpLane,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: object,
        aborting: bool,
        context: object,
    ) -> Mem0V5CleanupReceipt:
        assert aborting is False
        calls.append(
            canonical_sha256(
                {
                    "context": asdict(context),
                    "seal": asdict(seal),
                }
            )
        )
        return Mem0V5CleanupReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            seal_commitment_sha256=seal.commitment_sha256,
            operation_root_sha256=seal.operation_root_sha256,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=1,
            residual_record_count=0,
            residual_root_sha256=hashlib.sha256(b"").hexdigest(),
        )

    monkeypatch.setattr(ManagedMem0V5HttpLane, "cleanup", exact_cleanup)
    lane = object.__new__(ManagedMem0V5HttpLane)

    def opened() -> FreshChainMem0RetrievalCleanup:
        boundary = FreshChainMem0RetrievalCleanup(
            lane=lane,
            admission=admission,
            manifest=manifest,
            unit=unit,
            operation_id_sha256=_sha("operation"),
            case_question="What was freshly remembered?",
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            journal=_journal(path),
        )
        assert (
            boundary.capture(
                extraction=extraction,
                namespace_id=_NAMESPACE_ID,
                namespace_commitment_sha256=_NAMESPACE_SHA,
                source_commitment_sha256=_SOURCE_SHA,
                source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            )
            == handoff
        )
        return boundary

    original_terminal = OperatorLocalHmacFreshChainLifecycleJournal.record_cleanup_terminal

    def crash_before_terminal(*_args: object, **_kwargs: object) -> FreshChainCleanupResult:
        raise RuntimeError("simulated crash after remote cleanup")

    first = opened()
    monkeypatch.setattr(
        OperatorLocalHmacFreshChainLifecycleJournal,
        "record_cleanup_terminal",
        crash_before_terminal,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        first.cleanup(
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
        )
    claimed = json.loads(path.read_bytes())
    assert claimed["cleanup"]["intent"]["source_projection_commitment_sha256"] == (
        _SOURCE_PROJECTION_SHA
    )
    monkeypatch.setattr(
        OperatorLocalHmacFreshChainLifecycleJournal,
        "record_cleanup_terminal",
        original_terminal,
    )

    recovered = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
    )
    assert recovered.deleted is True
    assert len(calls) == 2
    assert calls[0] == calls[1]

    replayed = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
    )
    assert replayed == recovered
    assert len(calls) == 2
