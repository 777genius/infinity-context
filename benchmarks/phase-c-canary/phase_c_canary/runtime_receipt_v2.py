from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from weakref import ReferenceType, ref

from .hashing import canonical_json_bytes, sha256_bytes
from .receipt import ReceiptVerificationError, RuntimeReceiptVerifierPort, validate_receipt_shape
from .runtime_binding import TrustedRuntimeBinding, require_trusted_runtime_binding


class RuntimeCallKind(StrEnum):
    EXTRACTION = "extraction"
    ANSWER = "answer"
    JUDGE = "judge"


@dataclass(frozen=True, slots=True)
class RuntimeReceiptExpectation:
    model: str
    reasoning_effort: str
    service_tier: str
    base_instructions_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str
    account_binding_hmac_sha256: str
    thread_id: str
    turn_id: str
    request_body_sha256: str
    output_text_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int


@dataclass(frozen=True, slots=True)
class ProviderObservedUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None
    cache_write_tokens: int | None
    reasoning_tokens: int | None

    def commitment_payload(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


_RECEIPT_SEAL = object()


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SafeRuntimeReceipt:
    schema_version: int
    call_kind: RuntimeCallKind
    sequence: int
    operation_id_sha256: str
    receipt_sha256: str
    identity_sha256: str
    request_body_sha256: str
    output_text_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str
    runtime_binding_commitment_sha256: str
    usage: ProviderObservedUsage
    _seal: object = field(init=False, repr=False, compare=False)
    _runtime_binding: TrustedRuntimeBinding = field(init=False, repr=False, compare=False)

    def __init__(
        self,
        *,
        schema_version: int,
        call_kind: RuntimeCallKind,
        sequence: int,
        operation_id_sha256: str,
        receipt_sha256: str,
        identity_sha256: str,
        request_body_sha256: str,
        output_text_sha256: str,
        runtime_source_sha256: str,
        route_binding_sha256: str,
        runtime_binding_commitment_sha256: str,
        usage: ProviderObservedUsage,
        runtime_binding: TrustedRuntimeBinding,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _RECEIPT_SEAL:
            raise ReceiptVerificationError("safe runtime receipts are verifier-issued only")
        values = locals()
        for attribute_name in (
            "schema_version",
            "call_kind",
            "sequence",
            "operation_id_sha256",
            "receipt_sha256",
            "identity_sha256",
            "request_body_sha256",
            "output_text_sha256",
            "runtime_source_sha256",
            "route_binding_sha256",
            "runtime_binding_commitment_sha256",
            "usage",
            "_seal",
            "runtime_binding",
        ):
            stored_name = (
                "_runtime_binding" if attribute_name == "runtime_binding" else attribute_name
            )
            object.__setattr__(self, stored_name, values[attribute_name])
        _remember_receipt(self)

    def _is_authentic(self) -> bool:
        registered = _ISSUED_RECEIPTS.get(id(self))
        binding = getattr(self, "_runtime_binding", None)
        try:
            require_trusted_runtime_binding(binding)
            binding_matches = (
                self.runtime_source_sha256 == binding.runtime_source_sha256
                and self.route_binding_sha256 == binding.route_binding_sha256
                and self.runtime_binding_commitment_sha256 == binding.commitment_sha256
            )
        except (AttributeError, ReceiptVerificationError):
            binding_matches = False
        return (
            getattr(self, "_seal", None) is _RECEIPT_SEAL
            and registered is not None
            and registered[0]() is self
            and registered[1] == _receipt_snapshot(self)
            and registered[2] == id(binding)
            and binding_matches
        )

    def commitment_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "call_kind": self.call_kind.value,
            "sequence": self.sequence,
            "operation_id_sha256": self.operation_id_sha256,
            "receipt_sha256": self.receipt_sha256,
            "identity_sha256": self.identity_sha256,
            "request_body_sha256": self.request_body_sha256,
            "output_text_sha256": self.output_text_sha256,
            "runtime_source_sha256": self.runtime_source_sha256,
            "route_binding_sha256": self.route_binding_sha256,
            "runtime_binding_commitment_sha256": self.runtime_binding_commitment_sha256,
            "usage": self.usage.commitment_payload(),
        }


_ISSUED_RECEIPTS: dict[int, tuple[ReferenceType[SafeRuntimeReceipt], str, int]] = {}


def require_verified_safe_receipt(receipt: SafeRuntimeReceipt) -> None:
    if type(receipt) is not SafeRuntimeReceipt or not receipt._is_authentic():
        raise ReceiptVerificationError("aggregation accepts only verifier-issued safe receipts")


def _remember_receipt(receipt: SafeRuntimeReceipt) -> None:
    identity = id(receipt)

    def discard(reference: ReferenceType[SafeRuntimeReceipt]) -> None:
        if (registered := _ISSUED_RECEIPTS.get(identity)) is not None and registered[
            0
        ] is reference:
            _ISSUED_RECEIPTS.pop(identity, None)

    reference = ref(receipt, discard)
    _ISSUED_RECEIPTS[identity] = (
        reference,
        _receipt_snapshot(receipt),
        id(receipt._runtime_binding),
    )


def _receipt_snapshot(receipt: SafeRuntimeReceipt) -> str:
    try:
        return sha256_bytes(canonical_json_bytes(receipt.commitment_payload()))
    except (AttributeError, TypeError, ValueError):
        return "invalid"


class RuntimeReceiptBoundaryPort(Protocol):
    def verify(
        self,
        *,
        receipt: Mapping[str, Any],
        secret: str,
        expectation: RuntimeReceiptExpectation,
        runtime_binding: TrustedRuntimeBinding,
        call_kind: RuntimeCallKind,
        sequence: int,
        operation_id_sha256: str,
    ) -> SafeRuntimeReceipt: ...


@dataclass(frozen=True, slots=True)
class RuntimeReceiptV2Boundary(RuntimeReceiptBoundaryPort):
    hmac_verifier: RuntimeReceiptVerifierPort

    def verify(
        self,
        *,
        receipt: Mapping[str, Any],
        secret: str,
        expectation: RuntimeReceiptExpectation,
        runtime_binding: TrustedRuntimeBinding,
        call_kind: RuntimeCallKind,
        sequence: int,
        operation_id_sha256: str,
    ) -> SafeRuntimeReceipt:
        if type(receipt) is not dict:
            raise ReceiptVerificationError("receipt must be a plain object")
        raw = dict(receipt)
        validate_receipt_shape(raw)
        parsed = _parse_receipt(raw)
        _require_nonnegative_int(sequence, "sequence")
        if type(call_kind) is not RuntimeCallKind:
            raise ReceiptVerificationError("call_kind must be a RuntimeCallKind")
        operation_hash = _sha256(operation_id_sha256, "operation_id_sha256")
        require_trusted_runtime_binding(runtime_binding)
        runtime_source = runtime_binding.runtime_source_sha256
        route_binding = runtime_binding.route_binding_sha256
        _verify_expectation(
            parsed,
            expectation,
            runtime_source_sha256=runtime_source,
            route_binding_sha256=route_binding,
        )
        # This delegates only the existing immutable canonical-byte/HMAC contract.
        self.hmac_verifier.verify(receipt=raw, secret=secret)
        identity_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "account_binding_hmac_sha256": parsed.account_binding_hmac_sha256,
                    "thread_id": parsed.thread_id,
                    "turn_id": parsed.turn_id,
                }
            )
        )
        return SafeRuntimeReceipt(
            schema_version=2,
            call_kind=call_kind,
            sequence=sequence,
            operation_id_sha256=operation_hash,
            receipt_sha256=sha256_bytes(canonical_json_bytes(raw)),
            identity_sha256=identity_sha256,
            request_body_sha256=parsed.request_body_sha256,
            output_text_sha256=parsed.output_text_sha256,
            runtime_source_sha256=runtime_source,
            route_binding_sha256=route_binding,
            runtime_binding_commitment_sha256=runtime_binding.commitment_sha256,
            usage=parsed.usage,
            runtime_binding=runtime_binding,
            _seal=_RECEIPT_SEAL,
        )


