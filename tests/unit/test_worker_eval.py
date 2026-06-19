import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres import create_schema
from infinity_context_adapters.postgres.models import MemoryFactRow, MemoryOutboxRow
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    PortStatus,
    VectorWriteResult,
)
from infinity_context_core.ports.capabilities import (
    CapabilityStatus,
    ProjectionForgetResult,
    ProjectionWriteResult,
)
from infinity_context_server.admin import (
    ACTIVE_CONTEXT_MANUAL_CHECK_NAMES,
    invariant_check,
    seed_defaults,
)
from infinity_context_server.composition import build_container
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.db import upgrade
from infinity_context_server.doctor import run_doctor
from infinity_context_server.eval import (
    _execute_graph_native_golden,
    _execute_long_memory_golden,
    _execute_quality_golden,
    _execute_small_golden,
    run_auto_memory_golden,
    run_graph_native_golden,
    run_long_memory_golden,
    run_quality_golden,
    run_semantic_linking_golden,
    run_small_golden,
)
from infinity_context_server.eval_constants import (
    QUALITY_GOLDEN_REQUIRED_CASE_IDS,
    SEMANTIC_LINKING_REQUIRED_CASE_IDS,
)
from infinity_context_server.eval_graph import (
    EvalGraphMemoryAdapter,
    _install_eval_graph_adapter,
)
from infinity_context_server.eval_semantic_linking import _execute_semantic_linking_golden
from infinity_context_server.main import create_app
from infinity_context_server.worker import (
    OutboxWorker,
    OutboxWorkerFilter,
    _safe_diagnostic_code,
    _safe_error,
)
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


def test_eval_cli_uses_env_token_not_cli_auth_token() -> None:
    source = (
        Path(__file__).parents[2]
        / "packages"
        / "infinity_context_server"
        / "infinity_context_server"
        / "eval.py"
    ).read_text(encoding="utf-8")

    assert "--auth-token" not in source
    assert "MEMORY_EVAL_AUTH_TOKEN" in source
    assert "MEMORY_SERVICE_TOKEN" in source


def fact_payload(text: str = "Graph jobs stay safe when Graphiti is disabled.") -> dict[str, Any]:
    return {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
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


async def outbox_summary(client: TestClient) -> list[tuple[str, str, str]]:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                select(
                    MemoryOutboxRow.event_type,
                    MemoryOutboxRow.workload_class,
                    MemoryOutboxRow.status,
                ).order_by(MemoryOutboxRow.id)
            )
        ).all()
    return [
        (str(event_type), str(workload_class), str(status))
        for event_type, workload_class, status in rows
    ]


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


def test_extraction_worker_filter_skips_suggestion_maintenance(tmp_path: Path) -> None:
    class RecordingExpirePendingSuggestions:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, *, limit: int):
            self.calls += 1

    async def run() -> tuple[int, int]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker-filter.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        recorder = RecordingExpirePendingSuggestions()
        object.__setattr__(container, "expire_pending_suggestions", recorder)
        processed = await OutboxWorker(
            container,
            worker_filter=OutboxWorkerFilter.from_values(workload_classes=("extraction",)),
        ).run_once(limit=10)
        return processed, recorder.calls

    processed, calls = asyncio.run(run())

    assert processed == 0
    assert calls == 0


def test_projection_worker_filter_runs_suggestion_maintenance(tmp_path: Path) -> None:
    class RecordingExpirePendingSuggestions:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, *, limit: int):
            self.calls += 1

    async def run() -> tuple[int, int]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'projection-filter.db'}",
                service_token="test-token",
            )
        )
        await create_schema(container.engine)
        recorder = RecordingExpirePendingSuggestions()
        object.__setattr__(container, "expire_pending_suggestions", recorder)
        processed = await OutboxWorker(
            container,
            worker_filter=OutboxWorkerFilter.from_values(workload_classes=("projection",)),
        ).run_once(limit=10)
        return processed, recorder.calls

    processed, calls = asyncio.run(run())

    assert processed == 0
    assert calls == 1


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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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


def test_extraction_worker_filter_processes_only_extraction_jobs(tmp_path: Path) -> None:
    with make_client_with_settings(tmp_path, asset_storage_dir=str(tmp_path / "assets")) as client:
        fact = client.post("/v1/facts", json=fact_payload(), headers=auth_headers())
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "worker-contract.txt",
                "extract": "true",
            },
            content=b"Extraction worker contract should not drain projection jobs.",
            headers={**auth_headers(), "Content-Type": "text/plain"},
        )
        processed = asyncio.run(
            OutboxWorker(
                client.app.state.container,
                worker_filter=OutboxWorkerFilter.from_values(workload_classes=("extraction",)),
            ).run_once(limit=10)
        )
        summary = asyncio.run(outbox_summary(client))

    assert fact.status_code == 201
    assert upload.status_code == 201
    assert processed == 1
    assert ("graph.upsert_fact", "projection", "pending") in summary
    assert ("asset.extract", "extraction", "done") in summary
    assert any(
        event_type == "vector.upsert_chunk"
        and workload_class == "projection"
        and status == "pending"
        for event_type, workload_class, status in summary
    )


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


