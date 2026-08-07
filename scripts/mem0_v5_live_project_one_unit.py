"""Project one immutable managed case into an exact Mem0 v5 live input."""

# ruff: noqa: E402 - direct CLI execution bootstraps repository package roots.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _repository_path in (
    _PROJECT_ROOT,
    _PROJECT_ROOT / "packages" / "infinity_context_core",
    _PROJECT_ROOT / "packages" / "infinity_context_server",
    _PROJECT_ROOT / "benchmarks" / "mem0-oss-adapter-v5",
):
    if str(_repository_path) not in sys.path:
        sys.path.insert(0, str(_repository_path))

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_MAX_CASE_BYTES = 16 * 1024 * 1024
_SHA256 = frozenset("0123456789abcdef")


class ExtractionRequestView(Protocol):
    request_body_sha256: str
    response_format_sha256: str
    response_schema_sha256: str
    max_tokens: int


ExtractionProjector = Callable[..., ExtractionRequestView]


@dataclass(frozen=True, slots=True)
class OneUnitProjection:
    cases: tuple[ManagedRunCase, ...]
    authority: ManagedMem0V5ManifestAuthority
    request_body_sha256: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int
    case_file_sha256: str
    search_query: str

    def __post_init__(self) -> None:
        if (
            len(self.cases) != 1
            or self.authority.case_count != 1
            or self.authority.corpus_count != 1
            or self.authority.operation_count != 1
            or any(
                not _is_sha256(value)
                for value in (
                    self.request_body_sha256,
                    self.response_format_sha256,
                    self.response_schema_sha256,
                    self.case_file_sha256,
                )
            )
            or self.requested_output_tokens != 4096
            or not _safe_query(self.search_query)
        ):
            raise ValueError("mem0_v5_live_one_unit_projection_invalid")

    def public_payload(self) -> dict[str, object]:
        unit = self.authority.units[0]
        return {
            "schema_version": "managed-mem0-v5-live-one-unit.v1",
            "case_file_sha256": self.case_file_sha256,
            "authority_commitment_sha256": self.authority.authority_commitment_sha256,
            "sealed_payload_sha256": self.authority.sealed_payload_sha256,
            "ingestion_manifest_sha256": self.authority.ingestion_manifest_sha256,
            "ingestion_root_sha256": self.authority.ingestion_root_sha256,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
            "source_sha256": unit.source_sha256,
            "scope_sha256": unit.scope_sha256,
            "request_body_sha256": self.request_body_sha256,
            "response_format_sha256": self.response_format_sha256,
            "response_schema_sha256": self.response_schema_sha256,
            "requested_output_tokens": self.requested_output_tokens,
            "case_count": 1,
            "corpus_count": 1,
            "unit_count": 1,
        }


def project_one_unit(
    *,
    case_file: Path,
    expected_case_sha256: str,
    current_date: str,
    extraction_projector: ExtractionProjector,
) -> OneUnitProjection:
    raw = _read_immutable(case_file, expected_case_sha256, maximum_bytes=_MAX_CASE_BYTES)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("mem0_v5_live_case_invalid") from None
    if type(payload) is not dict or set(payload) != {
        "case_id",
        "corpus_id",
        "record",
        "search_query",
    }:
        raise ValueError("mem0_v5_live_case_invalid")
    search_query = payload["search_query"]
    if not _safe_query(search_query):
        raise ValueError("mem0_v5_live_case_invalid")
    try:
        case = ManagedRunCase(payload["case_id"], payload["corpus_id"], payload["record"])
        authority = ManagedMem0V5ManifestProjector().project((case,), current_date=current_date)
    except Exception:
        raise ValueError("mem0_v5_live_case_invalid") from None
    if authority.case_count != 1 or authority.corpus_count != 1 or authority.operation_count != 1:
        raise ValueError("mem0_v5_live_case_must_project_exactly_one_unit")
    request = _project_request(extraction_projector, authority.units[0], current_date)
    return OneUnitProjection(
        cases=(case,),
        authority=authority,
        request_body_sha256=request.request_body_sha256,
        response_format_sha256=request.response_format_sha256,
        response_schema_sha256=request.response_schema_sha256,
        requested_output_tokens=request.max_tokens,
        case_file_sha256=hashlib.sha256(raw).hexdigest(),
        search_query=search_query,
    )


def materialize_projection(projection: OneUnitProjection, *, input_root: Path) -> None:
    _require_private_directory(input_root, must_be_empty=True)
    manifest = json.dumps(
        projection.authority.private_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    public = json.dumps(
        projection.public_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    _write_once(input_root / "manifest.json", manifest, mode=0o400)
    _write_once(input_root / "one-unit-authority.json", public, mode=0o400)
    _fsync_directory(input_root)


def _project_request(
    projector: ExtractionProjector,
    unit: ManagedMem0V5SourceUnit,
    current_date: str,
) -> ExtractionRequestView:
    try:
        request = projector(
            tuple(message.payload() for message in unit.source_messages),
            current_date=current_date,
            timestamp=unit.observation_date,
        )
    except Exception:
        raise ValueError("mem0_v5_live_extraction_projection_failed") from None
    if (
        any(
            not _is_sha256(value)
            for value in (
                getattr(request, "request_body_sha256", None),
                getattr(request, "response_format_sha256", None),
                getattr(request, "response_schema_sha256", None),
            )
        )
        or getattr(request, "max_tokens", None) != 4096
    ):
        raise ValueError("mem0_v5_live_extraction_projection_invalid")
    return request


def _read_immutable(path: Path, expected_sha256: str, *, maximum_bytes: int) -> bytes:
    if not _is_sha256(expected_sha256) or not path.is_absolute():
        raise ValueError("mem0_v5_live_immutable_file_invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) not in {0o400, 0o440, 0o444}
            or opened.st_nlink != 1
            or identity != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            or not 1 <= opened.st_size <= maximum_bytes
        ):
            raise ValueError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise ValueError
        final = os.fstat(descriptor)
        if identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise ValueError
        raw = b"".join(chunks)
    except (OSError, ValueError):
        raise ValueError("mem0_v5_live_immutable_file_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > maximum_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("mem0_v5_live_immutable_file_invalid")
    return raw


def _require_private_directory(path: Path, *, must_be_empty: bool) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("mem0_v5_live_private_root_invalid")
    try:
        metadata = path.stat()
        entries = tuple(path.iterdir()) if must_be_empty else ()
    except OSError:
        raise ValueError("mem0_v5_live_private_root_invalid") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or entries
    ):
        raise ValueError("mem0_v5_live_private_root_invalid")


def _write_once(path: Path, value: bytes, *, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(value)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256


def _safe_query(value: object) -> bool:
    return type(value) is str and value == value.strip() and 1 <= len(value) <= 16_384


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-sha256", required=True)
    parser.add_argument("--current-date", required=True)
    parser.add_argument("--input-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from mem0_oss_adapter_v5.extraction_contract import build_extraction_request

    projection = project_one_unit(
        case_file=args.case_file,
        expected_case_sha256=args.case_sha256,
        current_date=args.current_date,
        extraction_projector=build_extraction_request,
    )
    materialize_projection(projection, input_root=args.input_root)
    print(json.dumps(projection.public_payload(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("OneUnitProjection", "materialize_projection", "project_one_unit")