@dataclass(frozen=True, slots=True)
class _ParsedReceipt:
    model: str
    public_model: str
    client_requested_model: str
    configured_codex_model: str
    requested_codex_model: str
    reasoning_effort: str
    service_tier: str
    base_instructions_sha256: str
    account_binding_hmac_sha256: str
    thread_id: str
    turn_id: str
    request_body_sha256: str
    output_text_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int
    usage: ProviderObservedUsage


def _parse_receipt(receipt: dict[str, Any]) -> _ParsedReceipt:
    metadata = _plain_mapping(receipt["metadata"], "metadata")
    selection = _plain_mapping(metadata["runtime_selection"], "runtime_selection")
    request = _plain_mapping(metadata["request_identity"], "request_identity")
    output = _plain_mapping(metadata["output_identity"], "output_identity")
    limit = _plain_mapping(metadata["output_token_limit"], "output_token_limit")
    usage = _parse_usage(_plain_mapping(receipt["usage"], "usage"))
    _literal(metadata["schema_version"], 2, "schema_version")
    _literal(metadata["attestation_level"], "provider_receipt", "attestation_level")
    _literal(metadata["usage_source"], "codex_thread_token_usage_updated", "usage_source")
    _literal(selection["model_provider"], "openai", "model_provider")
    _literal(selection["execution_profile"], "stateless-completion", "execution_profile")
    _literal(output["terminal_status"], "completed", "terminal_status")
    _literal(limit["enforced"], False, "output_token_limit.enforced")
    _sha256(metadata["receipt_hmac_sha256"], "receipt_hmac_sha256")
    return _ParsedReceipt(
        model=_text(selection["model"], "model"),
        public_model=_text(request["public_model"], "public_model"),
        client_requested_model=_text(request["client_requested_model"], "client_requested_model"),
        configured_codex_model=_text(request["configured_codex_model"], "configured_codex_model"),
        requested_codex_model=_text(request["requested_codex_model"], "requested_codex_model"),
        reasoning_effort=_text(selection["reasoning_effort"], "reasoning_effort"),
        service_tier=_text(selection["service_tier"], "service_tier"),
        base_instructions_sha256=_sha256(
            selection["base_instructions_sha256"], "base_instructions_sha256"
        ),
        account_binding_hmac_sha256=_sha256(
            selection["account_binding_hmac_sha256"], "account_binding_hmac_sha256"
        ),
        thread_id=_text(selection["thread_id"], "thread_id"),
        turn_id=_text(selection["turn_id"], "turn_id"),
        request_body_sha256=_sha256(request["request_body_sha256"], "request_body_sha256"),
        output_text_sha256=_sha256(output["output_text_sha256"], "output_text_sha256"),
        response_format_type=_text(request["response_format_type"], "response_format_type"),
        response_format_sha256=_sha256(request["response_format_sha256"], "response_format_sha256"),
        response_schema_sha256=_sha256(request["response_schema_sha256"], "response_schema_sha256"),
        requested_output_tokens=_positive_int(
            limit["requested_tokens"], "output_token_limit.requested_tokens"
        ),
        usage=usage,
    )


