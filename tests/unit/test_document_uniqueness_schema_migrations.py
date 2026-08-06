"""Behavior checks for document uniqueness schema migrations."""

import asyncio
from pathlib import Path

from infinity_context_adapters.postgres import build_async_engine, create_schema
from sqlalchemy import inspect, text


def test_create_schema_rebuilds_sqlite_legacy_document_unique_constraint(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-unique.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_documents (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            title VARCHAR(300) NOT NULL,
                            source_type VARCHAR(80) NOT NULL,
                            source_external_id VARCHAR(240) NOT NULL,
                            content_hash VARCHAR(80) NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            CONSTRAINT uq_document_source_hash UNIQUE (
                                space_id,
                                memory_scope_id,
                                source_type,
                                source_external_id,
                                content_hash
                            )
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id, space_id, memory_scope_id, thread_id, title,
                            source_type, source_external_id, content_hash, status,
                            created_at, updated_at
                        )
                        VALUES (
                            'doc_thread_a', 'space_1', 'memory_scope_1', 'thread_a',
                            'Doc A', 'document', 'same-source', 'same-hash', 'active',
                            '2026-05-25T10:00:00+00:00', '2026-05-25T10:00:00+00:00'
                        )
                        """
                    )
                )

            await create_schema(engine)

            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id, space_id, memory_scope_id, thread_id, title,
                            source_type, source_external_id, content_hash,
                            classification, status, created_at, updated_at
                        )
                        VALUES (
                            'doc_thread_b', 'space_1', 'memory_scope_1', 'thread_b',
                            'Doc B', 'document', 'same-source', 'same-hash', 'internal',
                            'active', '2026-05-25T10:01:00+00:00',
                            '2026-05-25T10:01:00+00:00'
                        )
                        """
                    )
                )

            def inspect_documents(connection) -> dict[str, object]:
                inspector = inspect(connection)
                unique_constraints = inspector.get_unique_constraints("memory_documents")
                indexes = inspector.get_indexes("memory_documents")
                document_count = connection.execute(
                    text("SELECT COUNT(*) FROM memory_documents")
                ).scalar_one()
                return {
                    "document_count": document_count,
                    "index_names": {index["name"] for index in indexes},
                    "legacy_unique_exists": any(
                        tuple(constraint.get("column_names") or ())
                        == (
                            "space_id",
                            "memory_scope_id",
                            "source_type",
                            "source_external_id",
                            "content_hash",
                        )
                        for constraint in unique_constraints
                    ),
                }

            async with engine.connect() as connection:
                return await connection.run_sync(inspect_documents)
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert result["document_count"] == 2
    assert result["legacy_unique_exists"] is False
    assert "uq_document_content_hash_memory_scope_wide" in result["index_names"]
    assert "uq_document_content_hash_thread" in result["index_names"]


def test_document_unique_indexes_prevent_same_hash_duplicate_rows_per_scope(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, str]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'content-unique.db'}")
        try:
            await create_schema(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id,
                            space_id,
                            memory_scope_id,
                            thread_id,
                            title,
                            source_type,
                            source_external_id,
                            content_hash,
                            classification,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'doc_a',
                            'space_1',
                            'memory_scope_1',
                            'thread_a',
                            'Doc A',
                            'document',
                            'source-a',
                            'same-hash',
                            'internal',
                            'active',
                            '2026-05-25T10:00:00+00:00',
                            '2026-05-25T10:00:00+00:00'
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id,
                            space_id,
                            memory_scope_id,
                            thread_id,
                            title,
                            source_type,
                            source_external_id,
                            content_hash,
                            classification,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'doc_b',
                            'space_1',
                            'memory_scope_1',
                            'thread_b',
                            'Doc B',
                            'document',
                            'source-b',
                            'same-hash',
                            'internal',
                            'active',
                            '2026-05-25T10:01:00+00:00',
                            '2026-05-25T10:01:00+00:00'
                        )
                        """
                    )
                )
            async with engine.begin() as connection:
                try:
                    await connection.execute(
                        text(
                            """
                            INSERT INTO memory_documents (
                                id,
                                space_id,
                                memory_scope_id,
                                thread_id,
                                title,
                                source_type,
                                source_external_id,
                                content_hash,
                                classification,
                                status,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                'doc_duplicate_thread_a',
                                'space_1',
                                'memory_scope_1',
                                'thread_a',
                                'Doc duplicate',
                                'document',
                                'different-source',
                                'same-hash',
                                'internal',
                                'active',
                                '2026-05-25T10:02:00+00:00',
                                '2026-05-25T10:02:00+00:00'
                            )
                            """
                        )
                    )
                except Exception as exc:
                    return {"error_type": exc.__class__.__name__}
        finally:
            await engine.dispose()
        return {"error_type": ""}

    result = asyncio.run(run())

    assert result["error_type"] == "IntegrityError"


def test_document_unique_indexes_allow_reimport_after_deleted_tombstone(
    tmp_path: Path,
) -> None:
    async def run() -> int:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deleted-reimport.db'}")
        try:
            await create_schema(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id,
                            space_id,
                            memory_scope_id,
                            thread_id,
                            title,
                            source_type,
                            source_external_id,
                            content_hash,
                            classification,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'doc_deleted',
                            'space_1',
                            'memory_scope_1',
                            'thread_a',
                            'Deleted doc',
                            'document',
                            'source-old',
                            'same-hash',
                            'internal',
                            'deleted',
                            '2026-05-25T10:00:00+00:00',
                            '2026-05-25T10:00:00+00:00'
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_documents (
                            id,
                            space_id,
                            memory_scope_id,
                            thread_id,
                            title,
                            source_type,
                            source_external_id,
                            content_hash,
                            classification,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'doc_reimported',
                            'space_1',
                            'memory_scope_1',
                            'thread_a',
                            'Reimported doc',
                            'document',
                            'source-new',
                            'same-hash',
                            'internal',
                            'active',
                            '2026-05-25T10:01:00+00:00',
                            '2026-05-25T10:01:00+00:00'
                        )
                        """
                    )
                )
                count = await connection.execute(text("SELECT COUNT(*) FROM memory_documents"))
                return int(count.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == 2
