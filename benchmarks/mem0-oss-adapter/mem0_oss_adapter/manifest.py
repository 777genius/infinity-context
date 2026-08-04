"""Sanitized v4 capability manifest for the pinned OSS runtime."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from mem0_oss_adapter.models import TimestampAttestation
from mem0_oss_adapter.runtime_lock import canonical_runtime_lock_sha256, load_runtime_lock
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN, runtime_pin_sha256

_RUNTIME_LOCK_PATH = Path(__file__).resolve().parent.parent / "runtime-lock.json"
_CAPABILITIES = (
    "delete_verified_absence",
    "hmac_auth_challenge",
    "offline_fastembed",
    "raw_passthrough",
    "same_run_refresh_witness",
    "signed_run_scoped_usage_evidence",
    "source_identity_roundtrip",
    "subscription_llm_extraction",
)
_USAGE_LEDGER_FIELDS = (
    "run_id",
    "operation",
    "mode",
    "extraction_calls",
    "request_bytes",
    "response_bytes",
    "model",
    "created_at",
)


def capabilities_manifest(
    *,
    configured: bool,
    extraction_mode: Literal["raw_passthrough", "subscription_llm"],
    timestamp_attestation: TimestampAttestation,
    source_identity_attested: bool,
) -> dict[str, Any]:
    """Construct the exact public v4 schema without endpoint or secret material."""

    runtime_lock = load_runtime_lock(_RUNTIME_LOCK_PATH, pin=RUNTIME_PIN)
    extraction_enabled = extraction_mode == "subscription_llm"
    max_calls = 1 if extraction_enabled else 0
    static_config = {
        "adapter": "mem0_oss",
        "embedding": {
            "dimensions": 384,
            "model": RUNTIME_PIN.embedding_model,
            "model_revision": RUNTIME_PIN.embedding_model_revision,
            "offline": True,
        },
        "extraction": {
            "max_calls_per_add": max_calls,
            "mode": extraction_mode,
            "request_max_bytes": 65_536,
            "response_max_bytes": 65_536,
            "subscription_scope": "isolated_single_add",
        },
        "runtime": {
            "auth_mode": "none",
            "mode": "oss",
            "python_version": RUNTIME_PIN.python_version,
        },
        "timestamp": {"mode": "wrapper_metadata_created_at", "sdk_native_timestamp": False},
    }
    payload: dict[str, Any] = {
        "schema_version": "mem0-benchmark-capabilities.v4",
        "runtime_mode": "oss",
        "configured": configured,
        "wrapper_source_revision": RUNTIME_PIN.wrapper_source_revision,
        "wrapper_source_sha256": _wrapper_source_sha256(),
        "config_fingerprint_sha256": _sha256_json(static_config),
        "adapter": "mem0_oss",
        "runtime": {
            "mode": "oss",
            "auth_mode": "none",
            "python_version": RUNTIME_PIN.python_version,
            "python_image_digest": RUNTIME_PIN.python_image_digest,
            "qdrant_image_digest": RUNTIME_PIN.qdrant_image_digest,
        },
        "packages": {
            "mem0ai": {
                "version": RUNTIME_PIN.mem0ai_version,
                "source_revision": RUNTIME_PIN.mem0ai_source_revision,
                "wheel_sha256": RUNTIME_PIN.mem0ai_wheel_sha256,
            },
            "fastembed": {
                "version": RUNTIME_PIN.fastembed_version,
                "wheel_sha256": RUNTIME_PIN.fastembed_wheel_sha256,
            },
            "qdrant_client": {
                "version": RUNTIME_PIN.qdrant_client_version,
                "wheel_sha256": RUNTIME_PIN.qdrant_client_wheel_sha256,
            },
        },
        "embedding": {
            "provider": "fastembed",
            "model": RUNTIME_PIN.embedding_model,
            "model_revision": RUNTIME_PIN.embedding_model_revision,
            "onnx_sha256": RUNTIME_PIN.embedding_onnx_sha256,
            "dimensions": 384,
            "offline": True,
        },
        "extraction": {
            "mode": extraction_mode,
            "raw_passthrough_supported": True,
            "extraction_enabled": extraction_enabled,
            "telemetry_enabled": False,
            "max_calls_per_add": max_calls,
            "request_max_bytes": 65_536,
            "response_max_bytes": 65_536,
            "subscription_scope": "isolated_single_add",
            "usage_ledger": {"required": True, "fields": list(_USAGE_LEDGER_FIELDS)},
            "usage_evidence": {
                "schema_version": "mem0-benchmark-usage-attestation.v1",
                "run_scoped": True,
                "hmac_sha256": True,
                "ingress_auth_required": True,
                "probe_token_required": True,
            },
        },
        "timestamp": {
            "mode": "wrapper_metadata_created_at",
            "sdk_native_timestamp": False,
            "request_supported": True,
            "metadata_readback_supported": True,
            "attestation": timestamp_attestation.model_dump(),
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": source_identity_attested,
            "source_sha256_roundtrip_attested": source_identity_attested,
            "sanitized_identity_response": True,
        },
        "capabilities": list(_CAPABILITIES),
        "delete": {"verified_absent": True},
        "integrity": {
            "manifest_sha256": "",
            "runtime_pin_sha256": runtime_pin_sha256(),
            "lock_sha256": canonical_runtime_lock_sha256(
                {
                    "artifacts": [
                        {
                            "distribution": artifact.distribution,
                            "filename": artifact.filename,
                            "sha256": artifact.sha256,
                            "url": artifact.url,
                            "version": artifact.version,
                        }
                        for artifact in runtime_lock.artifacts
                    ],
                    "machine": runtime_lock.machine,
                    "python_version": runtime_lock.python_version,
                    "schema_version": runtime_lock.schema_version,
                    "sys_platform": runtime_lock.sys_platform,
                }
            ),
        },
    }
    return seal_manifest(payload)


def seal_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy and seal a server-created manifest according to the additive v4 formula."""

    sealed = copy.deepcopy(dict(payload))
    integrity = sealed.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("manifest integrity object is required")
    integrity["manifest_sha256"] = manifest_integrity_sha256(sealed)
    return sealed


