from __future__ import annotations

import os
import stat
from pathlib import Path

import publishable_mem0_v5.immutable_evidence as subject
import pytest
from publishable_mem0_v5.immutable_evidence import (
    ImmutableEvidenceError,
    read_immutable_json,
    require_immutable_json_unchanged,
    write_immutable_json,
)

PREFIX = "mapped-owner-"


def _private(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _write(directory: Path, *, uid: int | None = None, gid: int | None = None):
    return write_immutable_json(
        directory=directory,
        prefix=PREFIX,
        payload={"value": "safe"},
        expected_uid=os.geteuid() if uid is None else uid,
        expected_gid=os.getegid() if gid is None else gid,
    )


def test_write_read_and_unchanged_require_exact_owner_and_mode(tmp_path: Path) -> None:
    directory = _private(tmp_path / "evidence")
    evidence = _write(directory)

    value = evidence.path.stat()
    assert (value.st_uid, value.st_gid, value.st_mode & 0o777) == (
        os.geteuid(),
        os.getegid(),
        0o600,
    )
    assert require_immutable_json_unchanged(
        evidence,
        directory=directory,
        prefix=PREFIX,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    ) == evidence


def test_existing_file_is_not_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _private(tmp_path / "evidence")
    evidence = _write(directory)
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "fchown", lambda _fd, uid, gid: calls.append((uid, gid)))

    assert _write(directory) == evidence
    assert calls == []


@pytest.mark.parametrize("operation", ["fchown", "fchmod", "write", "fsync"])
def test_failed_new_file_is_removed_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    directory = _private(tmp_path / "evidence")
    original = getattr(os, operation)
    failed = False

    def fail_once(*args: object, **kwargs: object):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected")
        return original(*args, **kwargs)

    monkeypatch.setattr(os, operation, fail_once)
    with pytest.raises(ImmutableEvidenceError):
        _write(directory)
    assert tuple(directory.iterdir()) == ()

    monkeypatch.setattr(os, operation, original)
    assert _write(directory).payload == {"value": "safe"}


def test_final_directory_fsync_failure_removes_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private(tmp_path / "evidence")
    original = os.fsync
    failed = False

    def fail_directory(descriptor: int) -> None:
        nonlocal failed
        if not failed and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            failed = True
            raise OSError("injected directory fsync")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(ImmutableEvidenceError):
        _write(directory)
    assert tuple(directory.iterdir()) == ()


def test_read_rejects_entry_replaced_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private(tmp_path / "evidence")
    evidence = _write(directory)
    replacement = evidence.path.with_suffix(".replacement")
    replacement.write_bytes(evidence.path.read_bytes())
    replacement.chmod(0o600)
    original = os.read
    replaced = False

    def replace_once(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        result = original(descriptor, size)
        if not replaced and result:
            replaced = True
            os.replace(replacement, evidence.path)
        return result

    monkeypatch.setattr(os, "read", replace_once)
    with pytest.raises(ImmutableEvidenceError, match="changed"):
        read_immutable_json(
            path=evidence.path,
            directory=directory,
            prefix=PREFIX,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_read_rejects_metadata_changed_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private(tmp_path / "evidence")
    evidence = _write(directory)
    original = os.read
    changed = False

    def chmod_once(descriptor: int, size: int) -> bytes:
        nonlocal changed
        result = original(descriptor, size)
        if not changed and result:
            changed = True
            evidence.path.chmod(0o640)
        return result

    monkeypatch.setattr(os, "read", chmod_once)
    with pytest.raises(ImmutableEvidenceError, match="changed"):
        read_immutable_json(
            path=evidence.path,
            directory=directory,
            prefix=PREFIX,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_write_rejects_directory_swap_without_adopting_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private(tmp_path / "evidence")
    displaced = tmp_path / "displaced"
    original = subject._read_immutable_json_from_dirfd

    def swap_directory(**kwargs: object):
        directory.rename(displaced)
        _private(directory)
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subject, "_read_immutable_json_from_dirfd", swap_directory)
    with pytest.raises(ImmutableEvidenceError, match="directory_changed"):
        _write(directory)
    assert tuple(displaced.iterdir()) == ()
    assert tuple(directory.iterdir()) == ()


@pytest.mark.parametrize("kind", ["mode", "symlink", "hardlink"])
def test_read_rejects_unsafe_existing_entry(tmp_path: Path, kind: str) -> None:
    directory = _private(tmp_path / "evidence")
    evidence = _write(directory)
    if kind == "mode":
        evidence.path.chmod(0o640)
    elif kind == "symlink":
        target = evidence.path.with_suffix(".target")
        evidence.path.rename(target)
        evidence.path.symlink_to(target)
    else:
        os.link(evidence.path, evidence.path.with_suffix(".link"))

    with pytest.raises(ImmutableEvidenceError):
        read_immutable_json(
            path=evidence.path,
            directory=directory,
            prefix=PREFIX,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


@pytest.mark.skipif(os.geteuid() != 0, reason="mapped-owner test requires root")
def test_root_can_create_for_mapped_owner(tmp_path: Path) -> None:
    directory = _private(tmp_path / "evidence")
    os.chown(directory, 65534, 65534)

    evidence = _write(directory, uid=65534, gid=65534)

    value = evidence.path.stat()
    assert (value.st_uid, value.st_gid, value.st_mode & 0o777) == (65534, 65534, 0o600)
    assert read_immutable_json(
        path=evidence.path,
        directory=directory,
        prefix=PREFIX,
        expected_uid=65534,
        expected_gid=65534,
    ) == evidence
    assert require_immutable_json_unchanged(
        evidence,
        directory=directory,
        prefix=PREFIX,
        expected_uid=65534,
        expected_gid=65534,
    ) == evidence
