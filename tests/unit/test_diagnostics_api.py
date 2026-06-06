import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import MemoryOutboxRow
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
from sqlalchemy.ext.asyncio import AsyncSession


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_diagnostics_adapters_and_outbox_are_safe(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Diagnostics notes",
                "text": "Do not leak this raw diagnostic text through outbox diagnostics.",
                "source_type": "document",
                "source_external_id": "doc-diagnostics",
            },
            headers=auth_headers(),
        )
        adapters = client.get("/v1/diagnostics/adapters", headers=auth_headers())
        outbox = client.get(
            "/v1/diagnostics/outbox",
            params={"limit": 1},
            headers=auth_headers(),
        )

    assert document.status_code == 201
    assert adapters.status_code == 200
    assert adapters.json()["data"]["adapters"]["qdrant"]["enabled"] is False
    assert {
        (item["adapter_name"], item["capability"])
        for item in adapters.json()["data"]["capabilities"]
    } >= {("qdrant", "vector_recall"), ("graphiti", "temporal_fact_graph")}
    assert outbox.status_code == 200
    assert outbox.json()["data"]["oldest_active_lag_seconds"] is not None
    item = outbox.json()["data"]["items"][0]
    assert item["event_type"] == "vector.upsert_chunk"
    assert item["workload_class"] == "projection"
    assert item["fairness_key"].startswith("chunk:")
    assert item["last_safe_diagnostic_code"] is None
    assert "payload_json" not in item
    assert "raw diagnostic text" not in str(item)


def test_diagnostics_profile_counts_are_scoped_and_non_content(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Profile diagnostics notes",
                "text": "PROFILE_DIAGNOSTIC_MARKER should not appear in diagnostics.",
                "source_type": "document",
                "source_external_id": "doc-profile-diagnostics",
            },
            headers=auth_headers(),
        )
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "PROFILE_DIAGNOSTIC_FACT should not appear in diagnostics.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "diag-fact"}],
            },
            headers=auth_headers(),
        )
        client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "candidate_text": "PROFILE_DIAGNOSTIC_SUGGESTION",
                "safe_reason": "diagnostic count",
                "source_refs": [{"source_type": "manual", "source_id": "diag-suggestion"}],
            },
            headers=auth_headers(),
        )
        diagnostics = client.get(
            "/v1/diagnostics/profile/profile_default",
            headers=auth_headers(),
        )

    assert diagnostics.status_code == 200
    data = diagnostics.json()["data"]
    assert data["facts"]["active"] == 1
    assert data["documents"]["active"] == 1
    assert data["chunks"]["active"] == 1
    assert data["suggestions"]["pending"] == 1
    assert "PROFILE_DIAGNOSTIC" not in str(data)


def test_diagnostics_redacts_restricted_preview(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Restricted diagnostics",
                "text": "RESTRICTED_DIAGNOSTIC_DOC_SECRET must never appear in diagnostics.",
                "source_type": "document",
                "source_external_id": "restricted-diagnostics-doc",
                "classification": "restricted",
            },
            headers=auth_headers(),
        )
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "RESTRICTED_DIAGNOSTIC_FACT_SECRET must never appear in diagnostics.",
                "kind": "note",
                "classification": "restricted",
                "source_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "restricted-diagnostics-fact",
                        "quote_preview": "RESTRICTED_DIAGNOSTIC_PREVIEW_SECRET",
                    }
                ],
            },
            headers=auth_headers(),
        )
        profile = client.get(
            "/v1/diagnostics/profile/profile_default",
            headers=auth_headers(),
        )
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    combined = f"{profile.json()} {metrics.json()}"
    assert profile.status_code == 200
    assert metrics.status_code == 200
    assert "RESTRICTED_DIAGNOSTIC_DOC_SECRET" not in combined
    assert "RESTRICTED_DIAGNOSTIC_FACT_SECRET" not in combined
    assert "RESTRICTED_DIAGNOSTIC_PREVIEW_SECRET" not in combined


