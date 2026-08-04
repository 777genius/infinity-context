"""Strict signed run-scoped usage evidence for the Mem0 OSS benchmark adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import final

MEM0_OSS_USAGE_ATTESTATION_PATH = "/benchmark/attest-usage"
MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION = "mem0-benchmark-usage-attestation.v1"
MEM0_OSS_USAGE_WITNESS_CONTEXT = "mem0-benchmark-usage-witness.v1"
MEM0_OSS_USAGE_ALGORITHM = "hmac-sha256"
MEM0_OSS_USAGE_MODEL = "gpt-5.6-sol"
MEM0_OSS_MAX_USAGE_OPERATIONS = 10_000
MEM0_OSS_USAGE_MAX_BYTES = 1_048_576
MEM0_OSS_USAGE_MAX_AGE_SECONDS = 120

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MILLISECOND_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_USAGE_FIELDS = {
    "mode",
    "operation_count",
    "extraction_calls",
    "request_bytes",
    "response_bytes",
    "model",
    "first_operation_at",
    "last_operation_at",
}
_RESPONSE_FIELDS = {
    "schema_version",
    "run_id_sha256",
    "probe_nonce_sha256",
    "target_identity_sha256",
    "attested_at",
    "usage",
    "usage_fingerprint_sha256",
    "algorithm",
    "signature",
}
_TOKEN = object()


class Mem0OssUsageAttestationError(RuntimeError):
    """Fixed-code verifier error that never reflects remote values or credentials."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class Mem0OssUsageAttestationRequest:
    """Exact private challenge sent to the usage attestation endpoint."""

    run_id: str
    probe_nonce: str
    target_identity_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or _RUN_ID.fullmatch(self.run_id) is None
            or type(self.probe_nonce) is not str
            or _NONCE.fullmatch(self.probe_nonce) is None
            or type(self.target_identity_sha256) is not str
            or _SHA256.fullmatch(self.target_identity_sha256) is None
        ):
            raise Mem0OssUsageAttestationError("mem0_oss_usage_request_invalid")

    def payload(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "probe_nonce": self.probe_nonce,
            "target_identity_sha256": self.target_identity_sha256,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0OssUsageAttestationRequest is final")


@final
@dataclass(frozen=True, slots=True)
class Mem0OssUsageEvidence:
    """Sanitized exact one-add usage evidence after signature verification."""

    mode: str
    operation_count: int
    extraction_calls: int
    request_bytes: int
    response_bytes: int
    model: str
    first_operation_at: str
    last_operation_at: str
    attested_at: str
    usage_fingerprint_sha256: str

    def __post_init__(self) -> None:
        if not _usage_evidence_is_valid(self):
            raise Mem0OssUsageAttestationError("mem0_oss_usage_evidence_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "operation_count": self.operation_count,
            "extraction_calls": self.extraction_calls,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "model": self.model,
            "first_operation_at": self.first_operation_at,
            "last_operation_at": self.last_operation_at,
            "usage_fingerprint_sha256": self.usage_fingerprint_sha256,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0OssUsageEvidence is final")


@final
class VerifiedMem0OssUsageAttestation:
    """Opaque proof that one exact response passed binding, invariant and HMAC checks."""

    __slots__ = (
        "__evidence",
        "__probe_nonce_sha256",
        "__run_id_sha256",
        "__target_identity_sha256",
    )

    def __init__(
        self,
        *,
        run_id_sha256: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
        evidence: Mem0OssUsageEvidence,
        _token: object,
    ) -> None:
        if (
            _token is not _TOKEN
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    run_id_sha256,
                    probe_nonce_sha256,
                    target_identity_sha256,
                )
            )
            or type(evidence) is not Mem0OssUsageEvidence
        ):
            raise Mem0OssUsageAttestationError("mem0_oss_usage_evidence_invalid")
        self.__run_id_sha256 = run_id_sha256
        self.__probe_nonce_sha256 = probe_nonce_sha256
        self.__target_identity_sha256 = target_identity_sha256
        self.__evidence = evidence

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedMem0OssUsageAttestation is final")

    def __repr__(self) -> str:
        return "VerifiedMem0OssUsageAttestation(<verified>)"

    def __reduce__(self) -> object:
        raise TypeError("verified Mem0 OSS usage attestation is nonserializable")

    @property
    def evidence(self) -> Mem0OssUsageEvidence:
        return self.__evidence

    def public_payload(self) -> dict[str, object]:
        return {
            "schema_version": MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION,
            "run_id_sha256": self.__run_id_sha256,
            "probe_nonce_sha256": self.__probe_nonce_sha256,
            "target_identity_sha256": self.__target_identity_sha256,
            "attested_at": self.__evidence.attested_at,
            "usage": self.__evidence.public_payload(),
            "algorithm": MEM0_OSS_USAGE_ALGORITHM,
            "verified": True,
        }


