"""Postgres unit of work and engine helpers."""

from __future__ import annotations

from types import TracebackType

from memo_stack_core.domain.errors import MemoryConflictError
from memo_stack_core.ports.clock import ClockPort
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from memo_stack_adapters.postgres.models import Base
from memo_stack_adapters.postgres.repositories import (
    PostgresCaptureRepository,
    PostgresChunkRepository,
    PostgresDocumentRepository,
    PostgresEpisodeRepository,
    PostgresFactRepository,
    PostgresIdempotencyRepository,
    PostgresOutbox,
    PostgresScopeRepository,
    PostgresSuggestionRepository,
)


def build_async_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_ADDITIVE_SCHEMA_COLUMNS = {
    "memory_service_tokens": (
        ("profile_ids_json", "JSON"),
        ("permissions_json", "JSON"),
        ("last_used_at", "TIMESTAMPTZ"),
        ("expires_at", "TIMESTAMPTZ"),
    ),
    "memory_facts": (("classification", "VARCHAR(40) NOT NULL DEFAULT 'internal'"),),
    "memory_documents": (("classification", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),),
    "memory_chunks": (("classification", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),),
    "memory_outbox": (
        ("workload_class", "VARCHAR(80) NOT NULL DEFAULT 'projection'"),
        ("fairness_key", "VARCHAR(160)"),
        ("last_safe_diagnostic_code", "VARCHAR(120)"),
    ),
    "memory_suggestions": (
        ("operation", "VARCHAR(40) NOT NULL DEFAULT 'add'"),
        ("category", "VARCHAR(80)"),
        ("tags_json", "JSON NOT NULL DEFAULT '[]'"),
        ("ttl_policy", "VARCHAR(80)"),
        ("expires_at", "TIMESTAMPTZ"),
        ("expiry_reason", "VARCHAR(160)"),
        ("created_from_capture_id", "VARCHAR(80)"),
        ("candidate_fingerprint", "VARCHAR(80)"),
        ("review_payload_json", "JSON NOT NULL DEFAULT '{}'"),
    ),
}


def _ensure_additive_schema_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    for table_name, columns in _ADDITIVE_SCHEMA_COLUMNS.items():
        if table_name not in table_names:
            continue
        existing_column_names = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns:
            if column_name not in existing_column_names:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


def _ensure_document_thread_unique_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_documents" not in set(inspector.get_table_names()):
        return
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("ALTER TABLE memory_documents DROP CONSTRAINT IF EXISTS uq_document_source_hash")
        )
    elif connection.dialect.name == "sqlite":
        _rebuild_sqlite_memory_documents_without_legacy_unique(connection, inspector)
    connection.execute(text("DROP INDEX IF EXISTS uq_document_source_hash_profile_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_source_hash_thread"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_content_hash_profile_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_content_hash_thread"))
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_profile_wide
            ON memory_documents (
                space_id,
                profile_id,
                content_hash
            )
            WHERE thread_id IS NULL AND status != 'deleted'
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_thread
            ON memory_documents (
                space_id,
                profile_id,
                thread_id,
                content_hash
            )
            WHERE thread_id IS NOT NULL AND status != 'deleted'
            """
        )
    )


def _rebuild_sqlite_memory_documents_without_legacy_unique(
    connection: Connection,
    inspector,
) -> None:
    legacy_columns = (
        "space_id",
        "profile_id",
        "source_type",
        "source_external_id",
        "content_hash",
    )
    has_legacy_constraint = any(
        tuple(constraint.get("column_names") or ()) == legacy_columns
        for constraint in inspector.get_unique_constraints("memory_documents")
    ) or _sqlite_memory_documents_table_sql_has_legacy_unique(connection)
    if not has_legacy_constraint:
        return

    old_table = "_memory_documents_old_unique_rebuild"
    connection.execute(text(f"DROP TABLE IF EXISTS {old_table}"))
    connection.execute(text(f"ALTER TABLE memory_documents RENAME TO {old_table}"))
    connection.execute(
        text(
            """
            CREATE TABLE memory_documents (
                id VARCHAR(80) NOT NULL,
                space_id VARCHAR(80) NOT NULL,
                profile_id VARCHAR(80) NOT NULL,
                thread_id VARCHAR(80),
                title VARCHAR(300) NOT NULL,
                source_type VARCHAR(80) NOT NULL,
                source_external_id VARCHAR(240) NOT NULL,
                content_hash VARCHAR(80) NOT NULL,
                classification VARCHAR(40) NOT NULL DEFAULT 'unknown',
                status VARCHAR(40) NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
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
            SELECT
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
            FROM {old_table}
            """
        )
    )
    connection.execute(text(f"DROP TABLE {old_table}"))


def _sqlite_memory_documents_table_sql_has_legacy_unique(connection: Connection) -> bool:
    table_sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memory_documents'")
    ).scalar_one_or_none()
    if not table_sql:
        return False
    normalized = " ".join(str(table_sql).lower().replace('"', "").split())
    return (
        "constraint uq_document_source_hash unique" in normalized
        or "unique ( space_id, profile_id, source_type, source_external_id, content_hash )"
        in normalized
        or "unique (space_id, profile_id, source_type, source_external_id, content_hash)"
        in normalized
    )


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_additive_schema_columns)
        await connection.run_sync(_ensure_document_thread_unique_indexes)
        await connection.run_sync(_ensure_outbox_lifecycle_indexes)
        await connection.run_sync(_ensure_capture_indexes)
        await connection.run_sync(_ensure_suggestion_metadata_indexes)


def _ensure_outbox_lifecycle_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_outbox" not in set(inspector.get_table_names()):
        return
    connection.execute(
        text(
            """
            UPDATE memory_outbox
            SET fairness_key = aggregate_type || ':' || aggregate_id
            WHERE fairness_key IS NULL
            """
        )
    )


def _ensure_capture_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_captures" not in set(inspector.get_table_names()):
        return
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_capture_idempotency
            ON memory_captures(space_id, idempotency_key)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_captures_consolidation
            ON memory_captures(space_id, profile_id, consolidation_status, created_at)
            """
        )
    )


def _ensure_suggestion_metadata_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_suggestions" not in set(inspector.get_table_names()):
        return
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_suggestions_expiry
            ON memory_suggestions(space_id, profile_id, status, expires_at)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_outbox_workload_fairness
            ON memory_outbox(status, workload_class, fairness_key, next_attempt_at)
            """
        )
    )


class PostgresUnitOfWork:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: ClockPort,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._session = self._session_factory()
        now = self._clock.now()
        self.scope = PostgresScopeRepository(self._session)
        self.facts = PostgresFactRepository(self._session)
        self.episodes = PostgresEpisodeRepository(self._session)
        self.documents = PostgresDocumentRepository(self._session)
        self.chunks = PostgresChunkRepository(self._session)
        self.captures = PostgresCaptureRepository(self._session)
        self.suggestions = PostgresSuggestionRepository(self._session)
        self.idempotency = PostgresIdempotencyRepository(self._session, now=now)
        self.outbox = PostgresOutbox(self._session, now=now)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()
        self._session = None
        self._committed = False

    async def commit(self) -> None:
        if self._session is None:
            msg = "UnitOfWork is not open"
            raise RuntimeError(msg)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Canonical write conflicted with existing data") from exc
        self._committed = True

    async def rollback(self) -> None:
        if self._session is None:
            return
        await self._session.rollback()
        self._committed = False


class PostgresUnitOfWorkFactory:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: ClockPort,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def __call__(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(session_factory=self._session_factory, clock=self._clock)
