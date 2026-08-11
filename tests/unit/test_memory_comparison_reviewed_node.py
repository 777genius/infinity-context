from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_reviewed_node as subject


def _node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    path = tmp_path / "node"
    raw = b"reviewed-node-fixture"
    path.write_bytes(raw)
    path.chmod(0o555)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(subject, "REVIEWED_NODE_EXECUTABLE_SHA256", digest)
    monkeypatch.setattr(subject, "REVIEWED_NODE_EXECUTABLE_SIZE_BYTES", len(raw))
    return path, digest


def test_euid_owned_immutable_exact_node_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node, digest = _node(tmp_path, monkeypatch)

    assert subject.require_reviewed_node_executable(node, digest) == node


@pytest.mark.parametrize("mode", (0o700, 0o755))
def test_owner_writable_node_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    node, digest = _node(tmp_path, monkeypatch)
    node.chmod(mode)

    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, digest)


def test_symlink_mutation_and_digest_drift_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node, digest = _node(tmp_path, monkeypatch)
    alias = tmp_path / "node-alias"
    alias.symlink_to(node)
    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(alias, digest)

    node.chmod(0o755)
    node.write_bytes(b"mutated-node-fixture!")
    node.chmod(0o555)
    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, digest)
    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, "0" * 64)


def test_foreign_owner_is_rejected_when_chown_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() != 0:
        pytest.skip("foreign owner requires root test sandbox")
    node, digest = _node(tmp_path, monkeypatch)
    os.chown(node, 65534, 65534)

    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, digest)


def test_hardlinked_node_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node, digest = _node(tmp_path, monkeypatch)
    os.link(node, tmp_path / "node-hardlink")

    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, digest)


def test_post_hash_same_size_mutation_with_restored_mtime_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node, digest = _node(tmp_path, monkeypatch)
    original = node.stat()
    real_fstat = subject.os.fstat
    calls = 0

    def mutate_before_final_fstat(descriptor: int) -> os.stat_result:
        nonlocal calls
        calls += 1
        if calls == 2:
            time.sleep(0.01)
            node.chmod(0o700)
            node.write_bytes(b"x" * original.st_size)
            node.chmod(0o555)
            os.utime(node, ns=(original.st_atime_ns, original.st_mtime_ns))
        return real_fstat(descriptor)

    monkeypatch.setattr(subject.os, "fstat", mutate_before_final_fstat)
    with pytest.raises(ValueError, match="reviewed_node_executable_invalid"):
        subject.require_reviewed_node_executable(node, digest)
    assert calls == 2
