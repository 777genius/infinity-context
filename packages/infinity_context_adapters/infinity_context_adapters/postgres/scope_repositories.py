"""Postgres repositories for space, memory scope, and thread lifecycle."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.domain.entities import MemoryScope, MemorySpace, MemoryThread
from infinity_context_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from infinity_context_core.ports.repositories import (
    CanonicalChunkVersion,
    ResolvedScope,
    ScopeRepositoryPort,
    SessionDeleteResult,
    SessionStatus,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.mappers import (
    memory_scope_row_to_domain,
    space_row_to_domain,
    thread_row_to_domain,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.repository_helpers import _stable_id


class PostgresScopeRepository(ScopeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_space(self, space: MemorySpace) -> MemorySpace:
        existing = (
            await self._session.execute(
                select(MemorySpaceRow).where(MemorySpaceRow.slug == space.slug)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return space_row_to_domain(existing)
        self._session.add(
            MemorySpaceRow(
                id=str(space.id),
                slug=space.slug,
                name=space.name,
                status=space.status.value,
                created_at=space.created_at,
                updated_at=space.updated_at,
            )
        )
        return space

    async def list_spaces(self, *, limit: int) -> list[MemorySpace]:
        rows = (
            await self._session.execute(
                select(MemorySpaceRow)
                .where(MemorySpaceRow.status == "active")
                .order_by(MemorySpaceRow.updated_at.desc(), MemorySpaceRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [space_row_to_domain(row) for row in rows]

    async def create_memory_scope(self, memory_scope: MemoryScope) -> MemoryScope:
        existing = (
            await self._session.execute(
                select(MemoryScopeRow).where(
                    MemoryScopeRow.space_id == str(memory_scope.space_id),
                    MemoryScopeRow.external_ref == memory_scope.external_ref,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == "deleted":
                existing.name = memory_scope.name
                existing.status = "active"
                existing.updated_at = memory_scope.updated_at
                await self._session.flush()
            return memory_scope_row_to_domain(existing)
        space = await self._session.get(MemorySpaceRow, str(memory_scope.space_id))
        if space is None or space.status != "active":
            raise MemoryNotFoundError("Space not found")
        self._session.add(
            MemoryScopeRow(
                id=str(memory_scope.id),
                space_id=str(memory_scope.space_id),
                external_ref=memory_scope.external_ref,
                name=memory_scope.name,
                status=memory_scope.status.value,
                created_at=memory_scope.created_at,
                updated_at=memory_scope.updated_at,
            )
        )
        return memory_scope

    async def list_memory_scopes(self, *, space_id: str, limit: int) -> list[MemoryScope]:
        rows = (
            await self._session.execute(
                select(MemoryScopeRow)
                .where(
                    MemoryScopeRow.space_id == space_id,
                    MemoryScopeRow.status == "active",
                )
                .order_by(MemoryScopeRow.updated_at.desc(), MemoryScopeRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [memory_scope_row_to_domain(row) for row in rows]

    async def get_memory_scope(self, memory_scope_id: str) -> MemoryScope | None:
        row = await self._session.get(MemoryScopeRow, memory_scope_id)
        if row is None:
            return None
        return memory_scope_row_to_domain(row)

    async def get_thread(self, thread_id: str) -> MemoryThread | None:
        row = await self._session.get(MemoryThreadRow, thread_id)
        if row is None:
            return None
        return thread_row_to_domain(row)

    async def list_threads(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemoryThread]:
        stmt = select(MemoryThreadRow).where(
            MemoryThreadRow.space_id == space_id,
            MemoryThreadRow.memory_scope_id == memory_scope_id,
        )
        if status is not None:
            stmt = stmt.where(MemoryThreadRow.status == status)
        rows = (
            await self._session.execute(
                stmt.order_by(MemoryThreadRow.updated_at.desc(), MemoryThreadRow.id.desc()).limit(
                    limit
                )
            )
        ).scalars()
        return [thread_row_to_domain(row) for row in rows]

    async def save_memory_scope(self, memory_scope: MemoryScope) -> MemoryScope:
        row = await self._session.get(MemoryScopeRow, str(memory_scope.id))
        if row is None:
            raise MemoryNotFoundError("MemoryScope not found")
        if row.external_ref != memory_scope.external_ref:
            conflict = (
                await self._session.execute(
                    select(MemoryScopeRow).where(
                        MemoryScopeRow.space_id == row.space_id,
                        MemoryScopeRow.external_ref == memory_scope.external_ref,
                        MemoryScopeRow.id != row.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                raise MemoryConflictError("MemoryScope external_ref already exists")
        row.external_ref = memory_scope.external_ref
        row.name = memory_scope.name
        row.status = memory_scope.status.value
        row.updated_at = memory_scope.updated_at
        await self._session.flush()
        return memory_scope_row_to_domain(row)

    async def ensure_scope(
        self,
        *,
        space_slug: str,
        memory_scope_external_ref: str,
        thread_external_ref: str | None,
        now: datetime,
    ) -> ResolvedScope:
        space_slug = space_slug.strip()
        memory_scope_external_ref = memory_scope_external_ref.strip()
        if not space_slug:
            space_slug = "default"
        if not memory_scope_external_ref:
            memory_scope_external_ref = "default"

        space = (
            await self._session.execute(
                select(MemorySpaceRow).where(MemorySpaceRow.slug == space_slug)
            )
        ).scalar_one_or_none()
        if space is None:
            await self._insert_ignore(
                MemorySpaceRow,
                values={
                    "id": _stable_id("space", space_slug),
                    "slug": space_slug,
                    "name": space_slug,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                },
                index_elements=(MemorySpaceRow.slug,),
            )
            space = (
                await self._session.execute(
                    select(MemorySpaceRow).where(MemorySpaceRow.slug == space_slug)
                )
            ).scalar_one()

        memory_scope = (
            await self._session.execute(
                select(MemoryScopeRow).where(
                    MemoryScopeRow.space_id == space.id,
                    MemoryScopeRow.external_ref == memory_scope_external_ref,
                )
            )
        ).scalar_one_or_none()
        if memory_scope is None:
            await self._insert_ignore(
                MemoryScopeRow,
                values={
                    "id": _stable_id("memory_scope", space.id, memory_scope_external_ref),
                    "space_id": space.id,
                    "external_ref": memory_scope_external_ref,
                    "name": memory_scope_external_ref,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                },
                index_elements=(MemoryScopeRow.space_id, MemoryScopeRow.external_ref),
            )
            memory_scope = (
                await self._session.execute(
                    select(MemoryScopeRow).where(
                        MemoryScopeRow.space_id == space.id,
                        MemoryScopeRow.external_ref == memory_scope_external_ref,
                    )
                )
            ).scalar_one()
        elif memory_scope.status == "deleted":
            memory_scope.status = "active"
            memory_scope.updated_at = now

        thread_id = None
        if thread_external_ref:
            thread = (
                await self._session.execute(
                    select(MemoryThreadRow).where(
                        MemoryThreadRow.space_id == space.id,
                        MemoryThreadRow.memory_scope_id == memory_scope.id,
                        MemoryThreadRow.external_ref == thread_external_ref,
                    )
                )
            ).scalar_one_or_none()
            if thread is None:
                await self._insert_ignore(
                    MemoryThreadRow,
                    values={
                        "id": _stable_id("thread", space.id, memory_scope.id, thread_external_ref),
                        "space_id": space.id,
                        "memory_scope_id": memory_scope.id,
                        "external_ref": thread_external_ref,
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    index_elements=(
                        MemoryThreadRow.space_id,
                        MemoryThreadRow.memory_scope_id,
                        MemoryThreadRow.external_ref,
                    ),
                )
                thread = (
                    await self._session.execute(
                        select(MemoryThreadRow).where(
                            MemoryThreadRow.space_id == space.id,
                            MemoryThreadRow.memory_scope_id == memory_scope.id,
                            MemoryThreadRow.external_ref == thread_external_ref,
                        )
                    )
                ).scalar_one()
            elif thread.status == "deleted":
                thread.status = "active"
                thread.updated_at = now
            thread_id = thread.id

        return ResolvedScope(
            space_id=space.id,
            memory_scope_id=memory_scope.id,
            thread_id=thread_id,
        )

    async def _insert_ignore(
        self,
        row_type: type,
        *,
        values: dict[str, object],
        index_elements: tuple[object, ...],
    ) -> None:
        dialect_name = self._session.get_bind().dialect.name
        table = row_type.__table__
        if dialect_name == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=index_elements)
            )
        elif dialect_name == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=index_elements)
            )
        else:
            self._session.add(row_type(**values))
            await self._session.flush()
            return
        await self._session.execute(statement)
        await self._session.flush()

    async def delete_thread_memory(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> SessionDeleteResult:
        aggregate_ids = await self._aggregate_ids_for_thread(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        # Prune obsolete work before canonical mutations enqueue authoritative
        # profile tombstones. Those new tombstones must survive this transaction.
        jobs = await self._delete_outbox_for_aggregate_ids(aggregate_ids)
        chunk_versions = await self._soft_delete_chunk_versions(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        chunk_ids = tuple(item.chunk_id for item in chunk_versions)
        fact_ids = await self._soft_delete_ids(
            MemoryFactRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        await self._soft_delete_ids(
            MemoryEpisodeRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        await self._soft_delete_ids(
            MemoryDocumentRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        return SessionDeleteResult(
            deleted_chunks=len(chunk_ids),
            deleted_facts=len(fact_ids),
            deleted_jobs=jobs,
            deleted_chunk_ids=chunk_ids,
            deleted_chunk_versions=chunk_versions,
            deleted_fact_ids=fact_ids,
        )

    async def thread_status(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> SessionStatus:
        chunks = await self._active_count(
            MemoryChunkRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        facts = await self._active_count(
            MemoryFactRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        aggregate_ids = await self._aggregate_ids_for_thread(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        jobs = await self._outbox_count_for_aggregate_ids(aggregate_ids)
        pending = await self._outbox_count_for_aggregate_ids(
            aggregate_ids,
            statuses=("pending", "retry_pending"),
        )
        return SessionStatus(chunks=chunks, facts=facts, jobs=jobs, pending_jobs=pending)

    async def _soft_delete_ids(
        self,
        model: (
            type[MemoryChunkRow]
            | type[MemoryFactRow]
            | type[MemoryEpisodeRow]
            | type[MemoryDocumentRow]
        ),
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> tuple[str, ...]:
        ids = await self._ids_for_thread(
            model,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            active_only=True,
        )
        if not ids:
            return ()
        await self._session.execute(
            update(model)
            .where(
                model.id.in_(ids),
            )
            .values(status="deleted")
        )
        return ids

    async def _soft_delete_chunk_versions(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> tuple[CanonicalChunkVersion, ...]:
        rows = list(
            (
                await self._session.execute(
                    select(MemoryChunkRow)
                    .where(
                        MemoryChunkRow.space_id == space_id,
                        MemoryChunkRow.memory_scope_id == memory_scope_id,
                        MemoryChunkRow.thread_id == thread_id,
                        MemoryChunkRow.status != "deleted",
                    )
                    .order_by(MemoryChunkRow.id)
                    .with_for_update()
                )
            ).scalars()
        )
        versions = tuple(
            CanonicalChunkVersion(
                chunk_id=row.id,
                canonical_version=row.retrieval_version,
            )
            for row in rows
        )
        for row in rows:
            row.status = "deleted"
            row.retrieval_version += 1
        return versions

    async def _aggregate_ids_for_thread(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> tuple[str, ...]:
        chunks = await self._ids_for_thread(
            MemoryChunkRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            active_only=False,
        )
        facts = await self._ids_for_thread(
            MemoryFactRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            active_only=False,
        )
        episodes = await self._ids_for_thread(
            MemoryEpisodeRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            active_only=False,
        )
        documents = await self._ids_for_thread(
            MemoryDocumentRow,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            active_only=False,
        )
        return (*chunks, *facts, *episodes, *documents)

    async def _ids_for_thread(
        self,
        model: (
            type[MemoryChunkRow]
            | type[MemoryFactRow]
            | type[MemoryEpisodeRow]
            | type[MemoryDocumentRow]
        ),
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
        active_only: bool,
    ) -> tuple[str, ...]:
        conditions = [
            model.space_id == space_id,
            model.memory_scope_id == memory_scope_id,
            model.thread_id == thread_id,
        ]
        if active_only:
            conditions.append(model.status != "deleted")
        rows = (await self._session.execute(select(model.id).where(*conditions))).scalars()
        return tuple(str(row_id) for row_id in rows)

    async def _delete_outbox_for_aggregate_ids(self, aggregate_ids: tuple[str, ...]) -> int:
        if not aggregate_ids:
            return 0
        result = await self._session.execute(
            delete(MemoryOutboxRow).where(MemoryOutboxRow.aggregate_id.in_(aggregate_ids))
        )
        return int(result.rowcount or 0)

    async def _outbox_count_for_aggregate_ids(
        self,
        aggregate_ids: tuple[str, ...],
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        if not aggregate_ids:
            return 0
        conditions = [MemoryOutboxRow.aggregate_id.in_(aggregate_ids)]
        if statuses is not None:
            conditions.append(MemoryOutboxRow.status.in_(statuses))
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemoryOutboxRow).where(*conditions)
                )
            ).scalar_one()
        )

    async def _active_count(
        self,
        model: type[MemoryChunkRow] | type[MemoryFactRow],
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.space_id == space_id,
                        model.memory_scope_id == memory_scope_id,
                        model.thread_id == thread_id,
                        model.status != "deleted",
                    )
                )
            ).scalar_one()
        )
