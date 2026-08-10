"""Bounded public-file verification regressions for runtime executables."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import process_files
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    CODEX_EXECUTABLE_MAX_BYTES,
    BridgeProcessError,
)

_CURRENT_CODEX_EXECUTABLE_SIZE_BYTES = 298_520_624
_EXPECTED_SHA256 = "a" * 64


def _sparse_executable(path: Path, size: int) -> None:
    with path.open("wb") as stream:
        stream.truncate(size)
    path.chmod(0o500)


@pytest.mark.parametrize(
    "size",
    (_CURRENT_CODEX_EXECUTABLE_SIZE_BYTES, CODEX_EXECUTABLE_MAX_BYTES),
)
def test_codex_size_contract_accepts_current_class_through_exact_maximum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    size: int,
) -> None:
    executable = tmp_path / "codex"
    _sparse_executable(executable, size)
    observations: list[tuple[int, int, str]] = []

    def accepted_digest(descriptor: int, *, maximum_bytes: int, label: str) -> str:
        observations.append((os.fstat(descriptor).st_size, maximum_bytes, label))
        return _EXPECTED_SHA256

    monkeypatch.setattr(process_files, "_sha256_descriptor", accepted_digest)

    process_files.verify_public_file(
        executable,
        _EXPECTED_SHA256,
        executable=True,
        maximum_bytes=CODEX_EXECUTABLE_MAX_BYTES,
        label="codex_executable",
    )

    assert observations == [(size, CODEX_EXECUTABLE_MAX_BYTES, "codex_executable")]


def test_codex_size_contract_rejects_one_byte_above_maximum_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex"
    _sparse_executable(executable, CODEX_EXECUTABLE_MAX_BYTES + 1)
    digest_called = False

    def unexpected_digest(*_args: object, **_kwargs: object) -> str:
        nonlocal digest_called
        digest_called = True
        return _EXPECTED_SHA256

    monkeypatch.setattr(process_files, "_sha256_descriptor", unexpected_digest)

    with pytest.raises(
        BridgeProcessError,
        match="^bridge_process_codex_executable_size_invalid$",
    ):
        process_files.verify_public_file(
            executable,
            _EXPECTED_SHA256,
            executable=True,
            maximum_bytes=CODEX_EXECUTABLE_MAX_BYTES,
            label="codex_executable",
        )

    assert not digest_called


def test_public_file_hash_is_streamed_in_bounded_chunks_and_exactly_matched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex"
    raw = b"reviewed-codex-chunk\n" * 100_000
    executable.write_bytes(raw)
    executable.chmod(0o500)
    expected = hashlib.sha256(raw).hexdigest()
    real_read = os.read
    requested_sizes: list[int] = []

    def observed_read(descriptor: int, maximum_bytes: int) -> bytes:
        requested_sizes.append(maximum_bytes)
        return real_read(descriptor, maximum_bytes)

    monkeypatch.setattr(process_files.os, "read", observed_read)

    process_files.verify_public_file(
        executable,
        expected,
        executable=True,
        maximum_bytes=CODEX_EXECUTABLE_MAX_BYTES,
        label="codex_executable",
    )

    assert requested_sizes
    assert max(requested_sizes) <= 1024 * 1024
    with pytest.raises(
        BridgeProcessError,
        match="^bridge_process_codex_executable_sha256_mismatch$",
    ):
        process_files.verify_public_file(
            executable,
            "0" * 64,
            executable=True,
            maximum_bytes=CODEX_EXECUTABLE_MAX_BYTES,
            label="codex_executable",
        )
