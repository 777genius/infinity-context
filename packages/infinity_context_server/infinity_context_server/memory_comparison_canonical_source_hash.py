"""Canonical source hashes shared by benchmark provider adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from infinity_context_core.application.normalize import content_hash

from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
)
from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class CanonicalSourceHashError(ValueError):
    """Raised when a benchmark source cannot be identified exactly."""


@dataclass(frozen=True, slots=True)
class CanonicalSourceHash:
    """Atomic public source id and canonical content digest."""

    source_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip()
        if not source_id:
            raise CanonicalSourceHashError("source_id is required")
        if not _SAFE_SOURCE_ID_RE.fullmatch(source_id):
            raise CanonicalSourceHashError("source_id must satisfy the Mem0 wire contract")
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise CanonicalSourceHashError("source_sha256 must be lowercase sha256")
        object.__setattr__(self, "source_id", source_id)

    def metadata(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
        }


def memory_source_hash(memory: BenchmarkMemoryInput) -> CanonicalSourceHash:
    """Match the raw UTF-8 fact content hash returned by Infinity Context."""

    source_id = _required_external_id(memory.source_external_id, kind="memory")
    return CanonicalSourceHash(
        source_id=safe_identifier(source_id, max_chars=160),
        source_sha256=hashlib.sha256(memory.text.encode("utf-8")).hexdigest(),
    )


def document_source_hash(document: BenchmarkDocumentInput) -> CanonicalSourceHash:
    """Match the legacy ``/v1/documents`` content-hash contract exactly."""

    source_id = _required_external_id(document.source_external_id, kind="document")
    return CanonicalSourceHash(
        source_id=safe_identifier(source_id, max_chars=160),
        source_sha256=content_hash(document.text),
    )


def conversation_source_hashes(
    case: PublicBenchmarkCase,
) -> tuple[CanonicalSourceHash, ...]:
    """Hash the exact canonical conversation documents sent to Infinity Context."""

    identities = tuple(document_source_hash(document) for document in conversation_documents(case))
    validate_unambiguous_source_hashes(identities)
    return identities


def validate_unambiguous_source_hashes(
    identities: tuple[CanonicalSourceHash, ...],
) -> None:
    """Reject duplicate ids even when their content happens to be identical."""

    seen: set[str] = set()
    for identity in identities:
        if identity.source_id in seen:
            raise CanonicalSourceHashError(f"ambiguous benchmark source_id: {identity.source_id}")
        seen.add(identity.source_id)


def _required_external_id(value: str | None, *, kind: str) -> str:
    source_id = str(value or "").strip()
    if not source_id:
        raise CanonicalSourceHashError(f"{kind} source_external_id is required")
    return source_id


__all__ = [
    "CanonicalSourceHash",
    "CanonicalSourceHashError",
    "conversation_source_hashes",
    "document_source_hash",
    "memory_source_hash",
    "validate_unambiguous_source_hashes",
]
