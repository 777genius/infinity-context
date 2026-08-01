"""Pure target normalization and identity commitments for managed runtimes."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit


def normalized_mem0_runtime_origin(base_url: str) -> tuple[str, str, str]:
    """Return the canonical origin used by live Mem0 runtime attestation."""

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


def mem0_runtime_target_identity_sha256(base_url: str) -> str:
    """Hash the exact normalized origin consumed by live Mem0 attestation."""

    origin, _, _ = normalized_mem0_runtime_origin(base_url)
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()


__all__ = (
    "mem0_runtime_target_identity_sha256",
    "normalized_mem0_runtime_origin",
)
