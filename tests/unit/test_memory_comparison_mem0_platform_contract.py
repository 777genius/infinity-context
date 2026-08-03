from __future__ import annotations

from copy import deepcopy

import pytest
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
    MEM0_RUNTIME_CAPABILITY_ISSUE_CODES,
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
)


def test_managed_platform_snapshot_requires_live_persisted_timestamp_attestation() -> None:
    payload = _valid_platform_capabilities()

    assert (
        evaluate_mem0_runtime_capabilities(
            payload,
            require_timestamp=True,
        )
        == ()
    )


def test_managed_platform_snapshot_rejects_valid_shaped_wrapper_profile_drift() -> None:
    payload = _valid_platform_capabilities()
    payload["wrapper_source_sha256"] = "f" * 64
    payload["wrapper_source_revision"] = "e" * 40

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)

    assert "wrapper_source_sha256_mismatch" in issues
    assert "wrapper_source_revision_mismatch" in issues


def test_managed_platform_snapshot_fails_closed_when_live_probe_was_not_run() -> None:
    payload = _valid_platform_capabilities()
    timestamp = payload["timestamp"]
    assert isinstance(timestamp, dict)
    timestamp.update(
        {
            "event_completion_supported": False,
            "readback_supported": False,
            "attestation": {
                "status": "not_run",
                "failure_code": "missing_mem0_api_key",
            },
        }
    )

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)

    assert "timestamp_event_completion_not_supported" in issues
    assert "timestamp_readback_not_supported" in issues
    assert "timestamp_live_attestation_not_passed" in issues
    assert "timestamp_attestation_event_not_succeeded" in issues
    assert "timestamp_attestation_cleanup_failed" in issues


def test_public_managed_manifest_drops_live_probe_correlation_and_secrets() -> None:
    payload = _valid_platform_capabilities()
    payload["api_key"] = "secret"
    timestamp = payload["timestamp"]
    assert isinstance(timestamp, dict)
    attestation = timestamp["attestation"]
    assert isinstance(attestation, dict)
    attestation.update(
        {
            "event_id": "private-event",
            "sentinel_user_id": "private-user",
            "headers": {"Authorization": "secret"},
        }
    )

    public = public_mem0_runtime_manifest(payload)

    assert "api_key" not in public
    public_attestation = public["timestamp"]["attestation"]
    assert "event_id" not in public_attestation
    assert "sentinel_user_id" not in public_attestation
    assert "headers" not in public_attestation
    assert public["platform"]["server_revision_attestable"] is False


def test_managed_platform_snapshot_rejects_false_reproducibility_claims() -> None:
    payload = _valid_platform_capabilities()
    platform = payload["platform"]
    assert isinstance(platform, dict)
    platform["server_source_revision"] = "d" * 40

    assert evaluate_mem0_runtime_capabilities(
        payload,
        require_timestamp=False,
    ) == ("platform_server_revision_claim_inconsistent",)


_PERSISTED_SOURCE_IDENTITY_ISSUES = {
    "request_metadata_required": (
        "persisted_source_identity_request_metadata_not_required"
    ),
    "source_filtered_readback_supported": (
        "persisted_source_identity_filtered_readback_not_supported"
    ),
    "source_id_roundtrip_attested": (
        "persisted_source_identity_source_id_roundtrip_not_attested"
    ),
    "source_sha256_roundtrip_attested": (
        "persisted_source_identity_source_sha256_roundtrip_not_attested"
    ),
    "sanitized_identity_response": "persisted_source_identity_response_not_sanitized",
}


@pytest.mark.parametrize(
    ("field_name", "issue_code"),
    tuple(_PERSISTED_SOURCE_IDENTITY_ISSUES.items()),
)
def test_managed_platform_snapshot_requires_exact_persisted_source_identity_attestation(
    field_name: str,
    issue_code: str,
) -> None:
    payload = _valid_platform_capabilities()
    payload["persisted_source_identity"][field_name] = False

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=False)

    assert issues == (issue_code,)
    assert issue_code in MEM0_RUNTIME_CAPABILITY_ISSUE_CODES


