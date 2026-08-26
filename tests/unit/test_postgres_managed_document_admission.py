import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    PostgresBenchmarkRunRepository,
    _json_sha256,
)
from infinity_context_adapters.postgres.models import (
    MemoryDocumentRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.dto import IngestDocumentCommand
from infinity_context_core.application.dto_benchmark_runs import RegisterBenchmarkRunCommand
from infinity_context_core.application.normalize import content_hash
from infinity_context_core.application.use_cases.benchmark_runs import RegisterBenchmarkRunUseCase
from infinity_context_core.application.use_cases.ingest_document import IngestDocumentUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_managed_document_admission_is_exact_and_enqueues_vector_only(tmp_path: Path) -> None:
    asyncio.run(_managed_document_admission_contract(tmp_path))


async def _managed_document_admission_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'managed-ingest.db'}")
    await create_schema(engine)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    command = _ingest_command(f"benchmark-space-{RUN[:48]}", "source-1")
    plan, _ = cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)
    fragments = tuple(
        managed_benchmark_document_fragment_descriptor(
            sequence=item.sequence,
            char_start=item.char_start,
            char_end=item.char_end,
            kind=item.kind.value,
            text=item.text,
            node_kind=item.node_kind,
            heading=item.heading,
            ordinal_in_heading=item.ordinal_in_heading,
        )
        for item in fragment_document_text(command.text)
    )
    material = managed_benchmark_document_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(command.source_external_id),
        content_sha256=content_hash(command.text),
        title_sha256=managed_benchmark_text_sha256(command.title),
        source_type=command.source_type,
        classification=command.classification,
        source_refs=(),
        fragments=fragments,
    )
    corpus = plan["corpora"][0]
    corpus.update(
        {
            "memory_scope_external_ref_sha256": managed_benchmark_text_sha256("corpus-1"),
            "thread_external_ref_sha256": managed_benchmark_text_sha256("thread-1"),
            "infinity_lane": "document",
            "ordered_infinity_operation_sha256": [
                managed_benchmark_infinity_operation_sha256(material)
            ],
            "ordered_infinity_source_external_id_sha256": [material["source_external_id_sha256"]],
            "ordered_infinity_content_sha256": [material["content_sha256"]],
            "ordered_document_fragment_count": [len(fragments)],
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": len(fragments),
        }
    )
    plan["cardinality"].update(
        {
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": len(fragments),
        }
    )
    plan_sha = _json_sha256(plan)
    registered = await RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock()).execute(
        replace(_registration(), cleanup_plan_json=plan, cleanup_plan_sha256=plan_sha)
    )
    await _seed_scope_thread(engine, registered.record.space_id, scope_external_ref="corpus-1")
    ingest = IngestDocumentUseCase(
        uow_factory=factory,
        clock=FixedClock(),
        ids=UuidIdGenerator(),
    )
    with pytest.raises(MemoryConflictError, match="is not admitted"):
        await ingest.execute(_ingest_command(registered.record.space_id, "source-2"))
    async with AsyncSession(engine) as session:
        assert await session.scalar(select(func.count()).select_from(MemoryDocumentRow)) == 0
        assert await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) == 0
    result, replay = await asyncio.gather(
        ingest.execute(command),
        ingest.execute(replace(command, idempotency_key="caller-selected-different")),
    )
    assert replay.document.id == result.document.id
    with pytest.raises(MemoryConflictError, match="is not admitted"):
        await ingest.execute(replace(command, text=command.text + " changed"))
    with pytest.raises(MemoryConflictError, match="is not admitted"):
        await ingest.execute(replace(command, thread_id=ThreadId("foreign-thread")))
    async with AsyncSession(engine) as session:
        document_count = await session.scalar(select(func.count()).select_from(MemoryDocumentRow))
        event_types = tuple((await session.execute(select(MemoryOutboxRow.event_type))).scalars())
    assert len(result.chunks) == len(fragments)
    assert document_count == 1
    assert event_types == ("vector.upsert_chunk",)
    await engine.dispose()


def test_ordinary_document_admission_skips_benchmark_lookup_and_keeps_cognee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_ordinary_document_admission_contract(tmp_path, monkeypatch))


async def _ordinary_document_admission_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ordinary-ingest.db'}")
    await create_schema(engine)
    await _seed_ordinary_space(engine, "ordinary-space")

    async def forbidden_lookup(*_args, **_kwargs):
        raise AssertionError("ordinary ingest queried benchmark registry")

    monkeypatch.setattr(PostgresBenchmarkRunRepository, "get_by_space_id", forbidden_lookup)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    result = await IngestDocumentUseCase(
        uow_factory=factory, clock=FixedClock(), ids=UuidIdGenerator()
    ).execute(_ingest_command("ordinary-space", "source-ordinary"))
    assert result.indexing_status == "pending"
    async with AsyncSession(engine) as session:
        events = tuple(
            (
                await session.execute(
                    select(MemoryOutboxRow.event_type).order_by(MemoryOutboxRow.id)
                )
            ).scalars()
        )
    assert events == ("vector.upsert_chunk", "cognee.ingest_document")
    await engine.dispose()


def _ingest_command(space_id: str, source_external_id: str) -> IngestDocumentCommand:
    return IngestDocumentCommand(
        space_id=SpaceId(space_id),
        memory_scope_id=MemoryScopeId("scope-1"),
        thread_id=ThreadId("thread-1"),
        title="benchmark document",
        text="A sufficiently useful benchmark document for projection admission.",
        source_type="benchmark",
        source_external_id=source_external_id,
        classification="internal",
    )


def _registration() -> RegisterBenchmarkRunCommand:
    cleanup_plan, cleanup_plan_sha256 = cleanup_plan_pair(
        run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG
    )
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256="d" * 64,
        cleanup_plan_json=cleanup_plan,
        cleanup_plan_sha256=cleanup_plan_sha256,
    )


async def _seed_ordinary_space(engine, space_id: str) -> None:
    async with AsyncSession(engine) as session:
        session.add(
            MemorySpaceRow(
                id=space_id,
                slug=space_id,
                name=space_id,
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await _seed_scope_thread(engine, space_id, scope_external_ref="scope-1")


async def _seed_scope_thread(engine, space_id: str, *, scope_external_ref: str) -> None:
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                MemoryScopeRow(
                    id="scope-1",
                    space_id=space_id,
                    external_ref=scope_external_ref,
                    name=scope_external_ref,
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryThreadRow(
                    id="thread-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    external_ref="thread-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        await session.commit()


class FixedClock:
    def now(self) -> datetime:
        return NOW
