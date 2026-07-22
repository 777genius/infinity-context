from __future__ import annotations

import asyncio
from math import isfinite
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)
from infinity_context_core.application.context_stage_diagnostics import (
    CONTEXT_STAGE_NAMES,
    MAX_CONTEXT_STAGE_DURATION_MS,
    MAX_CONTEXT_STAGE_TIMINGS,
    record_context_stage_duration,
)
from infinity_context_core.application.use_cases import build_context as build_context_module
from infinity_context_server.api.v1 import context as context_api
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def test_context_stage_values_are_fixed_name_bounded_numeric_and_text_free() -> None:
    sensitive_label = "query SECRET_SCOPE credential=private account=owner"
    raw_timings: dict[str, object] = {
        "planning_expansion": -3,
        "canonical_collect": float("inf"),
        "pack": MAX_CONTEXT_STAGE_DURATION_MS * 2,
        "rerank": True,
        sensitive_label: 12.0,
    }
    diagnostics: dict[str, object] = {"stage_timings_ms": raw_timings}

    record_context_stage_duration(
        diagnostics,
        stage=sensitive_label,
        duration_ms=7.0,
    )
    normalized = normalize_context_bundle_diagnostics(diagnostics, items=())
    timings = normalized["stage_timings_ms"]

    assert timings == {
        "planning_expansion": 0.0,
        "canonical_collect": 0.0,
        "rerank": 0.0,
        "pack": MAX_CONTEXT_STAGE_DURATION_MS,
    }
    assert len(timings) <= MAX_CONTEXT_STAGE_TIMINGS
    assert set(timings).issubset(CONTEXT_STAGE_NAMES)
    assert all(
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
        and 0.0 <= value <= MAX_CONTEXT_STAGE_DURATION_MS
        for value in timings.values()
    )
    assert sensitive_label not in str(timings)


def test_context_route_stage_boundaries_wrap_only_the_work_they_name(monkeypatch) -> None:
    clock = iter((0.0, 10.0, 15.0, 40.0, 43.0, 50.0, 51.0))
    events: list[str] = []
    scope = SimpleNamespace(space_id="space", memory_scope_ids=("scope",), thread_id=None)
    bundle = SimpleNamespace(diagnostics={"stage_timings_ms": {}})

    async def resolve_scope(*_args, **_kwargs):
        events.append("scope_resolution")
        return scope

    async def execute(_query):
        events.append("core_execute")
        return bundle

    def map_response(mapped_bundle, *, request_id):
        events.append("response_mapping")
        return {
            "meta": {"request_id": request_id},
            "data": {"diagnostics": mapped_bundle.diagnostics},
        }

    def record_metrics(**_kwargs):
        events.append("runtime_metrics")

    monkeypatch.setattr(context_api, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(context_api, "should_retrieve", lambda _container: True)
    monkeypatch.setattr(context_api, "resolve_existing_context_scope", resolve_scope)
    monkeypatch.setattr(
        context_api.context_building_server,
        "build_legacy_context_query_from_request",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        context_api,
        "_LEGACY_CONTEXT_API_RESPONSES",
        SimpleNamespace(context_response_from_bundle=map_response),
    )
    container = SimpleNamespace(
        ids=SimpleNamespace(new_id=lambda _prefix: "req_test"),
        settings=SimpleNamespace(max_context_chars=1000),
        build_context=SimpleNamespace(execute=execute),
        runtime_metrics=SimpleNamespace(record_context=record_metrics),
    )

    response = asyncio.run(
        context_api.build_context(context_api.ContextRequest(query="bounded"), container)
    )

    assert events == [
        "scope_resolution",
        "core_execute",
        "response_mapping",
        "runtime_metrics",
    ]
    assert response["meta"]["request_id"] == "req_test"
    assert response["data"]["diagnostics"]["stage_timings_ms"] == {
        "scope_resolution": 5000.0,
        "response_mapping": 3000.0,
        "total": 51000.0,
    }


def test_final_rank_and_rerank_are_real_sequential_intervals_and_trace_is_compatible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intervals: dict[str, tuple[float, float]] = {}
    real_record_interval = build_context_module.record_context_stage_interval

    def record_interval(
        diagnostics,
        *,
        stage: str,
        started_at: float,
        finished_at: float,
    ) -> None:
        if stage in {"final_rank", "rerank"}:
            intervals[stage] = (started_at, finished_at)
        real_record_interval(
            diagnostics,
            stage=stage,
            started_at=started_at,
            finished_at=finished_at,
        )

    monkeypatch.setattr(build_context_module, "record_context_stage_interval", record_interval)
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "text": "STAGE_INTERVAL_MARKER is canonical evidence.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "stage-interval"}],
            },
            headers=headers,
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "STAGE_INTERVAL_MARKER",
                "token_budget": 512,
            },
            headers=headers,
        )
        metrics = client.get("/v1/diagnostics/metrics", headers=headers)

    final_rank = intervals["final_rank"]
    rerank = intervals["rerank"]
    timings = context.json()["data"]["diagnostics"]["stage_timings_ms"]
    request_id = context.json()["meta"]["request_id"]
    trace = metrics.json()["data"]["context"]["last_trace"]

    assert created.status_code == 201
    assert context.status_code == 200
    assert metrics.status_code == 200
    assert final_rank[0] < final_rank[1] <= rerank[0] < rerank[1]
    assert final_rank[0] != rerank[0]
    assert timings["final_rank"] >= 0.0
    assert timings["rerank"] >= 0.0
    assert timings["total"] >= timings["response_mapping"]
    assert request_id.startswith("req_")
    assert trace["request_id"] == request_id
    assert trace["space_id"] == "space_client_app"
    assert trace["memory_scope_ids"] == ["memory_scope_default"]
