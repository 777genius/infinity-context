from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestation,
)
from infinity_context_server.memory_comparison_service_probes import (
    MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
    probe_mem0_api,
    probe_memo_api,
)
from test_memory_comparison_mem0_contract import _valid_openapi
from test_memory_comparison_mem0_runtime_attestation import (
    NONCE,
    RUN_ID,
    TARGET_URL,
    _runtime_manifest,
)

_PROBE_TOKEN = "unit-probe-token"


def test_managed_probe_refreshes_exact_same_run_contract_without_public_secrets() -> None:
    calls: list[tuple[str, str, object, object]] = []
    manifest = _witnessed_manifest()
    transport = _Transport(
        calls,
        {
            ("GET", "/openapi.json"): _Response(200, _refreshable_openapi()),
            ("POST", MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH): _Response(200, manifest),
        },
    )

    outcome = _probe(refresh=True, transport=transport)

    assert outcome.passed is True
    assert calls[1][2] == {"X-Benchmark-Probe-Token": _PROBE_TOKEN}
    details = dict(outcome.details)
    verified = details.pop("verified_runtime_attestation")
    assert isinstance(verified, VerifiedMem0RuntimeAttestation)
    manifest["runtime_mode"] = "oss"
    assert verified.payload["runtime_mode"] == "managed_platform"
    rendered = json.dumps(details, sort_keys=True)
    assert all(secret not in rendered for secret in (_PROBE_TOKEN, RUN_ID, NONCE, TARGET_URL))
    assert transport.client_closed is True
    assert all(response.closed for response in transport.responses.values())


def test_managed_probe_rejects_invalid_provenance_witness() -> None:
    manifest = _witnessed_manifest()
    witness = manifest["refresh_witness"]
    assert isinstance(witness, dict)
    witness["signature"] = "0" * 64
    transport = _Transport(
        [],
        {
            ("GET", "/openapi.json"): _Response(200, _refreshable_openapi()),
            ("POST", MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH): _Response(200, manifest),
        },
    )

    outcome = _probe(refresh=True, transport=transport)

    assert outcome.passed is False
    assert outcome.reason_code == "mem0_runtime_attestation_refresh_failed"
    assert outcome.details["verified_runtime_attestation"] is None


def test_hostname_allowlist_alone_does_not_authorize_dns_routing() -> None:
    outcome = _probe(refresh=False, transport=None)

    assert outcome.reason_code == "mem0_api_target_unsafe"


@pytest.mark.parametrize("probe_token", (None, "  "))
def test_managed_probe_fails_before_http_for_missing_auth_binding(
    probe_token: str | None,
) -> None:
    transport = _Transport([], {})
    outcome = probe_mem0_api(
        TARGET_URL,
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=0.5,
        refresh_runtime_attestation=True,
        benchmark_probe_token=probe_token,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,
    )

    assert outcome.reason_code == "mem0_runtime_attestation_binding_missing"
    assert transport.opened is False


def test_probe_rejects_oversized_raw_stream_before_json_decode() -> None:
    response = _Response(200, {}, chunks=(b"x" * 600_000, b"y" * 600_000))
    outcome = _probe(
        refresh=False,
        transport=_Transport([], {("GET", "/openapi.json"): response}),
    )

    assert outcome.reason_code == "mem0_api_openapi_probe_failed"
    assert outcome.details["error_type"] == "response_body_too_large"
    assert response.closed is True


def test_probe_rejects_non_identity_content_encoding_before_decompression() -> None:
    response = _Response(
        200,
        {},
        chunks=(b"tiny-compressed-body",),
        headers={"Content-Encoding": "gzip"},
    )
    outcome = _probe(
        refresh=False,
        transport=_Transport([], {("GET", "/openapi.json"): response}),
    )

    assert outcome.details["error_type"] == "unsupported_content_encoding"
    assert response.iterated is False


def test_refresh_200_json_array_fails_closed_inside_probe_boundary() -> None:
    transport = _Transport(
        [],
        {
            ("GET", "/openapi.json"): _Response(200, _refreshable_openapi()),
            ("POST", MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH): _Response(200, []),
        },
    )

    outcome = _probe(refresh=True, transport=transport)

    assert outcome.passed is False
    assert outcome.reason_code == "mem0_api_openapi_probe_failed"
    assert outcome.details["error_type"] == "invalid_response"


def test_total_deadline_cancels_slow_drip_and_closes_transport() -> None:
    response = _Response(
        200,
        {},
        chunks=(b"{", b'"paths":', b"{}", b"}"),
        delay_seconds=0.02,
    )
    transport = _Transport([], {("GET", "/openapi.json"): response})

    outcome = _probe(refresh=False, transport=transport, timeout=0.025)

    assert outcome.details["error_type"] == "deadline_exceeded"
    assert response.cancelled is True
    assert response.closed is True
    assert transport.client_closed is True


