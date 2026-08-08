from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_app import _receipt
from test_mem0_storage_cleanup import FakeMem0Backend

from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.composition import (
    SealedInputManifest,
    V5AdapterService,
    _atomic_private_write,
)
from mem0_oss_adapter_v5.domain import (
    ExtractionMemory,
    RuntimeExtractionResult,
    _issue_sanitized_runtime_receipt,
    canonical_json_bytes,
    canonical_sha256,
)
from mem0_oss_adapter_v5.http_models import (
    AdmitRequest,
    CleanupRequest,
    DispatchRequest,
    RuntimeReceiptEnvelope,
    StatusRequest,
)
from mem0_oss_adapter_v5.mem0_storage import Mem0StorageAdapter, independent_snapshot
from mem0_oss_adapter_v5.runtime_attestation import V5RuntimeAuthorityProjection
from mem0_oss_adapter_v5.source_authority import _issue_verified_source_authority
from mem0_oss_adapter_v5.state_sqlite import OperationState, SqliteOperationState
from mem0_oss_adapter_v5.subscription_runtime import SUBSCRIPTION_RUNTIME_ROUTE_SHA256


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Authority:
    def verify(self, **kwargs: object) -> str:
        return canonical_sha256(kwargs["receipt"])


class _Runtime:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, request, intent) -> RuntimeExtractionResult:
        self.calls += 1
        payload = _receipt(request.request_body_sha256)
        receipt = _issue_sanitized_runtime_receipt(
            payload,
            verified_receipt_sha256=canonical_sha256(payload),
        )
        return RuntimeExtractionResult(
            intent=intent,
            memories=(ExtractionMemory("0", "Alice likes tea.", "user", ()),),
            receipt=receipt,
            output_text_sha256=_sha("output"),
        )


class _Storage:
    def __init__(self) -> None:
        self.persisted = False
        self.verify_calls = 0

    def verify_exact(self, **_kwargs):
        self.verify_calls += 1
        if not self.persisted:
            raise RuntimeError("empty")
        return SimpleNamespace(commitment_sha256=_sha("storage"))

    def persist(self, **_kwargs):
        if self.persisted:
            raise RuntimeError("duplicate")
        self.persisted = True
        return SimpleNamespace(commitment_sha256=_sha("storage"))


@dataclass
class _Context:
    state: SqliteOperationState
    runtime: _Runtime
    storage: _Storage
    service: V5AdapterService
    admission: AdmitRequest
    dispatch: DispatchRequest
    unit_identity: str


def _context(tmp_path) -> _Context:
    unit = {
        "sequence": 0,
        "unit_identity_sha256": _sha("identity"),
        "unit_sha256": _sha("unit"),
        "scope_sha256": _sha("scope"),
        "corpus_id": "corpus-1",
        "source_id": "source-1",
        "observation_date": "2024-03-10",
        "source_messages": [{"role": "user", "content": "Alice likes tea."}],
    }
    root = canonical_sha256(
        {
            "units": [
                {
                    "unit_identity_sha256": unit["unit_identity_sha256"],
                    "unit_sha256": unit["unit_sha256"],
                    "scope_sha256": unit["scope_sha256"],
                }
            ]
        }
    )
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.sealed-input.v1",
        "ingestion_manifest_sha256": _sha("manifest"),
        "ingestion_root_sha256": root,
        "current_date": "2026-08-06",
        "units": [unit],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)}))
    os.chmod(path, 0o400)
    manifest = SealedInputManifest(path)
    state = SqliteOperationState(tmp_path / "state.sqlite3", hmac_key=b"h" * 32)
    runtime = _Runtime()
    storage = _Storage()
    service = _service(tmp_path, manifest, state, runtime, storage)
    admission_sha = _sha("admission")
    admission = AdmitRequest(
        admission_commitment_sha256=admission_sha,
        ingestion_manifest_sha256=_sha("manifest"),
        ingestion_root_sha256=root,
        expected_operation_count=1,
        route_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    )
    service.admit(admission, idempotency_key=_sha("admit"))
    request = service._extraction_request(manifest.units[0])
    operation_id = canonical_sha256(
        {
            "admission_commitment_sha256": admission_sha,
            "unit_index": 0,
            "unit_identity_sha256": unit["unit_identity_sha256"],
        }
    )
    dispatch = DispatchRequest(
        admission_commitment_sha256=admission_sha,
        operation_id_sha256=operation_id,
        unit_identity_sha256=unit["unit_identity_sha256"],
        unit_sha256=unit["unit_sha256"],
        scope_sha256=unit["scope_sha256"],
        request_body_sha256=request.request_body_sha256,
        sequence=0,
    )
    return _Context(
        state, runtime, storage, service, admission, dispatch, unit["unit_identity_sha256"]
    )


