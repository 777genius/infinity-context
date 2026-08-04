"""Pure same-run identity binding for managed Mem0 benchmark runtimes."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType

from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_RUNTIME_CAPABILITY_ISSUE_CODES,
    PUBLIC_MEM0_OPENAPI_VIOLATIONS,
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_probe_transport import (
    mem0_live_probe_target_is_safe,
    mem0_runtime_target_identity_sha256,
)

MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION = "memory-comparison-mem0-runtime-attestation.v1"
MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION = (
    "memory-comparison-mem0-runtime-attestation-validation.v1"
)
MEM0_OSS_RUNTIME_MODE = "oss"
MEM0_MANAGED_PLATFORM_RUNTIME_MODE = "managed_platform"
MEM0_RUNTIME_ATTESTATION_MAX_AGE_SECONDS = 120
_FUTURE_TOLERANCE_SECONDS = 5
_MAX_ISSUES = 32
_MAX_CANONICAL_DEPTH = 8
_MAX_CANONICAL_ITEMS = 4_096
_MAX_CANONICAL_KEY_CHARS = 128
_MAX_CANONICAL_TEXT_CHARS = 16_384
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_VALIDATION_ISSUES = frozenset(
    {
        "required_runtime_mode_invalid",
        "runtime_attestation_max_age_invalid",
        "runtime_attestation_missing",
        "runtime_attestation_schema_version_mismatch",
        "runtime_probe_not_passed",
        "runtime_witness_not_verified",
        "runtime_witness_signature_fingerprint_invalid",
        "runtime_mode_mismatch",
        "runtime_manifest_mode_mismatch",
        "expected_run_id_invalid",
        "runtime_attestation_run_id_invalid",
        "runtime_attestation_run_mismatch",
        "expected_probe_nonce_invalid",
        "runtime_attestation_probe_nonce_invalid",
        "runtime_attestation_probe_nonce_mismatch",
        "expected_target_identity_invalid",
        "runtime_attestation_target_invalid",
        "runtime_attestation_target_mismatch",
        "runtime_refresh_run_binding_mismatch",
        "runtime_refresh_nonce_binding_mismatch",
        "runtime_refresh_not_passed",
        "runtime_refresh_target_binding_mismatch",
        "runtime_refresh_checked_at_invalid",
        "runtime_refresh_stale",
        "runtime_refresh_from_future",
        "openapi_fingerprint_invalid",
        "openapi_contract_violations_invalid",
        "openapi_contract_invalid",
        "runtime_manifest_fingerprint_invalid",
        "runtime_manifest_fingerprint_mismatch",
        "runtime_attestation_fingerprint_invalid",
        "runtime_attestation_fingerprint_mismatch",
        "runtime_attestation_checked_at_invalid",
        "runtime_attestation_stale",
        "runtime_attestation_from_future",
        "timestamp_attestation_checked_at_invalid",
        "timestamp_attestation_stale",
        "timestamp_attestation_from_future",
        "mem0_backend_identity_count_invalid",
        "mem0_backend_target_identity_missing",
        "mem0_runtime_witness_capability_missing",
    }
)
_PUBLIC_FIELDS = (
    "schema_version",
    "checked_at",
    "runtime_mode",
    "probe_status",
    "run_id_sha256",
    "probe_nonce_sha256",
    "target_identity_sha256",
    "openapi_fingerprint_sha256",
    "openapi_contract_violations",
    "runtime_manifest_fingerprint_sha256",
    "runtime_manifest",
    "attestation_fingerprint_sha256",
    "witness_verified",
    "witness_signature_sha256",
)
_VERIFIED_MARKER = object()


@dataclass(frozen=True)
class VerifiedMem0RuntimeAttestation:
    """Nominal capability accepted by the runner after HMAC verification."""

    payload: Mapping[str, object]
    _payload_fingerprint_sha256: str
    _witness_binding_fingerprint_sha256: str
    _witness_signature_sha256: str
    _marker: object

    def __post_init__(self) -> None:
        if (
            self._marker is not _VERIFIED_MARKER
            or not isinstance(self.payload, MappingProxyType)
            or not _SHA256_RE.fullmatch(self._payload_fingerprint_sha256)
            or not _SHA256_RE.fullmatch(self._witness_binding_fingerprint_sha256)
            or not _SHA256_RE.fullmatch(self._witness_signature_sha256)
        ):
            raise ValueError("runtime attestation witness was not verified")


@dataclass(frozen=True)
class VerifiedMem0RuntimeAttestationValidation(Mapping[str, object]):
    """Runner-produced validation capability consumed by publication contracts."""

    payload: Mapping[str, object]
    _payload_fingerprint_sha256: str
    _marker: object

    def __post_init__(self) -> None:
        if (
            self._marker is not _VERIFIED_MARKER
            or not isinstance(self.payload, MappingProxyType)
            or _fingerprint(self.payload) != self._payload_fingerprint_sha256
        ):
            raise ValueError("runtime attestation validation was not runner-produced")

    def __getitem__(self, key: str) -> object:
        return self.payload[key]

    def __iter__(self):
        return iter(self.payload)

    def __len__(self) -> int:
        return len(self.payload)


def build_mem0_runtime_attestation(
    *,
    runtime_manifest: object,
    openapi_fingerprint_sha256: object,
    openapi_contract_violations: Sequence[object] = (),
    probe_passed: bool,
    run_id: str,
    probe_nonce: str,
    target_identity_sha256: str,
    witness_verified: bool = False,
    witness_signature_sha256: str = "",
    checked_at: datetime | None = None,
) -> dict[str, object]:
    """Bind one sanitized probe snapshot without retaining endpoint or credentials."""

    if not run_id.strip():
        raise ValueError("run_id is required for runtime attestation")
    if not probe_nonce.strip():
        raise ValueError("probe_nonce is required for runtime attestation")
    if not _SHA256_RE.fullmatch(target_identity_sha256):
        raise ValueError("target_identity_sha256 must be a SHA-256 digest")

    public_manifest = public_mem0_runtime_manifest(runtime_manifest)
    violations = [
        _safe_contract_violation(item) for item in openapi_contract_violations[:_MAX_ISSUES]
    ]
    body: dict[str, object] = {
        "schema_version": MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION,
        "checked_at": _instant_text(checked_at or datetime.now(UTC)),
        "runtime_mode": str(public_manifest.get("runtime_mode") or "missing"),
        "probe_status": "passed" if probe_passed else "failed",
        "run_id_sha256": _sha256_text(run_id),
        "probe_nonce_sha256": _sha256_text(probe_nonce),
        "target_identity_sha256": target_identity_sha256,
        "openapi_fingerprint_sha256": _public_hash(openapi_fingerprint_sha256),
        "openapi_contract_violations": violations,
        "runtime_manifest_fingerprint_sha256": _fingerprint(public_manifest),
        "runtime_manifest": public_manifest,
        "witness_verified": witness_verified is True,
        "witness_signature_sha256": _public_hash(witness_signature_sha256),
    }
    return {
        **body,
        "attestation_fingerprint_sha256": _fingerprint(body),
    }


def validate_mem0_runtime_attestation(
    payload: object,
    *,
    required_runtime_mode: str,
    expected_run_id: str,
    expected_probe_nonce: str,
    expected_target_identity_sha256: str,
    validated_at: datetime | None = None,
    max_age_seconds: int = MEM0_RUNTIME_ATTESTATION_MAX_AGE_SECONDS,
) -> dict[str, object]:
    """Return a bounded fail-closed verdict suitable for reports and contracts."""

    now = validated_at or datetime.now(UTC)
    public = public_mem0_runtime_attestation(payload)
    issues: list[str] = []
    public_required_mode = _public_runtime_mode(required_runtime_mode)
    if public_required_mode == "invalid":
        issues.append("required_runtime_mode_invalid")
    effective_max_age = _bounded_max_age(max_age_seconds)
    if effective_max_age is None:
        issues.append("runtime_attestation_max_age_invalid")
        effective_max_age = MEM0_RUNTIME_ATTESTATION_MAX_AGE_SECONDS
    if not isinstance(payload, Mapping):
        issues.append("runtime_attestation_missing")
    if public.get("schema_version") != MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION:
        issues.append("runtime_attestation_schema_version_mismatch")
    if public.get("probe_status") != "passed":
        issues.append("runtime_probe_not_passed")
    if public.get("witness_verified") is not True:
        issues.append("runtime_witness_not_verified")
    if not _SHA256_RE.fullmatch(str(public.get("witness_signature_sha256") or "")):
        issues.append("runtime_witness_signature_fingerprint_invalid")

    observed_mode = str(public.get("runtime_mode") or "missing")
    if observed_mode != required_runtime_mode:
        issues.append("runtime_mode_mismatch")
    manifest = _mapping(public.get("runtime_manifest"))
    if manifest.get("runtime_mode") != required_runtime_mode:
        issues.append("runtime_manifest_mode_mismatch")

    run_id_sha256 = str(public.get("run_id_sha256") or "")
    probe_nonce_sha256 = str(public.get("probe_nonce_sha256") or "")
    target_identity_sha256 = str(public.get("target_identity_sha256") or "")
    if not expected_run_id.strip():
        issues.append("expected_run_id_invalid")
    if not _SHA256_RE.fullmatch(run_id_sha256):
        issues.append("runtime_attestation_run_id_invalid")
    elif run_id_sha256 != _sha256_text(expected_run_id):
        issues.append("runtime_attestation_run_mismatch")
    if not expected_probe_nonce.strip():
        issues.append("expected_probe_nonce_invalid")
    if not _SHA256_RE.fullmatch(probe_nonce_sha256):
        issues.append("runtime_attestation_probe_nonce_invalid")
    elif probe_nonce_sha256 != _sha256_text(expected_probe_nonce):
        issues.append("runtime_attestation_probe_nonce_mismatch")
    if not _SHA256_RE.fullmatch(expected_target_identity_sha256):
        issues.append("expected_target_identity_invalid")
    if not _SHA256_RE.fullmatch(target_identity_sha256):
        issues.append("runtime_attestation_target_invalid")
    elif target_identity_sha256 != expected_target_identity_sha256:
        issues.append("runtime_attestation_target_mismatch")
    refresh_binding = _mapping(manifest.get("refresh_binding"))
    if refresh_binding.get("run_id_sha256") != run_id_sha256:
        issues.append("runtime_refresh_run_binding_mismatch")
    if refresh_binding.get("probe_nonce_sha256") != probe_nonce_sha256:
        issues.append("runtime_refresh_nonce_binding_mismatch")
    if refresh_binding.get("status") != "passed":
        issues.append("runtime_refresh_not_passed")
    if refresh_binding.get("target_identity_sha256") != target_identity_sha256:
        issues.append("runtime_refresh_target_binding_mismatch")
    refresh_checked_at = _parse_instant(refresh_binding.get("refreshed_at"))
    refresh_age_seconds = _age_seconds(refresh_checked_at, now)
    _append_freshness_issues(
        issues,
        age_seconds=refresh_age_seconds,
        invalid_code="runtime_refresh_checked_at_invalid",
        stale_code="runtime_refresh_stale",
        future_code="runtime_refresh_from_future",
        max_age_seconds=effective_max_age,
    )

    openapi_fingerprint = str(public.get("openapi_fingerprint_sha256") or "")
    if not _SHA256_RE.fullmatch(openapi_fingerprint):
        issues.append("openapi_fingerprint_invalid")
    violations = public.get("openapi_contract_violations")
    if not isinstance(violations, Sequence) or isinstance(violations, str | bytes):
        issues.append("openapi_contract_violations_invalid")
    elif violations:
        issues.append("openapi_contract_invalid")

    manifest_fingerprint = str(public.get("runtime_manifest_fingerprint_sha256") or "")
    if not _SHA256_RE.fullmatch(manifest_fingerprint):
        issues.append("runtime_manifest_fingerprint_invalid")
    elif manifest_fingerprint != _fingerprint(manifest):
        issues.append("runtime_manifest_fingerprint_mismatch")

    attestation_fingerprint = str(public.get("attestation_fingerprint_sha256") or "")
    fingerprint_body = {
        key: public[key]
        for key in _PUBLIC_FIELDS
        if key != "attestation_fingerprint_sha256" and key in public
    }
    if not _SHA256_RE.fullmatch(attestation_fingerprint):
        issues.append("runtime_attestation_fingerprint_invalid")
    elif attestation_fingerprint != _fingerprint(fingerprint_body):
        issues.append("runtime_attestation_fingerprint_mismatch")

    checked_at = _parse_instant(public.get("checked_at"))
    age_seconds = _age_seconds(checked_at, now)
    _append_freshness_issues(
        issues,
        age_seconds=age_seconds,
        invalid_code="runtime_attestation_checked_at_invalid",
        stale_code="runtime_attestation_stale",
        future_code="runtime_attestation_from_future",
        max_age_seconds=effective_max_age,
    )

    manifest_issues = evaluate_mem0_runtime_capabilities(
        manifest,
        require_timestamp=True,
    )
    issues.extend(f"runtime_manifest:{issue}" for issue in manifest_issues)
    timestamp_attestation = _mapping(_mapping(manifest.get("timestamp")).get("attestation"))
    timestamp_checked_at = _parse_instant(timestamp_attestation.get("checked_at"))
    timestamp_age_seconds = _age_seconds(timestamp_checked_at, now)
    _append_freshness_issues(
        issues,
        age_seconds=timestamp_age_seconds,
        invalid_code="timestamp_attestation_checked_at_invalid",
        stale_code="timestamp_attestation_stale",
        future_code="timestamp_attestation_from_future",
        max_age_seconds=effective_max_age,
    )

    bounded_issues = list(dict.fromkeys(issues))[:_MAX_ISSUES]
    eligible = not bounded_issues
    return {
        "schema_version": MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION,
        "status": "valid" if eligible else "invalid",
        "eligible": eligible,
        "required_runtime_mode": public_required_mode,
        "observed_runtime_mode": observed_mode,
        "validated_at": _instant_text(now),
        "max_age_seconds": effective_max_age,
        "age_seconds": age_seconds,
        "timestamp_attestation_age_seconds": timestamp_age_seconds,
        "refresh_age_seconds": refresh_age_seconds,
        "issues": bounded_issues,
        "attestation": public,
    }


def validate_mem0_runtime_attestation_for_backends(
    payload: object,
    backends: Sequence[object],
    expected_run_id: str,
    expected_probe_nonce: str,
    *,
    required_runtime_mode: str = MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
    validated_at: datetime | None = None,
) -> dict[str, object] | VerifiedMem0RuntimeAttestationValidation:
    """Bind a full-run attestation to the concrete Mem0 adapter target."""

    candidates = [backend for backend in backends if str(getattr(backend, "name", "")) == "mem0"]
    target_identity = (
        str(getattr(candidates[0], "runtime_target_identity_sha256", ""))
        if len(candidates) == 1
        else ""
    )
    verified_payload = _verified_payload(payload)
    validation = validate_mem0_runtime_attestation(
        verified_payload,
        required_runtime_mode=required_runtime_mode,
        expected_run_id=expected_run_id,
        expected_probe_nonce=expected_probe_nonce,
        expected_target_identity_sha256=target_identity,
        validated_at=validated_at,
    )
    extra_issues: list[str] = []
    if len(candidates) != 1:
        extra_issues.append("mem0_backend_identity_count_invalid")
    elif not _SHA256_RE.fullmatch(target_identity):
        extra_issues.append("mem0_backend_target_identity_missing")
    if verified_payload is None:
        extra_issues.append("mem0_runtime_witness_capability_missing")
    if not extra_issues:
        frozen_validation = _deep_freeze(
            validation,
            remaining=[_MAX_CANONICAL_ITEMS],
        )
        assert isinstance(frozen_validation, MappingProxyType)
        return VerifiedMem0RuntimeAttestationValidation(
            payload=frozen_validation,
            _payload_fingerprint_sha256=_fingerprint(frozen_validation),
            _marker=_VERIFIED_MARKER,
        )
    issues = list(dict.fromkeys([*extra_issues, *_sequence(validation.get("issues"))]))[
        :_MAX_ISSUES
    ]
    invalid = {**validation, "status": "invalid", "eligible": False, "issues": issues}
    if verified_payload is not None:
        frozen_invalid = _deep_freeze(invalid, remaining=[_MAX_CANONICAL_ITEMS])
        assert isinstance(frozen_invalid, MappingProxyType)
        return VerifiedMem0RuntimeAttestationValidation(
            payload=frozen_invalid,
            _payload_fingerprint_sha256=_fingerprint(frozen_invalid),
            _marker=_VERIFIED_MARKER,
        )
    return invalid


def public_mem0_runtime_attestation(payload: object) -> dict[str, object]:
    """Project only bounded attestation fields and re-sanitize the manifest."""

    if not isinstance(payload, Mapping):
        return {}
    public: dict[str, object] = {
        "schema_version": (
            MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION
            if payload.get("schema_version") == MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION
            else "invalid"
        ),
        "checked_at": _public_instant(payload.get("checked_at")),
        "runtime_mode": _public_runtime_mode(payload.get("runtime_mode")),
        "probe_status": (
            payload.get("probe_status")
            if payload.get("probe_status") in {"passed", "failed"}
            else "invalid"
        ),
        "witness_verified": payload.get("witness_verified") is True,
    }
    for key in (
        "run_id_sha256",
        "probe_nonce_sha256",
        "target_identity_sha256",
        "openapi_fingerprint_sha256",
        "runtime_manifest_fingerprint_sha256",
        "attestation_fingerprint_sha256",
        "witness_signature_sha256",
    ):
        public[key] = _public_hash(payload.get(key))
    public["runtime_manifest"] = public_mem0_runtime_manifest(payload.get("runtime_manifest"))
    violations = payload.get("openapi_contract_violations")
    public["openapi_contract_violations"] = (
        [_safe_contract_violation(item) for item in violations[:_MAX_ISSUES]]
        if isinstance(violations, Sequence) and not isinstance(violations, str | bytes)
        else []
    )
    return public


def public_mem0_runtime_attestation_validation(payload: object) -> dict[str, object]:
    """Project a bounded validation verdict for reports and publication gates."""

    if not isinstance(payload, Mapping):
        return {}
    public = {
        "schema_version": (
            MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION
            if payload.get("schema_version") == MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION
            else "invalid"
        ),
        "status": (
            payload.get("status") if payload.get("status") in {"valid", "invalid"} else "invalid"
        ),
        "eligible": payload.get("eligible") is True,
        "required_runtime_mode": _public_runtime_mode(payload.get("required_runtime_mode")),
        "observed_runtime_mode": _public_runtime_mode(payload.get("observed_runtime_mode")),
        "validated_at": _public_instant(payload.get("validated_at")),
        "max_age_seconds": _public_positive_int(payload.get("max_age_seconds"), maximum=3_600),
        "age_seconds": _public_age(payload.get("age_seconds")),
        "timestamp_attestation_age_seconds": _public_age(
            payload.get("timestamp_attestation_age_seconds")
        ),
        "refresh_age_seconds": _public_age(payload.get("refresh_age_seconds")),
    }
    public["issues"] = [
        _safe_validation_issue(item) for item in _sequence(payload.get("issues"))[:_MAX_ISSUES]
    ]
    public["attestation"] = public_mem0_runtime_attestation(payload.get("attestation"))
    return public


def mem0_runtime_attestation_validation_is_publishable(
    payload: object,
    *,
    required_runtime_mode: str,
) -> bool:
    """Require a complete internally consistent public proof envelope."""

    public = public_mem0_runtime_attestation_validation(payload)
    attestation = _mapping(public.get("attestation"))
    manifest = _mapping(attestation.get("runtime_manifest"))
    refresh = _mapping(manifest.get("refresh_binding"))
    issues = public.get("issues")
    fingerprint_body = {
        key: attestation[key]
        for key in _PUBLIC_FIELDS
        if key != "attestation_fingerprint_sha256" and key in attestation
    }
    return bool(
        public.get("schema_version") == MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION
        and public.get("status") == "valid"
        and public.get("eligible") is True
        and public.get("required_runtime_mode") == required_runtime_mode
        and public.get("observed_runtime_mode") == required_runtime_mode
        and isinstance(issues, list)
        and not issues
        and attestation.get("schema_version") == MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION
        and attestation.get("probe_status") == "passed"
        and attestation.get("runtime_mode") == required_runtime_mode
        and attestation.get("witness_verified") is True
        and all(
            _SHA256_RE.fullmatch(str(attestation.get(key) or ""))
            for key in (
                "run_id_sha256",
                "probe_nonce_sha256",
                "target_identity_sha256",
                "openapi_fingerprint_sha256",
                "runtime_manifest_fingerprint_sha256",
                "attestation_fingerprint_sha256",
                "witness_signature_sha256",
            )
        )
        and attestation.get("openapi_contract_violations") == []
        and manifest.get("runtime_mode") == required_runtime_mode
        and not evaluate_mem0_runtime_capabilities(manifest, require_timestamp=True)
        and refresh.get("status") == "passed"
        and refresh.get("run_id_sha256") == attestation.get("run_id_sha256")
        and refresh.get("probe_nonce_sha256") == attestation.get("probe_nonce_sha256")
        and refresh.get("target_identity_sha256") == attestation.get("target_identity_sha256")
        and attestation.get("runtime_manifest_fingerprint_sha256") == _fingerprint(manifest)
        and attestation.get("attestation_fingerprint_sha256") == _fingerprint(fingerprint_body)
    )


def build_verified_mem0_runtime_attestation(
    *,
    runtime_manifest: Mapping[str, object],
    benchmark_probe_token: str,
    openapi_fingerprint_sha256: object,
    openapi_contract_violations: Sequence[object],
    probe_passed: bool,
    run_id: str,
    probe_nonce: str,
    target_identity_sha256: str,
) -> VerifiedMem0RuntimeAttestation | None:
    """Verify the adapter HMAC witness before creating runner capability."""

    _require_hmac_key(benchmark_probe_token)
    canonical_manifest = _deep_thaw(
        _deep_freeze(runtime_manifest, remaining=[_MAX_CANONICAL_ITEMS])
    )
    assert isinstance(canonical_manifest, dict)
    witness = _mapping(canonical_manifest.get("refresh_witness"))
    unsigned_manifest = dict(canonical_manifest)
    unsigned_manifest.pop("refresh_witness", None)
    manifest_fingerprint = _fingerprint(unsigned_manifest)
    binding = _mapping(unsigned_manifest.get("refresh_binding"))
    signature = str(witness.get("signature") or "")
    expected_signature = _refresh_witness_signature(
        benchmark_probe_token,
        binding,
        manifest_fingerprint,
    )
    witness_valid = (
        witness.get("algorithm") == "hmac-sha256"
        and witness.get("manifest_fingerprint_sha256") == manifest_fingerprint
        and _SHA256_RE.fullmatch(signature) is not None
        and hmac.compare_digest(signature, expected_signature)
        and binding.get("run_id_sha256") == _sha256_text(run_id)
        and binding.get("probe_nonce_sha256") == _sha256_text(probe_nonce)
        and binding.get("target_identity_sha256") == target_identity_sha256
    )
    if not witness_valid:
        return None
    payload = build_mem0_runtime_attestation(
        runtime_manifest=unsigned_manifest,
        openapi_fingerprint_sha256=openapi_fingerprint_sha256,
        openapi_contract_violations=openapi_contract_violations,
        probe_passed=probe_passed,
        run_id=run_id,
        probe_nonce=probe_nonce,
        target_identity_sha256=target_identity_sha256,
        witness_verified=True,
        witness_signature_sha256=_sha256_text(signature),
    )
    frozen_payload = _deep_freeze(payload, remaining=[_MAX_CANONICAL_ITEMS])
    assert isinstance(frozen_payload, MappingProxyType)
    witness_signature_sha256 = _sha256_text(signature)
    return VerifiedMem0RuntimeAttestation(
        payload=frozen_payload,
        _payload_fingerprint_sha256=_fingerprint(frozen_payload),
        _witness_binding_fingerprint_sha256=_verified_binding_fingerprint(frozen_payload),
        _witness_signature_sha256=witness_signature_sha256,
        _marker=_VERIFIED_MARKER,
    )


def mem0_runtime_attestation_blocker(
    validation: Mapping[str, object],
) -> dict[str, object]:
    """Translate a validation verdict into one bounded application blocker."""

    public = public_mem0_runtime_attestation_validation(validation)
    return {
        "code": "mem0_runtime_attestation_invalid",
        "required_runtime_mode": public.get("required_runtime_mode"),
        "observed_runtime_mode": public.get("observed_runtime_mode"),
        "status": public.get("status"),
        "issues": list(_sequence(public.get("issues")))[:_MAX_ISSUES],
        "attestation_fingerprint_sha256": _mapping(public.get("attestation")).get(
            "attestation_fingerprint_sha256"
        ),
    }


def replay_mem0_runtime_attestation(payload: object) -> dict[str, object]:
    """Preserve source evidence while making live-claim non-upgrade explicit."""

    source = _mapping(payload)
    attestation = public_mem0_runtime_attestation(source.get("attestation"))
    return {
        "schema_version": "memory-comparison-mem0-runtime-attestation-replay.v1",
        "claim_scope": "source_report_only",
        "live_claim_eligible": False,
        "source_status": (
            source.get("status") if source.get("status") in {"valid", "invalid"} else "invalid"
        ),
        "source_eligible": source.get("eligible") is True,
        "attestation": attestation,
    }


def _append_freshness_issues(
    issues: list[str],
    *,
    age_seconds: float | None,
    invalid_code: str,
    stale_code: str,
    future_code: str,
    max_age_seconds: int,
) -> None:
    if age_seconds is None:
        issues.append(invalid_code)
    elif age_seconds > max_age_seconds:
        issues.append(stale_code)
    elif age_seconds < -_FUTURE_TOLERANCE_SECONDS:
        issues.append(future_code)


def _age_seconds(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    normalized_now = now.astimezone(UTC)
    return round((normalized_now - value).total_seconds(), 3)


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return None
    normalized = parsed.astimezone(UTC)
    return normalized if 1970 <= normalized.year <= 2100 else None


def _instant_text(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _public_instant(value: object) -> str:
    return value if isinstance(value, str) and _parse_instant(value) is not None else "invalid"


def _public_runtime_mode(value: object) -> str:
    return value if value in {"managed_platform", "oss"} else "invalid"


def _public_hash(value: object) -> str:
    return value if isinstance(value, str) and _SHA256_RE.fullmatch(value) else "invalid"


def _public_positive_int(value: object, *, maximum: int) -> int | str:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        return "invalid"
    return value


def _public_age(value: object) -> float | None | str:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "invalid"
    number = float(value)
    return number if isfinite(number) and abs(number) <= 3_155_760_000 else "invalid"


def _bounded_max_age(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3_600:
        return None
    return value


def _safe_contract_violation(value: object) -> str:
    if isinstance(value, str) and value in PUBLIC_MEM0_OPENAPI_VIOLATIONS:
        return value
    return "invalid_contract_violation"


def _safe_validation_issue(value: object) -> str:
    if isinstance(value, str) and value in _PUBLIC_VALIDATION_ISSUES:
        return value
    prefix = "runtime_manifest:"
    if isinstance(value, str) and value.startswith(prefix):
        suffix = value.removeprefix(prefix)
        if suffix in MEM0_RUNTIME_CAPABILITY_ISSUE_CODES:
            return value
    return "invalid_validation_issue"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _deep_thaw(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _refresh_witness_signature(
    token: str,
    binding: Mapping[str, object],
    manifest_fingerprint: str,
) -> str:
    _require_hmac_key(token)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding.get("run_id_sha256") or ""),
            str(binding.get("probe_nonce_sha256") or ""),
            str(binding.get("target_identity_sha256") or ""),
            str(binding.get("refreshed_at") or ""),
            manifest_fingerprint,
        )
    ).encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def _verified_payload(payload: object) -> Mapping[str, object] | None:
    if not isinstance(payload, VerifiedMem0RuntimeAttestation):
        return None
    candidate = payload.payload
    if (
        _fingerprint(candidate) != payload._payload_fingerprint_sha256
        or _verified_binding_fingerprint(candidate) != payload._witness_binding_fingerprint_sha256
        or candidate.get("witness_signature_sha256") != payload._witness_signature_sha256
    ):
        return None
    return candidate


def _verified_binding_fingerprint(payload: Mapping[str, object]) -> str:
    manifest = _mapping(payload.get("runtime_manifest"))
    refresh = _mapping(manifest.get("refresh_binding"))
    return _fingerprint(
        {
            "run_id_sha256": payload.get("run_id_sha256"),
            "probe_nonce_sha256": payload.get("probe_nonce_sha256"),
            "target_identity_sha256": payload.get("target_identity_sha256"),
            "runtime_manifest_fingerprint_sha256": payload.get(
                "runtime_manifest_fingerprint_sha256"
            ),
            "refresh_binding": refresh,
            "witness_signature_sha256": payload.get("witness_signature_sha256"),
        }
    )


def _require_hmac_key(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("benchmark_probe_token must be a non-empty HMAC key")


def _deep_freeze(
    value: object,
    *,
    remaining: list[int],
    depth: int = 0,
) -> object:
    if depth > _MAX_CANONICAL_DEPTH:
        raise ValueError("runtime attestation exceeds canonical depth")
    remaining[0] -= 1
    if remaining[0] < 0:
        raise ValueError("runtime attestation exceeds canonical item count")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("runtime attestation contains a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_CANONICAL_TEXT_CHARS:
            raise ValueError("runtime attestation text is too large")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not 0 < len(key) <= _MAX_CANONICAL_KEY_CHARS:
                raise ValueError("runtime attestation keys must be bounded strings")
            frozen[key] = _deep_freeze(item, remaining=remaining, depth=depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(_deep_freeze(item, remaining=remaining, depth=depth + 1) for item in value)
    raise ValueError("runtime attestation must be JSON-compatible")


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_deep_thaw(item) for item in value]
    return value


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


__all__ = (
    "MEM0_MANAGED_PLATFORM_RUNTIME_MODE",
    "MEM0_OSS_RUNTIME_MODE",
    "MEM0_RUNTIME_ATTESTATION_MAX_AGE_SECONDS",
    "MEM0_RUNTIME_ATTESTATION_SCHEMA_VERSION",
    "MEM0_RUNTIME_ATTESTATION_VALIDATION_SCHEMA_VERSION",
    "build_mem0_runtime_attestation",
    "build_verified_mem0_runtime_attestation",
    "mem0_live_probe_target_is_safe",
    "mem0_runtime_attestation_blocker",
    "mem0_runtime_attestation_validation_is_publishable",
    "mem0_runtime_target_identity_sha256",
    "public_mem0_runtime_attestation",
    "public_mem0_runtime_attestation_validation",
    "replay_mem0_runtime_attestation",
    "validate_mem0_runtime_attestation",
    "validate_mem0_runtime_attestation_for_backends",
    "VerifiedMem0RuntimeAttestation",
    "VerifiedMem0RuntimeAttestationValidation",
)
