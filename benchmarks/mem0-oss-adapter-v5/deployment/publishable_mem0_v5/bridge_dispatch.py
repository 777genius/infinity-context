"""Credential-file-free authenticated dispatch to three private bridge ports."""

from __future__ import annotations

import hashlib
import hmac
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import httpx
from infinity_context_runtime_bridge.contracts import (
    BridgeTransportError,
)

from .config import (
    ADAPTER_PORT,
    BRIDGE_PORTS,
    QDRANT_GRPC_PORT,
    QDRANT_HTTP_PORT,
    RELAY_PORT,
)

DISPATCH_SCHEMA: Final = "publishable-mem0-v5-bridge-dispatch.v1"
DISPATCH_ROUTE: Final = "/v1/chat/completions"
DISPATCH_SCHEMA_HEADER: Final = "X-Infinity-Dispatch-Schema"
DISPATCH_PORT_HEADER: Final = "X-Infinity-Bridge-Port"
DISPATCH_BODY_SHA256_HEADER: Final = "X-Infinity-Dispatch-Body-SHA256"
DISPATCH_HMAC_HEADER: Final = "X-Infinity-Dispatch-HMAC-SHA256"

_AUTHORIZATION_HEADER = "Authorization"
_CONTENT_LENGTH_HEADER = "Content-Length"
_CONTENT_TYPE_HEADER = "Content-Type"
_DOMAIN = b"publishable-mem0-v5/bridge-dispatch/v1\0"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BEARER_BYTES = 8192
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_FORBIDDEN_RELAY_PORTS = {
    ADAPTER_PORT,
    QDRANT_GRPC_PORT,
    QDRANT_HTTP_PORT,
    RELAY_PORT,
    *BRIDGE_PORTS,
}
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_FORWARDED_HEADERS = (
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "user-agent",
)


class BridgeDispatchError(RuntimeError):
    """Sanitized HTTP dispatch failure with a stable response status."""

    def __init__(self, code: str, *, status_code: int) -> None:
        allowed = {
            "publishable_dispatch_request_invalid": 400,
            "publishable_dispatch_authentication_invalid": 401,
            "publishable_dispatch_target_invalid": 403,
            "publishable_dispatch_upstream_unavailable": 502,
        }
        if allowed.get(code) != status_code:
            code = "publishable_dispatch_request_invalid"
            status_code = 400
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ParsedRequestHead:
    raw: bytes
    method: str
    target: str
    version: str
    headers: Mapping[str, str]
    body_prefix: bytes