def _service(tmp_path, manifest, state, runtime, storage) -> V5AdapterService:
    source_authority = _issue_verified_source_authority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        manifest_sha256=_sha("source-manifest"),
        closure_sha256=_sha("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_sha("phase-release"),
    )
    runtime_authority = V5RuntimeAuthorityProjection.issue(
        source_authority=source_authority,
        subscription_runtime_binding_commitment_sha256=_sha("runtime-binding"),
        runtime_source_sha256=_sha("runtime-source"),
        runtime_route_binding_sha256=_sha("runtime-route"),
        runtime_transport_origin_sha256=_sha("runtime-transport-origin"),
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base"),
    )
    return V5AdapterService(
        manifest=manifest,
        state=state,
        runtime=runtime,
        receipt_authority=_Authority(),
        storage=storage,
        receipt_directory=tmp_path / "receipts",
        result_hmac_key=b"r" * 32,
        runtime_authority=runtime_authority,
    )


def _provider_result(context: _Context) -> RuntimeExtractionResult:
    unit = context.service._manifest.units[0]
    request = context.service._extraction_request(unit)
    intent = context.service._bound_unit(context.dispatch)
    del intent
    from mem0_oss_adapter_v5.composition import _intent

    return context.runtime.extract(request, _intent(context.dispatch))


def test_crash_after_durable_file_resumes_without_second_provider_call(tmp_path) -> None:
    context = _context(tmp_path)
    context.state.reserve(context.unit_identity)
    context.state.mark_dispatched(context.unit_identity)
    result = _provider_result(context)
    context.service._write_result(result)
    context.service.admit(context.admission, idempotency_key=_sha("resume"))
    assert context.runtime.calls == 1
    assert context.state.get(context.unit_identity).state is OperationState.COMMITTED
    assert context.storage.persisted is True
    context.state.close()


def test_receipt_durable_and_storage_verified_cuts_resume_locally(tmp_path) -> None:
    context = _context(tmp_path)
    context.state.reserve(context.unit_identity)
    context.state.mark_dispatched(context.unit_identity)
    result = _provider_result(context)
    context.service._write_result(result)
    context.state.mark_receipt_durable(context.unit_identity, result.receipt.receipt_sha256)
    context.service.admit(context.admission, idempotency_key=_sha("receipt-resume"))
    assert context.runtime.calls == 1
    assert context.state.get(context.unit_identity).state is OperationState.COMMITTED
    assert context.storage.verify_calls >= 2
    context.state.close()


def test_storage_verified_cut_requires_independent_storage_proof_before_commit(tmp_path) -> None:
    context = _context(tmp_path)
    context.state.reserve(context.unit_identity)
    context.state.mark_dispatched(context.unit_identity)
    result = _provider_result(context)
    context.service._write_result(result)
    context.state.mark_receipt_durable(context.unit_identity, result.receipt.receipt_sha256)
    context.storage.persisted = True
    context.state.mark_storage_verified(context.unit_identity, _sha("storage"))
    before = context.storage.verify_calls
    context.service.admit(context.admission, idempotency_key=_sha("storage-resume"))
    assert context.runtime.calls == 1
    assert context.storage.verify_calls == before + 1
    assert context.state.get(context.unit_identity).state is OperationState.COMMITTED
    context.state.close()


def test_tampered_durable_result_fails_before_state_promotion(tmp_path) -> None:
    context = _context(tmp_path)
    context.state.reserve(context.unit_identity)
    context.state.mark_dispatched(context.unit_identity)
    result = _provider_result(context)
    context.service._write_result(result)
    path = context.service._result_path(context.dispatch.operation_id_sha256)
    payload = json.loads(path.read_text())
    payload["runtime_receipt"]["usage"]["total_tokens"] = 999
    path.write_text(json.dumps(payload))
    os.chmod(path, 0o600)
    with pytest.raises(AdapterServiceError, match="status_unavailable"):
        context.service.admit(context.admission, idempotency_key=_sha("tampered"))
    assert context.runtime.calls == 1
    assert context.state.get(context.unit_identity).state is OperationState.DISPATCHED
    context.state.close()