def test_asset_extraction_active_lease_reschedules_outbox_without_attempt_burn(
    tmp_path: Path,
) -> None:
    async def mark_extraction_running(client: TestClient, extraction_id: str):
        container = client.app.state.container
        now = container.clock.now()
        lease_expires_at = now + timedelta(minutes=15)
        async with container.uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(extraction_id)
            assert job is not None
            running = job.mark_running(
                now=now,
                lease_owner="outbox:active",
                lease_expires_at=lease_expires_at,
            )
            saved = await uow.asset_extractions.save(running)
            await uow.commit()
        return saved.lease_expires_at

    async def outbox_row_state(
        client: TestClient,
    ) -> tuple[str, int, object, str | None, str | None]:
        async with AsyncSession(client.app.state.container.engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(MemoryOutboxRow.event_type == "asset.extract")
                )
            ).scalar_one()
            return (
                row.status,
                row.attempt_count,
                row.next_attempt_at,
                row.last_safe_error,
                row.last_safe_diagnostic_code,
            )

    with make_client_with_settings(
        tmp_path,
        asset_storage_dir=str(tmp_path / "assets"),
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "active-lease.txt",
                "extract": "true",
            },
            content=b"Active extraction lease should delay duplicate outbox work.",
            headers={**auth_headers(), "Content-Type": "text/plain"},
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]
        lease_expires_at = asyncio.run(mark_extraction_running(client, extraction_id))

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        status, attempt_count, next_attempt_at, last_safe_error, diagnostic_code = asyncio.run(
            outbox_row_state(client)
        )

    assert processed == 1
    assert status == "retry_pending"
    assert attempt_count == 0
    assert next_attempt_at == lease_expires_at.replace(tzinfo=None)
    assert last_safe_error == "ActiveAssetExtractionLeaseError"
    assert diagnostic_code == "asset_extraction.lease_active"


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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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
                "memory_scope_id": "memory_scope_default",
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