class HttpxRelayBridgeTransport:
    """Dispatch one selected bridge call through the lane's only host relay."""

    __slots__ = (
        "_connect_timeout_seconds",
        "_maximum_request_bytes",
        "_read_timeout_seconds",
        "_relay_origin",
        "_transport",
        "_write_timeout_seconds",
    )

    def __init__(
        self,
        *,
        relay_origin: str,
        maximum_request_bytes: int,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 300.0,
        write_timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (
            type(maximum_request_bytes) is not int
            or not 1 <= maximum_request_bytes <= _MAX_REQUEST_BYTES
        ):
            raise BridgeTransportError("bridge_http_request_limit_invalid")
        for value in (
            connect_timeout_seconds,
            read_timeout_seconds,
            write_timeout_seconds,
        ):
            if type(value) not in {int, float} or not 0 < value <= 3600:
                raise BridgeTransportError("bridge_http_timeout_invalid")
        self._relay_origin = _relay_origin(relay_origin)
        self._maximum_request_bytes = maximum_request_bytes
        self._connect_timeout_seconds = float(connect_timeout_seconds)
        self._read_timeout_seconds = float(read_timeout_seconds)
        self._write_timeout_seconds = float(write_timeout_seconds)
        self._transport = transport

    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes:
        if (
            type(request_body) is not bytes
            or not request_body
            or len(request_body) > self._maximum_request_bytes
        ):
            raise BridgeTransportError("bridge_http_request_size_invalid")
        if type(maximum_response_bytes) is not int or maximum_response_bytes < 1:
            raise BridgeTransportError("bridge_http_response_limit_invalid")
        if route != DISPATCH_ROUTE:
            raise BridgeTransportError("bridge_http_route_invalid")
        bridge_port = _bridge_origin_port(origin)
        try:
            dispatch_headers = build_dispatch_headers(
                bridge_port=bridge_port,
                bearer_token=bearer_token,
                request_body=request_body,
            )
        except BridgeDispatchError as exc:
            raise BridgeTransportError("bridge_http_bearer_invalid") from exc
        timeout = httpx.Timeout(
            connect=self._connect_timeout_seconds,
            read=self._read_timeout_seconds,
            write=self._write_timeout_seconds,
            pool=self._connect_timeout_seconds,
        )
        transport = self._transport or httpx.HTTPTransport(retries=0)
        try:
            with (
                httpx.Client(
                    transport=transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "POST",
                    f"{self._relay_origin}{DISPATCH_ROUTE}",
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "Authorization": f"Bearer {bearer_token}",
                        "Content-Type": "application/json",
                        **dispatch_headers,
                    },
                    content=request_body,
                ) as response,
            ):
                if response.status_code != 200:
                    raise BridgeTransportError("bridge_http_status_invalid")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length, 10)
                    except ValueError as exc:
                        raise BridgeTransportError("bridge_http_content_length_invalid") from exc
                    if declared < 0 or declared > maximum_response_bytes:
                        raise BridgeTransportError("bridge_http_response_too_large")
                content = bytearray()
                for chunk in response.iter_raw():
                    content.extend(chunk)
                    if len(content) > maximum_response_bytes:
                        raise BridgeTransportError("bridge_http_response_too_large")
                if not content:
                    raise BridgeTransportError("bridge_http_response_empty")
                return bytes(content)
        except BridgeTransportError:
            raise
        except httpx.HTTPError as exc:
            raise BridgeTransportError("bridge_http_transport_failed") from exc


def build_dispatch_headers(
    *,
    bridge_port: int,
    bearer_token: str,
    request_body: bytes,
) -> dict[str, str]:
    """Bind a selected private port and exact body to the bridge bearer."""

    _require_port(bridge_port)
    bearer = _bearer_bytes(bearer_token)
    body_sha256 = _body_sha256(request_body)
    signature = hmac.new(
        bearer,
        _signature_material(bridge_port, body_sha256),
        hashlib.sha256,
    ).hexdigest()
    return {
        DISPATCH_SCHEMA_HEADER: DISPATCH_SCHEMA,
        DISPATCH_PORT_HEADER: str(bridge_port),
        DISPATCH_BODY_SHA256_HEADER: body_sha256,
        DISPATCH_HMAC_HEADER: signature,
    }


def authenticate_dispatch(
    *,
    method: str,
    target: str,
    headers: Mapping[str, str],
    request_body: bytes,
) -> int:
    """Return the selected port only after exact target, body, and bearer binding."""

    lowered = {key.casefold(): value for key, value in headers.items()}
    if len(lowered) != len(headers) or method != "POST" or target != DISPATCH_ROUTE:
        _invalid_request()
    if lowered.get(DISPATCH_SCHEMA_HEADER.casefold()) != DISPATCH_SCHEMA:
        _invalid_authentication()
    raw_port = lowered.get(DISPATCH_PORT_HEADER.casefold())
    if raw_port is None or not raw_port.isascii() or not raw_port.isdecimal():
        _invalid_target()
    port = int(raw_port, 10)
    _require_port(port)
    body_sha256 = lowered.get(DISPATCH_BODY_SHA256_HEADER.casefold())
    supplied_hmac = lowered.get(DISPATCH_HMAC_HEADER.casefold())
    authorization = lowered.get(_AUTHORIZATION_HEADER.casefold())
    if (
        body_sha256 is None
        or _SHA256.fullmatch(body_sha256) is None
        or supplied_hmac is None
        or _SHA256.fullmatch(supplied_hmac) is None
        or authorization is None
        or not authorization.startswith("Bearer ")
    ):
        _invalid_authentication()
    actual_body_sha256 = _body_sha256(request_body)
    if not hmac.compare_digest(body_sha256, actual_body_sha256):
        _invalid_authentication()
    bearer = _bearer_bytes(authorization.removeprefix("Bearer "))
    expected = hmac.new(
        bearer,
        _signature_material(port, actual_body_sha256),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_hmac, expected):
        _invalid_authentication()
    return port


