from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from root_contract_import import import_root_contract

from mem0_platform_adapter import manifest as manifest_module
from mem0_platform_adapter.app import create_app
from mem0_platform_adapter.models import EventSnapshot
from mem0_platform_adapter.port import UnconfiguredPlatformPort
from mem0_platform_adapter.service import PollingPolicy

_INGRESS_API_KEY = "adapter-ingress-test-key"
_INGRESS_HEADERS = {"X-API-Key": _INGRESS_API_KEY}
_SOURCE_SHA256 = "a" * 64
_SENTINEL_SHA256 = "ed6f4f0c92e7994b6f9ceaba666f1bd0b0ada51f59a0227973c75caf3d30b433"


@pytest.fixture(autouse=True)
def _configured_ingress_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_INGRESS_API_KEY", _INGRESS_API_KEY)


def _authorized_client(app: Any) -> TestClient:
    return TestClient(app, headers=_INGRESS_HEADERS)


@dataclass
class FakePlatform:
    is_configured: bool = True
    delete_result: bool = True
    events: list[EventSnapshot] = field(default_factory=lambda: [EventSnapshot(status="SUCCEEDED")])
    readback: dict[str, Any] = field(default_factory=lambda: {"results": []})
    readback_pages: dict[int, dict[str, Any]] | None = None
    search_response: dict[str, Any] = field(default_factory=lambda: {"results": []})
    add_response: dict[str, Any] = field(default_factory=lambda: {"event_id": "evt-1"})
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return self.is_configured

    def add(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("add", kwargs))
        return self.add_response

    def get_event(self, event_id: str) -> EventSnapshot:
        self.calls.append(("get_event", {"event_id": event_id}))
        return self.events.pop(0)

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
        if self.readback_pages is not None:
            return self.readback_pages[page]
        return self.readback

    def search(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("search", kwargs))
        return self.search_response

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        self.calls.append(("delete", {"user_id": user_id, "run_id": run_id}))
        if self.delete_result:
            self.readback = {"results": []}
        return self.delete_result


def _add_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "messages": [{"role": "user", "content": "Caroline attended the group."}],
        "user_id": "benchmark-user",
        "run_id": "run-1",
        "metadata": {
            "source_id": "conv0/session-1/turn-1",
            "source_sha256": _SOURCE_SHA256,
        },
        "timestamp": 1672531200,
    }
    payload.update(overrides)
    return payload


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


@pytest.mark.contract
def test_generated_openapi_satisfies_main_bounded_contract() -> None:
    contract = import_root_contract(
        "infinity_context_server.memory_comparison_mem0_contract",
    )
    schema = create_app(UnconfiguredPlatformPort()).openapi()

    result = contract.evaluate_mem0_openapi_contract(schema, require_timestamp=True)

    assert result["violations"] == ()
    assert len(result["fingerprint_sha256"]) == 64


def test_startup_attestation_passes_and_health_requires_all_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_ADAPTER_SOURCE_REVISION", "a" * 40)
    monkeypatch.setattr(
        manifest_module,
        "_installed_sdk_provenance",
        lambda: {"pin_matches": True},
    )
    platform = FakePlatform(readback=_sentinel_readback())
    app = create_app(
        platform,
        sleeper=lambda _: None,
        token_factory=lambda: "fixed",
    )

    with _authorized_client(app) as client:
        health = client.get("/health").json()
        manifest = client.get("/benchmark/capabilities").json()

    assert health == {
        "status": "ok",
        "runtime_mode": "managed_platform",
        "configured": True,
        "ready": True,
        "attestation_status": "passed",
        "ingress_auth_configured": True,
    }
    attestation = manifest["timestamp"]["attestation"]
    assert manifest["timestamp"]["readback_supported"] is True
    assert manifest["persisted_source_identity"] == {
        "request_metadata_required": True,
        "source_filtered_readback_supported": True,
        "source_id_roundtrip_attested": True,
        "source_sha256_roundtrip_attested": True,
        "sanitized_identity_response": True,
    }
    assert attestation["status"] == "passed"
    assert attestation["probe_mode"] == "live_sentinel"
    assert attestation["event_terminal_status"] == "SUCCEEDED"
    assert attestation["cleanup_succeeded"] is True
    assert attestation["delta_seconds"] == 0.0
    assert [name for name, _ in platform.calls] == [
        "add",
        "get_event",
        "get_all",
        "delete",
        "get_all",
    ]
    assert "evt-1" not in str(manifest)
    assert "mem0-attest-user-fixed" not in str(manifest)
    assert "mem0-attest-run-fixed" not in str(manifest)
    assert "mem0-attest-source-fixed" not in str(manifest)