@pytest.mark.parametrize("timeout", (0, -1, float("nan"), float("inf"), True, "1"))
def test_probe_rejects_non_finite_or_non_positive_timeout_before_http(timeout: object) -> None:
    outcome = probe_mem0_api(
        TARGET_URL,
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=timeout,  # type: ignore[arg-type]
        allowed_target_hosts=("mem0.example.test",),
    )
    assert outcome.reason_code == "mem0_api_probe_timeout_invalid"


def test_memo_probe_requires_explicit_policy_for_local_target() -> None:
    rejected = probe_memo_api("http://127.0.0.1:8000", timeout_seconds=0.5)
    transport = _Transport(
        [],
        {
            ("GET", "/v1/health"): _Response(200, {"ok": True}),
            ("GET", "/openapi.json"): _Response(
                200, {"paths": {"/v1/context/benchmark-search": {}}}
            ),
        },
    )
    allowed = probe_memo_api(
        "http://127.0.0.1:8000",
        timeout_seconds=0.5,
        allowed_target_hosts=("127.0.0.1",),
        vetted_transport=transport,
    )

    assert rejected.reason_code == "memo_api_target_unsafe"
    assert allowed.passed is True


def test_default_literal_transport_ignores_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9998")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    options: dict[str, object] = {}
    responses = {
        ("GET", "/v1/health"): _Response(200, {"ok": True}),
        ("GET", "/openapi.json"): _Response(200, {"paths": {"/v1/context/benchmark-search": {}}}),
    }

    class _LiteralClient:
        def __init__(self, **kwargs: object) -> None:
            options.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def stream(
            self,
            method: str,
            path: str,
            **_: object,
        ) -> _Response:
            return responses[(method, path)]

    monkeypatch.setattr(httpx, "AsyncClient", _LiteralClient)

    outcome = probe_memo_api("https://93.184.216.34", timeout_seconds=0.5)

    assert outcome.passed is True
    assert options == {
        "base_url": "https://93.184.216.34",
        "timeout": 0.5,
        "follow_redirects": False,
        "trust_env": False,
    }


def _probe(
    *,
    refresh: bool,
    transport: _Transport | None,
    timeout: float = 0.5,
):
    return probe_mem0_api(
        TARGET_URL,
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=timeout,
        refresh_runtime_attestation=refresh,
        benchmark_probe_token=_PROBE_TOKEN,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,
    )


def _refreshable_openapi() -> dict[str, object]:
    payload = deepcopy(_valid_openapi())
    paths = payload["paths"]
    assert isinstance(paths, dict)
    paths[MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH] = {"post": {}}
    return payload


def _witnessed_manifest() -> dict[str, object]:
    manifest = _runtime_manifest(datetime.now(UTC))
    manifest_fingerprint = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            manifest_fingerprint,
        )
    ).encode()
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": manifest_fingerprint,
        "signature": hmac.new(_PROBE_TOKEN.encode(), message, hashlib.sha256).hexdigest(),
    }
    return manifest


class _Response:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        chunks: tuple[bytes, ...] | None = None,
        headers: dict[str, str] | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.status_code = status_code
        self.headers = {key.casefold(): value for key, value in (headers or {}).items()}
        self._chunks = chunks or (json.dumps(payload, separators=(",", ":")).encode(),)
        self.delay_seconds = delay_seconds
        self.closed = False
        self.cancelled = False
        self.iterated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    async def aiter_raw(self, chunk_size: int | None = None):
        assert chunk_size is not None and chunk_size <= 65_536
        self.iterated = True
        try:
            for chunk in self._chunks:
                if self.delay_seconds:
                    await asyncio.sleep(self.delay_seconds)
                yield chunk
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _Transport(AbstractAsyncContextManager[object]):
    def __init__(
        self,
        calls: list[tuple[str, str, object, object]],
        responses: dict[tuple[str, str], _Response],
    ) -> None:
        self.calls = calls
        self.responses = responses
        self.opened = False
        self.client_closed = False

    def open_client(self, *, base_url: str, timeout_seconds: float):
        assert base_url in {
            "https://mem0.example.test:8443",
            "http://127.0.0.1:8000",
        }
        assert timeout_seconds > 0
        return self

    async def __aenter__(self):
        self.opened = True
        return self

    async def __aexit__(self, *_: object) -> None:
        self.client_closed = True

    def stream(
        self,
        method: str,
        path: str,
        *,
        headers: object = None,
        json: object = None,
    ) -> _Response:
        self.calls.append((method, path, headers, json))
        return self.responses[(method, path)]
