"""HTTP transport policy shared by the synchronous SDK facade."""

from __future__ import annotations

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


__all__ = ("InfinityContextHttpMixin",)