def test_startup_attestation_readback_failure_is_sanitized_and_cleaned() -> None:
    platform = FakePlatform(readback={"results": []})
    app = create_app(
        platform,
        sleeper=lambda _: None,
        token_factory=lambda: "fixed",
    )

    with _authorized_client(app) as client:
        health = client.get("/health").json()
        manifest = client.get("/benchmark/capabilities").json()

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    attestation = manifest["timestamp"]["attestation"]
    assert attestation["status"] == "failed"
    assert attestation["failure_code"] == "source_id_not_found"
    assert attestation["cleanup_succeeded"] is True
    assert [name for name, _ in platform.calls] == [
        "add",
        "get_event",
        "get_all",
        "delete",
        "get_all",
    ]


def test_startup_attestation_cleanup_failure_blocks_readiness() -> None:
    platform = FakePlatform(readback=_sentinel_readback(), delete_result=False)
    app = create_app(
        platform,
        sleeper=lambda _: None,
        token_factory=lambda: "fixed",
    )

    with _authorized_client(app) as client:
        health = client.get("/health").json()
        attestation = client.get("/benchmark/capabilities").json()["timestamp"]["attestation"]

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert attestation["status"] == "failed"
    assert attestation["failure_code"] == "cleanup_failed"
    assert attestation["cleanup_succeeded"] is False


def test_unconfigured_startup_does_not_call_platform() -> None:
    platform = FakePlatform(is_configured=False)

    with _authorized_client(create_app(platform, token_factory=lambda: "fixed")) as client:
        health = client.get("/health").json()

    assert health["status"] == "unconfigured"
    assert health["ready"] is False
    assert platform.calls == []


def test_benchmark_attestation_refresh_is_protected_and_returns_bound_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", "dedicated-probe-token")
    platform = FakePlatform(readback=_sentinel_readback())
    run_id = "managed-full-run-1"
    nonce = "c" * 64
    target_sha = "d" * 64

    with _authorized_client(
        create_app(
            platform,
            sleeper=lambda _: None,
            token_factory=lambda: "fixed",
            attest_on_startup=False,
        )
    ) as client:
        before = client.get("/benchmark/capabilities").json()
        denied = client.post(
            "/benchmark/attest-timestamp",
            json={
                "run_id": run_id,
                "probe_nonce": nonce,
                "target_identity_sha256": target_sha,
            },
        )
        assert platform.calls == []
        refreshed = client.post(
            "/benchmark/attest-timestamp",
            headers={"X-Benchmark-Probe-Token": "dedicated-probe-token"},
            json={
                "run_id": run_id,
                "probe_nonce": nonce,
                "target_identity_sha256": target_sha,
            },
        )
        later = client.get("/benchmark/capabilities").json()

    assert "refresh_binding" not in before
    assert denied.status_code == 401
    assert refreshed.status_code == 200
    binding = refreshed.json()["refresh_binding"]
    assert binding == later["refresh_binding"]
    assert binding["status"] == "passed"
    assert binding["run_id_sha256"] == hashlib.sha256(run_id.encode()).hexdigest()
    assert binding["probe_nonce_sha256"] == hashlib.sha256(nonce.encode()).hexdigest()
    assert binding["target_identity_sha256"] == target_sha
    assert refreshed.json()["refresh_witness"]["algorithm"] == "hmac-sha256"
    rendered = str(refreshed.json())
    assert run_id not in rendered
    assert nonce not in rendered
    assert "dedicated-probe-token" not in rendered
    assert [name for name, _ in platform.calls] == [
        "add",
        "get_event",
        "get_all",
        "delete",
        "get_all",
    ]


