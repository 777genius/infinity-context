"""Database-backed authorization scope checks.

HTTP dependencies pass plain request refs into this module. The API layer
does not open sessions or import ORM models directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryAssetExtractionArtifactRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_server.composition import Container


@dataclass(frozen=True)
class PathResourceRefs:
    space_id: str | None = None
    anchor_id: str | None = None
    fact_id: str | None = None
    document_id: str | None = None
    suggestion_id: str | None = None
    asset_id: str | None = None
    asset_extraction_job_id: str | None = None
    extraction_artifact_id: str | None = None
    context_link_id: str | None = None
    context_link_suggestion_id: str | None = None
    memory_scope_id: str | None = None


@dataclass(frozen=True)
class ExistingScopeRefs:
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None


async def resolve_existing_external_scope(
    container: Container,
    *,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
) -> ExistingScopeRefs | None:
    """Resolve external scope refs without creating rows."""

    normalized_space_slug = _scope_ref(
        space_slug,
        fallback=container.settings.default_space_slug,
    )
    normalized_memory_scope_ref = _scope_ref(
        memory_scope_external_ref,
        fallback=container.settings.default_memory_scope_external_ref,
    )
    normalized_thread_ref = _optional_scope_ref(thread_external_ref)

    async with AsyncSession(container.engine) as session:
        space = (
            await session.execute(
                select(MemorySpaceRow).where(
                    MemorySpaceRow.slug == normalized_space_slug,
                    MemorySpaceRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        if space is None:
            return None

        memory_scope = (
            await session.execute(
                select(MemoryScopeRow).where(
                    MemoryScopeRow.space_id == space.id,
                    MemoryScopeRow.external_ref == normalized_memory_scope_ref,
                    MemoryScopeRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        if memory_scope is None:
            return None

        thread_id = None
        if normalized_thread_ref is not None:
            thread_id = (
                await session.execute(
                    select(MemoryThreadRow.id).where(
                        MemoryThreadRow.space_id == space.id,
                        MemoryThreadRow.memory_scope_id == memory_scope.id,
                        MemoryThreadRow.external_ref == normalized_thread_ref,
                        MemoryThreadRow.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if thread_id is None:
                return None

    return ExistingScopeRefs(
        space_id=str(space.id),
        memory_scope_id=str(memory_scope.id),
        thread_id=str(thread_id) if thread_id else None,
    )


async def requested_space_refs(
    container: Container,
    *,
    query_space: str | None,
    query_space_slug: str | None,
    body_space: str | None,
    body_space_slug: str | None,
    path_refs: PathResourceRefs,
    include_default_legacy_space: bool,
) -> set[str]:
    refs: set[str] = set()
    if query_space:
        refs.add(query_space)
    if query_space_slug:
        refs.add(query_space_slug)
    if body_space:
        refs.add(body_space)
    if body_space_slug:
        refs.add(body_space_slug)

    await _add_space_from_path_resource(container, refs, path_refs)

    if include_default_legacy_space:
        refs.add(container.settings.default_space_slug)

    return refs


async def requested_memory_scope_refs(
    container: Container,
    *,
    query_memory_scope: str | None,
    query_memory_scope_external_ref: str | None,
    body_memory_scope: str | None,
    body_memory_scope_ids: tuple[str, ...],
    body_memory_scope_external_ref: str | None,
    body_memory_scope_external_refs: tuple[str, ...],
    path_refs: PathResourceRefs,
    include_default_legacy_memory_scope: bool,
) -> set[str]:
    refs: set[str] = set()
    if query_memory_scope:
        refs.add(query_memory_scope)
    if query_memory_scope_external_ref:
        refs.add(query_memory_scope_external_ref)
    if body_memory_scope:
        refs.add(body_memory_scope)
    refs.update(body_memory_scope_ids)
    if body_memory_scope_external_ref:
        refs.add(body_memory_scope_external_ref)
    refs.update(body_memory_scope_external_refs)

    await _add_memory_scope_from_path_resource(container, refs, path_refs)

    if include_default_legacy_memory_scope:
        refs.add(container.settings.default_memory_scope_external_ref)

    return refs


async def space_matches(container: Container, token_scope: str, requested_space: str) -> bool:
    async with AsyncSession(container.engine) as session:
        token_space = await _load_space(session, token_scope)
        requested = await _load_space(session, requested_space)
    if token_scope == requested_space:
        return _scope_row_is_active(token_space) and _scope_row_is_active(requested)
    token_refs = _space_refs(token_space, fallback=token_scope)
    requested_refs = _space_refs(requested, fallback=requested_space)
    return not token_refs.isdisjoint(requested_refs)


async def memory_scope_matches(
    container: Container,
    token_scope: str,
    requested_memory_scope: str,
    *,
    space_scope: str | None = None,
) -> bool:
    async with AsyncSession(container.engine) as session:
        space = await _load_space(session, space_scope) if space_scope else None
        if space_scope and not _scope_row_is_active(space):
            return False
        space_id = space.id if space else None
        token_memory_scope = await _load_memory_scope(session, token_scope, space_id=space_id)
        requested = await _load_memory_scope(session, requested_memory_scope, space_id=space_id)
    if space_scope and (token_memory_scope is None or requested is None):
        return False
    if token_scope == requested_memory_scope:
        return _scope_row_is_active(token_memory_scope) and _scope_row_is_active(requested)
    token_refs = _memory_scope_refs(token_memory_scope, fallback=token_scope)
    requested_refs = _memory_scope_refs(requested, fallback=requested_memory_scope)
    return not token_refs.isdisjoint(requested_refs)


async def canonical_scope_matches(
    container: Container,
    *,
    space_id: str,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
) -> bool:
    if not memory_scope_ids:
        return False
    unique_memory_scope_ids = tuple(dict.fromkeys(memory_scope_ids))
    async with AsyncSession(container.engine) as session:
        space_exists = (
            await session.execute(
                select(MemorySpaceRow.id).where(
                    MemorySpaceRow.id == space_id,
                    MemorySpaceRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        memory_scope_rows = list(
            (
                await session.execute(
                    select(
                        MemoryScopeRow.id,
                        MemoryScopeRow.space_id,
                        MemoryScopeRow.status,
                    ).where(
                        MemoryScopeRow.id.in_(unique_memory_scope_ids),
                    )
                )
            ).all()
        )
        if space_exists is None:
            return not memory_scope_rows and thread_id is None
        if len(memory_scope_rows) != len(unique_memory_scope_ids):
            return False
        if any(row.status != "active" for row in memory_scope_rows):
            return False
        if any(row.space_id != space_id for row in memory_scope_rows):
            return False
        if thread_id is None:
            return True
        thread_row = (
            await session.execute(
                select(
                    MemoryThreadRow.space_id,
                    MemoryThreadRow.memory_scope_id,
                    MemoryThreadRow.status,
                ).where(
                    MemoryThreadRow.id == thread_id,
                )
            )
        ).one_or_none()
    if thread_row is None:
        return False
    return (
        thread_row.status == "active"
        and thread_row.space_id == space_id
        and thread_row.memory_scope_id in unique_memory_scope_ids
    )


async def _add_space_from_path_resource(
    container: Container,
    refs: set[str],
    path_refs: PathResourceRefs,
) -> None:
    if path_refs.space_id:
        refs.add(path_refs.space_id)

    async with AsyncSession(container.engine) as session:
        if path_refs.anchor_id:
            await _add_row_space(session, refs, MemoryAnchorRow, path_refs.anchor_id)

        if path_refs.fact_id:
            await _add_row_space(session, refs, MemoryFactRow, path_refs.fact_id)

        if path_refs.document_id:
            await _add_row_space(session, refs, MemoryDocumentRow, path_refs.document_id)

        if path_refs.suggestion_id:
            await _add_row_space(session, refs, MemorySuggestionRow, path_refs.suggestion_id)

        if path_refs.asset_id:
            await _add_row_space(session, refs, MemoryAssetRow, path_refs.asset_id)

        if path_refs.asset_extraction_job_id:
            await _add_row_space(
                session, refs, MemoryAssetExtractionJobRow, path_refs.asset_extraction_job_id
            )

        if path_refs.extraction_artifact_id:
            await _add_extraction_artifact_space(
                session, refs, path_refs.extraction_artifact_id
            )

        if path_refs.context_link_id:
            await _add_row_space(session, refs, MemoryContextLinkRow, path_refs.context_link_id)

        if path_refs.context_link_suggestion_id:
            await _add_row_space(
                session,
                refs,
                MemoryContextLinkSuggestionRow,
                path_refs.context_link_suggestion_id,
            )

        if path_refs.memory_scope_id:
            await _add_row_space(session, refs, MemoryScopeRow, path_refs.memory_scope_id)


async def _add_memory_scope_from_path_resource(
    container: Container,
    refs: set[str],
    path_refs: PathResourceRefs,
) -> None:
    async with AsyncSession(container.engine) as session:
        if path_refs.anchor_id:
            await _add_row_memory_scope(session, refs, MemoryAnchorRow, path_refs.anchor_id)

        if path_refs.fact_id:
            await _add_row_memory_scope(session, refs, MemoryFactRow, path_refs.fact_id)

        if path_refs.document_id:
            await _add_row_memory_scope(session, refs, MemoryDocumentRow, path_refs.document_id)

        if path_refs.suggestion_id:
            await _add_row_memory_scope(session, refs, MemorySuggestionRow, path_refs.suggestion_id)

        if path_refs.asset_id:
            await _add_row_memory_scope(session, refs, MemoryAssetRow, path_refs.asset_id)

        if path_refs.asset_extraction_job_id:
            await _add_row_memory_scope(
                session, refs, MemoryAssetExtractionJobRow, path_refs.asset_extraction_job_id
            )

        if path_refs.extraction_artifact_id:
            await _add_extraction_artifact_memory_scope(
                session, refs, path_refs.extraction_artifact_id
            )

        if path_refs.context_link_id:
            await _add_row_memory_scope(
                session, refs, MemoryContextLinkRow, path_refs.context_link_id
            )

        if path_refs.context_link_suggestion_id:
            await _add_row_memory_scope(
                session,
                refs,
                MemoryContextLinkSuggestionRow,
                path_refs.context_link_suggestion_id,
            )

        if path_refs.memory_scope_id:
            refs.add(path_refs.memory_scope_id)


async def _add_row_space(
    session: AsyncSession,
    refs: set[str],
    model: type[MemoryFactRow]
    | type[MemoryAnchorRow]
    | type[MemoryDocumentRow]
    | type[MemorySuggestionRow]
    | type[MemoryAssetRow]
    | type[MemoryAssetExtractionJobRow]
    | type[MemoryContextLinkRow]
    | type[MemoryContextLinkSuggestionRow]
    | type[MemoryScopeRow],
    row_id: str,
) -> None:
    space_id = await session.scalar(select(model.space_id).where(model.id == row_id))
    if space_id:
        refs.add(str(space_id))


async def _add_row_memory_scope(
    session: AsyncSession,
    refs: set[str],
    model: type[MemoryFactRow]
    | type[MemoryAnchorRow]
    | type[MemoryDocumentRow]
    | type[MemorySuggestionRow]
    | type[MemoryAssetRow]
    | type[MemoryAssetExtractionJobRow]
    | type[MemoryContextLinkRow]
    | type[MemoryContextLinkSuggestionRow],
    row_id: str,
) -> None:
    memory_scope_id = await session.scalar(select(model.memory_scope_id).where(model.id == row_id))
    if memory_scope_id:
        refs.add(str(memory_scope_id))


async def _add_extraction_artifact_space(
    session: AsyncSession,
    refs: set[str],
    artifact_id: str,
) -> None:
    space_id = await session.scalar(
        select(MemoryAssetExtractionJobRow.space_id)
        .join(
            MemoryAssetExtractionArtifactRow,
            MemoryAssetExtractionArtifactRow.job_id == MemoryAssetExtractionJobRow.id,
        )
        .where(MemoryAssetExtractionArtifactRow.id == artifact_id)
    )
    if space_id:
        refs.add(str(space_id))


async def _add_extraction_artifact_memory_scope(
    session: AsyncSession,
    refs: set[str],
    artifact_id: str,
) -> None:
    memory_scope_id = await session.scalar(
        select(MemoryAssetExtractionJobRow.memory_scope_id)
        .join(
            MemoryAssetExtractionArtifactRow,
            MemoryAssetExtractionArtifactRow.job_id == MemoryAssetExtractionJobRow.id,
        )
        .where(MemoryAssetExtractionArtifactRow.id == artifact_id)
    )
    if memory_scope_id:
        refs.add(str(memory_scope_id))


async def _load_space(session: AsyncSession, value: str) -> MemorySpaceRow | None:
    return (
        await session.execute(
            select(MemorySpaceRow).where(
                or_(MemorySpaceRow.id == value, MemorySpaceRow.slug == value)
            )
        )
    ).scalar_one_or_none()


async def _load_memory_scope(
    session: AsyncSession,
    value: str,
    *,
    space_id: str | None = None,
) -> MemoryScopeRow | None:
    conditions = [or_(MemoryScopeRow.id == value, MemoryScopeRow.external_ref == value)]
    if space_id is not None:
        conditions.append(MemoryScopeRow.space_id == space_id)
    rows = await session.execute(select(MemoryScopeRow).where(*conditions).limit(1))
    return rows.scalars().first()


def _space_refs(row: MemorySpaceRow | None, *, fallback: str) -> set[str]:
    if row is None:
        return {fallback}
    if row.status != "active":
        return set()
    return {row.id, row.slug}


def _memory_scope_refs(row: MemoryScopeRow | None, *, fallback: str) -> set[str]:
    if row is None:
        return {fallback}
    if row.status != "active":
        return set()
    return {row.id, row.external_ref}


def _scope_row_is_active(row: MemorySpaceRow | MemoryScopeRow | None) -> bool:
    return row is None or row.status == "active"


def _scope_ref(value: str | None, *, fallback: str) -> str:
    cleaned = value.strip() if value else ""
    return cleaned or fallback


def _optional_scope_ref(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None
