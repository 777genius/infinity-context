"""Provider-free, challenge-bound authority for the deployed v5 HTTP contract."""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from collections.abc import Callable
from dataclasses import InitVar, dataclass
from typing import Annotated, Final, Literal, final

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .domain import canonical_json_bytes, canonical_sha256
from .extraction_contract import (
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_RESPONSE_FORMAT_SHA256,
    EXTRACTION_SCHEMA_SHA256,
    EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from .source_authority import VerifiedSourceAuthority
from .subscription_runtime import SUBSCRIPTION_RUNTIME_ROUTE_SHA256

REQUEST_SCHEMA: Final = "mem0-oss-adapter-v5.runtime-attestation-request.v1"
RESPONSE_SCHEMA: Final = "mem0-oss-adapter-v5.runtime-attestation.v1"
ATTESTATION_PATH: Final = "/v5/runtime/attest"
_AUTHENTICATION_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-authentication/v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response-key/v1"
_IDEMPOTENCY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-idempotency/v1\0"
_SIGNATURE_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response/v1\0"
_MAX_CHALLENGES = 1_024
_PROJECTION_ISSUANCE = object()
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHA1_PATTERN = r"^[0-9a-f]{40}$"
Sha256 = Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)]
Sha1 = Annotated[StrictStr, Field(pattern=_SHA1_PATTERN)]