def read_request_head(client: socket.socket) -> ParsedRequestHead:
    """Read one bounded HTTP/1 request head while retaining already-read body bytes."""

    raw = bytearray()
    marker = -1
    while marker < 0:
        try:
            chunk = client.recv(min(4096, _MAX_HEADER_BYTES + 1 - len(raw)))
        except OSError as exc:
            raise BridgeDispatchError(
                "publishable_dispatch_request_invalid",
                status_code=400,
            ) from exc
        if not chunk:
            _invalid_request()
        raw.extend(chunk)
        if len(raw) > _MAX_HEADER_BYTES:
            _invalid_request()
        marker = raw.find(b"\r\n\r\n")
    head_end = marker + 4
    head = bytes(raw[:head_end])
    lines = head[:-4].split(b"\r\n")
    if not lines:
        _invalid_request()
    try:
        method_raw, target_raw, version_raw = lines[0].split(b" ")
        method = method_raw.decode("ascii")
        target = target_raw.decode("ascii")
        version = version_raw.decode("ascii")
    except (UnicodeDecodeError, ValueError):
        _invalid_request()
    if (
        method not in {"GET", "POST"}
        or not target.startswith("/")
        or "#" in target
        or version not in {"HTTP/1.0", "HTTP/1.1"}
    ):
        _invalid_request()
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        if not line or line[:1] in b" \t" or b":" not in line:
            _invalid_request()
        name_raw, value_raw = line.split(b":", 1)
        if _HEADER_NAME.fullmatch(name_raw) is None:
            _invalid_request()
        try:
            name = name_raw.decode("ascii").casefold()
            value = value_raw.strip(b" \t").decode("ascii")
        except UnicodeDecodeError:
            _invalid_request()
        if name in parsed or any(ord(character) < 0x20 for character in value):
            _invalid_request()
        parsed[name] = value
    return ParsedRequestHead(
        raw=head,
        method=method,
        target=target,
        version=version,
        headers=parsed,
        body_prefix=bytes(raw[head_end:]),
    )


def read_dispatch_body(client: socket.socket, request: ParsedRequestHead) -> bytes:
    """Read the exact non-chunked dispatch body and reject request smuggling."""

    if "transfer-encoding" in request.headers:
        _invalid_request()
    length_text = request.headers.get(_CONTENT_LENGTH_HEADER.casefold())
    if length_text is None or not length_text.isdecimal():
        _invalid_request()
    length = int(length_text, 10)
    if not 1 <= length <= _MAX_REQUEST_BYTES or len(request.body_prefix) > length:
        _invalid_request()
    body = bytearray(request.body_prefix)
    while len(body) < length:
        try:
            chunk = client.recv(min(64 * 1024, length - len(body)))
        except OSError as exc:
            raise BridgeDispatchError(
                "publishable_dispatch_request_invalid",
                status_code=400,
            ) from exc
        if not chunk:
            _invalid_request()
        body.extend(chunk)
    return bytes(body)


