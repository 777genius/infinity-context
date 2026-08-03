from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    build_mem0_runtime_attestation,
    build_verified_mem0_runtime_attestation,
    mem0_live_probe_target_is_safe,
    mem0_runtime_target_identity_sha256,
    public_mem0_runtime_attestation_validation,
    replay_mem0_runtime_attestation,
    validate_mem0_runtime_attestation,
    validate_mem0_runtime_attestation_for_backends,
)

RUN_ID = "managed-full-run-1"
NONCE = "01" * 32
TARGET_URL = "https://mem0.example.test:8443/adapter"
TARGET_SHA = mem0_runtime_target_identity_sha256(TARGET_URL)


def test_same_run_managed_attestation_is_valid_and_sanitized() -> None:
    now = datetime.now(UTC)
    attestation = _attestation(now=now)

    validation = _validate(attestation, now=now)

    assert validation["eligible"] is True
    rendered = json.dumps(validation, sort_keys=True)
    assert RUN_ID not in rendered
    assert NONCE not in rendered
    assert TARGET_URL not in rendered


def test_attestation_binds_and_rejects_valid_shaped_wrapper_profile_drift() -> None:
    now = datetime.now(UTC)
    manifest = _runtime_manifest(now)
    manifest["wrapper_source_sha256"] = "f" * 64
    manifest["wrapper_source_revision"] = "e" * 40
    attestation = build_mem0_runtime_attestation(
        runtime_manifest=manifest,
        openapi_fingerprint_sha256="d" * 64,
        probe_passed=True,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        target_identity_sha256=TARGET_SHA,
        witness_verified=True,
        witness_signature_sha256="e" * 64,
        checked_at=now,
    )

    validation = _validate(attestation, now=now)

    assert validation["eligible"] is False
    assert "runtime_manifest:wrapper_source_sha256_mismatch" in validation["issues"]
    assert "runtime_manifest:wrapper_source_revision_mismatch" in validation["issues"]


@pytest.mark.parametrize(
    ("run_id", "nonce", "target_sha", "issue"),
    (
        ("other-run", NONCE, TARGET_SHA, "runtime_attestation_run_mismatch"),
        (RUN_ID, "b" * 64, TARGET_SHA, "runtime_attestation_probe_nonce_mismatch"),
        (
            RUN_ID,
            NONCE,
            mem0_runtime_target_identity_sha256("https://other.example.test"),
            "runtime_attestation_target_mismatch",
        ),
    ),
)
def test_attestation_rejects_cross_run_old_nonce_and_cross_endpoint(
    run_id: str,
    nonce: str,
    target_sha: str,
    issue: str,
) -> None:
    now = datetime.now(UTC)

    validation = validate_mem0_runtime_attestation(
        _attestation(now=now),
        required_runtime_mode="managed_platform",
        expected_run_id=run_id,
        expected_probe_nonce=nonce,
        expected_target_identity_sha256=target_sha,
        validated_at=now,
    )

    assert validation["eligible"] is False
    assert issue in validation["issues"]


def test_attestation_rejects_stale_outer_and_platform_timestamp() -> None:
    now = datetime.now(UTC)
    validation = _validate(_attestation(now=now - timedelta(seconds=121)), now=now)

    assert validation["eligible"] is False
    assert "runtime_attestation_stale" in validation["issues"]
    assert "timestamp_attestation_stale" in validation["issues"]


@pytest.mark.parametrize(
    "url",
    (
        "mem0.example.test",
        "ftp://mem0.example.test",
        "https://user:secret@mem0.example.test",
        "https://mem0.example.test?token=secret",
        "https://mem0.example.test/#fragment",
        "https://[broken",
    ),
)
def test_target_identity_rejects_ambiguous_or_secret_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError):
        mem0_runtime_target_identity_sha256(url)


