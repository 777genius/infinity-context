from __future__ import annotations

import hashlib
import hmac

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
    assert manifest["extraction"]["subscription_scope"] == "isolated_single_add"
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
