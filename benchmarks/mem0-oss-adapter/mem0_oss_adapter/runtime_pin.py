"""Strict loader for the tracked Mem0 OSS runtime identity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,99}$")
_WHEEL_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")
_RUNTIME_PIN_PATH = Path(__file__).resolve().parent.parent / "runtime-pin.json"


@dataclass(frozen=True, slots=True)
class RuntimePin:
    schema_version: str
    adapter: str
    python_version: str
    python_image_digest: str
    qdrant_image_tag: str
    qdrant_image_digest: str
    qdrant_image_linux_amd64_digest: str
    mem0ai_version: str
    mem0ai_source_revision: str
    mem0ai_wheel_filename: str
    mem0ai_wheel_sha256: str
    fastembed_version: str
    fastembed_wheel_filename: str
    fastembed_wheel_sha256: str
    qdrant_client_version: str
    qdrant_client_wheel_filename: str
    qdrant_client_wheel_sha256: str
    embedding_model: str
    embedding_source_repository: str
    embedding_model_revision: str
    embedding_onnx_filename: str
    embedding_onnx_sha256: str
    wrapper_source_revision: str
    wrapper_source_sha256: str
    runtime_lock_sha256: str
    runtime_lock_artifact_count: int


def load_runtime_pin(path: Path = _RUNTIME_PIN_PATH) -> RuntimePin:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid runtime pin: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("invalid runtime pin: expected an object")

    expected = set(RuntimePin.__dataclass_fields__)
    string_fields = expected - {"runtime_lock_artifact_count"}
    if (
        set(payload) != expected
        or any(
            not isinstance(payload.get(field), str) or not payload[field] for field in string_fields
        )
        or not isinstance(payload.get("runtime_lock_artifact_count"), int)
        or isinstance(payload.get("runtime_lock_artifact_count"), bool)
        or not 1 <= payload["runtime_lock_artifact_count"] <= 1000
    ):
        raise RuntimeError("invalid runtime pin: fields are missing, extra, or empty")

    pin = RuntimePin(**payload)
    if (
        pin.schema_version != "mem0-oss-runtime-pin.v1"
        or pin.adapter != "mem0_oss"
        or pin.python_version != "3.11"
        or pin.qdrant_image_tag != "v1.18.3"
        or pin.embedding_model != "BAAI/bge-small-en-v1.5"
        or pin.embedding_source_repository != "qdrant/bge-small-en-v1.5-onnx-q"
        or pin.embedding_onnx_filename != "model_optimized.onnx"
        or not _SHA256_DIGEST.fullmatch(pin.python_image_digest)
        or not _SHA256_DIGEST.fullmatch(pin.qdrant_image_digest)
        or not _SHA256_DIGEST.fullmatch(pin.qdrant_image_linux_amd64_digest)
        or not _REVISION.fullmatch(pin.mem0ai_source_revision)
        or not _REVISION.fullmatch(pin.embedding_model_revision)
        or not _REVISION.fullmatch(pin.wrapper_source_revision)
        or not all(
            _SHA256.fullmatch(value)
            for value in (
                pin.mem0ai_wheel_sha256,
                pin.fastembed_wheel_sha256,
                pin.qdrant_client_wheel_sha256,
                pin.embedding_onnx_sha256,
                pin.wrapper_source_sha256,
                pin.runtime_lock_sha256,
            )
        )
        or pin.wrapper_source_sha256 == "0" * 64
        or not all(
            _VERSION.fullmatch(value)
            for value in (
                pin.mem0ai_version,
                pin.fastembed_version,
                pin.qdrant_client_version,
            )
        )
        or not all(
            _WHEEL_FILENAME.fullmatch(value)
            for value in (
                pin.mem0ai_wheel_filename,
                pin.fastembed_wheel_filename,
                pin.qdrant_client_wheel_filename,
            )
        )
    ):
        raise RuntimeError("invalid runtime pin: value failed validation")
    return pin


def runtime_pin_sha256(path: Path = _RUNTIME_PIN_PATH) -> str:
    """Return the canonical digest used in the public manifest."""

    pin = load_runtime_pin(path)
    payload = {field: getattr(pin, field) for field in RuntimePin.__dataclass_fields__}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


RUNTIME_PIN = load_runtime_pin()
