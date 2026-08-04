from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy

import pytest
from infinity_context_server.memory_comparison_mem0_contract import (
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_oss_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3,
    evaluate_mem0_oss_runtime_capabilities,
    mem0_oss_refresh_manifest_sha256,
    mem0_oss_runtime_manifest_sha256,
    public_mem0_oss_runtime_manifest,
)

_PROBE_TOKEN = "v3-contract-probe-token"
_RUN_ID = "mem0-oss-v3-unit-run"
_NONCE = "ab" * 32
_TARGET_IDENTITY_SHA256 = "f" * 64
_CHECKED_AT = "2026-08-04T12:34:56Z"
_CAPABILITIES = [
    "delete_verified_absence",
    "hmac_auth_challenge",
    "offline_fastembed",
    "raw_passthrough",
    "same_run_refresh_witness",
    "source_identity_roundtrip",
    "subscription_llm_extraction",
]
_LEDGER_FIELDS = [
    "run_id",
    "operation",
    "mode",
    "extraction_calls",
    "request_bytes",
    "response_bytes",
    "model",
    "created_at",
]


def test_v3_unbound_capabilities_manifest_accepts_exact_raw_passthrough_profile() -> None:
    manifest = valid_v3_capabilities()

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()
    assert manifest["integrity"]["manifest_sha256"] == mem0_oss_runtime_manifest_sha256(manifest)


def test_generic_contract_dispatches_v3_without_broadening_legacy_modes() -> None:
    manifest = valid_v3_capabilities()

    assert evaluate_mem0_runtime_capabilities(manifest, require_timestamp=True) == ()
    assert public_mem0_runtime_manifest(manifest) == public_mem0_oss_runtime_manifest(manifest)


def test_v3_allows_one_bounded_subscription_extraction_call() -> None:
    manifest = valid_v3_capabilities(mode="subscription_llm")

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()
    extraction = manifest["extraction"]
    assert extraction == {
        "mode": "subscription_llm",
        "raw_passthrough_supported": True,
        "extraction_enabled": True,
        "telemetry_enabled": False,
        "max_calls_per_add": 1,
        "request_max_bytes": 65_536,
        "response_max_bytes": 65_536,
        "subscription_scope": "isolated_single_add",
        "usage_ledger": {"required": True, "fields": _LEDGER_FIELDS},
    }


def test_v3_refresh_manifest_requires_passed_source_timestamp_evidence_and_hmac_binding() -> None:
    manifest = valid_v3_capabilities(refreshed=True, signed=True)

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()
    assert manifest["refresh_witness"]["manifest_fingerprint_sha256"] == (
        mem0_oss_refresh_manifest_sha256(manifest)
    )

    public = public_mem0_oss_runtime_manifest(manifest)

    assert "refresh_witness" not in public
    assert evaluate_mem0_oss_runtime_capabilities(public, require_timestamp=True) == ()


@pytest.mark.parametrize(
    ("path", "value", "issue"),
    (
        (("runtime", "auth_mode"), "token", "oss_v3_runtime_auth_mode_invalid"),
        (
            ("runtime", "python_image_digest"),
            "sha256:" + "0" * 64,
            "oss_v3_runtime_python_image_digest_mismatch",
        ),
        (
            ("runtime", "qdrant_image_digest"),
            "sha256:" + "0" * 64,
            "oss_v3_runtime_qdrant_image_digest_mismatch",
        ),
        (("packages", "mem0ai", "version"), "2.0.14", "oss_v3_mem0ai_package_mismatch"),
        (
            ("packages", "mem0ai", "source_revision"),
            "0" * 40,
            "oss_v3_mem0ai_package_mismatch",
        ),
        (
            ("packages", "mem0ai", "wheel_sha256"),
            "0" * 64,
            "oss_v3_mem0ai_package_mismatch",
        ),
        (("packages", "fastembed", "version"), "0.7.0", "oss_v3_fastembed_package_mismatch"),
        (
            ("embedding", "model_revision"),
            "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
            "oss_v3_embedding_mismatch",
        ),
        (
            ("embedding", "onnx_sha256"),
            "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
            "oss_v3_embedding_mismatch",
        ),
        (("embedding", "dimensions"), 768, "oss_v3_embedding_mismatch"),
        (("timestamp", "mode"), "sdk_created_at", "oss_v3_timestamp_mode_invalid"),
        (("timestamp", "sdk_native_timestamp"), True, "oss_v3_timestamp_sdk_native_invalid"),
        (("extraction", "max_calls_per_add"), 1, "oss_v3_extraction_cap_invalid"),
        (("extraction", "telemetry_enabled"), True, "oss_v3_extraction_telemetry_enabled"),
        (
            ("persisted_source_identity", "source_id_roundtrip_attested"),
            True,
            "oss_v3_persisted_source_identity_unbound_invalid",
        ),
        (("delete", "verified_absent"), False, "oss_v3_delete_invalid"),
    ),
)
def test_v3_rejects_mutated_immutable_or_mode_bound_fields(
    path: tuple[str, ...],
    value: object,
    issue: str,
) -> None:
    manifest = valid_v3_capabilities()
    target: dict[str, object] = manifest
    for key in path[:-1]:
        child = target[key]
        assert isinstance(child, dict)
        target = child
    target[path[-1]] = value
    _seal_manifest(manifest)

    issues = evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True)

    assert issue in issues


