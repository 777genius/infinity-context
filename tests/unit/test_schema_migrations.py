import asyncio
from pathlib import Path

from memo_stack_adapters.postgres import build_async_engine, create_schema
from sqlalchemy import inspect, text


def test_create_schema_adds_classification_to_existing_memory_tables(tmp_path: Path) -> None:
    async def run() -> dict[str, dict[str, object]]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-schema.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_service_tokens (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80),
                            description VARCHAR(240) NOT NULL,
                            token_hash VARCHAR(80) UNIQUE NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            revoked_at DATETIME
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_facts (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            profile_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            kind VARCHAR(80) NOT NULL,
                            text TEXT NOT NULL,
                            status VARCHAR(40) NOT NULL,
                            confidence VARCHAR(40) NOT NULL,
                            trust_level VARCHAR(40) NOT NULL,
                            version INTEGER NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_documents (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            profile_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            title VARCHAR(300) NOT NULL,
                            source_type VARCHAR(80) NOT NULL,
                            source_external_id VARCHAR(240) NOT NULL,
                            content_hash VARCHAR(80) NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_chunks (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            profile_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            document_id VARCHAR(80),
                            episode_id VARCHAR(80),
                            source_type VARCHAR(80) NOT NULL,
                            source_external_id VARCHAR(240) NOT NULL,
                            source_hash VARCHAR(80) NOT NULL,
                            kind VARCHAR(80) NOT NULL,
                            text TEXT NOT NULL,
                            normalized_text TEXT NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            sequence INTEGER NOT NULL,
                            char_start INTEGER NOT NULL,
                            char_end INTEGER NOT NULL,
                            token_estimate INTEGER NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            metadata_json JSON NOT NULL
                        )
                        """
                    )
                )

            await create_schema(engine)

            def get_additive_columns(connection) -> dict[str, dict[str, object]]:
                inspector = inspect(connection)
                classification_columns = {
                    table_name: {
                        column["name"]: column
                        for column in inspector.get_columns(table_name)
                        if column["name"] == "classification"
                    }
                    for table_name in ("memory_facts", "memory_documents", "memory_chunks")
                }
                token_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_service_tokens")
                    if column["name"]
                    in {"profile_ids_json", "permissions_json", "last_used_at", "expires_at"}
                }
                document_indexes = {
                    index["name"]: index for index in inspector.get_indexes("memory_documents")
                }
                return {
                    **classification_columns,
                    "memory_service_tokens": token_columns,
                    "memory_document_indexes": document_indexes,
                }

            async with engine.connect() as connection:
                return await connection.run_sync(get_additive_columns)
        finally:
            await engine.dispose()

    columns = asyncio.run(run())

    assert columns["memory_facts"]["classification"]["nullable"] is False
    assert columns["memory_documents"]["classification"]["nullable"] is False
    assert columns["memory_chunks"]["classification"]["nullable"] is False
    assert set(columns["memory_service_tokens"]) == {
        "profile_ids_json",
        "permissions_json",
        "last_used_at",
        "expires_at",
    }
    assert "uq_document_content_hash_profile_wide" in columns["memory_document_indexes"]
    assert "uq_document_content_hash_thread" in columns["memory_document_indexes"]


def test_create_schema_adds_capture_tables_and_suggestion_metadata(tmp_path: Path) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'captures-schema.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_suggestions (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            profile_id VARCHAR(80) NOT NULL,
                            candidate_text TEXT NOT NULL,
                            kind VARCHAR(80) NOT NULL,
                            status VARCHAR(40) NOT NULL,
                            source_refs_json JSON NOT NULL,
                            confidence VARCHAR(40) NOT NULL,
                            trust_level VARCHAR(40) NOT NULL,
                            safe_reason VARCHAR(320) NOT NULL,
                            target_fact_id VARCHAR(80),
                            target_fact_version INTEGER,
                            review_reason VARCHAR(320),
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            reviewed_at DATETIME
                        )
                        """
                    )
                )

            await create_schema(engine)

            def inspect_schema(connection) -> dict[str, object]:
                inspector = inspect(connection)
                return {
                    "tables": set(inspector.get_table_names()),
                    "suggestion_columns": {
                        column["name"] for column in inspector.get_columns("memory_suggestions")
                    },
                    "capture_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_captures")
                    },
                    "suggestion_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_suggestions")
                    },
                }

            async with engine.connect() as connection:
                return await connection.run_sync(inspect_schema)
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert "memory_captures" in result["tables"]
    assert {
        "operation",
        "category",
        "tags_json",
        "ttl_policy",
        "expires_at",
        "created_from_capture_id",
        "candidate_fingerprint",
        "review_payload_json",
    } <= result["suggestion_columns"]
    assert "ix_memory_captures_consolidation" in result["capture_indexes"]
    assert "ix_memory_suggestions_expiry" in result["suggestion_indexes"]


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
                            profile_id VARCHAR(80) NOT NULL,
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
                                profile_id,
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
                            id,
                            space_id,
                            profile_id,
                            thread_id,
                            title,
                            source_type,
                            source_external_id,
                            content_hash,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'doc_thread_a',
                            'space_1',
                            'profile_1',
                            'thread_a',
                            'Doc A',
                            'document',
                            'same-source',
                            'same-hash',
                            'active',
                            '2026-05-25T10:00:00+00:00',
                            '2026-05-25T10:00:00+00:00'
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
                            id,
                            space_id,
                            profile_id,
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
                            'doc_thread_b',
                            'space_1',
                            'profile_1',
                            'thread_b',
                            'Doc B',
                            'document',
                            'same-source',
                            'same-hash',
                            'internal',
                            'active',
                            '2026-05-25T10:01:00+00:00',
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
                            "profile_id",
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
    assert "uq_document_content_hash_profile_wide" in result["index_names"]
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
                            profile_id,
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
                            'profile_1',
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
                            profile_id,
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
                            'profile_1',
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
                                profile_id,
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
                                'profile_1',
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
                            profile_id,
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
                            'profile_1',
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
                            profile_id,
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
                            'profile_1',
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
