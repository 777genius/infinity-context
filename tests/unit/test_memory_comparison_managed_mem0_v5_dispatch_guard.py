from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from infinity_context_server import memory_comparison_managed_mem0_v5_dispatch_guard as subject
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    AtomicJournalManagedMem0V5SingleDispatchGuard,
    create_managed_mem0_v5_single_dispatch_guard,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError

ADMISSION = "a" * 64
OPERATION = "b" * 64
REQUEST = "c" * 64


def _path(tmp_path: Path) -> Path:
    root = tmp_path / "guard"
    root.mkdir(mode=0o700)
    return root / "single-dispatch.json"


def _claim(guard: AtomicJournalManagedMem0V5SingleDispatchGuard) -> None:
    guard.claim(
        admission_commitment_sha256=ADMISSION,
        operation_id_sha256=OPERATION,
        request_body_sha256=REQUEST,
    )


def test_first_claim_is_private_durable_and_restart_forbids_redispatch(tmp_path: Path) -> None:
    path = _path(tmp_path)
    guard = create_managed_mem0_v5_single_dispatch_guard(path)
    _claim(guard)

    metadata = path.stat()
    assert metadata.st_mode & 0o777 == 0o600
    assert metadata.st_nlink == 1
    record = json.loads(path.read_bytes())
    assert record["admission_commitment_sha256"] == ADMISSION
    assert record["operation_id_sha256"] == OPERATION
    assert record["request_body_sha256"] == REQUEST
    assert "single-dispatch.json" not in repr(guard)

    restarted = create_managed_mem0_v5_single_dispatch_guard(path)
    with pytest.raises(ManagedRunError, match="already claimed"):
        _claim(restarted)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("admission_commitment_sha256", "d" * 64),
        ("operation_id_sha256", "e" * 64),
        ("request_body_sha256", "f" * 64),
    ),
)
def test_existing_claim_rejects_every_wrong_tuple_field(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = _path(tmp_path)
    _claim(create_managed_mem0_v5_single_dispatch_guard(path))
    kwargs = {
        "admission_commitment_sha256": ADMISSION,
        "operation_id_sha256": OPERATION,
        "request_body_sha256": REQUEST,
    }
    kwargs[field] = value
    with pytest.raises(ManagedRunError, match="binding differs"):
        create_managed_mem0_v5_single_dispatch_guard(path).claim(**kwargs)


def test_concurrent_claim_is_an_exact_single_winner_cas(tmp_path: Path) -> None:
    path = _path(tmp_path)
    guards = tuple(create_managed_mem0_v5_single_dispatch_guard(path) for _ in range(8))
    barrier = Barrier(len(guards))

    def attempt(guard: AtomicJournalManagedMem0V5SingleDispatchGuard) -> bool:
        barrier.wait()
        try:
            _claim(guard)
        except ManagedRunError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=len(guards)) as executor:
        results = tuple(executor.map(attempt, guards))
    assert results.count(True) == 1
    assert results.count(False) == len(guards) - 1
    with pytest.raises(ManagedRunError):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))


def test_fsync_failure_leaves_fail_closed_restart_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path(tmp_path)
    real_fsync = subject.os.fsync
    calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated crash before durable acknowledgement")
        real_fsync(descriptor)

    monkeypatch.setattr(subject.os, "fsync", fail_first_fsync)
    with pytest.raises(ManagedRunError, match="claim failed"):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))
    assert path.exists()

    monkeypatch.setattr(subject.os, "fsync", real_fsync)
    with pytest.raises(ManagedRunError):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))


def test_tampered_or_partial_existing_state_never_allows_redispatch(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.write_bytes(b'{"schema_version":')
    os.chmod(path, 0o600)
    with pytest.raises(ManagedRunError, match="state is invalid"):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))


def test_symlink_and_hardlink_targets_are_rejected_without_mutation(tmp_path: Path) -> None:
    path = _path(tmp_path)
    victim = tmp_path / "victim"
    victim.write_bytes(b"unchanged")
    os.chmod(victim, 0o600)

    path.symlink_to(victim)
    with pytest.raises(ManagedRunError, match="state is invalid"):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))
    assert victim.read_bytes() == b"unchanged"

    path.unlink()
    os.link(victim, path)
    with pytest.raises(ManagedRunError, match="state is invalid"):
        _claim(create_managed_mem0_v5_single_dispatch_guard(path))
    assert victim.read_bytes() == b"unchanged"


def test_insecure_parent_and_existing_file_mode_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "insecure"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o755)
    with pytest.raises(ManagedRunError, match="storage is invalid"):
        create_managed_mem0_v5_single_dispatch_guard(root / "claim")

    secure_path = _path(tmp_path)
    secure_path.write_bytes(b"{}")
    os.chmod(secure_path, 0o644)
    with pytest.raises(ManagedRunError, match="state is invalid"):
        _claim(create_managed_mem0_v5_single_dispatch_guard(secure_path))


def test_invalid_binding_fails_before_creating_state(tmp_path: Path) -> None:
    path = _path(tmp_path)
    guard = create_managed_mem0_v5_single_dispatch_guard(path)
    with pytest.raises(ManagedRunError, match="binding is invalid"):
        guard.claim(
            admission_commitment_sha256="not-a-digest",
            operation_id_sha256=OPERATION,
            request_body_sha256=REQUEST,
        )
    assert not path.exists()
