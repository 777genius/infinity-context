import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from fastapi.testclient import TestClient
from infinity_context_adapters.features.memory_facts import (
    create_memory_fact_id_adapter,
    create_postgres_memory_fact_unit_of_work_factory,
)
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres.feature_models import MemoryFactOperationReceiptRow
from infinity_context_adapters.postgres.models import (
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySourceRefRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.temporal_models import MemoryFactTemporalDecisionRow
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkRememberFactAdmission,
)
from infinity_context_core.application.dto_benchmark_runs import RegisterBenchmarkRunCommand
from infinity_context_core.application.use_cases.benchmark_runs import RegisterBenchmarkRunUseCase
from infinity_context_core.features.memory_facts.application.commands import RememberFactCommand
from infinity_context_core.features.memory_facts.application.handlers import RememberFactHandler
from infinity_context_core.features.memory_facts.domain import (
    MemoryFactScope,
    MemoryFactSourceRef,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE = f"benchmark-space-{RUN[:48]}"
SLUG = "memory-comparison-managed-fact-concurrency"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_concurrent_managed_fact_replay_creates_one_canonical_write(tmp_path: Path) -> None:
    asyncio.run(_concurrent_managed_fact_contract(tmp_path))


def test_managed_fact_update_and_forget_endpoints_are_zero_mutation(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'managed-fact-api.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    with TestClient(app) as client:
        asyncio.run(_register_and_seed(client.app.state.container))
        payload = {
            "space_id": SPACE,
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "text": "The benchmark requires exact cleanup.",
            "kind": "requirement",
            "source_refs": [
                {
                    "source_type": "memory_comparison_benchmark",
                    "source_id": "source-1",
                    "quote_preview": "The benchmark requires exact cleanup.",
                }
            ],
        }
        created = client.post("/v1/facts", json=payload, headers=_headers())
        fact_id = created.json()["data"]["id"]
        updated = client.patch(
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": 1,
                "text": payload["text"] + " changed",
                "reason": "must be immutable",
                "source_refs": payload["source_refs"],
            },
            headers=_headers(),
        )
        forgotten = client.delete(f"/v1/facts/{fact_id}", headers=_headers())
        counts = asyncio.run(_managed_api_counts(client.app.state.container.engine, fact_id))

    assert created.status_code == 201
    assert updated.status_code == 409
    assert forgotten.status_code == 409
    assert counts == ("active", 1, 1, 1, 0)


def test_managed_scope_routes_reject_foreign_refs_before_canonical_rows(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'managed-scope-api.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    with TestClient(app) as client:
        asyncio.run(_register_without_scope(client.app.state.container))
        exact_payload = {
            "space_slug": SLUG,
            "memory_scope_external_ref": "corpus-1",
            "thread_external_ref": "thread-1",
            "text": "The benchmark requires exact cleanup.",
            "kind": "requirement",
            "source_refs": [
                {
                    "source_type": "memory_comparison_benchmark",
                    "source_id": "source-1",
                    "quote_preview": "The benchmark requires exact cleanup.",
                }
            ],
        }
        exact = client.post("/v1/facts", json=exact_payload, headers=_headers())
        foreign_fact = client.post(
            "/v1/facts",
            json={**exact_payload, "thread_external_ref": "foreign-thread"},
            headers=_headers(),
        )
        foreign_document = client.post(
            "/v1/documents",
            json={
                "space_slug": SLUG,
                "memory_scope_external_ref": "foreign-corpus",
                "thread_external_ref": "foreign-thread",
                "title": "foreign",
                "text": "Foreign document must not create a managed scope.",
                "source_type": "benchmark",
                "source_external_id": "foreign-source",
                "classification": "internal",
            },
            headers=_headers(),
        )
        direct_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": SPACE, "external_ref": "foreign-corpus", "name": "foreign"},
            headers=_headers(),
        )
        scope_counts = asyncio.run(_scope_counts(client.app.state.container.engine))

    assert exact.status_code == 201
    assert foreign_fact.status_code == 409
    assert foreign_document.status_code == 409
    assert direct_scope.status_code == 409
    assert scope_counts == (1, 1)


async def _concurrent_managed_fact_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'managed-fact.db'}")
    await create_schema(engine)
    sessions = build_session_factory(engine)
    canonical_uow = PostgresUnitOfWorkFactory(session_factory=sessions, clock=SystemClock())
    command = _command()
    plan, plan_sha = _plan(command)
    registered = await RegisterBenchmarkRunUseCase(
        uow_factory=canonical_uow, clock=FixedClock()
    ).execute(
        RegisterBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_slug=SLUG,
            idempotency_key_sha256="d" * 64,
            cleanup_plan_json=plan,
            cleanup_plan_sha256=plan_sha,
        )
    )
    async with AsyncSession(engine) as session:
        session.add_all(
            (
                MemoryScopeRow(
                    id="scope-1",
                    space_id=registered.record.space_id,
                    external_ref="corpus-1",
                    name="corpus-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryThreadRow(
                    id="thread-1",
                    space_id=registered.record.space_id,
                    memory_scope_id="scope-1",
                    external_ref="thread-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            )
        )
        await session.commit()
    feature_uow = create_postgres_memory_fact_unit_of_work_factory(
        session_factory=sessions,
        clock=FixedClock(),
    )
    ids = create_memory_fact_id_adapter(UuidIdGenerator().new_id)
    admission = ManagedBenchmarkRememberFactAdmission(
        uow_factory=canonical_uow,
        inner=RememberFactHandler(uow_factory=feature_uow, clock=FixedClock(), ids=ids),
    )

    first, replay = await asyncio.gather(
        admission.execute(command),
        admission.execute(replace(command, idempotency_key="caller-selected-different")),
    )

    assert first.fact.identity.fact_id == replay.fact.identity.fact_id
    assert {first.replayed, replay.replayed} == {False, True}
    async with AsyncSession(engine) as session:
        counts = []
        for model in (
            MemoryFactRow,
            MemorySourceRefRow,
            MemoryFactOperationReceiptRow,
            MemoryOutboxRow,
        ):
            counts.append(int(await session.scalar(select(func.count()).select_from(model)) or 0))
    assert tuple(counts) == (1, 1, 1, 1)
    await engine.dispose()


async def _register_and_seed(container) -> None:
    command = _command()
    plan, plan_sha = _plan(command)
    await container.register_benchmark_run.execute(
        RegisterBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_slug=SLUG,
            idempotency_key_sha256="d" * 64,
            cleanup_plan_json=plan,
            cleanup_plan_sha256=plan_sha,
        )
    )
    async with AsyncSession(container.engine) as session:
        session.add_all(
            (
                MemoryScopeRow(
                    id="scope-1",
                    space_id=SPACE,
                    external_ref="corpus-1",
                    name="corpus-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryThreadRow(
                    id="thread-1",
                    space_id=SPACE,
                    memory_scope_id="scope-1",
                    external_ref="thread-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            )
        )
        await session.commit()


async def _register_without_scope(container) -> None:
    command = _command()
    plan, plan_sha = _plan(command)
    await container.register_benchmark_run.execute(
        RegisterBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_slug=SLUG,
            idempotency_key_sha256="d" * 64,
            cleanup_plan_json=plan,
            cleanup_plan_sha256=plan_sha,
        )
    )


async def _scope_counts(engine) -> tuple[int, int]:
    async with AsyncSession(engine) as session:
        return (
            int(await session.scalar(select(func.count()).select_from(MemoryScopeRow)) or 0),
            int(await session.scalar(select(func.count()).select_from(MemoryThreadRow)) or 0),
        )


async def _managed_api_counts(engine, fact_id: str) -> tuple[object, ...]:
    async with AsyncSession(engine) as session:
        fact = await session.get(MemoryFactRow, fact_id)
        return (
            fact.status,
            fact.version,
            int(await session.scalar(select(func.count()).select_from(MemoryFactVersionRow)) or 0),
            int(await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) or 0),
            int(
                await session.scalar(
                    select(func.count()).select_from(MemoryFactTemporalDecisionRow)
                )
                or 0
            ),
        )


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _command() -> RememberFactCommand:
    return RememberFactCommand(
        scope=MemoryFactScope(SPACE, "scope-1", "thread-1"),
        text="The benchmark requires exact cleanup.",
        source_refs=(
            MemoryFactSourceRef(
                source_type="memory_comparison_benchmark",
                source_id="source-1",
                quote_preview="The benchmark requires exact cleanup.",
            ),
        ),
        kind="requirement",
    )


def _plan(command: RememberFactCommand) -> tuple[dict[str, object], str]:
    plan, _ = cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)
    ref = command.source_refs[0]
    descriptor = managed_benchmark_fact_source_ref_descriptor(
        source_type=ref.source_type,
        source_id=ref.source_id,
        chunk_id=ref.chunk_id,
        char_start=ref.char_start,
        char_end=ref.char_end,
        quote_preview=ref.quote_preview,
        page_number=ref.page_number,
        time_start_ms=ref.time_start_ms,
        time_end_ms=ref.time_end_ms,
        bbox=ref.bbox,
    )
    source_sha = managed_benchmark_text_sha256(ref.source_id)
    material = managed_benchmark_fact_operation_material(
        source_external_id_sha256=source_sha,
        content_sha256=managed_benchmark_text_sha256(command.text),
        kind=command.kind,
        classification="internal",
        source_refs=(descriptor,),
    )
    plan["corpora"][0].update(
        {
            "memory_scope_external_ref_sha256": managed_benchmark_text_sha256("corpus-1"),
            "thread_external_ref_sha256": managed_benchmark_text_sha256("thread-1"),
            "ordered_infinity_operation_sha256": [
                managed_benchmark_infinity_operation_sha256(material)
            ],
            "ordered_infinity_source_external_id_sha256": [source_sha],
            "ordered_infinity_content_sha256": [material["content_sha256"]],
        }
    )
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return plan, hashlib.sha256(payload).hexdigest()


class FixedClock:
    def now(self) -> datetime:
        return NOW
