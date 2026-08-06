from __future__ import annotations

import hashlib
import json
import os
from types import SimpleNamespace

from test_app import _receipt

from mem0_oss_adapter_v5.composition import SealedInputManifest, V5AdapterService
from mem0_oss_adapter_v5.domain import (
    ExtractionMemory,
    RuntimeExtractionResult,
    _issue_sanitized_runtime_receipt,
    canonical_sha256,
)
from mem0_oss_adapter_v5.domain import (
    canonical_sha256 as domain_sha256,
)
from mem0_oss_adapter_v5.extraction_contract import build_extraction_request
from mem0_oss_adapter_v5.http_models import AdmitRequest, DispatchRequest, StatusRequest
from mem0_oss_adapter_v5.source_authority import _issue_verified_source_authority
from mem0_oss_adapter_v5.state_sqlite import SqliteOperationState
from mem0_oss_adapter_v5.subscription_runtime import (
    SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Runtime:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, request, intent):
        self.calls += 1
        memory = ExtractionMemory(
            id="0",
            text="Alice likes tea.",
            attributed_to="user",
            linked_memory_ids=(),
        )
        return RuntimeExtractionResult(
            intent=intent,
            memories=(memory,),
            receipt=_issued_receipt(request.request_body_sha256),
            output_text_sha256=_sha("output"),
        )


def _issued_receipt(request_body_sha256: str):
    payload = _receipt(request_body_sha256)
    return _issue_sanitized_runtime_receipt(
        payload,
        verified_receipt_sha256=domain_sha256(payload),
    )


class _Authority:
    def verify(self, **kwargs: object) -> str:
        return domain_sha256(kwargs["receipt"])


class _Storage:
    def __init__(self) -> None:
        self.persisted = False

    def verify_exact(self, **_kwargs):
        if not self.persisted:
            raise RuntimeError
        return SimpleNamespace(commitment_sha256=_sha("storage"))

    def persist(self, **_kwargs):
        self.persisted = True
        return SimpleNamespace(commitment_sha256=_sha("storage"))


def test_provider_free_dispatch_persists_once_and_status_only_reads_durable_result(
    tmp_path,
) -> None:
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
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.sealed-input.v1",
        "ingestion_manifest_sha256": _sha("manifest"),
        "ingestion_root_sha256": canonical_sha256(
            {
                "units": [
                    {
                        "unit_identity_sha256": unit["unit_identity_sha256"],
                        "unit_sha256": unit["unit_sha256"],
                        "scope_sha256": unit["scope_sha256"],
                    }
                ]
            }
        ),
        "current_date": "2026-08-06",
        "units": [unit],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)}))
    os.chmod(path, 0o400)
    manifest = SealedInputManifest(path)
    state = SqliteOperationState(tmp_path / "state.sqlite3", hmac_key=b"h" * 32)
    runtime = _Runtime()
    source_authority = _issue_verified_source_authority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        manifest_sha256=_sha("source-manifest"),
        closure_sha256=_sha("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_sha("phase-release"),
    )
    runtime_binding = _sha("runtime-binding")
    runtime_source = _sha("runtime-source")
    runtime_route = _sha("runtime-route")
    service = V5AdapterService(
        manifest=manifest,
        state=state,
        runtime=runtime,
        receipt_authority=_Authority(),
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base"),
        storage=_Storage(),
        receipt_directory=tmp_path / "receipts",
        result_hmac_key=b"r" * 32,
        source_authority=source_authority,
        runtime_binding_commitment_sha256=runtime_binding,
        runtime_source_sha256=runtime_source,
        runtime_route_binding_sha256=runtime_route,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    )
    admission_sha = _sha("admission")
    admission = AdmitRequest(
        admission_commitment_sha256=admission_sha,
        ingestion_manifest_sha256=unsigned["ingestion_manifest_sha256"],
        ingestion_root_sha256=unsigned["ingestion_root_sha256"],
        expected_operation_count=1,
        route_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    )
    admission_receipt = service.admit(admission, idempotency_key=_sha("admit"))
    assert admission_receipt.accepted is True
    assert (
        admission_receipt.runtime_binding_commitment_sha256
        == source_authority.binding_commitment(
            route_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
            runtime_binding_commitment_sha256=runtime_binding,
            runtime_source_sha256=runtime_source,
            runtime_route_binding_sha256=runtime_route,
            runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
        )
    )
    extraction = build_extraction_request(
        source_messages=tuple(unit["source_messages"]),
        current_date="2026-08-06",
        timestamp="2024-03-10",
    )
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
        request_body_sha256=extraction.request_body_sha256,
        sequence=0,
    )
    first = service.dispatch(dispatch, idempotency_key=_sha("dispatch"))
    assert first.operation_id_sha256 == operation_id
    assert runtime.calls == 1
    status = service.status(
        StatusRequest(
            admission_commitment_sha256=admission_sha,
            operation_id_sha256=operation_id,
        ),
        idempotency_key=_sha("status"),
    )
    assert status.runtime_receipt == first.runtime_receipt
    assert runtime.calls == 1
    state.close()
