import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres import create_schema
from memo_stack_adapters.postgres.models import MemoryFactRow, MemoryOutboxRow
from memo_stack_core.agent_behavior_contract import (
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS,
)
from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    PortStatus,
    VectorWriteResult,
)
from memo_stack_core.ports.capabilities import (
    CapabilityStatus,
    ProjectionForgetResult,
    ProjectionWriteResult,
)
from memo_stack_server.admin import (
    ACTIVE_CONTEXT_MANUAL_CHECK_NAMES,
    invariant_check,
    seed_defaults,
)
from memo_stack_server.composition import build_container
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.db import upgrade
from memo_stack_server.doctor import run_doctor
from memo_stack_server.eval import (
    _execute_small_golden,
    build_memory_quality_scorecard,
    memory_quality_scorecard_policy_snapshot,
    run_auto_memory_golden,
    run_graph_native_golden,
    run_long_memory_golden,
    run_memory_quality_scorecard,
    run_quality_golden,
    run_small_golden,
)
from memo_stack_server.main import create_app
from memo_stack_server.worker import OutboxWorker, _safe_diagnostic_code, _safe_error
from sqlalchemy import select, update
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


def make_client_with_settings(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _scorecard_fixture_results() -> dict[str, dict[str, Any]]:
    return {
        "small-golden": {
            "suite": "small-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 8,
                "recall_at_5": 0.9,
                "precision_at_5": 0.8,
                "deleted_memory_leak_count": 0,
                "cross_profile_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "context_token_overflow_count": 0,
            },
            "failures": [],
        },
        "quality-golden": {
            "suite": "quality-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 16,
                "recall_at_5": 0.96,
                "precision_at_5": 0.95,
                "answer_support_rate": 1.0,
                "document_recall_at_5": 1.0,
                "multi_profile_recall_at_5": 1.0,
                "thread_recall_at_5": 1.0,
                "stale_memory_rate": 0.0,
                "deleted_memory_leak_count": 0,
                "cross_profile_leak_count": 0,
                "cross_thread_leak_count": 0,
                "restricted_memory_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "harmful_context_rate": 0.0,
                "context_token_overflow_count": 0,
            },
            "failures": [],
        },
        "long-memory-golden": {
            "suite": "long-memory-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 16,
                "long_memory_case_count": 16,
                "recall_at_5": 0.96,
                "precision_at_5": 0.95,
                "multi_session_recall_at_5": 1.0,
                "temporal_update_accuracy": 1.0,
                "preference_synthesis_recall": 1.0,
                "long_document_recall_at_5": 1.0,
                "thread_recall_at_5": 1.0,
                "multi_profile_recall_at_5": 1.0,
                "stale_memory_rate": 0.0,
                "deleted_memory_leak_count": 0,
                "cross_profile_leak_count": 0,
                "cross_thread_leak_count": 0,
                "restricted_memory_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "long_safety_leak_count": 0,
                "harmful_context_rate": 0.0,
                "context_token_overflow_count": 0,
            },
            "failures": [],
        },
        "auto-memory-golden": {
            "suite": "auto-memory-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 13,
                "extraction_case_count": 78,
                "extraction_semantic_case_count": 18,
                "extraction_positive_recall_rate": 1.0,
                "extraction_operation_accuracy": 1.0,
                "extraction_kind_accuracy": 1.0,
                "extraction_admission_accuracy": 1.0,
                "extraction_ttl_accuracy": 1.0,
                "extraction_target_hint_accuracy": 1.0,
                "extraction_false_positive_count": 0,
                "extraction_false_negative_count": 0,
                "wrong_auto_apply_count": 0,
                "active_fact_before_review_count": 0,
                "prompt_injection_promoted_count": 0,
                "secret_leakage_count": 0,
                "assistant_low_trust_violation_count": 0,
                "target_resolution_violation_count": 0,
                "review_operation_violation_count": 0,
            },
            "failures": [],
        },
        "graph-native-golden": {
            "suite": "graph-native-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 8,
                "graph_recall_rate": 1.0,
                "graph_hydration_rate": 1.0,
                "graph_status_ok_rate": 1.0,
                "graph_safety_leak_count": 0,
                "graph_stale_drop_count": 4,
                "canonical_only_graph_skip_count": 1,
            },
            "failures": [],
        },
        "prompt-contract": {
            "suite": "prompt-contract",
            "ok": True,
            "status": "ok",
            "checks": {
                "snapshot_safe": True,
                "snapshot_exists": True,
                "matches_snapshot": True,
            },
            "cases": [
                "cross_profile_isolation",
                "degraded_graphiti",
                "degraded_qdrant",
                "deleted_fact_filtered",
                "empty_context",
                "facts_only",
                "facts_plus_chunks",
                "instruction_flag_dropped",
                "prompt_injection_quoted",
                "token_budget_truncated",
            ],
            "failures": [],
        },
    }


def _scorecard_provenance(
    *,
    generated_by: str,
    suite: str,
    commit: str = "abc123",
    dirty: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_by": generated_by,
        "suite": suite,
        "git": {"commit": commit, "dirty": dirty},
        "runtime": {"python_version": "3.13.5", "platform": "test-platform"},
    }


def _full_provider_canary_report() -> dict[str, Any]:
    return {
        "suite": "memo-stack-full-provider-canary",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="scripts/clean_full_smoke.py",
            suite="memo-stack-full-provider-canary",
        ),
        "checks": {
            "fact_created": True,
            "updated_fact_versioned": True,
            "forgotten_fact_deleted": True,
            "providers_are_healthy": True,
            "context_provider_status_ok": True,
            "mcp_provider_diagnostics_ok": True,
            "mcp_search_has_graphiti_fact_after_worker": True,
            "mcp_search_has_qdrant_document_chunk_after_worker": True,
            "mcp_search_hides_old_fact_after_update": True,
            "mcp_search_hides_deleted_fact": True,
            "outbox_has_no_pending_or_dead": True,
            "mcp_outbox_has_no_pending_or_dead": True,
        },
        "adapters": {
            "qdrant": "ok",
            "graphiti": "ok",
            "embeddings": "ok",
            "cognee": "disabled",
        },
        "mcp": {"ok": True},
    }


def _agent_behavior_benchmark_report() -> dict[str, Any]:
    return {
        "suite": "memory_mcp_agent_behavior",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="memo_stack_mcp.agent_behavior_bench",
            suite="memory_mcp_agent_behavior",
        ),
        "scenario_set": "all",
        "model": "gpt-5.4-mini",
        "metrics": {
            "scenario_count": 41,
            "tool_choice_accuracy": 1.0,
            "search_before_write_rate": 1.0,
            "update_vs_duplicate_rate": 1.0,
            "document_routing_accuracy": 1.0,
            "answer_support_rate": 1.0,
            "live_session_case_count": 11,
            "live_session_pass_rate": 1.0,
            "transcript_corpus_case_count": 5,
            "transcript_corpus_pass_rate": 1.0,
            "adversarial_case_count": 9,
            "adversarial_pass_rate": 1.0,
            "unsafe_write_count": 0,
            "secret_leak_count": 0,
            "cross_scope_leak_count": 0,
            "stale_leak_count": 0,
            "deleted_leak_count": 0,
            "critical_safety_failures": 0,
        },
        "gates": {
            "critical_safety_failures_zero": True,
            "secret_leak_count_zero": True,
            "unsafe_write_count_zero": True,
            "cross_scope_leak_count_zero": True,
            "stale_leak_count_zero": True,
            "deleted_leak_count_zero": True,
            "search_before_write_rate_min_0_90": True,
            "update_vs_duplicate_rate_min_0_80": True,
            "tool_choice_accuracy_min_0_80": True,
            "answer_support_rate_min_0_80": True,
            "live_session_pass_rate_min_0_80": True,
            "transcript_corpus_pass_rate_min_0_80": True,
            "adversarial_pass_rate_min_0_90": True,
            "critical_scenarios_pass": True,
        },
        "scenarios": _agent_behavior_scenario_reports(),
    }


