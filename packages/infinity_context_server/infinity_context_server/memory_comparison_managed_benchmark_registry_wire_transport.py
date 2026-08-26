"""Bounded transport timing and exact JSON envelope parsing for the registry."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import fail

MAX_RESPONSE_BYTES = 2_000_000


def remaining_io_timeout(
    *,
    deadline: datetime,
    timeout_seconds: float,
    clock: Callable[[], datetime],
) -> float:
    """Bound the next synchronous I/O phase without claiming total cancellation."""

    remaining = (deadline.astimezone(UTC) - _clock_utc(clock)).total_seconds()
    if not math.isfinite(remaining) or remaining <= 0:
        fail("managed_benchmark_registry_deadline_expired")
    return min(float(timeout_seconds), remaining)


def fresh_io_deadline(
    *,
    timeout_seconds: float,
    clock: Callable[[], datetime],
) -> datetime:
    """Create one fresh finite wall-clock window for a retryable operation."""

    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) <= 0
    ):
        fail("managed_benchmark_registry_recovery_window_invalid")
    try:
        return _clock_utc(clock) + timedelta(seconds=float(timeout_seconds))
    except (OverflowError, ValueError):
        fail("managed_benchmark_registry_recovery_window_invalid")


def read_json_envelope(
    response: httpx.Response,
    *,
    deadline: datetime,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Read a bounded exact JSON envelope while enforcing the absolute deadline."""

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_type != "application/json" or encoding not in {"", "identity"}:
        fail("managed_benchmark_registry_response_invalid")
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            fail("managed_benchmark_registry_response_invalid")
        if declared < 0 or declared > MAX_RESPONSE_BYTES:
            fail("managed_benchmark_registry_response_too_large")

    body = bytearray()
    iterator = iter(response.iter_bytes())
    while True:
        _require_before_deadline(deadline, clock)
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            fail("managed_benchmark_registry_response_too_large")
        _require_before_deadline(deadline, clock)
    decoded = _decode_json(bytes(body))
    envelope = _exact_object(
        decoded,
        frozenset({"data"}),
        "managed_benchmark_registry_response_invalid",
    )
    return _object(envelope["data"])


def _require_before_deadline(
    deadline: datetime,
    clock: Callable[[], datetime],
) -> None:
    remaining_io_timeout(deadline=deadline, timeout_seconds=float("inf"), clock=clock)


def _clock_utc(clock: Callable[[], datetime]) -> datetime:
    try:
        now = clock()
    except KeyboardInterrupt:
        raise KeyboardInterrupt() from None
    except SystemExit as error:
        safe_code = error.code if type(error.code) is int or error.code is None else 1
        raise SystemExit(safe_code) from None
    except BaseException:
        fail("managed_benchmark_registry_clock_failed")
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        fail("managed_benchmark_registry_clock_failed")
    return now.astimezone(UTC)


def _decode_json(body: bytes) -> object:
    try:
        return json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("managed_benchmark_registry_response_invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail("managed_benchmark_registry_response_invalid")
        result[key] = value
    return result


def _exact_object(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    result = _object(value)
    if set(result) != keys:
        fail(code)
    return result


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        fail("managed_benchmark_registry_response_invalid")
    return value


__all__ = ("fresh_io_deadline", "read_json_envelope", "remaining_io_timeout")
