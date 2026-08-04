from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from mem0_oss_adapter.app import create_app
from mem0_oss_adapter.manifest import manifest_integrity_sha256

from .conftest import FakeOssPort

_INGRESS = "unit-ingress-key"
_PROBE = "unit-probe-key"


def _headers() -> dict[str, str]:
    return {"X-API-Key": _INGRESS}


def _add_payload() -> dict[str, object]:
    return {
        "messages": [{"role": "user", "content": "hello"}],
        "user_id": "user-1",
        "run_id": "run-1",
        "metadata": {"source_id": "source-1", "source_sha256": "a" * 64},
        "timestamp": 1_672_531_200,
    }


def test_data_plane_requires_dedicated_ingress_key(monkeypatch) -> None:
    monkeypatch.delenv("MEM0_ADAPTER_INGRESS_API_KEY", raising=False)
    client = TestClient(create_app(FakeOssPort()))

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "missing_adapter_ingress_api_key"}


def test_add_is_strict_and_returns_sanitized_identity(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    client = TestClient(create_app(FakeOssPort()))

    response = client.post("/memories", headers=_headers(), json=_add_payload())
    unknown = client.post(
        "/memories",
        headers=_headers(),
        json={**_add_payload(), "manifest": {"quality_score": 1}},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "id": "memory-1",
            "event": "ADD",
            "metadata": {"source_id": "source-1", "source_sha256": "a" * 64},
        }
    ]
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "invalid_request"}


