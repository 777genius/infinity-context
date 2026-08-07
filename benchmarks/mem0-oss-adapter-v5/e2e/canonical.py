"""Small canonical primitives shared by the independent E2E boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class E2EVerificationError(RuntimeError):
    """Fail-closed, secret-safe E2E verdict."""


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError):
        raise E2EVerificationError("e2e_canonical_value_invalid") from None


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise E2EVerificationError("e2e_bytes_invalid")
    return hashlib.sha256(value).hexdigest()


def require_digest(value: object, code: str = "e2e_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise E2EVerificationError(code)
    return value


def exact_object(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise E2EVerificationError(code)
    return value


def read_private_text(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise E2EVerificationError("e2e_private_file_invalid")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise E2EVerificationError("e2e_private_file_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= 8192:
        raise E2EVerificationError("e2e_private_file_invalid")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise E2EVerificationError("e2e_private_file_invalid") from None
    if not value or value != value.strip():
        raise E2EVerificationError("e2e_private_file_invalid")
    return value


def atomic_private_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    if (
        not path.is_absolute()
        or path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents)
        or mode not in {0o400, 0o600}
    ):
        raise E2EVerificationError("e2e_private_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_text(value: object, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise E2EVerificationError("e2e_text_invalid")
    return value
