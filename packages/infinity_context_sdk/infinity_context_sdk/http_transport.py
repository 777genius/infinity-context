"""HTTP transport policy shared by the synchronous SDK facade."""

from __future__ import annotations

import time
from contextlib import suppress
from threading import Event, Thread
from typing import Any

import httpx

from infinity_context_sdk.errors import InfinityContextError, to_error


class InfinityContextHttpMixin:
    base_url: str
    token: str | None
    timeout: float
    transport: httpx.BaseTransport | None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        mutation = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        request_headers = {}
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
        if headers:
            request_headers.update(headers)
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers=request_headers,
            transport=self.transport,
        ) as client:
            try:
                response = client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    content=content,
                )
            except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
                raise InfinityContextError(
                    status_code=0,
                    code="memory.network_error",
                    message="Infinity Context request failed",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            except httpx.TransportError as exc:
                raise InfinityContextError(
                    status_code=0,
                    code="memory.network_error",
                    message=(
                        "Infinity Context request failed; retry mutations only with "
                        "the same Idempotency-Key"
                    ),
                    retryable=True,
                    unknown_commit_state=mutation,
                ) from exc
            if response.is_error:
                raise to_error(response, mutation=mutation)
            try:
                return response.json()
            except ValueError as exc:
                raise InfinityContextError(
                    status_code=response.status_code,
                    code="memory.invalid_json",
                    message=(
                        "Infinity Context returned invalid JSON; retry mutations only with "
                        "the same Idempotency-Key"
                    ),
                    retryable=mutation,
                    unknown_commit_state=mutation,
                ) from exc

    def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers=headers,
            transport=self.transport,
        ) as client:
            try:
                response = client.request(method, path, params=params)
            except httpx.TransportError as exc:
                raise InfinityContextError(
                    status_code=0,
                    code="memory.network_error",
                    message="Infinity Context request failed",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            if response.is_error:
                raise to_error(response)
            return response.content

    def _request_bounded_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any],
        max_response_bytes: int,
        timeout: float,
        cancellation_event: Event | None = None,
        absolute_deadline: float | None = None,
    ) -> dict[str, Any]:
        """Read-only bounded JSON transport used by reconciliation contracts."""

        deadline = min(
            time.monotonic() + min(self.timeout, timeout),
            absolute_deadline if absolute_deadline is not None else float("inf"),
        )
        _check_bounded_read_control(cancellation_event, deadline)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            # A scalar remains compatible with HTTPX custom transports and sets
            # one hard bound for connect/write/read/pool phases.
            timeout=max(0.001, deadline - time.monotonic()),
            headers=headers,
            transport=self.transport,
        ) as client:
            completed = Event()
            watcher = None
            if cancellation_event is not None:
                watcher = Thread(
                    target=_close_client_on_cancellation,
                    args=(client, cancellation_event, completed),
                    name="infinity-bounded-read-cancellation",
                )
                watcher.start()
            try:
                response = client.request(method, path, json=json)
            except httpx.TimeoutException as exc:
                raise InfinityContextError(
                    status_code=0,
                    code="memory.request_deadline_exceeded",
                    message="Infinity Context bounded read exceeded its absolute deadline",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            except httpx.TransportError as exc:
                _check_bounded_read_control(cancellation_event, deadline, cause=exc)
                raise InfinityContextError(
                    status_code=0,
                    code="memory.network_error",
                    message="Infinity Context bounded read failed",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            finally:
                completed.set()
                if watcher is not None:
                    watcher.join()
            _check_bounded_read_control(cancellation_event, deadline)
        if response.is_error:
            raise to_error(response, mutation=False)
        if len(response.content) > max_response_bytes:
            raise InfinityContextError(
                status_code=response.status_code,
                code="memory.response_byte_limit_exceeded",
                message="Infinity Context response exceeds the caller byte limit",
                retryable=False,
                unknown_commit_state=False,
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise InfinityContextError(
                status_code=response.status_code,
                code="memory.invalid_json",
                message="Infinity Context returned invalid JSON",
                retryable=False,
                unknown_commit_state=False,
            ) from exc
        if not isinstance(value, dict):
            raise InfinityContextError(
                status_code=response.status_code,
                code="memory.invalid_json",
                message="Infinity Context returned an invalid JSON envelope",
                retryable=False,
                unknown_commit_state=False,
            )
        _check_bounded_read_control(cancellation_event, deadline)
        return value


def _close_client_on_cancellation(
    client: httpx.Client, cancellation_event: Event, completed: Event
) -> None:
    while not completed.wait(0.01):
        if cancellation_event.is_set():
            with suppress(Exception):
                client.close()
            return


def _check_bounded_read_control(
    cancellation_event: Event | None,
    deadline: float,
    *,
    cause: BaseException | None = None,
) -> None:
    if cancellation_event is not None and cancellation_event.is_set():
        raise InfinityContextError(
            status_code=0,
            code="memory.request_cancelled",
            message="Infinity Context bounded read was cancelled",
            retryable=True,
            unknown_commit_state=False,
        ) from cause
    if time.monotonic() >= deadline:
        raise InfinityContextError(
            status_code=0,
            code="memory.request_deadline_exceeded",
            message="Infinity Context bounded read exceeded its absolute deadline",
            retryable=True,
            unknown_commit_state=False,
        ) from cause


__all__ = ("InfinityContextHttpMixin",)
