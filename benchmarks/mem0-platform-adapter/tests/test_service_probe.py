from __future__ import annotations

import json
from copy import deepcopy

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
    def __init__(self, status_code: int, payload: object, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.headers = {key.casefold(): value for key, value in headers.items()}
        self._body = json.dumps(payload, separators=(",", ":")).encode()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    async def aiter_raw(self, chunk_size: int | None = None):
        assert chunk_size is not None and chunk_size <= 65_536
        yield self._body


class _VettedTransport:
    def __init__(
        self,
        app_client: TestClient,
        requests: list[dict[str, object]],
        *,
        drop_refresh_operation: bool = False,
        tamper_hmac: bool = False,
    ) -> None:
        self.app_client = app_client
        self.requests = requests
        self.drop_refresh_operation = drop_refresh_operation
        self.tamper_hmac = tamper_hmac
        self.client_opened = False
        self.client_closed = False
        self.responses: list[_Response] = []

    def open_client(self, *, base_url: str, timeout_seconds: float):
        assert base_url == "https://mem0.example"
        assert timeout_seconds == 1.0
        return self

    async def __aenter__(self):
        self.client_opened = True
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
        normalized_method = method.casefold()
        request_record: dict[str, object] = {"method": normalized_method, "path": path}
        if normalized_method == "post":
            request_record.update(
                {
                    "headers": dict(headers or {}),
                    "json": dict(json or {}),
                }
            )
        self.requests.append(request_record)
        response = self.app_client.request(
            normalized_method,
            path,
            headers=headers,
            json=json,
        )
        payload = response.json()
        if self.drop_refresh_operation and path == "/openapi.json":
            payload = deepcopy(payload)
            payload["paths"].pop("/benchmark/attest-timestamp", None)
        if self.tamper_hmac and normalized_method == "post" and response.status_code < 400:
            payload["refresh_witness"]["signature"] = "0" * 64
        probe_response = _Response(response.status_code, payload, dict(response.headers))
        self.responses.append(probe_response)
        return probe_response


def _run_probe(transport: _VettedTransport) -> object:
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
        vetted_transport=transport,
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
        transport = _VettedTransport(client, requests)
        outcome = _run_probe(transport)

    assert outcome.passed is True, outcome.details
    assert transport.client_opened is True
    assert transport.client_closed is True
    assert transport.responses and all(response.closed for response in transport.responses)
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
        transport = _VettedTransport(
            client,
            requests,
            drop_refresh_operation=mode == "missing_operation",
            tamper_hmac=mode == "bad_hmac",
        )
        outcome = _run_probe(transport)

    assert outcome.passed is False
    assert transport.client_closed is True
    assert transport.responses and all(response.closed for response in transport.responses)
    assert outcome.details.get("verified_runtime_attestation") is None
    post_count = sum(item["method"] == "post" for item in requests)
    assert post_count == (0 if mode == "missing_operation" else 1)


def test_unsafe_target_rejects_before_http_client_or_token_request() -> None:
    calls: list[str] = []

    class MustNotOpenTransport:
        def open_client(self, **_: object):
            calls.append("client")
            raise AssertionError("unsafe target must not construct an HTTP client")

    outcome = probe_mem0_api(
        "http://evil.example",
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=1.0,
        refresh_runtime_attestation=True,
        benchmark_probe_token=TOKEN,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        vetted_transport=MustNotOpenTransport(),
    )

    assert outcome.passed is False
    assert outcome.reason_code == "mem0_api_target_unsafe"
    assert calls == []
