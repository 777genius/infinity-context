from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

import mem0_platform_adapter.app as app_module
from mem0_platform_adapter import manifest as manifest_module
from mem0_platform_adapter.app import create_app
from mem0_platform_adapter.models import EventSnapshot
from mem0_platform_adapter.port import UnconfiguredPlatformPort

_INGRESS_API_KEY = "adapter-ingress-test-key"
_SOURCE_SHA256 = "a" * 64
_SENTINEL_SHA256 = "ed6f4f0c92e7994b6f9ceaba666f1bd0b0ada51f59a0227973c75caf3d30b433"


@pytest.fixture(autouse=True)
def _configured_ingress_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS_API_KEY)


@dataclass
class FakePlatform:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    readback: dict[str, Any] = field(default_factory=lambda: _sentinel_readback())

    @property
    def configured(self) -> bool:
        return True

    def add(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("add", kwargs))
        return {"event_id": "evt-1"}

    def get_event(self, event_id: str) -> EventSnapshot:
        self.calls.append(("get_event", {"event_id": event_id}))
        return EventSnapshot(status="SUCCEEDED")

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        page: int,
        page_size: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            (
                "get_all",
                {"filters": filters, "page": page, "page_size": page_size},
            )
        )
        return self.readback

    def search(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("search", kwargs))
        return {"results": []}

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        self.calls.append(("delete", {"user_id": user_id, "run_id": run_id}))
        self.readback = {"results": []}
        return True


def _add_payload() -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": "Caroline attended the group."}],
        "user_id": "benchmark-user",
        "run_id": "run-1",
        "metadata": {
            "source_id": "conv0/session-1/turn-1",
            "source_sha256": _SOURCE_SHA256,
        },
        "timestamp": 1672531200,
    }


def _search_payload() -> dict[str, Any]:
    return {
        "query": "when?",
        "filters": {"user_id": "benchmark-user"},
        "limit": 10,
    }


def _sentinel_readback() -> dict[str, Any]:
    return {
        "results": [
            {
                "id": "sentinel-memory",
                "memory": "Mem0 timestamp attestation sentinel.",
                "created_at": "2023-01-01T00:00:00Z",
                "metadata": {
                    "source_id": "mem0-attest-source-fixed",
                    "source_sha256": _SENTINEL_SHA256,
                },
            }
        ]
    }


def _data_plane_cases() -> tuple[tuple[str, str, dict[str, Any]], ...]:
    return (
        ("POST", "/memories", {"json": _add_payload()}),
        ("POST", "/search", {"json": _search_payload()}),
        (
            "DELETE",
            "/memories",
            {"params": {"user_id": "benchmark-user", "run_id": "run-1"}},
        ),
    )


@pytest.mark.parametrize(("method", "path", "request_kwargs"), _data_plane_cases())
def test_data_plane_fails_closed_when_server_ingress_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    request_kwargs: dict[str, Any],
) -> None:
    monkeypatch.delenv("MEM0_ADAPTER_INGRESS_API_KEY", raising=False)
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.request(method, path, **request_kwargs)

    assert response.status_code == 503
    assert response.json() == {"detail": "missing_adapter_ingress_api_key"}
    assert platform.calls == []


def test_data_plane_fails_closed_when_server_ingress_key_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", "   ")
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.post(
        "/search",
        headers={"X-API-Key": "   "},
        json=_search_payload(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "missing_adapter_ingress_api_key"}
    assert platform.calls == []


def test_data_plane_fails_closed_for_whitespace_padded_server_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", " padded-key ")
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.post(
        "/search",
        headers={"X-API-Key": "padded-key"},
        json=_search_payload(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "missing_adapter_ingress_api_key"}
    assert platform.calls == []


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"X-API-Key": "wrong"},
        {"Authorization": f"Bearer {_INGRESS_API_KEY}"},
        {"X-API-Key": f"{_INGRESS_API_KEY} "},
    ),
    ids=("missing", "wrong", "wrong-header", "not-exact"),
)
@pytest.mark.parametrize(("method", "path", "request_kwargs"), _data_plane_cases())
def test_data_plane_rejects_missing_wrong_or_non_exact_credentials(
    headers: dict[str, str],
    method: str,
    path: str,
    request_kwargs: dict[str, Any],
) -> None:
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.request(method, path, headers=headers, **request_kwargs)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_adapter_ingress_api_key"}
    assert platform.calls == []