# This inventory is the public HTTP capability being attested. Any route change must
# intentionally change the digest and therefore the implementation binding.
V5_ROUTE_CONTRACT: Final = (
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
V5_ROUTE_CONTRACT_SHA256: Final = canonical_sha256(
    {
        "schema_version": "mem0-oss-adapter-v5.route-contract.v1",
        "routes": [{"method": method, "path": path} for method, path in V5_ROUTE_CONTRACT],
    }
)


class _ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RuntimeAttestationRequest(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.runtime-attestation-request.v1"] = REQUEST_SCHEMA
    target_origin_sha256: Sha256
    run_id_sha256: Sha256
    probe_nonce_sha256: Sha256
    validity_seconds: Annotated[StrictInt, Field(ge=1, le=7_200)]


class RuntimeAttestationResponse(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.runtime-attestation.v1"]
    service: Literal["mem0-oss-adapter-v5"]
    route_contract_sha256: Sha256
    target_origin_sha256: Sha256
    run_id_sha256: Sha256
    probe_nonce_sha256: Sha256
    source_commit_sha1: Sha1
    source_tree_sha1: Sha1
    source_manifest_sha256: Sha256
    source_closure_sha256: Sha256
    phase_c_infinity_commit_sha1: Sha1
    phase_c_infinity_tree_sha1: Sha1
    phase_c_release_manifest_sha256: Sha256
    runtime_binding_commitment_sha256: Sha256
    subscription_runtime_binding_commitment_sha256: Sha256
    runtime_source_sha256: Sha256
    runtime_route_binding_sha256: Sha256
    runtime_transport_origin_sha256: Sha256
    expected_account_binding_hmac_sha256: Sha256
    expected_base_instructions_sha256: Sha256
    extraction_system_prompt_sha256: Sha256
    extraction_response_format_sha256: Sha256
    extraction_response_schema_sha256: Sha256
    requested_output_tokens: Literal[4096]
    output_limit_enforced: Literal[False]
    usage_attestation_required: Literal[False]
    implementation_binding_sha256: Sha256
    issued_at_unix: Annotated[StrictInt, Field(ge=1)]
    expires_at_unix: Annotated[StrictInt, Field(ge=1)]
    provider_calls: Literal[0]
    attestation_hmac_sha256: Sha256

    @model_validator(mode="after")
    def lifetime_is_bounded(self) -> RuntimeAttestationResponse:
        lifetime = self.expires_at_unix - self.issued_at_unix
        if not 1 <= lifetime <= 7_200:
            raise ValueError("runtime_attestation_invalid")
        return self


class RuntimeAttestationError(RuntimeError):
    """Stable, data-free error raised by the attestation authority."""

    def __init__(self, code: str, *, status_code: int) -> None:
        allowed = {
            "runtime_attestation_invalid": 400,
            "runtime_attestation_conflict": 409,
            "runtime_attestation_expired": 410,
            "runtime_attestation_unavailable": 503,
        }
        expected_status = allowed.get(code)
        if expected_status != status_code:
            code = "runtime_attestation_unavailable"
            expected_status = 503
        self.code = code
        self.status_code = expected_status
        super().__init__(self.code)


@final
@dataclass(frozen=True, slots=True)
class V5RuntimeAuthorityProjection:
    """One immutable authority shared by admission and runtime attestation."""

    source_authority: VerifiedSourceAuthority
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
    _issuance: InitVar[object]

    def __post_init__(self, issuance: object) -> None:
        if issuance is not _PROJECTION_ISSUANCE:
            raise TypeError("runtime authority projection requires verified issuance")

    @classmethod
    def issue(
        cls,
        *,
        source_authority: VerifiedSourceAuthority,
        subscription_runtime_binding_commitment_sha256: str,
        runtime_source_sha256: str,
        runtime_route_binding_sha256: str,
        runtime_transport_origin_sha256: str,
        expected_account_binding_hmac_sha256: str,
        expected_base_instructions_sha256: str,
    ) -> V5RuntimeAuthorityProjection:
        if type(source_authority) is not VerifiedSourceAuthority:
            raise ValueError("adapter_configuration_invalid")
        values = (
            subscription_runtime_binding_commitment_sha256,
            runtime_source_sha256,
            runtime_route_binding_sha256,
            runtime_transport_origin_sha256,
            expected_account_binding_hmac_sha256,
            expected_base_instructions_sha256,
        )
        if any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in values
        ):
            raise ValueError("adapter_configuration_invalid")
        runtime_binding = source_authority.binding_commitment(
            route_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
            runtime_binding_commitment_sha256=subscription_runtime_binding_commitment_sha256,
            runtime_source_sha256=runtime_source_sha256,
            runtime_route_binding_sha256=runtime_route_binding_sha256,
            runtime_transport_origin_sha256=runtime_transport_origin_sha256,
        )
        return cls(
            source_authority=source_authority,
            runtime_binding_commitment_sha256=runtime_binding,
            subscription_runtime_binding_commitment_sha256=(
                subscription_runtime_binding_commitment_sha256
            ),
            runtime_source_sha256=runtime_source_sha256,
            runtime_route_binding_sha256=runtime_route_binding_sha256,
            runtime_transport_origin_sha256=runtime_transport_origin_sha256,
            expected_account_binding_hmac_sha256=expected_account_binding_hmac_sha256,
            expected_base_instructions_sha256=expected_base_instructions_sha256,
            extraction_system_prompt_sha256=EXTRACTION_SYSTEM_PROMPT_SHA256,
            extraction_response_format_sha256=EXTRACTION_RESPONSE_FORMAT_SHA256,
            extraction_response_schema_sha256=EXTRACTION_SCHEMA_SHA256,
            requested_output_tokens=EXTRACTION_MAX_TOKENS,
            output_limit_enforced=False,
            usage_attestation_required=False,
            _issuance=_PROJECTION_ISSUANCE,
        )


@final
class V5RuntimeAttestationAuthority:
    """Issues exact, short-lived responses without provider or application calls."""

    def __init__(
        self,
        *,
        projection: V5RuntimeAuthorityProjection,
        root_secret: bytes,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(projection) is not V5RuntimeAuthorityProjection:
            raise ValueError("adapter_configuration_invalid")
        if type(root_secret) is not bytes or not 32 <= len(root_secret) <= 4_096:
            raise ValueError("adapter_configuration_invalid")
        source_authority = projection.source_authority
        static = {
            "route_contract_sha256": V5_ROUTE_CONTRACT_SHA256,
            "source_commit_sha1": source_authority.source_commit_sha1,
            "source_tree_sha1": source_authority.source_tree_sha1,
            "source_manifest_sha256": source_authority.manifest_sha256,
            "source_closure_sha256": source_authority.closure_sha256,
            "phase_c_infinity_commit_sha1": source_authority.phase_c_infinity_commit_sha1,
            "phase_c_infinity_tree_sha1": source_authority.phase_c_infinity_tree_sha1,
            "phase_c_release_manifest_sha256": source_authority.phase_c_release_manifest_sha256,
            "runtime_binding_commitment_sha256": projection.runtime_binding_commitment_sha256,
            "subscription_runtime_binding_commitment_sha256": (
                projection.subscription_runtime_binding_commitment_sha256
            ),
            "runtime_source_sha256": projection.runtime_source_sha256,
            "runtime_route_binding_sha256": projection.runtime_route_binding_sha256,
            "runtime_transport_origin_sha256": projection.runtime_transport_origin_sha256,
            "expected_account_binding_hmac_sha256": (
                projection.expected_account_binding_hmac_sha256
            ),
            "expected_base_instructions_sha256": projection.expected_base_instructions_sha256,
            "extraction_system_prompt_sha256": projection.extraction_system_prompt_sha256,
            "extraction_response_format_sha256": projection.extraction_response_format_sha256,
            "extraction_response_schema_sha256": projection.extraction_response_schema_sha256,
            "requested_output_tokens": projection.requested_output_tokens,
            "output_limit_enforced": projection.output_limit_enforced,
            "usage_attestation_required": projection.usage_attestation_required,
        }
        try:
            RuntimeAttestationResponse.model_validate(
                {
                    "schema_version": RESPONSE_SCHEMA,
                    "service": "mem0-oss-adapter-v5",
                    **static,
                    "target_origin_sha256": "0" * 64,
                    "run_id_sha256": "0" * 64,
                    "probe_nonce_sha256": "0" * 64,
                    "implementation_binding_sha256": "0" * 64,
                    "issued_at_unix": 1,
                    "expires_at_unix": 2,
                    "provider_calls": 0,
                    "attestation_hmac_sha256": "0" * 64,
                }
            )
        except Exception:
            raise ValueError("adapter_configuration_invalid") from None
        self._static = static
        self._implementation_binding = canonical_sha256(
            {
                "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
                **static,
            }
        )
        self._authentication_token = hmac.new(
            root_secret, _AUTHENTICATION_DOMAIN, hashlib.sha256
        ).hexdigest()
        self._signing_key = hmac.new(root_secret, _KEY_DOMAIN, hashlib.sha256).digest()
        self._clock = clock
        self._lock = threading.Lock()
        self._by_nonce: dict[str, tuple[str, RuntimeAttestationResponse]] = {}

    @property
    def authentication_token(self) -> str:
        return self._authentication_token

    def attest(
        self,
        request: RuntimeAttestationRequest,
        *,
        idempotency_key: str,
    ) -> RuntimeAttestationResponse:
        request_payload = request.model_dump(mode="json")
        request_sha256 = canonical_sha256(request_payload)
        if not hmac.compare_digest(
            runtime_attestation_idempotency_key(request_sha256), idempotency_key
        ):
            raise RuntimeAttestationError("runtime_attestation_invalid", status_code=400)
        try:
            raw_now = self._clock()
            if type(raw_now) is not float or not math.isfinite(raw_now) or raw_now < 1:
                raise ValueError
            now = int(raw_now)
        except (OverflowError, TypeError, ValueError):
            raise RuntimeAttestationError(
                "runtime_attestation_unavailable", status_code=503
            ) from None
        with self._lock:
            existing = self._by_nonce.get(request.probe_nonce_sha256)
            if existing is not None:
                existing_request, response = existing
                if not hmac.compare_digest(existing_request, request_sha256):
                    raise RuntimeAttestationError("runtime_attestation_conflict", status_code=409)
                if now > response.expires_at_unix:
                    raise RuntimeAttestationError("runtime_attestation_expired", status_code=410)
                return response
            if len(self._by_nonce) >= _MAX_CHALLENGES:
                raise RuntimeAttestationError("runtime_attestation_unavailable", status_code=503)
            unsigned = {
                "schema_version": RESPONSE_SCHEMA,
                "service": "mem0-oss-adapter-v5",
                **self._static,
                "target_origin_sha256": request.target_origin_sha256,
                "run_id_sha256": request.run_id_sha256,
                "probe_nonce_sha256": request.probe_nonce_sha256,
                "implementation_binding_sha256": self._implementation_binding,
                "issued_at_unix": now,
                "expires_at_unix": now + request.validity_seconds,
                "provider_calls": 0,
            }
            response = RuntimeAttestationResponse.model_validate(
                {
                    **unsigned,
                    "attestation_hmac_sha256": _signature(self._signing_key, unsigned),
                }
            )
            self._by_nonce[request.probe_nonce_sha256] = (request_sha256, response)
            return response


def verify_runtime_attestation(
    response: RuntimeAttestationResponse,
    *,
    root_secret: bytes,
) -> bool:
    """Verify the adapter signature without trusting the issuing authority object."""

    if type(root_secret) is not bytes or not 32 <= len(root_secret) <= 4_096:
        return False
    payload = response.model_dump(mode="json")
    presented = payload.pop("attestation_hmac_sha256")
    signing_key = hmac.new(root_secret, _KEY_DOMAIN, hashlib.sha256).digest()
    return hmac.compare_digest(_signature(signing_key, payload), presented)


def _signature(key: bytes, payload: dict[str, object]) -> str:
    return hmac.new(
        key,
        _SIGNATURE_DOMAIN + canonical_json_bytes(payload),
        hashlib.sha256,
    ).hexdigest()


def runtime_attestation_idempotency_key(request_sha256: str) -> str:
    if (
        type(request_sha256) is not str
        or len(request_sha256) != 64
        or any(character not in "0123456789abcdef" for character in request_sha256)
    ):
        raise ValueError("runtime_attestation_invalid")
    return hashlib.sha256(_IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha256)).hexdigest()


__all__ = (
    "ATTESTATION_PATH",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "V5_ROUTE_CONTRACT",
    "V5_ROUTE_CONTRACT_SHA256",
    "RuntimeAttestationError",
    "RuntimeAttestationRequest",
    "RuntimeAttestationResponse",
    "V5RuntimeAttestationAuthority",
    "V5RuntimeAuthorityProjection",
    "runtime_attestation_idempotency_key",
    "verify_runtime_attestation",
)
