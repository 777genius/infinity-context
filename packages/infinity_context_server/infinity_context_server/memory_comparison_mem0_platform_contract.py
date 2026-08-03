"""Pure validation and sanitization for managed Mem0 Platform snapshots."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_SDK_VERSION = "2.0.14"
_SDK_SOURCE_REVISION = "b357a5a1b03c299ec8229c268e63cfac0f7c6566"
_SDK_ARTIFACT_SHA256 = "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
_SDK_VERIFICATION_METHOD = "direct_url_archive_info_sha256"
_MIN_INSTANT = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_INSTANT = datetime(2100, 1, 1, tzinfo=UTC)
_MAX_EPOCH_SECONDS = int(_MAX_INSTANT.timestamp())
_FAILURE_CODES = frozenset(
    {
        "cleanup_failed",
        "event_not_succeeded",
        "missing_mem0_api_key",
        "probe_failed",
        "readback_missing",
        "timestamp_mismatch",
    }
)
_PLATFORM_FIELDS = {
    "api_origin": "https://api.mem0.ai",
    "api_generation": "v3",
    "add_path": "/v3/memories/add/",
    "search_path": "/v3/memories/search/",
    "event_path_template": "/v1/event/{event_id}/",
}
MANAGED_PLATFORM_CAPABILITY_ISSUE_CODES = frozenset(
    {
        "runtime_mode_not_managed_platform",
        "wrapper_source_sha256_invalid",
        "wrapper_source_revision_unpinned",
        "config_fingerprint_sha256_invalid",
        "sdk_distribution_not_mem0ai",
        "sdk_version_mismatch",
        "sdk_source_revision_mismatch",
        "sdk_artifact_sha256_mismatch",
        "sdk_verification_method_invalid",
        "sdk_verification_observed_sha256_invalid",
        "sdk_verification_observed_mismatch",
        "sdk_verification_not_passed",
        "platform_server_revision_claim_inconsistent",
        "platform_server_revision_unpinned",
        "platform_server_revision_attestability_missing",
        "persisted_source_identity_request_metadata_not_required",
        "persisted_source_identity_filtered_readback_not_supported",
        "persisted_source_identity_source_id_roundtrip_not_attested",
        "persisted_source_identity_source_sha256_roundtrip_not_attested",
        "persisted_source_identity_response_not_sanitized",
        "timestamp_live_attestation_not_passed",
        "timestamp_attestation_probe_mode_invalid",
        "timestamp_attestation_checked_at_invalid",
        "timestamp_attestation_input_epoch_invalid",
        "timestamp_attestation_expected_created_at_invalid",
        "timestamp_attestation_event_not_succeeded",
        "timestamp_attestation_readback_missing",
        "timestamp_attestation_persisted_created_at_invalid",
        "timestamp_attestation_delta_out_of_range",
        "timestamp_attestation_delta_inconsistent",
        "timestamp_attestation_delta_below_first_readback",
        "timestamp_attestation_input_expected_mismatch",
        "timestamp_attestation_persisted_delta_out_of_range",
        "timestamp_attestation_cleanup_failed",
        "timestamp_attestation_failure_reported",
        *{f"platform_{field}_mismatch" for field in _PLATFORM_FIELDS},
        *{
            f"timestamp_{field}_not_supported"
            for field in ("request", "sdk_forwarding", "event_completion", "readback")
        },
    }
)


def evaluate_managed_platform_capabilities(
    payload: Mapping[str, object],
    *,
    require_timestamp: bool,
) -> tuple[str, ...]:
    """Validate a bounded managed-Platform snapshot without claiming server reproducibility."""

    issues: list[str] = []
    if payload.get("runtime_mode") != "managed_platform":
        issues.append("runtime_mode_not_managed_platform")
    _require_sha256(payload, "wrapper_source_sha256", issues)
    _require_revision(payload, "wrapper_source_revision", issues)
    _require_sha256(payload, "config_fingerprint_sha256", issues)

    sdk = _mapping(payload.get("sdk"))
    if sdk.get("distribution") != "mem0ai":
        issues.append("sdk_distribution_not_mem0ai")
    if sdk.get("version") != _SDK_VERSION:
        issues.append("sdk_version_mismatch")
    if sdk.get("source_revision") != _SDK_SOURCE_REVISION:
        issues.append("sdk_source_revision_mismatch")
    if sdk.get("artifact_sha256") != _SDK_ARTIFACT_SHA256:
        issues.append("sdk_artifact_sha256_mismatch")
    _validate_sdk_verification(sdk, issues)

    platform = _mapping(payload.get("platform"))
    for field_name, expected in _PLATFORM_FIELDS.items():
        if platform.get(field_name) != expected:
            issues.append(f"platform_{field_name}_mismatch")
    _validate_server_revision(platform, issues)

    _validate_persisted_source_identity(
        _mapping(payload.get("persisted_source_identity")),
        issues,
    )

    timestamp = _mapping(payload.get("timestamp"))
    if require_timestamp:
        for field_name in (
            "request_supported",
            "sdk_forwarding_supported",
            "event_completion_supported",
            "readback_supported",
        ):
            if timestamp.get(field_name) is not True:
                issues.append(f"timestamp_{field_name.removesuffix('_supported')}_not_supported")
        issues.extend(_evaluate_live_timestamp_attestation(timestamp.get("attestation")))
    return tuple(issues)


def public_managed_timestamp_contract(payload: Mapping[str, object]) -> dict[str, object]:
    """Drop correlation identifiers and credentials from timestamp evidence."""

    public = {
        field_name: payload.get(field_name) is True
        for field_name in (
            "request_supported",
            "sdk_forwarding_supported",
            "event_completion_supported",
            "readback_supported",
        )
    }
    attestation = payload.get("attestation")
    if isinstance(attestation, Mapping):
        public["attestation"] = _public_timestamp_attestation(attestation)
    return public


def public_managed_sdk_contract(payload: Mapping[str, object]) -> dict[str, object]:
    """Project only exact pinned SDK provenance values."""

    verification = _mapping(payload.get("verification"))
    return {
        "distribution": _exact_public_text(payload.get("distribution"), "mem0ai"),
        "version": _exact_public_text(payload.get("version"), _SDK_VERSION),
        "source_revision": _public_digest(payload.get("source_revision"), _REVISION_RE),
        "artifact_sha256": _public_digest(payload.get("artifact_sha256"), _SHA256_RE),
        "verification": {
            "method": _exact_public_text(
                verification.get("method"),
                _SDK_VERIFICATION_METHOD,
            ),
            "observed_sha256": _public_digest(
                verification.get("observed_sha256"),
                _SHA256_RE,
            ),
            "passed": verification.get("passed") is True,
        },
    }


def public_managed_platform_contract(payload: Mapping[str, object]) -> dict[str, object]:
    """Project exact endpoint provenance without reflecting arbitrary strings."""

    public = {
        field_name: _exact_public_text(payload.get(field_name), expected)
        for field_name, expected in _PLATFORM_FIELDS.items()
    }
    attestable = payload.get("server_revision_attestable")
    public["server_revision_attestable"] = attestable if isinstance(attestable, bool) else "invalid"
    revision = payload.get("server_source_revision")
    public["server_source_revision"] = (
        None if revision is None else _public_digest(revision, _REVISION_RE)
    )
    return public


def public_managed_persisted_source_identity_contract(
    payload: Mapping[str, object],
) -> dict[str, bool]:
    """Project only bounded persisted-source capability attestations."""

    return {
        field_name: payload.get(field_name) is True
        for field_name in (
            "request_metadata_required",
            "source_filtered_readback_supported",
            "source_id_roundtrip_attested",
            "source_sha256_roundtrip_attested",
            "sanitized_identity_response",
        )
    }


def public_managed_refresh_binding(payload: Mapping[str, object]) -> dict[str, object]:
    """Project same-run binding fields through strict bounded validators."""

    return {
        "status": _exact_public_text(payload.get("status"), "passed"),
        "run_id_sha256": _public_digest(payload.get("run_id_sha256"), _SHA256_RE),
        "probe_nonce_sha256": _public_digest(
            payload.get("probe_nonce_sha256"),
            _SHA256_RE,
        ),
        "target_identity_sha256": _public_digest(
            payload.get("target_identity_sha256"),
            _SHA256_RE,
        ),
        "refreshed_at": _public_instant(payload.get("refreshed_at")),
    }


def _validate_sdk_verification(
    sdk: Mapping[str, object],
    issues: list[str],
) -> None:
    verification = _mapping(sdk.get("verification"))
    if verification.get("method") != _SDK_VERIFICATION_METHOD:
        issues.append("sdk_verification_method_invalid")
    observed = verification.get("observed_sha256")
    if not _SHA256_RE.fullmatch(str(observed or "")):
        issues.append("sdk_verification_observed_sha256_invalid")
    elif observed != sdk.get("artifact_sha256"):
        issues.append("sdk_verification_observed_mismatch")
    if verification.get("passed") is not True:
        issues.append("sdk_verification_not_passed")


def _evaluate_live_timestamp_attestation(payload: object) -> tuple[str, ...]:
    attestation = _mapping(payload)
    issues: list[str] = []
    if attestation.get("status") != "passed":
        issues.append("timestamp_live_attestation_not_passed")
    if attestation.get("probe_mode") != "live_sentinel":
        issues.append("timestamp_attestation_probe_mode_invalid")
    if _parse_utc_instant(attestation.get("checked_at")) is None:
        issues.append("timestamp_attestation_checked_at_invalid")
    input_epoch = _bounded_epoch_seconds(attestation.get("input_epoch_seconds"))
    if input_epoch is None:
        issues.append("timestamp_attestation_input_epoch_invalid")
    expected = _parse_utc_instant(attestation.get("expected_created_at"))
    if expected is None:
        issues.append("timestamp_attestation_expected_created_at_invalid")
    if attestation.get("event_terminal_status") != "SUCCEEDED":
        issues.append("timestamp_attestation_event_not_succeeded")
    readback_count = _positive_int(attestation.get("readback_result_count"))
    if readback_count is None:
        issues.append("timestamp_attestation_readback_missing")
    persisted = _parse_utc_instant(attestation.get("persisted_created_at"))
    if persisted is None:
        issues.append("timestamp_attestation_persisted_created_at_invalid")
    delta_seconds = _finite_number(attestation.get("delta_seconds"))
    if delta_seconds is None or delta_seconds < 0 or delta_seconds > 1.0:
        issues.append("timestamp_attestation_delta_out_of_range")
    if input_epoch is not None and expected is not None:
        epoch_expected = datetime.fromtimestamp(input_epoch, tz=UTC)
        if abs((expected - epoch_expected).total_seconds()) > 0.001:
            issues.append("timestamp_attestation_input_expected_mismatch")
    if expected is not None and persisted is not None and delta_seconds is not None:
        first_readback_delta = abs((persisted - expected).total_seconds())
        if readback_count == 1 and abs(first_readback_delta - delta_seconds) > 0.001:
            issues.append("timestamp_attestation_delta_inconsistent")
        if (
            readback_count is not None
            and readback_count > 1
            and delta_seconds + 0.001 < first_readback_delta
        ):
            # The signed adapter reports the maximum absolute delta across all
            # readbacks; persisted_created_at is the first readback evidence.
            issues.append("timestamp_attestation_delta_below_first_readback")
        if first_readback_delta > 1.0:
            issues.append("timestamp_attestation_persisted_delta_out_of_range")
    if attestation.get("cleanup_succeeded") is not True:
        issues.append("timestamp_attestation_cleanup_failed")
    if attestation.get("failure_code") not in (None, ""):
        issues.append("timestamp_attestation_failure_reported")
    return tuple(issues)


def _validate_server_revision(
    platform: Mapping[str, object],
    issues: list[str],
) -> None:
    attestable = platform.get("server_revision_attestable")
    revision = platform.get("server_source_revision")
    if attestable is False:
        if revision is not None:
            issues.append("platform_server_revision_claim_inconsistent")
        return
    if attestable is True:
        if not _REVISION_RE.fullmatch(str(revision or "")):
            issues.append("platform_server_revision_unpinned")
        return
    issues.append("platform_server_revision_attestability_missing")


def _validate_persisted_source_identity(
    payload: Mapping[str, object],
    issues: list[str],
) -> None:
    expected_fields = {
        "request_metadata_required": "persisted_source_identity_request_metadata_not_required",
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
    for field_name, issue_code in expected_fields.items():
        if payload.get(field_name) is not True:
            issues.append(issue_code)


def _require_sha256(
    payload: Mapping[str, object],
    field_name: str,
    issues: list[str],
    *,
    prefix: str = "",
) -> None:
    if not _SHA256_RE.fullmatch(str(payload.get(field_name) or "")):
        issues.append(f"{prefix}{field_name}_invalid")


def _require_revision(
    payload: Mapping[str, object],
    field_name: str,
    issues: list[str],
    *,
    prefix: str = "",
) -> None:
    if not _REVISION_RE.fullmatch(str(payload.get(field_name) or "")):
        issues.append(f"{prefix}{field_name}_unpinned")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _bounded_epoch_seconds(value: object) -> int | None:
    result = _non_negative_int(value)
    return result if result is not None and result <= _MAX_EPOCH_SECONDS else None


def _positive_int(value: object) -> int | None:
    result = _non_negative_int(value)
    return result if result is not None and result > 0 else None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if isfinite(result) else None


def _parse_utc_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00").astimezone(UTC)
    except ValueError:
        return None
    return parsed if _MIN_INSTANT <= parsed <= _MAX_INSTANT else None


def _public_timestamp_attestation(payload: Mapping[str, object]) -> dict[str, object]:
    failure_code = payload.get("failure_code")
    return {
        "status": _exact_public_text(payload.get("status"), "passed"),
        "checked_at": _public_instant(payload.get("checked_at")),
        "probe_mode": _exact_public_text(payload.get("probe_mode"), "live_sentinel"),
        "input_epoch_seconds": _public_epoch(payload.get("input_epoch_seconds")),
        "expected_created_at": _public_instant(payload.get("expected_created_at")),
        "event_terminal_status": _exact_public_text(
            payload.get("event_terminal_status"),
            "SUCCEEDED",
        ),
        "readback_result_count": _public_positive_int(payload.get("readback_result_count")),
        "persisted_created_at": _public_instant(payload.get("persisted_created_at")),
        "delta_seconds": _public_finite_number(payload.get("delta_seconds")),
        "cleanup_succeeded": payload.get("cleanup_succeeded") is True,
        "failure_code": (
            None
            if failure_code in (None, "")
            else failure_code
            if failure_code in _FAILURE_CODES
            else "invalid"
        ),
    }


def _exact_public_text(value: object, expected: str) -> str:
    return expected if value == expected else "invalid"


def _public_digest(value: object, pattern: re.Pattern[str]) -> str:
    return value if isinstance(value, str) and pattern.fullmatch(value) else "invalid"


def _public_instant(value: object) -> str:
    return value if isinstance(value, str) and _parse_utc_instant(value) is not None else "invalid"


def _public_epoch(value: object) -> int | str:
    result = _bounded_epoch_seconds(value)
    return result if result is not None else "invalid"


def _public_positive_int(value: object) -> int | str:
    result = _positive_int(value)
    return result if result is not None and result <= 1_000_000 else "invalid"


def _public_finite_number(value: object) -> float | str:
    result = _finite_number(value)
    return result if result is not None and abs(result) <= 86_400 else "invalid"


__all__ = (
    "MANAGED_PLATFORM_CAPABILITY_ISSUE_CODES",
    "evaluate_managed_platform_capabilities",
    "public_managed_platform_contract",
    "public_managed_persisted_source_identity_contract",
    "public_managed_refresh_binding",
    "public_managed_sdk_contract",
    "public_managed_timestamp_contract",
)
