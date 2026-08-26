from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from mem0_oss_adapter_v5.source_authority import (
    SourceAuthorityError,
    verify_source_authority,
)
from tools.generate_source_authority import (
    PhaseCAuthority,
    encoded_manifest,
    runtime_attestation_contract,
    source_manifest,
    write_authority,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
FROZEN_V4_TREE = "5d640f4ea0164f18a5e8cff2bd5469b1e7eea201"
LIVE_SOURCE_COMMIT = "a7c4e9e56a9e2779cce6edef917368dab23056d0"


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


def test_adapter_builds_exclude_python_bytecode_from_the_exact_context() -> None:
    expected_patterns = ["**/__pycache__", "**/*.pyc", "**/*.pyo"]

    for compose_name in (
        "compose.hosted-canary.yaml",
        "compose.provider-free-e2e.yaml",
    ):
        compose_path = ROOT / compose_name
        compose = yaml.safe_load(compose_path.read_text())
        build = compose["services"]["mem0-oss-adapter-v5"]["build"]
        context = (compose_path.parent / build["context"]).resolve()
        dockerfile = (context / build["dockerfile"]).resolve()
        dockerfile_ignore = dockerfile.with_name(f"{dockerfile.name}.dockerignore")

        assert context == REPOSITORY / "benchmarks"
        assert dockerfile == ROOT / "Dockerfile"
        assert dockerfile_ignore == ROOT / "Dockerfile.dockerignore"
        assert dockerfile_ignore.read_text().splitlines() == expected_patterns


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


def test_pin_b_reproduces_live_v2_archive_and_verifies_exact_staged_closure(
    tmp_path: Path,
) -> None:
    committed = json.loads((ROOT / "authority/manifest.json").read_bytes())
    phase = committed["phase_c_authority"]
    generated, staged = source_manifest(
        REPOSITORY,
        committed["source_commit_sha1"],
        PhaseCAuthority(**phase),
    )
    assert committed == generated
    assert committed["source_commit_sha1"] == LIVE_SOURCE_COMMIT
    manifest_sha256 = hashlib.sha256(encoded_manifest(committed)).hexdigest()
    manifest_digest = (ROOT / "authority/manifest.sha256").read_bytes()
    assert manifest_digest == manifest_sha256.encode("ascii") and len(manifest_digest) == 64
    runtime_source = json.loads((ROOT / "authority/runtime-pin.json").read_bytes())["source_a"]
    assert runtime_source == {
        "closure_algorithm": committed["closure_algorithm"],
        "closure_sha256": committed["closure_sha256"],
        "commit_sha1": committed["source_commit_sha1"],
        "manifest_file_count": len(committed["files"]),
        "manifest_sha256": manifest_sha256,
        "tree_sha1": committed["source_tree_sha1"],
    }
    head_generated, _ = source_manifest(
        REPOSITORY,
        "HEAD",
        PhaseCAuthority(**phase),
    )
    assert head_generated["files"] == committed["files"]
    assert head_generated["closure_algorithm"] == committed["closure_algorithm"]
    assert head_generated["closure_sha256"] == committed["closure_sha256"]
    assert {item["path"] for item in committed["files"]}.issuperset(
        {
            "mem0_oss_adapter_v5/evidence_contracts.py",
            "mem0_oss_adapter_v5/evidence_service.py",
            "mem0_oss_adapter_v5/request_binding.py",
            "mem0_oss_adapter_v5/runtime_attestation.py",
        }
    )

    installed = tmp_path / "installed"
    for relative, content in staged.items():
        target = installed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    phase_root = tmp_path / "phase-c"
    attestation = phase_root / "attestation"
    attestation.mkdir(parents=True)
    release = b"provider-free-phase-c-release-fixture\n"
    fixture_phase = PhaseCAuthority(
        infinity_commit_sha1=phase["infinity_commit_sha1"],
        infinity_tree_sha1=phase["infinity_tree_sha1"],
        release_manifest_sha256=hashlib.sha256(release).hexdigest(),
    )
    (attestation / "commit.txt").write_text(f"{fixture_phase.infinity_commit_sha1}\n")
    (attestation / "tree.txt").write_text(f"{fixture_phase.infinity_tree_sha1}\n")
    (attestation / "release-files.sha256").write_bytes(release)
    fixture_manifest, _ = source_manifest(REPOSITORY, LIVE_SOURCE_COMMIT, fixture_phase)
    manifest_path = tmp_path / "manifest.json"
    manifest_bytes = encoded_manifest(fixture_manifest)
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    verified = verify_source_authority(
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        installed_root=installed,
        phase_c_authority_root=phase_root,
    )
    assert verified.source_commit_sha1 == LIVE_SOURCE_COMMIT
    assert verified.closure_sha256 == committed["closure_sha256"]

    (installed / "mem0_oss_adapter_v5/evidence_service.py").unlink()
    with pytest.raises(SourceAuthorityError, match="source_authority_inventory_invalid"):
        verify_source_authority(
            manifest_path=manifest_path,
            expected_manifest_sha256=manifest_sha256,
            installed_root=installed,
            phase_c_authority_root=phase_root,
        )


def _runtime_contract_staged_source() -> dict[str, bytes]:
    package = ROOT / "mem0_oss_adapter_v5"
    return {
        f"mem0_oss_adapter_v5/{name}": (package / name).read_bytes()
        for name in ("runtime_attestation.py", "extraction_contract.py")
    }


def test_generator_upgrades_old_runtime_pin_from_archived_source_contract(
    tmp_path: Path,
) -> None:
    manifest = json.loads((ROOT / "authority/manifest.json").read_bytes())
    runtime_pin = json.loads((ROOT / "authority/runtime-pin.json").read_bytes())
    added = {
        "runtime_attestation_request_schema",
        "runtime_attestation_response_schema",
        "runtime_attestation_route_contract_sha256",
        "requested_output_tokens",
        "output_limit_enforced",
        "usage_attestation_required",
    }
    for name in added:
        runtime_pin["runtime_contract"].pop(name, None)
    runtime_pin["runtime_contract"]["preserved_generator_fixture"] = "unchanged"
    runtime_pin_file = tmp_path / "runtime-pin.json"
    runtime_pin_file.write_text(json.dumps(runtime_pin))
    authority = tmp_path / "authority"
    authority.mkdir()

    write_authority(
        authority_directory=authority,
        runtime_pin_file=runtime_pin_file,
        manifest=manifest,
        staged=_runtime_contract_staged_source(),
    )

    generated = json.loads(runtime_pin_file.read_bytes())["runtime_contract"]
    assert generated["preserved_generator_fixture"] == "unchanged"
    assert {name: generated[name] for name in added} == {
        "runtime_attestation_request_schema": (
            "mem0-oss-adapter-v5.runtime-attestation-request.v1"
        ),
        "runtime_attestation_response_schema": ("mem0-oss-adapter-v5.runtime-attestation.v1"),
        "runtime_attestation_route_contract_sha256": (
            "7ed6947e7694feebff43e5b33e1c99b462462c437be808d078442c4aaac0bf49"
        ),
        "requested_output_tokens": 4096,
        "output_limit_enforced": False,
        "usage_attestation_required": False,
    }


def test_generator_rejects_tampered_source_and_conflicting_contract(tmp_path: Path) -> None:
    staged = _runtime_contract_staged_source()
    exact = runtime_attestation_contract(staged).payload()
    runtime_pin = json.loads((ROOT / "authority/runtime-pin.json").read_bytes())
    runtime_pin["runtime_contract"].update(exact)
    runtime_pin_file = tmp_path / "runtime-pin.json"
    runtime_pin_file.write_text(json.dumps(runtime_pin))
    authority = tmp_path / "authority"
    authority.mkdir()
    sentinels = {"manifest.json": b"old-manifest", "manifest.sha256": b"old-digest"}
    for name, raw in sentinels.items():
        (authority / name).write_bytes(raw)
    manifest = json.loads((ROOT / "authority/manifest.json").read_bytes())
    tampered = dict(staged)
    tampered["mem0_oss_adapter_v5/runtime_attestation.py"] = staged[
        "mem0_oss_adapter_v5/runtime_attestation.py"
    ].replace(b'("POST", "/v5/runs/search")', b'("POST", "/v5/runs/tampered")')
    with pytest.raises(ValueError, match="runtime_pin_runtime_contract_invalid"):
        write_authority(
            authority_directory=authority,
            runtime_pin_file=runtime_pin_file,
            manifest=manifest,
            staged=tampered,
        )
    assert {name: (authority / name).read_bytes() for name in sentinels} == sentinels
    assert json.loads(runtime_pin_file.read_bytes()) == runtime_pin

    runtime_pin["runtime_contract"]["requested_output_tokens"] = 2048
    runtime_pin_file.write_text(json.dumps(runtime_pin))
    with pytest.raises(ValueError, match="runtime_pin_runtime_contract_invalid"):
        write_authority(
            authority_directory=authority,
            runtime_pin_file=runtime_pin_file,
            manifest=manifest,
            staged=staged,
        )

    assert {name: (authority / name).read_bytes() for name in sentinels} == sentinels
    assert json.loads(runtime_pin_file.read_bytes()) == runtime_pin


def test_live_micro_canary_qdrant_snapshots_use_writable_state_path() -> None:
    compose = yaml.safe_load((ROOT / "compose.live-micro-canary.override.yaml").read_text())
    qdrant = compose["services"]["mem0-oss-v5-qdrant"]
    assert qdrant["read_only"] is True
    assert qdrant["environment"]["QDRANT__STORAGE__STORAGE_PATH"] == "/qdrant/storage"
    assert qdrant["environment"]["QDRANT__STORAGE__SNAPSHOTS_PATH"] == ("/qdrant/storage/snapshots")
    state_mount = next(
        volume for volume in qdrant["volumes"] if volume["target"] == "/qdrant/storage"
    )
    assert state_mount.get("read_only") is not True
    assert state_mount["source"].startswith("${MEM0_V5_QDRANT_STATE_DIR:")
    adapter = compose["services"]["mem0-oss-adapter-v5"]
    mounts = {volume["target"]: volume for volume in adapter["volumes"]}
    environment = adapter["environment"]
    assert mounts[environment["MEM0_V5_RUNTIME_AUTHORITY_DIR"]]["read_only"] is True
    assert mounts[environment["MEM0_V5_PHASE_C_AUTHORITY_DIR"]]["read_only"] is True


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
    assert environment["MEM0_V5_RUNTIME_AUTHORITY_DIR"].endswith(
        "/runtimes/subscription-runtime/e904ec95"
    )
    assert environment["MEM0_V5_RUNTIME_REPO"] == (
        f"{environment['MEM0_V5_RUNTIME_AUTHORITY_DIR']}/repo"
    )
    assert environment["MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE"].endswith(
        "/source-authority-pin/manifest.sha256"
    )
    assert environment["MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE"] == (
        "/run/secrets/runtime-transport-origin"
    )
    assert "MEM0_V5_RUNTIME_ORIGIN_FILE" not in environment
    assert environment["MEM0_V5_RUNTIME_ATTESTATION_SECRET_FILE"] == (
        "/run/secrets/runtime-attestation-secret"
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
