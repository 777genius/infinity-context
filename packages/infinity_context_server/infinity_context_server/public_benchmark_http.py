"""HTTP helpers for public benchmark execution."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_server.public_benchmark_models import (
    BenchmarkHttpClientPort,
    BenchmarkHttpResponsePort,
)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def post_required(
    adapter: BenchmarkHttpClientPort,
    path: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    idempotency_key: str | None = None,
) -> BenchmarkHttpResponsePort:
    request_headers = dict(headers)
    if idempotency_key:
        request_headers["Idempotency-Key"] = idempotency_key[:120]
    response = adapter.post(path, json_body=payload, headers=request_headers)
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{path} returned HTTP {response.status_code}")
    return response


def response_data(response: BenchmarkHttpResponsePort) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}
