"""Provider circuit breakers for prompt-path adapter calls."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Protocol, TypeVar

from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingPort,
    EmbeddingResult,
    GraphMemoryPort,
    GraphSearchResult,
    PortDiagnostic,
    PortStatus,
    VectorMemoryPort,
    VectorSearchResult,
    VectorUpsertItem,
    VectorWriteResult,
)
from infinity_context_core.ports.clock import ClockPort

_STATE_CLOSED = "closed"
_STATE_OPEN = "open"
_STATE_HALF_OPEN = "half_open"


class _CircuitResult(Protocol):
    status: PortStatus
    diagnostics: tuple[PortDiagnostic, ...]


_ResultT = TypeVar("_ResultT", bound=_CircuitResult)


@dataclass
class ProviderCircuitBreaker:
    adapter_name: str
    operation_kind: str
    clock: ClockPort
    failure_threshold: int = 3
    reset_after_seconds: int = 60
    _state: str = _STATE_CLOSED
    _failure_count: int = 0
    _opened_at: datetime | None = None
    _last_failure_code: str | None = None
    _lock: Lock = field(default_factory=Lock)

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == _STATE_CLOSED:
                return True
            if self._state == _STATE_OPEN and self._reset_elapsed():
                self._state = _STATE_HALF_OPEN
                return True
            return self._state == _STATE_HALF_OPEN

    def record_success(self) -> None:
        with self._lock:
            self._state = _STATE_CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._last_failure_code = None

    def record_failure(self, code: str) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_code = code
            if self._failure_count >= self.failure_threshold:
                self._state = _STATE_OPEN
                self._opened_at = self.clock.now()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            opened_at = self._opened_at
            next_probe_at = opened_at.timestamp() + self.reset_after_seconds if opened_at else None
            return {
                "adapter_name": self.adapter_name,
                "operation_kind": self.operation_kind,
                "state": self._state,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "reset_after_seconds": self.reset_after_seconds,
                "opened_at": opened_at.isoformat() if opened_at else None,
                "next_probe_after_epoch_seconds": int(next_probe_at) if next_probe_at else None,
                "last_failure_code": self._last_failure_code,
            }

    def _reset_elapsed(self) -> bool:
        if self._opened_at is None:
            return True
        return (self.clock.now() - self._opened_at).total_seconds() >= self.reset_after_seconds


class CircuitBreakingEmbeddingAdapter:
    def __init__(self, inner: EmbeddingPort, circuit: ProviderCircuitBreaker) -> None:
        self._inner = inner
        self._circuit = circuit

    async def capabilities(self) -> AdapterCapabilities:
        if not self._circuit.allow_request():
            return _open_capabilities(self._circuit, supports_search=True)
        try:
            capabilities = await self._inner.capabilities()
        except Exception:
            self._circuit.record_failure("embeddings.capabilities_exception")
            raise
        _record_capability_result(self._circuit, capabilities)
        return capabilities

    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        if not self._circuit.allow_request():
            return EmbeddingResult.degraded("embeddings.circuit_open", retryable=True)
        try:
            result = await self._inner.embed_texts(texts)
        except Exception:
            self._circuit.record_failure("embeddings.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def aclose(self) -> None:
        await _close_resource(self._inner)


class CircuitBreakingVectorMemoryAdapter:
    def __init__(self, inner: VectorMemoryPort, circuit: ProviderCircuitBreaker) -> None:
        self._inner = inner
        self._circuit = circuit

    async def capabilities(self) -> AdapterCapabilities:
        if not self._circuit.allow_request():
            return _open_capabilities(
                self._circuit,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )
        try:
            capabilities = await self._inner.capabilities()
        except Exception:
            self._circuit.record_failure("vector.capabilities_exception")
            raise
        _record_capability_result(self._circuit, capabilities)
        return capabilities

    async def upsert_chunks(self, items: tuple[VectorUpsertItem, ...]) -> VectorWriteResult:
        if not self._circuit.allow_request():
            return VectorWriteResult.degraded("vector.circuit_open", retryable=True)
        try:
            result = await self._inner.upsert_chunks(items)
        except Exception:
            self._circuit.record_failure("vector.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
        if not self._circuit.allow_request():
            return VectorWriteResult.degraded("vector.circuit_open", retryable=True)
        try:
            result = await self._inner.delete_chunks(chunk_ids)
        except Exception:
            self._circuit.record_failure("vector.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def search_chunks(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None = None,
        query_vector: tuple[float, ...],
        query_text: str | None = None,
        limit: int,
    ) -> VectorSearchResult:
        if not self._circuit.allow_request():
            return VectorSearchResult.degraded("vector.circuit_open", retryable=True)
        try:
            result = await self._inner.search_chunks(
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                query_vector=query_vector,
                query_text=query_text,
                limit=limit,
            )
        except Exception:
            self._circuit.record_failure("vector.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def aclose(self) -> None:
        await _close_resource(self._inner)


class CircuitBreakingGraphMemoryAdapter:
    def __init__(self, inner: GraphMemoryPort, circuit: ProviderCircuitBreaker) -> None:
        self._inner = inner
        self._circuit = circuit

    async def capabilities(self) -> AdapterCapabilities:
        if not self._circuit.allow_request():
            return _open_capabilities(
                self._circuit,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
                supports_temporal_queries=True,
            )
        try:
            capabilities = await self._inner.capabilities()
        except Exception:
            self._circuit.record_failure("graph.capabilities_exception")
            raise
        _record_capability_result(self._circuit, capabilities)
        return capabilities

    async def upsert_fact(
        self,
        fact_id: str,
        text: str,
        metadata: dict[str, str],
    ) -> VectorWriteResult:
        if not self._circuit.allow_request():
            return VectorWriteResult.degraded("graph.circuit_open", retryable=True)
        try:
            result = await self._inner.upsert_fact(fact_id, text, metadata)
        except Exception:
            self._circuit.record_failure("graph.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def delete_fact(self, fact_id: str) -> VectorWriteResult:
        if not self._circuit.allow_request():
            return VectorWriteResult.degraded("graph.circuit_open", retryable=True)
        try:
            result = await self._inner.delete_fact(fact_id)
        except Exception:
            self._circuit.record_failure("graph.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None = None,
        query: str,
        limit: int,
    ) -> GraphSearchResult:
        if not self._circuit.allow_request():
            return GraphSearchResult.degraded("graph.circuit_open", retryable=True)
        try:
            result = await self._inner.search(
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                query=query,
                limit=limit,
            )
        except Exception:
            self._circuit.record_failure("graph.exception")
            raise
        _record_result(self._circuit, result)
        return result

    async def aclose(self) -> None:
        await _close_resource(self._inner)


async def _close_resource(resource: object) -> None:
    for method_name in ("aclose", "close"):
        close = getattr(resource, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return


def _record_result(circuit: ProviderCircuitBreaker, result: _ResultT) -> None:
    if result.status == PortStatus.OK:
        circuit.record_success()
        return
    if _retryable_diagnostic(result.diagnostics):
        circuit.record_failure(result.diagnostics[0].code)


def _record_capability_result(
    circuit: ProviderCircuitBreaker,
    capabilities: AdapterCapabilities,
) -> None:
    if capabilities.enabled and capabilities.degraded_reason not in {None, "disabled"}:
        circuit.record_failure(capabilities.degraded_reason)


def _retryable_diagnostic(diagnostics: tuple[PortDiagnostic, ...]) -> bool:
    return bool(diagnostics and diagnostics[0].retryable)


def _open_capabilities(
    circuit: ProviderCircuitBreaker,
    *,
    supports_upsert: bool = False,
    supports_delete: bool = False,
    supports_search: bool = False,
    supports_filters: bool = False,
    supports_temporal_queries: bool = False,
) -> AdapterCapabilities:
    return AdapterCapabilities(
        name=circuit.adapter_name,
        enabled=True,
        healthy=False,
        supports_upsert=supports_upsert,
        supports_delete=supports_delete,
        supports_search=supports_search,
        supports_filters=supports_filters,
        supports_temporal_queries=supports_temporal_queries,
        degraded_reason=f"{circuit.operation_kind}.circuit_open",
    )
