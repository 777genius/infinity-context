import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import infinity_context_server.benchmark_unsealed_recovery_inventory as recovery_inventory
import pytest
from infinity_context_adapters.postgres.models import (
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySourceRefRow,
)
from infinity_context_core.application.normalize import normalize_text, scoped_source_hash
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_server.benchmark_unsealed_inventory_validation import (
    require_chunk_source_hashes,
    require_managed_inventory_links,
)
from infinity_context_server.benchmark_unsealed_outbox_validation import (
    MAX_RECOVERY_OBSOLETE_UPSERT_JOBS,
)
from infinity_context_server.benchmark_unsealed_recovery_inventory import (
    MAX_RECOVERY_ROWS_PER_KIND,
    _fact_source_refs,
    _projection_scopes,
    _require_caps,
    _require_counts_and_tombstones,
    _require_exact_delete_jobs,
    _rows,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def _ref(source_id: str = "fact-source") -> SimpleNamespace:
    return SimpleNamespace(
        fact_id="db-fact",
        fact_version=1,
        source_type="memory_comparison_benchmark",
        source_id=source_id,
        chunk_id=None,
        char_start=None,
        char_end=None,
        quote_preview="fact text",
        page_number=None,
        time_start_ms=None,
        time_end_ms=None,
        bbox_json=None,
    )


def _fact_inventory() -> tuple[dict[str, object], tuple[object, ...]]:
    descriptor = managed_benchmark_fact_source_ref_descriptor(
        source_type="memory_comparison_benchmark",
        source_id="fact-source",
        quote_preview="fact text",
    )
    source_sha = managed_benchmark_text_sha256("fact-source")
    content_sha = managed_benchmark_text_sha256("fact text")
    operation = managed_benchmark_infinity_operation_sha256(
        managed_benchmark_fact_operation_material(
            source_external_id_sha256=source_sha,
            content_sha256=content_sha,
            kind="note",
            classification="internal",
            source_refs=(descriptor,),
        )
    )
    corpus = {
        "memory_scope_external_ref_sha256": managed_benchmark_text_sha256("corpus"),
        "thread_external_ref_sha256": managed_benchmark_text_sha256("thread-ref"),
        "infinity_lane": "fact",
        "ordered_infinity_source_external_id_sha256": [source_sha],
        "ordered_infinity_content_sha256": [content_sha],
        "ordered_infinity_operation_sha256": [operation],
        "expected_fact_count": 1,
        "expected_document_count": 0,
        "expected_chunk_count": 0,
    }
    plan = {
        "corpora": [corpus],
        "cardinality": {
            "expected_fact_count": 1,
            "expected_document_count": 0,
            "expected_chunk_count": 0,
        },
    }
    scope = SimpleNamespace(id="db-scope", external_ref="corpus")
    thread = SimpleNamespace(id="db-thread", memory_scope_id="db-scope", external_ref="thread-ref")
    fact = SimpleNamespace(
        id="db-fact",
        version=1,
        memory_scope_id="db-scope",
        thread_id="db-thread",
        text="fact text",
        kind="note",
        classification="internal",
    )
    return plan, (scope, thread, fact, _ref())


def test_inventory_authorizes_actual_db_ids_through_exact_fact_operation() -> None:
    plan, (scope, thread, fact, ref) = _fact_inventory()
    require_managed_inventory_links(
        plan,
        scopes=(scope,),
        threads=(thread,),
        episodes=(),
        documents=(),
        chunks=(),
        facts=(fact,),
        fact_source_refs=(ref,),
    )
    projected = _projection_scopes((scope,), (thread,), (), (fact,))
    assert projected[0].memory_scope_id == "db-scope"
    assert projected[0].thread_id == "db-thread"
    assert projected[0].fact_ids == ("db-fact",)


@pytest.mark.parametrize("corruption", ["scope", "thread", "source", "content"])
def test_inventory_rejects_foreign_fact_authority(corruption: str) -> None:
    plan, rows = _fact_inventory()
    scope, thread, fact, ref = rows
    if corruption == "scope":
        scope.external_ref = "foreign"
    elif corruption == "thread":
        thread.external_ref = "foreign"
    elif corruption == "source":
        ref.source_id = "foreign"
    else:
        fact.text = "foreign"
    with pytest.raises(MemoryConflictError, match="differs from cleanup plan"):
        require_managed_inventory_links(
            plan,
            scopes=(scope,),
            threads=(thread,),
            episodes=(),
            documents=(),
            chunks=(),
            facts=(fact,),
            fact_source_refs=(ref,),
        )


def test_inventory_binds_document_fragments_and_exact_chunk_total() -> None:
    fragment = managed_benchmark_document_fragment_descriptor(
        sequence=0,
        char_start=0,
        char_end=9,
        kind="document_section",
        text="document ",
        node_kind="section_chunk",
        heading=None,
        ordinal_in_heading=None,
    )
    second_fragment = managed_benchmark_document_fragment_descriptor(
        sequence=1,
        char_start=9,
        char_end=13,
        kind="document_section",
        text="text",
        node_kind="section_chunk",
        heading=None,
        ordinal_in_heading=None,
    )
    source_refs = [{"source_type": "benchmark", "source_id": "source-ref"}]
    source_sha = managed_benchmark_text_sha256("document-source")
    content_sha = "c" * 64
    operation = managed_benchmark_infinity_operation_sha256(
        managed_benchmark_document_operation_material(
            source_external_id_sha256=source_sha,
            content_sha256=content_sha,
            title_sha256=managed_benchmark_text_sha256("Document"),
            source_type="benchmark_conversation_pair",
            classification="internal",
            source_refs=source_refs,
            fragments=(fragment, second_fragment),
        )
    )
    plan = {
        "corpora": [
            {
                "memory_scope_external_ref_sha256": managed_benchmark_text_sha256("corpus"),
                "thread_external_ref_sha256": managed_benchmark_text_sha256("thread-ref"),
                "infinity_lane": "document",
                "ordered_infinity_source_external_id_sha256": [source_sha],
                "ordered_infinity_content_sha256": [content_sha],
                "ordered_infinity_operation_sha256": [operation],
                "expected_fact_count": 0,
                "expected_document_count": 1,
                "expected_chunk_count": 2,
            }
        ],
        "cardinality": {
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": 2,
        },
    }
    scope = SimpleNamespace(id="scope", external_ref="corpus")
    thread = SimpleNamespace(id="thread", memory_scope_id="scope", external_ref="thread-ref")
    document = SimpleNamespace(
        id="document",
        memory_scope_id="scope",
        thread_id="thread",
        source_external_id="document-source",
        content_hash=content_sha,
        title="Document",
        source_type="benchmark_conversation_pair",
        classification="internal",
    )
    chunk = SimpleNamespace(
        id="chunk",
        document_id="document",
        episode_id=None,
        memory_scope_id="scope",
        thread_id="thread",
        source_external_id="document-source",
        source_type="benchmark_conversation_pair",
        sequence=0,
        char_start=0,
        char_end=9,
        kind="document_section",
        text="document ",
        metadata_json={"node_kind": "section_chunk", "source_refs": source_refs},
    )
    second_chunk = SimpleNamespace(
        id="chunk-2",
        document_id="document",
        episode_id=None,
        memory_scope_id="scope",
        thread_id="thread",
        source_external_id="document-source",
        source_type="benchmark_conversation_pair",
        sequence=1,
        char_start=9,
        char_end=13,
        kind="document_section",
        text="text",
        metadata_json={"node_kind": "section_chunk"},
    )
    require_managed_inventory_links(
        plan,
        scopes=(scope,),
        threads=(thread,),
        episodes=(),
        documents=(document,),
        chunks=(chunk, second_chunk),
        facts=(),
        fact_source_refs=(),
    )
    second_chunk.metadata_json["source_refs"] = [{"foreign": True}]
    with pytest.raises(MemoryConflictError, match="fragment source references"):
        require_managed_inventory_links(
            plan,
            scopes=(scope,),
            threads=(thread,),
            episodes=(),
            documents=(document,),
            chunks=(chunk, second_chunk),
            facts=(),
            fact_source_refs=(),
        )


def test_inventory_caps_fail_closed_before_provider_access() -> None:
    rows = tuple(SimpleNamespace() for _ in range(MAX_RECOVERY_ROWS_PER_KIND + 1))
    with pytest.raises(MemoryConflictError, match="per-kind cap"):
        _require_caps({"chunks": rows})


def test_inventory_exact_expansion_boundary_fits_loader_caps() -> None:
    rows = tuple(SimpleNamespace() for _ in range(MAX_RECOVERY_ROWS_PER_KIND))
    _require_caps({"memory_scopes": rows, "threads": rows, "documents": rows, "chunks": rows})


def test_canonical_inventory_query_materializes_only_cap_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as connection:
            await connection.run_sync(MemoryScopeRow.__table__.create)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        async with AsyncSession(engine) as session:
            session.add_all(
                MemoryScopeRow(
                    id=f"scope-{index}",
                    space_id="space",
                    external_ref=f"external-{index}",
                    name=f"Scope {index}",
                    status="deleted",
                    created_at=now,
                    updated_at=now,
                )
                for index in range(4)
            )
            await session.commit()
            monkeypatch.setattr(recovery_inventory, "MAX_RECOVERY_ROWS_PER_KIND", 2)
            rows = await _rows(session, MemoryScopeRow, "space")
            assert len(rows) == 3
            with pytest.raises(MemoryConflictError, match="per-kind cap"):
                _require_caps({"memory_scopes": rows})
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("obsolete", [True, -1, MAX_RECOVERY_OBSOLETE_UPSERT_JOBS + 1])
def test_inventory_obsolete_upsert_count_is_exact_bounded_int(obsolete: object) -> None:
    with pytest.raises(MemoryConflictError, match="obsolete upsert count"):
        _require_counts_and_tombstones(
            {"documents": ()},
            SimpleNamespace(documents=0, obsolete_upsert_jobs=obsolete),
        )
    _require_counts_and_tombstones(
        {"documents": ()},
        SimpleNamespace(documents=0, obsolete_upsert_jobs=2),
    )


def test_inventory_recomputes_document_chunk_source_hash() -> None:
    row = SimpleNamespace(
        id="db-chunk",
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        episode_id=None,
        document_id="document",
        source_external_id="source",
        sequence=0,
        text=" Source TEXT ",
        source_hash=scoped_source_hash(
            "space", "scope", "document", 0, normalize_text(" Source TEXT ")
        ),
    )
    require_chunk_source_hashes((row,))
    row.source_hash = "0" * 64
    with pytest.raises(MemoryConflictError, match="source hash differs"):
        require_chunk_source_hashes((row,))


def test_inventory_rejects_any_managed_episode_lane() -> None:
    plan, (scope, thread, fact, ref) = _fact_inventory()
    with pytest.raises(MemoryConflictError, match="episode lane"):
        require_managed_inventory_links(
            plan,
            scopes=(scope,),
            threads=(thread,),
            episodes=(SimpleNamespace(id="episode"),),
            documents=(),
            chunks=(),
            facts=(fact,),
            fact_source_refs=(ref,),
        )


def test_delete_job_discovery_ignores_many_unrelated_but_rejects_related_extra() -> None:
    async def run(*, related_extra: bool) -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as connection:
            await connection.run_sync(MemoryOutboxRow.__table__.create)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [
            MemoryOutboxRow(
                event_type="vector.delete_chunks",
                aggregate_type="benchmark_run",
                aggregate_id=f"foreign-{index}",
                payload_json={"space_id": f"foreign-space-{index}"},
                status="done",
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
            for index in range(250)
        ]
        if related_extra:
            rows.append(
                MemoryOutboxRow(
                    event_type="vector.delete_chunks",
                    aggregate_type="benchmark_run",
                    aggregate_id="r" * 64,
                    payload_json={"space_id": "benchmark-space"},
                    status="done",
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        async with AsyncSession(engine) as session:
            session.add_all(rows)
            await session.commit()
            record = SimpleNamespace(
                run_id_sha256="r" * 64,
                space_id="benchmark-space",
                cleanup_receipt=SimpleNamespace(
                    vector_delete_outbox_ids=(),
                    graph_delete_outbox_ids=(),
                    cognee_delete_outbox_ids=(),
                    counts=SimpleNamespace(
                        vector_delete_jobs=0,
                        graph_delete_jobs=0,
                        cognee_delete_jobs=0,
                    ),
                ),
            )
            if related_extra:
                with pytest.raises(MemoryConflictError, match="unregistered delete jobs"):
                    await _require_exact_delete_jobs(
                        session,
                        record=record,
                        chunks=(),
                        facts=(),
                        documents=(),
                    )
            else:
                assert (
                    await _require_exact_delete_jobs(
                        session,
                        record=record,
                        chunks=(),
                        facts=(),
                        documents=(),
                    )
                    == ()
                )
        await engine.dispose()

    asyncio.run(run(related_extra=False))
    asyncio.run(run(related_extra=True))


def test_fact_source_ref_query_is_exact_and_bounded_to_current_versions() -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as connection:
            await connection.run_sync(MemorySourceRefRow.__table__.create)
        unrelated = [
            MemorySourceRefRow(
                fact_id=f"foreign-{index}",
                fact_version=1,
                source_type="benchmark",
                source_id=f"foreign-source-{index}",
            )
            for index in range(250)
        ]
        current = MemorySourceRefRow(
            fact_id="db-fact",
            fact_version=2,
            source_type="benchmark",
            source_id="current-source",
        )
        async with AsyncSession(engine) as session:
            session.add_all([*unrelated, current])
            await session.commit()
            facts = (SimpleNamespace(id="db-fact", version=2),)
            rows = await _fact_source_refs(session, facts, expected_count=1)
            assert tuple(row.source_id for row in rows) == ("current-source",)
            session.add(
                MemorySourceRefRow(
                    fact_id="db-fact",
                    fact_version=2,
                    source_type="benchmark",
                    source_id="unexpected-source",
                )
            )
            await session.commit()
            with pytest.raises(MemoryConflictError, match="source reference count"):
                await _fact_source_refs(session, facts, expected_count=1)
        await engine.dispose()

    asyncio.run(run())
