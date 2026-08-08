from __future__ import annotations

import hashlib
import json
import os
from types import SimpleNamespace

from fastapi.testclient import TestClient
from test_app import _TOKEN, _headers, _receipt

from mem0_oss_adapter_v5.app import create_app
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
from mem0_oss_adapter_v5.request_binding import (
    RequestBindingRequest,
    verify_request_binding,
)
from mem0_oss_adapter_v5.runtime_attestation import (
    V5RuntimeAttestationAuthority,
    V5RuntimeAuthorityProjection,
)
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
        self.last_scope = None

    def verify_exact(self, **_kwargs):
        if not self.persisted:
            raise RuntimeError
        return SimpleNamespace(commitment_sha256=_sha("storage"))

    def persist(self, **kwargs):
        self.persisted = True
        self.last_scope = kwargs["scope"]
        return SimpleNamespace(commitment_sha256=_sha("storage"))


def test_provider_free_dispatch_persists_once_and_status_only_reads_durable_result(
    tmp_path,
) -> None:
    source_messages = [{"role": "user", "content": "Alice likes tea."}]
    unit_sha256 = canonical_sha256({"source_messages": source_messages})
    source_sha256 = _sha("canonical-source-content")
    scope_sha256 = canonical_sha256(
        {
            "corpus_id": "corpus-1",
            "source_id": "source-1",
            "source_sha256": source_sha256,
            "unit_sha256": unit_sha256,
        }
    )
    unit = {
        "sequence": 0,
        "unit_identity_sha256": canonical_sha256(
            {
                "sequence": 0,
                "scope_sha256": scope_sha256,
                "unit_sha256": unit_sha256,
            }
        ),
        "unit_sha256": unit_sha256,
        "source_sha256": source_sha256,
        "scope_sha256": scope_sha256,
        "corpus_id": "corpus-1",
        "source_id": "source-1",
        "observation_date": "2024-03-10",
        "source_messages": source_messages,
    }
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.sealed-input.v2",
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
    runtime_authority = V5RuntimeAuthorityProjection.issue(
        source_authority=source_authority,
        subscription_runtime_binding_commitment_sha256=runtime_binding,
        runtime_source_sha256=runtime_source,
        runtime_route_binding_sha256=runtime_route,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base"),
    )
    storage = _Storage()
    service = V5AdapterService(
        manifest=manifest,
        state=state,
        runtime=runtime,
        receipt_authority=_Authority(),
        storage=storage,
        receipt_directory=tmp_path / "receipts",
        result_hmac_key=b"r" * 32,
        runtime_authority=runtime_authority,
    )
    assert service._runtime_authority is runtime_authority
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
    assert admission_receipt.runtime_binding_commitment_sha256 == (
        runtime_authority.runtime_binding_commitment_sha256
    )
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
    assert storage.last_scope.source_sha256 == source_sha256
    binding_request = RequestBindingRequest(
        schema_version="mem0-oss-adapter-v5.request-binding.v2",
        admission_commitment_sha256=admission_sha,
        operation_id_sha256=operation_id,
    )
    binding = service.request_binding(
        binding_request,
        idempotency_key=_sha("request-binding-v2"),
    )
    assert binding.schema_version == "mem0-oss-adapter-v5.request-binding.v2"
    assert binding.corpus_id == unit["corpus_id"]
    assert binding.source_sha256 == source_sha256
    assert binding.observation_date == unit["observation_date"]
    assert verify_request_binding(binding, result_hmac_key=b"r" * 32)
    body = binding_request.model_dump(mode="json")
    attestation = V5RuntimeAttestationAuthority(
        projection=runtime_authority,
        root_secret=b"a" * 32,
    )
    response = TestClient(
        create_app(
            service=service,
            bearer_token=_TOKEN,
            runtime_attestation_authority=attestation,
        )
    ).post(
        "/v5/operations/request-binding",
        json=body,
        headers=_headers(body),
    )
    assert response.status_code == 200
    assert response.json()["request_binding_evidence_sha256"] == (
        binding.request_binding_evidence_sha256
    )
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
