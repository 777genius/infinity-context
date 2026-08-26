"""Nominal managed Mem0 v5 runtime authority and validation capabilities."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import final

REQUEST_SCHEMA = "mem0-oss-adapter-v5.runtime-attestation-request.v1"
RESPONSE_SCHEMA = "mem0-oss-adapter-v5.runtime-attestation.v1"
VALIDATION_SCHEMA = "managed-mem0-v5-runtime-attestation-validation.v1"
RUNTIME_FAMILY = "mem0_oss_adapter_v5"
ATTESTATION_PATH = "/v5/runtime/attest"
_AUTH_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-authentication/v1"
_RESPONSE_KEY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response-key/v1"
_RESPONSE_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response/v1\0"
_IDEMPOTENCY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-idempotency/v1\0"
_ROUTES = (
    ("GET", "/health"),
    ("POST", ATTESTATION_PATH),
    ("POST", "/v5/operations/dispatch"),
    ("POST", "/v5/operations/request-binding"),
    ("POST", "/v5/operations/status"),
    ("POST", "/v5/operations/storage-observation"),
    ("POST", "/v5/runs/admit"),
    ("POST", "/v5/runs/clean-state"),
    ("POST", "/v5/runs/cleanup"),
    ("POST", "/v5/runs/search"),
)
_ROUTE_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema_version": "mem0-oss-adapter-v5.route-contract.v1",
            "routes": [{"method": method, "path": path} for method, path in _ROUTES],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
).hexdigest()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_STATIC_FIELDS = (
    "source_commit_sha1",
    "source_tree_sha1",
    "source_manifest_sha256",
    "source_closure_sha256",
    "phase_c_infinity_commit_sha1",
    "phase_c_infinity_tree_sha1",
    "phase_c_release_manifest_sha256",
    "runtime_binding_commitment_sha256",
    "subscription_runtime_binding_commitment_sha256",
    "runtime_source_sha256",
    "runtime_route_binding_sha256",
    "runtime_transport_origin_sha256",
    "expected_account_binding_hmac_sha256",
    "expected_base_instructions_sha256",
    "extraction_system_prompt_sha256",
    "extraction_response_format_sha256",
    "extraction_response_schema_sha256",
    "requested_output_tokens",
    "output_limit_enforced",
    "usage_attestation_required",
)
_RESPONSE_KEYS = frozenset(
    {
        "schema_version",
        "service",
        "route_contract_sha256",
        "target_origin_sha256",
        "run_id_sha256",
        "probe_nonce_sha256",
        *_STATIC_FIELDS,
        "implementation_binding_sha256",
        "issued_at_unix",
        "expires_at_unix",
        "provider_calls",
        "attestation_hmac_sha256",
    }
)
_SAFE_CODES = frozenset(
    {
        "managed_mem0_v5_runtime_already_used",
        "managed_mem0_v5_runtime_binding_invalid",
        "managed_mem0_v5_runtime_capability_invalid",
        "managed_mem0_v5_runtime_configuration_invalid",
        "managed_mem0_v5_runtime_deadline_exceeded",
        "managed_mem0_v5_runtime_implementation_mismatch",
        "managed_mem0_v5_runtime_implementation_unavailable",
        "managed_mem0_v5_runtime_not_prevalidated",
        "managed_mem0_v5_runtime_probe_failed",
        "managed_mem0_v5_runtime_target_unsafe",
    }
)
_MARKER = object()
_LOCK = threading.RLock()
_PENDING: set[object] = set()
_ISSUED: weakref.WeakValueDictionary[int, object] = weakref.WeakValueDictionary()


class ManagedMem0V5RuntimeAttestationHttpError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code if code in _SAFE_CODES else "managed_mem0_v5_runtime_probe_failed"
        super().__init__(self.code)


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5ExpectedRuntimeAuthority:
    """Public pins the response must match exactly before a capability is issued."""

    source_commit_sha1: str
    source_tree_sha1: str
    source_manifest_sha256: str
    source_closure_sha256: str
    phase_c_infinity_commit_sha1: str
    phase_c_infinity_tree_sha1: str
    phase_c_release_manifest_sha256: str
    runtime_binding_commitment_sha256: str
    subscription_runtime_binding_commitment_sha256: str
    runtime_source_sha256: str
    runtime_route_binding_sha256: str
    runtime_transport_origin_sha256: str
    expected_account_binding_hmac_sha256: str
    expected_base_instructions_sha256: str
    extraction_system_prompt_sha256: str
    extraction_response_format_sha256: str
    extraction_response_schema_sha256: str
    requested_output_tokens: int
    output_limit_enforced: bool
    usage_attestation_required: bool

    def __post_init__(self) -> None:
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        sha1_names = {
            "source_commit_sha1",
            "source_tree_sha1",
            "phase_c_infinity_commit_sha1",
            "phase_c_infinity_tree_sha1",
        }
        if (
            any(_SHA1.fullmatch(str(values[name])) is None for name in sha1_names)
            or any(
                not _is_sha256(value)
                for name, value in values.items()
                if name not in sha1_names
                and name
                not in {
                    "requested_output_tokens",
                    "output_limit_enforced",
                    "usage_attestation_required",
                }
            )
            or self.requested_output_tokens != 4096
            or self.output_limit_enforced is not False
            or self.usage_attestation_required is not False
        ):
            _configuration_invalid()

    def public_payload(self) -> dict[str, object]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


def expected_managed_mem0_v5_runtime_authority_from_pin(
    *,
    runtime_pin_file: Path,
    runtime_pin_sha256: str,
    runtime_source_sha256: str,
    runtime_route_binding_sha256: str,
    subscription_runtime_binding_commitment_sha256: str,
    expected_account_binding_hmac_sha256: str,
    expected_base_instructions_sha256: str,
    expected_extraction_system_prompt_sha256: str,
    expected_extraction_response_format_sha256: str,
    expected_extraction_response_schema_sha256: str,
    expected_requested_output_tokens: int,
) -> ManagedMem0V5ExpectedRuntimeAuthority:
    """Build exact expected response authority from independently pinned public inputs."""

    try:
        from infinity_context_server.memory_comparison_managed_v5_live_config import (
            _read_public_immutable,
        )

        raw = _read_public_immutable(
            runtime_pin_file,
            runtime_pin_sha256,
            maximum_bytes=128 * 1024,
            executable=False,
            code="managed_v5_live_adapter_runtime_pin_invalid",
        )
        pin = json.loads(raw, object_pairs_hook=_unique_object)
        if type(pin) is not dict or pin.get("schema_version") != (
            "mem0-oss-adapter-v5.runtime-pin.v1"
        ):
            raise ValueError
        source = _exact_mapping(pin.get("source_a"))
        phase = _exact_mapping(pin.get("phase_c"))
        contract = _exact_mapping(pin.get("runtime_contract"))
        if (
            contract.get("adapter_schema_version") != "mem0-benchmark-full-run.v5"
            or contract.get("provider_attempts_per_dispatch") != 1
            or contract.get("status_provider_attempts") != 0
            or contract.get("runtime_attestation_request_schema") != REQUEST_SCHEMA
            or contract.get("runtime_attestation_response_schema") != RESPONSE_SCHEMA
            or contract.get("runtime_attestation_route_contract_sha256") != _ROUTE_SHA256
            or contract.get("requested_output_tokens") != 4096
            or contract.get("output_limit_enforced") is not False
            or contract.get("usage_attestation_required") is not False
        ):
            raise ValueError
        runtime_transport = _digest(contract["transport_origin_sha256"])
        route = _digest(contract["route_binding_sha256"])
        extraction_system_prompt = _digest(contract["adapter_extraction_system_prompt_sha256"])
        extraction_response_format = _digest(contract["adapter_extraction_response_format_sha256"])
        extraction_response_schema = _digest(contract["adapter_extraction_schema_sha256"])
        if (
            route != runtime_route_binding_sha256
            or extraction_system_prompt != _digest(expected_extraction_system_prompt_sha256)
            or extraction_response_format != _digest(expected_extraction_response_format_sha256)
            or extraction_response_schema != _digest(expected_extraction_response_schema_sha256)
            or type(expected_requested_output_tokens) is not int
            or expected_requested_output_tokens != 4096
        ):
            raise ValueError
        source_values = {
            "source_commit_sha1": _sha1(source["commit_sha1"]),
            "source_tree_sha1": _sha1(source["tree_sha1"]),
            "source_manifest_sha256": _digest(source["manifest_sha256"]),
            "source_closure_sha256": _digest(source["closure_sha256"]),
            "phase_c_infinity_commit_sha1": _sha1(phase["infinity_source_commit_sha1"]),
            "phase_c_infinity_tree_sha1": _sha1(phase["infinity_source_tree_sha1"]),
            "phase_c_release_manifest_sha256": _digest(phase["release_manifest_sha256"]),
        }
        final_binding = _canonical_sha256(
            {
                "route_sha256": route,
                "manifest_sha256": source_values["source_manifest_sha256"],
                "source_closure_sha256": source_values["source_closure_sha256"],
                "source_commit_sha1": source_values["source_commit_sha1"],
                "source_tree_sha1": source_values["source_tree_sha1"],
                "phase_c_infinity_commit_sha1": source_values["phase_c_infinity_commit_sha1"],
                "phase_c_infinity_tree_sha1": source_values["phase_c_infinity_tree_sha1"],
                "phase_c_release_manifest_sha256": source_values["phase_c_release_manifest_sha256"],
                "runtime_binding_commitment_sha256": (
                    subscription_runtime_binding_commitment_sha256
                ),
                "runtime_source_sha256": runtime_source_sha256,
                "runtime_route_binding_sha256": route,
                "runtime_transport_origin_sha256": runtime_transport,
            }
        )
        return ManagedMem0V5ExpectedRuntimeAuthority(
            **source_values,
            runtime_binding_commitment_sha256=final_binding,
            subscription_runtime_binding_commitment_sha256=(
                subscription_runtime_binding_commitment_sha256
            ),
            runtime_source_sha256=_digest(runtime_source_sha256),
            runtime_route_binding_sha256=route,
            runtime_transport_origin_sha256=runtime_transport,
            expected_account_binding_hmac_sha256=_digest(expected_account_binding_hmac_sha256),
            expected_base_instructions_sha256=_digest(expected_base_instructions_sha256),
            extraction_system_prompt_sha256=extraction_system_prompt,
            extraction_response_format_sha256=extraction_response_format,
            extraction_response_schema_sha256=extraction_response_schema,
            requested_output_tokens=expected_requested_output_tokens,
            output_limit_enforced=False,
            usage_attestation_required=False,
        )
    except Exception:
        _configuration_invalid()


@final
@dataclass(frozen=True, slots=True, weakref_slot=True)
class VerifiedManagedMem0V5RuntimeAttestationValidation:
    payload: MappingProxyType
    _payload_fingerprint_sha256: str
    _marker: object
    _issuance_nonce: object

    def __post_init__(self) -> None:
        with _LOCK:
            issued_here = self._issuance_nonce in _PENDING
            _PENDING.discard(self._issuance_nonce)
        if (
            not issued_here
            or self._marker is not _MARKER
            or type(self.payload) is not MappingProxyType
            or _canonical_sha256(self.payload) != self._payload_fingerprint_sha256
        ):
            raise TypeError("managed v5 runtime validations must be verifier-issued")
        with _LOCK:
            _ISSUED[id(self)] = self

    def __copy__(self) -> object:
        raise TypeError("managed v5 runtime validations are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed v5 runtime validations are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed v5 runtime validations are nonserializable")


def _verified_managed_mem0_v5_runtime_validation_is_issued(value: object) -> bool:
    with _LOCK:
        return bool(
            type(value) is VerifiedManagedMem0V5RuntimeAttestationValidation
            and _ISSUED.get(id(value)) is value
            and _canonical_sha256(value.payload) == value._payload_fingerprint_sha256
        )


def public_managed_mem0_v5_runtime_validation(value: object) -> dict[str, object]:
    if not _verified_managed_mem0_v5_runtime_validation_is_issued(value):
        return {}
    thawed = _thaw(value.payload)
    return thawed if type(thawed) is dict else {}


def managed_mem0_v5_runtime_validation_is_publishable(
    value: object, *, required_runtime_mode: str
) -> bool:
    if required_runtime_mode != "oss" or not _verified_managed_mem0_v5_runtime_validation_is_issued(
        value
    ):
        return False
    payload = value.payload
    attestation = payload.get("attestation")
    return bool(
        payload.get("schema_version") == VALIDATION_SCHEMA
        and payload.get("status") == "valid"
        and payload.get("eligible") is True
        and payload.get("runtime_family") == RUNTIME_FAMILY
        and payload.get("required_runtime_mode") == "oss"
        and payload.get("observed_runtime_mode") == "oss"
        and type(payload.get("max_age_seconds")) is int
        and 1 <= payload["max_age_seconds"] <= 7_200
        and isinstance(attestation, Mapping)
        and attestation.get("schema_version") == RESPONSE_SCHEMA
        and attestation.get("service") == "mem0-oss-adapter-v5"
        and attestation.get("route_contract_sha256") == _ROUTE_SHA256
        and attestation.get("provider_calls") == 0
        and attestation.get("usage_attestation_required") is False
        and _is_sha256(attestation.get("attestation_fingerprint_sha256"))
    )


def _verify_and_issue(
    response: dict[str, object],
    *,
    request: Mapping[str, object],
    root_secret: bytes,
    expected_authority: ManagedMem0V5ExpectedRuntimeAuthority,
    now_unix: int,
) -> VerifiedManagedMem0V5RuntimeAttestationValidation:
    sha1_fields = {
        "source_commit_sha1",
        "source_tree_sha1",
        "phase_c_infinity_commit_sha1",
        "phase_c_infinity_tree_sha1",
    }
    if (
        set(response) != _RESPONSE_KEYS
        or response.get("schema_version") != RESPONSE_SCHEMA
        or response.get("service") != "mem0-oss-adapter-v5"
        or response.get("route_contract_sha256") != _ROUTE_SHA256
        or any(
            response.get(key) != request[key]
            for key in ("target_origin_sha256", "run_id_sha256", "probe_nonce_sha256")
        )
        or response.get("provider_calls") != 0
        or any(_SHA1.fullmatch(str(response.get(key) or "")) is None for key in sha1_fields)
        or any(
            not _is_sha256(response.get(key))
            for key in _RESPONSE_KEYS
            if key.endswith("_sha256") and key not in sha1_fields
        )
    ):
        _invalid_capability()
    issued = response.get("issued_at_unix")
    expires = response.get("expires_at_unix")
    validity = request.get("validity_seconds")
    if (
        type(issued) is not int
        or type(expires) is not int
        or type(validity) is not int
        or expires - issued != validity
        or not issued - 1 <= now_unix <= expires
    ):
        _invalid_capability()
    expected = expected_authority.public_payload()
    if any(response.get(key) != expected[key] for key in _STATIC_FIELDS):
        _invalid_capability()
    unsigned = dict(response)
    presented = str(unsigned.pop("attestation_hmac_sha256"))
    signing_key = hmac.new(root_secret, _RESPONSE_KEY_DOMAIN, hashlib.sha256).digest()
    signature = hmac.new(
        signing_key, _RESPONSE_DOMAIN + _canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(presented, signature):
        _invalid_capability()
    implementation = {
        "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
        "route_contract_sha256": _ROUTE_SHA256,
        **expected,
    }
    if response.get("implementation_binding_sha256") != _canonical_sha256(implementation):
        _invalid_capability()
    checked_at = _instant(issued)
    attestation = {
        **response,
        "runtime_mode": "oss",
        "checked_at": checked_at,
        "target_identity_sha256": response["target_origin_sha256"],
        "attestation_fingerprint_sha256": _canonical_sha256(response),
    }
    frozen = _freeze(
        {
            "schema_version": VALIDATION_SCHEMA,
            "status": "valid",
            "eligible": True,
            "runtime_family": RUNTIME_FAMILY,
            "required_runtime_mode": "oss",
            "observed_runtime_mode": "oss",
            "validated_at": checked_at,
            "max_age_seconds": validity,
            "age_seconds": 0.0,
            "timestamp_attestation_age_seconds": float(max(0, now_unix - issued)),
            "refresh_age_seconds": 0.0,
            "issues": [],
            "attestation": attestation,
        }
    )
    assert type(frozen) is MappingProxyType
    nonce = object()
    with _LOCK:
        _PENDING.add(nonce)
    try:
        return VerifiedManagedMem0V5RuntimeAttestationValidation(
            frozen, _canonical_sha256(frozen), _MARKER, nonce
        )
    finally:
        with _LOCK:
            _PENDING.discard(nonce)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise TypeError("managed v5 runtime validation is not canonical JSON")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_thaw(item) for item in value]
    return value


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _exact_mapping(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return value


def _digest(value: object) -> str:
    if not _is_sha256(value):
        raise ValueError
    return str(value)


def _sha1(value: object) -> str:
    if type(value) is not str or _SHA1.fullmatch(value) is None:
        raise ValueError
    return value


def _instant(value: int) -> str:
    return (
        datetime.fromtimestamp(value, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _configuration_invalid() -> None:
    raise ManagedMem0V5RuntimeAttestationHttpError("managed_mem0_v5_runtime_configuration_invalid")


def _invalid_capability() -> None:
    raise ManagedMem0V5RuntimeAttestationHttpError("managed_mem0_v5_runtime_capability_invalid")


__all__ = (
    "ManagedMem0V5ExpectedRuntimeAuthority",
    "ManagedMem0V5RuntimeAttestationHttpError",
    "VerifiedManagedMem0V5RuntimeAttestationValidation",
    "managed_mem0_v5_runtime_validation_is_publishable",
    "expected_managed_mem0_v5_runtime_authority_from_pin",
    "public_managed_mem0_v5_runtime_validation",
)
