"""Low-level request and one-shot close mechanics for the registry adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpError,
    fail,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_wire_transport import (
    read_json_envelope,
    remaining_io_timeout,
)


def request_registry_json(
    adapter: Any,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None,
    idempotency_key: str | None,
    accepted_statuses: frozenset[int],
    deadline: datetime,
    on_dispatch: Callable[[], None],
    missing_statuses: frozenset[int] = frozenset(),
) -> tuple[dict[str, object], int]:
    timeout = remaining_io_timeout(
        deadline=deadline,
        timeout_seconds=float(adapter._config.timeout_seconds),
        clock=adapter._config.clock,
    )
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    url = f"{adapter._config.base_url.rstrip('/')}/{path}"
    try:
        on_dispatch()
        response_context = (
            adapter._client.stream(method, url, headers=headers, timeout=timeout)
            if payload is None
            else adapter._client.stream(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        )
        with response_context as response:
            if response.status_code in missing_statuses:
                return {}, response.status_code
            if response.status_code not in accepted_statuses:
                if 500 <= response.status_code <= 599:
                    fail("managed_benchmark_registry_response_retryable")
                fail("managed_benchmark_registry_response_rejected")
            data = read_json_envelope(
                response,
                deadline=deadline,
                clock=adapter._config.clock,
            )
            status = response.status_code
    except ManagedBenchmarkRegistryHttpError:
        raise
    except KeyboardInterrupt:
        raise KeyboardInterrupt() from None
    except SystemExit as error:
        safe_code = error.code if type(error.code) is int or error.code is None else 1
        raise SystemExit(safe_code) from None
    except BaseException:
        fail("managed_benchmark_registry_request_failed")
    return data, status


def close_registry_transport(adapter: Any, *, suppress_failure: bool) -> None:
    with adapter._lock:
        if adapter._close_attempted:
            return
        adapter._close_attempted = True
    try:
        adapter._client.close()
    except BaseException as error:
        with adapter._lock:
            adapter._close_warning_code = "managed_benchmark_registry_close_failed"
        if suppress_failure:
            return
        if isinstance(error, KeyboardInterrupt):
            raise KeyboardInterrupt() from None
        if isinstance(error, SystemExit):
            safe_code = error.code if type(error.code) is int or error.code is None else 1
            raise SystemExit(safe_code) from None
        fail("managed_benchmark_registry_close_failed")


__all__ = ("close_registry_transport", "request_registry_json")