def test_diagnostics_metrics_are_counts_only_and_alert_on_dead_outbox(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Metrics diagnostics notes",
                "text": "RAW_METRICS_SECRET should not appear in metrics.",
                "source_type": "document",
                "source_external_id": "doc-metrics-diagnostics",
            },
            headers=auth_headers(),
        )
        asyncio.run(_insert_dead_metrics_outbox(client))
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    assert metrics.status_code == 200
    data = metrics.json()["data"]
    assert data["outbox"]["counts"]["dead"] == 1
    assert data["outbox"]["dead"] == 1
    assert data["canonical"]["documents"]["active"] == 1
    assert data["canonical"]["chunks"]["active"] == 1
    assert data["adapters"]["qdrant"]["status"] == "disabled"
    assert data["context"]["request_count"] == 0
    assert data["context"]["p95_latency_ms"] is None
    assert data["context"]["degraded_rate"] == 0.0
    assert any(alert["name"] == "outbox_dead_count" for alert in data["alerts"])
    assert "RAW_METRICS_SECRET" not in str(data)
    assert "payload_json" not in str(data)


def test_diagnostics_metrics_include_context_runtime_counters(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "RUNTIME_METRIC_FACT should not leak through metrics.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "runtime-metric"}],
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "runtime metric",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    assert context.status_code == 200
    data = metrics.json()["data"]
    assert data["context"]["request_count"] == 1
    assert data["context"]["p95_latency_ms"] >= 0
    assert data["context"]["degraded_count"] == 0
    assert data["context"]["degraded_rate"] == 0.0
    assert data["context"]["collection"] == "in_memory"
    assert "RUNTIME_METRIC_FACT" not in str(data)


def test_circuit_state_visible_in_safe_diagnostics(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        qdrant_circuit = client.app.state.container.provider_circuits[0]
        qdrant_circuit.record_failure("vector.timeout")
        qdrant_circuit.record_failure("vector.timeout")
        qdrant_circuit.record_failure("vector.timeout")
        adapters = client.get("/v1/diagnostics/adapters", headers=auth_headers())
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    adapter_circuit = adapters.json()["data"]["circuits"]["qdrant"]
    metrics_circuit = metrics.json()["data"]["circuits"]["qdrant"]
    assert adapters.status_code == 200
    assert metrics.status_code == 200
    assert adapter_circuit["state"] == "open"
    assert metrics_circuit["state"] == "open"
    assert metrics_circuit["last_failure_code"] == "vector.timeout"
    assert any(
        alert["name"] == "provider_circuit_qdrant_open"
        for alert in metrics.json()["data"]["alerts"]
    )
    assert "payload_json" not in str(metrics.json()["data"])
    assert "RAW_" not in str(metrics.json()["data"])


def test_context_response_request_id_matches_log_record(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "TRACE_REQUEST_ID_MARKER renders from canonical facts.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "trace-request"}],
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "TRACE_REQUEST_ID_MARKER",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    request_id = context.json()["meta"]["request_id"]
    trace = metrics.json()["data"]["context"]["last_trace"]
    assert context.status_code == 200
    assert metrics.status_code == 200
    assert request_id.startswith("req_")
    assert trace["request_id"] == request_id
    assert trace["span"] == "memory.context.request"
    assert trace["use_case"] == "build_context"
    assert trace["space_id"] == "space_client_app"
    assert trace["profile_ids"] == ["profile_default"]


def test_trace_attributes_do_not_include_raw_text(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "TRACE_RAW_TEXT_SECRET must not appear in trace attributes.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "trace-secret"}],
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "TRACE_RAW_TEXT_SECRET",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        metrics = client.get("/v1/diagnostics/metrics", headers=auth_headers())

    trace = metrics.json()["data"]["context"]["last_trace"]
    assert context.status_code == 200
    assert "TRACE_RAW_TEXT_SECRET" in context.json()["data"]["rendered_text"]
    assert "TRACE_RAW_TEXT_SECRET" not in str(trace)
    assert "query" not in trace
    assert "rendered_text" not in trace


async def _insert_dead_metrics_outbox(client: TestClient) -> None:
    now = datetime.now(UTC)
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryOutboxRow(
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk_metrics_secret",
                aggregate_version=None,
                payload_json={"raw": "RAW_METRICS_SECRET should stay private"},
                status="dead",
                attempt_count=5,
                next_attempt_at=now - timedelta(minutes=15),
                created_at=now - timedelta(minutes=15),
                updated_at=now,
                workload_class="projection",
                fairness_key="chunk:chunk_metrics_secret",
                last_safe_error="Vector write degraded",
                last_safe_diagnostic_code="qdrant.upsert_failed",
            )
        )
        await session.commit()
