"""Immutable contracts for the low-level subscription-runtime bridge adapter."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from typing import ClassVar, Protocol
from urllib.parse import urlsplit

from .json_boundary import canonical_json_bytes

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class BridgeAuthorityError(ValueError):
    pass


class BridgeIntentError(ValueError):
    pass


class BridgeDivergenceError(RuntimeError):
    pass


class BridgeJournalError(RuntimeError):
    pass


class BridgeReceiptError(RuntimeError):
    pass


class BridgeTransportError(RuntimeError):
    pass


class PrivateOutputError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BridgeAuthority:
    """Public authority for exactly one local runtime; it never contains secrets."""

    bridge_id: str
    origin: str
    account_binding_hmac_sha256: str
    public_model: str
    base_instructions_sha256: str
    route: str = "/v1/chat/completions"

    CODEX_MODEL: ClassVar[str] = "gpt-5.6-sol"
    REASONING_EFFORT: ClassVar[str] = "high"
    SERVICE_TIER: ClassVar[str] = "priority"
    MODEL_PROVIDER: ClassVar[str] = "openai"
    EXECUTION_PROFILE: ClassVar[str] = "stateless-completion"

    def __post_init__(self) -> None:
        _require_identifier(self.bridge_id, "bridge_id", BridgeAuthorityError)
        _require_loopback_origin(self.origin)
        _require_sha256(self.account_binding_hmac_sha256, "account_binding")
        _require_sha256(self.base_instructions_sha256, "base_instructions")
        if self.route != "/v1/chat/completions":
            raise BridgeAuthorityError("bridge_route_invalid")
        if not isinstance(self.public_model, str) or not 1 <= len(self.public_model) <= 128:
            raise BridgeAuthorityError("bridge_public_model_invalid")
        if self.public_model.strip() != self.public_model:
            raise BridgeAuthorityError("bridge_public_model_invalid")

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.public_payload())).hexdigest()

    def public_payload(self) -> dict[str, object]:
        return {
            "account_binding_hmac_sha256": self.account_binding_hmac_sha256,
            "base_instructions_sha256": self.base_instructions_sha256,
            "bridge_id": self.bridge_id,
            "codex_model": self.CODEX_MODEL,
            "execution_profile": self.EXECUTION_PROFILE,
            "model_provider": self.MODEL_PROVIDER,
            "origin": self.origin,
            "public_model": self.public_model,
            "reasoning_effort": self.REASONING_EFFORT,
            "route": self.route,
            "service_tier": self.SERVICE_TIER,
        }


@dataclass(frozen=True, slots=True)
class BridgeCallBinding:
    """Caller-supplied durable intent and logical sharding identity."""

    intent_id: str
    logical_operation: str
    logical_call_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.intent_id, "intent_id", BridgeIntentError)
        _require_identifier(self.logical_operation, "logical_operation", BridgeIntentError)
        _require_identifier(self.logical_call_id, "logical_call_id", BridgeIntentError)

    def public_payload(self) -> dict[str, str]:
        return {
            "intent_id": self.intent_id,
            "logical_call_id": self.logical_call_id,
            "logical_operation": self.logical_operation,
        }


@dataclass(frozen=True, slots=True)
class BridgePoolAuthority:
    """Strict immutable pool whose order and bridge commitments are authoritative."""

    pool_id: str
    bridges: tuple[BridgeAuthority, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.pool_id, "pool_id", BridgeAuthorityError)
        if type(self.bridges) is not tuple or not 1 <= len(self.bridges) <= 32:
            raise BridgeAuthorityError("bridge_pool_members_invalid")
        if any(not isinstance(bridge, BridgeAuthority) for bridge in self.bridges):
            raise BridgeAuthorityError("bridge_pool_members_invalid")
        bridge_ids = tuple(bridge.bridge_id for bridge in self.bridges)
        if len(set(bridge_ids)) != len(bridge_ids):
            raise BridgeAuthorityError("bridge_pool_duplicate_id")

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.public_payload())).hexdigest()

    def public_payload(self) -> dict[str, object]:
        return {
            "bridges": [bridge.public_payload() for bridge in self.bridges],
            "pool_id": self.pool_id,
        }

    def select(self, binding: BridgeCallBinding) -> BridgeAuthority:
        shard_material = canonical_json_bytes(
            {
                "logical_call_id": binding.logical_call_id,
                "logical_operation": binding.logical_operation,
                "pool_authority_sha256": self.commitment_sha256,
            }
        )
        shard = int.from_bytes(hashlib.sha256(shard_material).digest()[:8], "big")
        return self.bridges[shard % len(self.bridges)]


@dataclass(frozen=True, slots=True)
class BridgeIntent:
    binding: BridgeCallBinding
    pool_id: str
    pool_authority_sha256: str
    bridge_id: str
    bridge_authority_sha256: str
    request_body_sha256: str
    prompt_input_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str | None
    request_identity_nonce: str
    output_token_limit: int

    def __post_init__(self) -> None:
        _require_identifier(self.pool_id, "pool_id", BridgeIntentError)
        _require_identifier(self.bridge_id, "bridge_id", BridgeIntentError)
        for label, value in (
            ("pool_authority", self.pool_authority_sha256),
            ("bridge_authority", self.bridge_authority_sha256),
            ("request_body", self.request_body_sha256),
            ("prompt_input", self.prompt_input_sha256),
            ("response_format", self.response_format_sha256),
            ("request_identity_nonce", self.request_identity_nonce),
        ):
            _require_sha256(value, label, BridgeIntentError)
        if self.response_schema_sha256 is not None:
            _require_sha256(self.response_schema_sha256, "response_schema", BridgeIntentError)
        if self.response_format_type not in {"text", "json_schema"}:
            raise BridgeIntentError("bridge_response_format_type_invalid")
        if (self.response_format_type == "text") != (self.response_schema_sha256 is None):
            raise BridgeIntentError("bridge_response_schema_binding_invalid")
        _require_safe_token_count(
            self.output_token_limit,
            "output_token_limit",
            positive=True,
            error_type=BridgeIntentError,
        )

    def public_payload(self) -> dict[str, object]:
        return {
            **self.binding.public_payload(),
            "bridge_authority_sha256": self.bridge_authority_sha256,
            "bridge_id": self.bridge_id,
            "output_token_limit": self.output_token_limit,
            "pool_authority_sha256": self.pool_authority_sha256,
            "pool_id": self.pool_id,
            "prompt_input_sha256": self.prompt_input_sha256,
            "request_body_sha256": self.request_body_sha256,
            "request_identity_nonce": self.request_identity_nonce,
            "response_format_sha256": self.response_format_sha256,
            "response_format_type": self.response_format_type,
            "response_schema_sha256": self.response_schema_sha256,
        }


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    cached_tokens: int
    cache_write_tokens: int | None
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        for label, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("cached_tokens", self.cached_tokens),
            ("completion_tokens", self.completion_tokens),
            ("reasoning_tokens", self.reasoning_tokens),
            ("total_tokens", self.total_tokens),
        ):
            _require_safe_token_count(value, label)
        if self.cache_write_tokens is not None:
            _require_safe_token_count(self.cache_write_tokens, "cache_write_tokens")
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise BridgeReceiptError("bridge_usage_total_invalid")
        if self.cached_tokens > self.prompt_tokens:
            raise BridgeReceiptError("bridge_usage_cached_invalid")
        if self.reasoning_tokens > self.completion_tokens:
            raise BridgeReceiptError("bridge_usage_reasoning_invalid")

    def public_payload(self) -> dict[str, int | None]:
        return {
            "cache_write_tokens": self.cache_write_tokens,
            "cached_tokens": self.cached_tokens,
            "completion_tokens": self.completion_tokens,
            "prompt_tokens": self.prompt_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class AuthenticatedBridgeResult:
    response_body_sha256: str
    output_text_sha256: str
    attestation_sha256: str
    receipt_hmac_sha256: str
    dispatch_binding_hmac_sha256: str
    thread_id: str
    turn_id: str
    usage: TokenUsage
    encrypted_output: bytes
    physical_receipt_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("response_body", self.response_body_sha256),
            ("output_text", self.output_text_sha256),
            ("attestation", self.attestation_sha256),
            ("receipt_hmac", self.receipt_hmac_sha256),
            ("dispatch_binding_hmac", self.dispatch_binding_hmac_sha256),
        ):
            _require_sha256(value, label, BridgeReceiptError)
        _require_identifier(self.thread_id, "thread_id", BridgeReceiptError)
        _require_identifier(self.turn_id, "turn_id", BridgeReceiptError)
        if not isinstance(self.encrypted_output, bytes) or not self.encrypted_output:
            raise BridgeReceiptError("bridge_encrypted_output_invalid")
        physical_receipt_sha256 = physical_provider_receipt_sha256(
            attestation_sha256=self.attestation_sha256,
            receipt_hmac_sha256=self.receipt_hmac_sha256,
        )
        object.__setattr__(self, "physical_receipt_sha256", physical_receipt_sha256)

    def public_payload(self, *, include_ciphertext: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "attestation_sha256": self.attestation_sha256,
            "dispatch_binding_hmac_sha256": self.dispatch_binding_hmac_sha256,
            "output_text_sha256": self.output_text_sha256,
            "receipt_hmac_sha256": self.receipt_hmac_sha256,
            "physical_receipt_sha256": self.physical_receipt_sha256,
            "response_body_sha256": self.response_body_sha256,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "usage": self.usage.public_payload(),
        }
        if include_ciphertext:
            payload["encrypted_output"] = self.encrypted_output.hex()
        return payload


@dataclass(frozen=True, slots=True)
class NotFound:
    intent_id: str


@dataclass(frozen=True, slots=True)
class AuthenticatedPreDispatchAbsence:
    """Journal-authenticated proof that an exact logical call was never observed."""

    binding: BridgeCallBinding
    journal_generation_sha256: str
    proof_hmac_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, BridgeCallBinding):
            raise BridgeJournalError("bridge_pre_dispatch_absence_binding_invalid")
        _require_sha256(
            self.journal_generation_sha256,
            "journal_generation",
            BridgeJournalError,
        )
        _require_sha256(
            self.proof_hmac_sha256,
            "pre_dispatch_absence_hmac",
            BridgeJournalError,
        )

    def public_payload(self) -> dict[str, object]:
        return {
            "binding": self.binding.public_payload(),
            "journal_generation_sha256": self.journal_generation_sha256,
            "proof_hmac_sha256": self.proof_hmac_sha256,
        }


@dataclass(frozen=True, slots=True)
class OutcomeUnknown:
    intent: BridgeIntent


@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    intent: BridgeIntent
    result: AuthenticatedBridgeResult


BridgeOutcome = AuthenticatedPreDispatchAbsence | NotFound | OutcomeUnknown | TerminalOutcome


class BridgeSecretCapability(Protocol):
    """Separate non-serializable access to runtime and launcher secrets."""

    def authorization_bearer(self, bridge_id: str) -> str: ...

    def attestation_secret(self, bridge_id: str) -> bytes: ...

    def launcher_receipt_key(self, bridge_id: str) -> bytes: ...


class BridgeTransportPort(Protocol):
    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes: ...


class OutputCipherPort(Protocol):
    """AEAD-like port; production implementations must use a reviewed direct dependency."""

    def seal(self, plaintext: bytes, *, associated_data: bytes) -> bytes: ...

    def open(self, ciphertext: bytes, *, associated_data: bytes) -> bytes: ...


def physical_provider_receipt_sha256(
    *,
    attestation_sha256: str,
    receipt_hmac_sha256: str,
) -> str:
    """Identify one provider-authenticated physical response independent of wrappers."""

    _require_sha256(attestation_sha256, "attestation", BridgeReceiptError)
    _require_sha256(receipt_hmac_sha256, "receipt_hmac", BridgeReceiptError)
    return hashlib.sha256(
        b"subscription-runtime-physical-receipt-v1\0"
        + canonical_json_bytes(
            {
                "attestation_sha256": attestation_sha256,
                "receipt_hmac_sha256": receipt_hmac_sha256,
            }
        )
    ).hexdigest()


def _require_loopback_origin(origin: object) -> None:
    if not isinstance(origin, str) or len(origin) > 256:
        raise BridgeAuthorityError("bridge_origin_invalid")
    try:
        split = urlsplit(origin)
        host = split.hostname
        port = split.port
    except (ValueError, TypeError) as exc:
        raise BridgeAuthorityError("bridge_origin_invalid") from exc
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError as exc:
        raise BridgeAuthorityError("bridge_origin_not_loopback") from exc
    if (
        split.scheme not in {"http", "https"}
        or split.username is not None
        or split.password is not None
        or split.path != ""
        or split.query
        or split.fragment
        or port is None
        or not address.is_loopback
    ):
        raise BridgeAuthorityError("bridge_origin_not_loopback")


def _require_identifier(value: object, label: str, error_type: type[ValueError]) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise error_type(f"bridge_{label}_invalid")


def _require_sha256(
    value: object,
    label: str,
    error_type: type[ValueError] | type[RuntimeError] = BridgeAuthorityError,
) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise error_type(f"bridge_{label}_sha256_invalid")


def _require_safe_token_count(
    value: object,
    label: str,
    *,
    positive: bool = False,
    error_type: type[ValueError] | type[RuntimeError] = BridgeReceiptError,
) -> None:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= _MAX_SAFE_INTEGER:
        raise error_type(f"bridge_{label}_invalid")


__all__ = (
    "AuthenticatedBridgeResult",
    "AuthenticatedPreDispatchAbsence",
    "BridgeAuthority",
    "BridgeAuthorityError",
    "BridgeCallBinding",
    "BridgeDivergenceError",
    "BridgeIntent",
    "BridgeIntentError",
    "BridgeJournalError",
    "BridgeOutcome",
    "BridgePoolAuthority",
    "BridgeReceiptError",
    "BridgeSecretCapability",
    "BridgeTransportError",
    "BridgeTransportPort",
    "NotFound",
    "OutcomeUnknown",
    "OutputCipherPort",
    "PrivateOutputError",
    "physical_provider_receipt_sha256",
    "TerminalOutcome",
    "TokenUsage",
)