def render_upstream_request(
    *,
    request: ParsedRequestHead,
    request_body: bytes,
    bridge_port: int,
) -> bytes:
    """Strip dispatcher metadata and render one close-delimited upstream request."""

    _require_port(bridge_port)
    if request.method != "POST" or request.target != DISPATCH_ROUTE:
        _invalid_request()
    content_type = request.headers.get(_CONTENT_TYPE_HEADER.casefold())
    if content_type is None or content_type.split(";", 1)[0].strip() != "application/json":
        _invalid_request()
    lines = [
        f"POST {DISPATCH_ROUTE} HTTP/1.1",
        f"Host: 127.0.0.1:{bridge_port}",
        "Connection: close",
        f"Content-Length: {len(request_body)}",
    ]
    for name in _FORWARDED_HEADERS:
        if name in {"content-length"}:
            continue
        value = request.headers.get(name)
        if value is not None:
            canonical_name = "-".join(part.capitalize() for part in name.split("-"))
            lines.append(f"{canonical_name}: {value}")
    return "\r\n".join((*lines, "", "")).encode("ascii") + request_body


def _bridge_origin_port(value: object) -> int:
    port = _loopback_origin_port(value, code="bridge_http_origin_invalid")
    if port not in BRIDGE_PORTS:
        raise BridgeTransportError("bridge_http_origin_invalid")
    return port


def _relay_origin(value: object) -> str:
    port = _loopback_origin_port(value, code="bridge_http_relay_origin_invalid")
    if port in _FORBIDDEN_RELAY_PORTS:
        raise BridgeTransportError("bridge_http_relay_origin_invalid")
    return f"http://127.0.0.1:{port}"


def _loopback_origin_port(value: object, *, code: str) -> int:
    if type(value) is not str or len(value) > 256:
        raise BridgeTransportError(code)
    try:
        split = urlsplit(value)
        port = split.port
    except (TypeError, ValueError) as exc:
        raise BridgeTransportError(code) from exc
    if (
        split.scheme != "http"
        or split.hostname != "127.0.0.1"
        or split.username is not None
        or split.password is not None
        or split.path
        or split.query
        or split.fragment
        or type(port) is not int
        or not 1024 <= port <= 65535
        or value != f"http://127.0.0.1:{port}"
    ):
        raise BridgeTransportError(code)
    return port


def _signature_material(port: int, body_sha256: str) -> bytes:
    return _DOMAIN + f"POST\0{DISPATCH_ROUTE}\0{port}\0{body_sha256}".encode("ascii")


def _body_sha256(value: bytes) -> str:
    if type(value) is not bytes or not 1 <= len(value) <= _MAX_REQUEST_BYTES:
        _invalid_request()
    return hashlib.sha256(value).hexdigest()


def _bearer_bytes(value: str) -> bytes:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\r" in value
        or "\n" in value
    ):
        _invalid_authentication()
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError:
        _invalid_authentication()
    if len(raw) > _MAX_BEARER_BYTES:
        _invalid_authentication()
    return raw


def _require_port(value: int) -> None:
    if type(value) is not int or value not in BRIDGE_PORTS:
        _invalid_target()


def _invalid_request() -> None:
    raise BridgeDispatchError(
        "publishable_dispatch_request_invalid",
        status_code=400,
    )


def _invalid_authentication() -> None:
    raise BridgeDispatchError(
        "publishable_dispatch_authentication_invalid",
        status_code=401,
    )


def _invalid_target() -> None:
    raise BridgeDispatchError(
        "publishable_dispatch_target_invalid",
        status_code=403,
    )


__all__ = (
    "DISPATCH_BODY_SHA256_HEADER",
    "DISPATCH_HMAC_HEADER",
    "DISPATCH_PORT_HEADER",
    "DISPATCH_ROUTE",
    "DISPATCH_SCHEMA",
    "DISPATCH_SCHEMA_HEADER",
    "BridgeDispatchError",
    "HttpxRelayBridgeTransport",
    "ParsedRequestHead",
    "authenticate_dispatch",
    "build_dispatch_headers",
    "read_dispatch_body",
    "read_request_head",
    "render_upstream_request",
)
