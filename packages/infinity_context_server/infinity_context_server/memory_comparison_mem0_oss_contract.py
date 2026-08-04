"""Strict, provider-free validation policy for the reproducible Mem0 OSS v3 runtime."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_server.memory_comparison_mem0_oss_manifest import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3,
    MEM0_OSS_ADAPTER,
    MEM0_OSS_BASE_FIELDS,
    MEM0_OSS_CAPABILITIES,
    MEM0_OSS_EMBEDDING,
    MEM0_OSS_FASTEMBED_PACKAGE,
    MEM0_OSS_LEDGER_FIELDS,
    MEM0_OSS_MAX_LEDGER_BYTES,
    MEM0_OSS_MEM0AI_PACKAGE,
    MEM0_OSS_PYTHON_IMAGE_DIGEST,
    MEM0_OSS_QDRANT_CLIENT_PACKAGE,
    MEM0_OSS_QDRANT_IMAGE_DIGEST,
    MEM0_OSS_REFRESH_FIELDS,
    MEM0_OSS_RUNTIME_MODE,
    REVIEWED_MEM0_OSS_LOCK_SHA256,
    REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256,
    REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256,
    exact_mapping,
    exact_mapping_matches,
    is_revision,
    is_sha256,
    is_utc_instant,
    mapping,
    mem0_oss_refresh_manifest_sha256,
    mem0_oss_runtime_manifest_sha256,
    public_mem0_oss_runtime_manifest,
)

MEM0_OSS_RUNTIME_CAPABILITY_ISSUE_CODES = frozenset(
    {
        "oss_v3_manifest_not_object",
        "oss_v3_unknown_top_level_fields",
        "oss_v3_missing_top_level_fields",
        "oss_v3_schema_version_mismatch",
        "oss_v3_configured_not_true",
        "oss_v3_wrapper_source_revision_invalid",
        "oss_v3_wrapper_source_revision_mismatch",
        "oss_v3_wrapper_source_sha256_invalid",
        "oss_v3_wrapper_source_sha256_mismatch",
        "oss_v3_config_fingerprint_sha256_invalid",
        "oss_v3_adapter_mismatch",
        "oss_v3_runtime_invalid",
        "oss_v3_runtime_mode_mismatch",
        "oss_v3_runtime_auth_mode_invalid",
        "oss_v3_runtime_python_version_mismatch",
        "oss_v3_runtime_python_image_digest_mismatch",
        "oss_v3_runtime_qdrant_image_digest_mismatch",
        "oss_v3_packages_invalid",
        "oss_v3_mem0ai_package_mismatch",
        "oss_v3_fastembed_package_mismatch",
        "oss_v3_qdrant_client_package_mismatch",
        "oss_v3_embedding_invalid",
        "oss_v3_embedding_mismatch",
        "oss_v3_extraction_invalid",
        "oss_v3_extraction_mode_invalid",
        "oss_v3_extraction_cap_invalid",
        "oss_v3_extraction_subscription_scope_invalid",
        "oss_v3_extraction_telemetry_enabled",
        "oss_v3_usage_ledger_invalid",
        "oss_v3_timestamp_invalid",
        "oss_v3_timestamp_mode_invalid",
        "oss_v3_timestamp_sdk_native_invalid",
        "oss_v3_timestamp_request_not_supported",
        "oss_v3_timestamp_readback_not_supported",
        "oss_v3_timestamp_unbound_attestation_invalid",
        "oss_v3_timestamp_refresh_attestation_invalid",
        "oss_v3_persisted_source_identity_invalid",
        "oss_v3_persisted_source_identity_static_invalid",
        "oss_v3_persisted_source_identity_unbound_invalid",
        "oss_v3_persisted_source_identity_refresh_invalid",
        "oss_v3_capabilities_invalid",
        "oss_v3_delete_invalid",
        "oss_v3_integrity_invalid",
        "oss_v3_runtime_pin_sha256_mismatch",
        "oss_v3_lock_sha256_mismatch",
        "oss_v3_manifest_sha256_mismatch",
        "oss_v3_refresh_witness_without_binding",
        "oss_v3_refresh_binding_invalid",
        "oss_v3_refresh_witness_invalid",
        "oss_v3_refresh_witness_fingerprint_mismatch",
        "oss_v3_refresh_timestamp_binding_mismatch",
    }
)


def evaluate_mem0_oss_runtime_capabilities(
    payload: object,
    *,
    require_timestamp: bool,
) -> tuple[str, ...]:
    """Validate one exact Mem0 OSS v3 capability manifest without provider imports.

    v3 always requires wrapper-managed timestamp evidence. A raw refresh response
    must first pass the generic HMAC verifier; its verified public projection then
    intentionally has a binding but no HMAC witness.
    """

    del require_timestamp
    if not isinstance(payload, Mapping):
        return ("oss_v3_manifest_not_object",)

    issues: list[str] = []
    _validate_top_level(payload, issues)
    _validate_scalar_provenance(payload, issues)
    _validate_runtime(payload.get("runtime"), issues)
    _validate_packages(payload.get("packages"), issues)
    _validate_embedding(payload.get("embedding"), issues)
    _validate_extraction(payload.get("extraction"), issues)
    refresh_bound = "refresh_binding" in payload
    _validate_timestamp(payload.get("timestamp"), refresh_bound=refresh_bound, issues=issues)
    _validate_persisted_source_identity(
        payload.get("persisted_source_identity"),
        refresh_bound=refresh_bound,
        issues=issues,
    )
    _validate_capabilities(payload.get("capabilities"), issues)
    _validate_delete(payload.get("delete"), issues)
    _validate_integrity(payload, issues)
    _validate_refresh_evidence(payload, issues)
    return tuple(dict.fromkeys(issues))


def _validate_top_level(payload: Mapping[str, object], issues: list[str]) -> None:
    keys = set(payload)
    if keys.difference(MEM0_OSS_BASE_FIELDS | MEM0_OSS_REFRESH_FIELDS):
        issues.append("oss_v3_unknown_top_level_fields")
    if MEM0_OSS_BASE_FIELDS.difference(keys):
        issues.append("oss_v3_missing_top_level_fields")
    if "refresh_witness" in keys and "refresh_binding" not in keys:
        issues.append("oss_v3_refresh_witness_without_binding")


def _validate_scalar_provenance(payload: Mapping[str, object], issues: list[str]) -> None:
    if payload.get("schema_version") != MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3:
        issues.append("oss_v3_schema_version_mismatch")
    if payload.get("runtime_mode") != MEM0_OSS_RUNTIME_MODE:
        issues.append("oss_v3_runtime_mode_mismatch")
    if payload.get("configured") is not True:
        issues.append("oss_v3_configured_not_true")
    wrapper_revision = payload.get("wrapper_source_revision")
    if not is_revision(wrapper_revision):
        issues.append("oss_v3_wrapper_source_revision_invalid")
    elif wrapper_revision != REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION:
        issues.append("oss_v3_wrapper_source_revision_mismatch")
    wrapper_sha256 = payload.get("wrapper_source_sha256")
    if not is_sha256(wrapper_sha256):
        issues.append("oss_v3_wrapper_source_sha256_invalid")
    elif wrapper_sha256 != REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256:
        issues.append("oss_v3_wrapper_source_sha256_mismatch")
    if not is_sha256(payload.get("config_fingerprint_sha256")):
        issues.append("oss_v3_config_fingerprint_sha256_invalid")
    if payload.get("adapter") != MEM0_OSS_ADAPTER:
        issues.append("oss_v3_adapter_mismatch")


def _validate_runtime(value: object, issues: list[str]) -> None:
    runtime = exact_mapping(
        value,
        {"mode", "auth_mode", "python_version", "python_image_digest", "qdrant_image_digest"},
    )
    if runtime is None:
        issues.append("oss_v3_runtime_invalid")
        return
    if runtime.get("mode") != MEM0_OSS_RUNTIME_MODE:
        issues.append("oss_v3_runtime_mode_mismatch")
    if runtime.get("auth_mode") != "none":
        issues.append("oss_v3_runtime_auth_mode_invalid")
    if runtime.get("python_version") != "3.11":
        issues.append("oss_v3_runtime_python_version_mismatch")
    if runtime.get("python_image_digest") != MEM0_OSS_PYTHON_IMAGE_DIGEST:
        issues.append("oss_v3_runtime_python_image_digest_mismatch")
    if runtime.get("qdrant_image_digest") != MEM0_OSS_QDRANT_IMAGE_DIGEST:
        issues.append("oss_v3_runtime_qdrant_image_digest_mismatch")


def _validate_packages(value: object, issues: list[str]) -> None:
    packages = exact_mapping(value, {"mem0ai", "fastembed", "qdrant_client"})
    if packages is None:
        issues.append("oss_v3_packages_invalid")
        return
    if not exact_mapping_matches(packages.get("mem0ai"), MEM0_OSS_MEM0AI_PACKAGE):
        issues.append("oss_v3_mem0ai_package_mismatch")
    if not exact_mapping_matches(packages.get("fastembed"), MEM0_OSS_FASTEMBED_PACKAGE):
        issues.append("oss_v3_fastembed_package_mismatch")
    if not exact_mapping_matches(packages.get("qdrant_client"), MEM0_OSS_QDRANT_CLIENT_PACKAGE):
        issues.append("oss_v3_qdrant_client_package_mismatch")


def _validate_embedding(value: object, issues: list[str]) -> None:
    embedding = exact_mapping(
        value,
        {"provider", "model", "model_revision", "onnx_sha256", "dimensions", "offline"},
    )
    if embedding is None:
        issues.append("oss_v3_embedding_invalid")
        return
    if any(embedding.get(key) != expected for key, expected in MEM0_OSS_EMBEDDING.items()):
        issues.append("oss_v3_embedding_mismatch")
    if embedding.get("offline") is not True:
        issues.append("oss_v3_embedding_mismatch")


def _validate_extraction(value: object, issues: list[str]) -> None:
    extraction = exact_mapping(
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
    if extraction is None:
        issues.append("oss_v3_extraction_invalid")
        return
    mode = extraction.get("mode")
    if not isinstance(mode, str) or mode not in {"raw_passthrough", "subscription_llm"}:
        issues.append("oss_v3_extraction_mode_invalid")
    elif not _valid_extraction_mode(extraction, mode):
        issues.append("oss_v3_extraction_cap_invalid")
    if extraction.get("subscription_scope") != "isolated_single_add":
        issues.append("oss_v3_extraction_subscription_scope_invalid")
    if extraction.get("telemetry_enabled") is not False:
        issues.append("oss_v3_extraction_telemetry_enabled")
    if not all(
        _valid_non_negative_bound(extraction.get(key))
        for key in ("request_max_bytes", "response_max_bytes")
    ):
        issues.append("oss_v3_extraction_cap_invalid")
    if not _valid_usage_ledger(extraction.get("usage_ledger")):
        issues.append("oss_v3_usage_ledger_invalid")


def _validate_timestamp(
    value: object,
    *,
    refresh_bound: bool,
    issues: list[str],
) -> None:
    timestamp = exact_mapping(
        value,
        {
            "mode",
            "sdk_native_timestamp",
            "request_supported",
            "metadata_readback_supported",
            "attestation",
        },
    )
    if timestamp is None:
        issues.append("oss_v3_timestamp_invalid")
        return
    if timestamp.get("mode") != "wrapper_metadata_created_at":
        issues.append("oss_v3_timestamp_mode_invalid")
    if timestamp.get("sdk_native_timestamp") is not False:
        issues.append("oss_v3_timestamp_sdk_native_invalid")
    if timestamp.get("request_supported") is not True:
        issues.append("oss_v3_timestamp_request_not_supported")
    if timestamp.get("metadata_readback_supported") is not True:
        issues.append("oss_v3_timestamp_readback_not_supported")
    valid_attestation = (
        _valid_refreshed_timestamp_attestation(timestamp.get("attestation"))
        if refresh_bound
        else _valid_unbound_timestamp_attestation(timestamp.get("attestation"))
    )
    if not valid_attestation:
        issues.append(
            "oss_v3_timestamp_refresh_attestation_invalid"
            if refresh_bound
            else "oss_v3_timestamp_unbound_attestation_invalid"
        )


def _validate_persisted_source_identity(
    value: object,
    *,
    refresh_bound: bool,
    issues: list[str],
) -> None:
    identity = exact_mapping(
        value,
        {
            "request_metadata_required",
            "source_filtered_readback_supported",
            "source_id_roundtrip_attested",
            "source_sha256_roundtrip_attested",
            "sanitized_identity_response",
        },
    )
    if identity is None:
        issues.append("oss_v3_persisted_source_identity_invalid")
        return
    if (
        identity.get("request_metadata_required") is not True
        or identity.get("source_filtered_readback_supported") is not True
        or identity.get("sanitized_identity_response") is not True
    ):
        issues.append("oss_v3_persisted_source_identity_static_invalid")
    expected_attested = refresh_bound
    if (
        identity.get("source_id_roundtrip_attested") is not expected_attested
        or identity.get("source_sha256_roundtrip_attested") is not expected_attested
    ):
        issues.append(
            "oss_v3_persisted_source_identity_refresh_invalid"
            if refresh_bound
            else "oss_v3_persisted_source_identity_unbound_invalid"
        )


def _validate_capabilities(value: object, issues: list[str]) -> None:
    if not isinstance(value, list) or tuple(value) != MEM0_OSS_CAPABILITIES:
        issues.append("oss_v3_capabilities_invalid")


def _validate_delete(value: object, issues: list[str]) -> None:
    delete = exact_mapping(value, {"verified_absent"})
    if delete is None or delete.get("verified_absent") is not True:
        issues.append("oss_v3_delete_invalid")


def _validate_integrity(payload: Mapping[str, object], issues: list[str]) -> None:
    integrity = exact_mapping(
        payload.get("integrity"),
        {"manifest_sha256", "runtime_pin_sha256", "lock_sha256"},
    )
    if integrity is None or not all(is_sha256(integrity.get(key)) for key in integrity):
        issues.append("oss_v3_integrity_invalid")
        return
    if integrity.get("runtime_pin_sha256") != REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256:
        issues.append("oss_v3_runtime_pin_sha256_mismatch")
    if integrity.get("lock_sha256") != REVIEWED_MEM0_OSS_LOCK_SHA256:
        issues.append("oss_v3_lock_sha256_mismatch")
    if integrity.get("manifest_sha256") != mem0_oss_runtime_manifest_sha256(payload):
        issues.append("oss_v3_manifest_sha256_mismatch")


def _validate_refresh_evidence(payload: Mapping[str, object], issues: list[str]) -> None:
    if "refresh_binding" not in payload:
        return
    binding = exact_mapping(
        payload.get("refresh_binding"),
        {"status", "run_id_sha256", "probe_nonce_sha256", "target_identity_sha256", "refreshed_at"},
    )
    if binding is None or (
        binding.get("status") != "passed"
        or not all(
            is_sha256(binding.get(key))
            for key in ("run_id_sha256", "probe_nonce_sha256", "target_identity_sha256")
        )
        or not is_utc_instant(binding.get("refreshed_at"))
    ):
        issues.append("oss_v3_refresh_binding_invalid")
        return
    attestation = mapping(mapping(payload.get("timestamp")).get("attestation"))
    if binding.get("refreshed_at") != attestation.get("checked_at"):
        issues.append("oss_v3_refresh_timestamp_binding_mismatch")
    witness_value = payload.get("refresh_witness")
    if witness_value is None:
        return
    witness = exact_mapping(
        witness_value,
        {"algorithm", "manifest_fingerprint_sha256", "signature"},
    )
    if (
        witness is None
        or witness.get("algorithm") != "hmac-sha256"
        or not all(
            is_sha256(witness.get(key)) for key in ("manifest_fingerprint_sha256", "signature")
        )
    ):
        issues.append("oss_v3_refresh_witness_invalid")
        return
    if witness.get("manifest_fingerprint_sha256") != mem0_oss_refresh_manifest_sha256(payload):
        issues.append("oss_v3_refresh_witness_fingerprint_mismatch")


def _valid_extraction_mode(extraction: Mapping[str, object], mode: str) -> bool:
    if extraction.get("raw_passthrough_supported") is not True:
        return False
    expected_enabled, expected_calls = (False, 0) if mode == "raw_passthrough" else (True, 1)
    return (
        extraction.get("extraction_enabled") is expected_enabled
        and type(extraction.get("max_calls_per_add")) is int
        and extraction.get("max_calls_per_add") == expected_calls
    )


def _valid_non_negative_bound(value: object) -> bool:
    return type(value) is int and 0 < value <= MEM0_OSS_MAX_LEDGER_BYTES


def _valid_usage_ledger(value: object) -> bool:
    ledger = exact_mapping(value, {"required", "fields"})
    return (
        ledger is not None
        and ledger.get("required") is True
        and ledger.get("fields") == list(MEM0_OSS_LEDGER_FIELDS)
    )


def _valid_unbound_timestamp_attestation(value: object) -> bool:
    attestation = exact_mapping(
        value,
        {"status", "checked_at", "metadata_created_at_roundtrip_attested", "cleanup_succeeded"},
    )
    return bool(
        attestation
        and attestation.get("status") == "not_run"
        and attestation.get("checked_at") is None
        and attestation.get("metadata_created_at_roundtrip_attested") is False
        and attestation.get("cleanup_succeeded") is None
    )


def _valid_refreshed_timestamp_attestation(value: object) -> bool:
    attestation = exact_mapping(
        value,
        {"status", "checked_at", "metadata_created_at_roundtrip_attested", "cleanup_succeeded"},
    )
    return bool(
        attestation
        and attestation.get("status") == "passed"
        and is_utc_instant(attestation.get("checked_at"))
        and attestation.get("metadata_created_at_roundtrip_attested") is True
        and attestation.get("cleanup_succeeded") is True
    )


__all__ = (
    "MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3",
    "MEM0_OSS_ADAPTER",
    "MEM0_OSS_RUNTIME_CAPABILITY_ISSUE_CODES",
    "MEM0_OSS_RUNTIME_MODE",
    "REVIEWED_MEM0_OSS_LOCK_SHA256",
    "REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256",
    "REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION",
    "REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256",
    "evaluate_mem0_oss_runtime_capabilities",
    "mem0_oss_refresh_manifest_sha256",
    "mem0_oss_runtime_manifest_sha256",
    "public_mem0_oss_runtime_manifest",
)
