from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupRequest,
    Mem0V5HttpError,
    Mem0V5HttpPort,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request(*, aborting: bool) -> Mem0V5CleanupRequest:
    return Mem0V5CleanupRequest(
        admission_commitment_sha256=_digest("admission"),
        seal_commitment_sha256=None if aborting else _digest("seal"),
        operation_root_sha256=None if aborting else _digest("operations"),
        operation_inventory_root_sha256=_digest("inventory"),
        expected_operation_count=1,
        aborting=aborting,
        idempotency_key=_digest("cleanup"),
    )


class _Transport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def request(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=200, content=json.dumps(self.payload).encode())


def _cleanup_payload(request: Mem0V5CleanupRequest) -> dict[str, object]:
    return {
        "admission_commitment_sha256": request.admission_commitment_sha256,
        "seal_commitment_sha256": request.seal_commitment_sha256,
        "operation_root_sha256": request.operation_root_sha256,
        "operation_inventory_root_sha256": request.operation_inventory_root_sha256,
        "deleted_operation_count": 1,
        "residual_record_count": 0,
        "residual_root_sha256": _digest("empty"),
    }


def _client(payload: dict[str, object]) -> Mem0V5HttpPort:
    return Mem0V5HttpPort(
        origin="http://127.0.0.1:8888",
        bearer_token="fixture-bearer-token",
        timeout_seconds=1,
        transport=_Transport(payload),
    )


def test_cleanup_request_binds_operation_root_for_sealed_delete() -> None:
    request = _request(aborting=False)
    assert request.body()["operation_root_sha256"] == _digest("operations")
    assert _client(_cleanup_payload(request)).cleanup(request).operation_root_sha256 == _digest(
        "operations"
    )


@pytest.mark.parametrize("field", ["operation_root_sha256", "deleted_operation_count"])
def test_cleanup_response_rejects_divergent_root_and_unbounded_count(field: str) -> None:
    request = _request(aborting=False)
    payload = _cleanup_payload(request)
    payload[field] = _digest("divergent") if field.endswith("sha256") else 2
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_response_invalid"):
        _client(payload).cleanup(request)


def test_cleanup_request_requires_both_seal_and_operation_root_outside_abort() -> None:
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_request_invalid"):
        Mem0V5CleanupRequest(
            admission_commitment_sha256=_digest("admission"),
            seal_commitment_sha256=_digest("seal"),
            operation_root_sha256=None,
            operation_inventory_root_sha256=_digest("inventory"),
            expected_operation_count=1,
            aborting=False,
            idempotency_key=_digest("cleanup"),
        )


def test_abort_cleanup_forbids_seal_and_operation_root() -> None:
    assert _request(aborting=True).operation_root_sha256 is None
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_request_invalid"):
        Mem0V5CleanupRequest(
            admission_commitment_sha256=_digest("admission"),
            seal_commitment_sha256=None,
            operation_root_sha256=_digest("operations"),
            operation_inventory_root_sha256=_digest("inventory"),
            expected_operation_count=1,
            aborting=True,
            idempotency_key=_digest("cleanup"),
        )


@pytest.mark.parametrize("impostor", [0, 1, "true"])
def test_cleanup_request_rejects_bool_impostor_without_type_leak(impostor: object) -> None:
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_request_invalid"):
        Mem0V5CleanupRequest(
            admission_commitment_sha256=_digest("admission"),
            seal_commitment_sha256=None,
            operation_root_sha256=None,
            operation_inventory_root_sha256=_digest("inventory"),
            expected_operation_count=1,
            aborting=impostor,  # type: ignore[arg-type]
            idempotency_key=_digest("cleanup"),
        )