def test_v3_rejects_unknown_extra_and_missing_fields_without_reflecting_them() -> None:
    manifest = valid_v3_capabilities()
    secret = "https://token:private@example.test/unsafe/raw-provider-text"
    manifest["quality_score"] = 1.0
    manifest["runtime"]["api_key"] = secret
    del manifest["packages"]["fastembed"]["wheel_sha256"]
    _seal_manifest(manifest)

    issues = evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True)
    public = public_mem0_oss_runtime_manifest(manifest)

    assert "oss_v3_unknown_top_level_fields" in issues
    assert "oss_v3_runtime_invalid" in issues
    assert "oss_v3_fastembed_package_mismatch" in issues
    rendered = json.dumps(public, sort_keys=True)
    assert secret not in rendered
    assert "quality_score" not in rendered
    assert "api_key" not in rendered


@pytest.mark.parametrize(
    ("scope", "issue"),
    (
        ("shared_full_run", "oss_v3_extraction_subscription_scope_invalid"),
        (None, "oss_v3_extraction_invalid"),
    ),
)
def test_v3_requires_exact_isolated_subscription_scope(
    scope: str | None,
    issue: str,
) -> None:
    manifest = valid_v3_capabilities()
    extraction = manifest["extraction"]
    assert isinstance(extraction, dict)
    if scope is None:
        del extraction["subscription_scope"]
    else:
        extraction["subscription_scope"] = scope
    _seal_manifest(manifest)

    issues = evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True)
    public = public_mem0_oss_runtime_manifest(manifest)

    assert issue in issues
    assert public["extraction"]["subscription_scope"] == "invalid"


def test_v3_rejects_duplicate_or_reordered_capabilities_and_usage_ledger_fields() -> None:
    manifest = valid_v3_capabilities()
    manifest["capabilities"] = [*_CAPABILITIES, _CAPABILITIES[-1]]
    manifest["extraction"]["usage_ledger"]["fields"] = list(reversed(_LEDGER_FIELDS))
    _seal_manifest(manifest)

    issues = evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True)

    assert "oss_v3_capabilities_invalid" in issues
    assert "oss_v3_usage_ledger_invalid" in issues


def test_v3_rejects_rehashed_refresh_with_mismatched_timestamp_binding() -> None:
    manifest = valid_v3_capabilities(refreshed=True, signed=True)
    manifest["timestamp"]["attestation"]["checked_at"] = "2026-08-04T12:34:55Z"
    _seal_manifest(manifest)
    _sign_refresh_witness(manifest)

    issues = evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True)

    assert "oss_v3_refresh_timestamp_binding_mismatch" in issues


def test_v3_public_projection_never_upgrades_invalid_false_required_values() -> None:
    manifest = valid_v3_capabilities()
    manifest["timestamp"]["sdk_native_timestamp"] = "private-token"
    manifest["extraction"]["telemetry_enabled"] = "private-token"
    _seal_manifest(manifest)

    public = public_mem0_oss_runtime_manifest(manifest)

    assert public["timestamp"]["sdk_native_timestamp"] == "invalid"
    assert public["extraction"]["telemetry_enabled"] == "invalid"
    assert evaluate_mem0_oss_runtime_capabilities(public, require_timestamp=True)


