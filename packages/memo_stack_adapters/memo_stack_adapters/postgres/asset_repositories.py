"""Postgres asset, extraction, and context-link repositories."""

from __future__ import annotations

from datetime import datetime

from memo_stack_core.domain.assets import (
    MemoryAsset,
    MemoryContextLink,
    MemoryContextLinkSuggestion,
)
from memo_stack_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from memo_stack_core.domain.extraction import AssetExtractionJob, ExtractionArtifact
from memo_stack_core.ports.assets import (
    AssetRepositoryPort,
    ContextLinkRepositoryPort,
    ContextLinkSuggestionRepositoryPort,
)
from memo_stack_core.ports.extraction import AssetExtractionRepositoryPort
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_adapters.postgres.mappers import (
    apply_asset_extraction_job_to_row,
    apply_asset_to_row,
    apply_context_link_suggestion_to_row,
    apply_context_link_to_row,
    asset_extraction_job_row_to_domain,
    asset_extraction_job_to_row,
    asset_row_to_domain,
    asset_to_row,
    context_link_row_to_domain,
    context_link_suggestion_row_to_domain,
    context_link_suggestion_to_row,
    context_link_to_row,
    extraction_artifact_row_to_domain,
    extraction_artifact_to_row,
)
from memo_stack_adapters.postgres.models import (
    MemoryAssetExtractionArtifactRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
)


