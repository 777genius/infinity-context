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
    assert adapter["command"][-4:] == ["--host", "127.0.0.1", "--port", "8080"]
    assert adapter["environment"]["MEM0_OSS_QDRANT_HOST"] == "127.0.0.1"
    assert adapter["environment"]["MEM0_OSS_SUBSCRIPTION_BRIDGE_URL"].endswith(
        "http://127.0.0.1:19090/v1}"
    )
    assert any(item.startswith("/var/lib/mem0-oss:") for item in adapter["tmpfs"])
    assert qdrant["platform"] == "linux/amd64"
    assert qdrant["image"].endswith(
        "@sha256:ecc81d662bb9bb734db879b94461eb44be38604fc259491d478ad7e673238a0d"
    )
    assert qdrant["network_mode"] == "host"
    assert "ports" not in qdrant
    assert qdrant["environment"]["QDRANT__SERVICE__HOST"] == "127.0.0.1"
    assert any(item.startswith("/qdrant/storage:") for item in qdrant["tmpfs"])
    assert "volumes" not in payload