def test_managed_platform_snapshot_fails_closed_without_persisted_source_identity() -> None:
    payload = _valid_platform_capabilities()
    del payload["persisted_source_identity"]

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=False)

    assert set(issues) == set(_PERSISTED_SOURCE_IDENTITY_ISSUES.values())


def test_public_manifest_bounds_persisted_source_identity_attestation() -> None:
    payload = _valid_platform_capabilities()
    payload["persisted_source_identity"]["source_id_roundtrip_attested"] = "secret"
    payload["persisted_source_identity"]["credential"] = "secret"

    public = public_mem0_runtime_manifest(payload)

    assert public["persisted_source_identity"] == {
        "request_metadata_required": True,
        "source_filtered_readback_supported": True,
        "source_id_roundtrip_attested": False,
        "source_sha256_roundtrip_attested": True,
        "sanitized_identity_response": True,
    }
    assert "credential" not in str(public)


@pytest.mark.parametrize(
    ("updates", "issue"),
    (
        (
            {"input_epoch_seconds": 1_672_531_201},
            "timestamp_attestation_input_expected_mismatch",
        ),
        (
            {"persisted_created_at": "2023-01-01T00:00:00.500Z", "delta_seconds": 0.0},
            "timestamp_attestation_delta_inconsistent",
        ),
        (
            {"persisted_created_at": "2023-01-01T00:00:02Z", "delta_seconds": 2.0},
            "timestamp_attestation_persisted_delta_out_of_range",
        ),
        (
            {"expected_created_at": "9999-01-01T00:00:00Z"},
            "timestamp_attestation_expected_created_at_invalid",
        ),
    ),
)
def test_timestamp_attestation_rejects_inconsistent_or_impossible_values(
    updates: dict[str, object],
    issue: str,
) -> None:
    payload = deepcopy(_valid_platform_capabilities())
    payload["timestamp"]["attestation"].update(updates)

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)

    assert issue in issues


def test_timestamp_delta_is_non_negative_and_matches_single_readback_absolute_delta() -> None:
    payload = _valid_platform_capabilities()
    attestation = payload["timestamp"]["attestation"]
    attestation.update(
        {
            "persisted_created_at": "2022-12-31T23:59:59.750Z",
            "delta_seconds": 0.25,
        }
    )
    assert evaluate_mem0_runtime_capabilities(payload, require_timestamp=True) == ()

    attestation["delta_seconds"] = -0.25
    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)
    assert "timestamp_attestation_delta_out_of_range" in issues


def test_multi_readback_delta_attests_maximum_and_cannot_be_below_first() -> None:
    payload = _valid_platform_capabilities()
    attestation = payload["timestamp"]["attestation"]
    attestation.update(
        {
            "readback_result_count": 2,
            "persisted_created_at": "2023-01-01T00:00:00.250Z",
            "delta_seconds": 0.5,
        }
    )
    assert evaluate_mem0_runtime_capabilities(payload, require_timestamp=True) == ()

    attestation["delta_seconds"] = 0.1
    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)
    assert "timestamp_attestation_delta_below_first_readback" in issues


def test_public_timestamp_contract_replaces_invalid_allowed_values() -> None:
    payload = _valid_platform_capabilities()
    secret = "timestamp-secret-token"
    payload["timestamp"]["attestation"]["checked_at"] = secret

    public = public_mem0_runtime_manifest(payload)

    assert secret not in str(public)
    assert public["timestamp"]["attestation"]["checked_at"] == "invalid"


def _valid_platform_capabilities() -> dict[str, object]:
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
        "wrapper_source_revision": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": (
                    "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
                ),
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
            "sanitized_identity_response": True,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": "2026-07-29T12:34:56Z",
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1_672_531_200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
    }
