from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
FROZEN_V4_TREE = "5d640f4ea0164f18a5e8cff2bd5469b1e7eea201"


def test_complete_v4_tree_and_working_bytes_remain_exact() -> None:
    assert _git("rev-parse", "HEAD:benchmarks/mem0-oss-adapter") == FROZEN_V4_TREE
    rows = _git("ls-tree", "-r", "HEAD", "benchmarks/mem0-oss-adapter").splitlines()
    assert len(rows) == 36
    for row in rows:
        metadata, relative = row.split("\t", 1)
        expected_blob = metadata.split()[2]
        actual_blob = _git("hash-object", relative)
        assert actual_blob == expected_blob, relative


def test_dependency_lock_is_not_accepted_as_a_source_trust_root() -> None:
    runtime_lock = json.loads((ROOT / "runtime-lock.json").read_text())
    assert "v5_source_authority" not in runtime_lock


def test_runtime_lock_pins_key_benchmark_dependencies() -> None:
    lock = json.loads((ROOT / "runtime-lock.json").read_text())
    versions = {item["distribution"]: item["version"] for item in lock["artifacts"]}
    assert versions["mem0ai"] == "2.0.15"
    assert versions["qdrant-client"] == "1.18.0"
    assert versions["fastembed"] == "0.8.0"
    assert lock["python_version"] == "3.11"
    assert lock["machine"] == "x86_64"
    assert lock["sys_platform"] == "linux"
    assert lock["runtime_metadata"]["provider_attempts_per_dispatch"] == 1
    assert lock["runtime_metadata"]["status_provider_attempts"] == 0


def test_uv_and_deploy_runtime_locks_have_one_exact_runtime_closure() -> None:
    runtime = json.loads((ROOT / "runtime-lock.json").read_text())
    uv = tomllib.loads((ROOT / "uv.lock").read_text())
    resolved = {item["name"].lower().replace("_", "-"): item["version"] for item in uv["package"]}
    for artifact in runtime["artifacts"]:
        name = artifact["distribution"].lower().replace("_", "-")
        assert resolved[name] == artifact["version"]


def test_dockerfile_is_pinned_non_root_and_loopback_only() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93" in dockerfile
    assert "USER 65532:65532" in dockerfile
    assert '"--host", "127.0.0.1"' in dockerfile
    assert '"--no-access-log"' in dockerfile
    assert '"--no-proxy-headers"' in dockerfile
    assert "COPY mem0-oss-adapter/runtime-pin.json ./runtime-pin.json" in dockerfile
    assert "mem0-oss-adapter-v5/uv.lock" in dockerfile
    assert "runtime_lock_uv_closure_mismatch" in dockerfile
    assert "COPY --from=source-authority manifest.json" in dockerfile
    assert "verify_source_authority" in dockerfile
    assert "id=source_authority_manifest_sha256,required=true" in dockerfile
    assert "COPY mem0-oss-adapter-v5/runtime-pin.json" not in dockerfile
    assert "ARG " not in dockerfile
    assert "BEARER=" not in dockerfile
    assert "TOKEN=" not in dockerfile


def test_frozen_v4_runtime_pin_import_and_model_stage_preflight(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    shutil.copytree(
        REPOSITORY / "benchmarks/mem0-oss-adapter/mem0_oss_adapter",
        app / "mem0_oss_adapter",
    )
    shutil.copy2(
        REPOSITORY / "benchmarks/mem0-oss-adapter/runtime-pin.json",
        app / "runtime-pin.json",
    )
    scripts = app / "scripts"
    scripts.mkdir()
    stage = scripts / "stage_fastembed_model.py"
    shutil.copy2(
        REPOSITORY / "benchmarks/mem0-oss-adapter/scripts/stage_fastembed_model.py",
        stage,
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(app),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    imported = subprocess.run(
        [sys.executable, "-c", "from mem0_oss_adapter.runtime_pin import RUNTIME_PIN"],
        cwd=app,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
    staged = subprocess.run(
        [sys.executable, str(stage), "--help"],
        cwd=app,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert staged.returncode == 0, staged.stderr


def test_hosted_compose_has_no_secret_values_or_external_listener() -> None:
    compose = yaml.safe_load((ROOT / "compose.hosted-canary.yaml").read_text())
    services = compose["services"]
    adapter = services["mem0-oss-adapter-v5"]
    qdrant = services["mem0-oss-v5-qdrant"]
    assert adapter["network_mode"] == "host"
    assert qdrant["network_mode"] == "host"
    assert "ports" not in adapter and "ports" not in qdrant
    assert adapter["read_only"] is True and qdrant["read_only"] is True
    assert adapter["cap_drop"] == ["ALL"]
    assert set(adapter["build"]["additional_contexts"]) == {
        "source-authority",
        "phase-c-authority",
    }
    assert qdrant["cap_drop"] == ["ALL"]
    environment = adapter["environment"]
    assert environment["MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE"] == (
        "/run/source-authority/manifest.json"
    )
    assert environment["MEM0_V5_PHASE_C_AUTHORITY_DIR"].endswith("/sources/9499b9c2")
    assert environment["MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE"].endswith(
        "/source-authority-pin/manifest.sha256"
    )
    build_pin_source = compose["secrets"]["source-authority-manifest-sha256"]["file"]
    runtime_pin = next(
        volume
        for volume in adapter["volumes"]
        if volume["target"] == "/run/source-authority-pin/manifest.sha256"
    )
    assert runtime_pin["read_only"] is True
    assert runtime_pin["source"] == build_pin_source
    assert build_pin_source.startswith("${MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE:")
    private_names = [
        name for name in environment if any(term in name for term in ("BEARER", "HMAC"))
    ]
    assert private_names
    assert all(name.endswith("_FILE") for name in private_names)
    assert all(str(environment[name]).startswith("/run/secrets/") for name in private_names)
    assert environment["MEM0_V5_QDRANT_ORIGIN"] == "http://127.0.0.1:6334"
    command = " ".join(adapter["healthcheck"]["test"])
    assert "127.0.0.1:19091/health" in command


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