def test_nested_receipt_rejects_deep_extra_and_type_impostors() -> None:
    payload = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
        "runtime_receipt": _receipt(),
    }
    payload["runtime_receipt"]["metadata"]["runtime_selection"]["private_prompt"] = "secret"
    with pytest.raises(ValidationError):
        RuntimeReceiptEnvelope.model_validate(payload)
    payload = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
        "runtime_receipt": _receipt(),
    }
    payload["runtime_receipt"]["usage"]["prompt_tokens"] = True
    with pytest.raises(ValidationError):
        RuntimeReceiptEnvelope.model_validate(payload)


def _cleanup_request(context: _Context, *, aborting: bool) -> CleanupRequest:
    expected = context.service._run_commitments(aborting)
    return CleanupRequest(
        admission_commitment_sha256=context.admission.admission_commitment_sha256,
        seal_commitment_sha256=expected["seal_commitment_sha256"],
        operation_root_sha256=expected["operation_root_sha256"],
        operation_inventory_root_sha256=expected["operation_inventory_root_sha256"],
        expected_operation_count=1,
        aborting=aborting,
    )


def test_committed_cleanup_and_terminal_replay_use_sealed_evidence(tmp_path) -> None:
    context = _context(tmp_path)
    backend = FakeMem0Backend()
    context.service._storage = Mem0StorageAdapter(backend)
    context.service.dispatch(context.dispatch, idempotency_key=_sha("dispatch"))
    unit = context.service._manifest.units[0]
    before = independent_snapshot(backend, scope=context.service._scope(unit))
    request = _cleanup_request(context, aborting=False)
    first = context.service.cleanup(request, idempotency_key=_sha("cleanup-1"))
    evidence_path = context.service._cleanup_evidence_path(unit)
    v2_payload = json.loads(evidence_path.read_bytes())
    assert v2_payload["schema_version"] == "mem0-oss-adapter-v5.cleanup-evidence.v2"
    assert b"Alice likes tea." not in evidence_path.read_bytes()

    # Authenticated v1 evidence remains readable, but terminal replay must scrub it to v2.
    legacy = {
        "schema_version": "mem0-oss-adapter-v5.cleanup-evidence.v1",
        "unit_identity_sha256": unit.unit_identity_sha256,
        "sealed_before": asdict(before),
        "runtime_receipt_sha256": v2_payload["runtime_receipt_sha256"],
        "cleanup_receipt": v2_payload["cleanup_receipt"],
    }
    legacy["evidence_hmac_sha256"] = hmac.new(
        b"r" * 32, canonical_json_bytes(legacy), hashlib.sha256
    ).hexdigest()
    _atomic_private_write(evidence_path, canonical_json_bytes(legacy))
    assert b"Alice likes tea." in evidence_path.read_bytes()
    second = context.service.cleanup(request, idempotency_key=_sha("cleanup-2"))
    migrated = evidence_path.read_bytes()
    assert b"cleanup-evidence.v2" in migrated
    assert b"Alice likes tea." not in migrated
    assert first == second
    assert first.deleted_operation_count == 1
    assert first.residual_record_count == 0
    assert context.state.get(context.unit_identity).state is OperationState.CLEANED
    assert backend.vectors == {}
    with pytest.raises(AdapterServiceError) as terminal:
        context.service.status(
            StatusRequest(
                admission_commitment_sha256=context.admission.admission_commitment_sha256,
                operation_id_sha256=context.dispatch.operation_id_sha256,
            ),
            idempotency_key=_sha("terminal-status"),
        )
    assert terminal.value.status_code == 410
    assert str(terminal.value) == "operation_cleaned"
    context.state.close()


def test_abort_cleanup_seals_admitted_operation_and_replays(tmp_path) -> None:
    context = _context(tmp_path)
    context.service._storage = Mem0StorageAdapter(FakeMem0Backend())
    request = _cleanup_request(context, aborting=True)
    context.service.cleanup(request, idempotency_key=_sha("abort-1"))
    context.service.cleanup(request, idempotency_key=_sha("abort-2"))
    record = context.state.get(context.unit_identity)
    assert record.state is OperationState.ABORT_CLEANED
    assert record.abort_origin_state is OperationState.ADMITTED
    context.state.close()


def test_initialized_admission_rejects_lost_row_without_provider_retry(tmp_path) -> None:
    context = _context(tmp_path)
    context.service.dispatch(context.dispatch, idempotency_key=_sha("dispatch"))
    assert context.runtime.calls == 1
    context.state._connection.execute(
        "DELETE FROM operations_v2 WHERE unit_identity_sha256 = ?",
        (context.unit_identity,),
    )
    with pytest.raises(AdapterServiceError, match="admission_conflict"):
        context.service.admit(context.admission, idempotency_key=_sha("lost-row"))
    assert context.runtime.calls == 1
    context.state.close()