def test_auth_challenge_is_token_bound_and_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "dedicated-probe-token"
    nonce = "ab" * 32
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", token)
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    denied = client.post(
        "/benchmark/auth-challenge",
        headers={"X-Benchmark-Probe-Token": "wrong"},
        json={"nonce": nonce},
    )
    response = client.post(
        "/benchmark/auth-challenge",
        headers={"X-Benchmark-Probe-Token": token},
        json={"nonce": nonce},
    )
    operation = client.get("/openapi.json").json()["paths"]["/benchmark/auth-challenge"]["post"]

    assert denied.status_code == 401
    assert denied.json() == {"detail": "invalid_benchmark_probe_token"}
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "mem0-benchmark-auth-challenge.v1",
        "nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "signature": hmac.new(
            token.encode(),
            f"mem0-benchmark-auth-challenge.v1\n{nonce}".encode(),
            hashlib.sha256,
        ).hexdigest(),
    }
    assert token not in str(response.json())
    assert nonce not in str(response.json())
    assert operation["requestBody"]["required"] is True
    assert any(
        parameter["name"] == "X-Benchmark-Probe-Token" and parameter["in"] == "header"
        for parameter in operation["parameters"]
    )
    assert platform.calls == []


def test_auth_challenge_fails_closed_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_BENCHMARK_PROBE_TOKEN", raising=False)
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    response = client.post(
        "/benchmark/auth-challenge",
        headers={"X-Benchmark-Probe-Token": "presented"},
        json={"nonce": "ab" * 32},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "missing_benchmark_probe_token"}
    assert platform.calls == []


def test_add_forwards_timestamp_polls_and_attests_readback() -> None:
    platform = FakePlatform(
        events=[
            EventSnapshot(status="PENDING"),
            EventSnapshot(status="RUNNING"),
            EventSnapshot(status="SUCCEEDED"),
        ],
        readback={
            "results": [
                {
                    "id": "mem-1",
                    "memory": "Caroline attended the group.",
                    "created_at": "2023-01-01T00:00:00Z",
                    "metadata": {
                        "source_id": "conv0/session-1/turn-1",
                        "source_sha256": _SOURCE_SHA256,
                    },
                },
            ]
        },
    )
    sleeps: list[float] = []
    client = _authorized_client(
        create_app(
            platform,
            policy=PollingPolicy(max_attempts=4, interval_seconds=0.25),
            sleeper=sleeps.append,
        )
    )

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "evt-1",
        "results": [
            {
                "id": "mem-1",
                "event": "ADD",
                "metadata": {
                    "source_id": "conv0/session-1/turn-1",
                    "source_sha256": _SOURCE_SHA256,
                },
            }
        ],
    }
    assert sleeps == [0.25, 0.25]
    add_call = platform.calls[0]
    assert add_call[0] == "add"
    assert add_call[1]["timestamp"] == 1672531200
    assert add_call[1]["metadata"]["source_id"] == "conv0/session-1/turn-1"
    assert add_call[1]["metadata"]["source_sha256"] == _SOURCE_SHA256
    expected_readback_call = (
        "get_all",
        {
            "filters": {
                "AND": [
                    {"user_id": "benchmark-user"},
                    {"run_id": "run-1"},
                    {"metadata": {"source_id": "conv0/session-1/turn-1"}},
                ]
            },
            "page": 1,
            "page_size": 200,
        },
    )
    assert expected_readback_call in platform.calls

    manifest = client.get("/benchmark/capabilities").json()
    assert manifest["schema_version"] == "mem0-benchmark-capabilities.v2"
    assert manifest["runtime_mode"] == "managed_platform"
    assert manifest["sdk"]["expected_version"] == "2.0.14"
    assert manifest["timestamp"]["readback_supported"] is False
    assert manifest["timestamp"]["attestation"]["status"] == "not_run"


def test_add_source_filtered_readback_paginates_beyond_first_200_results() -> None:
    first_page = [
        {
            "id": f"target-{index}",
            "created_at": "2023-01-01T00:00:00Z",
            "metadata": {
                "source_id": "conv0/session-1/turn-1",
                "source_sha256": _SOURCE_SHA256,
            },
        }
        for index in range(200)
    ]
    platform = FakePlatform(
        readback_pages={
            1: {
                "count": 201,
                "next": "https://api.mem0.ai/v3/memories/?page=2",
                "results": first_page,
            },
            2: {
                "count": 201,
                "next": None,
                "results": [
                    {
                        "id": "target",
                        "created_at": "2023-01-01T00:00:00Z",
                        "metadata": {
                            "source_id": "conv0/session-1/turn-1",
                            "source_sha256": _SOURCE_SHA256,
                        },
                    }
                ],
            },
        }
    )
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 200
    assert len(response.json()["results"]) == 201
    assert response.json()["results"][-1]["id"] == "target"
    readback_calls = [payload for name, payload in platform.calls if name == "get_all"]
    assert [call["page"] for call in readback_calls] == [1, 2]
    assert all(call["page_size"] == 200 for call in readback_calls)


