"""In-process runtime counters for operational diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    _storage_maintenance_run_count: int = 0
    _storage_maintenance_skipped_count: int = 0
    _storage_maintenance_degraded_count: int = 0
    _last_storage_maintenance_trace: dict[str, Any] | None = None
    _last_storage_maintenance_started_at: datetime | None = None
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

    def storage_maintenance_due(self, *, now: datetime, interval_seconds: int) -> bool:
        interval = timedelta(seconds=max(60, int(interval_seconds)))
        with self._lock:
            last_started_at = self._last_storage_maintenance_started_at
        if last_started_at is None:
            return True
        return now - _align_tz(last_started_at, now) >= interval

    def record_storage_maintenance(
        self,
        *,
        trace: dict[str, Any],
        started_at: datetime,
    ) -> None:
        status = str(trace.get("status") or "unknown")
        safe_trace = _storage_maintenance_trace(trace)
        with self._lock:
            self._storage_maintenance_run_count += 1
            if status == "skipped":
                self._storage_maintenance_skipped_count += 1
            elif status != "ok":
                self._storage_maintenance_degraded_count += 1
            self._last_storage_maintenance_started_at = started_at
            self._last_storage_maintenance_trace = safe_trace

    def storage_maintenance_snapshot(self) -> dict[str, Any]:
        with self._lock:
            run_count = self._storage_maintenance_run_count
            skipped_count = self._storage_maintenance_skipped_count
            degraded_count = self._storage_maintenance_degraded_count
            last_trace = (
                dict(self._last_storage_maintenance_trace)
                if self._last_storage_maintenance_trace
                else None
            )
        return {
            "run_count": run_count,
            "skipped_count": skipped_count,
            "degraded_count": degraded_count,
            "degraded_rate": _rate(degraded_count, run_count),
            "last_trace": last_trace,
        }

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
        _component_is_degraded(
            diagnostics,
            status_key=status_key,
            reason_key=reason_key,
        )
        for status_key, reason_key in (
            ("vector_status", "vector_degraded_reason"),
            ("graph_status", "graph_degraded_reason"),
            ("rag_status", "rag_degraded_reason"),
        )
    )


def _component_is_degraded(
    diagnostics: dict[str, object],
    *,
    status_key: str,
    reason_key: str,
) -> bool:
    if diagnostics.get(status_key) != "degraded":
        return False
    return not _is_disabled_reason(diagnostics.get(reason_key))


def _is_disabled_reason(value: object) -> bool:
    if not isinstance(value, str):
        return False
    reason = value.strip().casefold()
    return reason == "disabled" or reason.endswith(".disabled")


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


def _align_tz(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value


def _storage_maintenance_trace(trace: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "span",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "storage_backend",
        "maintenance_enabled",
        "lock_backend",
        "lock_acquired",
        "lock_skipped",
        "cleanup_status",
        "cleanup_dry_run",
        "cleanup_scanned_count",
        "cleanup_unsafe_storage_key_count",
        "cleanup_orphan_candidate_count",
        "cleanup_deleted_count",
        "cleanup_delete_error_count",
        "integrity_status",
        "integrity_scanned_count",
        "integrity_missing_count",
        "integrity_byte_size_mismatch_count",
        "integrity_checksum_mismatch_count",
        "integrity_checksum_skipped_count",
        "integrity_read_error_count",
        "integrity_stat_error_count",
        "integrity_unsafe_storage_key_count",
        "safe_error_code",
    }
    safe: dict[str, Any] = {}
    for key, value in trace.items():
        if key not in allowed_keys:
            continue
        safe[key] = _safe_metric_value(value)
    safe["storage_keys_are_redacted"] = True
    return safe


def _safe_metric_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:120]
