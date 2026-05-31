"""Database-backed authorization scope checks.

HTTP dependencies pass plain request refs into this module. The API layer
does not open sessions or import ORM models directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory_adapters.postgres.models import (
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryProfileRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_server.composition import Container


@dataclass(frozen=True)
class PathResourceRefs:
    fact_id: str | None = None
    document_id: str | None = None
    suggestion_id: str | None = None
    profile_id: str | None = None


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


async def requested_profile_refs(
    container: Container,
    *,
    query_profile: str | None,
    query_profile_external_ref: str | None,
    body_profile: str | None,
    body_profile_ids: tuple[str, ...],
    body_profile_external_ref: str | None,
    body_profile_external_refs: tuple[str, ...],
    path_refs: PathResourceRefs,
    include_default_legacy_profile: bool,
) -> set[str]:
    refs: set[str] = set()
    if query_profile:
        refs.add(query_profile)
    if query_profile_external_ref:
        refs.add(query_profile_external_ref)
    if body_profile:
        refs.add(body_profile)
    refs.update(body_profile_ids)
    if body_profile_external_ref:
        refs.add(body_profile_external_ref)
    refs.update(body_profile_external_refs)

    await _add_profile_from_path_resource(container, refs, path_refs)

    if include_default_legacy_profile:
        refs.add(container.settings.default_profile_external_ref)

    return refs


async def space_matches(container: Container, token_scope: str, requested_space: str) -> bool:
    if token_scope == requested_space:
        return True
    async with AsyncSession(container.engine) as session:
        token_space = await _load_space(session, token_scope)
        requested = await _load_space(session, requested_space)
    token_refs = _space_refs(token_space, fallback=token_scope)
    requested_refs = _space_refs(requested, fallback=requested_space)
    return not token_refs.isdisjoint(requested_refs)


async def profile_matches(
    container: Container,
    token_scope: str,
    requested_profile: str,
) -> bool:
    if token_scope == requested_profile:
        return True
    async with AsyncSession(container.engine) as session:
        token_profile = await _load_profile(session, token_scope)
        requested = await _load_profile(session, requested_profile)
    token_refs = _profile_refs(token_profile, fallback=token_scope)
    requested_refs = _profile_refs(requested, fallback=requested_profile)
    return not token_refs.isdisjoint(requested_refs)


async def canonical_scope_matches(
    container: Container,
    *,
    space_id: str,
    profile_ids: tuple[str, ...],
    thread_id: str | None,
) -> bool:
    if not profile_ids:
        return False
    unique_profile_ids = tuple(dict.fromkeys(profile_ids))
    async with AsyncSession(container.engine) as session:
        space_exists = (
            await session.execute(
                select(MemorySpaceRow.id).where(
                    MemorySpaceRow.id == space_id,
                    MemorySpaceRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        profile_rows = list(
            (
                await session.execute(
                    select(
                        MemoryProfileRow.id,
                        MemoryProfileRow.space_id,
                        MemoryProfileRow.status,
                    ).where(
                        MemoryProfileRow.id.in_(unique_profile_ids),
                    )
                )
            ).all()
        )
        if space_exists is None:
            return not profile_rows and thread_id is None
        if len(profile_rows) != len(unique_profile_ids):
            return False
        if any(row.status != "active" for row in profile_rows):
            return False
        if any(row.space_id != space_id for row in profile_rows):
            return False
        if thread_id is None:
            return True
        thread_row = (
            await session.execute(
                select(
                    MemoryThreadRow.space_id,
                    MemoryThreadRow.profile_id,
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
        and thread_row.profile_id in unique_profile_ids
    )


async def _add_space_from_path_resource(
    container: Container,
    refs: set[str],
    path_refs: PathResourceRefs,
) -> None:
    async with AsyncSession(container.engine) as session:
        if path_refs.fact_id:
            await _add_row_space(session, refs, MemoryFactRow, path_refs.fact_id)

        if path_refs.document_id:
            await _add_row_space(session, refs, MemoryDocumentRow, path_refs.document_id)

        if path_refs.suggestion_id:
            await _add_row_space(session, refs, MemorySuggestionRow, path_refs.suggestion_id)

        if path_refs.profile_id:
            await _add_row_space(session, refs, MemoryProfileRow, path_refs.profile_id)


async def _add_profile_from_path_resource(
    container: Container,
    refs: set[str],
    path_refs: PathResourceRefs,
) -> None:
    async with AsyncSession(container.engine) as session:
        if path_refs.fact_id:
            await _add_row_profile(session, refs, MemoryFactRow, path_refs.fact_id)

        if path_refs.document_id:
            await _add_row_profile(session, refs, MemoryDocumentRow, path_refs.document_id)

        if path_refs.suggestion_id:
            await _add_row_profile(session, refs, MemorySuggestionRow, path_refs.suggestion_id)

        if path_refs.profile_id:
            refs.add(path_refs.profile_id)


async def _add_row_space(
    session: AsyncSession,
    refs: set[str],
    model: type[MemoryFactRow]
    | type[MemoryDocumentRow]
    | type[MemorySuggestionRow]
    | type[MemoryProfileRow],
    row_id: str,
) -> None:
    space_id = await session.scalar(select(model.space_id).where(model.id == row_id))
    if space_id:
        refs.add(str(space_id))


async def _add_row_profile(
    session: AsyncSession,
    refs: set[str],
    model: type[MemoryFactRow] | type[MemoryDocumentRow] | type[MemorySuggestionRow],
    row_id: str,
) -> None:
    profile_id = await session.scalar(select(model.profile_id).where(model.id == row_id))
    if profile_id:
        refs.add(str(profile_id))


async def _load_space(session: AsyncSession, value: str) -> MemorySpaceRow | None:
    return (
        await session.execute(
            select(MemorySpaceRow).where(
                or_(MemorySpaceRow.id == value, MemorySpaceRow.slug == value)
            )
        )
    ).scalar_one_or_none()


async def _load_profile(session: AsyncSession, value: str) -> MemoryProfileRow | None:
    rows = await session.execute(
        select(MemoryProfileRow)
        .where(or_(MemoryProfileRow.id == value, MemoryProfileRow.external_ref == value))
        .limit(1)
    )
    return rows.scalars().first()


def _space_refs(row: MemorySpaceRow | None, *, fallback: str) -> set[str]:
    if row is None:
        return {fallback}
    return {row.id, row.slug}


def _profile_refs(row: MemoryProfileRow | None, *, fallback: str) -> set[str]:
    if row is None:
        return {fallback}
    return {row.id, row.external_ref}