def test_target_identity_binds_actual_origin_not_discarded_base_path() -> None:
    assert mem0_runtime_target_identity_sha256("https://mem0.example/a") == (
        mem0_runtime_target_identity_sha256("https://mem0.example/b")
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://192.0.2.1",
        "http://93.184.216.34",
    ),
)
def test_live_probe_target_rejects_non_global_or_non_https_destinations(url: str) -> None:
    assert mem0_live_probe_target_is_safe(url) is False


def test_live_probe_target_requires_vetted_transport_for_hostnames() -> None:
    class _VettedTransport:
        def open_client(self, **_: object):
            raise AssertionError("policy check must not open the transport")

    def private_dns(_host: str) -> tuple[str, ...]:
        return ("10.0.0.7",)

    assert not mem0_live_probe_target_is_safe(
        "https://mem0.example.test",
        allowed_hosts=("mem0.example.test",),
    )
    assert mem0_live_probe_target_is_safe(
        "https://mem0.example.test",
        allowed_hosts=("mem0.example.test",),
        vetted_transport=_VettedTransport(),
    )
    assert not mem0_live_probe_target_is_safe(
        "https://mem0.example.test",
        allowed_hosts=("mem0.example.test",),
        vetted_transport=_VettedTransport(),
        resolver=private_dns,
    )
    assert mem0_live_probe_target_is_safe(
        "http://127.0.0.1:8765",
        allowed_hosts=("127.0.0.1",),
    )


def test_replay_attestation_cannot_upgrade_a_live_claim() -> None:
    replay = replay_mem0_runtime_attestation(_validate(_attestation()))

    assert replay["claim_scope"] == "source_report_only"
    assert replay["live_claim_eligible"] is False


def test_verified_capabilities_are_deeply_immutable() -> None:
    verified = _verified_attestation()
    manifest = verified.payload["runtime_manifest"]
    assert isinstance(verified.payload, MappingProxyType)
    assert isinstance(manifest, MappingProxyType)

    with pytest.raises(TypeError):
        manifest["runtime_mode"] = "oss"  # type: ignore[index]

    validation = _verified_validation()
    attestation = validation["attestation"]
    assert isinstance(attestation, MappingProxyType)
    with pytest.raises(TypeError):
        attestation["probe_status"] = "failed"  # type: ignore[index]


def test_internal_canonical_binding_rejects_tamper_after_normal_fingerprint_recompute() -> None:
    verified = _verified_attestation()
    forged = _thaw(verified.payload)
    assert isinstance(forged, dict)
    manifest = forged["runtime_manifest"]
    assert isinstance(manifest, dict)
    manifest["runtime_mode"] = "oss"
    forged["runtime_manifest_fingerprint_sha256"] = _fingerprint(manifest)
    forged["attestation_fingerprint_sha256"] = _fingerprint(
        {key: value for key, value in forged.items() if key != "attestation_fingerprint_sha256"}
    )
    object.__setattr__(verified, "payload", MappingProxyType(forged))

    validation = validate_mem0_runtime_attestation_for_backends(
        verified,
        (_NoCallBackend("infinity-context"), _NoCallBackend("mem0", target_sha=TARGET_SHA)),
        RUN_ID,
        NONCE,
    )

    assert validation["eligible"] is False
    assert "mem0_runtime_witness_capability_missing" in validation["issues"]


@pytest.mark.parametrize("token", ("", " ", "\t\n"))
def test_verified_builder_rejects_empty_hmac_key(token: str) -> None:
    with pytest.raises(ValueError, match="non-empty HMAC key"):
        build_verified_mem0_runtime_attestation(
            runtime_manifest=_runtime_manifest(datetime.now(UTC)),
            benchmark_probe_token=token,
            openapi_fingerprint_sha256="d" * 64,
            openapi_contract_violations=(),
            probe_passed=True,
            run_id=RUN_ID,
            probe_nonce=NONCE,
            target_identity_sha256=TARGET_SHA,
        )