def _agent_behavior_scenario_reports(
    *,
    scenario_count: int = 41,
    live_session_count: int = 11,
    transcript_corpus_count: int = 5,
    adversarial_count: int = 9,
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    transcript_adversarial_count = min(transcript_corpus_count, adversarial_count)
    for index in range(transcript_adversarial_count):
        scenarios.append(
            _agent_behavior_scenario_report(
                index,
                tags=("live_session", "transcript_corpus", "adversarial"),
            )
        )
    remaining_adversarial = adversarial_count - transcript_adversarial_count
    for _ in range(remaining_adversarial):
        scenarios.append(
            _agent_behavior_scenario_report(
                len(scenarios),
                tags=("live_session", "adversarial"),
            )
        )
    remaining_live = live_session_count - sum(
        "live_session" in scenario["tags"] for scenario in scenarios
    )
    for _ in range(max(remaining_live, 0)):
        scenarios.append(
            _agent_behavior_scenario_report(
                len(scenarios),
                tags=("live_session",),
            )
        )
    while len(scenarios) < scenario_count:
        scenarios.append(_agent_behavior_scenario_report(len(scenarios), tags=("core",)))
    return scenarios[:scenario_count]


def _agent_behavior_scenario_report(
    index: int,
    *,
    tags: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "id": AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[index]
        if index < len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)
        else f"external-agent-scenario-{index}",
        "category": "answer",
        "tags": list(tags),
        "critical": True,
        "status": "passed",
        "tool_calls": [],
        "failures": [],
        "memory_checks": [],
    }


def _public_benchmark_report() -> dict[str, Any]:
    return {
        "suite": "public-memory-benchmark",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="memo_stack_server.official_public_benchmark",
            suite="public-memory-benchmark",
        ),
        "benchmarks": [
            {
                "name": "locomo",
                "ok": True,
                "metrics": {"accuracy": 0.947, "case_count": 600},
            },
            {
                "name": "longmemeval",
                "ok": True,
                "metrics": {"accuracy": 0.902, "case_count": 500},
            },
        ],
        "dataset_hashes": {
            "locomo": "locomo-dataset-sha256",
            "longmemeval": "longmemeval-dataset-sha256",
        },
        "dataset_sources": {
            "locomo": {
                "source_kind": "official_download",
                "official_url": "https://example.test/locomo.json",
                "path_label": "locomo.json",
                "sha256": "locomo-dataset-sha256",
                "size_bytes": 1000,
            },
            "longmemeval": {
                "source_kind": "official_download",
                "official_url": "https://example.test/longmemeval.json",
                "path_label": "longmemeval.json",
                "sha256": "longmemeval-dataset-sha256",
                "size_bytes": 1000,
            },
        },
        "metrics": {"benchmark_count": 2},
    }


def test_eval_cli_uses_env_token_not_cli_auth_token() -> None:
    source = (
        Path(__file__).parents[2]
        / "packages"
        / "memo_stack_server"
        / "memo_stack_server"
        / "eval.py"
    ).read_text(encoding="utf-8")

    assert "--auth-token" not in source
    assert "MEMORY_EVAL_AUTH_TOKEN" in source
    assert "MEMORY_SERVICE_TOKEN" in source


def fact_payload(text: str = "Graph jobs stay safe when Graphiti is disabled.") -> dict[str, Any]:
    return {
        "space_id": "space_client_app",
        "profile_id": "profile_default",
        "text": text,
        "kind": "architecture_decision",
        "source_refs": [{"source_type": "manual", "source_id": "worker-test"}],
    }


async def outbox_statuses(client: TestClient) -> list[str]:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        return list(
            (
                await session.execute(select(MemoryOutboxRow.status).order_by(MemoryOutboxRow.id))
            ).scalars()
        )


async def outbox_event_types(client: TestClient) -> list[str]:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        return list(
            (
                await session.execute(
                    select(MemoryOutboxRow.event_type).order_by(MemoryOutboxRow.id)
                )
            ).scalars()
        )


def test_outbox_worker_no_pending_jobs_is_stable(tmp_path: Path) -> None:
    async def run() -> int:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        return await OutboxWorker(container).run_once(limit=10)

    assert asyncio.run(run()) == 0


def test_outbox_worker_marks_disabled_projection_jobs_done(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        statuses = asyncio.run(outbox_statuses(client))

    assert created.status_code == 201
    assert processed == 1
    assert statuses == ["done"]


def test_safe_document_ingest_enqueues_cognee_projection(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Cognee projection",
                "text": "COGNEE_PUBLIC_DOC_MARKER can be projected to document memory.",
                "source_type": "document",
                "source_external_id": "cognee-public-doc",
                "classification": "public",
            },
            headers=auth_headers(),
        )
        event_types = asyncio.run(outbox_event_types(client))

    assert created.status_code == 201
    assert event_types == ["vector.upsert_chunk", "cognee.ingest_document"]


def test_restricted_document_ingest_does_not_enqueue_cognee_projection(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Restricted projection",
                "text": "COGNEE_RESTRICTED_DOC_MARKER must stay out of external memory.",
                "source_type": "document",
                "source_external_id": "cognee-restricted-doc",
                "classification": "restricted",
            },
            headers=auth_headers(),
        )
        event_types = asyncio.run(outbox_event_types(client))

    assert created.status_code == 201
    assert event_types == ["vector.upsert_chunk"]


def test_cognee_document_projection_worker_sends_only_safe_canonical_chunks(
    tmp_path: Path,
) -> None:
    class RecordingCogneeMemory:
        def __init__(self) -> None:
            self.ingested = []
            self.forgotten = []

        async def ingest_document(self, command):
            self.ingested.append(command)
            return ProjectionWriteResult(
                status=CapabilityStatus.OK,
                affected_ids=(command.document_id,),
            )

        async def forget_document(self, command):
            self.forgotten.append(command)
            return ProjectionForgetResult(
                status=CapabilityStatus.OK,
                forgotten_ids=command.canonical_ids,
            )

    with make_client(tmp_path) as client:
        cognee = RecordingCogneeMemory()
        object.__setattr__(client.app.state.container, "cognee_memory", cognee)
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Safe Cognee worker",
                "text": "COGNEE_WORKER_SAFE_MARKER should be sent from canonical chunks.",
                "source_type": "document",
                "source_external_id": "cognee-worker-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        statuses = asyncio.run(outbox_statuses(client))

    assert created.status_code == 201
    assert processed == 2
    assert statuses == ["done", "done"]
    assert len(cognee.ingested) == 1
    command = cognee.ingested[0]
    assert command.document_id == created.json()["data"]["id"]
    assert "COGNEE_WORKER_SAFE_MARKER" in command.text
    assert command.metadata["classification"] == "internal"
    assert command.chunk_ids
    assert command.source_refs[0].chunk_id == command.chunk_ids[0]


def test_outbox_jobs_store_lifecycle_metadata_by_default(tmp_path: Path) -> None:
    async def row_metadata(client: TestClient) -> tuple[str, str | None, str | None]:
        engine = client.app.state.container.engine
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(select(MemoryOutboxRow).order_by(MemoryOutboxRow.id))
            ).scalar_one()
            return row.workload_class, row.fairness_key, row.last_safe_diagnostic_code

    with make_client(tmp_path) as client:
        created = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        workload_class, fairness_key, diagnostic_code = asyncio.run(row_metadata(client))

    assert created.status_code == 201
    assert workload_class == "projection"
    assert fairness_key == f"fact:{created.json()['data']['id']}"
    assert diagnostic_code is None


def test_expired_running_outbox_job_is_recovered_and_processed(tmp_path: Path) -> None:
    async def run() -> tuple[int, str, int, str | None, str | None]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'expired-running.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        now = container.clock.now()
        async with AsyncSession(container.engine) as session:
            session.add(
                MemoryOutboxRow(
                    event_type="graph.delete_fact",
                    aggregate_type="fact",
                    aggregate_id="fact_missing_after_worker_crash",
                    aggregate_version=None,
                    payload_json={},
                    status="running",
                    attempt_count=0,
                    next_attempt_at=now + timedelta(hours=1),
                    last_safe_error="Previous worker crashed mid-job",
                    created_at=now - timedelta(minutes=10),
                    updated_at=now - timedelta(minutes=6),
                )
            )
            await session.commit()

        processed = await OutboxWorker(container).run_once(limit=10)
        async with AsyncSession(container.engine) as session:
            row = (
                await session.execute(select(MemoryOutboxRow).where(MemoryOutboxRow.id == 1))
            ).scalar_one()
            return (
                processed,
                row.status,
                row.attempt_count,
                row.last_safe_error,
                row.last_safe_diagnostic_code,
            )

    processed, status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(run())

    assert processed == 1
    assert status == "done"
    assert attempt_count == 1
    assert last_safe_error is None
    assert diagnostic_code is None


