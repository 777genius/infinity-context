from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deployment/compose.publishable.yaml"


def test_publishable_adapter_authority_environment_matches_read_only_mounts() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    adapter = compose["services"]["publishable-adapter"]
    environment = adapter["environment"]
    mounts = {item["target"]: item for item in adapter["volumes"]}
    source_root = environment["MEM0_V5_PHASE_C_AUTHORITY_DIR"]
    runtime_root = environment["MEM0_V5_RUNTIME_AUTHORITY_DIR"]

    assert source_root == "/opt/publishable/source/phase-c"
    assert runtime_root == "/opt/publishable/runtime"
    assert environment["MEM0_V5_RUNTIME_REPO"] == f"{runtime_root}/repo"
    assert mounts[source_root]["read_only"] is True
    assert mounts[runtime_root]["read_only"] is True
    assert all(not str(value).startswith("/mnt/volume_") for value in environment.values())
    assert all(
        not PurePosixPath(target).is_relative_to(PurePosixPath("/mnt/volume_ams3_1784742570542"))
        for target in mounts
    )