@pytest.mark.parametrize(
    "continuation",
    (
        "not-a-url",
        "https://evil.example/v3/memories/?page=2",
        "https://api.mem0.ai/v3/memories/?page=3",
        "https://api.mem0.ai/v3/memories/?page=2&cursor=evil",
        "https://api.mem0.ai/v3/memories/?page=02",
    ),
)
def test_add_readback_rejects_invalid_continuation(continuation: str) -> None:
    platform = FakePlatform(
        readback_pages={
            1: {
                "next": continuation,
                "results": [],
            }
        }
    )
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 502
    assert response.json() == {"detail": "timestamp_readback_failed"}
    assert [payload["page"] for name, payload in platform.calls if name == "get_all"] == [1]


def test_add_polling_is_bounded() -> None:
    platform = FakePlatform(
        events=[EventSnapshot(status="PENDING"), EventSnapshot(status="RUNNING")]
    )
    client = _authorized_client(
        create_app(
            platform,
            policy=PollingPolicy(max_attempts=2, interval_seconds=0),
            sleeper=lambda _: None,
        )
    )

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 504
    assert response.json() == {"detail": "event_poll_timeout"}
    assert [name for name, _ in platform.calls] == ["add", "get_event", "get_event"]


def test_add_rejects_timestamp_readback_mismatch() -> None:
    platform = FakePlatform(
        readback={
            "results": [
                {
                    "id": "mem-mismatch",
                    "created_at": "2024-01-01T00:00:00Z",
                    "metadata": {
                        "source_id": "conv0/session-1/turn-1",
                        "source_sha256": _SOURCE_SHA256,
                    },
                }
            ]
        }
    )
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 502
    assert response.json() == {"detail": "timestamp_readback_failed"}


@pytest.mark.parametrize(
    "metadata",
    (
        {"source_id": "secret source id", "source_sha256": _SOURCE_SHA256},
        {"source_id": "conv0/session-1/turn-1"},
        {
            "source_id": "conv0/session-1/turn-1",
            "source_sha256": "A" * 64,
        },
    ),
)
def test_add_requires_exact_safe_source_identity(metadata: dict[str, str]) -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    response = client.post("/memories", json=_add_payload(metadata=metadata))

    assert response.status_code == 422
    assert platform.calls == []


def test_add_forbids_unknown_request_fields() -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    unknown = client.post("/memories", json=_add_payload(unexpected=True))

    assert unknown.status_code == 422
    assert platform.calls == []


@pytest.mark.parametrize(
    "persisted_metadata",
    (
        {
            "source_id": "conv0/session-1/turn-1",
            "source_sha256": "b" * 64,
        },
        {
            "source_id": "wrong-source",
            "source_sha256": _SOURCE_SHA256,
        },
    ),
)
def test_add_fails_closed_when_filtered_row_misbinds_source_identity(
    persisted_metadata: dict[str, str],
) -> None:
    platform = FakePlatform(
        readback={
            "results": [
                {
                    "id": "mem-wrong-hash",
                    "created_at": "2023-01-01T00:00:00Z",
                    "metadata": persisted_metadata,
                }
            ]
        }
    )
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    response = client.post("/memories", json=_add_payload())

    assert response.status_code == 502
    assert response.json() == {"detail": "timestamp_readback_failed"}
    readback = next(payload for name, payload in platform.calls if name == "get_all")
    assert readback["filters"]["AND"][-1] == {
        "metadata": {"source_id": "conv0/session-1/turn-1"}
    }


@pytest.mark.parametrize("memory_id", ("", " duplicated "))
def test_add_fails_closed_on_invalid_persisted_id(memory_id: str) -> None:
    platform = FakePlatform(
        readback={
            "results": [
                {
                    "id": memory_id,
                    "created_at": "2023-01-01T00:00:00Z",
                    "metadata": {
                        "source_id": "conv0/session-1/turn-1",
                        "source_sha256": _SOURCE_SHA256,
                    },
                }
            ]
        }
    )
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    assert client.post("/memories", json=_add_payload()).status_code == 502


