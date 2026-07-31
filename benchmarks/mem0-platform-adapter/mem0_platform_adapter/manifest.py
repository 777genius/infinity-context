"""Sanitized managed-platform capability manifest."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import distribution as installed_distribution
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from mem0_platform_adapter.models import TimestampAttestation
from mem0_platform_adapter.runtime_pin import (
    PLATFORM_API_ORIGIN,
    RUNTIME_PIN,
    RuntimePin,
    load_runtime_pin,
)
from mem0_platform_adapter.service import PollingPolicy

SDK_VERIFICATION_METHOD = "direct_url_archive_info_sha256"
_REVISION = re.compile(r"^[0-9a-f]{40}$")

__all__ = (
    "PLATFORM_API_ORIGIN",
    "RUNTIME_PIN",
    "RuntimePin",
    "capabilities_manifest",
    "load_runtime_pin",
    "manifest_is_ready",
)


def capabilities_manifest(
    *,
    configured: bool,
    attestation: TimestampAttestation,
    policy: PollingPolicy,
    wrapper_revision: str | None = None,
) -> dict[str, Any]:
    revision = _tracked_wrapper_revision(wrapper_revision)
    static_config = {
        "platform_api_origin": PLATFORM_API_ORIGIN,
        "max_poll_attempts": policy.max_attempts,
        "poll_interval_seconds": policy.interval_seconds,
        "timestamp_tolerance_seconds": policy.timestamp_tolerance_seconds,
        "readback_page_size": policy.readback_page_size,
        "max_readback_pages": policy.max_readback_pages,
    }
    sdk = _installed_sdk_provenance()
    return {
        "schema_version": "mem0-benchmark-capabilities.v2",
        "runtime_mode": "managed_platform",
        "configured": configured,
        "wrapper_source_sha256": _wrapper_source_sha256(),
        "wrapper_source_revision": revision,
        "config_fingerprint_sha256": _sha256_json(static_config),
        "sdk": sdk,
        "platform": {
            "api_origin": PLATFORM_API_ORIGIN,
            "api_generation": RUNTIME_PIN.platform_api_generation,
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": sdk["pin_matches"],
            "event_completion_supported": True,
            "readback_supported": attestation.status == "passed",
            "attestation": attestation.model_dump(),
        },
    }


def _installed_sdk_provenance() -> dict[str, Any]:
    try:
        distribution = installed_distribution(RUNTIME_PIN.distribution)
    except PackageNotFoundError:
        distribution = None

    installed_version = distribution.version if distribution is not None else None
    observed_sha256 = _direct_url_archive_sha256(distribution)
    matches = (
        installed_version == RUNTIME_PIN.version and observed_sha256 == RUNTIME_PIN.wheel_sha256
    )
    return {
        "distribution": RUNTIME_PIN.distribution,
        "version": installed_version,
        "expected_version": RUNTIME_PIN.version,
        "pin_matches": matches,
        "source_revision": RUNTIME_PIN.source_revision if matches else None,
        "artifact_sha256": RUNTIME_PIN.wheel_sha256 if matches else None,
        "verification": {
            "method": SDK_VERIFICATION_METHOD,
            "observed_sha256": observed_sha256,
            "passed": matches,
        },
    }


def manifest_is_ready(payload: dict[str, Any]) -> bool:
    """Evaluate the fail-closed readiness invariants from a manifest snapshot."""
    timestamp = payload.get("timestamp")
    sdk = payload.get("sdk")
    if not isinstance(timestamp, dict) or not isinstance(sdk, dict):
        return False
    attestation = timestamp.get("attestation")
    return bool(
        payload.get("configured") is True
        and payload.get("wrapper_source_revision") is not None
        and sdk.get("pin_matches") is True
        and isinstance(attestation, dict)
        and attestation.get("status") == "passed"
        and isinstance(attestation.get("checked_at"), str)
        and bool(attestation["checked_at"])
        and attestation.get("cleanup_succeeded") is True
    )


def _tracked_wrapper_revision(value: str | None) -> str | None:
    if value is None or not _REVISION.fullmatch(value) or value == "0" * 40:
        return None
    return value


def _direct_url_archive_sha256(distribution: Any) -> str | None:
    if distribution is None:
        return None
    try:
        raw = distribution.read_text("direct_url.json")
        direct_url = json.loads(raw) if raw else {}
    except (AttributeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(direct_url, dict):
        return None
    raw_url = direct_url.get("url")
    if not isinstance(raw_url, str):
        return None
    parsed_url = urlparse(raw_url)
    if (
        parsed_url.scheme != "file"
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or PurePosixPath(unquote(parsed_url.path)).name != RUNTIME_PIN.wheel_filename
    ):
        return None
    archive_info = direct_url.get("archive_info")
    if not isinstance(archive_info, dict):
        return None
    hashes = archive_info.get("hashes")
    candidate = hashes.get("sha256") if isinstance(hashes, dict) else None
    if candidate is None:
        legacy_hash = archive_info.get("hash")
        if isinstance(legacy_hash, str) and legacy_hash.startswith("sha256="):
            candidate = legacy_hash.removeprefix("sha256=")
    if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", candidate):
        return None
    return candidate.casefold()


def _wrapper_source_sha256() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
