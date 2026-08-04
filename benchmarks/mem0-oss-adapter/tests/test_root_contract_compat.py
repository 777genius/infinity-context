from __future__ import annotations

import sys
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


def test_static_adapter_manifest_satisfies_the_root_v3_contract() -> None:
    manifest = capabilities_manifest(
        configured=True,
        extraction_mode="raw_passthrough",
        timestamp_attestation=TimestampAttestation(),
        source_identity_attested=False,
    )

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()


def test_refreshed_adapter_manifest_satisfies_the_root_v3_contract(monkeypatch) -> None:
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
