"""Nonpublishable loopback bridge for subscription-backed chat completions.

The adapter sends max_tokens as a request hint. It cannot prove that the
subscription runtime enforced the requested output limit, so it deliberately
returns no publishable per-call provenance.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import threading
from collections.abc import Mapping, Sequence
from math import isfinite
from urllib.parse import urlsplit

import httpx

from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderChatCompletion,
    ProviderRouteAttestation,
)

DEFAULT_SUBSCRIPTION_RUNTIME_ORIGIN = "http://127.0.0.1:8890"
SUBSCRIPTION_CHAT_ENDPOINT_PATH = "/v1/chat/completions"
SUBSCRIPTION_RUNTIME_TRUST = "codex_subscription_runtime"
SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE = "subscription-runtime-openai-codex-bridge.v1"
SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE = "requested_not_provider_verified"
MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_RESPONSE_BODY_BYTES = 1_048_576

_SAFE_FINISH_REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


class SubscriptionChatError(RuntimeError):
    """Base error exposing only a stable code, never response or secret data."""

    code = "subscription_chat_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubscriptionChatClosedError(SubscriptionChatError):
    code = "subscription_chat_closed"


class SubscriptionChatRequestError(SubscriptionChatError):
    code = "subscription_chat_request_failed"


class SubscriptionChatHTTPError(SubscriptionChatError):
    code = "subscription_chat_http_error"

    def __init__(self, status_code: int) -> None:
        self.status_code = int(status_code)
        super().__init__()


class SubscriptionChatRequestTooLargeError(SubscriptionChatError, ValueError):
    code = "subscription_chat_request_too_large"


class SubscriptionChatResponseTooLargeError(SubscriptionChatError):
    code = "subscription_chat_response_too_large"


class SubscriptionChatMalformedResponseError(SubscriptionChatError):
    code = "subscription_chat_malformed_response"


class SubscriptionRuntimeChatCompletions:
    """Provider-chat adapter for an already-running local subscription bridge."""

    __slots__ = (
        "_authorization",
        "_client",
        "_closed",
        "_credential_binding_id",
        "_endpoint",
        "_last_response_status",
        "_max_retries",
        "_origin",
    )

    def __init__(
        self,
        *,
        origin: str = DEFAULT_SUBSCRIPTION_RUNTIME_ORIGIN,
        bearer_token: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized_origin = _validated_loopback_origin(origin)
        timeout = _bounded_timeout(timeout_seconds)
        retries = _bounded_retries(max_retries)
        if bearer_token is not None and type(bearer_token) is not str:
            raise ValueError("subscription chat bearer token must be a string")
        token = None if bearer_token is None else str(bearer_token).strip()
        if bearer_token is not None and not token:
            raise ValueError("subscription chat bearer token must not be empty")

        self._origin = normalized_origin
        self._endpoint = f"{normalized_origin}{SUBSCRIPTION_CHAT_ENDPOINT_PATH}"
        self._authorization = f"Bearer {token}" if token is not None else None
        self._credential_binding_id = (
            f"sha256:{hashlib.sha256(token.encode()).hexdigest()}" if token is not None else None
        )
        self._max_retries = retries
        self._last_response_status = 0
        self._closed = threading.Event()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(origin={self._origin!r}, "
            f"credential_bound={self._credential_binding_id is not None})"
        )

    @property
    def route_attestation(self) -> ProviderRouteAttestation:
        """Return nonpublishable route facts, including the last HTTP status."""

        return ProviderRouteAttestation(
            trust=SUBSCRIPTION_RUNTIME_TRUST,
            origin=self._origin,
            endpoint_path=SUBSCRIPTION_CHAT_ENDPOINT_PATH,
            route_sha256=hashlib.sha256(self._endpoint.encode()).hexdigest(),
            transport_evidence=SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
            credential_binding_id=self._credential_binding_id,
            request_method="POST",
            response_status=self._last_response_status,
        )

    @property
    def output_limit_evidence(self) -> str:
        """State explicitly that runtime-side max_tokens enforcement is unknown."""

        return SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> ProviderChatCompletion:
        if self._closed.is_set():
            raise SubscriptionChatClosedError
        payload = _request_payload(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if len(body) > MAX_REQUEST_BODY_BYTES:
            raise SubscriptionChatRequestTooLargeError

        response_payload = self._post(body)
        return _parse_completion(
            response_payload,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def close(self) -> None:
        if not self._closed.is_set():
            self._closed.set()
            self._client.close()

    def _post(self, body: bytes) -> object:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        if self._authorization is not None:
            headers["Authorization"] = self._authorization

        for attempt in range(self._max_retries + 1):
            if self._closed.is_set():
                raise SubscriptionChatClosedError
            try:
                with self._client.stream(
                    "POST",
                    self._endpoint,
                    headers=headers,
                    content=body,
                ) as response:
                    self._last_response_status = response.status_code
                    retry = _retryable_status(response.status_code) and attempt < self._max_retries
                    if retry:
                        continue
                    if response.status_code != 200:
                        raise SubscriptionChatHTTPError(response.status_code)
                    response_body = _read_bounded_json_response(response)
            except SubscriptionChatError:
                raise
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise SubscriptionChatRequestError from None
                continue
            try:
                return json.loads(response_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise SubscriptionChatMalformedResponseError from None
        raise AssertionError("subscription chat retry loop exhausted")


def _validated_loopback_origin(raw_origin: str) -> str:
    raw = str(raw_origin or "").strip()
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        address = ipaddress.ip_address(host)
        port = parsed.port
    except ValueError:
        raise ValueError("subscription chat origin must be a loopback URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not address.is_loopback
        or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("subscription chat origin must be a loopback URL")
    normalized_host = address.compressed
    if address.version == 6:
        normalized_host = f"[{normalized_host}]"
    port_suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{normalized_host}{port_suffix}"


def _bounded_timeout(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("subscription chat timeout must be between 0 and 180 seconds")
    timeout = float(value)
    if not isfinite(timeout) or not 0 < timeout <= 180:
        raise ValueError("subscription chat timeout must be between 0 and 180 seconds")
    return timeout


def _bounded_retries(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ValueError("subscription chat retries must be disabled for exact call budgets")
    return value


def _request_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float | None,
    response_format: Mapping[str, object] | None,
) -> dict[str, object]:
    normalized_model = str(model or "").strip()
    if not normalized_model or len(normalized_model) > 200:
        raise ValueError("subscription chat model is invalid")
    if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
        raise TypeError("subscription chat prompts must be strings")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 1 <= max_output_tokens <= 1_000_000
    ):
        raise ValueError("subscription chat max output tokens is invalid")
    if temperature is not None:
        if isinstance(temperature, bool):
            raise ValueError("subscription chat temperature must be zero or omitted")
        normalized_temperature = float(temperature)
        if not isfinite(normalized_temperature) or normalized_temperature != 0:
            raise ValueError("subscription chat temperature must be zero or omitted")
    if response_format is not None and dict(response_format) != {"type": "json_object"}:
        raise ValueError("subscription chat response format is unsupported")

    payload: dict[str, object] = {
        "model": normalized_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_output_tokens,
    }
    if temperature is not None:
        payload["temperature"] = 0
    if response_format is not None:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _read_bounded_json_response(response: httpx.Response) -> bytes:
    encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    if encoding not in {"", "identity"}:
        raise SubscriptionChatMalformedResponseError
    content_type = response.headers.get("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if media_type != "application/json":
        raise SubscriptionChatMalformedResponseError
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            content_length = int(raw_length)
        except ValueError:
            raise SubscriptionChatMalformedResponseError from None
        if content_length < 0 or content_length > MAX_RESPONSE_BODY_BYTES:
            raise SubscriptionChatResponseTooLargeError
    if response.is_stream_consumed:
        buffered = response.content
        if len(buffered) > MAX_RESPONSE_BODY_BYTES:
            raise SubscriptionChatResponseTooLargeError
        return buffered

    body = bytearray()
    for chunk in response.iter_raw():
        if len(body) + len(chunk) > MAX_RESPONSE_BODY_BYTES:
            raise SubscriptionChatResponseTooLargeError
        body.extend(chunk)
    return bytes(body)


def _parse_completion(
    payload: object,
    *,
    system_prompt: str,
    user_prompt: str,
) -> ProviderChatCompletion:
    if not isinstance(payload, Mapping):
        raise SubscriptionChatMalformedResponseError
    choices = payload.get("choices")
    first = (
        choices[0]
        if isinstance(choices, Sequence) and not isinstance(choices, str | bytes) and choices
        else None
    )
    message = first.get("message") if isinstance(first, Mapping) else None
    text = message.get("content") if isinstance(message, Mapping) else None
    if (
        not isinstance(first, Mapping)
        or not isinstance(message, Mapping)
        or message.get("role") != "assistant"
        or not isinstance(text, str)
    ):
        raise SubscriptionChatMalformedResponseError

    prompt_tokens, completion_tokens, usage_source = _usage(
        payload.get("usage"),
        prompt_text=f"{system_prompt}\n{user_prompt}",
        completion_text=text,
    )
    raw_finish_reason = first.get("finish_reason")
    finish_reason = (
        raw_finish_reason
        if isinstance(raw_finish_reason, str)
        and _SAFE_FINISH_REASON_RE.fullmatch(raw_finish_reason)
        else ""
    )
    return ProviderChatCompletion(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        token_usage_source=usage_source,
        finish_reason=finish_reason,
        finish_reason_source="provider_observed" if finish_reason else "",
        provenance=None,
    )


def _usage(
    raw_usage: object,
    *,
    prompt_text: str,
    completion_text: str,
) -> tuple[int, int, str]:
    if isinstance(raw_usage, Mapping):
        prompt_tokens = raw_usage.get("prompt_tokens")
        completion_tokens = raw_usage.get("completion_tokens")
        if _is_token_count(prompt_tokens) and _is_token_count(completion_tokens):
            return prompt_tokens, completion_tokens, "provider_observed"
    return (
        _estimated_tokens(prompt_text),
        _estimated_tokens(completion_text),
        "estimated_by_subscription_adapter",
    )


def _is_token_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _estimated_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES or status_code >= 500


__all__ = (
    "DEFAULT_SUBSCRIPTION_RUNTIME_ORIGIN",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BODY_BYTES",
    "SUBSCRIPTION_CHAT_ENDPOINT_PATH",
    "SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE",
    "SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE",
    "SUBSCRIPTION_RUNTIME_TRUST",
    "SubscriptionChatClosedError",
    "SubscriptionChatError",
    "SubscriptionChatHTTPError",
    "SubscriptionChatMalformedResponseError",
    "SubscriptionChatRequestError",
    "SubscriptionChatRequestTooLargeError",
    "SubscriptionChatResponseTooLargeError",
    "SubscriptionRuntimeChatCompletions",
)
