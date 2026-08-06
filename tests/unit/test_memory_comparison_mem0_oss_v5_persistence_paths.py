from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_mem0_oss_v5_persistence import (
    Mem0V5EvidenceStoreError,
    SQLiteMem0V5EvidenceStore,
)

_AUTH_KEY = b"database-authentication-key-32byte"
_CHECKPOINT_KEY = b"external-checkpoint-key-32-bytes!!"


def _create(path: Path) -> SQLiteMem0V5EvidenceStore:
    return SQLiteMem0V5EvidenceStore.create(path=path, authentication_key=_AUTH_KEY)


def test_new_store_uses_private_owned_regular_paths(tmp_path: Path) -> None:
    parent = tmp_path / "private"
    path = parent / "evidence.sqlite3"
    store = _create(path)
    assert stat.S_IMODE(os.lstat(parent).st_mode) == 0o700
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            value = os.lstat(candidate)
            assert stat.S_ISREG(value.st_mode)
            assert value.st_uid == os.getuid()
            assert stat.S_IMODE(value.st_mode) == 0o600
    store.close()


@pytest.mark.parametrize("target", ["parent_mode", "database_mode", "wal_symlink"])
def test_reopen_rejects_unsafe_database_paths(tmp_path: Path, target: str) -> None:
    parent = tmp_path / "private"
    path = parent / "evidence.sqlite3"
    store = _create(path)
    checkpoint = store.issue_checkpoint(checkpoint_key=_CHECKPOINT_KEY)
    store.close()
    if target == "parent_mode":
        parent.chmod(0o755)
    elif target == "database_mode":
        path.chmod(0o644)
    else:
        Path(f"{path}-wal").symlink_to(path)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=_AUTH_KEY,
            checkpoint=checkpoint,
            checkpoint_key=_CHECKPOINT_KEY,
        )


def test_create_rejects_symlink_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        _create(linked / "evidence.sqlite3")
