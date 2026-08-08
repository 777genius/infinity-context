from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mem0_oss_adapter_v5.app import create_app
from mem0_oss_adapter_v5.domain import canonical_sha256
from mem0_oss_adapter_v5.runtime_attestation import (
    V5_ROUTE_CONTRACT,
    V5_ROUTE_CONTRACT_SHA256,
    RuntimeAttestationError,
    RuntimeAttestationRequest,
    V5RuntimeAttestationAuthority,
    V5RuntimeAuthorityProjection,
    runtime_attestation_idempotency_key,
    verify_runtime_attestation,
)
from mem0_oss_adapter_v5.source_authority import _issue_verified_source_authority

_INGRESS = "i" * 32
_PROBE = b"p" * 32


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source_authority():
    return _issue_verified_source_authority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        manifest_sha256=_sha("source-manifest"),
        closure_sha256=_sha("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_sha("phase-c-release"),
    )


def _projection() -> V5RuntimeAuthorityProjection:
    return V5RuntimeAuthorityProjection.issue(
        source_authority=_source_authority(),
        subscription_runtime_binding_commitment_sha256=_sha("runtime-binding"),
        runtime_source_sha256=_sha("runtime-source"),
        runtime_route_binding_sha256=_sha("runtime-route"),
        runtime_transport_origin_sha256=_sha("runtime-transport"),
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base"),
    )


def _authority(clock=lambda: 1_900_000_000.0) -> V5RuntimeAttestationAuthority:
    return V5RuntimeAttestationAuthority(
        projection=_projection(),
        root_secret=_PROBE,
        clock=clock,
    )


def _request(
    *, run: str = "run", nonce: str = "nonce", validity_seconds: int = 180
) -> RuntimeAttestationRequest:
    return RuntimeAttestationRequest(
        target_origin_sha256=_sha("http://127.0.0.1:19091"),
        run_id_sha256=_sha(run),
        probe_nonce_sha256=_sha(nonce),
        validity_seconds=validity_seconds,
    )


def _commitment(request: RuntimeAttestationRequest) -> str:
    return canonical_sha256(request.model_dump(mode="json"))


def _headers(request: RuntimeAttestationRequest, *, token: str | None = None) -> dict[str, str]:
    commitment = _commitment(request)
    token = token or _authority().authentication_token
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": runtime_attestation_idempotency_key(commitment),
        "X-Request-Commitment-SHA256": commitment,
    }


def test_attestation_is_signed_exact_idempotent_and_provider_free() -> None:
    authority = _authority()
    request = _request()
    idempotency = runtime_attestation_idempotency_key(_commitment(request))
    first = authority.attest(request, idempotency_key=idempotency)
    second = authority.attest(request, idempotency_key=idempotency)

    assert first is second
    assert first.provider_calls == 0
    assert first.issued_at_unix == 1_900_000_000
    assert first.expires_at_unix == first.issued_at_unix + request.validity_seconds
    assert first.target_origin_sha256 == request.target_origin_sha256
    assert first.run_id_sha256 == request.run_id_sha256
    assert first.probe_nonce_sha256 == request.probe_nonce_sha256
    assert first.route_contract_sha256 == V5_ROUTE_CONTRACT_SHA256
    assert first.runtime_binding_commitment_sha256 == (
        _projection().runtime_binding_commitment_sha256
    )
    public = first.model_dump(mode="json")
    dynamic = {
        "schema_version",
        "service",
        "target_origin_sha256",
        "run_id_sha256",
        "probe_nonce_sha256",
        "implementation_binding_sha256",
        "issued_at_unix",
        "expires_at_unix",
        "provider_calls",
        "attestation_hmac_sha256",
    }
    expected_implementation = canonical_sha256(
        {
            "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
            **{key: value for key, value in public.items() if key not in dynamic},
        }
    )
    assert first.implementation_binding_sha256 == expected_implementation
    assert verify_runtime_attestation(first, root_secret=_PROBE)
    assert not verify_runtime_attestation(first, root_secret=b"x" * 32)

    tampered = first.model_copy(update={"run_id_sha256": _sha("other")})
    assert not verify_runtime_attestation(tampered, root_secret=_PROBE)


