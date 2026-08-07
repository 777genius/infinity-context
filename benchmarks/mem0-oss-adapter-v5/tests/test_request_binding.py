from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_app import _TOKEN, _headers
from test_composition_recovery import FakeMem0Backend, _cleanup_request, _context, _service

from mem0_oss_adapter_v5.app import AdapterServiceError, create_app
from mem0_oss_adapter_v5.domain import canonical_sha256
from mem0_oss_adapter_v5.mem0_storage import Mem0StorageAdapter
from mem0_oss_adapter_v5.request_binding import (
    RequestBindingRequest,
    verify_request_binding,
)
from mem0_oss_adapter_v5.state_sqlite import SqliteOperationState


def _request(context) -> RequestBindingRequest:
    return RequestBindingRequest(
        admission_commitment_sha256=context.admission.admission_commitment_sha256,
        operation_id_sha256=context.dispatch.operation_id_sha256,
    )


def test_request_binding_matches_exact_sealed_extraction_and_is_deterministic(tmp_path) -> None:
    context = _context(tmp_path)
    request = _request(context)
    state_before = context.state.get(context.unit_identity)
    first = context.service.request_binding(request, idempotency_key=_sha("binding-1"))
    second = context.service.request_binding(request, idempotency_key=_sha("binding-2"))
    unit = context.service._manifest.units[0]
    extraction = context.service._extraction_request(unit)

    assert first == second
    assert first.request_body_sha256 == extraction.request_body_sha256
    assert first.response_format_sha256 == extraction.response_format_sha256
    assert first.current_date_commitment_sha256 == canonical_sha256(
        {"current_date": context.service._manifest.current_date}
    )
    assert first.ingestion_manifest_sha256 == context.service._manifest.ingestion_manifest_sha256
    assert first.ingestion_root_sha256 == context.service._manifest.ingestion_root_sha256
    assert first.unit_identity_sha256 == unit.unit_identity_sha256
    assert first.unit_sha256 == unit.unit_sha256
    assert first.scope_sha256 == unit.scope_sha256
    assert first.source_id == unit.source_id
    assert first.source_sha256 == unit.source_sha256
    assert first.sequence == unit.sequence
    assert verify_request_binding(first, result_hmac_key=b"r" * 32)
    assert context.runtime.calls == 0

    public = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "Alice likes tea." not in public
    assert context.service._manifest.current_date not in public
    assert "source_messages" not in public
    assert context.state.get(context.unit_identity) == state_before
    context.state.close()


def test_request_binding_survives_restart_without_provider_dispatch(tmp_path) -> None:
    context = _context(tmp_path)
    expected = context.service.request_binding(_request(context), idempotency_key=_sha("before"))
    manifest = context.service._manifest
    runtime = context.runtime
    storage = context.storage
    context.state.close()

    state = SqliteOperationState(tmp_path / "state.sqlite3", hmac_key=b"h" * 32)
    restarted = _service(tmp_path, manifest, state, runtime, storage)
    restarted.admit(context.admission, idempotency_key=_sha("readmit"))
    actual = restarted.request_binding(_request(context), idempotency_key=_sha("after"))
    assert actual == expected
    assert runtime.calls == 0
    state.close()


def test_request_binding_rejects_wrong_authority_and_tampering(tmp_path) -> None:
    context = _context(tmp_path)
    request = _request(context)
    response = context.service.request_binding(request, idempotency_key=_sha("valid"))

    with pytest.raises(AdapterServiceError, match="run_not_found") as wrong_admission:
        context.service.request_binding(
            request.model_copy(update={"admission_commitment_sha256": _sha("wrong")}),
            idempotency_key=_sha("wrong-admission"),
        )
    assert wrong_admission.value.status_code == 404

    with pytest.raises(AdapterServiceError, match="operation_not_found") as wrong_operation:
        context.service.request_binding(
            request.model_copy(update={"operation_id_sha256": _sha("wrong-operation")}),
            idempotency_key=_sha("wrong-operation"),
        )
    assert wrong_operation.value.status_code == 404

    tampered = response.model_copy(update={"request_body_sha256": _sha("tampered")})
    assert not verify_request_binding(tampered, result_hmac_key=b"r" * 32)
    assert not verify_request_binding(response, result_hmac_key=b"x" * 32)
    assert context.runtime.calls == 0
    context.state.close()


def test_request_binding_is_unavailable_after_cleanup(tmp_path) -> None:
    context = _context(tmp_path)
    request = _request(context)
    context.service._storage = Mem0StorageAdapter(FakeMem0Backend())
    context.service.cleanup(
        _cleanup_request(context, aborting=True),
        idempotency_key=_sha("cleanup"),
    )
    with pytest.raises(AdapterServiceError, match="operation_cleaned") as cleaned:
        context.service.request_binding(request, idempotency_key=_sha("after-cleanup"))
    assert cleaned.value.status_code == 410
    assert context.runtime.calls == 0
    context.state.close()


def test_request_binding_maps_authenticated_row_tampering_to_fixed_503(tmp_path) -> None:
    context = _context(tmp_path)
    context.state._connection.execute(
        "UPDATE operations_v2 SET request_sha256 = ? WHERE unit_identity_sha256 = ?",
        (_sha("tampered-request"), context.unit_identity),
    )
    _assert_service_and_http_run_state_invalid(context)
    context.state.close()


def test_request_binding_maps_schema_tampering_to_fixed_503(tmp_path) -> None:
    context = _context(tmp_path)
    context.state._connection.execute(
        "CREATE TRIGGER hostile AFTER INSERT ON operations_v2 BEGIN SELECT 1; END"
    )
    _assert_service_and_http_run_state_invalid(context)
    context.state.close()


def test_request_binding_maps_unavailable_state_to_fixed_503(tmp_path) -> None:
    context = _context(tmp_path)
    context.state.close()
    _assert_service_and_http_run_state_invalid(context)


def test_request_binding_maps_projection_failure_to_fixed_503(tmp_path) -> None:
    context = _context(tmp_path)
    service = context.service._request_binding_service()

    def unavailable_projection(_unit):
        raise RuntimeError("private projection failure")

    service._extraction_request = unavailable_projection
    _assert_service_and_http_run_state_invalid(context)
    context.state.close()


def _assert_service_and_http_run_state_invalid(context) -> None:
    request = _request(context)
    with pytest.raises(AdapterServiceError, match="run_state_invalid") as failure:
        context.service.request_binding(request, idempotency_key=_sha("service-failure"))
    assert failure.value.status_code == 503

    body = request.model_dump(mode="json")
    response = TestClient(
        create_app(service=context.service, bearer_token=_TOKEN),
        raise_server_exceptions=False,
    ).post(
        "/v5/operations/request-binding",
        json=body,
        headers=_headers(body),
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "run_state_invalid"}
    assert context.runtime.calls == 0


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()
