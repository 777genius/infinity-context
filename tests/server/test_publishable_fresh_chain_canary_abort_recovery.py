"""Crash recovery for the authenticated failed-extraction cleanup seam."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
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
