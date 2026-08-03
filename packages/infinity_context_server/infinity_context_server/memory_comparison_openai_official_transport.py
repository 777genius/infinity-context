"""Bounded fixed-origin HTTP transport for official OpenAI benchmark calls."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from urllib.parse import urlsplit

import httpx

from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

APPROVED_OPENAI_ORIGIN = "https://api.openai.com"
APPROVED_OPENAI_ENDPOINT_PATH = "/v1/chat/completions"
TRUST_OFFICIAL_OPENAI = "official_openai"
TRUST_DIAGNOSTIC_UNTRUSTED = "diagnostic_untrusted"
OFFICIAL_OPENAI_ROUTE_POLICY_ID = "official-openai-chat-completions.v1"
_DIRECT_TRANSPORT_EVIDENCE = "httpx-direct-tls-no-env-v1"
_DIAGNOSTIC_TRANSPORT_EVIDENCE = "injected-diagnostic-transport"
_OFFICIAL_ENDPOINT = f"{APPROVED_OPENAI_ORIGIN}{APPROVED_OPENAI_ENDPOINT_PATH}"
_OFFICIAL_ROUTE_SHA256 = hashlib.sha256(_OFFICIAL_ENDPOINT.encode()).hexdigest()
_MAX_REQUEST_BODY_BYTES = 1_048_576
_MAX_RESPONSE_BODY_BYTES = 1_048_576
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
_OPENAI_KEY_RE = re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")
_OPENAI_RESPONSE_ID_RE = re.compile(r"^chatcmpl-[A-Za-z0-9_-]{8,128}$")
_OPENAI_FINGERPRINT_RE = re.compile(r"^fp_[0-9a-f]{8,64}$")
_SHA256_BINDING_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class OfficialOpenAITransportError(RuntimeError):
    """Safe base error for official OpenAI transport failures."""


class OfficialOpenAIRequestError(OfficialOpenAITransportError):
    """Raised when the official endpoint cannot be reached."""


class OfficialOpenAIDeadlineError(OfficialOpenAIRequestError):
    """Raised when the absolute operation deadline expires."""


class OfficialOpenAICancelledError(OfficialOpenAIRequestError):
    """Raised when close cancels an in-flight operation."""


class OfficialOpenAIHTTPError(OfficialOpenAITransportError):
    """Non-success response that deliberately excludes headers and body."""

    def __init__(self, status_code: int) -> None:
        self.status_code = int(status_code)
        super().__init__(f"official OpenAI request failed with HTTP {self.status_code}")


class OfficialOpenAIMalformedResponseError(OfficialOpenAITransportError):
    """Raised when official provider output is structurally unsafe."""


class OfficialOpenAIResponseTooLargeError(OfficialOpenAIMalformedResponseError):
    """Raised before a provider response can exceed the hard body cap."""


class OfficialOpenAIUnsafeEncodingError(OfficialOpenAIMalformedResponseError):
    """Raised for encoded responses whose decoded size cannot be bounded safely."""


class OfficialOpenAIRequestTooLargeError(OfficialOpenAITransportError, ValueError):
    """Raised before HTTP when a request exceeds the hard body cap."""


@dataclass(frozen=True, slots=True)
class OfficialOpenAIRoutePolicy:
    """Strict OpenAI-specific route and response evidence policy."""

    policy_id: str = OFFICIAL_OPENAI_ROUTE_POLICY_ID

    def call_issues(
        self,
        provenance: Mapping[str, object],
        *,
        required_model: str,
    ) -> Sequence[str]:
        issues: list[str] = []
        if (
            provenance.get("trust") != TRUST_OFFICIAL_OPENAI
            or provenance.get("origin") != APPROVED_OPENAI_ORIGIN
            or provenance.get("endpoint_path") != APPROVED_OPENAI_ENDPOINT_PATH
            or provenance.get("route_sha256") != _OFFICIAL_ROUTE_SHA256
            or provenance.get("transport_evidence") != _DIRECT_TRANSPORT_EVIDENCE
            or provenance.get("request_method") != "POST"
        ):
            issues.append("route")
        status = provenance.get("response_status")
        if status != 200 or isinstance(status, bool):
            issues.append("response_status")
        if not _SHA256_BINDING_RE.fullmatch(
            str(provenance.get("credential_binding_id") or "")
        ):
            issues.append("credential_binding_shape")
        if provenance.get("requested_model") != required_model:
            issues.append("requested_model_shape")
        if provenance.get("observed_model") != required_model:
            issues.append("observed_model_shape")
        if not _OPENAI_RESPONSE_ID_RE.fullmatch(str(provenance.get("response_id") or "")):
            issues.append("response_id_shape")
        if not _OPENAI_FINGERPRINT_RE.fullmatch(
            str(provenance.get("system_fingerprint") or "")
        ):
            issues.append("system_fingerprint_shape")
        return tuple(issues)

    def public_summary(self) -> Mapping[str, object]:
        return {
            "provider": "openai",
            "origin": APPROVED_OPENAI_ORIGIN,
            "endpoint_path": APPROVED_OPENAI_ENDPOINT_PATH,
            "transport_evidence": _DIRECT_TRANSPORT_EVIDENCE,
        }


OFFICIAL_OPENAI_ROUTE_POLICY = OfficialOpenAIRoutePolicy()


@dataclass(frozen=True, slots=True)
class OfficialOpenAIHTTPResponse:
    status_code: int
    body: bytes
    route: ProviderRouteAttestation


def diagnostic_openai_route(
    route: ProviderRouteAttestation,
) -> ProviderRouteAttestation:
    """Force any injected high-level transport evidence to non-publishable trust."""

    return replace(
        route,
        trust=TRUST_DIAGNOSTIC_UNTRUSTED,
        origin="[redacted]",
        endpoint_path="[redacted]",
        transport_evidence=_DIAGNOSTIC_TRANSPORT_EVIDENCE,
    )


class OfficialOpenAIHTTPTransport:
    """Raw HTTP adapter with a fixed publishable path and diagnostic factory."""

    def __init__(
        self,
        *,
        api_key: str,
        credential_binding_id: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        self._configure(
            api_key=api_key,
            credential_binding_id=credential_binding_id,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            trusted_transport=True,
            diagnostic_transport=None,
        )

    @classmethod
    def for_diagnostics(
        cls,
        *,
        api_key: str,
        credential_binding_id: str,
        transport: httpx.AsyncBaseTransport,
        timeout_seconds: float = 120.0,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.25,
    ) -> OfficialOpenAIHTTPTransport:
        instance = cls.__new__(cls)
        instance._configure(
            api_key=api_key,
            credential_binding_id=credential_binding_id,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            trusted_transport=False,
            diagnostic_transport=transport,
        )
        return instance

    def _configure(
        self,
        *,
        api_key: str,
        credential_binding_id: str,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        trusted_transport: bool,
        diagnostic_transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        key = str(api_key or "").strip()
        if not _OPENAI_KEY_RE.fullmatch(key):
            raise ValueError("official OpenAI transport requires a valid official API key")
        binding = str(credential_binding_id or "").strip()
        if not binding:
            raise ValueError("official OpenAI transport requires a credential binding")
        self._timeout_seconds = _bounded_float(timeout_seconds, "timeout", 600.0)
        self._max_retries = _bounded_int(max_retries, "max retries", 5)
        self._retry_backoff_seconds = _bounded_float(
            retry_backoff_seconds, "retry backoff", 30.0, allow_zero=True
        )
        self._authorization = f"Bearer {key}"
        commitment = hmac.new(key.encode(), binding.encode(), hashlib.sha256).digest()
        self._credential_binding_id = f"sha256:{hashlib.sha256(commitment).hexdigest()}"
        self._trusted_transport = trusted_transport
        self._diagnostic_transport = diagnostic_transport
        self._closed = threading.Event()
        self._active_lock = threading.Lock()
        self._active_tasks: set[tuple[asyncio.AbstractEventLoop, asyncio.Task[object]]] = set()

    def post(self, body: bytes) -> OfficialOpenAIHTTPResponse:
        if len(body) > _MAX_REQUEST_BODY_BYTES:
            raise OfficialOpenAIRequestTooLargeError(
                "official OpenAI request exceeded the body limit"
            )
        if self._closed.is_set():
            raise OfficialOpenAICancelledError("official OpenAI request was cancelled")
        return _run_coroutine(self._complete_request(bytes(body)))

    def close(self) -> None:
        self._closed.set()
        with self._active_lock:
            active = tuple(self._active_tasks)
        for loop, task in active:
            loop.call_soon_threadsafe(task.cancel)

    async def _complete_request(self, body: bytes) -> OfficialOpenAIHTTPResponse:
        task = asyncio.current_task()
        if task is None:
            raise AssertionError("official OpenAI request requires an asyncio task")
        loop = asyncio.get_running_loop()
        active = (loop, task)
        with self._active_lock:
            if self._closed.is_set():
                raise OfficialOpenAICancelledError("official OpenAI request was cancelled")
            self._active_tasks.add(active)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._post_async(body)
        except TimeoutError:
            raise OfficialOpenAIDeadlineError(
                "official OpenAI request deadline expired"
            ) from None
        except asyncio.CancelledError:
            raise OfficialOpenAICancelledError(
                "official OpenAI request was cancelled"
            ) from None
        finally:
            with self._active_lock:
                self._active_tasks.discard(active)

    async def _post_async(self, body: bytes) -> OfficialOpenAIHTTPResponse:
        headers = {
            "Accept-Encoding": "identity",
            "Authorization": self._authorization,
            "Content-Type": "application/json",
        }
        async with self._new_client() as client:
            for attempt in range(self._max_retries + 1):
                try:
                    async with client.stream(
                        "POST", _OFFICIAL_ENDPOINT, headers=headers, content=body
                    ) as response:
                        _reject_unsafe_encoding(response)
                        status = response.status_code
                        request_url = str(response.request.url)
                        retry = _retryable_status(status) and attempt < self._max_retries
                        if status == 200:
                            _require_json_utf8(response)
                        response_body = (
                            await _read_bounded_response(response)
                            if status == 200 and not retry
                            else b""
                        )
                except OfficialOpenAITransportError:
                    raise
                except httpx.TransportError:
                    if self._closed.is_set():
                        raise OfficialOpenAICancelledError(
                            "official OpenAI request was cancelled"
                        ) from None
                    if attempt >= self._max_retries:
                        raise OfficialOpenAIRequestError(
                            "official OpenAI request failed"
                        ) from None
                    await self._backoff(attempt)
                    continue
                if retry:
                    await self._backoff(attempt)
                    continue
                route = _route_attestation(
                    request_url,
                    credential_binding_id=self._credential_binding_id,
                    response_status=status,
                    trusted_transport=self._trusted_transport,
                )
                return OfficialOpenAIHTTPResponse(status, response_body, route)
        raise AssertionError("official OpenAI retry loop exhausted unexpectedly")

    async def _backoff(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        if delay:
            await asyncio.sleep(delay)

    def _new_client(self) -> httpx.AsyncClient:
        if self._trusted_transport:
            return httpx.AsyncClient(
                timeout=None, follow_redirects=False, trust_env=False, verify=True
            )
        return httpx.AsyncClient(
            timeout=None,
            transport=self._diagnostic_transport,
            follow_redirects=False,
            trust_env=False,
        )


def _route_attestation(
    endpoint: str,
    *,
    credential_binding_id: str,
    response_status: int,
    trusted_transport: bool,
) -> ProviderRouteAttestation:
    raw = str(endpoint or "").strip()
    try:
        parsed = urlsplit(raw)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        exact = (
            origin == APPROVED_OPENAI_ORIGIN
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == APPROVED_OPENAI_ENDPOINT_PATH
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        exact = False
    official = exact and trusted_transport
    return ProviderRouteAttestation(
        trust=TRUST_OFFICIAL_OPENAI if official else TRUST_DIAGNOSTIC_UNTRUSTED,
        origin=APPROVED_OPENAI_ORIGIN if official else "[redacted]",
        endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH if official else "[redacted]",
        route_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        transport_evidence=(
            _DIRECT_TRANSPORT_EVIDENCE if official else _DIAGNOSTIC_TRANSPORT_EVIDENCE
        ),
        credential_binding_id=credential_binding_id,
        request_method="POST",
        response_status=response_status,
    )


async def _read_bounded_response(response: httpx.Response) -> bytes:
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            content_length = int(raw_length)
        except ValueError:
            raise OfficialOpenAIMalformedResponseError(
                "official OpenAI response had invalid content length"
            ) from None
        if content_length < 0 or content_length > _MAX_RESPONSE_BODY_BYTES:
            raise OfficialOpenAIResponseTooLargeError(
                "official OpenAI response exceeded the body limit"
            )
    body = bytearray()
    async for chunk in response.aiter_raw():
        if len(body) + len(chunk) > _MAX_RESPONSE_BODY_BYTES:
            raise OfficialOpenAIResponseTooLargeError(
                "official OpenAI response exceeded the body limit"
            )
        body.extend(chunk)
    return bytes(body)


def _reject_unsafe_encoding(response: httpx.Response) -> None:
    encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    if encoding not in {"", "identity"}:
        raise OfficialOpenAIUnsafeEncodingError(
            "official OpenAI response used an unsupported content encoding"
        )


def _require_json_utf8(response: httpx.Response) -> None:
    content_type = response.headers.get("Content-Type", "")
    parts = [part.strip().casefold() for part in content_type.split(";")]
    if not parts or parts[0] != "application/json":
        raise OfficialOpenAIMalformedResponseError(
            "official OpenAI response was not application/json UTF-8"
        )
    parameters = parts[1:]
    if parameters and parameters != ["charset=utf-8"]:
        raise OfficialOpenAIMalformedResponseError(
            "official OpenAI response was not application/json UTF-8"
        )


def validate_official_chat_completion(
    payload: object,
    *,
    configured_model: str,
) -> None:
    """Fail closed on the exact official Chat Completion envelope."""

    if not isinstance(payload, Mapping):
        raise OfficialOpenAIMalformedResponseError(
            "official OpenAI response had an invalid completion envelope"
        )
    choices = payload.get("choices")
    first = (
        choices[0]
        if isinstance(choices, Sequence)
        and not isinstance(choices, str | bytes)
        and choices
        else None
    )
    message = first.get("message") if isinstance(first, Mapping) else None
    if (
        payload.get("object") != "chat.completion"
        or payload.get("model") != configured_model
        or not _OPENAI_RESPONSE_ID_RE.fullmatch(str(payload.get("id") or ""))
        or not _OPENAI_FINGERPRINT_RE.fullmatch(
            str(payload.get("system_fingerprint") or "")
        )
        or not isinstance(first, Mapping)
        or len(choices) != 1
        or type(first.get("index")) is not int
        or first.get("index") != 0
        or not isinstance(message, Mapping)
        or message.get("role") != "assistant"
    ):
        raise OfficialOpenAIMalformedResponseError(
            "official OpenAI response had an invalid completion envelope"
        )


def _run_coroutine(coroutine: object) -> OfficialOpenAIHTTPResponse:
    async def runner() -> OfficialOpenAIHTTPResponse:
        return await coroutine  # type: ignore[misc]

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(runner())
    result: list[OfficialOpenAIHTTPResponse] = []
    errors: list[BaseException] = []

    def run_in_thread() -> None:
        try:
            result.append(asyncio.run(runner()))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def _bounded_int(value: int, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"official OpenAI {label} must be between 0 and {maximum}")
    return value


def _bounded_float(
    value: float, label: str, maximum: float, *, allow_zero: bool = False
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"official OpenAI {label} must be numeric")
    normalized = float(value)
    minimum_ok = normalized >= 0 if allow_zero else normalized > 0
    if not isfinite(normalized) or not minimum_ok or normalized > maximum:
        raise ValueError(f"official OpenAI {label} must be bounded and finite")
    return normalized


def _retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES or status_code >= 500


__all__ = (
    "APPROVED_OPENAI_ENDPOINT_PATH",
    "APPROVED_OPENAI_ORIGIN",
    "OFFICIAL_OPENAI_ROUTE_POLICY",
    "OFFICIAL_OPENAI_ROUTE_POLICY_ID",
    "OfficialOpenAICancelledError",
    "OfficialOpenAIDeadlineError",
    "OfficialOpenAIHTTPError",
    "OfficialOpenAIHTTPResponse",
    "OfficialOpenAIHTTPTransport",
    "OfficialOpenAIMalformedResponseError",
    "OfficialOpenAIRequestError",
    "OfficialOpenAIRequestTooLargeError",
    "OfficialOpenAIResponseTooLargeError",
    "OfficialOpenAIRoutePolicy",
    "OfficialOpenAITransportError",
    "OfficialOpenAIUnsafeEncodingError",
    "TRUST_DIAGNOSTIC_UNTRUSTED",
    "TRUST_OFFICIAL_OPENAI",
    "diagnostic_openai_route",
    "validate_official_chat_completion",
)
