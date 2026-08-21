from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_v5_recovery_projector import (
    ManagedV5RecoveryProjectorError,
    _read_dataset,
)


def test_recovery_projector_import_rejects_provider_dependency_reachability() -> None:
    script = r"""
import sys

class Trap:
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('subscription_chat', 'readiness', 'bounded_provider')
        if any(item in fullname for item in forbidden):
            raise RuntimeError(fullname)
        return None

sys.meta_path.insert(0, Trap())
import infinity_context_server.memory_comparison_managed_v5_live_cli_config_loader
import infinity_context_server.memory_comparison_managed_v5_recovery_projector
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_dataset_reader_uses_exact_regular_fd(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_bytes(b'{"exact":true}')

    assert _read_dataset(dataset) == b'{"exact":true}'


@pytest.mark.parametrize("kind", ("symlink", "fifo", "directory"))
def test_dataset_reader_rejects_nonregular_without_blocking(tmp_path: Path, kind: str) -> None:
    dataset = tmp_path / "dataset"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"payload")
        dataset.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(dataset)
    else:
        dataset.mkdir()

    with pytest.raises(ManagedV5RecoveryProjectorError, match="dataset_unreadable"):
        _read_dataset(dataset)
