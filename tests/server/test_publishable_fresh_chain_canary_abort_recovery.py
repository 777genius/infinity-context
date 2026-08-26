"""Crash recovery for the authenticated failed-extraction cleanup seam."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallFailure,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainFailureDisposition,
    provider_disposition_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_one_shot import (
    FreshChainMem0RetrievalCleanup,
)
from test_publishable_fresh_chain_canary_mem0_lifecycle import (
    _NAMESPACE_ID,
    _NAMESPACE_SHA,
    _SOURCE_PROJECTION_SHA,
    _SOURCE_SHA,
    _capture_authority,
    _extraction,
    _journal,
    _private_path,
    _sha,
)


def test_abort_cleanup_inflight_restart_reuses_intent_then_replays_zero_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest, unit, admission = _capture_authority()
    operation_id = _sha("operation")
    disposition = FreshChainFailureDisposition.PROVIDER_FAILED
    failure = FreshChainCallFailure(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=_sha("abort intent"),
        physical_receipt_sha256=_sha("abort receipt"),
        receipt_id="abort-receipt",
        usage=FreshChainUsage(5, 2, 7),
        provider_disposition=disposition,
        transport_dispatched=True,
        commitments={
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id,
            "output_text_sha256": _sha("abort output"),
            "provider_disposition_sha256": provider_disposition_sha256(disposition),
            "request_body_sha256": _sha("abort request"),
            "run_identity_commitment_sha256": _sha("abort run identity"),
            "runtime_binding_commitment_sha256": _sha("abort binding"),
            "scope_sha256": unit.scope_sha256,
            "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
        },
    )
    contexts: list[dict[str, object]] = []

    def cleanup(*_args: object, **kwargs: object) -> Mem0V5CleanupReceipt:
        context = kwargs["context"]
        contexts.append(asdict(context))
        if len(contexts) == 1:
            raise RuntimeError("crash after durable cleanup claim")
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
            operation_id_sha256=operation_id,
            case_question="What failed?",
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            journal=_journal(path),
        )

    with pytest.raises(RuntimeError, match="durable cleanup claim"):
        opened().cleanup(
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            failure=failure,
        )
    result = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        failure=replace(failure, transport_dispatched=False),
    )
    replay = opened().cleanup(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        failure=replace(failure, transport_dispatched=False),
    )

    assert replay == result
    assert len(contexts) == 2
    assert contexts[0] == contexts[1]


def test_successful_extraction_abort_before_retrieval_is_durable_and_restartable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    manifest, unit, admission = _capture_authority()
    operation_id = _sha("operation")
    storage_payload = {
        "operation_id_sha256": operation_id,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("abort storage"),
        "created_record_ids": ["fresh-record-1"],
        "source_pairs": [{"source_id": unit.source_id, "source_sha256": unit.source_sha256}],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=operation_id,
        unit_identity_sha256=unit.unit_identity_sha256,
        storage_commitment_sha256=storage_payload["storage_commitment_sha256"],
        created_record_ids=("fresh-record-1",),
        source_pairs=((unit.source_id, unit.source_sha256),),
        evidence_commitment_sha256=canonical_sha256(storage_payload),
    )
    extraction = replace(
        _extraction(),
        commitments={
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id,
            "scope_sha256": unit.scope_sha256,
            "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
        },
    )
    cleanup_calls: list[object] = []
    monkeypatch.setattr(ManagedMem0V5HttpLane, "inspect_storage", lambda *_a, **_k: storage)

    def cleanup(*_args: object, **kwargs: object) -> Mem0V5CleanupReceipt:
        cleanup_calls.append(kwargs["context"])
        if len(cleanup_calls) == 1:
            raise RuntimeError("cleanup interrupted")
        context = kwargs["context"]
        assert kwargs["aborting"] is True
        assert kwargs["seal"] is None
        return Mem0V5CleanupReceipt(
            admission_commitment_sha256=admission.commitment_sha256,
            seal_commitment_sha256=None,
            operation_root_sha256=None,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=1,
            residual_record_count=0,
            residual_root_sha256=hashlib.sha256(b"").hexdigest(),
        )

    monkeypatch.setattr(ManagedMem0V5HttpLane, "cleanup", cleanup)
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "search_authenticated",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retrieval must not run")),
    )

    def opened() -> FreshChainMem0RetrievalCleanup:
        return FreshChainMem0RetrievalCleanup(
            lane=object.__new__(ManagedMem0V5HttpLane),
            admission=admission,
            manifest=manifest,
            unit=unit,
            operation_id_sha256=operation_id,
            case_question="unused",
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            journal=_journal(path),
        )

    with pytest.raises(RuntimeError, match="interrupted"):
        opened().abort_after_extraction(
            extraction=extraction,
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
        )
    terminal = opened().abort_after_extraction(
        extraction=replace(extraction, transport_dispatched=False),
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
    )
    replay = opened().abort_after_extraction(
        extraction=replace(extraction, transport_dispatched=False),
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
    )

    assert replay == terminal
    assert len(cleanup_calls) == 2