def _parse_usage(value: dict[str, Any]) -> ProviderObservedUsage:
    prompt = _nonnegative_int(value["prompt_tokens"], "prompt_tokens")
    completion = _nonnegative_int(value["completion_tokens"], "completion_tokens")
    total = _positive_int(value["total_tokens"], "total_tokens")
    if total != prompt + completion:
        raise ReceiptVerificationError("total_tokens does not equal prompt plus completion")
    prompt_details = value.get("prompt_tokens_details")
    completion_details = value.get("completion_tokens_details")
    cached = cache_write = reasoning = None
    if prompt_details is not None:
        details = _plain_mapping(prompt_details, "prompt_tokens_details")
        cached = _nonnegative_int(details["cached_tokens"], "cached_tokens")
        if "cache_write_tokens" in details:
            cache_write = _nonnegative_int(details["cache_write_tokens"], "cache_write_tokens")
        if cached > prompt or (cache_write is not None and cache_write > prompt):
            raise ReceiptVerificationError("prompt token details exceed prompt_tokens")
    if completion_details is not None:
        details = _plain_mapping(completion_details, "completion_tokens_details")
        reasoning = _nonnegative_int(details["reasoning_tokens"], "reasoning_tokens")
        if reasoning > completion:
            raise ReceiptVerificationError("reasoning_tokens exceeds completion_tokens")
    return ProviderObservedUsage(prompt, completion, total, cached, cache_write, reasoning)


