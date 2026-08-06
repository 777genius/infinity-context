"""Retry-free loopback client for immutable subscription-runtime receipt v2."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any, Protocol
from weakref import ReferenceType, ref

import httpx

from .domain import (
    AdapterContractError,
    OperationDispatchIntent,
    RuntimeCallDisposition,
    RuntimeCallOutcome,
    RuntimeExtractionResult,
    _issue_sanitized_runtime_receipt,
    canonical_json_bytes,
    require_authentic_runtime_result,
    require_sha256,
    snapshot_authentic_dispatch_intent,
)
from .extraction_contract import (
    EXTRACTION_MODEL,
    EXTRACTION_RESPONSE_FORMAT_SHA256,
    EXTRACTION_SCHEMA_SHA256,
    ExtractionRequest,
    parse_extraction_output,
    snapshot_authentic_extraction_request,
)

SUBSCRIPTION_RUNTIME_ORIGIN = "http://127.0.0.1:8890"
SUBSCRIPTION_RUNTIME_ENDPOINT = f"{SUBSCRIPTION_RUNTIME_ORIGIN}/v1/chat/completions"
SUBSCRIPTION_RUNTIME_ROUTE_BINDING = "http://127.0.0.1:8890/v1"
SUBSCRIPTION_RUNTIME_ROUTE_SHA256 = hashlib.sha256(
    SUBSCRIPTION_RUNTIME_ROUTE_BINDING.encode("utf-8")
).hexdigest()
MAX_RUNTIME_RESPONSE_BYTES = 1_048_576
MAX_PROVIDER_TOKENS = 1_000_000

_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_AUTHORITIES: dict[int, tuple[ReferenceType[object], tuple[object, ...]]] = {}


class SubscriptionRuntimeError(RuntimeError):
    """Sanitized error carrying the only safe crash-recovery decision."""

    def __init__(
        self,
        code: str,
        *,
        outcome: RuntimeCallOutcome | None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.outcome = outcome
        self.status_code = status_code
        super().__init__(code)


class RuntimeReceiptV2BoundaryPort(Protocol):
    def verify(self, **kwargs: object) -> object: ...


class EstablishedReceiptV2Authority:
    """Narrow capability over the established Phase C receipt-v2 verifier."""

    __slots__ = (
        "__weakref__",
        "_boundary",
        "_receipt_secret",
        "_runtime_binding",
        "_runtime_source_sha256",
    )

    def __init__(
        self,
        *,
        boundary: RuntimeReceiptV2BoundaryPort,
        runtime_binding: object,
        receipt_secret: str,
        runtime_source_sha256: str,
    ) -> None:
        if not callable(getattr(boundary, "verify", None)):
            raise AdapterContractError("mem0_v5_receipt_authority_invalid")
        if (
            type(receipt_secret) is not str
            or len(receipt_secret.encode("utf-8")) < 32
            or receipt_secret != receipt_secret.strip()
        ):
            raise AdapterContractError("mem0_v5_receipt_authority_invalid")
        require_sha256(runtime_source_sha256, "mem0_v5_receipt_authority_invalid")
        self._boundary = boundary
        self._runtime_binding = runtime_binding
        self._receipt_secret = receipt_secret
        self._runtime_source_sha256 = runtime_source_sha256
        _register_authority(self)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(runtime_source_sha256="
            f"{self._runtime_source_sha256!r}, secret_bound=True)"
        )

    def verify(
        self,
        *,
        receipt: dict[str, object],
        intent: OperationDispatchIntent,
        request: ExtractionRequest,
        expected_account_binding_hmac_sha256: str,
        expected_base_instructions_sha256: str,
        reasoning_effort: str,
        service_tier: str,
    ) -> str:
        """Return the established verifier's authenticated canonical receipt hash."""

        try:
            _require_authority(self)
            from phase_c_canary.runtime_receipt_v2 import (
                RuntimeCallKind,
                RuntimeReceiptExpectation,
                require_verified_safe_receipt,
            )

            metadata = receipt["metadata"]
            selection = metadata["runtime_selection"]
            identity = metadata["request_identity"]
            output = metadata["output_identity"]
            safe = self._boundary.verify(
                receipt=receipt,
                secret=self._receipt_secret,
                expectation=RuntimeReceiptExpectation(
                    model=EXTRACTION_MODEL,
                    reasoning_effort=reasoning_effort,
                    service_tier=service_tier,
                    base_instructions_sha256=expected_base_instructions_sha256,
                    runtime_source_sha256=self._runtime_source_sha256,
                    route_binding_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
                    account_binding_hmac_sha256=expected_account_binding_hmac_sha256,
                    thread_id=selection["thread_id"],
                    turn_id=selection["turn_id"],
                    request_body_sha256=request.request_body_sha256,
                    output_text_sha256=output["output_text_sha256"],
                    response_format_type="json_schema",
                    response_format_sha256=EXTRACTION_RESPONSE_FORMAT_SHA256,
                    response_schema_sha256=EXTRACTION_SCHEMA_SHA256,
                    requested_output_tokens=request.max_tokens,
                ),
                runtime_binding=self._runtime_binding,
                call_kind=RuntimeCallKind.EXTRACTION,
                sequence=intent.sequence,
                operation_id_sha256=intent.operation_id_sha256,
            )
            require_verified_safe_receipt(safe)
            canonical_receipt_sha256 = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            if (
                safe.receipt_sha256 != canonical_receipt_sha256
                or safe.request_body_sha256 != identity["request_body_sha256"]
                or safe.output_text_sha256 != output["output_text_sha256"]
                or safe.runtime_source_sha256 != self._runtime_source_sha256
                or safe.route_binding_sha256 != SUBSCRIPTION_RUNTIME_ROUTE_SHA256
            ):
                raise AdapterContractError("mem0_v5_receipt_authority_mismatch")
            return safe.receipt_sha256
        except Exception:
            raise AdapterContractError("mem0_v5_receipt_unauthenticated") from None


