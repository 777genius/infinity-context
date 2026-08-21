from __future__ import annotations

import os
from pathlib import Path

import pytest
from infinity_context_runtime_bridge import (
    secure_secret_file as subject,
)
from infinity_context_runtime_bridge.secure_secret_file import (
    SecureSecretFileError,
    SecureSecretFileReader,
)


def _private_root(tmp_path: Path, name: str = "secrets") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _secret(root: Path, value: bytes = b"s" * 64, name: str = "secret") -> Path:
    path = root / name
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def _reader(root: Path, path: Path, *, maximum: int = 16 * 1024) -> SecureSecretFileReader:
    return SecureSecretFileReader(
        private_root=root,
        path=path,
        maximum_bytes=maximum,
    )


def test_exact_descriptor_bound_read_returns_wipeable_owned_bytes(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    expected = b"private-keyring-manifest"
    path = _secret(root, expected)

    opened = _reader(root, path).read()
    retained = opened.value

    assert bytes(retained) == expected
    assert opened.snapshot.file[0:2] == (path.stat().st_dev, path.stat().st_ino)
    assert "private-keyring-manifest" not in repr(opened)
    assert str(path) not in repr(opened)
    opened.close()
    opened.close()
    assert retained == bytearray()
    with pytest.raises(SecureSecretFileError):
        _ = opened.value


@pytest.mark.parametrize("target", ("relative-root", "relative-file", "outside-root"))
def test_absolute_canonical_descendant_paths_are_mandatory(
    tmp_path: Path,
    target: str,
) -> None:
    root = _private_root(tmp_path)
    path = _secret(root)
    if target == "relative-root":
        reader = _reader(Path("relative-secrets"), path)
    elif target == "relative-file":
        reader = _reader(root, Path("relative-secret"))
    else:
        outside = _secret(_private_root(tmp_path, "outside"))
        reader = _reader(root, outside)

    with pytest.raises(SecureSecretFileError, match="secure_secret_file_unavailable"):
        reader.read()

    nested = root / "nested"
    nested.mkdir(mode=0o700)
    noncanonical = nested / ".." / path.name
    with pytest.raises(SecureSecretFileError):
        _reader(root, noncanonical).read()


def test_every_private_ancestor_must_be_euid_owned_mode_0700(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    path = _secret(nested)

    nested.chmod(0o750)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path).read()

    nested.chmod(0o700)
    root.chmod(0o710)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path).read()


def test_symlinked_leaf_ancestor_and_private_root_fail_closed(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    target = _secret(root, name="target")
    leaf = root / "leaf"
    leaf.symlink_to(target)
    with pytest.raises(SecureSecretFileError):
        _reader(root, leaf).read()

    real_nested = root / "real-nested"
    real_nested.mkdir(mode=0o700)
    nested_secret = _secret(real_nested)
    linked_nested = root / "linked-nested"
    linked_nested.symlink_to(real_nested, target_is_directory=True)
    with pytest.raises(SecureSecretFileError):
        _reader(root, linked_nested / nested_secret.name).read()

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(SecureSecretFileError):
        _reader(linked_root, linked_root / target.name).read()


def test_hardlink_and_non_private_leaf_fail_closed(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    original = _secret(root, name="original")
    linked = root / "linked"
    os.link(original, linked)

    with pytest.raises(SecureSecretFileError):
        _reader(root, original).read()
    with pytest.raises(SecureSecretFileError):
        _reader(root, linked).read()

    linked.unlink()
    original.chmod(0o640)
    with pytest.raises(SecureSecretFileError):
        _reader(root, original).read()


def test_inode_replacement_between_path_stat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_root(tmp_path)
    path = _secret(root, b"a" * 64)
    real_stat = subject.os.stat
    replaced = False

    def racing_stat(candidate, *args, **kwargs):
        nonlocal replaced
        result = real_stat(candidate, *args, **kwargs)
        if candidate == path.name and kwargs.get("dir_fd") is not None and not replaced:
            replaced = True
            replacement = root / "replacement"
            replacement.write_bytes(b"b" * 64)
            replacement.chmod(0o600)
            replacement.replace(path)
        return result

    monkeypatch.setattr(subject.os, "stat", racing_stat)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path).read()


def test_rename_replacement_during_read_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_root(tmp_path)
    path = _secret(root, b"a" * 9_000)
    real_read = subject.os.read
    replaced = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = real_read(descriptor, size)
        if not replaced:
            replaced = True
            replacement = root / "replacement"
            replacement.write_bytes(b"b" * 9_000)
            replacement.chmod(0o600)
            replacement.replace(path)
        return chunk

    monkeypatch.setattr(subject.os, "read", racing_read)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path).read()


def test_same_inode_same_size_mutation_during_read_is_rejected_and_wiped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_root(tmp_path)
    path = _secret(root, b"a" * 9_000)
    before = path.stat()
    real_read = subject.os.read
    real_wipe = subject._wipe
    mutated = False
    wiped: list[bytearray] = []

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, size)
        if not mutated:
            mutated = True
            path.write_bytes(b"b" * 9_000)
            path.chmod(0o600)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return chunk

    def tracking_wipe(value: bytearray) -> None:
        wiped.append(value)
        real_wipe(value)

    monkeypatch.setattr(subject.os, "read", racing_read)
    monkeypatch.setattr(subject, "_wipe", tracking_wipe)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path).read()

    after = path.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    assert wiped and all(value == bytearray() for value in wiped)


def test_concurrent_growth_is_bounded_by_each_read_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_root(tmp_path)
    path = _secret(root, b"x")
    requested: list[int] = []

    def growing_read(_descriptor: int, size: int) -> bytes:
        requested.append(size)
        return b"x" * min(size, 16)

    monkeypatch.setattr(subject.os, "read", growing_read)
    with pytest.raises(SecureSecretFileError):
        _reader(root, path, maximum=64).read()

    assert requested == [65, 49, 33, 17, 1]
    assert all(1 <= size <= subject._READ_CHUNK_BYTES for size in requested)


def test_missing_nofollow_support_and_secret_bearing_os_error_are_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_root(tmp_path)
    marker = "PRIVATE-PATH-MARKER"
    path = _secret(root, name=marker)

    monkeypatch.delattr(subject.os, "O_NOFOLLOW")
    with pytest.raises(SecureSecretFileError) as captured:
        _reader(root, path).read()

    rendered = f"{captured.value!r} {captured.value}"
    assert marker not in rendered
    assert str(path) not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
