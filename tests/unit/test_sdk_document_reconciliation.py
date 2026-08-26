from __future__ import annotations

import json

import httpx
import pytest
from infinity_context_sdk import InfinityContextClient
from infinity_context_sdk.errors import InfinityContextError

CAPABILITY = {
    "exact_reconciliation": {
        "contract_version": "document-reconciliation.v1",
        "endpoint": "/v1/documents/reconcile-exact",
        "max_deadline_ms": 10_000,
        "max_response_bytes": 65_536,
        "read_only": True,
    }
}
INPUT = {
    "capability": CAPABILITY,
    "space_id": "space",
    "memory_scope_id": "scope",
    "source_type": "opaque-kind",
    "source_external_id": "opaque-id",
    "deadline_ms": 500,
}


def _response(**changes):
    data = {
        "contract_version": "document-reconciliation.v1",
        "state": "present",
        "scope": {"space_id": "space", "memory_scope_id": "scope", "thread_id": None},
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "document_id": "doc-1",
        "canonical_status": "active",
        "projection_generation": None,
        "profile_generation": None,
        "visibility": "accepted",
        "idempotency_key_matches": None,
    }
    data.update(changes)
    return {"data": data}


def test_python_sdk_parity_validates_capability_and_performs_one_bounded_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response())

    result = InfinityContextClient(transport=httpx.MockTransport(handler)).reconcile_exact_document(
        **INPUT
    )
    assert result["data"]["state"] == "present"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/documents/reconcile-exact"
    assert json.loads(requests[0].content)["deadline_ms"] == 500


def test_python_sdk_fails_closed_on_unattested_malformed_or_oversized_responses() -> None:
    client = InfinityContextClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    )
    with pytest.raises(ValueError, match="capability"):
        client.reconcile_exact_document(**{**INPUT, "capability": {}})
    with pytest.raises(ValueError, match="malformed"):
        client.reconcile_exact_document(**INPUT)

    oversized = InfinityContextClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b'"' + b"x" * 65_537 + b'"')
        )
    )
    with pytest.raises(InfinityContextError) as captured:
        oversized.reconcile_exact_document(**INPUT)
    assert captured.value.code == "memory.response_byte_limit_exceeded"


def test_python_sdk_does_not_leak_opaque_identity_in_validation_errors() -> None:
    secret = "secret-opaque-identity"
    with pytest.raises(ValueError) as captured:
        InfinityContextClient().reconcile_exact_document(
            **{**INPUT, "source_external_id": f"{secret}\x00"}
        )
    assert secret not in str(captured.value)