def valid_v3_capabilities(
    *,
    mode: str = "raw_passthrough",
    refreshed: bool = False,
    signed: bool = False,
) -> dict[str, object]:
    if mode not in {"raw_passthrough", "subscription_llm"}:
        raise ValueError("unsupported test extraction mode")
    extraction_enabled = mode == "subscription_llm"
    manifest: dict[str, object] = {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V3,
        "runtime_mode": "oss",
        "configured": True,
        "wrapper_source_revision": "a" * 40,
        "wrapper_source_sha256": "b" * 64,
        "config_fingerprint_sha256": "c" * 64,
        "adapter": "mem0_oss",
        "runtime": {
            "mode": "oss",
            "auth_mode": "none",
            "python_version": "3.11",
            "python_image_digest": (
                "sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
            ),
            "qdrant_image_digest": (
                "sha256:0bd98fa7977f1e75694779359ca4e212822e5a71334e28421182f72f209d5286"
            ),
        },
        "packages": {
            "mem0ai": {
                "version": "2.0.15",
                "source_revision": "50bdaaea0c02744720ed374d88584fd01494eeb7",
                "wheel_sha256": (
                    "d5c0565ea385cecc8643aa4f4ed61dab56d4f60273499fa2b4e43fc0e5e9c273"
                ),
            },
            "fastembed": {
                "version": "0.8.0",
                "wheel_sha256": (
                    "40bee672657574a1009e35ec50030a55f2b426842cb011845379817641bbbbd0"
                ),
            },
            "qdrant_client": {
                "version": "1.18.0",
                "wheel_sha256": (
                    "093aa8cf8a420ee3ad2a68b007e1378d7992b2600e0b53c193fc172674f659cd"
                ),
            },
        },
        "embedding": {
            "provider": "fastembed",
            "model": "BAAI/bge-small-en-v1.5",
            "model_revision": "52398278842ec682c6f32300af41344b1c0b0bb2",
            "onnx_sha256": ("51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"),
            "dimensions": 384,
            "offline": True,
        },
        "extraction": {
            "mode": mode,
            "raw_passthrough_supported": True,
            "extraction_enabled": extraction_enabled,
            "telemetry_enabled": False,
            "max_calls_per_add": 1 if extraction_enabled else 0,
            "request_max_bytes": 65_536,
            "response_max_bytes": 65_536,
            "subscription_scope": "isolated_single_add",
            "usage_ledger": {"required": True, "fields": list(_LEDGER_FIELDS)},
        },
        "timestamp": {
            "mode": "wrapper_metadata_created_at",
            "sdk_native_timestamp": False,
            "request_supported": True,
            "metadata_readback_supported": True,
            "attestation": {
                "status": "not_run",
                "checked_at": None,
                "metadata_created_at_roundtrip_attested": False,
                "cleanup_succeeded": None,
            },
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": False,
            "source_sha256_roundtrip_attested": False,
            "sanitized_identity_response": True,
        },
        "capabilities": list(_CAPABILITIES),
        "delete": {"verified_absent": True},
        "integrity": {
            "manifest_sha256": "0" * 64,
            "runtime_pin_sha256": "d" * 64,
            "lock_sha256": "e" * 64,
        },
    }
    if refreshed:
        _set_refreshed_evidence(manifest)
    _seal_manifest(manifest)
    if signed:
        _sign_refresh_witness(manifest)
    return manifest


def _set_refreshed_evidence(manifest: dict[str, object]) -> None:
    timestamp = manifest["timestamp"]
    identity = manifest["persisted_source_identity"]
    assert isinstance(timestamp, dict)
    assert isinstance(identity, dict)
    timestamp["attestation"] = {
        "status": "passed",
        "checked_at": _CHECKED_AT,
        "metadata_created_at_roundtrip_attested": True,
        "cleanup_succeeded": True,
    }
    identity.update(
        {
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
        }
    )
    manifest["refresh_binding"] = {
        "status": "passed",
        "run_id_sha256": hashlib.sha256(_RUN_ID.encode()).hexdigest(),
        "probe_nonce_sha256": hashlib.sha256(_NONCE.encode()).hexdigest(),
        "target_identity_sha256": _TARGET_IDENTITY_SHA256,
        "refreshed_at": _CHECKED_AT,
    }


def _seal_manifest(manifest: dict[str, object]) -> None:
    integrity = manifest["integrity"]
    assert isinstance(integrity, dict)
    checksum = mem0_oss_runtime_manifest_sha256(manifest)
    assert checksum is not None
    integrity["manifest_sha256"] = checksum


def _sign_refresh_witness(manifest: dict[str, object]) -> None:
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    fingerprint = mem0_oss_refresh_manifest_sha256(manifest)
    assert fingerprint is not None
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            fingerprint,
        )
    ).encode()
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": fingerprint,
        "signature": hmac.new(_PROBE_TOKEN.encode(), message, hashlib.sha256).hexdigest(),
    }


def deep_copied_v3_capabilities(**kwargs: object) -> dict[str, object]:
    """Provide a named reusable fixture without sharing mutable nested values."""

    return deepcopy(valid_v3_capabilities(**kwargs))
