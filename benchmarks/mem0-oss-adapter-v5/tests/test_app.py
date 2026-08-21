from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from mem0_oss_adapter_v5.app import create_app
from mem0_oss_adapter_v5.http_models import (
    AdmissionReceipt,
    CleanupReceipt,
    RuntimeReceiptEnvelope,
    ScopedSearchResponse,
    StorageObservationResponse,
)
from mem0_oss_adapter_v5.request_binding import RequestBindingResponse

_TOKEN = "t" * 32


class _UnusedRuntimeAttestation:
    authentication_token = "a" * 64

    def attest(self, *_args, **_kwargs):
        raise AssertionError("runtime attestation is not expected")


def _app(service):
    return create_app(
        service=service,
        bearer_token=_TOKEN,
        runtime_attestation_authority=_UnusedRuntimeAttestation(),
    )


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _receipt(request_body_sha256: str | None = None) -> dict[str, object]:
    return {
        "metadata": {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": {
                "account_binding_hmac_sha256": _sha("account"),
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "model": "gpt-5.6-sol",
                "model_provider": "openai",
                "reasoning_effort": "high",
                "service_tier": "default",
                "execution_profile": "stateless-completion",
                "base_instructions_sha256": _sha("base"),
            },
            "request_identity": {
                "public_model": "gpt-5.6-sol",
                "client_requested_model": "gpt-5.6-sol",
                "configured_codex_model": "gpt-5.6-sol",
                "requested_codex_model": "gpt-5.6-sol",
                "request_body_sha256": request_body_sha256 or _sha("body"),
                "response_format_type": "json_schema",
                "response_format_sha256": _sha("format"),
                "response_schema_sha256": _sha("schema"),
            },
            "output_identity": {
                "output_text_sha256": _sha("output"),
                "terminal_status": "completed",
            },
            "output_token_limit": {"requested_tokens": 4096, "enforced": False},
            "receipt_hmac_sha256": _sha("receipt"),
        },
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _headers(body: dict[str, object], *, token: str = _TOKEN) -> dict[str, str]:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        "Authorization": "Bearer " + token,
        "Idempotency-Key": _sha("idempotency"),
        "X-Request-Commitment-SHA256": hashlib.sha256(canonical).hexdigest(),
    }


