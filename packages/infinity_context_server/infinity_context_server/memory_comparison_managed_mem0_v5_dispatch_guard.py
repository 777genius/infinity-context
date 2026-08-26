"""Fail-closed single-dispatch journal for the managed Mem0 v5 canary."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)

_SCHEMA = "managed-mem0-v5-single-dispatch-claim.v1"
_MAX_BYTES = 4_096
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class ManagedMem0V5SingleDispatchGuardPort(Protocol):
    """One-way durable CAS from unclaimed to one exact dispatch tuple."""

    def claim(
        self,
        *,
        admission_commitment_sha256: str,
        operation_id_sha256: str,
        request_body_sha256: str,
    ) -> None: ...


@final
class AtomicJournalManagedMem0V5SingleDispatchGuard:
    """A private O_EXCL journal; any prior file permanently forbids redispatch."""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or path.parent == path
        ):
            raise ManagedRunError("managed Mem0 v5 dispatch guard path is invalid")
        parent_fd = _open_private_parent(path.parent)
        os.close(parent_fd)
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def claim(
        self,
        *,
        admission_commitment_sha256: str,
        operation_id_sha256: str,
        request_body_sha256: str,
    ) -> None:
        binding = _binding(
            admission_commitment_sha256=admission_commitment_sha256,
            operation_id_sha256=operation_id_sha256,
            request_body_sha256=request_body_sha256,
        )
        encoded = _encoded(binding)
        parent_fd = _open_private_parent(self._path.parent)
        try:
            try:
                claim_fd = os.open(
                    self._path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                existing = _read_existing(parent_fd, self._path.name)
                _require_existing_binding(existing, binding)
                raise ManagedRunError("managed Mem0 v5 dispatch was already claimed") from None
            except OSError:
                raise ManagedRunError("managed Mem0 v5 dispatch guard claim failed") from None
            try:
                os.fchmod(claim_fd, 0o600)
                _require_private_file(os.fstat(claim_fd))
                _write_all(claim_fd, encoded)
                os.fsync(claim_fd)
            except Exception:
                raise ManagedRunError("managed Mem0 v5 dispatch guard claim failed") from None
            finally:
                os.close(claim_fd)
            os.fsync(parent_fd)
        except ManagedRunError:
            raise
        except Exception:
            raise ManagedRunError("managed Mem0 v5 dispatch guard claim failed") from None
        finally:
            os.close(parent_fd)

    def __repr__(self) -> str:
        return "AtomicJournalManagedMem0V5SingleDispatchGuard(<opaque>)"


def create_managed_mem0_v5_single_dispatch_guard(
    path: Path,
) -> AtomicJournalManagedMem0V5SingleDispatchGuard:
    return AtomicJournalManagedMem0V5SingleDispatchGuard(path)


def managed_mem0_v5_unclaimed_dispatch_commitment(path: Path) -> str:
    """Prove the write-once dispatch claim is absent under its private root."""

    if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ManagedRunError("managed Mem0 v5 dispatch guard path is invalid")
    parent_fd = _open_private_parent(path.parent)
    try:
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return canonical_sha256(
                {
                    "schema_version": "managed-mem0-v5-dispatch-unclaimed.v1",
                    "path_sha256": canonical_sha256({"absolute_path": str(path)}),
                }
            )
        except OSError:
            raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid") from None
        else:
            os.close(descriptor)
            raise ManagedRunError("managed Mem0 v5 dispatch was already claimed")
    finally:
        os.close(parent_fd)


def _open_private_parent(path: Path) -> int:
    if _NOFOLLOW == 0 or _DIRECTORY == 0:
        raise ManagedRunError("managed Mem0 v5 dispatch guard storage is unavailable")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
        )
    except OSError:
        raise ManagedRunError("managed Mem0 v5 dispatch guard storage is invalid") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ManagedRunError("managed Mem0 v5 dispatch guard storage is invalid")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _binding(
    *,
    admission_commitment_sha256: str,
    operation_id_sha256: str,
    request_body_sha256: str,
) -> dict[str, str]:
    values = (
        admission_commitment_sha256,
        operation_id_sha256,
        request_body_sha256,
    )
    if not all(is_sha256(value) for value in values):
        raise ManagedRunError("managed Mem0 v5 dispatch guard binding is invalid")
    return {
        "schema_version": _SCHEMA,
        "admission_commitment_sha256": admission_commitment_sha256,
        "operation_id_sha256": operation_id_sha256,
        "request_body_sha256": request_body_sha256,
    }


def _encoded(binding: dict[str, str]) -> bytes:
    record = {
        **binding,
        "claim_commitment_sha256": canonical_sha256(binding),
    }
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _read_existing(parent_fd: int, name: str) -> dict[str, object]:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
            dir_fd=parent_fd,
        )
    except OSError:
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid") from None
    try:
        _require_private_file(os.fstat(descriptor))
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(1_024, _MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_BYTES:
                raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid")
        raw = b"".join(chunks)
    except ManagedRunError:
        raise
    except Exception:
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid") from None
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid") from None
    if type(value) is not dict or raw != _canonical_record(value):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid")
    return value


def _canonical_record(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid") from None


def _require_existing_binding(
    value: dict[str, object],
    expected: dict[str, str],
) -> None:
    keys = {
        "schema_version",
        "admission_commitment_sha256",
        "operation_id_sha256",
        "request_body_sha256",
        "claim_commitment_sha256",
    }
    if (
        set(value) != keys
        or value["schema_version"] != _SCHEMA
        or not all(is_sha256(value[key]) for key in keys - {"schema_version"})
    ):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid")
    unsigned = {key: value[key] for key in expected}
    if value["claim_commitment_sha256"] != canonical_sha256(unsigned):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid")
    if any(value[key] != item for key, item in expected.items()):
        raise ManagedRunError("managed Mem0 v5 dispatch guard binding differs")


def _require_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise ManagedRunError("managed Mem0 v5 dispatch guard state is invalid")


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short dispatch guard write")
        offset += written


__all__ = (
    "AtomicJournalManagedMem0V5SingleDispatchGuard",
    "ManagedMem0V5SingleDispatchGuardPort",
    "create_managed_mem0_v5_single_dispatch_guard",
    "managed_mem0_v5_unclaimed_dispatch_commitment",
)