def test_data_plane_rejects_ambiguous_duplicate_api_key_headers() -> None:
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.post(
        "/search",
        headers=[
            ("X-API-Key", _INGRESS_API_KEY),
            ("X-API-Key", "wrong"),
        ],
        json=_search_payload(),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_adapter_ingress_api_key"}
    assert platform.calls == []


def test_authentication_precedes_body_validation() -> None:
    platform = FakePlatform()
    client = TestClient(create_app(platform, attest_on_startup=False))

    response = client.post("/memories", json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_adapter_ingress_api_key"}
    assert platform.calls == []


def test_ingress_key_uses_constant_time_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bytes, bytes]] = []
    real_compare = app_module.secrets.compare_digest

    def capture_compare(presented: bytes, expected: bytes) -> bool:
        observed.append((presented, expected))
        return real_compare(presented, expected)

    monkeypatch.setattr(app_module.secrets, "compare_digest", capture_compare)
    client = TestClient(create_app(FakePlatform(), attest_on_startup=False))

    response = client.post(
        "/search",
        headers={"X-API-Key": "wrong"},
        json=_search_payload(),
    )

    assert response.status_code == 401
    assert observed == [(b"wrong", _INGRESS_API_KEY.encode())]


def test_openapi_declares_data_plane_only_api_key_policy() -> None:
    schema = create_app(UnconfiguredPlatformPort()).openapi()
    expected_security = [{"Mem0AdapterIngressApiKey": []}]

    assert schema["components"]["securitySchemes"]["Mem0AdapterIngressApiKey"] == {
        "type": "apiKey",
        "description": "Dedicated authentication for benchmark data-plane operations.",
        "in": "header",
        "name": "X-API-Key",
    }
    for path, method in (
        ("/memories", "post"),
        ("/memories", "delete"),
        ("/search", "post"),
    ):
        assert schema["paths"][path][method]["security"] == expected_security
    for path, method in (
        ("/health", "get"),
        ("/benchmark/capabilities", "get"),
        ("/benchmark/auth-challenge", "post"),
        ("/benchmark/attest-timestamp", "post"),
    ):
        assert "security" not in schema["paths"][path][method]


def test_control_plane_policy_is_public_or_probe_token_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_ADAPTER_INGRESS_API_KEY", raising=False)
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", "dedicated-probe-token")
    platform = FakePlatform()
    app = create_app(
        platform,
        sleeper=lambda _: None,
        token_factory=lambda: "fixed",
        attest_on_startup=False,
    )

    with TestClient(app) as client:
        health = client.get("/health")
        capabilities = client.get("/benchmark/capabilities")
        challenge = client.post(
            "/benchmark/auth-challenge",
            headers={"X-Benchmark-Probe-Token": "dedicated-probe-token"},
            json={"nonce": "ab" * 32},
        )
        refresh = client.post(
            "/benchmark/attest-timestamp",
            headers={"X-Benchmark-Probe-Token": "dedicated-probe-token"},
            json={
                "run_id": "managed-run-1",
                "probe_nonce": "cd" * 32,
                "target_identity_sha256": "ef" * 32,
            },
        )

    assert health.status_code == 200
    assert health.json()["ingress_auth_configured"] is False
    assert capabilities.status_code == 200
    assert challenge.status_code == 200
    assert refresh.status_code == 200
    assert [name for name, _ in platform.calls] == [
        "add",
        "get_event",
        "get_all",
        "delete",
        "get_all",
    ]


def test_health_never_reports_ready_without_ingress_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_ADAPTER_INGRESS_API_KEY", raising=False)
    monkeypatch.setenv("MEM0_ADAPTER_SOURCE_REVISION", "a" * 40)
    monkeypatch.setattr(
        manifest_module,
        "_installed_sdk_provenance",
        lambda: {"pin_matches": True},
    )
    app = create_app(
        FakePlatform(),
        sleeper=lambda _: None,
        token_factory=lambda: "fixed",
    )

    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert health["configured"] is True
    assert health["attestation_status"] == "passed"
    assert health["ingress_auth_configured"] is False


def test_ingress_key_is_never_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "unique-never-rendered-ingress-secret"
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", secret)
    client = TestClient(create_app(FakePlatform(), attest_on_startup=False))

    rendered = str(
        (
            client.get("/health").json(),
            client.get("/benchmark/capabilities").json(),
            client.get("/openapi.json").json(),
        )
    )

    assert secret not in rendered
