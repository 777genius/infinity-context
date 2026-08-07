from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
import yaml

from e2e.canonical import canonical_sha256
from e2e.contracts import (
    LOGICAL_RUNTIME_ROUTE,
    ROUTE_SHA256,
    RequestProjection,
    RunFixture,
    RuntimeOwnership,
)
from e2e.http_client import AdapterHttpClient


class _Projector:
    def project(self, _unit: object, *, current_date: str) -> RequestProjection:
        assert current_date == "2026-08-06"
        return RequestProjection("1" * 64, "2" * 64, "3" * 64)


class _Transport:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value
        self.seen: tuple[str, dict[str, str], bytes] | None = None

    def post(self, path: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        self.seen = path, headers, body
        return 200, json.dumps(self.value, separators=(",", ":")).encode()


def test_fixture_materializes_exact_sealed_input(tmp_path) -> None:
    fixture = RunFixture.create(_Projector())
    root = tmp_path / "provider-free-run"
    directories = fixture.materialize(root)
    manifest_path = root / "input" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    unsigned = {key: value for key, value in manifest.items() if key != "sealed_payload_sha256"}
    assert manifest["sealed_payload_sha256"] == canonical_sha256(unsigned)
    assert manifest["ingestion_root_sha256"] == fixture.ingestion_root_sha256
    assert fixture.dispatch_body()["request_body_sha256"] == "1" * 64
    assert set(directories) == {"input", "state", "secrets", "fake-runtime"}
    memory_config = root / "state" / "e2e-mem0-config"
    assert memory_config.is_dir() and memory_config.stat().st_mode & 0o777 == 0o700
    assert manifest_path.stat().st_mode & 0o777 == 0o400
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (root / "secrets").iterdir())


def test_route_digest_matches_actual_adapter_raw_utf8_contract() -> None:
    from mem0_oss_adapter_v5.subscription_runtime import (
        SUBSCRIPTION_RUNTIME_ROUTE_BINDING,
        SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    )

    assert LOGICAL_RUNTIME_ROUTE == SUBSCRIPTION_RUNTIME_ROUTE_BINDING
    assert ROUTE_SHA256 == SUBSCRIPTION_RUNTIME_ROUTE_SHA256
    assert ROUTE_SHA256 == "aaff3d27c7ca1b964a86355622e87b2bbd7841722dbcff782292ea02e1fa0935"
    assert canonical_sha256(LOGICAL_RUNTIME_ROUTE) != ROUTE_SHA256


def test_materialize_rejects_wrong_effective_host_mapped_owner_before_write(
    tmp_path, monkeypatch
) -> None:
    fixture = RunFixture.create(_Projector())
    monkeypatch.setattr("e2e.contracts.os.geteuid", lambda: 0)
    monkeypatch.setattr("e2e.contracts.os.getegid", lambda: 0)
    root = tmp_path / "must-not-exist"
    ownership = RuntimeOwnership(296603, 296603, 65532, 65532)
    with pytest.raises(ValueError, match="e2e_host_mapped_owner_mismatch"):
        fixture.materialize(root, ownership=ownership)
    assert not root.exists()


def test_rootless_mapping_keeps_host_and_container_identities_distinct() -> None:
    ownership = RuntimeOwnership(296603, 296603, 65532, 65532)
    assert ownership.public_attestation() == {
        "host_mapped_uid": 296603,
        "host_mapped_gid": 296603,
        "container_runtime_uid": 65532,
        "container_runtime_gid": 65532,
    }
    with pytest.raises(ValueError, match="e2e_rootless_identity_conflated"):
        RuntimeOwnership(65532, 65532, 65532, 65532)


@pytest.mark.parametrize(
    "values",
    [
        (0, 296603, 65532, 65532),
        (296603, 0, 65532, 65532),
        (2**31, 296603, 65532, 65532),
        (296603, 296603, 0, 65532),
    ],
)
def test_rootless_mapping_rejects_unbounded_or_root_identities(values) -> None:
    with pytest.raises(ValueError, match="e2e_runtime_identity_invalid"):
        RuntimeOwnership(*values)


def test_rootless_mapping_rejects_non_pinned_container_identity() -> None:
    with pytest.raises(ValueError, match="e2e_container_runtime_identity_invalid"):
        RuntimeOwnership(296603, 296603, 65531, 65532)


def test_compose_binds_only_pinned_container_identity_not_host_mapping() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "compose.provider-free-e2e.yaml"
    compose = yaml.safe_load(compose_path.read_text())
    assert {name: service["user"] for name, service in compose["services"].items()} == {
        "e2e-network-anchor": "65532:65532",
        "mem0-oss-v5-fake-runtime": "65532:65532",
        "mem0-oss-v5-qdrant": "65532:65532",
        "mem0-oss-adapter-v5": "65532:65532",
    }


def test_qdrant_snapshots_stay_on_writable_storage_tmpfs() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "compose.provider-free-e2e.yaml"
    compose = yaml.safe_load(compose_path.read_text())
    service = compose["services"]["mem0-oss-v5-qdrant"]
    environment = service["environment"]
    storage_path = PurePosixPath(environment["QDRANT__STORAGE__STORAGE_PATH"])
    snapshots_path = PurePosixPath(environment["QDRANT__STORAGE__SNAPSHOTS_PATH"])
    tmpfs_mounts = {
        PurePosixPath(str(entry).split(":", maxsplit=1)[0]) for entry in service["tmpfs"]
    }

    assert service["read_only"] is True
    assert storage_path.is_absolute()
    assert snapshots_path.is_absolute()
    assert snapshots_path == storage_path / "snapshots"
    assert ".." not in snapshots_path.parts
    assert storage_path in tmpfs_mounts


def test_http_client_matches_pr34_request_commitment_and_exact_response() -> None:
    fixture = RunFixture.create(_Projector())
    value = {
        "admission_commitment_sha256": fixture.admission_commitment_sha256,
        "runtime_binding_commitment_sha256": "4" * 64,
        "accepted": True,
    }
    transport = _Transport(value)
    client = AdapterHttpClient(bearer_token="b" * 32, transport=transport)
    body = {
        "admission_commitment_sha256": fixture.admission_commitment_sha256,
        "ingestion_manifest_sha256": fixture.ingestion_manifest_sha256,
        "ingestion_root_sha256": fixture.ingestion_root_sha256,
        "expected_operation_count": 1,
        "route_sha256": "5" * 64,
    }
    receipt = client.admit(body, "6" * 64)
    assert receipt.accepted is True
    assert transport.seen is not None
    path, headers, encoded = transport.seen
    assert path == "/v5/runs/admit"
    assert headers["X-Request-Commitment-SHA256"] == canonical_sha256(body)
    assert headers["Idempotency-Key"] == "6" * 64
    assert json.loads(encoded) == body


def test_http_client_rejects_response_schema_drift() -> None:
    transport = _Transport({"accepted": True, "raw_prompt": "private"})
    client = AdapterHttpClient(bearer_token="b" * 32, transport=transport)
    with pytest.raises(RuntimeError, match="e2e_admission_receipt_invalid"):
        client.admit(
            {
                "admission_commitment_sha256": "1" * 64,
                "ingestion_manifest_sha256": "2" * 64,
                "ingestion_root_sha256": "3" * 64,
                "expected_operation_count": 1,
                "route_sha256": "4" * 64,
            },
            "5" * 64,
        )
