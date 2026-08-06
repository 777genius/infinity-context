from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from mem0_oss_adapter.app import create_app
from mem0_oss_adapter.manifest import capabilities_manifest
from mem0_oss_adapter.models import TimestampAttestation

from .conftest import FakeOssPort

_SERVER_PACKAGE = Path(__file__).resolve().parents[3] / "packages" / "infinity_context_server"
if str(_SERVER_PACKAGE) not in sys.path:
    sys.path.insert(0, str(_SERVER_PACKAGE))

from infinity_context_server.memory_comparison_mem0_oss_contract import (  # noqa: E402
    evaluate_mem0_oss_runtime_capabilities,
)
from infinity_context_server.memory_comparison_mem0_oss_usage_attestation import (  # noqa: E402
    Mem0OssUsageAttestationRequest,
    verify_mem0_oss_usage_attestation,
)


def test_static_adapter_manifest_satisfies_the_root_v4_contract() -> None:
    manifest = capabilities_manifest(
        configured=True,
        extraction_mode="raw_passthrough",
        timestamp_attestation=TimestampAttestation(),
        source_identity_attested=False,
    )

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()


def test_refreshed_adapter_manifest_satisfies_the_root_v4_contract(monkeypatch) -> None:
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", "contract-probe-key")
    client = TestClient(create_app(FakeOssPort()))

    response = client.post(
        "/benchmark/attest-timestamp",
        headers={"X-Benchmark-Probe-Token": "contract-probe-key"},
        json={
            "run_id": "run-1",
            "probe_nonce": "ab" * 32,
            "target_identity_sha256": "f" * 64,
        },
    )

    assert response.status_code == 200
    assert (
        evaluate_mem0_oss_runtime_capabilities(
            response.json(),
            require_timestamp=True,
        )
        == ()
    )


def test_usage_attestation_satisfies_the_root_exact_verifier(monkeypatch) -> None:
    ingress_key = "contract-ingress-key"
    probe_token = "contract-probe-key"
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", ingress_key)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", probe_token)
    client = TestClient(create_app(FakeOssPort()))
    add_response = client.post(
        "/memories",
        headers={"X-API-Key": ingress_key},
        json={
            "messages": [{"role": "user", "content": "compatibility proof"}],
            "user_id": "user-1",
            "run_id": "run-1",
            "metadata": {"source_id": "source-1", "source_sha256": "a" * 64},
            "timestamp": 1_672_531_200,
        },
    )
    request = Mem0OssUsageAttestationRequest(
        run_id="run-1",
        probe_nonce="ab" * 32,
        target_identity_sha256="f" * 64,
    )
    response = client.post(
        "/benchmark/attest-usage",
        headers={
            "X-API-Key": ingress_key,
            "X-Benchmark-Probe-Token": probe_token,
        },
        json=request.payload(),
    )

    assert add_response.status_code == 200
    assert response.status_code == 200
    verified = verify_mem0_oss_usage_attestation(
        response.json(),
        benchmark_probe_token=probe_token,
        request=request,
        validated_at=datetime.now(UTC),
    )
    assert verified.evidence.mode == "raw_passthrough"
    assert verified.evidence.extraction_calls == 0
