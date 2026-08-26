"""Separate test-only deployment launcher; private material never enters the runtime."""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("infinity_context_adapters", "infinity_context_core", "infinity_context_server"):
    sys.path.insert(0, str(ROOT / "packages" / package))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from infinity_context_adapters.postgres import (  # noqa: E402
    RuntimeProcessSupervisor,
    registry_document,
)
from infinity_context_server.build_identity import (  # noqa: E402
    repository_source_release_identity,
)

_SOURCE_DIRECTORIES = ("packages", "tests", "scripts", "docs", ".github")
_SOURCE_FILES = ("pyproject.toml", "uv.lock")
_IGNORED_NAMES = (
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
)


def _stage_verified_runtime_source(target: Path, release) -> Path:
    staged_root = target / "runtime-source"
    staged_root.mkdir(mode=0o755)
    for name in _SOURCE_DIRECTORIES:
        shutil.copytree(
            ROOT / name,
            staged_root / name,
            symlinks=True,
            ignore=shutil.ignore_patterns(*_IGNORED_NAMES),
        )
    for name in _SOURCE_FILES:
        shutil.copy2(ROOT / name, staged_root / name)

    for path in sorted(staged_root.rglob("*"), reverse=True):
        if path.is_symlink():
            raise RuntimeError("disposable runtime source cannot contain symlinks")
        path.chmod(0o555 if path.is_dir() else 0o444)
    staged_root.chmod(0o555)

    observed = repository_source_release_identity(
        staged_root,
        service_revision=release.service_revision,
    )
    if observed != release:
        raise RuntimeError("disposable runtime source release identity mismatch")
    return staged_root


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve()
    key_id = "deployment-supervisor-2026-08"
    generation = 41
    signing_key = Ed25519PrivateKey.generate()
    release = repository_source_release_identity(ROOT)
    runtime_root = _stage_verified_runtime_source(target, release)
    public_key = (
        signing_key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    registry, digest = registry_document(
        registry_id="deployment-supervisor-test",
        generation=generation,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_until=datetime.now(UTC) + timedelta(minutes=10),
        keys=((key_id, public_key),),
        installed_release=release,
    )
    registry_path = target / "supervisor-trust-registry.json"
    registry_path.write_bytes(registry)
    registry_path.chmod(0o444)
    nobody = pwd.getpwnam("nobody")
    environment = dict(os.environ)
    local_packages = os.pathsep.join(
        str(runtime_root / "packages" / package)
        for package in (
            "infinity_context_server",
            "infinity_context_adapters",
            "infinity_context_core",
            "infinity_context_contracts",
        )
    )
    environment["PYTHONPATH"] = local_packages
    environment.update(
        {
            "TEST_SUPERVISOR_REGISTRY_PATH": str(registry_path),
            "TEST_SUPERVISOR_ROOT_SHA256": digest,
            "TEST_SUPERVISOR_KEY_ID": key_id,
            "TEST_SUPERVISOR_REGISTRY_GENERATION": str(generation),
            "TEST_RUNTIME_UID": str(nobody.pw_uid),
            "TEST_RUNTIME_GID": str(nobody.pw_gid),
            "TEST_RELEASE_REVISION": release.service_revision,
            "TEST_RUNTIME_SOURCE_ROOT": str(runtime_root),
        }
    )

    runtime = subprocess.Popen(
        [
            sys.executable,
            str(runtime_root / "tests/composition/supervisor_trust_runtime_process.py"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    supervisor = RuntimeProcessSupervisor(
        key_id=key_id,
        process=runtime,
        trust_root_sha256=digest,
        trust_registry_generation=generation,
        installed_release=release,
        signing_key=signing_key,
    )
    output, error = runtime.communicate(json.dumps(asdict(supervisor.owner())), timeout=90)
    if runtime.returncode != 0:
        raise SystemExit(error[-4000:])
    result = json.loads(output)
    result["launcher_pid"] = os.getpid()
    result["launcher_uid"] = os.geteuid()
    result["runtime_pid"] = runtime.pid
    result["source_release_verified"] = True
    print(json.dumps(result, sort_keys=True))