def test_worker_safe_diagnostic_code_uses_wrapped_root_cause_code() -> None:
    class ParserTimeoutError(RuntimeError):
        diagnostic_code = "asset_extraction.parser_timeout"

    cause = ParserTimeoutError("RAW_PROVIDER_SECRET_MARKER should not be persisted")
    error = RuntimeError("outer wrapper")
    error.__cause__ = cause

    assert _safe_error(error) == "ParserTimeoutError"
    assert _safe_diagnostic_code(error) == "asset_extraction.parser_timeout"


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
    assert result["metrics"]["cross_memory_scope_leak_count"] == 0
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
    assert result["metrics"]["hybrid_retrieval_rate"] == 1.0
    assert result["gates"]["hybrid_retrieval_rate"] is True
    assert result["metrics"]["citation_support_rate"] == 1.0
    assert result["metrics"]["source_citation_failure_count"] == 0
    assert result["gates"]["citation_support_rate"] is True
    assert result["gates"]["source_citation_failure_count"] is True
    assert result["metrics"]["required_case_count"] == len(QUALITY_GOLDEN_REQUIRED_CASE_IDS)
    assert result["metrics"]["missing_required_case_count"] == 0
    assert result["metrics"]["required_case_coverage_rate"] == 1.0
    assert result["gates"]["missing_required_case_count"] is True
    assert result["gates"]["required_case_coverage_rate"] is True
    assert result["metrics"]["multi_memory_scope_recall_at_5"] == 1.0
    assert result["metrics"]["thread_recall_at_5"] == 1.0
    assert result["metrics"]["stale_memory_rate"] == 0.0
    assert result["metrics"]["deleted_memory_leak_count"] == 0
    assert result["metrics"]["cross_memory_scope_leak_count"] == 0
    assert result["metrics"]["cross_thread_leak_count"] == 0
    assert result["metrics"]["restricted_memory_leak_count"] == 0
    assert result["metrics"]["prompt_injection_promoted_count"] == 0
    assert result["metrics"]["critical_failure_count"] == 0
    assert result["metrics"]["harmful_context_rate"] == 0.0
    quality_case_ids = {case["case_id"] for case in result["cases"]}
    assert set(QUALITY_GOLDEN_REQUIRED_CASE_IDS) <= quality_case_ids
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
    assert payload["metrics"]["hybrid_retrieval_rate"] == 1.0
    assert payload["failures"] == []
    assert "QUALITY_FACT_MODEL_CURRENT" not in report_text
    assert "QUALITY_HYBRID_DUAL_SOURCE" not in report_text
    assert "QUALITY_HYBRID_SINGLE_SOURCE_DECOY" not in report_text
    assert "QUALITY_RESTRICTED_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_semantic_linking_golden_eval_passes(tmp_path: Path) -> None:
    report = tmp_path / "semantic-linking-golden-report.json"
    result = run_semantic_linking_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "semantic-linking-golden"
    assert result["checks"]["top_fact_beats_distractor"] is True
    assert result["checks"]["event_call_beats_recent_chat"] is True
    assert result["checks"]["temporal_intent_links_recent_fact_without_text_match"] is True
    assert result["checks"]["person_and_project_anchors_suggested"] is True
    assert result["checks"]["same_name_person_project_anchors_separate"] is True
    assert result["checks"]["high_impact_relation_requires_explicit_signal"] is True
    assert result["checks"]["weak_overlap_below_review_threshold_denied"] is True
    assert result["checks"]["evidence_relation_requires_source_signal"] is True
    assert result["checks"]["mentions_relation_requires_entity_signal"] is True
    assert result["checks"]["document_chunk_evidence_suggested"] is True
    assert result["checks"]["top_suggestion_approves_to_link"] is True
    assert result["checks"]["unrelated_capture_has_no_candidates"] is True
    assert result["checks"]["cross_scope_fact_not_suggested"] is True
    assert result["metrics"]["case_count"] >= 10
    assert result["gates"]["case_count"] is True
    assert result["metrics"]["required_case_count"] == len(SEMANTIC_LINKING_REQUIRED_CASE_IDS)
    assert result["metrics"]["missing_required_case_count"] == 0
    assert result["metrics"]["required_case_coverage_rate"] == 1.0
    assert result["gates"]["missing_required_case_count"] is True
    assert result["gates"]["required_case_coverage_rate"] is True
    assert result["metrics"]["event_linking_accuracy"] == 1.0
    assert result["metrics"]["temporal_intent_recall"] == 1.0
    assert result["metrics"]["anchor_disambiguation_rate"] == 1.0
    assert result["metrics"]["anchor_review_evidence_rate"] == 1.0
    assert result["metrics"]["high_impact_relation_policy_safety"] == 1.0
    assert result["metrics"]["weak_overlap_policy_safety"] == 1.0
    assert result["metrics"]["evidence_relation_policy_safety"] == 1.0
    assert result["metrics"]["mentions_relation_policy_safety"] == 1.0
    assert result["metrics"]["false_positive_count"] == 0
    assert result["metrics"]["cross_scope_leak_count"] == 0
    assert set(SEMANTIC_LINKING_REQUIRED_CASE_IDS) <= {
        case["case_id"] for case in result["cases"]
    }
    assert payload["suite"] == "semantic-linking-golden"
    assert "Project Atlas" not in report_text
    assert "invoice threshold" not in report_text
    assert "migration rollback" not in report_text


def test_semantic_linking_golden_eval_repeats_against_persistent_server(
    tmp_path: Path,
) -> None:
    with make_client_with_settings(tmp_path, capture_mode=CaptureMode.SUGGEST) as client:
        first = _execute_semantic_linking_golden(client, auth_headers())
        second = _execute_semantic_linking_golden(client, auth_headers())

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["metrics"]["case_count"] >= 4
    assert second["metrics"]["case_count"] >= 4
    assert first["failures"] == []
    assert second["failures"] == []


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
    assert result["metrics"]["multi_memory_scope_recall_at_5"] == 1.0
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


def test_heavy_golden_eval_suites_repeat_against_persistent_server(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'heavy-eval-repeatable.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    graph = EvalGraphMemoryAdapter()
    _install_eval_graph_adapter(app, graph)

    with TestClient(app) as client:
        results = (
            _execute_quality_golden(client, auth_headers()),
            _execute_quality_golden(client, auth_headers()),
            _execute_long_memory_golden(client, auth_headers()),
            _execute_long_memory_golden(client, auth_headers()),
            _execute_graph_native_golden(client, auth_headers(), graph),
            _execute_graph_native_golden(client, auth_headers(), graph),
        )

    assert all(result["ok"] is True for result in results)
    assert all(result["failures"] == [] for result in results)
    assert [result["suite"] for result in results] == [
        "quality-golden",
        "quality-golden",
        "long-memory-golden",
        "long-memory-golden",
        "graph-native-golden",
        "graph-native-golden",
    ]


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
    assert "memory_scope_scoped_rows_match_memory_scope" not in str(invariants.get("failed", []))


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
    assert str(seeded["memory_scope_id"]).startswith("memory_scope_")


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
