"""Fail-closed network policy and transport ports for benchmark probes."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


class ProbeResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def aiter_raw(self, chunk_size: int | None = None) -> AsyncIterator[bytes]: ...


class ProbeHttpClient(Protocol):
    def stream(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> AbstractAsyncContextManager[ProbeResponse]: ...


class VettedProbeTransport(Protocol):
    """Create a client whose hostname routing is pinned or peer-validated.

    Implementations for managed hostnames must preserve Host/SNI while ensuring
    every connection reaches only addresses vetted before any credential is sent.
    """

    def open_client(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> AbstractAsyncContextManager[ProbeHttpClient]: ...


@dataclass(frozen=True)
class VettedProbeTarget:
    base_url: str
    host: str
    identity_sha256: str
    transport: VettedProbeTransport


class HttpxLiteralProbeTransport:
    """Default transport for an already pinned IP-literal origin."""

    def open_client(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> AbstractAsyncContextManager[ProbeHttpClient]:
        import httpx

        return httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )


def vet_probe_target(
    base_url: str,
    *,
    allowed_hosts: Sequence[str] = (),
    vetted_transport: VettedProbeTransport | None = None,
) -> VettedProbeTarget | None:
    """Return a usable target only when routing cannot silently change after vetting."""

    try:
        origin, host, scheme = _normalized_origin(base_url)
    except ValueError:
        return None
    allowlist = _validated_host_allowlist(allowed_hosts)
    if allowlist is None:
        return None
    explicitly_allowed = host in allowlist
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None:
        if not explicitly_allowed or vetted_transport is None:
            return None
        transport = vetted_transport
    else:
        if (scheme != "https" or not address.is_global) and not explicitly_allowed:
            return None
        transport = vetted_transport or HttpxLiteralProbeTransport()
    return VettedProbeTarget(
        base_url=origin,
        host=host,
        identity_sha256=hashlib.sha256(origin.encode("utf-8")).hexdigest(),
        transport=transport,
    )


def mem0_runtime_target_identity_sha256(base_url: str) -> str:
    """Hash a normalized target origin without exposing its URL."""

    origin, _, _ = _normalized_origin(base_url)
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()


def mem0_live_probe_target_is_safe(
    base_url: str,
    *,
    allowed_hosts: Sequence[str] = (),
    vetted_transport: VettedProbeTransport | None = None,
    resolver: object = None,
) -> bool:
    """Compatibility predicate; DNS resolver injection is intentionally unsupported."""

    return (
        resolver is None
        and vet_probe_target(
            base_url,
            allowed_hosts=allowed_hosts,
            vetted_transport=vetted_transport,
        )
        is not None
    )


def _normalized_origin(base_url: str) -> tuple[str, str, str]:
    raw = str(base_url).strip()
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").casefold().removesuffix(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("probe target URL is invalid") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("probe target URL must use HTTP(S) with a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("probe target URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("probe target URL must not contain query or fragment")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    rendered_host = f"[{host}]" if ":" in host else host
    port_suffix = "" if port is None or default_port else f":{port}"
    return f"{scheme}://{rendered_host}{port_suffix}", host, scheme


def _validated_host_allowlist(values: Sequence[str]) -> frozenset[str] | None:
    if isinstance(values, str | bytes) or len(values) > 128:
        return None
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            return None
        host = value.strip().casefold().removesuffix(".")
        if not host or len(host) > 253 or "/" in host or "@" in host or ":" in host:
            return None
        normalized.add(host)
    return frozenset(normalized)


__all__ = (
    "ProbeHttpClient",
    "VettedProbeTarget",
    "VettedProbeTransport",
    "mem0_live_probe_target_is_safe",
    "mem0_runtime_target_identity_sha256",
    "vet_probe_target",
)