def test_thread_cleanup_graph_delete_uses_payload_fact_id(tmp_path: Path) -> None:
    class RecordingGraphAdapter:
        def __init__(self) -> None:
            self.deleted_fact_ids: list[str] = []

        async def delete_fact(self, fact_id: str) -> VectorWriteResult:
            self.deleted_fact_ids.append(fact_id)
            return VectorWriteResult.ok(1)

    async def run() -> tuple[int, tuple[str, ...], str]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'thread-cleanup.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        graph = RecordingGraphAdapter()
        object.__setattr__(container, "graph_index", graph)
        now = container.clock.now()
        async with AsyncSession(container.engine) as session:
            session.add(
                MemoryOutboxRow(
                    event_type="graph.delete_fact",
                    aggregate_type="thread",
                    aggregate_id="thread_deleted_session",
                    aggregate_version=None,
                    payload_json={"fact_id": "fact_deleted_by_thread_cleanup"},
                    status="pending",
                    attempt_count=0,
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        processed = await OutboxWorker(container).run_once(limit=10)
        async with AsyncSession(container.engine) as session:
            status = (
                await session.execute(select(MemoryOutboxRow.status).where(MemoryOutboxRow.id == 1))
            ).scalar_one()
        return processed, tuple(graph.deleted_fact_ids), status

    processed, deleted_fact_ids, status = asyncio.run(run())

    assert processed == 1
    assert deleted_fact_ids == ("fact_deleted_by_thread_cleanup",)
    assert status == "done"


def test_expired_running_outbox_job_becomes_dead_after_max_attempts(tmp_path: Path) -> None:
    async def run() -> tuple[int, str, int, str | None, str | None]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'expired-running-dead.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        now = container.clock.now()
        async with AsyncSession(container.engine) as session:
            session.add(
                MemoryOutboxRow(
                    event_type="graph.delete_fact",
                    aggregate_type="fact",
                    aggregate_id="fact_repeated_worker_crash",
                    aggregate_version=None,
                    payload_json={},
                    status="running",
                    attempt_count=4,
                    next_attempt_at=now + timedelta(hours=1),
                    last_safe_error="Previous worker crashed mid-job",
                    created_at=now - timedelta(minutes=20),
                    updated_at=now - timedelta(minutes=6),
                )
            )
            await session.commit()

        processed = await OutboxWorker(container).run_once(limit=10)
        async with AsyncSession(container.engine) as session:
            row = (
                await session.execute(select(MemoryOutboxRow).where(MemoryOutboxRow.id == 1))
            ).scalar_one()
            return (
                processed,
                row.status,
                row.attempt_count,
                row.last_safe_error,
                row.last_safe_diagnostic_code,
            )

    processed, status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(run())

    assert processed == 0
    assert status == "dead"
    assert attempt_count == 5
    assert last_safe_error == "Worker lease expired"
    assert diagnostic_code == "worker.lease_expired"


def test_unknown_document_is_not_embedded_but_job_completes(tmp_path: Path) -> None:
    class FailingEmbedder:
        calls = 0

        async def embed_texts(self, _texts):
            self.calls += 1
            raise AssertionError("unknown documents must not be embedded")

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Unknown document",
                "text": "UNKNOWN_CLASSIFICATION_MARKER should be stored only.",
                "source_type": "document",
                "source_external_id": "unknown-doc",
            },
            headers=auth_headers(),
        )
        embedder = FailingEmbedder()
        object.__setattr__(client.app.state.container, "embedder", embedder)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        statuses = asyncio.run(outbox_statuses(client))

    assert created.status_code == 201
    assert created.json()["data"]["classification"] == "unknown"
    assert processed == 1
    assert statuses == ["done"]
    assert embedder.calls == 0


def test_vector_disabled_internal_document_job_skips_embedding_and_completes(
    tmp_path: Path,
) -> None:
    class FailingEmbedder:
        calls = 0

        async def embed_texts(self, _texts):
            self.calls += 1
            raise AssertionError("disabled vector projection must not call embeddings")

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Internal document",
                "text": "VECTOR_DISABLED_INTERNAL_DOC_MARKER should stay canonical only.",
                "source_type": "document",
                "source_external_id": "internal-vector-disabled-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        embedder = FailingEmbedder()
        object.__setattr__(client.app.state.container, "embedder", embedder)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        statuses = asyncio.run(outbox_statuses(client))

    assert created.status_code == 201
    assert processed == 2
    assert statuses == ["done", "done"]
    assert embedder.calls == 0


def test_vector_document_projection_indexes_document_title_with_chunk_text(
    tmp_path: Path,
) -> None:
    class RecordingVectorAdapter:
        def __init__(self) -> None:
            self.upserts = []

        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def upsert_chunks(self, items) -> VectorWriteResult:
            self.upserts.append(items)
            return VectorWriteResult.ok(len(items))

        async def delete_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            return VectorWriteResult.ok(1)

    class RecordingEmbedder:
        def __init__(self) -> None:
            self.texts = []

        async def embed_texts(self, texts) -> EmbeddingResult:
            self.texts.append(tuple(texts))
            return EmbeddingResult(
                status=PortStatus.OK,
                vectors=((0.1, 0.2, 0.3),),
                model="unit",
            )

    marker = "VECTOR_TITLE_ONLY_MARKER"
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": f"{marker}: Architecture notes",
                "text": "Body mentions Postgres, Qdrant and Graphiti without the title marker.",
                "source_type": "document",
                "source_external_id": "vector-title-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        vector = RecordingVectorAdapter()
        embedder = RecordingEmbedder()
        object.__setattr__(client.app.state.container, "vector_index", vector)
        object.__setattr__(client.app.state.container, "embedder", embedder)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))

    assert created.status_code == 201
    assert processed == 2
    assert marker in embedder.texts[0][0]
    assert "Body mentions Postgres" in embedder.texts[0][0]
    assert marker in vector.upserts[0][0].text
    assert "Body mentions Postgres" in vector.upserts[0][0].text


def test_unhealthy_vector_projection_retries_without_embedding_cost(tmp_path: Path) -> None:
    class UnhealthyVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=False,
                supports_upsert=False,
                supports_delete=True,
                supports_search=False,
                supports_filters=True,
                degraded_reason="qdrant.timeout",
            )

        async def upsert_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            raise AssertionError("unhealthy vector adapter must fail before upsert")

        async def delete_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            raise AssertionError("delete should not be called for active chunks")

    class FailingEmbedder:
        calls = 0

        async def embed_texts(self, _texts):
            self.calls += 1
            raise AssertionError("unhealthy vector projection must not call embeddings")

    async def row_state(client: TestClient) -> tuple[str, int, str | None, str | None]:
        engine = client.app.state.container.engine
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.event_type == "vector.upsert_chunk"
                    )
                )
            ).scalar_one()
            return row.status, row.attempt_count, row.last_safe_error, row.last_safe_diagnostic_code

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Internal document",
                "text": "VECTOR_UNHEALTHY_RETRY_MARKER should leave projection pending.",
                "source_type": "document",
                "source_external_id": "internal-vector-unhealthy-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        embedder = FailingEmbedder()
        object.__setattr__(client.app.state.container, "vector_index", UnhealthyVectorAdapter())
        object.__setattr__(client.app.state.container, "embedder", embedder)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(row_state(client))

    assert created.status_code == 201
    assert processed == 2
    assert status == "retry_pending"
    assert attempt_count == 1
    assert last_safe_error == "RuntimeError"
    assert diagnostic_code == "RuntimeError"
    assert embedder.calls == 0


def test_embedding_budget_exceeded_keeps_document_canonical(tmp_path: Path) -> None:
    class HealthyVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def upsert_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            raise AssertionError("budget-exceeded document must not be embedded or upserted")

        async def delete_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            return VectorWriteResult.ok(1)

    class FailingEmbedder:
        calls = 0

        async def embed_texts(self, _texts):
            self.calls += 1
            raise AssertionError("budget-exceeded document must not call embeddings")

    async def row_state(client: TestClient) -> tuple[str, int, str | None, str | None]:
        async with AsyncSession(client.app.state.container.engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.event_type == "vector.upsert_chunk"
                    )
                )
            ).scalar_one()
            return row.status, row.attempt_count, row.last_safe_error, row.last_safe_diagnostic_code

    with make_client_with_settings(
        tmp_path,
        max_embedding_tokens_per_document=1,
    ) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Budget exceeded",
                "text": (
                    "EMBEDDING_BUDGET_SECRET_MARKER is a canonical document that should "
                    "remain stored even when projection budget is exceeded."
                ),
                "source_type": "document",
                "source_external_id": "embedding-budget-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        embedder = FailingEmbedder()
        object.__setattr__(client.app.state.container, "vector_index", HealthyVectorAdapter())
        object.__setattr__(client.app.state.container, "embedder", embedder)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=1))
        status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(row_state(client))
        loaded = client.get(
            f"/v1/documents/{created.json()['data']['id']}",
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert loaded.status_code == 200
    assert processed == 1
    assert status == "retry_pending"
    assert attempt_count == 1
    assert last_safe_error == "OutboxProjectionError"
    assert diagnostic_code == "embeddings.document_budget_exceeded"
    assert embedder.calls == 0


def test_budget_diagnostics_omit_raw_text(tmp_path: Path) -> None:
    class HealthyVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def upsert_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            raise AssertionError("budget-exceeded document must not be upserted")

        async def delete_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
            return VectorWriteResult.ok(1)

    async def diagnostic_payload(client: TestClient) -> dict[str, object]:
        async with AsyncSession(client.app.state.container.engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.event_type == "vector.upsert_chunk"
                    )
                )
            ).scalar_one()
            return {
                "last_safe_error": row.last_safe_error,
                "last_safe_diagnostic_code": row.last_safe_diagnostic_code,
                "payload_json": row.payload_json,
            }

    with make_client_with_settings(
        tmp_path,
        max_embedding_tokens_per_document=1,
    ) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Budget diagnostics",
                "text": "BUDGET_DIAGNOSTIC_RAW_TEXT must not appear in worker diagnostics.",
                "source_type": "document",
                "source_external_id": "budget-diagnostics-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        object.__setattr__(client.app.state.container, "vector_index", HealthyVectorAdapter())
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=1))
        diagnostic = asyncio.run(diagnostic_payload(client))

    assert created.status_code == 201
    assert processed == 1
    assert diagnostic["last_safe_error"] == "OutboxProjectionError"
    assert diagnostic["last_safe_diagnostic_code"] == "embeddings.document_budget_exceeded"
    assert "BUDGET_DIAGNOSTIC_RAW_TEXT" not in str(diagnostic)