def _verify_expectation(
    receipt: _ParsedReceipt,
    expected: RuntimeReceiptExpectation,
    *,
    runtime_source_sha256: str,
    route_binding_sha256: str,
) -> None:
    checks = {
        "model": receipt.model == expected.model,
        "public_model": receipt.public_model == expected.model,
        "client_requested_model": receipt.client_requested_model == expected.model,
        "configured_codex_model": receipt.configured_codex_model == expected.model,
        "requested_codex_model": receipt.requested_codex_model == expected.model,
        "reasoning_effort": receipt.reasoning_effort == expected.reasoning_effort,
        "service_tier": receipt.service_tier == expected.service_tier,
        "base_instructions_sha256": receipt.base_instructions_sha256
        == _sha256(expected.base_instructions_sha256, "expected base instructions"),
        "runtime_source_sha256": runtime_source_sha256
        == _sha256(expected.runtime_source_sha256, "expected runtime source"),
        "route_binding_sha256": route_binding_sha256
        == _sha256(expected.route_binding_sha256, "expected route binding"),
        "account_binding_hmac_sha256": receipt.account_binding_hmac_sha256
        == _sha256(expected.account_binding_hmac_sha256, "expected account binding"),
        "thread_id": receipt.thread_id == expected.thread_id,
        "turn_id": receipt.turn_id == expected.turn_id,
        "request_body_sha256": receipt.request_body_sha256
        == _sha256(expected.request_body_sha256, "expected request body"),
        "output_text_sha256": receipt.output_text_sha256
        == _sha256(expected.output_text_sha256, "expected output text"),
        "response_format_type": receipt.response_format_type == expected.response_format_type,
        "response_format_sha256": receipt.response_format_sha256
        == _sha256(expected.response_format_sha256, "expected response format"),
        "response_schema_sha256": receipt.response_schema_sha256
        == _sha256(expected.response_schema_sha256, "expected response schema"),
        "requested_output_tokens": receipt.requested_output_tokens
        == _positive_int(expected.requested_output_tokens, "expected output tokens"),
    }
    failed = sorted(key for key, valid in checks.items() if not valid)
    if failed:
        raise ReceiptVerificationError(f"runtime receipt authority mismatch: {failed}")


def _plain_mapping(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReceiptVerificationError(f"{label} must be a plain object")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise ReceiptVerificationError(f"{label} must be bounded non-empty text")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ReceiptVerificationError(f"{label} must be a lowercase sha256")
    return text


def _literal(value: Any, expected: object, label: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ReceiptVerificationError(f"{label} has an invalid value")


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ReceiptVerificationError(f"{label} must be a non-negative integer")
    return value


def _require_nonnegative_int(value: Any, label: str) -> None:
    _nonnegative_int(value, label)


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ReceiptVerificationError(f"{label} must be positive")
    return result
