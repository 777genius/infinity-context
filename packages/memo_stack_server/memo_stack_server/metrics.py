"""In-process runtime counters for operational diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

_MAX_LATENCY_SAMPLES = 1000


@dataclass
class RuntimeMetrics:
    _context_request_count: int = 0
    _context_degraded_count: int = 0
    _stale_hydration_drop_count: int = 0
    _context_latency_ms: list[float] = field(default_factory=list)
    _last_context_trace: dict[str, Any] | None = None
    _lock: Lock = field(default_factory=Lock)

    def record_context(
        self,
        *,
        latency_ms: float,
        diagnostics: dict[str, object],
        request_id: str | None = None,
        use_case: str = "context",
        scope: dict[str, object] | None = None,
    ) -> None:
        degraded = _context_is_degraded(diagnostics)
        stale_drops = _int_diagnostic(diagnostics, "stale_vector_drop_count") + _int_diagnostic(
            diagnostics,
            "stale_graph_drop_count",
        )
        trace = _context_trace(
            request_id=request_id,
            use_case=use_case,
            latency_ms=latency_ms,
            diagnostics=diagnostics,
            degraded=degraded,
            scope=scope,
        )
        with self._lock:
            self._context_request_count += 1
            if degraded:
                self._context_degraded_count += 1
            self._stale_hydration_drop_count += stale_drops
            self._context_latency_ms.append(max(0.0, float(latency_ms)))
            if len(self._context_latency_ms) > _MAX_LATENCY_SAMPLES:
                del self._context_latency_ms[: len(self._context_latency_ms) - _MAX_LATENCY_SAMPLES]
            self._last_context_trace = trace

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            request_count = self._context_request_count
            degraded_count = self._context_degraded_count
            stale_drop_count = self._stale_hydration_drop_count
            samples = tuple(self._context_latency_ms)
            last_trace = dict(self._last_context_trace) if self._last_context_trace else None
        return {
            "request_count": request_count,
            "p95_latency_ms": _p95(samples),
            "degraded_count": degraded_count,
            "degraded_rate": _rate(degraded_count, request_count),
            "stale_hydration_drop_count": stale_drop_count,
            "collection": "in_memory",
            "last_trace": last_trace,
        }


def _context_is_degraded(diagnostics: dict[str, object]) -> bool:
    if diagnostics.get("retrieval_disabled") is True:
        return True
    return any(
        diagnostics.get(key) == "degraded"
        for key in ("vector_status", "graph_status", "rag_status")
    )


def _int_diagnostic(diagnostics: dict[str, object], key: str) -> int:
    value = diagnostics.get(key)
    return value if isinstance(value, int) else 0


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _p95(samples: tuple[float, ...]) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 2)


def _context_trace(
    *,
    request_id: str | None,
    use_case: str,
    latency_ms: float,
    diagnostics: dict[str, object],
    degraded: bool,
    scope: dict[str, object] | None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "request_id": request_id,
        "span": "memory.context.request",
        "use_case": use_case,
        "status": "degraded" if degraded else "ok",
        "duration_ms": round(max(0.0, float(latency_ms)), 2),
        "candidate_count": _int_diagnostic(diagnostics, "items_considered"),
        "hydrated_count": _int_diagnostic(diagnostics, "items_used"),
        "degraded_reason": _degraded_reason(diagnostics),
    }
    if scope:
        trace.update(scope)
    return trace


def _degraded_reason(diagnostics: dict[str, object]) -> str | None:
    for key in (
        "vector_degraded_reason",
        "graph_degraded_reason",
        "rag_degraded_reason",
    ):
        value = diagnostics.get(key)
        if isinstance(value, str) and value:
            return value
    if diagnostics.get("retrieval_disabled") is True:
        return "retrieval_disabled"
    return None