def test_stale_graph_upsert_event_is_skipped_after_fact_update(tmp_path: Path) -> None:
    class RecordingGraphAdapter:
        def __init__(self) -> None:
            self.upserted: list[str] = []

        async def upsert_fact(
            self,
            fact_id: str,
            _text: str,
            _metadata: dict[str, str],
        ) -> VectorWriteResult:
            self.upserted.append(fact_id)
            return VectorWriteResult.ok(1)

        async def delete_fact(self, _fact_id: str) -> VectorWriteResult:
            return VectorWriteResult.ok(1)

    with make_client(tmp_path) as client:
        created = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        fact_id = created.json()["data"]["id"]
        updated = client.patch(
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": 1,
                "text": "Graph jobs must skip stale versions.",
                "reason": "Worker version guard",
                "source_refs": [{"source_type": "manual", "source_id": "worker-version"}],
            },
            headers=auth_headers(),
        )
        graph = RecordingGraphAdapter()
        object.__setattr__(client.app.state.container, "graph_index", graph)
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=1))
        statuses = asyncio.run(outbox_statuses(client))

    assert created.status_code == 201
    assert updated.status_code == 200
    assert processed == 1
    assert graph.upserted == []
    assert statuses == ["done", "pending"]


def test_degraded_graph_projection_job_retries_without_losing_fact(tmp_path: Path) -> None:
    class DegradedGraphAdapter:
        async def upsert_fact(
            self,
            _fact_id: str,
            _text: str,
            _metadata: dict[str, str],
        ) -> VectorWriteResult:
            return VectorWriteResult.degraded("graph.unavailable", retryable=True)

        async def delete_fact(self, _fact_id: str) -> VectorWriteResult:
            return VectorWriteResult.degraded("graph.unavailable", retryable=True)

    async def row_state(client: TestClient) -> tuple[str, int, str | None, str | None]:
        engine = client.app.state.container.engine
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(select(MemoryOutboxRow).order_by(MemoryOutboxRow.id))
            ).scalar_one()
            return row.status, row.attempt_count, row.last_safe_error, row.last_safe_diagnostic_code

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json=fact_payload("GRAPH_DEGRADED_FACT_MARKER remains canonical."),
            headers=auth_headers(),
        )
        object.__setattr__(client.app.state.container, "graph_index", DegradedGraphAdapter())
        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(row_state(client))
        fact = client.get(f"/v1/facts/{created.json()['data']['id']}", headers=auth_headers())

    assert created.status_code == 201
    assert processed == 1
    assert status == "retry_pending"
    assert attempt_count == 1
    assert last_safe_error == "OutboxProjectionError"
    assert diagnostic_code == "graph.unavailable"
    assert fact.json()["data"]["text"] == "GRAPH_DEGRADED_FACT_MARKER remains canonical."


def test_worker_safe_error_omits_raw_exception_text() -> None:
    error = RuntimeError("RAW_PROVIDER_SECRET_MARKER should not be persisted")

    assert _safe_error(error) == "RuntimeError"
    assert _safe_diagnostic_code(error) == "RuntimeError"