def test_add_fails_closed_on_duplicate_persisted_ids() -> None:
    row = {
        "id": "duplicate",
        "created_at": "2023-01-01T00:00:00Z",
        "metadata": {
            "source_id": "conv0/session-1/turn-1",
            "source_sha256": _SOURCE_SHA256,
        },
    }
    platform = FakePlatform(readback={"results": [row, dict(row)]})
    client = _authorized_client(create_app(platform, sleeper=lambda _: None))

    assert client.post("/memories", json=_add_payload()).status_code == 502


def test_search_maps_limit_to_top_k_without_mutating_filters() -> None:
    filters = {"AND": [{"user_id": "benchmark-user"}, {"run_id": "run-1"}]}
    platform = FakePlatform(
        search_response={"results": [{"id": "mem-1", "memory": "evidence", "score": 0.8}]}
    )
    client = _authorized_client(create_app(platform))

    response = client.post(
        "/search",
        json={"query": "when?", "filters": filters, "limit": 200},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == "mem-1"
    assert platform.calls == [("search", {"query": "when?", "filters": filters, "top_k": 200})]


def test_search_rejects_entity_name_only_in_a_value() -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    response = client.post(
        "/search",
        json={"query": "when?", "filters": {"metadata_key": "user_id"}, "limit": 10},
    )

    assert response.status_code == 422
    assert platform.calls == []


@pytest.mark.parametrize(
    "filters",
    (
        {"OR": [{"user_id": "victim"}, {"visibility": "public"}]},
        {"NOT": {"user_id": "victim"}},
        {
            "AND": [
                {"project": "safe"},
                {"OR": [{"user_id": "victim"}, {"visibility": "public"}]},
            ]
        },
        {
            "AND": [
                {"user_id": "victim"},
                {"AND": [{"NOT": {"run_id": "private"}}]},
            ]
        },
    ),
)
def test_search_rejects_or_not_scope_bypasses(filters: dict[str, Any]) -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    response = client.post(
        "/search",
        json={"query": "private evidence", "filters": filters, "limit": 10},
    )

    assert response.status_code == 422
    assert platform.calls == []


@pytest.mark.parametrize(
    "invalid_value",
    (None, True, False, 1, "", "   ", {}, [], ["user-1"]),
)
def test_search_rejects_every_invalid_identity_filter_value(
    invalid_value: object,
) -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    response = client.post(
        "/search",
        json={
            "query": "when?",
            "filters": {
                "AND": [
                    {"user_id": "valid-user"},
                    {"run_id": invalid_value},
                ]
            },
            "limit": 10,
        },
    )

    assert response.status_code == 422
    assert platform.calls == []


def test_delete_is_exactly_scoped_and_health_is_strict() -> None:
    platform = FakePlatform()
    client = _authorized_client(create_app(platform))

    health = client.get("/health")
    deleted = client.delete("/memories", params={"user_id": "benchmark-user", "run_id": "run-1"})
    missing_scope = client.delete("/memories", params={"user_id": "benchmark-user"})

    assert health.json() == {
        "status": "not_ready",
        "runtime_mode": "managed_platform",
        "configured": True,
        "ready": False,
        "attestation_status": "not_run",
        "ingress_auth_configured": True,
    }
    assert deleted.json() == {"deleted": True, "verified_absent": True}
    assert missing_scope.status_code == 422
    assert platform.calls == [
        ("delete", {"user_id": "benchmark-user", "run_id": "run-1"}),
        (
            "get_all",
            {
                "filters": {"AND": [{"user_id": "benchmark-user"}, {"run_id": "run-1"}]},
                "page": 1,
                "page_size": 200,
            },
        ),
    ]


def test_unconfigured_runtime_never_calls_a_platform() -> None:
    client = _authorized_client(create_app(UnconfiguredPlatformPort()))

    assert client.get("/health").json() == {
        "status": "unconfigured",
        "runtime_mode": "managed_platform",
        "configured": False,
        "ready": False,
        "attestation_status": "not_run",
        "ingress_auth_configured": True,
    }
    manifest = client.get("/benchmark/capabilities").json()
    assert manifest["configured"] is False
    assert manifest["timestamp"]["readback_supported"] is False
    assert manifest["timestamp"]["attestation"]["failure_code"] == "missing_mem0_api_key"
    assert client.post("/memories", json=_add_payload()).status_code == 503
