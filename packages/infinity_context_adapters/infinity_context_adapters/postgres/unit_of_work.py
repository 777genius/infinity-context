"""Postgres unit of work and engine helpers."""

from __future__ import annotations

from types import TracebackType

from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdPort,
    ReviewedFactMutationExecutor,
)
from infinity_context_core.ports.clock import ClockPort
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactTransaction,
)
from infinity_context_adapters.postgres.anchor_repositories import (
    PostgresAnchorRepository,
)
from infinity_context_adapters.postgres.asset_repositories import (
    PostgresAssetExtractionRepository,
    PostgresAssetRepository,
    PostgresContextLinkRepository,
    PostgresContextLinkSuggestionRepository,
)
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    PostgresBenchmarkRunRepository,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_CONSTRAINT as _BENCHMARK_WRITER_FENCE_CONSTRAINT,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_SQLSTATE as _BENCHMARK_WRITER_FENCE_SQLSTATE,
)
from infinity_context_adapters.postgres.capture_repositories import (
    PostgresCaptureRepository,
)
from infinity_context_adapters.postgres.document_repositories import (
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from infinity_context_adapters.postgres.document_source_ref_coordination import (
    coordinate_document_source_ref_write,
)
from infinity_context_adapters.postgres.episode_repositories import (
    PostgresEpisodeRepository,
)
from infinity_context_adapters.postgres.fact_repositories import (
    PostgresFactRelationRepository,
    PostgresFactRepository,
)
from infinity_context_adapters.postgres.record_repositories import (
    PostgresIdempotencyRepository,
    PostgresOutbox,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _ADDITIVE_SCHEMA_COLUMNS as _ADDITIVE_SCHEMA_COLUMNS,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _LEGACY_PROFILE_ID_TABLES as _LEGACY_PROFILE_ID_TABLES,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _column_names as _column_names,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _copy_legacy_profiles_to_memory_scopes as _copy_legacy_profiles_to_memory_scopes,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _decode_json_string_list as _decode_json_string_list,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _ensure_additive_schema_columns as _ensure_additive_schema_columns,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _ensure_document_thread_unique_indexes as _ensure_document_thread_unique_indexes,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _ensure_legacy_profile_schema as _ensure_legacy_profile_schema,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _rebuild_sqlite_memory_documents_without_legacy_unique as _rebuild_sqlite_legacy_documents,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _rename_or_backfill_legacy_column as _rename_or_backfill_legacy_column,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _repoint_legacy_profile_references as _repoint_legacy_profile_references,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _repoint_scalar_scope_column as _repoint_scalar_scope_column,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _repoint_token_scope_json as _repoint_token_scope_json,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _sqlite_memory_documents_table_sql_has_legacy_unique as _sqlite_has_legacy_document_unique,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _backfill_memory_fact_temporal_columns as _backfill_memory_fact_temporal_columns,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_capture_indexes as _ensure_capture_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_managed_benchmark_writer_fence as _ensure_managed_benchmark_writer_fence,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_memory_fact_code_scope_indexes as _ensure_memory_fact_code_scope_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_memory_fact_supersession_indexes as _ensure_memory_fact_supersession_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_memory_fact_temporal_indexes as _ensure_memory_fact_temporal_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_outbox_lifecycle_indexes as _ensure_outbox_lifecycle_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_runtime_schema as _ensure_runtime_schema,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _ensure_suggestion_metadata_indexes as _ensure_suggestion_metadata_indexes,
)
from infinity_context_adapters.postgres.schema_runtime import (
    _expire_duplicate_pending_suggestions_before_unique_indexes as _expire_duplicate_pending,
)
from infinity_context_adapters.postgres.schema_runtime import (
    create_schema as create_schema,
)
from infinity_context_adapters.postgres.scope_repositories import PostgresScopeRepository
from infinity_context_adapters.postgres.suggestion_repositories import (
    PostgresSuggestionRepository,
)
from infinity_context_adapters.postgres.suggestion_resolution_receipts import (
    PostgresSuggestionResolutionReceiptRepository,
)
from infinity_context_adapters.postgres.usage_repositories import PostgresUsageRepository
from infinity_context_adapters.postgres.user_repositories import PostgresUserRepository

# Explicit aliases retain long legacy helper names within the import style limit.
_rebuild_sqlite_memory_documents_without_legacy_unique = _rebuild_sqlite_legacy_documents
_sqlite_memory_documents_table_sql_has_legacy_unique = _sqlite_has_legacy_document_unique
_expire_duplicate_pending_suggestions_before_unique_indexes = _expire_duplicate_pending

_BENCHMARK_WRITER_FENCE_MESSAGE = "Benchmark canonical write conflicted with cleanup in progress"


def _is_benchmark_writer_fence_error(exc: IntegrityError) -> bool:
    """Match only the stable Postgres trigger identity, including wrapped drivers."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        diagnostics = getattr(current, "diag", None)
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current,
            "pgcode",
            None,
        )
        constraint = getattr(current, "constraint_name", None) or getattr(
            diagnostics,
            "constraint_name",
            None,
        )
        if (
            sqlstate == _BENCHMARK_WRITER_FENCE_SQLSTATE
            and constraint == _BENCHMARK_WRITER_FENCE_CONSTRAINT
        ):
            return True
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def build_async_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class PostgresUnitOfWork:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: ClockPort,
        memory_fact_ids: MemoryFactIdPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._memory_fact_ids = memory_fact_ids
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._session = self._session_factory()
        self.benchmark_runs = PostgresBenchmarkRunRepository(self._session)
        now = self._clock.now()
        self.scope = PostgresScopeRepository(self._session)
        self.users = PostgresUserRepository(self._session)
        self.facts = PostgresFactRepository(self._session, now=now)
        self.fact_relations = PostgresFactRelationRepository(self._session)
        self.assets = PostgresAssetRepository(self._session)
        self.asset_extractions = PostgresAssetExtractionRepository(self._session)
        self.context_links = PostgresContextLinkRepository(self._session)
        self.context_link_suggestions = PostgresContextLinkSuggestionRepository(self._session)
        self.anchors = PostgresAnchorRepository(self._session)
        self.episodes = PostgresEpisodeRepository(self._session)
        self.documents = PostgresDocumentRepository(self._session)
        self.chunks = PostgresChunkRepository(self._session)
        self.captures = PostgresCaptureRepository(self._session)
        self.suggestions = PostgresSuggestionRepository(self._session)
        self.suggestion_resolution_receipts = PostgresSuggestionResolutionReceiptRepository(
            self._session
        )
        self.usage = PostgresUsageRepository(self._session)
        self.idempotency = PostgresIdempotencyRepository(self._session, now=now)
        self.outbox = PostgresOutbox(self._session, now=now)
        if self._memory_fact_ids is not None:
            memory_fact_transaction = PostgresMemoryFactTransaction(self._session, now=now)
            self.reviewed_facts = ReviewedFactMutationExecutor(
                transaction=memory_fact_transaction,
                clock=self._clock,
                ids=self._memory_fact_ids,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        integrity_error = exc if isinstance(exc, IntegrityError) else None
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()
        self._session = None
        self._committed = False
        if integrity_error is not None:
            message = (
                _BENCHMARK_WRITER_FENCE_MESSAGE
                if _is_benchmark_writer_fence_error(integrity_error)
                else "Canonical write conflicted with existing data"
            )
            raise MemoryConflictError(message) from integrity_error

    async def commit(self) -> None:
        if self._session is None:
            msg = "UnitOfWork is not open"
            raise RuntimeError(msg)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _is_benchmark_writer_fence_error(exc):
                raise MemoryConflictError(_BENCHMARK_WRITER_FENCE_MESSAGE) from exc
            raise MemoryConflictError("Canonical write conflicted with existing data") from exc
        self._committed = True

    async def coordinate_fact_source_refs(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        source_refs: tuple[SourceRef, ...],
    ) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not open")
        await coordinate_document_source_ref_write(
            self._session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            source_refs=source_refs,
        )

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
        memory_fact_ids: MemoryFactIdPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._memory_fact_ids = memory_fact_ids

    def __call__(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            memory_fact_ids=self._memory_fact_ids,
        )
