from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from root_contract_import import import_root_contract
from test_app import FakePlatform, _sentinel_readback

from mem0_platform_adapter import manifest as manifest_module
from mem0_platform_adapter.app import create_app

pytestmark = pytest.mark.contract
runtime_attestation = import_root_contract(
    "infinity_context_server.memory_comparison_mem0_runtime_attestation",
    allow_module_level=True,
)
service_probes = import_root_contract(
    "infinity_context_server.memory_comparison_service_probes",
    allow_module_level=True,
)
VerifiedMem0RuntimeAttestation = runtime_attestation.VerifiedMem0RuntimeAttestation
probe_mem0_api = service_probes.probe_mem0_api

RUN_ID = "managed-full-run-1"
NONCE = "ab" * 32
TOKEN = "dedicated-probe-token"


def _configure_publishable_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_SOURCE_REVISION", "b" * 40)
    monkeypatch.setattr(
        manifest_module,
        "_installed_sdk_provenance",
        lambda: {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "expected_version": "2.0.14",
            "pin_matches": True,
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": (
                    "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
                ),
                "passed": True,
            },
        },
    )


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def iter_bytes(self, *, chunk_size: int):
        del chunk_size
        yield json.dumps(self._payload).encode()


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    app_client: TestClient,
    requests: list[dict[str, object]],
    *,
    drop_refresh_operation: bool = False,
    tamper_hmac: bool = False,
) -> None:
    class Client:
        def __init__(self, **_: object) -> None:
            requests.append({"method": "client_init"})

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def _request(self, method: str, path: str, **kwargs: Any) -> _Response:
            normalized_method = method.casefold()
            request_record: dict[str, object] = {"method": normalized_method, "path": path}
            if normalized_method == "post":
                request_record.update(
                    {
                        "headers": dict(kwargs.get("headers") or {}),
                        "json": dict(kwargs.get("json") or {}),
                    }
                )
            requests.append(request_record)
            response = app_client.request(
                normalized_method,
                path,
                headers=kwargs.get("headers"),
                json=kwargs.get("json"),
            )
            payload = response.json()
            if drop_refresh_operation and path == "/openapi.json":
                payload = deepcopy(payload)
                payload["paths"].pop("/benchmark/attest-timestamp", None)
            if tamper_hmac and normalized_method == "post" and response.status_code < 400:
                payload["refresh_witness"]["signature"] = "0" * 64
            return _Response(response.status_code, payload)

        def get(self, path: str) -> _Response:
            return self._request("get", path)

        def post(self, path: str, **kwargs: Any) -> _Response:
            return self._request("post", path, **kwargs)

        def stream(self, method: str, path: str, **kwargs: Any) -> _Response:
            return self._request(method, path, **kwargs)

    monkeypatch.setattr(httpx, "Client", Client)


def _run_probe() -> object:
    return probe_mem0_api(
        "https://mem0.example/ignored-base-path",
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=1.0,
        refresh_runtime_attestation=True,
        benchmark_probe_token=TOKEN,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        allowed_target_hosts=("mem0.example",),
    )


def test_valid_signed_refresh_yields_typed_target_bound_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", TOKEN)
    _configure_publishable_manifest(monkeypatch)
    requests: list[dict[str, object]] = []
    platform = FakePlatform(readback=_sentinel_readback())
    with TestClient(
        create_app(
            platform,
            sleeper=lambda _: None,
            token_factory=lambda: "fixed",
            attest_on_startup=False,
        )
    ) as client:
        _install_client(monkeypatch, client, requests)
        outcome = _run_probe()

    assert outcome.passed is True, outcome.details
    verified = outcome.details["verified_runtime_attestation"]
    assert isinstance(verified, VerifiedMem0RuntimeAttestation)
    post = next(item for item in requests if item["method"] == "post")
    assert post["headers"] == {"X-Benchmark-Probe-Token": TOKEN}
    assert post["json"]["run_id"] == RUN_ID
    assert post["json"]["probe_nonce"] == NONCE
    assert post["json"]["target_identity_sha256"] == verified.payload["target_identity_sha256"]
    public = str(outcome.details["runtime_attestation"])
    assert TOKEN not in public
    assert "https://mem0.example" not in public


@pytest.mark.parametrize("mode", ("missing_operation", "bad_hmac"))
def test_invalid_refresh_contract_or_hmac_never_yields_typed_capability(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", TOKEN)
    _configure_publishable_manifest(monkeypatch)
    requests: list[dict[str, object]] = []
    platform = FakePlatform(readback=_sentinel_readback())
    with TestClient(
        create_app(
            platform,
            sleeper=lambda _: None,
            token_factory=lambda: "fixed",
            attest_on_startup=False,
        )
    ) as client:
        _install_client(
            monkeypatch,
            client,
            requests,
            drop_refresh_operation=mode == "missing_operation",
            tamper_hmac=mode == "bad_hmac",
        )
        outcome = _run_probe()

    assert outcome.passed is False
    assert outcome.details.get("verified_runtime_attestation") is None
    post_count = sum(item["method"] == "post" for item in requests)
    assert post_count == (0 if mode == "missing_operation" else 1)


def test_unsafe_target_rejects_before_http_client_or_token_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fail_client(**_: object) -> None:
        calls.append("client")
        raise AssertionError("unsafe target must not construct an HTTP client")

    monkeypatch.setattr(httpx, "Client", fail_client)
    outcome = probe_mem0_api(
        "http://evil.example",
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=1.0,
        refresh_runtime_attestation=True,
        benchmark_probe_token=TOKEN,
        run_id=RUN_ID,
        probe_nonce=NONCE,
    )

    assert outcome.passed is False
    assert outcome.reason_code == "mem0_api_target_unsafe"
    assert calls == []
