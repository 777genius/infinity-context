from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.disposable_root
def test_external_launcher_issues_envelope_and_server_composition_consumes_it() -> None:
    if os.geteuid() != 0:
        raise AssertionError(
            "mandatory launcher identity separation requires the disposable root harness"
        )
    target = Path(tempfile.mkdtemp(prefix="infinity-supervisor-contract-", dir="/tmp"))
    target.chmod(0o755)
    try:
        completed = subprocess.run(
            [sys.executable, "tests/composition/supervisor_trust_launcher_process.py", str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(target)
    result = json.loads(completed.stdout)
    assert result["consumed"] is True
    assert result["source_release_verified"] is True
    assert result["pid"] == result["runtime_pid"]
    assert result["runtime_pid"] != result["launcher_pid"]
    assert result["launcher_uid"] == 0
    assert result["runtime_uid"] > 0
    assert result["runtime_uid"] != result["launcher_uid"]
    assert result["runtime_source_root"] == str(target / "runtime-source")
    assert result["runtime_source_mode"] == 0o555
    assert result["runtime_source_owner_uid"] == result["launcher_uid"]
    assert result["runtime_source_owner_uid"] != result["runtime_uid"]
    assert result["registry_owner_uid"] == result["launcher_uid"]
    assert result["registry_owner_uid"] != result["runtime_uid"]
    assert result["registry_mode"] == 0o444
    assert result["supervisor_key_id"] == "deployment-supervisor-2026-08"
    assert result["trust_registry_generation"] == 41
    assert len(result["trust_root_sha256"]) == 64
    assert len(result["installed_release_identity_sha256"]) == 64
    assert len(result["lifecycle_identity_sha256"]) == 64
