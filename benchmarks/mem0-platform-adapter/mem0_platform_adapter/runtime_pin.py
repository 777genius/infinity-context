"""Strict loader for the tracked managed-platform runtime identity."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,99}$")
_WHEEL_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")
_RUNTIME_PIN_PATH = Path(__file__).resolve().parent.parent / "runtime-pin.json"


@dataclass(frozen=True, slots=True)
class RuntimePin:
    distribution: str
    version: str
    source_repository: str
    source_revision: str
    wrapper_source_revision: str
    wrapper_source_sha256: str
    wheel_filename: str
    wheel_sha256: str
    runtime_lock_sha256: str
    runtime_lock_artifact_count: int
    platform_api_origin: str
    platform_api_generation: str


def load_runtime_pin(path: Path = _RUNTIME_PIN_PATH) -> RuntimePin:
    """Load and strictly validate the tracked runtime identity."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid runtime pin: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("invalid runtime pin: expected an object")
    expected_fields = set(RuntimePin.__dataclass_fields__)
    string_fields = expected_fields - {"runtime_lock_artifact_count"}
    if (
        set(payload) != expected_fields
        or any(not isinstance(payload[field], str) or not payload[field] for field in string_fields)
        or not isinstance(payload["runtime_lock_artifact_count"], int)
        or isinstance(payload["runtime_lock_artifact_count"], bool)
        or not 1 <= payload["runtime_lock_artifact_count"] <= 1000
    ):
        raise RuntimeError("invalid runtime pin: fields are missing, extra, or empty")
    pin = RuntimePin(**payload)
    origin = urlparse(pin.platform_api_origin)
    if (
        not _DISTRIBUTION.fullmatch(pin.distribution)
        or not _VERSION.fullmatch(pin.version)
        or not _REVISION.fullmatch(pin.source_revision)
        or not _REVISION.fullmatch(pin.wrapper_source_revision)
        or not _SHA256.fullmatch(pin.wrapper_source_sha256)
        or not _SHA256.fullmatch(pin.wheel_sha256)
        or not _SHA256.fullmatch(pin.runtime_lock_sha256)
        or not _WHEEL_FILENAME.fullmatch(pin.wheel_filename)
        or origin.scheme != "https"
        or not origin.netloc
        or origin.path not in {"", "/"}
        or origin.params
        or origin.query
        or origin.fragment
    ):
        raise RuntimeError("invalid runtime pin: value failed validation")
    return pin


RUNTIME_PIN = load_runtime_pin()
PLATFORM_API_ORIGIN = RUNTIME_PIN.platform_api_origin