def test_outbox_poison_job_becomes_dead_with_safe_error(tmp_path: Path) -> None:
    async def run() -> tuple[str, int, str | None, str | None]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'poison.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        now = container.clock.now()
        async with AsyncSession(container.engine) as session:
            session.add(
                MemoryOutboxRow(
                    event_type="unknown.poison",
                    aggregate_type="test",
                    aggregate_id="RAW_POISON_PAYLOAD_MARKER",
                    aggregate_version=None,
                    payload_json={"raw": "RAW_POISON_PAYLOAD_MARKER"},
                    status="pending",
                    attempt_count=0,
                    next_attempt_at=now,
                    last_safe_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        worker = OutboxWorker(container)
        for _ in range(5):
            assert await worker.run_once(limit=10) == 1
            async with AsyncSession(container.engine) as session:
                await session.execute(
                    update(MemoryOutboxRow).values(next_attempt_at=container.clock.now())
                )
                await session.commit()

        async with AsyncSession(container.engine) as session:
            row = (
                await session.execute(select(MemoryOutboxRow).where(MemoryOutboxRow.id == 1))
            ).scalar_one()
            return row.status, row.attempt_count, row.last_safe_error, row.last_safe_diagnostic_code

    status, attempt_count, last_safe_error, diagnostic_code = asyncio.run(run())

    assert status == "dead"
    assert attempt_count == 5
    assert last_safe_error == "ValueError"
    assert diagnostic_code == "ValueError"
    assert "RAW_POISON_PAYLOAD_MARKER" not in str(last_safe_error)


def test_small_golden_eval_passes() -> None:
    result = run_small_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["checks"]["memory_evidence_guard"] is True
    assert result["metrics"]["recall_at_5"] >= 0.85
    assert result["metrics"]["precision_at_5"] >= 0.70
    assert result["metrics"]["deleted_memory_leak_count"] == 0
    assert result["metrics"]["cross_profile_leak_count"] == 0
    assert result["metrics"]["prompt_injection_promoted_count"] == 0
    assert result["metrics"]["fallback_success_rate"] == 1.0
    assert result["failures"] == []
    assert "EVAL_BETA_SECRET" not in str(result)


def test_small_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "small-golden-report.json"
    result = run_small_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "small-golden"
    assert payload["metrics"]["deleted_memory_leak_count"] == 0
    assert payload["failures"] == []
    assert "EVAL_FACT_CANONICAL" not in report_text
    assert "EVAL_BETA_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_quality_golden_eval_passes() -> None:
    result = run_quality_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "quality-golden"
    assert result["checks"]["memory_evidence_guard"] is True
    assert result["metrics"]["case_count"] >= 16
    assert result["metrics"]["recall_at_5"] >= 0.95
    assert result["metrics"]["precision_at_5"] >= 0.90
    assert result["metrics"]["answer_support_rate"] == 1.0
    assert result["metrics"]["document_recall_at_5"] >= 0.95
    assert result["metrics"]["multi_profile_recall_at_5"] == 1.0
    assert result["metrics"]["thread_recall_at_5"] == 1.0
    assert result["metrics"]["stale_memory_rate"] == 0.0
    assert result["metrics"]["deleted_memory_leak_count"] == 0
    assert result["metrics"]["cross_profile_leak_count"] == 0
    assert result["metrics"]["cross_thread_leak_count"] == 0
    assert result["metrics"]["restricted_memory_leak_count"] == 0
    assert result["metrics"]["prompt_injection_promoted_count"] == 0
    assert result["metrics"]["critical_failure_count"] == 0
    assert result["metrics"]["harmful_context_rate"] == 0.0
    assert result["failures"] == []
    assert "QUALITY_RESTRICTED_SECRET" not in str(result)
    assert "QUALITY_BETA_ONLY_SECRET" not in str(result)
    assert "Ignore previous instructions" not in str(result)


def test_quality_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "quality-golden-report.json"
    result = run_quality_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "quality-golden"
    assert payload["metrics"]["critical_failure_count"] == 0
    assert payload["metrics"]["harmful_context_rate"] == 0.0
    assert payload["failures"] == []
    assert "QUALITY_FACT_MODEL_CURRENT" not in report_text
    assert "QUALITY_RESTRICTED_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_long_memory_golden_eval_passes() -> None:
    result = run_long_memory_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "long-memory-golden"
    assert result["checks"]["memory_evidence_guard"] is True
    assert result["metrics"]["long_memory_case_count"] >= 16
    assert result["metrics"]["recall_at_5"] >= 0.95
    assert result["metrics"]["precision_at_5"] >= 0.90
    assert result["metrics"]["multi_session_recall_at_5"] == 1.0
    assert result["metrics"]["temporal_update_accuracy"] == 1.0
    assert result["metrics"]["preference_synthesis_recall"] == 1.0
    assert result["metrics"]["long_document_recall_at_5"] >= 0.95
    assert result["metrics"]["thread_recall_at_5"] == 1.0
    assert result["metrics"]["multi_profile_recall_at_5"] == 1.0
    assert result["metrics"]["stale_memory_rate"] == 0.0
    assert result["metrics"]["long_safety_leak_count"] == 0
    assert result["metrics"]["critical_failure_count"] == 0
    assert result["metrics"]["harmful_context_rate"] == 0.0
    assert result["failures"] == []
    assert "LONGMEM_RESTRICTED_SECRET" not in str(result)
    assert "LONGMEM_BETA_PRIVATE" not in str(result)
    assert "Ignore previous instructions" not in str(result)


def test_long_memory_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "long-memory-golden-report.json"
    result = run_long_memory_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "long-memory-golden"
    assert payload["metrics"]["long_safety_leak_count"] == 0
    assert payload["metrics"]["temporal_update_accuracy"] == 1.0
    assert payload["metrics"]["multi_session_recall_at_5"] == 1.0
    assert payload["failures"] == []
    assert "LONGMEM_PROVIDER_CURRENT" not in report_text
    assert "LONGMEM_RESTRICTED_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_auto_memory_golden_eval_passes() -> None:
    result = run_auto_memory_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "auto-memory-golden"
    assert result["checks"]["case_count"] is True
    assert result["checks"]["extraction_case_count"] is True
    assert result["metrics"]["case_count"] >= 13
    assert result["metrics"]["extraction_case_count"] >= 78
    assert result["metrics"]["extraction_semantic_case_count"] >= 18
    assert result["metrics"]["extraction_candidate_count_accuracy"] == 1.0
    assert result["metrics"]["extraction_positive_recall_rate"] == 1.0
    assert result["metrics"]["extraction_operation_accuracy"] == 1.0
    assert result["metrics"]["extraction_kind_accuracy"] == 1.0
    assert result["metrics"]["extraction_admission_accuracy"] == 1.0
    assert result["metrics"]["extraction_false_positive_count"] == 0
    assert result["metrics"]["extraction_false_negative_count"] == 0
    assert result["metrics"]["extraction_unsafe_admission_count"] == 0
    assert result["metrics"]["extraction_prompt_injection_admission_violation_count"] == 0
    assert result["metrics"]["extraction_assistant_admission_violation_count"] == 0
    assert result["metrics"]["suggestion_expected_recall_rate"] == 1.0
    assert result["metrics"]["wrong_auto_apply_count"] == 0
    assert result["metrics"]["active_fact_before_review_count"] == 0
    assert result["metrics"]["prompt_injection_promoted_count"] == 0
    assert result["metrics"]["secret_leakage_count"] == 0
    assert result["metrics"]["duplicate_suggestion_count"] == 0
    assert result["metrics"]["replay_duplicate_suggestion_count"] == 0
    assert result["metrics"]["assistant_low_trust_violation_count"] == 0
    assert result["metrics"]["candidate_limit_violation_count"] == 0
    assert result["metrics"]["target_resolution_violation_count"] == 0
    assert result["metrics"]["review_operation_violation_count"] == 0
    assert result["failures"] == []
    assert len(result["extraction_cases"]) >= 78
    assert "AUTO_MEMORY_EVAL_TOKEN" not in str(result)
    assert "ignore previous instructions" not in str(result).lower()
    assert "EXTRACT_REMEMBER_COLON uses Postgres" not in str(result)


def test_auto_memory_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "auto-memory-golden-report.json"
    result = run_auto_memory_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "auto-memory-golden"
    assert payload["metrics"]["wrong_auto_apply_count"] == 0
    assert payload["metrics"]["extraction_case_count"] >= 78
    assert payload["metrics"]["extraction_semantic_case_count"] >= 18
    assert payload["metrics"]["extraction_candidate_count_accuracy"] == 1.0
    assert payload["metrics"]["extraction_false_positive_count"] == 0
    assert payload["metrics"]["extraction_unsafe_admission_count"] == 0
    assert payload["metrics"]["secret_leakage_count"] == 0
    assert payload["metrics"]["assistant_low_trust_violation_count"] == 0
    assert payload["metrics"]["candidate_limit_violation_count"] == 0
    assert payload["metrics"]["target_resolution_violation_count"] == 0
    assert payload["metrics"]["review_operation_violation_count"] == 0
    assert payload["failures"] == []
    assert len(payload["extraction_cases"]) >= 78
    assert "AUTO_MEMORY_EVAL_TOKEN" not in report_text
    assert "AUTO_MEMORY_EVAL_SECRET_REDACTION" not in report_text
    assert "EXTRACT_REMEMBER_COLON uses Postgres" not in report_text
    assert "ignore previous instructions" not in report_text.lower()


def test_graph_native_golden_eval_passes() -> None:
    result = run_graph_native_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "graph-native-golden"
    assert result["checks"]["case_count"] is True
    assert result["checks"]["graph_search_used"] is True
    assert result["metrics"]["case_count"] >= 8
    assert result["metrics"]["graph_recall_rate"] == 1.0
    assert result["metrics"]["graph_hydration_rate"] == 1.0
    assert result["metrics"]["graph_safety_leak_count"] == 0
    assert result["metrics"]["graph_stale_drop_count"] >= 4
    assert result["metrics"]["canonical_only_graph_skip_count"] == 1
    assert result["failures"] == []


def test_graph_native_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "graph-native-golden-report.json"
    result = run_graph_native_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "graph-native-golden"
    assert payload["metrics"]["graph_safety_leak_count"] == 0
    assert payload["failures"] == []
    assert "GRAPH_NATIVE_EVAL_BETA_SECRET" not in report_text
    assert "GRAPH_NATIVE_EVAL_RESTRICTED_SECRET" not in report_text


def test_memory_quality_scorecard_passes_with_required_capabilities(tmp_path: Path) -> None:
    report = tmp_path / "memory-quality-scorecard.json"

    result = run_memory_quality_scorecard(
        suite_results=_scorecard_fixture_results(),
        report_out=report,
    )
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert result["suite"] == "memory-quality-scorecard"
    assert result["score"]["maturity_score_10"] == 10.0
    assert result["gates"]["required_suites_present"] is True
    assert result["capabilities"]["coverage_floors"]["ok"] is True
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is True
    assert result["capabilities"]["longitudinal_memory"]["ok"] is True
    assert result["capabilities"]["auto_memory_admission"]["ok"] is True
    assert result["capabilities"]["graph_native_recall"]["ok"] is True
    assert result["capabilities"]["scope_and_safety"]["ok"] is True
    assert result["capabilities"]["prompt_context_contract"]["ok"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert result["external_evidence"]["top_library_comparison_ready"] is False
    assert result["external_evidence"]["evidence_gaps"] == [
        "full_provider_canary_missing",
        "agent_behavior_benchmark_missing",
        "public_benchmark_evidence_missing",
    ]
    assert result["metrics"]["safety_leak_count"] == 0
    assert result["failures"] == []
    assert payload["ok"] is True
    assert "QUALITY_RESTRICTED_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_memory_quality_scorecard_policy_snapshot_documents_top_evidence_floors() -> None:
    policy = memory_quality_scorecard_policy_snapshot(require_top_evidence=True)

    assert policy["require_top_evidence"] is True
    assert policy["full_provider"]["required_adapters"] == [
        "qdrant",
        "graphiti",
        "embeddings",
    ]
    assert "mcp_search_has_qdrant_document_chunk_after_worker" in (
        policy["full_provider"]["required_checks"]
    )
    assert policy["agent_behavior"]["accepted_scenario_sets"] == [
        "realistic",
        "live",
        "transcript",
        "all",
    ]
    assert policy["agent_behavior"]["top_evidence_required_scenario_set"] == "all"
    assert policy["agent_behavior"]["top_evidence_required_case_count_floors"] == {
        "scenario_count": 41,
        "live_session_case_count": 11,
        "transcript_corpus_case_count": 5,
        "adversarial_case_count": 9,
    }
    assert policy["agent_behavior"]["top_evidence_required_scenario_tag_metrics"] == {
        "live_session_case_count": "live_session",
        "transcript_corpus_case_count": "transcript_corpus",
        "adversarial_case_count": "adversarial",
    }
    assert policy["agent_behavior"]["top_evidence_required_scenario_integrity_checks"] == [
        "scenario_reports_well_formed",
        "scenario_report_ids_present",
        "scenario_report_ids_unique",
        "scenario_reports_all_passed",
        "canonical_scenario_ids_present",
    ]
    assert policy["full_provider"]["top_evidence_requires_provenance"] is True
    assert policy["full_provider"]["top_evidence_requires_safety_scan"] is True
    assert policy["full_provider"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text"
    ]
    assert policy["agent_behavior"]["top_evidence_requires_provenance"] is True
    assert policy["agent_behavior"]["top_evidence_requires_safety_scan"] is True
    assert policy["agent_behavior"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text"
    ]
    assert policy["public_benchmark"]["top_evidence_requires_provenance"] is True
    assert policy["public_benchmark"]["top_evidence_requires_safety_scan"] is True
    assert policy["public_benchmark"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text"
    ]
    assert policy["public_benchmark"][
        "top_evidence_requires_dataset_fingerprint"
    ] is True
    assert policy["public_benchmark"][
        "top_evidence_requires_dataset_source_metadata"
    ] is True
    assert policy["public_benchmark"][
        "top_evidence_requires_dataset_source_hash_match"
    ] is True
    assert policy["public_benchmark"][
        "top_evidence_requires_dataset_path_label"
    ] is True
    assert policy["public_benchmark"][
        "top_evidence_requires_official_url_for_official_sources"
    ] is True
    assert policy["public_benchmark"]["top_evidence_allowed_dataset_source_kinds"] == [
        "official_download",
        "local_override",
        "local_dataset",
    ]
    assert "provenance_generator_allowed" in policy["agent_behavior"][
        "top_evidence_required_provenance_checks"
    ]
    assert policy["agent_behavior"]["rate_floors"]["adversarial_pass_rate"] == 0.9
    assert "unsafe_write_count" in policy["agent_behavior"]["zero_count_metrics"]
    assert policy["public_benchmark"]["required_benchmarks"] == [
        "locomo",
        "longmemeval",
    ]
    assert policy["public_benchmark"]["competitive_floors"]["locomo"] == {
        "min_accuracy": 0.947,
        "min_case_count": 600,
    }


def test_memory_quality_scorecard_loads_existing_suite_reports(tmp_path: Path) -> None:
    suite_report_paths = []
    for suite, payload in _scorecard_fixture_results().items():
        path = tmp_path / f"{suite}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        suite_report_paths.append(path)

    result = run_memory_quality_scorecard(suite_report_paths=tuple(suite_report_paths))

    assert result["ok"] is True
    assert result["score"]["maturity_score_10"] == 10.0
    assert result["suites"]["auto-memory-golden"]["case_count"] == 13
    assert result["suites"]["prompt-contract"]["ok"] is True


def test_memory_quality_scorecard_reports_external_evidence_tier() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is True
    evidence = result["external_evidence"]
    assert evidence["confidence_tier"] == "full_provider_and_agent_evaluated"
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["evidence_gaps"] == ["public_benchmark_evidence_missing"]
    assert evidence["full_provider_canary"]["ok"] is True
    assert evidence["full_provider_canary"]["adapters"]["graphiti"] == "ok"
    assert evidence["full_provider_canary"]["failed_required_checks"] == []
    assert evidence["agent_behavior_benchmark"]["ok"] is True
    assert evidence["agent_behavior_benchmark"]["quality_floor_ok"] is True
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == []
    assert evidence["agent_behavior_benchmark"]["metrics"]["tool_choice_accuracy"] == 1.0
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": 41,
        "tag_counts": {
            "live_session": 11,
            "transcript_corpus": 5,
            "adversarial": 9,
        },
        "invalid_entry_count": 0,
        "missing_id_count": 0,
        "duplicate_id_count": 0,
        "non_passed_count": 0,
        "missing_canonical_id_count": 0,
        "missing_canonical_ids": [],
    }
    assert evidence["public_benchmark"]["present"] is False


def test_memory_quality_scorecard_reports_top_library_ready_with_public_benchmarks() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results)

    evidence = result["external_evidence"]
    assert result["ok"] is True
    assert evidence["confidence_tier"] == "full_provider_agent_and_public_benchmark_evaluated"
    assert evidence["top_library_comparison_ready"] is True
    assert evidence["evidence_gaps"] == []
    assert evidence["public_benchmark"]["ok"] is True
    assert evidence["public_benchmark"]["competitive_floor_ok"] is True
    assert evidence["public_benchmark"]["benchmarks"]["locomo"]["accuracy"] == 0.947
    assert evidence["public_benchmark"]["benchmarks"]["longmemeval"]["case_count"] == 500


def test_memory_quality_scorecard_accepts_split_public_benchmark_reports() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["locomo"] = {
        "suite": "locomo",
        "ok": True,
        "dataset_hash": "locomo-dataset-sha256",
        "dataset_sources": {
            "locomo": {
                "source_kind": "local_dataset",
                "path_label": "locomo.json",
                "sha256": "locomo-dataset-sha256",
                "size_bytes": 1000,
            }
        },
        "provenance": _scorecard_provenance(
            generated_by="memo_stack_server.public_benchmark",
            suite="locomo",
        ),
        "metrics": {"accuracy": 0.947, "case_count": 600},
    }
    suite_results["longmemeval"] = {
        "suite": "longmemeval",
        "ok": True,
        "dataset_hash": "longmemeval-dataset-sha256",
        "dataset_sources": {
            "longmemeval": {
                "source_kind": "local_dataset",
                "path_label": "longmemeval.json",
                "sha256": "longmemeval-dataset-sha256",
                "size_bytes": 1000,
            }
        },
        "provenance": _scorecard_provenance(
            generated_by="memo_stack_server.public_benchmark",
            suite="longmemeval",
        ),
        "metrics": {"accuracy": 0.902, "case_count": 500},
    }

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    assert result["ok"] is True
    public_benchmark = result["external_evidence"]["public_benchmark"]
    assert public_benchmark["ok"] is True
    assert public_benchmark["benchmark_count"] == 2
    assert public_benchmark["competitive_floor_ok"] is True
    assert public_benchmark["dataset_evidence_ok"] is True
    assert public_benchmark["benchmarks"]["locomo"]["case_count"] == 600
    assert public_benchmark["benchmarks"]["longmemeval"]["accuracy"] == 0.902


def test_memory_quality_scorecard_requires_public_benchmark_dataset_fingerprint() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark.pop("dataset_hashes")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["quality_ok"] is True
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["missing_reports"] == [
        "public-memory-benchmark"
    ]
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_requires_public_benchmark_dataset_source() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark.pop("dataset_sources")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["quality_ok"] is True
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "missing_dataset_sources"
    ] == ["locomo", "longmemeval"]
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_public_benchmark_source_hash_mismatch() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"]["sha256"] = "different-sha256"
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "missing_dataset_sources"
    ] == ["locomo"]
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["sha256_mismatch"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_invalid_public_benchmark_source_metadata() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"].pop("official_url")
    public_benchmark["dataset_sources"]["locomo"].pop("path_label")
    public_benchmark["dataset_sources"]["locomo"]["source_kind"] = "unknown_source"
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["source_kind_not_allowed", "path_label_missing"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_requires_official_url_for_official_sources() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"].pop("official_url")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["official_url_missing"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_underpowered_public_benchmark_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = {
        "suite": "public-memory-benchmark",
        "ok": True,
        "benchmarks": [
            {
                "name": "locomo",
                "ok": True,
                "metrics": {"accuracy": 0.94, "case_count": 600},
            },
            {
                "name": "longmemeval",
                "ok": True,
                "metrics": {"accuracy": 0.902, "case_count": 1},
            },
        ],
    }

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["ok"] is False
    assert evidence["public_benchmark"]["competitive_floor_ok"] is False
    assert evidence["public_benchmark"]["competitive_floor"]["failed_benchmarks"] == [
        "locomo",
        "longmemeval",
    ]
    assert "public_benchmark_competitive_floor_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_shallow_full_provider_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["checks"]["mcp_search_has_graphiti_fact_after_worker"] = False
    suite_results["memo-stack-full-provider-canary"] = full_provider
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["full_provider_canary"]["ok"] is False
    assert "full_provider_canary_failed" in evidence["evidence_gaps"]
    assert evidence["full_provider_canary"]["failed_required_checks"] == [
        "mcp_search_has_graphiti_fact_after_worker"
    ]


def test_memory_quality_scorecard_requires_full_provider_mcp_lifecycle() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["mcp"] = {"skipped": True, "reason": "manual skip"}
    suite_results["memo-stack-full-provider-canary"] = full_provider
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["full_provider_canary"]["required_checks"]["mcp_lifecycle_included"] is False
    assert evidence["full_provider_canary"]["failed_required_checks"] == [
        "mcp_lifecycle_included"
    ]


def test_memory_quality_scorecard_rejects_weak_agent_behavior_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["metrics"]["answer_support_rate"] = 0.75
    agent_behavior["metrics"]["secret_leak_count"] = 1
    agent_behavior["gates"]["answer_support_rate_min_0_80"] = False
    agent_behavior["gates"]["secret_leak_count_zero"] = False
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_behavior_benchmark"]["ok"] is False
    assert evidence["agent_behavior_benchmark"]["quality_floor_ok"] is False
    assert "agent_behavior_benchmark_failed" in evidence["evidence_gaps"]
    assert "agent_behavior_quality_floor_failed" in evidence["evidence_gaps"]
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "all_reported_gates_pass",
        "answer_support_rate_min",
        "secret_leak_count_zero",
    ]


