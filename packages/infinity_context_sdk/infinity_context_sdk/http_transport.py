"""HTTP transport policy shared by the synchronous SDK facade."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from threading import Event
from typing import Any

import httpx

from infinity_context_sdk.errors import InfinityContextError, to_error


class InfinityContextHttpMixin:
    base_url: str
    token: str | None
    timeout: float
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None

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
            time.monotonic() + timeout,
            absolute_deadline if absolute_deadline is not None else float("inf"),
        )
        _check_bounded_read_control(cancellation_event, deadline)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = _run_async_exchange(
                _bounded_async_exchange(
                    method=method,
                    path=path,
                    json=json,
                    base_url=self.base_url.rstrip("/"),
                    headers=headers,
                    phase_timeout=self.timeout,
                    deadline=deadline,
                    cancellation_event=cancellation_event,
                    transport=self.transport,
                ),
            )
        except httpx.TimeoutException as exc:
            raise _deadline_error() from exc
        except httpx.TransportError as exc:
            _check_bounded_read_control(cancellation_event, deadline, cause=exc)
            raise InfinityContextError(
                status_code=0,
                code="memory.network_error",
                message="Infinity Context bounded read failed",
                retryable=True,
                unknown_commit_state=False,
            ) from exc
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


async def _bounded_async_exchange(
    *,
    method: str,
    path: str,
    json: dict[str, Any],
    base_url: str,
    headers: dict[str, str],
    phase_timeout: float,
    deadline: float,
    cancellation_event: Event | None,
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    """Race one async exchange against caller cancellation and a total deadline."""

    async_transport = _async_transport(transport)
    client = httpx.AsyncClient(
        base_url=base_url,
        timeout=max(0.001, min(phase_timeout, deadline - time.monotonic())),
        headers=headers,
        transport=async_transport,
    )
    if cancellation_event is not None and cancellation_event.is_set():
        await _close_before_control_error(client, _cancellation_error())
    if time.monotonic() >= deadline:
        await _close_before_control_error(client, _deadline_error())
    request_task = asyncio.create_task(
        client.request(method, path, json=json),
        name="infinity-bounded-read-request",
    )
    deadline_task = asyncio.create_task(
        _wait_for_deadline(deadline),
        name="infinity-bounded-read-deadline",
    )
    cancellation_task = (
        asyncio.create_task(
            _wait_for_cancellation(cancellation_event),
            name="infinity-bounded-read-cancellation",
        )
        if cancellation_event is not None
        else None
    )
    control_tasks = [deadline_task]
    if cancellation_task is not None:
        control_tasks.append(cancellation_task)
    control_error: InfinityContextError | None = None
    cleanup_error: BaseException | None = None
    try:
        await asyncio.wait([request_task, *control_tasks], return_when=asyncio.FIRST_COMPLETED)
        # Control has deterministic precedence if it became observable before the
        # synchronous facade can return the response.
        if cancellation_event is not None and cancellation_event.is_set():
            await _cancel_and_wait(request_task)
            control_error = _cancellation_error()
        elif deadline_task.done() or time.monotonic() >= deadline:
            await _cancel_and_wait(request_task)
            control_error = _deadline_error()
    finally:
        for task in control_tasks:
            task.cancel()
        await asyncio.gather(*control_tasks, return_exceptions=True)
        if not request_task.done():
            await _cancel_and_wait(request_task)
        try:
            await client.aclose()
        except BaseException as exc:  # Cleanup is awaited but cannot mask caller control.
            cleanup_error = exc
    if control_error is not None:
        raise control_error from cleanup_error
    if cleanup_error is not None:
        raise cleanup_error
    return await request_task


async def _close_before_control_error(
    client: httpx.AsyncClient,
    error: InfinityContextError,
) -> None:
    try:
        await client.aclose()
    except BaseException as cleanup_error:
        raise error from cleanup_error
    raise error


def _run_async_exchange(
    coroutine: Coroutine[Any, Any, httpx.Response],
) -> httpx.Response:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    coroutine.close()
    raise RuntimeError(
        "synchronous Infinity Context SDK methods cannot run inside an active event loop"
    )


def _async_transport(
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None,
) -> httpx.AsyncBaseTransport | None:
    if transport is None or isinstance(transport, httpx.AsyncBaseTransport):
        return transport
    return _SyncTransportAdapter(transport)


class _SyncTransportAdapter(httpx.AsyncBaseTransport):
    """Compatibility bridge for immediate synchronous SDK test transports."""

    def __init__(self, transport: httpx.BaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        sync_request = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            content=content,
            extensions=request.extensions,
        )
        response = self._transport.handle_request(sync_request)
        try:
            response_content = response.read()
        finally:
            response.close()
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response_content,
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        self._transport.close()


async def _wait_for_cancellation(cancellation_event: Event) -> None:
    while not cancellation_event.is_set():
        await asyncio.sleep(0.005)


async def _wait_for_deadline(deadline: float) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        await asyncio.sleep(remaining)


async def _cancel_and_wait(task: asyncio.Task[httpx.Response]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _cancellation_error() -> InfinityContextError:
    return InfinityContextError(
        status_code=0,
        code="memory.request_cancelled",
        message="Infinity Context bounded read was cancelled",
        retryable=True,
        unknown_commit_state=False,
    )


def _deadline_error() -> InfinityContextError:
    return InfinityContextError(
        status_code=0,
        code="memory.request_deadline_exceeded",
        message="Infinity Context bounded read exceeded its absolute deadline",
        retryable=True,
        unknown_commit_state=False,
    )


def _check_bounded_read_control(
    cancellation_event: Event | None,
    deadline: float,
    *,
    cause: BaseException | None = None,
) -> None:
    if cancellation_event is not None and cancellation_event.is_set():
        raise _cancellation_error() from cause
    if time.monotonic() >= deadline:
        raise _deadline_error() from cause


__all__ = ("InfinityContextHttpMixin",)