def manifest_integrity_sha256(payload: Mapping[str, Any]) -> str:
    """Hash all unsigned manifest fields, including an optional refresh binding."""

    unsigned = copy.deepcopy(dict(payload))
    unsigned.pop("refresh_witness", None)
    integrity = unsigned.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("manifest integrity object is required")
    integrity.pop("manifest_sha256", None)
    return _sha256_json(unsigned)


def manifest_is_ready(payload: Mapping[str, Any]) -> bool:
    """Fail closed until a signed refresh demonstrates the live wrapper path."""

    timestamp = payload.get("timestamp")
    identity = payload.get("persisted_source_identity")
    integrity = payload.get("integrity")
    if not isinstance(timestamp, Mapping) or not isinstance(identity, Mapping):
        return False
    if not isinstance(integrity, Mapping):
        return False
    attestation = timestamp.get("attestation")
    return bool(
        payload.get("configured") is True
        and payload.get("schema_version") == "mem0-benchmark-capabilities.v4"
        and payload.get("runtime_mode") == "oss"
        and payload.get("wrapper_source_revision") == RUNTIME_PIN.wrapper_source_revision
        and payload.get("wrapper_source_sha256") == RUNTIME_PIN.wrapper_source_sha256
        and payload.get("wrapper_source_sha256") != "0" * 64
        and timestamp.get("mode") == "wrapper_metadata_created_at"
        and timestamp.get("sdk_native_timestamp") is False
        and isinstance(attestation, Mapping)
        and attestation.get("status") == "passed"
        and attestation.get("metadata_created_at_roundtrip_attested") is True
        and attestation.get("cleanup_succeeded") is True
        and identity.get("source_id_roundtrip_attested") is True
        and identity.get("source_sha256_roundtrip_attested") is True
        and integrity.get("manifest_sha256") == manifest_integrity_sha256(payload)
    )


def _wrapper_source_sha256() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