def test_capabilities_stay_static_without_refresh_material(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    client = TestClient(create_app(FakeOssPort()))

    manifest = client.get("/benchmark/capabilities").json()

    assert set(manifest) == {
        "schema_version",
        "runtime_mode",
        "configured",
        "wrapper_source_revision",
        "wrapper_source_sha256",
        "config_fingerprint_sha256",
        "adapter",
        "runtime",
        "packages",
        "embedding",
        "extraction",
        "timestamp",
        "persisted_source_identity",
        "capabilities",
        "delete",
        "integrity",
    }
    assert manifest["timestamp"]["attestation"]["status"] == "not_run"
    assert manifest["schema_version"] == "mem0-benchmark-capabilities.v4"
    assert manifest["extraction"]["subscription_scope"] == "isolated_single_add"
    assert manifest["extraction"]["usage_evidence"] == {
        "schema_version": "mem0-benchmark-usage-attestation.v1",
        "run_scoped": True,
        "hmac_sha256": True,
        "ingress_auth_required": True,
        "probe_token_required": True,
    }
    assert "signed_run_scoped_usage_evidence" in manifest["capabilities"]
    assert "refresh_binding" not in manifest
    assert "refresh_witness" not in manifest


def test_probe_challenge_and_refresh_use_separate_hmac_witness(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _PROBE)
    client = TestClient(create_app(FakeOssPort()))
    probe_headers = {"X-Benchmark-Probe-Token": _PROBE}
    nonce = "ab" * 32

    challenge = client.post(
        "/benchmark/auth-challenge",
        headers=probe_headers,
        json={"nonce": nonce},
    )
    refreshed = client.post(
        "/benchmark/attest-timestamp",
        headers=probe_headers,
        json={"run_id": "run-1", "probe_nonce": nonce, "target_identity_sha256": "f" * 64},
    )
    static_after_refresh = client.get("/benchmark/capabilities")

    assert challenge.status_code == 200
    assert (
        challenge.json()["signature"]
        == hmac.new(
            _PROBE.encode(),
            f"mem0-benchmark-auth-challenge.v1\n{nonce}".encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    assert refreshed.status_code == 200
    manifest = refreshed.json()
    assert manifest["timestamp"]["attestation"]["status"] == "passed"
    assert manifest["persisted_source_identity"]["source_id_roundtrip_attested"] is True
    assert manifest["integrity"]["manifest_sha256"] == manifest_integrity_sha256(manifest)
    assert set(manifest["refresh_witness"]) == {
        "algorithm",
        "manifest_fingerprint_sha256",
        "signature",
    }
    binding = manifest["refresh_binding"]
    expected_witness_message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            binding["run_id_sha256"],
            binding["probe_nonce_sha256"],
            binding["target_identity_sha256"],
            binding["refreshed_at"],
            manifest["refresh_witness"]["manifest_fingerprint_sha256"],
        )
    ).encode()
    assert (
        manifest["refresh_witness"]["signature"]
        == hmac.new(
            _PROBE.encode(),
            expected_witness_message,
            hashlib.sha256,
        ).hexdigest()
    )
    assert "refresh_binding" not in static_after_refresh.json()
    assert "refresh_witness" not in static_after_refresh.json()


def test_usage_attestation_is_exact_run_scoped_sanitized_and_signed(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _PROBE)
    client = TestClient(create_app(FakeOssPort()))
    assert client.post("/memories", headers=_headers(), json=_add_payload()).status_code == 200
    second_add = _add_payload()
    second_add["metadata"] = {"source_id": "source-2", "source_sha256": "b" * 64}
    assert client.post("/memories", headers=_headers(), json=second_add).status_code == 200
    nonce = "ab" * 32

    response = client.post(
        "/benchmark/attest-usage",
        headers={**_headers(), "X-Benchmark-Probe-Token": _PROBE},
        json={
            "run_id": "run-1",
            "probe_nonce": nonce,
            "target_identity_sha256": "f" * 64,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "run_id_sha256",
        "probe_nonce_sha256",
        "target_identity_sha256",
        "attested_at",
        "usage",
        "usage_fingerprint_sha256",
        "algorithm",
        "signature",
    }
    assert payload["schema_version"] == "mem0-benchmark-usage-attestation.v1"
    assert payload["run_id_sha256"] == hashlib.sha256(b"run-1").hexdigest()
    assert payload["probe_nonce_sha256"] == hashlib.sha256(nonce.encode()).hexdigest()
    assert payload["target_identity_sha256"] == "f" * 64
    assert payload["usage"]["mode"] == "raw_passthrough"
    assert payload["usage"]["operation_count"] == 2
    assert payload["usage"]["extraction_calls"] == 0
    assert payload["usage"]["request_bytes"] == 0
    assert payload["usage"]["response_bytes"] == 0
    assert payload["usage"]["first_operation_at"] <= payload["usage"]["last_operation_at"]
    assert payload["usage"]["last_operation_at"] <= payload["attested_at"]
    canonical_usage = json.dumps(
        {"attested_at": payload["attested_at"], "usage": payload["usage"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert payload["usage_fingerprint_sha256"] == hashlib.sha256(canonical_usage).hexdigest()
    witness = "\n".join(
        (
            "mem0-benchmark-usage-witness.v1",
            payload["run_id_sha256"],
            payload["probe_nonce_sha256"],
            payload["target_identity_sha256"],
            payload["attested_at"],
            payload["usage_fingerprint_sha256"],
        )
    ).encode()
    assert payload["signature"] == hmac.new(_PROBE.encode(), witness, hashlib.sha256).hexdigest()
    serialized = response.text
    assert "run-1" not in serialized
    assert "hello" not in serialized
    assert "token" not in serialized.casefold()
    assert "url" not in serialized.casefold()


def test_usage_attestation_requires_both_auth_headers_and_exact_existing_run(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _PROBE)
    client = TestClient(create_app(FakeOssPort()))
    request = {
        "run_id": "missing-run",
        "probe_nonce": "ab" * 32,
        "target_identity_sha256": "f" * 64,
    }

    assert (
        client.post(
            "/benchmark/attest-usage",
            headers=_headers(),
            json=request,
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/benchmark/attest-usage",
            headers={"X-Benchmark-Probe-Token": _PROBE},
            json=request,
        ).status_code
        == 401
    )
    unavailable = client.post(
        "/benchmark/attest-usage",
        headers={**_headers(), "X-Benchmark-Probe-Token": _PROBE},
        json=request,
    )
    assert unavailable.status_code == 409
    assert unavailable.json() == {"detail": "mem0_oss_usage_evidence_unavailable"}
    unknown = client.post(
        "/benchmark/attest-usage",
        headers={**_headers(), "X-Benchmark-Probe-Token": _PROBE},
        json={**request, "prompt": "must not be accepted"},
    )
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "invalid_request"}


def test_request_validation_never_reflects_attestation_input(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _PROBE)
    client = TestClient(create_app(FakeOssPort()))
    sentinel = "SECRET-RUN-ID-MUST-NOT-LEAK?"

    response = client.post(
        "/benchmark/attest-usage",
        headers={**_headers(), "X-Benchmark-Probe-Token": _PROBE},
        json={
            "run_id": sentinel,
            "probe_nonce": "ab" * 32,
            "target_identity_sha256": "f" * 64,
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert sentinel not in response.text


def test_subscription_usage_attestation_proves_one_bounded_call(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _PROBE)
    client = TestClient(create_app(FakeOssPort(extraction_mode="subscription_llm")))
    assert client.post("/memories", headers=_headers(), json=_add_payload()).status_code == 200

    response = client.post(
        "/benchmark/attest-usage",
        headers={**_headers(), "X-Benchmark-Probe-Token": _PROBE},
        json={
            "run_id": "run-1",
            "probe_nonce": "ab" * 32,
            "target_identity_sha256": "f" * 64,
        },
    )

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["mode"] == "subscription_llm"
    assert usage["operation_count"] == 1
    assert usage["extraction_calls"] == 1
    assert 0 < usage["request_bytes"] <= 1_048_576
    assert 0 <= usage["response_bytes"] <= 1_048_576
