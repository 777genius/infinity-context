from __future__ import annotations

from pathlib import Path

import yaml


def test_hosted_canary_compose_is_loopback_only_and_disposable() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "compose.hosted-canary.yaml"
    payload = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert set(payload) == {"services"}
    assert set(payload["services"]) == {"adapter", "qdrant"}
    adapter = payload["services"]["adapter"]
    qdrant = payload["services"]["qdrant"]
    assert adapter["platform"] == "linux/amd64"
    assert adapter["network_mode"] == "host"
    assert "ports" not in adapter
    assert adapter["read_only"] is True
    assert adapter["environment"]["MEM0_OSS_QDRANT_HOST"] == "127.0.0.1"
    assert adapter["environment"]["MEM0_OSS_SUBSCRIPTION_BRIDGE_URL"].endswith(
        "http://127.0.0.1:19090/v1}"
    )
    assert adapter["environment"].items() >= {
        "HOME": "/var/lib/mem0-oss",
        "XDG_STATE_HOME": "/var/lib/mem0-oss/state",
        "XDG_CACHE_HOME": "/var/lib/mem0-oss/cache",
        "XDG_DATA_HOME": "/var/lib/mem0-oss/data",
        "XDG_CONFIG_HOME": "/var/lib/mem0-oss/config",
    }.items()
    assert any(item.startswith("/var/lib/mem0-oss:") for item in adapter["tmpfs"])
    assert adapter["command"][:2] == ["/bin/sh", "-ec"]
    bootstrap = adapter["command"][2]
    assert "umask 077" in bootstrap
    for directory in (
        "/var/lib/mem0-oss/.mem0",
        "/var/lib/mem0-oss/state",
        "/var/lib/mem0-oss/cache",
        "/var/lib/mem0-oss/data",
        "/var/lib/mem0-oss/config",
    ):
        assert directory in bootstrap
    assert (
        "exec /opt/mem0-oss-venv/bin/uvicorn mem0_oss_adapter.app:app "
        "--host 127.0.0.1 --port 8080"
    ) in bootstrap
    assert qdrant["platform"] == "linux/amd64"
    assert qdrant["image"].endswith(
        "@sha256:ecc81d662bb9bb734db879b94461eb44be38604fc259491d478ad7e673238a0d"
    )
    assert qdrant["network_mode"] == "host"
    assert "ports" not in qdrant
    assert qdrant["read_only"] is True
    assert qdrant["entrypoint"] == []
    assert qdrant["command"] == ["/qdrant/qdrant"]
    assert qdrant["environment"]["QDRANT__SERVICE__HOST"] == "127.0.0.1"
    assert qdrant["environment"].items() >= {
        "QDRANT__STORAGE__STORAGE_PATH": "/qdrant/storage",
        "QDRANT__STORAGE__SNAPSHOTS_PATH": "/qdrant/storage/snapshots",
    }.items()
    assert any(item.startswith("/qdrant/storage:") for item in qdrant["tmpfs"])
    assert "volumes" not in payload
