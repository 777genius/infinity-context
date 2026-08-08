"""Provider-free Mem0 OSS v4 manifest profile and public projection.

Version four is deliberately additive: it preserves the v3 runtime shape while
making the signed, run-scoped usage witness an explicit capability.  The v3
profile remains sealed in its own module so historical evidence stays
reproducible under the tuple it was originally reviewed against.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final

from infinity_context_server.memory_comparison_mem0_oss_manifest import (
    MEM0_OSS_ADAPTER,
    MEM0_OSS_EMBEDDING,
    MEM0_OSS_FASTEMBED_PACKAGE,
    MEM0_OSS_LEDGER_FIELDS,
    MEM0_OSS_MEM0AI_PACKAGE,
    MEM0_OSS_PYTHON_IMAGE_DIGEST,
    MEM0_OSS_QDRANT_CLIENT_PACKAGE,
    MEM0_OSS_QDRANT_IMAGE_DIGEST,
    MEM0_OSS_RUNTIME_MODE,
    exact_mapping,
    is_sha256,
    is_utc_instant,
    public_bool,
    public_bound,
    public_cap,
    public_instant,
    public_sha256,
    public_timestamp_status,
)

MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4: Final = "mem0-benchmark-capabilities.v4"
REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION: Final = "6dcdb1339f7af7010bb027d8fdd881a726a4e824"
REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256: Final = (
    "9109c2fdc554b86e213773aa40bd29816082199681dabb4ac3246b33ca5814fe"
)
REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256: Final = (
    "075ec6cf7d5691fa388e2c413fa34e48cbf7cbb14b3b037fbc18fe9a8cf0d17c"
)
REVIEWED_MEM0_OSS_V4_LOCK_SHA256: Final = (
    "70a54d810222b68f1f8b76f1fcf9c4332875f3fc242682fee3b5779db122f73d"
)

MEM0_OSS_V4_CAPABILITIES: Final = (
    "delete_verified_absence",
    "hmac_auth_challenge",
    "offline_fastembed",
    "raw_passthrough",
    "same_run_refresh_witness",
    "signed_run_scoped_usage_evidence",
    "source_identity_roundtrip",
    "subscription_llm_extraction",
)
MEM0_OSS_V4_USAGE_EVIDENCE: Final = {
    "schema_version": "mem0-benchmark-usage-attestation.v1",
    "run_scoped": True,
    "hmac_sha256": True,
    "ingress_auth_required": True,
    "probe_token_required": True,
}
MEM0_OSS_V4_BASE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "runtime_mode",
        "configured",
        "wrapper_source_revision",
        "wrapper_source_sha256",
        "config_fingerprint_sha256",
        "adapter",
        "runtime",
        "packages",
        "embedding",
        "extraction",
        "timestamp",
        "persisted_source_identity",
        "capabilities",
        "delete",
        "integrity",
    }
)
MEM0_OSS_V4_REFRESH_FIELDS: Final = frozenset({"refresh_binding", "refresh_witness"})


def mem0_oss_v4_runtime_manifest_sha256(payload: object) -> str | None:
    """Return the v4 immutable-manifest checksum without HMAC witness material."""

    if not isinstance(payload, Mapping):
        return None
    canonical = _copy_without_keys(
        payload,
        drop_top_level=frozenset({"refresh_witness"}),
        drop_integrity_manifest=True,
    )
    return _canonical_sha256(canonical) if canonical is not None else None


def mem0_oss_v4_refresh_manifest_sha256(payload: object) -> str | None:
    """Return the existing refresh-witness fingerprint for a v4 response."""

    if not isinstance(payload, Mapping):
        return None
    canonical = _copy_without_keys(payload, drop_top_level=frozenset({"refresh_witness"}))
    return _canonical_sha256(canonical) if canonical is not None else None


def public_mem0_oss_v4_runtime_manifest(payload: object) -> dict[str, object]:
    """Project a fixed v4 shape without URLs, credentials, paths, or texts."""

    if not isinstance(payload, Mapping):
        return {}
    public: dict[str, object] = {}
    _project_scalars(payload, public)
    if "runtime" in payload:
        public["runtime"] = _project_runtime(payload.get("runtime"))
    if "packages" in payload:
        public["packages"] = _project_packages(payload.get("packages"))
    if "embedding" in payload:
        public["embedding"] = _project_embedding(payload.get("embedding"))
    if "extraction" in payload:
        public["extraction"] = _project_extraction(payload.get("extraction"))
    if "timestamp" in payload:
        public["timestamp"] = _project_timestamp(payload.get("timestamp"))
    if "persisted_source_identity" in payload:
        public["persisted_source_identity"] = _project_persisted_source_identity(
            payload.get("persisted_source_identity")
        )
    if "capabilities" in payload:
        public["capabilities"] = (
            list(MEM0_OSS_V4_CAPABILITIES)
            if _matches_ordered_sequence(payload.get("capabilities"), MEM0_OSS_V4_CAPABILITIES)
            else []
        )
    if "delete" in payload:
        delete = exact_mapping(payload.get("delete"), {"verified_absent"}) or {}
        public["delete"] = {"verified_absent": delete.get("verified_absent") is True}
    if "integrity" in payload:
        public["integrity"] = _project_integrity(payload.get("integrity"))
    if "refresh_binding" in payload:
        public["refresh_binding"] = _project_refresh_binding(payload.get("refresh_binding"))
    return public


def _project_scalars(payload: Mapping[str, object], public: dict[str, object]) -> None:
    if "schema_version" in payload:
        public["schema_version"] = (
            MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4
            if payload.get("schema_version") == MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4
            else "invalid"
        )
    if "runtime_mode" in payload:
        public["runtime_mode"] = (
            MEM0_OSS_RUNTIME_MODE
            if payload.get("runtime_mode") == MEM0_OSS_RUNTIME_MODE
            else "invalid"
        )
    if "configured" in payload:
        public["configured"] = payload.get("configured") is True
    for key, expected in (
        ("wrapper_source_revision", REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION),
        ("wrapper_source_sha256", REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256),
    ):
        if key in payload:
            public[key] = expected if payload.get(key) == expected else "invalid"
    if "config_fingerprint_sha256" in payload:
        value = payload.get("config_fingerprint_sha256")
        public["config_fingerprint_sha256"] = value if is_sha256(value) else "invalid"
    if "adapter" in payload:
        public["adapter"] = (
            MEM0_OSS_ADAPTER if payload.get("adapter") == MEM0_OSS_ADAPTER else "invalid"
        )
    if set(payload).difference(MEM0_OSS_V4_BASE_FIELDS | MEM0_OSS_V4_REFRESH_FIELDS) and (
        "schema_version" in public
    ):
        public["schema_version"] = "invalid"


def _project_runtime(value: object) -> dict[str, object]:
    runtime = (
        exact_mapping(
            value,
            {"mode", "auth_mode", "python_version", "python_image_digest", "qdrant_image_digest"},
        )
        or {}
    )
    return {
        "mode": MEM0_OSS_RUNTIME_MODE
        if runtime.get("mode") == MEM0_OSS_RUNTIME_MODE
        else "invalid",
        "auth_mode": "none" if runtime.get("auth_mode") == "none" else "invalid",
        "python_version": "3.11" if runtime.get("python_version") == "3.11" else "invalid",
        "python_image_digest": (
            MEM0_OSS_PYTHON_IMAGE_DIGEST
            if runtime.get("python_image_digest") == MEM0_OSS_PYTHON_IMAGE_DIGEST
            else "invalid"
        ),
        "qdrant_image_digest": (
            MEM0_OSS_QDRANT_IMAGE_DIGEST
            if runtime.get("qdrant_image_digest") == MEM0_OSS_QDRANT_IMAGE_DIGEST
            else "invalid"
        ),
    }


def _project_packages(value: object) -> dict[str, object]:
    packages = exact_mapping(value, {"mem0ai", "fastembed", "qdrant_client"}) or {}
    return {
        "mem0ai": _project_exact_mapping(packages.get("mem0ai"), MEM0_OSS_MEM0AI_PACKAGE),
        "fastembed": _project_exact_mapping(packages.get("fastembed"), MEM0_OSS_FASTEMBED_PACKAGE),
        "qdrant_client": _project_exact_mapping(
            packages.get("qdrant_client"), MEM0_OSS_QDRANT_CLIENT_PACKAGE
        ),
    }


def _project_embedding(value: object) -> dict[str, object]:
    embedding = (
        exact_mapping(
            value,
            {"provider", "model", "model_revision", "onnx_sha256", "dimensions", "offline"},
        )
        or {}
    )
    return {
        **{
            key: expected if embedding.get(key) == expected else "invalid"
            for key, expected in MEM0_OSS_EMBEDDING.items()
        },
        "offline": embedding.get("offline") is True,
    }


def _project_extraction(value: object) -> dict[str, object]:
    extraction = (
        exact_mapping(
            value,
            {
                "mode",
                "raw_passthrough_supported",
                "extraction_enabled",
                "telemetry_enabled",
                "max_calls_per_add",
                "request_max_bytes",
                "response_max_bytes",
                "subscription_scope",
                "usage_ledger",
                "usage_evidence",
            },
        )
        or {}
    )
    mode = extraction.get("mode")
    ledger = exact_mapping(extraction.get("usage_ledger"), {"required", "fields"}) or {}
    return {
        "mode": mode if mode in {"raw_passthrough", "subscription_llm"} else "invalid",
        "raw_passthrough_supported": extraction.get("raw_passthrough_supported") is True,
        "extraction_enabled": public_bool(extraction.get("extraction_enabled")),
        "telemetry_enabled": public_bool(extraction.get("telemetry_enabled")),
        "max_calls_per_add": public_cap(extraction.get("max_calls_per_add")),
        "request_max_bytes": public_bound(extraction.get("request_max_bytes")),
        "response_max_bytes": public_bound(extraction.get("response_max_bytes")),
        "subscription_scope": (
            "isolated_single_add"
            if extraction.get("subscription_scope") == "isolated_single_add"
            else "invalid"
        ),
        "usage_ledger": {
            "required": ledger.get("required") is True,
            "fields": list(MEM0_OSS_LEDGER_FIELDS)
            if _matches_ordered_sequence(ledger.get("fields"), MEM0_OSS_LEDGER_FIELDS)
            else [],
        },
        "usage_evidence": _project_exact_mapping(
            extraction.get("usage_evidence"), MEM0_OSS_V4_USAGE_EVIDENCE
        ),
    }


def _project_timestamp(value: object) -> dict[str, object]:
    timestamp = (
        exact_mapping(
            value,
            {
                "mode",
                "sdk_native_timestamp",
                "request_supported",
                "metadata_readback_supported",
                "attestation",
            },
        )
        or {}
    )
    attestation = (
        exact_mapping(
            timestamp.get("attestation"),
            {"status", "checked_at", "metadata_created_at_roundtrip_attested", "cleanup_succeeded"},
        )
        or {}
    )
    checked_at = attestation.get("checked_at") if "checked_at" in attestation else "invalid"
    cleanup_succeeded = (
        attestation.get("cleanup_succeeded") if "cleanup_succeeded" in attestation else "invalid"
    )
    return {
        "mode": (
            "wrapper_metadata_created_at"
            if timestamp.get("mode") == "wrapper_metadata_created_at"
            else "invalid"
        ),
        "sdk_native_timestamp": public_bool(timestamp.get("sdk_native_timestamp")),
        "request_supported": timestamp.get("request_supported") is True,
        "metadata_readback_supported": timestamp.get("metadata_readback_supported") is True,
        "attestation": {
            "status": public_timestamp_status(attestation.get("status")),
            "checked_at": checked_at
            if checked_at is None or is_utc_instant(checked_at)
            else "invalid",
            "metadata_created_at_roundtrip_attested": public_bool(
                attestation.get("metadata_created_at_roundtrip_attested")
            ),
            "cleanup_succeeded": cleanup_succeeded
            if cleanup_succeeded is None or cleanup_succeeded is True
            else "invalid",
        },
    }


def _project_persisted_source_identity(value: object) -> dict[str, bool | str]:
    identity = (
        exact_mapping(
            value,
            {
                "request_metadata_required",
                "source_filtered_readback_supported",
                "source_id_roundtrip_attested",
                "source_sha256_roundtrip_attested",
                "sanitized_identity_response",
            },
        )
        or {}
    )
    return {
        field: identity.get(field) if isinstance(identity.get(field), bool) else "invalid"
        for field in (
            "request_metadata_required",
            "source_filtered_readback_supported",
            "source_id_roundtrip_attested",
            "source_sha256_roundtrip_attested",
            "sanitized_identity_response",
        )
    }


def _project_integrity(value: object) -> dict[str, str]:
    integrity = exact_mapping(value, {"manifest_sha256", "runtime_pin_sha256", "lock_sha256"}) or {}
    return {
        "manifest_sha256": (
            integrity["manifest_sha256"]
            if is_sha256(integrity.get("manifest_sha256"))
            else "invalid"
        ),
        "runtime_pin_sha256": (
            REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256
            if integrity.get("runtime_pin_sha256") == REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256
            else "invalid"
        ),
        "lock_sha256": (
            REVIEWED_MEM0_OSS_V4_LOCK_SHA256
            if integrity.get("lock_sha256") == REVIEWED_MEM0_OSS_V4_LOCK_SHA256
            else "invalid"
        ),
    }


def _project_refresh_binding(value: object) -> dict[str, object]:
    binding = (
        exact_mapping(
            value,
            {
                "status",
                "run_id_sha256",
                "probe_nonce_sha256",
                "target_identity_sha256",
                "refreshed_at",
            },
        )
        or {}
    )
    return {
        "status": "passed" if binding.get("status") == "passed" else "invalid",
        "run_id_sha256": public_sha256(binding.get("run_id_sha256")),
        "probe_nonce_sha256": public_sha256(binding.get("probe_nonce_sha256")),
        "target_identity_sha256": public_sha256(binding.get("target_identity_sha256")),
        "refreshed_at": public_instant(binding.get("refreshed_at")),
    }


def _project_exact_mapping(value: object, expected: Mapping[str, object]) -> dict[str, object]:
    candidate = exact_mapping(value, set(expected)) or {}
    return {
        key: expected_value if candidate.get(key) == expected_value else "invalid"
        for key, expected_value in expected.items()
    }


def _matches_ordered_sequence(value: object, expected: tuple[str, ...]) -> bool:
    return isinstance(value, list | tuple) and tuple(value) == expected


def _copy_without_keys(
    payload: Mapping[str, object],
    *,
    drop_top_level: frozenset[str],
    drop_integrity_manifest: bool = False,
) -> dict[str, object] | None:
    try:
        copied = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return None
    if not isinstance(copied, dict):
        return None
    for key in drop_top_level:
        copied.pop(key, None)
    if drop_integrity_manifest:
        integrity = copied.get("integrity")
        if not isinstance(integrity, dict):
            return None
        integrity.pop("manifest_sha256", None)
    return copied


def _canonical_sha256(value: object) -> str | None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4",
    "MEM0_OSS_V4_BASE_FIELDS",
    "MEM0_OSS_V4_CAPABILITIES",
    "MEM0_OSS_V4_REFRESH_FIELDS",
    "MEM0_OSS_V4_USAGE_EVIDENCE",
    "REVIEWED_MEM0_OSS_V4_LOCK_SHA256",
    "REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256",
    "REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION",
    "REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256",
    "mem0_oss_v4_refresh_manifest_sha256",
    "mem0_oss_v4_runtime_manifest_sha256",
    "public_mem0_oss_v4_runtime_manifest",
)