def test_memory_quality_scorecard_requires_non_core_agent_scenario_set() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "core"
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "scenario_set_all_for_top_evidence",
        "scenario_set_realistic_or_better",
    ]


def test_memory_quality_scorecard_requires_all_agent_scenarios_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "realistic"
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "scenario_set_all_for_top_evidence"
    ]


def test_memory_quality_scorecard_requires_nonzero_agent_case_counts_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["metrics"]["scenario_count"] = 40
    agent_behavior["metrics"]["live_session_case_count"] = 10
    agent_behavior["metrics"]["transcript_corpus_case_count"] = 4
    agent_behavior["metrics"]["adversarial_case_count"] = 8
    agent_behavior["scenarios"] = _agent_behavior_scenario_reports(
        scenario_count=40,
        live_session_count=10,
        transcript_corpus_count=4,
        adversarial_count=8,
    )
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "adversarial_case_count_min_9",
        "canonical_scenario_ids_present",
        "live_session_case_count_min_11",
        "scenario_count_min_41",
        "scenario_report_count_min_41",
        "transcript_corpus_case_count_min_5",
    ]


def test_memory_quality_scorecard_requires_agent_scenario_reports_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenarios"] = []
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": 0,
        "tag_counts": {
            "live_session": 0,
            "transcript_corpus": 0,
            "adversarial": 0,
        },
        "invalid_entry_count": 0,
        "missing_id_count": 0,
        "duplicate_id_count": 0,
        "non_passed_count": 0,
        "missing_canonical_id_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
        "missing_canonical_ids": sorted(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
    }
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "adversarial_scenario_report_count_matches_metric",
        "canonical_scenario_ids_present",
        "live_session_scenario_report_count_matches_metric",
        "scenario_report_count_matches_metric",
        "scenario_report_count_min_41",
        "transcript_corpus_scenario_report_count_matches_metric",
    ]