def verify_mem0_oss_usage_attestation(
    payload: object,
    *,
    benchmark_probe_token: str,
    request: Mem0OssUsageAttestationRequest,
    validated_at: datetime,
) -> VerifiedMem0OssUsageAttestation:
    """Verify exact bindings, single-add invariants, freshness, fingerprint and HMAC."""

    if type(request) is not Mem0OssUsageAttestationRequest:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_request_invalid")
    key = _hmac_key(benchmark_probe_token)
    now = _aware(validated_at)
    response = _exact_mapping(payload, _RESPONSE_FIELDS)
    if response is None:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_response_invalid")
    run_id_sha256 = hashlib.sha256(request.run_id.encode()).hexdigest()
    probe_nonce_sha256 = hashlib.sha256(request.probe_nonce.encode()).hexdigest()
    if (
        response.get("schema_version") != MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION
        or response.get("algorithm") != MEM0_OSS_USAGE_ALGORITHM
        or not _digest_matches(response.get("run_id_sha256"), run_id_sha256)
        or not _digest_matches(response.get("probe_nonce_sha256"), probe_nonce_sha256)
        or not _digest_matches(
            response.get("target_identity_sha256"),
            request.target_identity_sha256,
        )
    ):
        raise Mem0OssUsageAttestationError("mem0_oss_usage_binding_invalid")
    usage = _exact_mapping(response.get("usage"), _USAGE_FIELDS)
    if usage is None or not _usage_mapping_is_valid(usage):
        raise Mem0OssUsageAttestationError("mem0_oss_usage_invariant_invalid")
    attested_at = _instant(response.get("attested_at"))
    first = _instant(usage["first_operation_at"])
    last = _instant(usage["last_operation_at"])
    if (
        first > last
        or last > attested_at
        or attested_at > now + timedelta(seconds=5)
        or now - attested_at > timedelta(seconds=MEM0_OSS_USAGE_MAX_AGE_SECONDS)
    ):
        raise Mem0OssUsageAttestationError("mem0_oss_usage_timestamp_invalid")
    fingerprint = hashlib.sha256(
        _canonical_json_bytes(
            {
                "attested_at": response["attested_at"],
                "usage": dict(usage),
            }
        )
    ).hexdigest()
    if not _digest_matches(response.get("usage_fingerprint_sha256"), fingerprint):
        raise Mem0OssUsageAttestationError("mem0_oss_usage_fingerprint_invalid")
    expected_signature = hmac.new(
        key,
        _witness_payload(
            run_id_sha256=run_id_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=request.target_identity_sha256,
            attested_at=str(response["attested_at"]),
            usage_fingerprint_sha256=fingerprint,
        ),
        hashlib.sha256,
    ).hexdigest()
    if not _digest_matches(response.get("signature"), expected_signature):
        raise Mem0OssUsageAttestationError("mem0_oss_usage_signature_invalid")
    evidence = Mem0OssUsageEvidence(
        mode=str(usage["mode"]),
        operation_count=int(usage["operation_count"]),
        extraction_calls=int(usage["extraction_calls"]),
        request_bytes=int(usage["request_bytes"]),
        response_bytes=int(usage["response_bytes"]),
        model=str(usage["model"]),
        first_operation_at=str(usage["first_operation_at"]),
        last_operation_at=str(usage["last_operation_at"]),
        attested_at=str(response["attested_at"]),
        usage_fingerprint_sha256=fingerprint,
    )
    return VerifiedMem0OssUsageAttestation(
        run_id_sha256=run_id_sha256,
        probe_nonce_sha256=probe_nonce_sha256,
        target_identity_sha256=request.target_identity_sha256,
        evidence=evidence,
        _token=_TOKEN,
    )