def test_nonce_reuse_is_conflict_and_expired_exact_request_is_tombstoned() -> None:
    now = [1_900_000_000.0]
    authority = _authority(clock=lambda: now[0])
    request = _request()
    first = authority.attest(
        request,
        idempotency_key=runtime_attestation_idempotency_key(_commitment(request)),
    )

    conflicting = _request(run="other")
    with pytest.raises(RuntimeAttestationError, match="runtime_attestation_conflict") as failure:
        authority.attest(
            conflicting,
            idempotency_key=runtime_attestation_idempotency_key(_commitment(conflicting)),
        )
    assert failure.value.status_code == 409

    now[0] = float(first.expires_at_unix + 1)
    with pytest.raises(RuntimeAttestationError, match="runtime_attestation_expired") as expired:
        authority.attest(
            request,
            idempotency_key=runtime_attestation_idempotency_key(_commitment(request)),
        )
    assert expired.value.status_code == 410


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "invalid"])
def test_invalid_clock_is_stable_unavailable(value: object) -> None:
    authority = _authority(clock=lambda: value)  # type: ignore[arg-type,return-value]
    request = _request()
    with pytest.raises(RuntimeAttestationError, match="runtime_attestation_unavailable") as failure:
        authority.attest(
            request,
            idempotency_key=runtime_attestation_idempotency_key(_commitment(request)),
        )
    assert failure.value.status_code == 503


def test_authenticated_challenge_registry_is_bounded() -> None:
    authority = _authority()
    for index in range(1_024):
        request = _request(nonce=f"nonce-{index}")
        authority.attest(
            request,
            idempotency_key=runtime_attestation_idempotency_key(_commitment(request)),
        )
    overflow = _request(nonce="overflow")
    with pytest.raises(RuntimeAttestationError, match="runtime_attestation_unavailable") as failure:
        authority.attest(
            overflow,
            idempotency_key=runtime_attestation_idempotency_key(_commitment(overflow)),
        )
    assert failure.value.status_code == 503


def test_http_route_uses_distinct_probe_auth_and_never_calls_application_service() -> None:
    application = SimpleNamespace(calls=[])
    authority = _authority()
    client = TestClient(
        create_app(
            service=application,
            bearer_token=_INGRESS,
            runtime_attestation_authority=authority,
        )
    )
    request = _request()
    body = request.model_dump(mode="json")

    response = client.post("/v5/runtime/attest", json=body, headers=_headers(request))
    assert response.status_code == 200
    assert response.json()["provider_calls"] == 0
    assert application.calls == []

    wrong_auth = client.post(
        "/v5/runtime/attest",
        json=body,
        headers=_headers(request, token=_INGRESS),
    )
    assert wrong_auth.status_code == 401
    assert wrong_auth.json() == {"detail": "invalid_authentication"}
    assert application.calls == []

    wrong_idempotency = _headers(request)
    wrong_idempotency["Idempotency-Key"] = _sha("wrong")
    rejected = client.post("/v5/runtime/attest", json=body, headers=wrong_idempotency)
    assert rejected.status_code == 400
    assert rejected.json() == {"detail": "runtime_attestation_invalid"}


def test_attested_route_inventory_matches_actual_application_routes() -> None:
    app = create_app(
        service=SimpleNamespace(),
        bearer_token=_INGRESS,
        runtime_attestation_authority=_authority(),
    )
    actual = {
        (method, route.path)
        for route in app.routes
        if route.path == "/health" or route.path.startswith("/v5/")
        for method in route.methods
    }
    assert actual == set(V5_ROUTE_CONTRACT)
    expected = canonical_sha256(
        {
            "schema_version": "mem0-oss-adapter-v5.route-contract.v1",
            "routes": [{"method": method, "path": path} for method, path in V5_ROUTE_CONTRACT],
        }
    )
    assert expected == V5_ROUTE_CONTRACT_SHA256


def test_factory_requires_runtime_attestation_authority() -> None:
    with pytest.raises(TypeError):
        create_app(
            service=SimpleNamespace(),
            bearer_token=_INGRESS,
        )


def test_request_schema_is_exact_and_canonical() -> None:
    request = _request()
    body = request.model_dump(mode="json")
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == _commitment(request)
    with pytest.raises(ValueError):
        RuntimeAttestationRequest.model_validate({**body, "unexpected": True})
    for invalid in (0, 7201, True):
        with pytest.raises(ValueError):
            RuntimeAttestationRequest.model_validate({**body, "validity_seconds": invalid})