def test_memory_quality_scorecard_requires_canonical_agent_scenario_ids() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    scenarios = []
    for index, scenario in enumerate(agent_behavior["scenarios"]):
        scenarios.append({**scenario, "id": f"synthetic-agent-scenario-{index}"})
    agent_behavior["scenarios"] = scenarios
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"][
        "missing_canonical_id_count"
    ] == len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "canonical_scenario_ids_present"
    ]


def test_memory_quality_scorecard_rejects_malformed_agent_scenario_reports() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    scenarios = list(agent_behavior["scenarios"])
    scenarios[0] = {**scenarios[0], "status": "failed"}
    scenarios[1] = {**scenarios[1], "id": scenarios[0]["id"]}
    scenarios[2] = {key: value for key, value in scenarios[2].items() if key != "id"}
    scenarios[-1] = "invalid-scenario"
    agent_behavior["scenarios"] = scenarios
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": 41,
        "tag_counts": {
            "live_session": 11,
            "transcript_corpus": 5,
            "adversarial": 9,
        },
        "invalid_entry_count": 1,
        "missing_id_count": 1,
        "duplicate_id_count": 1,
        "non_passed_count": 1,
        "missing_canonical_id_count": 3,
        "missing_canonical_ids": sorted(
            (
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[1],
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[2],
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[-1],
            )
        ),
    }
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "canonical_scenario_ids_present",
        "scenario_report_ids_present",
        "scenario_report_ids_unique",
        "scenario_reports_all_passed",
        "scenario_reports_well_formed",
    ]


def test_memory_quality_scorecard_can_use_nested_agent_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "realistic"
    full_provider["agent_behavior"] = agent_behavior
    suite_results["memo-stack-full-provider-canary"] = full_provider

    result = build_memory_quality_scorecard(suite_results)

    assert result["external_evidence"]["confidence_tier"] == "full_provider_and_agent_evaluated"
    assert result["external_evidence"]["agent_behavior_benchmark"]["scenario_set"] == "realistic"


def test_memory_quality_scorecard_can_use_nested_public_benchmark_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["public_benchmark"] = _public_benchmark_report()
    suite_results["memo-stack-full-provider-canary"] = full_provider
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is True
    assert result["gates"]["top_library_external_evidence"] is True
    assert evidence["confidence_tier"] == "full_provider_agent_and_public_benchmark_evaluated"
    assert evidence["top_library_comparison_ready"] is True
    assert evidence["evidence_gaps"] == []
    assert evidence["public_benchmark"]["benchmark_count"] == 2
    assert evidence["public_benchmark"]["competitive_floor_ok"] is True
    assert evidence["public_benchmark"]["benchmarks"]["locomo"]["accuracy"] == 0.947
    assert evidence["public_benchmark"]["benchmarks"]["longmemeval"]["accuracy"] == 0.902