def test_admission_evidence_tamper_fails_closed(tmp_path) -> None:
    context = _context(tmp_path)
    path = context.service._receipt_directory / "admission.json"
    payload = json.loads(path.read_text())
    payload["inventory"][0]["unit_sha256"] = _sha("tampered")
    path.write_text(json.dumps(payload))
    os.chmod(path, 0o600)
    with pytest.raises(AdapterServiceError, match="admission_conflict"):
        context.service.admit(context.admission, idempotency_key=_sha("tampered-admission"))
    assert context.runtime.calls == 0
    context.state.close()


def test_cleanup_rejects_self_attested_seal_and_inventory(tmp_path) -> None:
    context = _context(tmp_path)
    backend = FakeMem0Backend()
    context.service._storage = Mem0StorageAdapter(backend)
    context.service.dispatch(context.dispatch, idempotency_key=_sha("dispatch"))
    valid = _cleanup_request(context, aborting=False)
    tampered_seal = valid.model_copy(update={"seal_commitment_sha256": _sha("fake-seal")})
    with pytest.raises(AdapterServiceError, match="cleanup_conflict"):
        context.service.cleanup(tampered_seal, idempotency_key=_sha("fake-seal"))
    tampered_inventory = valid.model_copy(
        update={"operation_inventory_root_sha256": _sha("fake-inventory")}
    )
    with pytest.raises(AdapterServiceError, match="cleanup_conflict"):
        context.service.cleanup(tampered_inventory, idempotency_key=_sha("fake-inventory"))
    assert backend.vectors
    context.state.close()


def test_abort_inventory_matches_only_operations_the_runner_began(tmp_path) -> None:
    context = _context(tmp_path)
    early = context.service._run_commitments(True)
    assert early["operation_inventory_root_sha256"] == canonical_sha256({"operations": []})
    context.state.reserve(context.unit_identity)
    unit = context.service._manifest.units[0]
    operation = {
        "operation_id_sha256": context.dispatch.operation_id_sha256,
        "unit_index": 0,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "unit_sha256": unit.unit_sha256,
        "scope_sha256": unit.scope_sha256,
        "provider_receipt_sha256": None,
        "disposition": None,
        "extraction_calls": 0,
        "retry_count": 0,
        "request_tokens": 0,
        "response_tokens": 0,
        "stored_identity_sha256": None,
        "stored_record_count": 0,
        "state": "reserved",
        "commitment_sha256": None,
    }
    partial = context.service._run_commitments(True)
    assert partial["operation_inventory_root_sha256"] == canonical_sha256(
        {"operations": [operation]}
    )
    context.state.mark_dispatched(context.unit_identity)
    context.state.recover()
    operation["state"] = "reconciliation_required"
    unknown = context.service._run_commitments(True)
    assert unknown["operation_inventory_root_sha256"] == canonical_sha256(
        {"operations": [operation]}
    )
    context.state.close()


def test_atomic_result_write_fsyncs_file_and_parent_directory(tmp_path, monkeypatch) -> None:
    calls = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    _atomic_private_write(tmp_path / "result.json", b"{}")
    assert len(calls) == 2


def test_direct_abort_recovers_lost_dispatch_before_inventory_binding(tmp_path) -> None:
    context = _context(tmp_path)
    context.service._storage = Mem0StorageAdapter(FakeMem0Backend())
    context.state.reserve(context.unit_identity)
    context.state.mark_dispatched(context.unit_identity)
    unit = context.service._manifest.units[0]
    operation = {
        "operation_id_sha256": context.dispatch.operation_id_sha256,
        "unit_index": 0,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "unit_sha256": unit.unit_sha256,
        "scope_sha256": unit.scope_sha256,
        "provider_receipt_sha256": None,
        "disposition": None,
        "extraction_calls": 0,
        "retry_count": 0,
        "request_tokens": 0,
        "response_tokens": 0,
        "stored_identity_sha256": None,
        "stored_record_count": 0,
        "state": "reconciliation_required",
        "commitment_sha256": None,
    }
    request = CleanupRequest(
        admission_commitment_sha256=context.admission.admission_commitment_sha256,
        seal_commitment_sha256=None,
        operation_root_sha256=None,
        operation_inventory_root_sha256=canonical_sha256({"operations": [operation]}),
        expected_operation_count=1,
        aborting=True,
    )
    receipt = context.service.cleanup(request, idempotency_key=_sha("direct-abort"))
    assert receipt.operation_inventory_root_sha256 == request.operation_inventory_root_sha256
    assert context.state.get(context.unit_identity).state is OperationState.ABORT_CLEANED
    context.state.close()
