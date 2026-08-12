"""Provider-free contracts for the concrete fresh-chain provider primitives."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainRetrievalHandoff,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_one_shot import (
    FreshChainMem0AbsenceProof,
    FreshChainMem0OneShotAdapter,
    OperatorLocalHmacMem0OneShotJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.request_renderer import (
    FreshChainOfficialRequestRenderer,
)
from publishable_full_extraction_managed_mem0_v5_test_support import synthetic_manifest

_NAMESPACE_ID = "fresh-chain-provider-primitives"
_NAMESPACE_SHA = hashlib.sha256(b"namespace").hexdigest()
_SOURCE_SHA = hashlib.sha256(b"source").hexdigest()
_JOURNAL_KEY = bytes(range(32))


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _command() -> PublishableExtractionCommand:
    return PublishableExtractionCommand(
        run_id="fresh-chain-one-shot",
        run_identity_commitment_sha256=_sha("run identity"),
        logical_operation_id=_sha("logical operation"),
        ordinal=0,
        admission_commitment_sha256=_sha("admission"),
        operation_id_sha256=_sha("operation"),
        unit_identity_sha256=_sha("unit identity"),
        unit_sha256=_sha("unit"),
        route_sha256=_sha("route"),
        scope_sha256=_sha("scope"),
        request_body_sha256=_sha("request body"),
    )


def _journal(path: Path) -> OperatorLocalHmacMem0OneShotJournal:
    return OperatorLocalHmacMem0OneShotJournal(
        path,
        authentication_key=_JOURNAL_KEY,
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
    )


def test_operator_local_hmac_one_shot_claim_terminal_and_reopen(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    os.chmod(private, 0o700)
    path = private / "mem0-one-shot.json"
    command = _command()
    journal = _journal(path)

    proof = journal.absence(command)
    assert type(proof) is FreshChainMem0AbsenceProof
    absence_sha256 = journal.authenticate_absence(proof, command=command)
    assert type(absence_sha256) is str and len(absence_sha256) == 64

    journal.claim(command)
    assert journal.absence(command) is None
    assert journal.terminal(command) is None
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_mem0_dispatch_duplicate"):
        journal.claim(command)

    envelope = Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=command.admission_commitment_sha256,
        operation_id_sha256=command.operation_id_sha256,
        runtime_receipt={"authenticated": True, "physical_attempt_count": 1},
    )
    journal.record_terminal(command, envelope)
    journal.record_terminal(command, envelope)
    assert journal.terminal(command) == envelope

    reopened = _journal(path)
    assert reopened.absence(command) is None
    assert reopened.terminal(command) == envelope
    assert path.stat().st_mode & 0o777 == 0o600


def test_operator_local_hmac_one_shot_rejects_absence_and_journal_tamper(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    os.chmod(private, 0o700)
    path = private / "mem0-one-shot.json"
    command = _command()
    journal = _journal(path)
    proof = journal.absence(command)
    assert type(proof) is FreshChainMem0AbsenceProof

    object.__setattr__(proof, "absence_hmac_sha256", _sha("forged absence"))
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_mem0_absence_unauthenticated"):
        journal.authenticate_absence(proof, command=command)

    journal.claim(command)
    payload = json.loads(path.read_bytes())
    payload["namespace_id"] = "fresh-chain-tampered"
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
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_mem0_journal_invalid"):
        _journal(path).terminal(command)


def _one_shot_authority():
    authority = synthetic_manifest(profile_id="mem0-locomo-top50-v1", operation_count=1)
    admission = Mem0OssFullRunAdmission(
        request=Mem0OssAdmissionRequest(
            run_id="fresh-chain-one-shot",
            route_sha256=_sha("route"),
            credential_binding_sha256=_sha("credential"),
            model="gpt-5.6-sol",
            reasoning_effort="high",
            service_tier="priority",
            runtime_source_revision="fresh-chain-provider-free-test",
            runtime_source_sha256=_sha("runtime source"),
            runtime_base_sha256=_sha("runtime base"),
            expected_operation_count=1,
        ),
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    unit = authority.units[0]
    command = PublishableExtractionCommand(
        run_id="fresh-chain-one-shot",
        run_identity_commitment_sha256=_sha("run identity"),
        logical_operation_id=_sha("logical operation"),
        ordinal=0,
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_sha("operation"),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256=admission.request.route_sha256,
        scope_sha256=unit.scope_sha256,
        request_body_sha256=_sha("request body"),
    )
    return authority, admission, unit, command


def test_concrete_one_shot_dispatches_once_and_replays_cached_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    authority, admission, unit, command = _one_shot_authority()
    envelope = Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=command.operation_id_sha256,
        runtime_receipt={"authenticated": True},
    )
    calls: list[str] = []

    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "admit",
        lambda *_args, **_kwargs: type(
            "AdmissionReceipt",
            (),
            {
                "accepted": True,
                "admission_commitment_sha256": admission.commitment_sha256,
                "runtime_binding_commitment_sha256": _sha("runtime binding"),
            },
        )(),
    )

    def dispatch(*_args: object, **_kwargs: object) -> Mem0V5RuntimeReceiptEnvelope:
        calls.append("dispatch")
        return envelope

    monkeypatch.setattr(ManagedMem0V5HttpLane, "dispatch", dispatch)
    lane = object.__new__(ManagedMem0V5HttpLane)
    journal_path = private / "mem0-one-shot.json"

    def opened() -> FreshChainMem0OneShotAdapter:
        return FreshChainMem0OneShotAdapter(
            authority=authority,
            admission=admission,
            unit=unit,
            command=command,
            lane=lane,
            expected_runtime_binding_sha256=_sha("runtime binding"),
            journal=_journal(journal_path),
        )

    first = opened()
    absence = first.lookup_outcome(command=command)
    assert type(absence) is FreshChainMem0AbsenceProof
    assert first.dispatch_once(command=command) == envelope
    assert calls == ["dispatch"]
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_mem0_dispatch_duplicate"):
        first.dispatch_once(command=command)

    assert opened().lookup_outcome(command=command) == envelope
    assert calls == ["dispatch"]


def test_concrete_one_shot_recovery_is_status_only_never_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    authority, admission, unit, command = _one_shot_authority()
    envelope = Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=command.operation_id_sha256,
        runtime_receipt={"authenticated": True, "recovered": True},
    )
    journal = _journal(private / "mem0-one-shot.json")
    journal.claim(command)
    calls: list[str] = []
    monkeypatch.setattr(
        ManagedMem0V5HttpLane,
        "admit",
        lambda *_args, **_kwargs: type(
            "AdmissionReceipt",
            (),
            {
                "accepted": True,
                "admission_commitment_sha256": admission.commitment_sha256,
                "runtime_binding_commitment_sha256": _sha("runtime binding"),
            },
        )(),
    )

    def status(*_args: object, **_kwargs: object) -> Mem0V5RuntimeReceiptEnvelope:
        calls.append("status")
        return envelope

    def dispatch(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("recovery must not enter dispatch")

    monkeypatch.setattr(ManagedMem0V5HttpLane, "status", status)
    monkeypatch.setattr(ManagedMem0V5HttpLane, "dispatch", dispatch)
    boundary = FreshChainMem0OneShotAdapter(
        authority=authority,
        admission=admission,
        unit=unit,
        command=command,
        lane=object.__new__(ManagedMem0V5HttpLane),
        expected_runtime_binding_sha256=_sha("runtime binding"),
        journal=journal,
    )

    assert boundary.recover_once(command=command) == envelope
    assert calls == ["status"]


@dataclass
class _InfinityRetrieval:
    memories: tuple[RetrievedMemory, ...]
    calls: int = 0

    def retrieve(self) -> tuple[RetrievedMemory, ...]:
        self.calls += 1
        return self.memories


@dataclass
class _FreshMem0Memories:
    memories: tuple[RetrievedMemory, ...]

    @property
    def retrieved_memories(self) -> tuple[RetrievedMemory, ...]:
        return self.memories


def _case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:1",
        question="Which uniquely named place was discussed?",
        expected_terms=("fresh answer",),
        metadata={"_evaluator_ground_truth": "fresh answer", "category": 1},
    )


def _result(stage: str, ordinal: int, *, output: str = "") -> FreshChainCallResult:
    return FreshChainCallResult(
        stage=stage,  # type: ignore[arg-type]
        ordinal=ordinal,
        intent_sha256=_sha(f"intent {ordinal}"),
        result_sha256=_sha(f"result {ordinal}"),
        physical_receipt_sha256=_sha(f"receipt {ordinal}"),
        receipt_id=f"receipt-{ordinal}",
        usage=FreshChainUsage(1, 1, 2),
        transport_dispatched=True,
        output_text=output,
    )


def _handoff(*, retrieval_authority: str) -> FreshChainRetrievalHandoff:
    return FreshChainRetrievalHandoff(
        extraction_intent_sha256=_sha("intent 0"),
        extraction_result_sha256=_sha("result 0"),
        extraction_receipt_sha256=_sha("receipt 0"),
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_sha("source projection"),
        memory_authority_sha256=_sha("memory authority"),
        retrieval_authority_sha256=retrieval_authority,
        retrieval_material_sha256=_sha("retrieval material"),
        memory_count=1,
    )


def _request(payload: bytes) -> dict[str, object]:
    value = json.loads(payload)
    assert type(value) is dict
    return value


def test_official_renderer_is_lazy_ordered_and_binds_fresh_mem0_retrieval() -> None:
    infinity = _InfinityRetrieval(
        (RetrievedMemory(text="INFINITY_ONLY_EVIDENCE", rank=0, item_id="infinity-1"),)
    )
    mem0 = _FreshMem0Memories(
        (RetrievedMemory(text="FRESH_MEM0_EXTRACTION_EVIDENCE", rank=0, item_id="mem0-1"),)
    )
    extraction_body = b'{"one_fresh_mem0_extraction":true}'
    renderer = FreshChainOfficialRequestRenderer(
        case=_case(),
        extraction_request_body=extraction_body,
        infinity_retrieval=infinity,
        mem0_memories=mem0,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
    )
    extraction = _result("mem0_extraction", 0)
    infinity_answer = _result("infinity_answer", 1, output="infinity answer")
    infinity_judge = _result("infinity_judge", 2, output='{"label":"CORRECT"}')

    assert infinity.calls == 0
    assert (
        renderer.render(
            stage="mem0_extraction",
            prior_results=(),
            retrieval_handoff=None,
        )
        == extraction_body
    )
    assert infinity.calls == 0
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_request_render_order_invalid"):
        renderer.render(
            stage="mem0_extraction",
            prior_results=(extraction,),
            retrieval_handoff=None,
        )

    infinity_body = renderer.render(
        stage="infinity_answer",
        prior_results=(extraction,),
        retrieval_handoff=_handoff(retrieval_authority=_sha("fresh retrieval")),
    )
    infinity_body_replay = renderer.render(
        stage="infinity_answer",
        prior_results=(extraction,),
        retrieval_handoff=_handoff(retrieval_authority=_sha("fresh retrieval")),
    )
    assert infinity.calls == 1
    assert infinity_body_replay == infinity_body
    assert "INFINITY_ONLY_EVIDENCE" in json.dumps(_request(infinity_body))
    assert "FRESH_MEM0_EXTRACTION_EVIDENCE" not in json.dumps(_request(infinity_body))

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_request_retrieval_missing"):
        renderer.render(
            stage="mem0_answer",
            prior_results=(extraction, infinity_answer, infinity_judge),
            retrieval_handoff=None,
        )
    first_handoff = _handoff(retrieval_authority=_sha("fresh retrieval"))
    second_handoff = _handoff(retrieval_authority=_sha("different retrieval"))
    first_mem0_body = renderer.render(
        stage="mem0_answer",
        prior_results=(extraction, infinity_answer, infinity_judge),
        retrieval_handoff=first_handoff,
    )
    second_mem0_body = renderer.render(
        stage="mem0_answer",
        prior_results=(extraction, infinity_answer, infinity_judge),
        retrieval_handoff=second_handoff,
    )
    first_payload = _request(first_mem0_body)
    second_payload = _request(second_mem0_body)
    assert "FRESH_MEM0_EXTRACTION_EVIDENCE" in json.dumps(first_payload)
    assert "INFINITY_ONLY_EVIDENCE" not in json.dumps(first_payload)
    assert first_payload["user"] != second_payload["user"]
