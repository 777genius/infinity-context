"""Exactly-once HTTP transport for an already-selected local bridge."""

from __future__ import annotations

import httpx

from .contracts import BridgeTransportError


class HttpxOneShotBridgeTransport:
    """POST once with redirects, retries, environment proxies, and logging disabled."""

    __slots__ = (
        "_connect_timeout_seconds",
        "_maximum_request_bytes",
        "_read_timeout_seconds",
        "_transport",
        "_write_timeout_seconds",
    )

    def __init__(
        self,
        *,
        maximum_request_bytes: int,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 300.0,
        write_timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if type(maximum_request_bytes) is not int or maximum_request_bytes < 1:
            raise BridgeTransportError("bridge_http_request_limit_invalid")
        for value in (
            connect_timeout_seconds,
            read_timeout_seconds,
            write_timeout_seconds,
        ):
            if type(value) not in {int, float} or not 0 < value <= 3600:
                raise BridgeTransportError("bridge_http_timeout_invalid")
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
        if (
            not isinstance(bearer_token, str)
            or not bearer_token
            or "\r" in bearer_token
            or "\n" in bearer_token
        ):
            raise BridgeTransportError("bridge_http_bearer_invalid")
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
                    f"{origin}{route}",
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "Authorization": f"Bearer {bearer_token}",
                        "Content-Type": "application/json",
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
                observed = 0
                for chunk in response.iter_raw():
                    observed += len(chunk)
                    if observed > maximum_response_bytes:
                        raise BridgeTransportError("bridge_http_response_too_large")
                    content.extend(chunk)
                if observed == 0:
                    raise BridgeTransportError("bridge_http_response_empty")
                return bytes(content)
        except BridgeTransportError:
            raise
        except httpx.HTTPError as exc:
            raise BridgeTransportError("bridge_http_transport_failed") from exc


__all__ = ("HttpxOneShotBridgeTransport",)