class PostgresAssetRepository(AssetRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, asset: MemoryAsset) -> MemoryAsset:
        self._session.add(asset_to_row(asset))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Asset metadata conflicted with existing data") from exc
        return asset

    async def save(self, asset: MemoryAsset) -> MemoryAsset:
        row = await self._session.get(MemoryAssetRow, str(asset.id))
        if row is None:
            raise MemoryNotFoundError("Asset not found")
        apply_asset_to_row(asset, row)
        await self._session.flush()
        return asset_row_to_domain(row)

    async def get_by_id(self, asset_id: str) -> MemoryAsset | None:
        row = await self._session.get(MemoryAssetRow, asset_id)
        return asset_row_to_domain(row) if row is not None else None

    async def find_stored_by_sha256(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        sha256_hex: str,
    ) -> MemoryAsset | None:
        conditions = [
            MemoryAssetRow.space_id == space_id,
            MemoryAssetRow.memory_scope_id == memory_scope_id,
            MemoryAssetRow.sha256_hex == sha256_hex,
            MemoryAssetRow.status == "stored",
        ]
        if thread_id is None:
            conditions.append(MemoryAssetRow.thread_id.is_(None))
        else:
            conditions.append(MemoryAssetRow.thread_id == thread_id)
        row = (
            await self._session.execute(
                select(MemoryAssetRow)
                .where(*conditions)
                .order_by(MemoryAssetRow.created_at.desc(), MemoryAssetRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return asset_row_to_domain(row) if row is not None else None

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryAsset]:
        conditions = [
            MemoryAssetRow.space_id == space_id,
            MemoryAssetRow.memory_scope_id == memory_scope_id,
        ]
        if thread_id is not None:
            conditions.append(
                or_(MemoryAssetRow.thread_id == thread_id, MemoryAssetRow.thread_id.is_(None))
            )
        if status:
            conditions.append(MemoryAssetRow.status == status)
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryAssetRow.created_at < cursor_created_at,
                    (MemoryAssetRow.created_at == cursor_created_at)
                    & (MemoryAssetRow.id < cursor_id),
                )
            )
        rows = (
            await self._session.execute(
                select(MemoryAssetRow)
                .where(*conditions)
                .order_by(MemoryAssetRow.created_at.desc(), MemoryAssetRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [asset_row_to_domain(row) for row in rows]


class PostgresAssetExtractionRepository(AssetExtractionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: AssetExtractionJob) -> AssetExtractionJob:
        self._session.add(asset_extraction_job_to_row(job))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Asset extraction job conflicted with existing data") from exc
        return job

    async def get_by_id(self, job_id: str) -> AssetExtractionJob | None:
        row = await self._session.get(MemoryAssetExtractionJobRow, job_id)
        return asset_extraction_job_row_to_domain(row) if row is not None else None

    async def find_active_for_asset_profile(
        self,
        *,
        asset_id: str,
        parser_profile: str,
        parser_config_hash: str,
        source_sha256_hex: str,
    ) -> AssetExtractionJob | None:
        row = (
            await self._session.execute(
                select(MemoryAssetExtractionJobRow)
                .where(
                    MemoryAssetExtractionJobRow.asset_id == asset_id,
                    MemoryAssetExtractionJobRow.parser_profile == parser_profile,
                    MemoryAssetExtractionJobRow.parser_config_hash == parser_config_hash,
                    MemoryAssetExtractionJobRow.source_sha256_hex == source_sha256_hex,
                    MemoryAssetExtractionJobRow.status.in_(("pending", "running", "succeeded")),
                )
                .order_by(
                    MemoryAssetExtractionJobRow.created_at.desc(),
                    MemoryAssetExtractionJobRow.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return asset_extraction_job_row_to_domain(row) if row is not None else None

    async def save(self, job: AssetExtractionJob) -> AssetExtractionJob:
        row = await self._session.get(MemoryAssetExtractionJobRow, str(job.id))
        if row is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        apply_asset_extraction_job_to_row(job, row)
        await self._session.flush()
        return asset_extraction_job_row_to_domain(row)

    async def create_artifact(self, artifact: ExtractionArtifact) -> ExtractionArtifact:
        self._session.add(extraction_artifact_to_row(artifact))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Extraction artifact conflicted with existing data") from exc
        return artifact

    async def list_artifacts(self, *, job_id: str) -> list[ExtractionArtifact]:
        rows = (
            await self._session.execute(
                select(MemoryAssetExtractionArtifactRow)
                .where(MemoryAssetExtractionArtifactRow.job_id == job_id)
                .order_by(
                    MemoryAssetExtractionArtifactRow.created_at,
                    MemoryAssetExtractionArtifactRow.id,
                )
            )
        ).scalars()
        return [extraction_artifact_row_to_domain(row) for row in rows]

    async def get_artifact_by_id(self, artifact_id: str) -> ExtractionArtifact | None:
        row = await self._session.get(MemoryAssetExtractionArtifactRow, artifact_id)
        return extraction_artifact_row_to_domain(row) if row is not None else None

    async def list_for_asset(
        self,
        *,
        asset_id: str,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[AssetExtractionJob]:
        conditions = [MemoryAssetExtractionJobRow.asset_id == asset_id]
        if status:
            conditions.append(MemoryAssetExtractionJobRow.status == status)
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryAssetExtractionJobRow.created_at < cursor_created_at,
                    (MemoryAssetExtractionJobRow.created_at == cursor_created_at)
                    & (MemoryAssetExtractionJobRow.id < cursor_id),
                )
            )
        rows = (
            await self._session.execute(
                select(MemoryAssetExtractionJobRow)
                .where(*conditions)
                .order_by(
                    MemoryAssetExtractionJobRow.created_at.desc(),
                    MemoryAssetExtractionJobRow.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [asset_extraction_job_row_to_domain(row) for row in rows]

    async def count_by_status_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
    ) -> dict[str, int]:
        conditions = [
            MemoryAssetExtractionJobRow.space_id == space_id,
            MemoryAssetExtractionJobRow.memory_scope_id == memory_scope_id,
        ]
        if thread_id is not None:
            conditions.append(
                or_(
                    MemoryAssetExtractionJobRow.thread_id == thread_id,
                    MemoryAssetExtractionJobRow.thread_id.is_(None),
                )
            )
        rows = (
            await self._session.execute(
                select(
                    MemoryAssetExtractionJobRow.status,
                    func.count(MemoryAssetExtractionJobRow.id),
                )
                .where(*conditions)
                .group_by(MemoryAssetExtractionJobRow.status)
            )
        ).all()
        return {str(status): int(count) for status, count in rows}

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[AssetExtractionJob]:
        conditions = [
            MemoryAssetExtractionJobRow.space_id == space_id,
            MemoryAssetExtractionJobRow.memory_scope_id == memory_scope_id,
        ]
        if thread_id is not None:
            conditions.append(
                or_(
                    MemoryAssetExtractionJobRow.thread_id == thread_id,
                    MemoryAssetExtractionJobRow.thread_id.is_(None),
                )
            )
        if status:
            conditions.append(MemoryAssetExtractionJobRow.status == status)
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryAssetExtractionJobRow.created_at < cursor_created_at,
                    (MemoryAssetExtractionJobRow.created_at == cursor_created_at)
                    & (MemoryAssetExtractionJobRow.id < cursor_id),
                )
            )
        rows = (
            await self._session.execute(
                select(MemoryAssetExtractionJobRow)
                .where(*conditions)
                .order_by(
                    MemoryAssetExtractionJobRow.created_at.desc(),
                    MemoryAssetExtractionJobRow.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [asset_extraction_job_row_to_domain(row) for row in rows]


class PostgresContextLinkRepository(ContextLinkRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, link: MemoryContextLink) -> MemoryContextLink:
        self._session.add(context_link_to_row(link))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Context link conflicted with existing data") from exc
        return link

    async def save(self, link: MemoryContextLink) -> MemoryContextLink:
        row = await self._session.get(MemoryContextLinkRow, str(link.id))
        if row is None:
            raise MemoryNotFoundError("Context link not found")
        apply_context_link_to_row(link, row)
        await self._session.flush()
        return context_link_row_to_domain(row)

    async def get_by_id(self, context_link_id: str) -> MemoryContextLink | None:
        row = await self._session.get(MemoryContextLinkRow, context_link_id)
        return context_link_row_to_domain(row) if row is not None else None

    async def find_active(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLink | None:
        row = (
            await self._session.execute(
                select(MemoryContextLinkRow).where(
                    MemoryContextLinkRow.space_id == space_id,
                    MemoryContextLinkRow.memory_scope_id == memory_scope_id,
                    MemoryContextLinkRow.source_type == source_type,
                    MemoryContextLinkRow.source_id == source_id,
                    MemoryContextLinkRow.target_type == target_type,
                    MemoryContextLinkRow.target_id == target_id,
                    MemoryContextLinkRow.relation_type == relation_type,
                    MemoryContextLinkRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        return context_link_row_to_domain(row) if row is not None else None

    async def list_for_source(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemoryContextLink]:
        conditions = [
            MemoryContextLinkRow.space_id == space_id,
            MemoryContextLinkRow.memory_scope_id == memory_scope_id,
            MemoryContextLinkRow.source_type == source_type,
            MemoryContextLinkRow.source_id == source_id,
        ]
        if status:
            conditions.append(MemoryContextLinkRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryContextLinkRow)
                .where(*conditions)
                .order_by(MemoryContextLinkRow.updated_at.desc(), MemoryContextLinkRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [context_link_row_to_domain(row) for row in rows]

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemoryContextLink]:
        conditions = [
            MemoryContextLinkRow.space_id == space_id,
            MemoryContextLinkRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemoryContextLinkRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryContextLinkRow)
                .where(*conditions)
                .order_by(MemoryContextLinkRow.updated_at.desc(), MemoryContextLinkRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [context_link_row_to_domain(row) for row in rows]


class PostgresContextLinkSuggestionRepository(ContextLinkSuggestionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        suggestion: MemoryContextLinkSuggestion,
    ) -> MemoryContextLinkSuggestion:
        self._session.add(context_link_suggestion_to_row(suggestion))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError(
                "Context link suggestion conflicted with existing data"
            ) from exc
        return suggestion

    async def save(
        self,
        suggestion: MemoryContextLinkSuggestion,
    ) -> MemoryContextLinkSuggestion:
        row = await self._session.get(MemoryContextLinkSuggestionRow, str(suggestion.id))
        if row is None:
            raise MemoryNotFoundError("Context link suggestion not found")
        apply_context_link_suggestion_to_row(suggestion, row)
        await self._session.flush()
        return context_link_suggestion_row_to_domain(row)

    async def get_by_id(
        self,
        suggestion_id: str,
    ) -> MemoryContextLinkSuggestion | None:
        row = await self._session.get(MemoryContextLinkSuggestionRow, suggestion_id)
        return context_link_suggestion_row_to_domain(row) if row is not None else None

    async def find_pending(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLinkSuggestion | None:
        row = (
            await self._session.execute(
                select(MemoryContextLinkSuggestionRow).where(
                    MemoryContextLinkSuggestionRow.space_id == space_id,
                    MemoryContextLinkSuggestionRow.memory_scope_id == memory_scope_id,
                    MemoryContextLinkSuggestionRow.source_type == source_type,
                    MemoryContextLinkSuggestionRow.source_id == source_id,
                    MemoryContextLinkSuggestionRow.target_type == target_type,
                    MemoryContextLinkSuggestionRow.target_id == target_id,
                    MemoryContextLinkSuggestionRow.relation_type == relation_type,
                    MemoryContextLinkSuggestionRow.status == "pending",
                )
            )
        ).scalar_one_or_none()
        return context_link_suggestion_row_to_domain(row) if row is not None else None

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[MemoryContextLinkSuggestion]:
        conditions = [
            MemoryContextLinkSuggestionRow.space_id == space_id,
            MemoryContextLinkSuggestionRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemoryContextLinkSuggestionRow.status == status)
        if source_type:
            conditions.append(MemoryContextLinkSuggestionRow.source_type == source_type)
        if source_id:
            conditions.append(MemoryContextLinkSuggestionRow.source_id == source_id)
        rows = (
            await self._session.execute(
                select(MemoryContextLinkSuggestionRow)
                .where(*conditions)
                .order_by(
                    MemoryContextLinkSuggestionRow.updated_at.desc(),
                    MemoryContextLinkSuggestionRow.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [context_link_suggestion_row_to_domain(row) for row in rows]

    async def count_by_status_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
    ) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(
                    MemoryContextLinkSuggestionRow.status,
                    func.count(MemoryContextLinkSuggestionRow.id),
                )
                .where(
                    MemoryContextLinkSuggestionRow.space_id == space_id,
                    MemoryContextLinkSuggestionRow.memory_scope_id == memory_scope_id,
                )
                .group_by(MemoryContextLinkSuggestionRow.status)
            )
        ).all()
        return {str(status): int(count) for status, count in rows}