def test_public_attestation_and_validation_do_not_reflect_arbitrary_allowed_values() -> None:
    secret = "operator-secret-token"
    attestation = build_mem0_runtime_attestation(
        runtime_manifest={"runtime_mode": secret},
        openapi_fingerprint_sha256=secret,
        openapi_contract_violations=(secret,),
        probe_passed=True,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        target_identity_sha256=TARGET_SHA,
        witness_signature_sha256=secret,
    )

    validation = validate_mem0_runtime_attestation(
        attestation,
        required_runtime_mode=secret,
        expected_run_id=RUN_ID,
        expected_probe_nonce=NONCE,
        expected_target_identity_sha256=TARGET_SHA,
    )

    rendered = json.dumps(validation, sort_keys=True)
    assert secret not in rendered
    assert attestation["openapi_contract_violations"] == ["invalid_contract_violation"]
    assert validation["required_runtime_mode"] == "invalid"


def test_public_validation_uses_exact_issue_allowlist_not_prefixes() -> None:
    public = public_mem0_runtime_attestation_validation(
        {
            "issues": [
                "runtime_attestation_secret_token",
                "runtime_manifest:timestamp_secret_token",
                "runtime_attestation_stale",
            ]
        }
    )

    assert public["issues"] == [
        "invalid_validation_issue",
        "invalid_validation_issue",
        "runtime_attestation_stale",
    ]


class _NoCallBackend:
    def __init__(self, name: str, *, target_sha: str | None = None) -> None:
        self.name = name
        self.calls: list[str] = []
        if target_sha is not None:
            self.runtime_target_identity_sha256 = target_sha

    def reset(self, *, run_id: str) -> None:
        self.calls.append("reset")

    def ingest(self, *args: object, **kwargs: object) -> object:
        self.calls.append("ingest")
        raise AssertionError("ingest must not run")

    def search(self, *args: object, **kwargs: object) -> object:
        self.calls.append("search")
        raise AssertionError("search must not run")


def _attestation(*, now: datetime | None = None) -> dict[str, object]:
    checked_at = now or datetime.now(UTC)
    manifest = _runtime_manifest(checked_at)
    return build_mem0_runtime_attestation(
        runtime_manifest=manifest,
        openapi_fingerprint_sha256="d" * 64,
        probe_passed=True,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        target_identity_sha256=TARGET_SHA,
        witness_verified=True,
        witness_signature_sha256="e" * 64,
        checked_at=checked_at,
    )


def _validate(
    attestation: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    return validate_mem0_runtime_attestation(
        attestation,
        required_runtime_mode="managed_platform",
        expected_run_id=RUN_ID,
        expected_probe_nonce=NONCE,
        expected_target_identity_sha256=TARGET_SHA,
        validated_at=now or datetime.now(UTC),
    )


def _runtime_manifest(now: datetime) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
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
                "checked_at": checked_at,
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
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(RUN_ID.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(NONCE.encode()).hexdigest(),
            "target_identity_sha256": TARGET_SHA,
            "refreshed_at": checked_at,
        },
    }


def _verified_attestation(*, now: datetime | None = None) -> object:
    now = now or datetime.now(UTC)
    manifest = _runtime_manifest(now)
    manifest_fingerprint = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            manifest_fingerprint,
        )
    ).encode()
    token = "unit-probe-token"
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": manifest_fingerprint,
        "signature": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
    }
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=manifest,
        benchmark_probe_token=token,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        target_identity_sha256=TARGET_SHA,
    )
    assert verified is not None
    return verified


def _verified_validation() -> object:
    now = datetime.now(UTC)
    verified = _verified_attestation(now=now)
    return validate_mem0_runtime_attestation_for_backends(
        verified,
        (_NoCallBackend("infinity-context"), _NoCallBackend("mem0", target_sha=TARGET_SHA)),
        RUN_ID,
        NONCE,
        validated_at=now,
    )


def _fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_thaw(item) for item in value]
    return value
