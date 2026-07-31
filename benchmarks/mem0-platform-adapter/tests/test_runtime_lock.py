from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
import tomllib
from dataclasses import replace
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from mem0_platform_adapter.runtime_lock import (
    LockedArtifact,
    RuntimeLock,
    canonical_runtime_lock_sha256,
    load_runtime_lock,
    verify_wheel_metadata_closure,
)
from mem0_platform_adapter.runtime_pin import RUNTIME_PIN, RuntimePin


def test_compact_runtime_lock_matches_project_and_pin() -> None:
    root = Path(__file__).resolve().parents[1]
    lock_path = root / "runtime-lock.json"
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    runtime_lock = load_runtime_lock(lock_path, pin=RUNTIME_PIN)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    locked_versions = {
        artifact.distribution: artifact.version for artifact in runtime_lock.artifacts
    }
    declared = [
        Requirement(value)
        for value in (
            *project["project"]["dependencies"],
            *project["dependency-groups"]["dev"],
        )
    ]

    assert project["project"]["requires-python"] == ">=3.13,<3.14"
    assert not (root / "uv.lock").exists()
    assert len(lock_path.read_text(encoding="utf-8").splitlines()) <= 1000
    assert len(runtime_lock.artifacts) == RUNTIME_PIN.runtime_lock_artifact_count == 44
    assert canonical_runtime_lock_sha256(payload) == RUNTIME_PIN.runtime_lock_sha256
    for requirement in declared:
        name = canonicalize_name(requirement.name)
        assert name in locked_versions
        if requirement.specifier:
            assert requirement.specifier.contains(locked_versions[name], prereleases=True)


@pytest.mark.parametrize(
    "case",
    ("REMOVED_TRANSITIVE", "FALSE_VERSION", "DUPLICATE_WHEEL"),
    ids=("REMOVED_TRANSITIVE", "FALSE_VERSION", "DUPLICATE_WHEEL"),
)
def test_runtime_lock_rejects_adversarial_graph_mutations(tmp_path: Path, case: str) -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "runtime-lock.json").read_text(encoding="utf-8"))
    pin = RUNTIME_PIN
    expected = "artifact count"
    if case == "REMOVED_TRANSITIVE":
        payload["artifacts"] = [
            item for item in payload["artifacts"] if item["distribution"] != "anyio"
        ]
    elif case == "FALSE_VERSION":
        payload["artifacts"][0]["version"] = "999.0"
        pin = _pin_for_payload(payload)
        expected = "invalid runtime lock artifact"
    else:
        payload["artifacts"].insert(1, copy.deepcopy(payload["artifacts"][0]))
        pin = _pin_for_payload(payload)
        expected = "duplicate normalized distribution"
    tampered = tmp_path / "runtime-lock.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=expected):
        load_runtime_lock(tampered, pin=pin)


def test_runtime_lock_fails_closed_when_mem0_artifact_drifts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "runtime-lock.json").read_text(encoding="utf-8"))
    mem0_artifact = next(item for item in payload["artifacts"] if item["distribution"] == "mem0ai")
    mem0_artifact["sha256"] = "f" * 64
    tampered = tmp_path / "runtime-lock.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="digest does not match runtime pin"):
        load_runtime_lock(tampered, pin=RUNTIME_PIN)


def test_metadata_closure_rejects_missing_active_dependency(tmp_path: Path) -> None:
    alpha = _write_wheel(tmp_path, "alpha", "1.0", ["bravo>=1; python_version >= '3.13'"])
    runtime_lock = _synthetic_lock(alpha)

    with pytest.raises(RuntimeError, match=r"active dependency is absent.*alpha -> bravo"):
        verify_wheel_metadata_closure(runtime_lock, tmp_path)


def test_metadata_closure_rejects_incompatible_locked_version(tmp_path: Path) -> None:
    alpha = _write_wheel(tmp_path, "alpha", "1.0", ["bravo>=2"])
    bravo = _write_wheel(tmp_path, "bravo", "1.0", [])
    runtime_lock = _synthetic_lock(alpha, bravo)

    with pytest.raises(RuntimeError, match="locked dependency version is incompatible"):
        verify_wheel_metadata_closure(runtime_lock, tmp_path)


def test_metadata_identity_cannot_be_replaced_by_declared_lock_version(tmp_path: Path) -> None:
    alpha = _write_wheel(tmp_path, "alpha", "1.0", [], metadata_version="999.0")
    runtime_lock = _synthetic_lock(alpha)

    with pytest.raises(RuntimeError, match="wheel METADATA identity disagrees with lock"):
        verify_wheel_metadata_closure(runtime_lock, tmp_path)


def _pin_for_payload(payload: dict[str, object]) -> RuntimePin:
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list)
    return replace(
        RUNTIME_PIN,
        runtime_lock_sha256=canonical_runtime_lock_sha256(payload),
        runtime_lock_artifact_count=len(artifacts),
    )


def _write_wheel(
    directory: Path,
    distribution: str,
    version: str,
    requirements: list[str],
    *,
    metadata_version: str | None = None,
) -> LockedArtifact:
    filename = f"{distribution}-{version}-py3-none-any.whl"
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {distribution}",
        f"Version: {metadata_version or version}",
    ]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    wheel_path = directory / filename
    with ZipFile(wheel_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{distribution}-{version}.dist-info/METADATA",
            "\n".join(metadata) + "\n\n",
        )
    return LockedArtifact(
        distribution=distribution,
        version=version,
        filename=filename,
        url=f"https://files.pythonhosted.org/packages/test/{filename}",
        sha256=hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
    )


def _synthetic_lock(*artifacts: LockedArtifact) -> RuntimeLock:
    return RuntimeLock(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        sys_platform=sys.platform,
        machine=platform.machine().casefold(),
        artifacts=artifacts,
    )