class _FakeService:
    def __init__(self) -> None:
        self.provider_calls = 0
        self.calls: list[str] = []

    def admit(self, request, *, idempotency_key: str) -> AdmissionReceipt:
        self.calls.append("admit")
        return AdmissionReceipt(
            admission_commitment_sha256=request.admission_commitment_sha256,
            runtime_binding_commitment_sha256=_sha("runtime"),
            accepted=True,
        )

    def dispatch(self, request, *, idempotency_key: str) -> RuntimeReceiptEnvelope:
        self.calls.append("dispatch")
        self.provider_calls += 1
        return RuntimeReceiptEnvelope(
            admission_commitment_sha256=request.admission_commitment_sha256,
            operation_id_sha256=request.operation_id_sha256,
            runtime_receipt=_receipt(),
        )

    def status(self, request, *, idempotency_key: str) -> RuntimeReceiptEnvelope:
        self.calls.append("status")
        return RuntimeReceiptEnvelope(
            admission_commitment_sha256=request.admission_commitment_sha256,
            operation_id_sha256=request.operation_id_sha256,
            runtime_receipt=_receipt(),
        )

    def cleanup(self, request, *, idempotency_key: str) -> CleanupReceipt:
        self.calls.append("cleanup")
        return CleanupReceipt(
            admission_commitment_sha256=request.admission_commitment_sha256,
            seal_commitment_sha256=request.seal_commitment_sha256,
            operation_root_sha256=_sha("operation-root"),
            operation_inventory_root_sha256=request.operation_inventory_root_sha256,
            deleted_operation_count=request.expected_operation_count,
            residual_record_count=0,
            residual_root_sha256=hashlib.sha256(b"").hexdigest(),
        )

    def storage_observation(self, request, *, idempotency_key: str) -> StorageObservationResponse:
        self.calls.append("storage_observation")
        records = (
            {
                "record_id": "provider-1",
                "extraction_memory_id": "0",
                "source_id": "source-1",
                "source_sha256": _sha("source"),
                "memory_sha256": _sha("memory"),
            },
        )
        return StorageObservationResponse.model_validate(
            {
                "schema_version": "mem0-oss-adapter-v5.storage-observation.v1",
                "admission_commitment_sha256": request.admission_commitment_sha256,
                "operation_id_sha256": request.operation_id_sha256,
                "scope_sha256": _sha("scope"),
                "source_id": "source-1",
                "source_sha256": _sha("source"),
                "storage_commitment_sha256": _sha("storage"),
                "record_count": 1,
                "record_root_sha256": _sha("record-root"),
                "records": records,
                "observation_hmac_sha256": _sha("observation-hmac"),
            }
        )

    def request_binding(self, request, *, idempotency_key: str) -> RequestBindingResponse:
        self.calls.append("request_binding")
        return RequestBindingResponse.model_validate(
            {
                "schema_version": "mem0-oss-adapter-v5.request-binding.v1",
                "admission_commitment_sha256": request.admission_commitment_sha256,
                "ingestion_manifest_sha256": _sha("manifest"),
                "ingestion_root_sha256": _sha("root"),
                "current_date_commitment_sha256": _sha("current-date"),
                "operation_id_sha256": request.operation_id_sha256,
                "unit_identity_sha256": _sha("identity"),
                "unit_sha256": _sha("unit"),
                "scope_sha256": _sha("scope"),
                "source_id": "source-1",
                "source_sha256": _sha("source"),
                "sequence": 0,
                "request_body_sha256": _sha("body"),
                "response_format_sha256": _sha("format"),
                "request_binding_hmac_sha256": _sha("binding-hmac"),
            }
        )

    def scoped_search(self, request, *, idempotency_key: str) -> ScopedSearchResponse:
        self.calls.append("scoped_search")
        results = (
            {
                "rank": 0,
                "record_id": "provider-1",
                "memory": "sanitized memory",
                "memory_sha256": _sha("sanitized memory"),
                "source_id": "source-1",
                "source_sha256": _sha("source"),
                "score": 0.75,
            },
        )
        return ScopedSearchResponse.model_validate(
            {
                "schema_version": "mem0-oss-adapter-v5.scoped-search.v1",
                "admission_commitment_sha256": request.admission_commitment_sha256,
                "corpus_id": request.corpus_id,
                "query_commitment_sha256": _sha(request.query),
                "limit": request.limit,
                "result_count": 1,
                "result_root_sha256": _sha("result-root"),
                "results": results,
                "search_hmac_sha256": _sha("search-hmac"),
            }
        )


def _admit_body() -> dict[str, object]:
    return {
        "admission_commitment_sha256": _sha("admission"),
        "ingestion_manifest_sha256": _sha("manifest"),
        "ingestion_root_sha256": _sha("root"),
        "expected_operation_count": 1,
        "route_sha256": _sha("route"),
    }


def test_endpoint_specific_exact_models_and_safe_health() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    health = client.get("/health")
    assert health.json() == {
        "ok": True,
        "service": "mem0-oss-adapter-v5",
        "provider_calls": "dispatch_only",
    }

    admit = _admit_body()
    assert client.post("/v5/runs/admit", json=admit, headers=_headers(admit)).json() == {
        "admission_commitment_sha256": _sha("admission"),
        "runtime_binding_commitment_sha256": _sha("runtime"),
        "accepted": True,
    }
    extra = {**admit, "source_messages": ["private"]}
    response = client.post("/v5/runs/admit", json=extra, headers=_headers(extra))
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}


def test_auth_and_request_commitment_fail_closed_without_service_call() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    body = _admit_body()
    response = client.post("/v5/runs/admit", json=body, headers=_headers(body, token="x" * 32))
    assert response.status_code == 401
    headers = _headers(body)
    headers["X-Request-Commitment-SHA256"] = _sha("wrong")
    response = client.post("/v5/runs/admit", json=body, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "request_commitment_invalid"}
    assert service.calls == []


def test_status_is_durable_readback_and_never_dispatches_provider() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    body = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
    }
    response = client.post("/v5/operations/status", json=body, headers=_headers(body))
    assert response.status_code == 200
    assert response.json()["runtime_receipt"] == _receipt()
    assert service.calls == ["status"]
    assert service.provider_calls == 0