def _witness_payload(
    *,
    run_id_sha256: str,
    probe_nonce_sha256: str,
    target_identity_sha256: str,
    attested_at: str,
    usage_fingerprint_sha256: str,
) -> bytes:
    return "\n".join(
        (
            MEM0_OSS_USAGE_WITNESS_CONTEXT,
            run_id_sha256,
            probe_nonce_sha256,
            target_identity_sha256,
            attested_at,
            usage_fingerprint_sha256,
        )
    ).encode()


def _usage_mapping_is_valid(usage: Mapping[str, object]) -> bool:
    mode = usage.get("mode")
    operation_count = usage.get("operation_count")
    extraction_calls = usage.get("extraction_calls")
    request_bytes = usage.get("request_bytes")
    response_bytes = usage.get("response_bytes")
    common_valid = (
        mode in {"raw_passthrough", "subscription_llm"}
        and usage.get("model") == MEM0_OSS_USAGE_MODEL
        and all(
            type(usage.get(field)) is str
            and _MILLISECOND_UTC.fullmatch(str(usage[field])) is not None
            for field in ("first_operation_at", "last_operation_at")
        )
    )
    if not common_valid:
        return False
    if mode == "raw_passthrough":
        return (
            type(operation_count) is int
            and 1 <= operation_count <= MEM0_OSS_MAX_USAGE_OPERATIONS
            and type(extraction_calls) is int
            and extraction_calls == 0
            and type(request_bytes) is int
            and request_bytes == 0
            and type(response_bytes) is int
            and response_bytes == 0
        )
    return (
        type(operation_count) is int
        and operation_count == 1
        and type(extraction_calls) is int
        and extraction_calls == 1
        and type(request_bytes) is int
        and 1 <= request_bytes <= MEM0_OSS_USAGE_MAX_BYTES
        and type(response_bytes) is int
        and 0 <= response_bytes <= MEM0_OSS_USAGE_MAX_BYTES
    )


def _usage_evidence_is_valid(value: Mem0OssUsageEvidence) -> bool:
    usage = value.public_payload()
    usage.pop("usage_fingerprint_sha256")
    return (
        _usage_mapping_is_valid(usage)
        and type(value.attested_at) is str
        and _MILLISECOND_UTC.fullmatch(value.attested_at) is not None
        and type(value.usage_fingerprint_sha256) is str
        and _SHA256.fullmatch(value.usage_fingerprint_sha256) is not None
    )


def _exact_mapping(value: object, keys: set[str]) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) and set(value) == keys else None


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def _digest_matches(value: object, expected: str) -> bool:
    return (
        type(value) is str
        and _SHA256.fullmatch(value) is not None
        and hmac.compare_digest(value, expected)
    )


def _hmac_key(value: object) -> bytes:
    if type(value) is not str or not value or value != value.strip():
        raise Mem0OssUsageAttestationError("mem0_oss_usage_verifier_key_invalid")
    try:
        encoded = value.encode()
    except UnicodeEncodeError:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_verifier_key_invalid") from None
    if len(encoded) > 4_096:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_verifier_key_invalid")
    return encoded


def _instant(value: object) -> datetime:
    if type(value) is not str or _MILLISECOND_UTC.fullmatch(value) is None:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_timestamp_invalid")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(UTC)
    except ValueError:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_timestamp_invalid") from None


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Mem0OssUsageAttestationError("mem0_oss_usage_validation_time_invalid")
    return value.astimezone(UTC)


__all__ = (
    "MEM0_OSS_USAGE_ALGORITHM",
    "MEM0_OSS_USAGE_ATTESTATION_PATH",
    "MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION",
    "MEM0_OSS_MAX_USAGE_OPERATIONS",
    "MEM0_OSS_USAGE_MAX_AGE_SECONDS",
    "MEM0_OSS_USAGE_MAX_BYTES",
    "MEM0_OSS_USAGE_MODEL",
    "MEM0_OSS_USAGE_WITNESS_CONTEXT",
    "Mem0OssUsageAttestationError",
    "Mem0OssUsageAttestationRequest",
    "Mem0OssUsageEvidence",
    "VerifiedMem0OssUsageAttestation",
    "verify_mem0_oss_usage_attestation",
)
