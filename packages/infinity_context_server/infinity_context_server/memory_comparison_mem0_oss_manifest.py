"""Provider-free Mem0 OSS v3 manifest profile, hashing, and public projection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3: Final = "mem0-benchmark-capabilities.v3"
MEM0_OSS_ADAPTER: Final = "mem0_oss"
MEM0_OSS_RUNTIME_MODE: Final = "oss"
REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION: Final = "10a7572007055ac9791b35d571a7844a432fe862"
REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256: Final = (
    "bc84ec6d608568cceb0aa23f92990018ddfba9e4cb8b575608a55d7dd1f58ba9"
)
REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256: Final = (
    "efa3a315048f6c117d61295be42af0d9cc36ecb1b627d4456a31da0764754f5a"
)
REVIEWED_MEM0_OSS_LOCK_SHA256: Final = (
    "70a54d810222b68f1f8b76f1fcf9c4332875f3fc242682fee3b5779db122f73d"
)

MEM0_OSS_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MEM0_OSS_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_MAX_CLOCK_YEAR = 2100
_MIN_CLOCK_YEAR = 2020

MEM0_OSS_MAX_LEDGER_BYTES = 1_048_576
MEM0_OSS_MEM0AI_PACKAGE: Final = {
    "version": "2.0.15",
    "source_revision": "50bdaaea0c02744720ed374d88584fd01494eeb7",
    "wheel_sha256": "d5c0565ea385cecc8643aa4f4ed61dab56d4f60273499fa2b4e43fc0e5e9c273",
}
MEM0_OSS_FASTEMBED_PACKAGE: Final = {
    "version": "0.8.0",
    "wheel_sha256": "40bee672657574a1009e35ec50030a55f2b426842cb011845379817641bbbbd0",
}
MEM0_OSS_QDRANT_CLIENT_PACKAGE: Final = {
    "version": "1.18.0",
    "wheel_sha256": "093aa8cf8a420ee3ad2a68b007e1378d7992b2600e0b53c193fc172674f659cd",
}
MEM0_OSS_PYTHON_IMAGE_DIGEST: Final = (
    "sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
)
MEM0_OSS_QDRANT_IMAGE_DIGEST: Final = (
    "sha256:0bd98fa7977f1e75694779359ca4e212822e5a71334e28421182f72f209d5286"
)
MEM0_OSS_EMBEDDING: Final = {
    "provider": "fastembed",
    "model": "BAAI/bge-small-en-v1.5",
    "model_revision": "52398278842ec682c6f32300af41344b1c0b0bb2",
    "onnx_sha256": "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431",
    "dimensions": 384,
}
MEM0_OSS_LEDGER_FIELDS: Final = (
    "run_id",
    "operation",
    "mode",
    "extraction_calls",
    "request_bytes",
    "response_bytes",
    "model",
    "created_at",
)
MEM0_OSS_CAPABILITIES: Final = (
    "delete_verified_absence",
    "hmac_auth_challenge",
    "offline_fastembed",
    "raw_passthrough",
    "same_run_refresh_witness",
    "source_identity_roundtrip",
    "subscription_llm_extraction",
)
MEM0_OSS_BASE_FIELDS: Final = frozenset(
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
MEM0_OSS_REFRESH_FIELDS: Final = frozenset({"refresh_binding", "refresh_witness"})


def mem0_oss_runtime_manifest_sha256(payload: object) -> str | None:
    """Return the immutable-manifest checksum defined by the v3 contract.

    The HMAC witness is deliberately excluded: the witness signs the unsigned
    runtime response, while this checksum detects mutation of every unsigned field.
    """

    if not isinstance(payload, Mapping):
        return None
    canonical = _copy_without_keys(
        payload,
        drop_top_level=frozenset({"refresh_witness"}),
        drop_integrity_manifest=True,
    )
    if canonical is None:
        return None
    return _canonical_sha256(canonical)


def mem0_oss_refresh_manifest_sha256(payload: object) -> str | None:
    """Return the existing generic witness fingerprint for a v3 response."""

    if not isinstance(payload, Mapping):
        return None
    canonical = _copy_without_keys(payload, drop_top_level=frozenset({"refresh_witness"}))
    return _canonical_sha256(canonical) if canonical is not None else None


def public_mem0_oss_runtime_manifest(payload: object) -> dict[str, object]:
    """Return a safe, fixed-shape projection without URLs, secrets, paths, or text."""

    if not isinstance(payload, Mapping):
        return {}
    public: dict[str, object] = {}
    _project_scalar_fields(payload, public)
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
        public["capabilities"] = _project_capabilities(payload.get("capabilities"))
    if "delete" in payload:
        public["delete"] = _project_delete(payload.get("delete"))
    if "integrity" in payload:
        public["integrity"] = _project_integrity(payload.get("integrity"))
    if "refresh_binding" in payload:
        public["refresh_binding"] = _project_refresh_binding(payload.get("refresh_binding"))
    # HMAC signature material is verified before this projection and is not public.
    return public


def exact_mapping(value: object, expected_keys: set[str]) -> Mapping[str, object] | None:
    """Return a mapping only when it has exactly the documented field set."""

    if not isinstance(value, Mapping) or set(value) != expected_keys:
        return None
    return value


def exact_mapping_matches(value: object, expected: Mapping[str, str]) -> bool:
    """Check a nested immutable profile without accepting aliases or extras."""

    candidate = exact_mapping(value, set(expected))
    return candidate is not None and all(
        candidate.get(key) == target for key, target in expected.items()
    )


def mapping(value: object) -> Mapping[str, object]:
    """Return a mapping-only view suitable for fail-closed field reads."""

    return value if isinstance(value, Mapping) else {}


def is_sha256(value: object) -> bool:
    """Validate a lowercase SHA-256 digest without coercion."""

    return isinstance(value, str) and MEM0_OSS_SHA256_RE.fullmatch(value) is not None


def is_revision(value: object) -> bool:
    """Validate an immutable 40-character source revision without coercion."""

    return isinstance(value, str) and MEM0_OSS_REVISION_RE.fullmatch(value) is not None


def is_utc_instant(value: object) -> bool:
    """Accept bounded, timezone-explicit UTC instants only."""

    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00").astimezone(UTC)
    except ValueError:
        return False
    return _MIN_CLOCK_YEAR <= parsed.year <= _MAX_CLOCK_YEAR


def public_sha256(value: object) -> str:
    """Project a digest or the non-upgrading invalid sentinel."""

    return value if is_sha256(value) else "invalid"


def public_instant(value: object) -> str:
    """Project a bounded instant or the non-upgrading invalid sentinel."""

    return value if is_utc_instant(value) else "invalid"


def public_cap(value: object) -> int | str:
    """Project the fixed per-add call cap without accepting other integers."""

    return value if type(value) is int and value in {0, 1} else "invalid"


def public_bound(value: object) -> int | str:
    """Project a bounded byte cap without accepting coercible values."""

    return value if type(value) is int and 0 < value <= MEM0_OSS_MAX_LEDGER_BYTES else "invalid"


def public_bool(value: object) -> bool | str:
    """Project a real bool only, preventing malformed false values from upgrading."""

    return value if type(value) is bool else "invalid"


def public_timestamp_status(value: object) -> str:
    """Project only timestamp states understood by the v3 contract."""

    return value if isinstance(value, str) and value in {"not_run", "passed"} else "invalid"


def _project_scalar_fields(payload: Mapping[str, object], public: dict[str, object]) -> None:
    if "schema_version" in payload:
        public["schema_version"] = (
            MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3
            if payload.get("schema_version") == MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3
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
        ("wrapper_source_revision", REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION),
        ("wrapper_source_sha256", REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256),
    ):
        if key in payload:
            public[key] = expected if payload.get(key) == expected else "invalid"
    if "config_fingerprint_sha256" in payload:
        config_fingerprint = payload.get("config_fingerprint_sha256")
        public["config_fingerprint_sha256"] = (
            config_fingerprint if is_sha256(config_fingerprint) else "invalid"
        )
    if "adapter" in payload:
        public["adapter"] = (
            MEM0_OSS_ADAPTER if payload.get("adapter") == MEM0_OSS_ADAPTER else "invalid"
        )
    if set(payload).difference(MEM0_OSS_BASE_FIELDS | MEM0_OSS_REFRESH_FIELDS) and (
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
        "mode": (
            MEM0_OSS_RUNTIME_MODE if runtime.get("mode") == MEM0_OSS_RUNTIME_MODE else "invalid"
        ),
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
            },
        )
        or {}
    )
    mode = extraction.get("mode")
    return {
        "mode": (
            mode
            if isinstance(mode, str) and mode in {"raw_passthrough", "subscription_llm"}
            else "invalid"
        ),
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
        "usage_ledger": _project_usage_ledger(extraction.get("usage_ledger")),
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
            "checked_at": (
                checked_at if checked_at is None or is_utc_instant(checked_at) else "invalid"
            ),
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
        field: identity.get(field) if type(identity.get(field)) is bool else "invalid"
        for field in (
            "request_metadata_required",
            "source_filtered_readback_supported",
            "source_id_roundtrip_attested",
            "source_sha256_roundtrip_attested",
            "sanitized_identity_response",
        )
    }


def _project_capabilities(value: object) -> list[str]:
    return (
        list(MEM0_OSS_CAPABILITIES)
        if _matches_ordered_sequence(value, MEM0_OSS_CAPABILITIES)
        else []
    )


def _project_delete(value: object) -> dict[str, bool]:
    delete = exact_mapping(value, {"verified_absent"}) or {}
    return {"verified_absent": delete.get("verified_absent") is True}


def _project_integrity(value: object) -> dict[str, str]:
    integrity = exact_mapping(value, {"manifest_sha256", "runtime_pin_sha256", "lock_sha256"}) or {}
    return {
        "manifest_sha256": (
            integrity["manifest_sha256"]
            if is_sha256(integrity.get("manifest_sha256"))
            else "invalid"
        ),
        "runtime_pin_sha256": (
            REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256
            if integrity.get("runtime_pin_sha256") == REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256
            else "invalid"
        ),
        "lock_sha256": (
            REVIEWED_MEM0_OSS_LOCK_SHA256
            if integrity.get("lock_sha256") == REVIEWED_MEM0_OSS_LOCK_SHA256
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


def _project_exact_mapping(value: object, expected: Mapping[str, str]) -> dict[str, str]:
    candidate = exact_mapping(value, set(expected)) or {}
    return {
        key: expected_value if candidate.get(key) == expected_value else "invalid"
        for key, expected_value in expected.items()
    }


def _project_usage_ledger(value: object) -> dict[str, object]:
    ledger = exact_mapping(value, {"required", "fields"}) or {}
    return {
        "required": ledger.get("required") is True,
        "fields": list(MEM0_OSS_LEDGER_FIELDS)
        if _matches_ordered_sequence(ledger.get("fields"), MEM0_OSS_LEDGER_FIELDS)
        else [],
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
