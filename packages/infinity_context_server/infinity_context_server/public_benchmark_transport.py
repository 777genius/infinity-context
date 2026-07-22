"""HTTPX transport recovery for external public benchmark reads."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

_SAFE_RETRYABLE_READ_PATHS = frozenset({"/v1/context"})
_MAX_ATTEMPTS = 2
_DEFAULT_RETRY_DELAY_SECONDS = 0.05
_MAX_RETRY_DELAY_SECONDS = 1.0


class HttpBenchmarkAdapter:
    """Adapt HTTPX with bounded recovery for proven pre-delivery failures."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        retry_delay_seconds: float = _DEFAULT_RETRY_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < retry_delay_seconds <= _MAX_RETRY_DELAY_SECONDS:
            raise ValueError(
                "retry_delay_seconds must be greater than zero and at most "
                f"{_MAX_RETRY_DELAY_SECONDS}"
            )
        self._client = client
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> Any:
        attempts = _MAX_ATTEMPTS if path in _SAFE_RETRYABLE_READ_PATHS else 1
        for attempt in range(1, attempts + 1):
            try:
                return self._client.post(
                    path,
                    json=dict(json_body),
                    headers=dict(headers),
                )
            except httpx.HTTPError as exc:
                if type(exc) not in _PRE_DELIVERY_ERROR_TYPES or attempt == attempts:
                    raise
                self._sleep(self._retry_delay_seconds)
        raise AssertionError("unreachable")


_PRE_DELIVERY_ERROR_TYPES = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.PoolTimeout,
)
