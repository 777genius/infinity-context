"""Public benchmark ports and normalized case models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


def __getattr__(name: str) -> Any:
    """Keep the historical adapter export without eagerly importing HTTPX."""
    if name != "HttpBenchmarkAdapter":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from infinity_context_server.public_benchmark_transport import HttpBenchmarkAdapter

    return HttpBenchmarkAdapter


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark dataset cannot be normalized safely."""


class BenchmarkHttpClientPort(Protocol):
    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        """Execute an HTTP POST through the chosen transport."""


class BenchmarkHttpResponsePort(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        """Return decoded JSON response body."""


@dataclass(frozen=True)
class BenchmarkMemoryInput:
    text: str
    kind: str = "note"
    source_external_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkDocumentInput:
    title: str
    text: str
    source_type: str = "benchmark_document"
    classification: str = "internal"
    source_external_id: str | None = None
    source_refs: tuple[Mapping[str, object], ...] = ()


BenchmarkMessageRole = Literal["user", "assistant", "system"]


@dataclass(frozen=True)
class BenchmarkMessageInput:
    """Provider-neutral message accepted by a benchmark ingestion adapter."""

    role: BenchmarkMessageRole
    content: str
    source_external_id: str | None = None
    timestamp: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkConversationInput:
    """Ordered messages that must be submitted as one ingestion operation."""

    messages: tuple[BenchmarkMessageInput, ...]
    source_external_id: str | None = None
    session_external_id: str | None = None
    session_date: str | None = None
    timestamp: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicBenchmarkCase:
    benchmark: str
    case_id: str
    question: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    memories: tuple[BenchmarkMemoryInput, ...] = ()
    documents: tuple[BenchmarkDocumentInput, ...] = ()
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    conversations: tuple[BenchmarkConversationInput, ...] = ()


class TestClientBenchmarkAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        return self._client.post(path, json=dict(json_body), headers=dict(headers))
