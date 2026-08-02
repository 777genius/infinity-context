"""Identity-only target commitments for derived projection adapters."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from infinity_context_core.domain.errors import MemoryValidationError


def graphiti_target_commitment_sha256(*, neo4j_uri: str, database: str = "default") -> str:
    """Bind evidence to a configured target without exposing its URL or database."""

    if not neo4j_uri.strip() or not database.strip():
        raise MemoryValidationError("Graphiti target configuration is incomplete")
    normalized_uri = _normalized_neo4j_target(neo4j_uri)
    return hashlib.sha256(f"graphiti\0{normalized_uri}\0{database}".encode()).hexdigest()


def _normalized_neo4j_target(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise MemoryValidationError("Graphiti target URI is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"neo4j", "neo4j+s", "bolt", "bolt+s"}:
        raise MemoryValidationError("Graphiti target URI scheme is invalid")
    hostname = parsed.hostname
    if hostname is None or not hostname.strip():
        raise MemoryValidationError("Graphiti target URI host is invalid")
    normalized_host = hostname.lower()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    netloc = normalized_host if port is None else f"{normalized_host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


__all__ = ("graphiti_target_commitment_sha256",)