class SubscriptionRuntimeClient:
    """One-attempt HTTP adapter with no redirects, proxies, retries, or secret output."""

    __slots__ = (
        "_authorization",
        "_client",
        "_closed",
        "_consumed_operations",
        "_expected_account_binding_hmac_sha256",
        "_expected_base_instructions_sha256",
        "_lock",
        "_reasoning_effort",
        "_receipt_authority",
        "_service_tier",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        origin: str,
        bearer_token: str,
        expected_account_binding_hmac_sha256: str,
        expected_base_instructions_sha256: str,
        receipt_authority: EstablishedReceiptV2Authority,
        reasoning_effort: str = "high",
        service_tier: str = "default",
        timeout_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if origin != SUBSCRIPTION_RUNTIME_ORIGIN:
            raise AdapterContractError("mem0_v5_subscription_route_invalid")
        if (
            type(bearer_token) is not str
            or not bearer_token
            or bearer_token != bearer_token.strip()
            or len(bearer_token.encode("utf-8")) > 8192
        ):
            raise AdapterContractError("mem0_v5_subscription_credential_invalid")
        require_sha256(
            expected_account_binding_hmac_sha256,
            "mem0_v5_subscription_authority_invalid",
        )
        require_sha256(
            expected_base_instructions_sha256,
            "mem0_v5_subscription_authority_invalid",
        )
        if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise AdapterContractError("mem0_v5_subscription_authority_invalid")
        if type(service_tier) is not str or _SAFE_TEXT.fullmatch(service_tier) is None:
            raise AdapterContractError("mem0_v5_subscription_authority_invalid")
        if isinstance(timeout_seconds, bool):
            raise AdapterContractError("mem0_v5_subscription_timeout_invalid")
        timeout = float(timeout_seconds)
        if not 0 < timeout <= 180:
            raise AdapterContractError("mem0_v5_subscription_timeout_invalid")
        if type(receipt_authority) is not EstablishedReceiptV2Authority:
            raise AdapterContractError("mem0_v5_receipt_authority_invalid")

        self._authorization = f"Bearer {bearer_token}"
        self._expected_account_binding_hmac_sha256 = expected_account_binding_hmac_sha256
        self._expected_base_instructions_sha256 = expected_base_instructions_sha256
        self._reasoning_effort = reasoning_effort
        self._receipt_authority = receipt_authority
        self._service_tier = service_tier
        self._timeout_seconds = timeout
        self._closed = False
        self._consumed_operations: set[str] = set()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(origin={SUBSCRIPTION_RUNTIME_ORIGIN!r}, "
            f"credential_bound=True, timeout_seconds={self._timeout_seconds!r})"
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._client.close()

    def extract(
        self,
        request: ExtractionRequest,
        intent: OperationDispatchIntent,
    ) -> RuntimeExtractionResult:
        try:
            request_snapshot = snapshot_authentic_extraction_request(request)
            intent_snapshot = snapshot_authentic_dispatch_intent(intent)
            receipt_authority = _require_authority(self._receipt_authority)
            authorization = self._authorization
            expected_account_binding = self._expected_account_binding_hmac_sha256
            expected_base_instructions = self._expected_base_instructions_sha256
            reasoning_effort = self._reasoning_effort
            service_tier = self._service_tier
        except AdapterContractError:
            raise SubscriptionRuntimeError(
                "mem0_v5_subscription_request_invalid",
                outcome=None,
            ) from None
        if intent_snapshot.request_body_sha256 != request_snapshot.request_body_sha256:
            raise self._error(
                "mem0_v5_subscription_request_binding_invalid",
                intent=intent_snapshot,
                attempted=False,
            )
        with self._lock:
            if self._closed:
                raise self._error(
                    "mem0_v5_subscription_client_closed",
                    intent=intent_snapshot,
                    attempted=False,
                )
            if intent_snapshot.operation_id_sha256 in self._consumed_operations:
                raise self._error(
                    "mem0_v5_subscription_operation_consumed",
                    intent=intent_snapshot,
                    attempted=False,
                )
            # Burn the operation before transport. A process crash can only recover
            # through durable status evidence, never a blind second provider call.
            self._consumed_operations.add(intent_snapshot.operation_id_sha256)

        try:
            response_payload = self._post_once(
                request_snapshot.body,
                intent=intent_snapshot,
                authorization=authorization,
            )
            output_text, receipt_payload = self._validate_response(
                response_payload,
                request_snapshot,
            )
            verified_receipt_sha256 = receipt_authority.verify(
                receipt=receipt_payload,
                intent=intent_snapshot,
                request=request_snapshot,
                expected_account_binding_hmac_sha256=(expected_account_binding),
                expected_base_instructions_sha256=expected_base_instructions,
                reasoning_effort=reasoning_effort,
                service_tier=service_tier,
            )
            memories = parse_extraction_output(
                output_text,
                allowed_existing_memory_ids=request_snapshot.allowed_existing_memory_ids,
            )
            output_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
            receipt = _issue_sanitized_runtime_receipt(
                receipt_payload,
                verified_receipt_sha256=verified_receipt_sha256,
            )
            result = RuntimeExtractionResult(
                intent=intent_snapshot,
                memories=memories,
                receipt=receipt,
                output_text_sha256=output_sha256,
            )
            return require_authentic_runtime_result(result)
        except SubscriptionRuntimeError:
            raise
        except (AdapterContractError, TypeError, ValueError):
            raise self._error(
                "mem0_v5_subscription_response_invalid",
                intent=intent_snapshot,
                attempted=True,
            ) from None

    def _post_once(
        self,
        body: bytes,
        *,
        intent: OperationDispatchIntent,
        authorization: str,
    ) -> object:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": authorization,
            "Content-Type": "application/json",
        }
        try:
            with self._client.stream(
                "POST",
                SUBSCRIPTION_RUNTIME_ENDPOINT,
                headers=headers,
                content=body,
            ) as response:
                if response.status_code != 200:
                    # Never follow redirects or infer that an error response means
                    # the provider was not reached.
                    raise _AttemptedHTTPError(response.status_code)
                raw = _read_bounded_json_response(response)
        except _AttemptedHTTPError as exc:
            error = self._error(
                "mem0_v5_subscription_http_failed",
                intent=intent,
                attempted=True,
            )
            error.status_code = exc.status_code
            raise error from None
        except AdapterContractError:
            raise
        except httpx.HTTPError:
            raise self._error(
                "mem0_v5_subscription_transport_failed",
                intent=intent,
                attempted=True,
            ) from None
        except Exception:
            raise self._error(
                "mem0_v5_subscription_transport_failed",
                intent=intent,
                attempted=True,
            ) from None
        try:
            return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterContractError("mem0_v5_subscription_response_invalid") from None

    def _validate_response(
        self,
        payload: object,
        request: ExtractionRequest,
    ) -> tuple[str, dict[str, object]]:
        root = _exact_object(
            payload,
            {
                "id",
                "object",
                "created",
                "model",
                "choices",
                "usage",
                "system_fingerprint",
                "subscription_runtime",
            },
        )
        if (
            root["object"] != "chat.completion"
            or root["model"] != EXTRACTION_MODEL
            or type(root["created"]) is not int
            or root["created"] < 0
            or _safe_text(root["id"]) is None
            or _safe_text(root["system_fingerprint"]) is None
        ):
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        choices = root["choices"]
        if type(choices) is not list or len(choices) != 1:
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        choice = _exact_object(choices[0], {"index", "message", "finish_reason"})
        message = _exact_object(choice["message"], {"role", "content"})
        if (
            choice["index"] != 0
            or choice["finish_reason"] != "stop"
            or message["role"] != "assistant"
            or type(message["content"]) is not str
        ):
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        output_text = message["content"]
        usage = _validate_usage(root["usage"])
        metadata = self._validate_metadata(
            root["subscription_runtime"],
            request=request,
            output_text=output_text,
        )
        return output_text, {"metadata": metadata, "usage": usage}

    def _validate_metadata(
        self,
        raw: object,
        *,
        request: ExtractionRequest,
        output_text: str,
    ) -> dict[str, object]:
        metadata = _exact_object(
            raw,
            {
                "schema_version",
                "attestation_level",
                "usage_source",
                "runtime_selection",
                "request_identity",
                "output_identity",
                "output_token_limit",
                "receipt_hmac_sha256",
            },
        )
        selection = _exact_object(
            metadata["runtime_selection"],
            {
                "account_binding_hmac_sha256",
                "thread_id",
                "turn_id",
                "model",
                "model_provider",
                "reasoning_effort",
                "service_tier",
                "execution_profile",
                "base_instructions_sha256",
            },
        )
        identity = _exact_object(
            metadata["request_identity"],
            {
                "public_model",
                "client_requested_model",
                "configured_codex_model",
                "requested_codex_model",
                "request_body_sha256",
                "response_format_type",
                "response_format_sha256",
                "response_schema_sha256",
            },
        )
        output = _exact_object(
            metadata["output_identity"],
            {"output_text_sha256", "terminal_status"},
        )
        limit = _exact_object(metadata["output_token_limit"], {"requested_tokens", "enforced"})
        for digest in (
            metadata["receipt_hmac_sha256"],
            selection["account_binding_hmac_sha256"],
            selection["base_instructions_sha256"],
            identity["request_body_sha256"],
            identity["response_format_sha256"],
            identity["response_schema_sha256"],
            output["output_text_sha256"],
        ):
            require_sha256(digest, "mem0_v5_subscription_response_invalid")
        expected_output_sha = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
        if (
            metadata["schema_version"] != 2
            or metadata["attestation_level"] != "provider_receipt"
            or metadata["usage_source"] != "codex_thread_token_usage_updated"
            or selection["account_binding_hmac_sha256"]
            != self._expected_account_binding_hmac_sha256
            or selection["model"] != EXTRACTION_MODEL
            or selection["model_provider"] != "openai"
            or selection["reasoning_effort"] != self._reasoning_effort
            or selection["service_tier"] != self._service_tier
            or selection["execution_profile"] != "stateless-completion"
            or selection["base_instructions_sha256"] != self._expected_base_instructions_sha256
            or _safe_text(selection["thread_id"]) is None
            or _safe_text(selection["turn_id"]) is None
            or any(
                identity[key] != EXTRACTION_MODEL
                for key in (
                    "public_model",
                    "client_requested_model",
                    "configured_codex_model",
                    "requested_codex_model",
                )
            )
            or identity["request_body_sha256"] != request.request_body_sha256
            or identity["response_format_type"] != "json_schema"
            or identity["response_format_sha256"] != EXTRACTION_RESPONSE_FORMAT_SHA256
            or identity["response_schema_sha256"] != EXTRACTION_SCHEMA_SHA256
            or output["output_text_sha256"] != expected_output_sha
            or output["terminal_status"] != "completed"
            or limit["requested_tokens"] != request.max_tokens
            or limit["enforced"] is not False
        ):
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        return metadata

    @staticmethod
    def _error(
        code: str,
        *,
        intent: OperationDispatchIntent,
        attempted: bool,
    ) -> SubscriptionRuntimeError:
        return SubscriptionRuntimeError(
            code,
            outcome=RuntimeCallOutcome(
                intent=intent,
                disposition=(
                    RuntimeCallDisposition.OUTCOME_UNKNOWN
                    if attempted
                    else RuntimeCallDisposition.NOT_DISPATCHED
                ),
            ),
        )


class _AttemptedHTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = int(status_code)


def _read_bounded_json_response(response: httpx.Response) -> bytes:
    encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
    if encoding not in {"", "identity"} or media_type != "application/json":
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            length = int(raw_length)
        except ValueError:
            raise AdapterContractError("mem0_v5_subscription_response_invalid") from None
        if not 0 <= length <= MAX_RUNTIME_RESPONSE_BYTES:
            raise AdapterContractError("mem0_v5_subscription_response_too_large")
    if response.is_stream_consumed:
        buffered = response.content
        if len(buffered) > MAX_RUNTIME_RESPONSE_BYTES:
            raise AdapterContractError("mem0_v5_subscription_response_too_large")
        return buffered
    body = bytearray()
    for chunk in response.iter_raw():
        if len(body) + len(chunk) > MAX_RUNTIME_RESPONSE_BYTES:
            raise AdapterContractError("mem0_v5_subscription_response_too_large")
        body.extend(chunk)
    return bytes(body)


def _exact_object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    return value


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        result[key] = value
    return result


def _safe_text(value: object) -> str | None:
    return value if type(value) is str and _SAFE_TEXT.fullmatch(value) is not None else None


def _validate_usage(raw: object) -> dict[str, object]:
    if type(raw) is not dict:
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    required = {"prompt_tokens", "completion_tokens", "total_tokens"}
    optional = {"prompt_tokens_details", "completion_tokens_details"}
    if not required <= set(raw) <= required | optional:
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    prompt = _bounded_token(raw["prompt_tokens"])
    completion = _bounded_token(raw["completion_tokens"])
    total = _bounded_token(raw["total_tokens"])
    if total != prompt + completion:
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    if "prompt_tokens_details" in raw:
        raw_details = raw["prompt_tokens_details"]
        if type(raw_details) is not dict or set(raw_details) not in (
            {"cached_tokens"},
            {"cached_tokens", "cache_write_tokens"},
        ):
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
        details = raw_details
        if _bounded_token(details["cached_tokens"]) > prompt or (
            "cache_write_tokens" in details
            and _bounded_token(details["cache_write_tokens"]) > prompt
        ):
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
    if "completion_tokens_details" in raw:
        details = _exact_object(raw["completion_tokens_details"], {"reasoning_tokens"})
        if _bounded_token(details["reasoning_tokens"]) > completion:
            raise AdapterContractError("mem0_v5_subscription_response_invalid")
    return raw


def _bounded_token(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_PROVIDER_TOKENS:
        raise AdapterContractError("mem0_v5_subscription_response_invalid")
    return value


def _authority_snapshot(value: EstablishedReceiptV2Authority) -> tuple[object, ...]:
    return (
        id(value._boundary),
        id(value._runtime_binding),
        hashlib.sha256(value._receipt_secret.encode("utf-8")).hexdigest(),
        value._runtime_source_sha256,
    )


def _register_authority(value: EstablishedReceiptV2Authority) -> None:
    identity = id(value)

    def discard(reference: ReferenceType[object]) -> None:
        current = _AUTHORITIES.get(identity)
        if current is not None and current[0] is reference:
            _AUTHORITIES.pop(identity, None)

    reference = ref(value, discard)
    _AUTHORITIES[identity] = (reference, _authority_snapshot(value))


def _require_authority(value: object) -> EstablishedReceiptV2Authority:
    if type(value) is not EstablishedReceiptV2Authority:
        raise AdapterContractError("mem0_v5_receipt_authority_unauthentic")
    try:
        snapshot = _authority_snapshot(value)
    except (AttributeError, TypeError, ValueError):
        raise AdapterContractError("mem0_v5_receipt_authority_unauthentic") from None
    registered = _AUTHORITIES.get(id(value))
    if registered is None or registered[0]() is not value or registered[1] != snapshot:
        raise AdapterContractError("mem0_v5_receipt_authority_unauthentic")
    return value


__all__ = [
    "MAX_RUNTIME_RESPONSE_BYTES",
    "SUBSCRIPTION_RUNTIME_ENDPOINT",
    "SUBSCRIPTION_RUNTIME_ORIGIN",
    "SUBSCRIPTION_RUNTIME_ROUTE_SHA256",
    "EstablishedReceiptV2Authority",
    "SubscriptionRuntimeClient",
    "SubscriptionRuntimeError",
]