def test_request_binding_is_authenticated_exact_and_provider_free() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    body = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
    }
    response = client.post(
        "/v5/operations/request-binding",
        json=body,
        headers=_headers(body),
    )
    assert response.status_code == 200
    assert response.json()["request_body_sha256"] == _sha("body")
    assert service.calls == ["request_binding"]
    assert service.provider_calls == 0

    extra = {**body, "source_messages": ["private"]}
    rejected = client.post(
        "/v5/operations/request-binding",
        json=extra,
        headers=_headers(extra),
    )
    assert rejected.status_code == 422
    assert service.calls == ["request_binding"]

    wrong_commitment_headers = _headers(body)
    wrong_commitment_headers["X-Request-Commitment-SHA256"] = _sha("wrong")
    rejected = client.post(
        "/v5/operations/request-binding",
        json=body,
        headers=wrong_commitment_headers,
    )
    assert rejected.status_code == 400
    assert rejected.json() == {"detail": "request_commitment_invalid"}
    assert service.calls == ["request_binding"]


def test_dispatch_is_one_service_invocation_and_strict_types() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    body = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
        "unit_identity_sha256": _sha("identity"),
        "unit_sha256": _sha("unit"),
        "scope_sha256": _sha("scope"),
        "request_body_sha256": _sha("body"),
        "sequence": 0,
    }
    response = client.post("/v5/operations/dispatch", json=body, headers=_headers(body))
    assert response.status_code == 200
    assert service.provider_calls == 1
    invalid = {**body, "sequence": True}
    assert (
        client.post("/v5/operations/dispatch", json=invalid, headers=_headers(invalid)).status_code
        == 422
    )
    assert service.provider_calls == 1


def test_cleanup_contract_is_exact_and_contains_no_secret() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    body = {
        "admission_commitment_sha256": _sha("admission"),
        "seal_commitment_sha256": None,
        "operation_root_sha256": None,
        "operation_inventory_root_sha256": _sha("inventory"),
        "expected_operation_count": 1,
        "aborting": True,
    }
    response = client.post("/v5/runs/cleanup", json=body, headers=_headers(body))
    assert response.status_code == 200
    encoded = response.content
    assert _TOKEN.encode() not in encoded
    assert set(response.json()) == {
        "admission_commitment_sha256",
        "seal_commitment_sha256",
        "operation_root_sha256",
        "operation_inventory_root_sha256",
        "deleted_operation_count",
        "residual_record_count",
        "residual_root_sha256",
    }
    sealed = {
        **body,
        "seal_commitment_sha256": _sha("seal"),
        "operation_root_sha256": _sha("operation-root"),
        "aborting": False,
    }
    assert client.post("/v5/runs/cleanup", json=sealed, headers=_headers(sealed)).status_code == 200


def test_oversized_body_is_rejected_before_parsing() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    response = client.post(
        "/v5/runs/admit",
        content=b"x" * 64_001,
        headers={
            **_headers(_admit_body()),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "request_body_too_large"}
    assert service.calls == []


def test_authenticated_evidence_routes_are_strict_and_never_echo_query() -> None:
    service = _FakeService()
    client = TestClient(_app(service))
    observation = {
        "admission_commitment_sha256": _sha("admission"),
        "operation_id_sha256": _sha("operation"),
    }
    response = client.post(
        "/v5/operations/storage-observation",
        json=observation,
        headers=_headers(observation),
    )
    assert response.status_code == 200
    assert response.json()["records"][0]["record_id"] == "provider-1"

    search = {
        "admission_commitment_sha256": _sha("admission"),
        "corpus_id": "corpus-1",
        "query": "private benchmark question",
        "limit": 10,
    }
    response = client.post("/v5/runs/search", json=search, headers=_headers(search))
    assert response.status_code == 200
    assert search["query"] not in response.text
    assert service.calls == ["storage_observation", "scoped_search"]

    invalid = {**search, "limit": 201}
    response = client.post("/v5/runs/search", json=invalid, headers=_headers(invalid))
    assert response.status_code == 422
    assert service.calls == ["storage_observation", "scoped_search"]
