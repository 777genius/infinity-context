"""Strict identity probe for an OpenAI-compatible TEI runtime."""

from __future__ import annotations

import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from urllib.parse import urlsplit

import httpx

_MAX_INFO_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class TeiIdentity:
    model_id: str
    model_sha: str
    build_sha: str
    inference_base_url: str


@dataclass(frozen=True, slots=True)
class TeiProbe:
    model_id: str
    model_sha: str
    build_sha: str
    inference_base_url: str
    info_url: str
    pinned_inference_base_url: str
    pinned_info_url: str
    authority: str
    sni_hostname: str

    @classmethod
    def create(
        cls,
        *,
        model_id: str,
        model_sha: str,
        build_sha: str,
        inference_base_url: str,
        info_url: str,
    ) -> TeiProbe:
        inference, info = bound_runtime_urls(inference_base_url, info_url)
        parsed = urlsplit(inference)
        assert parsed.hostname is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        address = _resolve_host(parsed.hostname, port)
        pinned_inference = _replace_hostname(inference, address)
        pinned_info = _replace_hostname(info, address)
        authority = parsed.hostname
        if port != (443 if parsed.scheme == "https" else 80):
            authority = f"{authority}:{port}"
        return cls(
            model_id,
            model_sha,
            build_sha,
            inference,
            info,
            pinned_inference,
            pinned_info,
            authority,
            parsed.hostname,
        )

    def verify(self) -> TeiIdentity:
        try:
            tracker = _ConnectionTracker()
            with _sync_client(self, tracker) as client:
                response = client.get(self.pinned_info_url)
                if str(response.url) != self.pinned_info_url:
                    raise RuntimeError("embedding runtime info endpoint redirected")
                data = response.content
        except (httpx.HTTPError, OSError) as exc:
            raise RuntimeError("embedding runtime info endpoint is unavailable") from exc
        self._verify_payload(data)
        return TeiIdentity(self.model_id, self.model_sha, self.build_sha, self.inference_base_url)

    @asynccontextmanager
    async def verified_session(self) -> AsyncIterator[VerifiedTeiSession]:
        tracker = _ConnectionTracker()
        transport = _PinnedAsyncTransport(self.sni_hostname)
        async with httpx.AsyncClient(
            follow_redirects=False,
            headers={"Host": self.authority},
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            timeout=5,
            transport=transport,
            event_hooks={"response": [tracker.observe_async]},
        ) as client:
            try:
                response = await client.get(self.pinned_info_url)
            except httpx.HTTPError as exc:
                raise RuntimeError("embedding runtime info endpoint is unavailable") from exc
            if str(response.url) != self.pinned_info_url:
                raise RuntimeError("embedding runtime info endpoint redirected")
            self._verify_payload(response.content)
            yield VerifiedTeiSession(client, self.pinned_inference_base_url, tracker)

    def _verify_payload(self, data: bytes) -> None:
        if len(data) > _MAX_INFO_BYTES:
            raise RuntimeError("embedding runtime info response exceeds its size limit")
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("embedding runtime info response is malformed") from exc
        expected = {
            "model_id": self.model_id,
            "model_sha": self.model_sha,
            "sha": self.build_sha,
        }
        if not isinstance(payload, dict) or any(payload.get(k) != v for k, v in expected.items()):
            raise RuntimeError("embedding runtime identity does not match frozen profile")


@dataclass(frozen=True, slots=True)
class VerifiedTeiSession:
    http_client: httpx.AsyncClient
    inference_base_url: str
    _tracker: _ConnectionTracker

    def assert_single_connection(self) -> None:
        self._tracker.assert_reused()


def bound_runtime_urls(base_url: str, info_url: str) -> tuple[str, str]:
    inference = _normalized_url(base_url, "embedding inference base URL")
    info = _normalized_url(info_url, "embedding runtime info URL")
    if inference[:3] != info[:3]:
        raise RuntimeError("embedding runtime info URL does not match inference origin")
    inference_path = inference[3].rstrip("/")
    if not inference_path.endswith("/v1"):
        raise RuntimeError("embedding inference base URL path must end in /v1")
    if info[3] != (f"{inference_path[:-3]}/info" or "/info"):
        raise RuntimeError("embedding runtime info URL does not match inference path")
    return _render(*inference[:3], inference_path), _render(*info)


def _normalized_url(url: str, label: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "//" in parsed.path
        or "%" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise RuntimeError(f"{label} must be a credential-free HTTP(S) URL")
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), effective_port, parsed.path


def _render(scheme: str, host: str, port: int, path: str) -> str:
    default = (scheme, port) in {("http", 80), ("https", 443)}
    host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host if default else f'{host}:{port}'}{path}"


def _resolve_host(host: str, port: int) -> str:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise RuntimeError("embedding runtime host cannot be resolved") from exc
    if not addresses:
        raise RuntimeError("embedding runtime host cannot be resolved")
    return sorted(addresses)[0]


def _replace_hostname(url: str, address: str) -> str:
    parsed = urlsplit(url)
    assert parsed.hostname is not None
    port = parsed.port
    host = f"[{address}]" if ":" in address else address
    authority = host if port is None else f"{host}:{port}"
    return parsed._replace(netloc=authority).geturl()


class _ConnectionTracker:
    def __init__(self) -> None:
        self._stream: object | None = None
        self._responses = 0

    def observe(self, response: httpx.Response) -> None:
        stream = response.extensions.get("network_stream")
        if stream is None:
            raise RuntimeError("embedding runtime connection identity is unavailable")
        if self._stream is None:
            self._stream = stream
        elif stream is not self._stream:
            raise RuntimeError("embedding runtime connection changed")
        self._responses += 1

    async def observe_async(self, response: httpx.Response) -> None:
        self.observe(response)

    def assert_reused(self) -> None:
        if self._responses < 2:
            raise RuntimeError("embedding inference did not reuse verified runtime connection")


class _PinnedSyncTransport(httpx.BaseTransport):
    def __init__(self, sni_hostname: str) -> None:
        self._inner = httpx.HTTPTransport(
            retries=0,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self._sni_hostname = sni_hostname.encode("idna")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.extensions["sni_hostname"] = self._sni_hostname
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, sni_hostname: str) -> None:
        self._inner = httpx.AsyncHTTPTransport(
            retries=0,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self._sni_hostname = sni_hostname.encode("idna")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.extensions["sni_hostname"] = self._sni_hostname
        return await self._inner.handle_async_request(request)

    async def __aenter__(self) -> _PinnedAsyncTransport:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _sync_client(probe: TeiProbe, tracker: _ConnectionTracker) -> httpx.Client:
    return httpx.Client(
        follow_redirects=False,
        headers={"Host": probe.authority},
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        timeout=5,
        transport=_PinnedSyncTransport(probe.sni_hostname),
        event_hooks={"response": [tracker.observe]},
    )
