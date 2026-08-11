"""PostgreSQL access-path proof for canonical keyword retrieval."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import create_schema
from infinity_context_adapters.postgres.canonical_keyword_trigram import (
    CANONICAL_KEYWORD_TRIGRAM_INDEX,
    CANONICAL_KEYWORD_TRIGRAM_STATEMENTS,
    ensure_canonical_keyword_trigram_access_path,
)
from infinity_context_adapters.postgres.canonical_retrieval_batching import (
    _keyword_batch_statement,
    _keyword_fragments,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.repositories import (
    PostgresChunkRepository,
    _keyword_search_statement,
)
from infinity_context_adapters.postgres.repository_helpers import _terms
from infinity_context_core.ports.repositories import ChunkKeywordSearch
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.e2e.postgres_test_database import PostgresTestDatabase

_MIGRATIONS = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)
MIGRATION = _MIGRATIONS / "0022_canonical_keyword_trigram.sql"
_LOGGER = logging.getLogger(__name__)


def test_migration_and_runtime_installer_share_the_partial_trigram_contract() -> None:
    migration = _normalize_sql(MIGRATION.read_text(encoding="utf-8"))
    connection = _RecordingConnection("postgresql")

    ensure_canonical_keyword_trigram_access_path(connection)

    assert tuple(connection.statements) == CANONICAL_KEYWORD_TRIGRAM_STATEMENTS
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    assert f"CREATE INDEX IF NOT EXISTS {CANONICAL_KEYWORD_TRIGRAM_INDEX}" in migration
    assert "normalized_text gin_trgm_ops" in migration
    assert "status = 'active' AND classification <> 'restricted'" in migration


def test_runtime_installer_keeps_sqlite_extension_free() -> None:
    connection = _RecordingConnection("sqlite")

    ensure_canonical_keyword_trigram_access_path(connection)

    assert connection.statements == []


def test_real_postgres_plan_and_scalar_batch_semantics_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_real_postgres_access_path(database_url))


class _RecordingConnection:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.statements: list[str] = []

    def execute(self, statement) -> None:
        self.statements.append(str(statement))


async def _assert_real_postgres_access_path(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="canonical_keyword_trgm",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    await database.recreate()
    engine = create_async_engine(database.app_url)
    try:
        await _install_versioned_schema_through(database, "0016_")
        now = datetime(2026, 1, 1, tzinfo=UTC)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            semantic_rows = _semantic_rows(now)
            session.add_all(_document_rows(semantic_rows, now))
            session.add(_filler_document(now))
            await session.flush()
            session.add_all(semantic_rows)
            await session.flush()
            await session.execute(
                text(
                    """
                    INSERT INTO memory_chunks (
                        id, space_id, memory_scope_id, thread_id, document_id, episode_id,
                        source_type, source_external_id, source_hash, kind, text,
                        normalized_text, status, sequence, char_start, char_end,
                        token_estimate, classification, created_at, updated_at, metadata_json
                    )
                    SELECT
                        'filler-' || value, 'space-a', 'scope-a', NULL,
                        'filler-document', NULL,
                        'manual', 'filler-source-' || value, 'filler-hash-' || value,
                        'document_section', 'ordinary filler row ' || value,
                        'ordinary filler row ' || value, 'active', value, 0, 20, 4,
                        'internal', :created_at, :created_at, CAST('{}' AS JSONB)
                        FROM generate_series(1, 60000) AS value
                    """
                ),
                {"created_at": now},
            )
            await session.commit()
        await create_schema(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            corpus_size = int(
                (await session.execute(text("SELECT count(*) FROM memory_chunks"))).scalar_one()
            )
            assert corpus_size >= 50_000

            repository = PostgresChunkRepository(session)
            request = ChunkKeywordSearch(
                "space-a",
                ("scope-a",),
                "thread-a",
                "reminder",
                10,
            )
            scalar = await repository.keyword_search(
                space_id=request.space_id,
                memory_scope_ids=request.memory_scope_ids,
                thread_id=request.thread_id,
                query=request.query,
                limit=request.limit,
            )
            batched = (await repository.keyword_search_many((request,)))[0]

            assert batched == scalar
            assert [str(item.id) for item in scalar] == ["safe-global", "safe-thread"]
            assert [item.source_type for item in scalar] == ["manual", "episode"]
            assert [item.source_external_id for item in scalar] == [
                "turn-global",
                "turn-thread-a",
            ]
            assert [item.metadata["source_identity"] for item in scalar] == [
                "turn-global",
                "turn-thread-a",
            ]

            index_definition = (
                await session.execute(
                    text(
                        """
                        SELECT indexdef
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND indexname = :index_name
                        """
                    ),
                    {"index_name": CANONICAL_KEYWORD_TRIGRAM_INDEX},
                )
            ).scalar_one()
            assert "USING gin (normalized_text gin_trgm_ops)" in index_definition
            scalar_statement, scalar_terms = _keyword_search_statement(
                space_id=request.space_id,
                memory_scope_ids=request.memory_scope_ids,
                thread_id=request.thread_id,
                query=request.query,
                limit=request.limit,
            )
            batch_requests = (
                request,
                ChunkKeywordSearch(
                    request.space_id,
                    request.memory_scope_ids,
                    request.thread_id,
                    request.query,
                    request.limit,
                ),
            )
            batch_fragments = tuple(
                fragment
                for request_index, batch_request in enumerate(batch_requests)
                for fragment in _keyword_fragments(
                    request_index,
                    batch_request,
                    _terms(batch_request.query),
                )
            )
            batch_statement = _keyword_batch_statement(batch_fragments, batch_requests)
            scalar_sql = _literal_postgres_sql(scalar_statement)
            batch_sql = _literal_postgres_sql(batch_statement)
            assert len(scalar_terms[0].variants) > 1
            for compiled_sql in (scalar_sql, batch_sql):
                assert "memory_chunks.space_id = 'space-a'" in compiled_sql
                assert "memory_chunks.memory_scope_id IN ('scope-a')" in compiled_sql
                assert "memory_chunks.thread_id = 'thread-a'" in compiled_sql
                assert "memory_chunks.thread_id IS NULL" in compiled_sql
                assert "memory_chunks.status = 'active'" in compiled_sql
                assert "memory_chunks.classification != 'restricted'" in compiled_sql
            assert "CASE WHEN" in scalar_sql
            assert "ORDER BY" in scalar_sql
            assert "LIMIT" in scalar_sql
            assert " ESCAPE E'\\\\'" in scalar_sql
            assert scalar_sql.count("normalized_text LIKE") > 2
            assert "UNION ALL" in batch_sql
            assert "CASE WHEN" in batch_sql
            assert "canonical_keyword_candidates" in batch_sql
            assert " ESCAPE E'\\\\'" in batch_sql
            assert batch_sql.count("normalized_text LIKE") > 4

            await session.execute(text(f"DROP INDEX {CANONICAL_KEYWORD_TRIGRAM_INDEX}"))
            await session.execute(text("ANALYZE memory_chunks"))
            before_scalar = await _explain_analyze(session, scalar_sql)
            before_batch = await _explain_analyze(session, batch_sql)
            assert CANONICAL_KEYWORD_TRIGRAM_INDEX not in _plan_index_names(before_scalar)
            assert CANONICAL_KEYWORD_TRIGRAM_INDEX not in _plan_index_names(before_batch)

            await session.execute(text(CANONICAL_KEYWORD_TRIGRAM_STATEMENTS[1]))
            await session.execute(text("ANALYZE memory_chunks"))
            after_scalar = await _explain_analyze(session, scalar_sql)
            after_batch = await _explain_analyze(session, batch_sql)
            assert CANONICAL_KEYWORD_TRIGRAM_INDEX in _plan_index_names(after_scalar)
            assert CANONICAL_KEYWORD_TRIGRAM_INDEX in _plan_index_names(after_batch)
            assert "Bitmap Index Scan" in _plan_node_types(after_scalar)
            assert "Bitmap Index Scan" in _plan_node_types(after_batch)
            _LOGGER.info(
                "canonical keyword plan evidence: %s",
                {
                    "corpus_size": corpus_size,
                    "scalar_before": _plan_summary(before_scalar),
                    "scalar_after": _plan_summary(after_scalar),
                    "batch_before": _plan_summary(before_batch),
                    "batch_after": _plan_summary(after_batch),
                },
            )
    finally:
        await engine.dispose()
        await database.drop()


async def _install_versioned_schema_through(
    database: PostgresTestDatabase,
    migration_prefix: str,
) -> None:
    paths = tuple(
        path for path in sorted(_MIGRATIONS.glob("*.sql")) if path.name[:5] <= migration_prefix
    )
    connection = await database.connect()
    try:
        for path in paths:
            await connection.execute(path.read_text(encoding="utf-8"))
        await connection.execute(
            """
            CREATE TABLE infinity_context_schema_migrations (
                migration_id VARCHAR(160) PRIMARY KEY,
                checksum VARCHAR(64) NOT NULL,
                execution_kind VARCHAR(32) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_infinity_context_schema_migration_kind
                    CHECK (execution_kind IN ('applied', 'legacy_baseline'))
            )
            """
        )
        await connection.executemany(
            """
            INSERT INTO infinity_context_schema_migrations (
                migration_id, checksum, execution_kind
            ) VALUES ($1, $2, 'applied')
            """,
            [(path.stem, sha256(path.read_bytes()).hexdigest()) for path in paths],
        )
    finally:
        await connection.close()


def _semantic_rows(now: datetime) -> list[MemoryChunkRow]:
    values = (
        ("safe-global", "scope-a", None, "active", "internal", 0, "manual", "turn-global"),
        (
            "safe-thread",
            "scope-a",
            "thread-a",
            "active",
            "internal",
            1,
            "episode",
            "turn-thread-a",
        ),
        ("wrong-thread", "scope-a", "thread-b", "active", "internal", 0, "manual", "turn-b"),
        ("wrong-scope", "scope-b", None, "active", "internal", 0, "manual", "turn-scope-b"),
        ("restricted", "scope-a", None, "active", "restricted", 0, "manual", "turn-private"),
        ("deleted", "scope-a", None, "deleted", "internal", 0, "manual", "turn-deleted"),
    )
    return [
        MemoryChunkRow(
            id=item_id,
            space_id="space-a",
            memory_scope_id=scope_id,
            thread_id=thread_id,
            document_id=f"document-{item_id}",
            episode_id=None,
            source_type=source_type,
            source_external_id=source_external_id,
            source_hash=f"hash-{item_id}",
            kind="document_section",
            text="canonical reminder evidence",
            normalized_text="canonical reminder evidence",
            status=status,
            sequence=sequence,
            char_start=0,
            char_end=25,
            token_estimate=4,
            classification=classification,
            created_at=now + timedelta(seconds=sequence),
            updated_at=now + timedelta(seconds=sequence),
            metadata_json={"source_identity": source_external_id},
        )
        for (
            item_id,
            scope_id,
            thread_id,
            status,
            classification,
            sequence,
            source_type,
            source_external_id,
        ) in values
    ]


def _document_rows(
    chunks: list[MemoryChunkRow],
    now: datetime,
) -> list[MemoryDocumentRow]:
    return [
        MemoryDocumentRow(
            id=str(chunk.document_id),
            space_id=chunk.space_id,
            memory_scope_id=chunk.memory_scope_id,
            thread_id=chunk.thread_id,
            title=f"Document for {chunk.id}",
            source_type=chunk.source_type,
            source_external_id=chunk.source_external_id,
            content_hash=f"document-hash-{chunk.id}",
            classification=chunk.classification,
            status="active",
            created_at=now,
            updated_at=now,
        )
        for chunk in chunks
    ]


def _filler_document(now: datetime) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="filler-document",
        space_id="space-a",
        memory_scope_id="scope-a",
        thread_id=None,
        title="Filler corpus",
        source_type="manual",
        source_external_id="filler-source",
        content_hash="filler-document-hash",
        classification="internal",
        status="active",
        created_at=now,
        updated_at=now,
    )


def _normalize_sql(value: str) -> str:
    return " ".join(value.replace(";", "").split())


def _literal_postgres_sql(statement) -> str:
    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    # The PostgreSQL compiler emits a DBAPI-escaped regular string here. EXPLAIN executes the
    # compiled text directly, so render the same one-character escape as an explicit E-string.
    return compiled.replace(" ESCAPE '\\\\'", " ESCAPE E'\\\\'")


async def _explain_analyze(session: AsyncSession, sql: str):
    return (
        await session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))
    ).scalar_one()


def _plan_index_names(plan) -> set[str]:
    return {str(node["Index Name"]) for node in _plan_nodes(plan) if "Index Name" in node}


def _plan_node_types(plan) -> set[str]:
    return {str(node["Node Type"]) for node in _plan_nodes(plan) if "Node Type" in node}


def _plan_summary(plan) -> dict[str, object]:
    root = plan[0]["Plan"]
    return {
        "actual_total_ms": root.get("Actual Total Time"),
        "total_cost": root.get("Total Cost"),
        "indexes": sorted(_plan_index_names(plan)),
        "nodes": sorted(_plan_node_types(plan)),
    }


def _plan_nodes(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _plan_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _plan_nodes(nested)
