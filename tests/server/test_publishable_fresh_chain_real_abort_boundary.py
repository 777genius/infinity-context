"""Real runtime/concrete Mem0 one-shot post-extraction abort boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainLookupDisposition,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_lifecycle import (
    OperatorLocalHmacFreshChainLifecycleJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_one_shot import (
    FreshChainMem0OneShotAdapter,
    FreshChainMem0RetrievalCleanup,
    OperatorLocalHmacMem0OneShotJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.runtime import (
    FreshChainCanaryRuntimeSession,
)
from test_publishable_fresh_chain_canary_provider_primitives import _one_shot_authority
from test_publishable_fresh_chain_canary_runtime import (
    _EXTRACTION_BODY,
    _NAMESPACE_ID,
    _NAMESPACE_SHA,
    _POLICY_SHA,
    _SOURCE_PROJECTION_SHA,
    _SOURCE_SHA,
    _Renderer,
    _session,
    _sha,
)


@dataclass
class _EnvelopeVerifier:
    def mark_outcome_unknown(self, *, context: RuntimeReceiptVerificationContext) -> None:
        assert context.readback_only is False

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ):
        return self._verify(payload, context)

    def verify_status_readback(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ):
        return self._verify(payload, context)

    def _verify(self, payload: object, context: RuntimeReceiptVerificationContext):
        assert type(payload) is Mem0V5RuntimeReceiptEnvelope
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha("real concrete receipt"),
            sequence=0,
            request_body_sha256=hashlib.sha256(_EXTRACTION_BODY).hexdigest(),
            output_text_sha256=_sha("real extraction output"),
            runtime_binding_commitment_sha256=_sha("real runtime binding"),
            disposition=Mem0OssReceiptDisposition.COMPLETED,
            extraction_calls=1,
            retry_count=0,
            request_tokens=8,
            response_tokens=3,
        )


def test_real_runtime_concrete_one_shot_abort_and_zero_call_terminal_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private-real"
    private.mkdir(mode=0o700)
    authority, admission, unit, _unused = _one_shot_authority()
    command = PublishableExtractionCommand(
        run_id=_NAMESPACE_ID,
        run_identity_commitment_sha256=canonical_sha256(
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "namespace_commitment_sha256": _NAMESPACE_SHA,
                "namespace_id": _NAMESPACE_ID,
                "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            }
        ),
        logical_operation_id=canonical_sha256(
            {
                "namespace_commitment_sha256": _NAMESPACE_SHA,
                "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
                "stage": "mem0_extraction",
            }
        ),
        ordinal=0,
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_sha("real operation"),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256=admission.request.route_sha256,
        scope_sha256=unit.scope_sha256,
        request_body_sha256=hashlib.sha256(_EXTRACTION_BODY).hexdigest(),
    )
    storage_payload = {
        "operation_id_sha256": command.operation_id_sha256,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "storage_commitment_sha256": _sha("real storage"),
        "created_record_ids": ["real-record"],
        "source_pairs": [{"source_id": unit.source_id, "source_sha256": unit.source_sha256}],
    }
    storage = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=command.operation_id_sha256,
        unit_identity_sha256=unit.unit_identity_sha256,
        storage_commitment_sha256=storage_payload["storage_commitment_sha256"],
        created_record_ids=("real-record",),
        source_pairs=((unit.source_id, unit.source_sha256),),
        evidence_commitment_sha256=canonical_sha256(storage_payload),
    )
    calls: list[str] = []
    envelope = Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=command.operation_id_sha256,
        runtime_receipt={"authenticated": True},
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "admit",
        lambda *_a, **_k: type(
            "Admission",
            (),
            {
                "accepted": True,
                "admission_commitment_sha256": admission.commitment_sha256,
                "runtime_binding_commitment_sha256": _sha("real runtime binding"),
            },
        )(),
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "dispatch",
        lambda *_a, **_k: (calls.append("dispatch"), envelope)[1],
    )
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "inspect_storage",
        lambda *_a, **_k: (calls.append("inspect"), storage)[1],
    )

    def cleanup(*_args: object, **kwargs: object) -> Mem0V5CleanupReceipt:
        calls.append("cleanup")
        context = kwargs["context"]
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
    lane = object.__new__(ManagedMem0V5HttpLane)
    one_shot_path = private / "one-shot.json"
    lifecycle_path = private / "lifecycle.json"
    bridge_root = tmp_path / "bridge-donor"
    bridge_root.mkdir(mode=0o700)
    donor, *_donor_items = _session(bridge_root)
    bridge_journal = _donor_items[2]

    def opened() -> FreshChainCanaryRuntimeSession:
        one_shot = FreshChainMem0OneShotAdapter(
            authority=authority,
            admission=admission,
            unit=unit,
            command=command,
            lane=lane,
            expected_runtime_binding_sha256=_sha("real runtime binding"),
            journal=OperatorLocalHmacMem0OneShotJournal(
                one_shot_path,
                authentication_key=hashlib.sha256(b"one-shot").digest(),
                namespace_id=_NAMESPACE_ID,
                namespace_commitment_sha256=_NAMESPACE_SHA,
            ),
        )
        cleanup_boundary = FreshChainMem0RetrievalCleanup(
            lane=lane,
            admission=admission,
            manifest=authority,
            unit=unit,
            operation_id_sha256=command.operation_id_sha256,
            case_question="unused",
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            journal=OperatorLocalHmacFreshChainLifecycleJournal(
                lifecycle_path,
                authentication_key=hashlib.sha256(b"lifecycle").digest(),
                namespace_id=_NAMESPACE_ID,
                namespace_commitment_sha256=_NAMESPACE_SHA,
                source_commitment_sha256=_SOURCE_SHA,
                source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            ),
        )
        return FreshChainCanaryRuntimeSession(
            namespace_id=_NAMESPACE_ID,
            namespace_commitment_sha256=_NAMESPACE_SHA,
            source_commitment_sha256=_SOURCE_SHA,
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
            extraction_boundary=one_shot,
            extraction_command=command,
            extraction_receipt_verifier=_EnvelopeVerifier(),
            extraction_absence=one_shot,
            bridge=donor._bridge,
            renderer=_Renderer(_EXTRACTION_BODY, common_condition_policy_sha256=_POLICY_SHA),
            retrieval=cleanup_boundary,
            cleanup=cleanup_boundary,
        )

    first = opened()
    intent = first.prepare_call(stage="mem0_extraction", prior_results=(), retrieval_handoff=None)
    assert first.lookup(intent).disposition is FreshChainLookupDisposition.AUTHENTICATED_ABSENT
    first.dispatch(intent)
    assert first.abort_after_extraction().deleted
    before_replay = tuple(calls)

    assert opened().abort_after_extraction().deleted
    assert tuple(calls) == before_replay == ("dispatch", "inspect", "cleanup")
    bridge_journal.close()