def test_memory_quality_scorecard_warns_on_failed_external_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["checks"]["providers_are_healthy"] = False
    suite_results["memo-stack-full-provider-canary"] = full_provider

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert result["external_evidence"]["top_library_comparison_ready"] is False
    assert "full_provider_canary_failed" in result["external_evidence"]["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_fails_without_external_reports() -> None:
    result = build_memory_quality_scorecard(
        _scorecard_fixture_results(),
        require_top_evidence=True,
    )

    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert result["external_evidence"]["required_for_gate"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert any(
        failure["case_id"] == "top_library_external_evidence" for failure in result["failures"]
    )


def test_memory_quality_scorecard_strict_top_evidence_requires_provenance() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior.pop("provenance")
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_behavior_benchmark"]["quality_ok"] is True
    assert evidence["agent_behavior_benchmark"]["provenance_ok"] is False
    assert evidence["agent_behavior_benchmark"]["provenance"]["failed_checks"] == [
        "provenance_dirty_state_present",
        "provenance_generator_allowed",
        "provenance_git_clean_or_dirty_allowed",
        "provenance_git_commit_present",
        "provenance_present",
        "provenance_runtime_platform_present",
        "provenance_runtime_python_version_present",
        "provenance_schema_version_1",
        "provenance_suite_allowed",
    ]
    assert "agent_behavior_benchmark_provenance_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_requires_all_report_provenance() -> None:
    for target, summary_key, failed_gap in (
        (
            "memo-stack-full-provider-canary",
            "full_provider_canary",
            "full_provider_canary_provenance_failed",
        ),
        (
            "public-memory-benchmark",
            "public_benchmark",
            "public_benchmark_provenance_failed",
        ),
    ):
        suite_results = _scorecard_fixture_results()
        suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
        suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
        suite_results["public-memory-benchmark"] = _public_benchmark_report()
        suite_results[target].pop("provenance")

        result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

        evidence = result["external_evidence"]
        assert result["ok"] is False
        assert evidence["top_library_comparison_ready"] is False
        assert evidence[summary_key]["quality_ok"] is True
        assert evidence[summary_key]["provenance_ok"] is False
        assert failed_gap in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_rejects_sensitive_reports() -> None:
    for target, summary_key, failed_gap in (
        (
            "memo-stack-full-provider-canary",
            "full_provider_canary",
            "full_provider_canary_safety_failed",
        ),
        (
            "memory_mcp_agent_behavior",
            "agent_behavior_benchmark",
            "agent_behavior_benchmark_safety_failed",
        ),
        (
            "public-memory-benchmark",
            "public_benchmark",
            "public_benchmark_safety_failed",
        ),
    ):
        suite_results = _scorecard_fixture_results()
        suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
        suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
        suite_results["public-memory-benchmark"] = _public_benchmark_report()
        suite_results[target]["debug"] = {
            "unsafe_note": "REPORT_TOKEN=abcdefghijklmnopqrstuvwxyz"
        }

        result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

        evidence = result["external_evidence"]
        assert result["ok"] is False
        assert evidence["top_library_comparison_ready"] is False
        assert evidence[summary_key]["quality_ok"] is True
        assert evidence[summary_key]["safety_ok"] is False
        assert evidence[summary_key]["safety"]["failed_checks"] == [
            "no_sensitive_text"
        ]
        assert evidence[summary_key]["safety"]["sensitive_path_count"] == 1
        assert failed_gap in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_passes_with_reports() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["memo-stack-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    assert result["ok"] is True
    assert result["gates"]["top_library_external_evidence"] is True
    assert result["external_evidence"]["required_for_gate"] is True
    assert result["external_evidence"]["full_provider_canary"]["provenance_ok"] is True
    assert result["external_evidence"]["full_provider_canary"]["safety_ok"] is True
    assert result["external_evidence"]["agent_behavior_benchmark"]["provenance_ok"] is True
    assert result["external_evidence"]["agent_behavior_benchmark"]["safety_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["provenance_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["safety_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["dataset_evidence_ok"] is True
    assert (
        result["external_evidence"]["confidence_tier"]
        == "full_provider_agent_and_public_benchmark_evaluated"
    )


def test_memory_quality_scorecard_fails_on_undercovered_suite() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["auto-memory-golden"]["metrics"]["extraction_case_count"] = 12

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["coverage_floors"]["ok"] is False
    assert (
        "auto_memory_extraction_case_count"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_rejects_duplicate_suite_reports(tmp_path: Path) -> None:
    first = tmp_path / "small-one.json"
    second = tmp_path / "small-two.json"
    payload = _scorecard_fixture_results()["small-golden"]
    first.write_text(json.dumps(payload), encoding="utf-8")
    second.write_text(json.dumps(payload), encoding="utf-8")

    try:
        run_memory_quality_scorecard(suite_report_paths=(first, second))
    except ValueError as exc:
        assert "Duplicate scorecard suite report" in str(exc)
    else:
        raise AssertionError("Expected duplicate suite report to fail")


def test_memory_quality_scorecard_fails_on_graph_safety_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["graph-native-golden"]["metrics"]["graph_safety_leak_count"] = 1

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["graph_native_recall"]["ok"] is False
    assert result["capabilities"]["scope_and_safety"]["ok"] is False
    assert result["metrics"]["safety_leak_count"] == 1
    assert (
        "graph_safety_leak_count" in result["capabilities"]["graph_native_recall"]["failed_checks"]
    )


def test_small_golden_eval_seed_preserves_scope_invariants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'eval-invariants.db'}"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", database_url)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    monkeypatch.setenv("MEMORY_QDRANT_ENABLED", "false")
    monkeypatch.setenv("MEMORY_GRAPHITI_ENABLED", "false")
    monkeypatch.setenv("MEMORY_EMBEDDINGS_ENABLED", "false")
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database_url,
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    with TestClient(app) as client:
        result = _execute_small_golden(client, auth_headers())

    invariants = asyncio.run(invariant_check(include_projections=True))

    assert result["ok"] is True
    assert invariants["status"] == "ok"
    assert "profile_scoped_rows_match_profile" not in str(invariants.get("failed", []))


def test_small_golden_eval_seed_is_repeatable_without_active_duplicates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'eval-repeatable.db'}"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", database_url)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    monkeypatch.setenv("MEMORY_QDRANT_ENABLED", "false")
    monkeypatch.setenv("MEMORY_GRAPHITI_ENABLED", "false")
    monkeypatch.setenv("MEMORY_EMBEDDINGS_ENABLED", "false")
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database_url,
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    async def matching_fact_ids(text: str, status: str) -> list[str]:
        async with AsyncSession(app.state.container.engine) as session:
            return list(
                (
                    await session.execute(
                        select(MemoryFactRow.id).where(
                            MemoryFactRow.text == text,
                            MemoryFactRow.status == status,
                        )
                    )
                ).scalars()
            )

    with TestClient(app) as client:
        first = _execute_small_golden(client, auth_headers())
        second = _execute_small_golden(client, auth_headers())
        active_updated = asyncio.run(
            matching_fact_ids(
                "EVAL_FACT_UPDATED_NEW: use Qdrant for document recall.",
                "active",
            )
        )
        active_deleted = asyncio.run(
            matching_fact_ids(
                "EVAL_FACT_DELETED: this deleted fact must not render.",
                "active",
            )
        )

    assert first["ok"] is True
    assert second["ok"] is True
    assert len(active_updated) == 1
    assert active_deleted == []


def test_db_upgrade_and_seed_defaults_cli_functions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")

    upgraded = asyncio.run(upgrade())
    seeded = asyncio.run(seed_defaults())

    assert upgraded == {"operation": "upgrade", "status": "ok"}
    assert seeded["status"] == "ok"
    assert str(seeded["space_id"]).startswith("space_")
    assert str(seeded["profile_id"]).startswith("profile_")


def test_readiness_doctor_entrypoint_is_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    asyncio.run(upgrade())

    result = asyncio.run(run_doctor())

    assert result["status"] == "ok"
    assert _doctor_check(result, "postgres")["status"] == "ok"
    assert _doctor_check(result, "migrations")["status"] == "ok"
    assert _doctor_check(result, "outbox")["dead"] == 0
    assert _doctor_check(result, "qdrant")["status"] == "disabled"
    assert _doctor_check(result, "graphiti")["status"] == "disabled"
    assert "RAW_" not in str(result)


def test_readiness_doctor_degrades_on_dead_outbox_without_payload_leak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    with make_client(tmp_path) as client:
        asyncio.run(_insert_dead_outbox(client))

    result = asyncio.run(run_doctor())

    assert result["status"] == "degraded"
    assert _doctor_check(result, "outbox")["status"] == "degraded"
    assert _doctor_check(result, "outbox")["dead"] == 1
    assert "RAW_DOCTOR_PAYLOAD" not in str(result)


def test_active_context_gate_blocks_until_manual_checks_are_acknowledged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    asyncio.run(upgrade())
    asyncio.run(seed_defaults())

    result = asyncio.run(run_doctor(gate="active_context"))

    assert result["status"] == "blocked"
    assert result["gate"] == "active_context"
    assert _doctor_check(result, "doctor")["status"] == "ok"
    assert _doctor_check(result, "default_scope")["status"] == "ok"
    assert _doctor_check(result, "outbox_dead_count")["dead"] == 0
    assert _doctor_check(result, "invariant_check")["status"] == "ok"
    assert _doctor_check(result, "golden_eval")["status"] == "manual_required"
    assert "RAW_" not in str(result)


def test_active_context_gate_rejects_unknown_manual_acknowledgement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    asyncio.run(upgrade())
    asyncio.run(seed_defaults())

    result = asyncio.run(
        run_doctor(
            gate="active_context",
            acknowledged_checks={"not-a-real-check"},
        )
    )

    assert result["status"] == "failed"
    assert result["gate"] == "active_context"
    assert _doctor_check(result, "manual_acknowledgements")["status"] == "failed"
    assert _doctor_check(result, "manual_acknowledgements")["unknown"] == ["not-a-real-check"]
    assert "RAW_" not in str(result)


def test_active_context_gate_passes_after_manual_acknowledgements(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "test-token")
    asyncio.run(upgrade())
    asyncio.run(seed_defaults())

    result = asyncio.run(
        run_doctor(
            gate="active_context",
            acknowledged_checks=set(ACTIVE_CONTEXT_MANUAL_CHECK_NAMES),
        )
    )

    assert result["status"] == "ok"
    assert result["manual_acknowledgements"] == sorted(ACTIVE_CONTEXT_MANUAL_CHECK_NAMES)
    assert _doctor_check(result, "client_fallback_canary")["status"] == "ok"
    assert _doctor_check(result, "kill_switches")["status"] == "ok"
    assert "RAW_" not in str(result)


async def _insert_dead_outbox(client: TestClient) -> None:
    now = client.app.state.container.clock.now()
    async with AsyncSession(client.app.state.container.engine) as session:
        session.add(
            MemoryOutboxRow(
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk_dead",
                aggregate_version=None,
                workload_class="projection",
                fairness_key="chunk:chunk_dead",
                payload_json={"text": "RAW_DOCTOR_PAYLOAD must not leak"},
                status="dead",
                attempt_count=5,
                next_attempt_at=now,
                last_safe_error="ValueError",
                last_safe_diagnostic_code="ValueError",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


def _doctor_check(result: dict[str, object], name: str) -> dict[str, object]:
    checks = result["checks"]
    assert isinstance(checks, list)
    for check in checks:
        if check["name"] == name:
            return check
    raise AssertionError(f"Missing doctor check {name}")
