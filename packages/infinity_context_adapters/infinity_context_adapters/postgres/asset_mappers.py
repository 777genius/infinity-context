"""Postgres row mappers for asset extraction lifecycle entities."""

from __future__ import annotations

from infinity_context_core.domain.assets import (
    AssetStatus,
    ContextLinkSuggestionStatus,
    MemoryAsset,
    MemoryAssetId,
    MemoryContextLink,
    MemoryContextLinkId,
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    AssetExtractionStatus,
    ExtractionArtifact,
    ExtractionArtifactId,
    ExtractionArtifactType,
    ExtractionRetryDisposition,
)

from infinity_context_adapters.postgres.models import (
    MemoryAssetExtractionArtifactRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
)


def asset_to_row(asset: MemoryAsset) -> MemoryAssetRow:
    return MemoryAssetRow(
        id=str(asset.id),
        space_id=str(asset.space_id),
        memory_scope_id=str(asset.memory_scope_id),
        thread_id=str(asset.thread_id) if asset.thread_id else None,
        filename=asset.filename,
        content_type=asset.content_type,
        byte_size=asset.byte_size,
        sha256_hex=asset.sha256_hex,
        storage_backend=asset.storage_backend,
        storage_key=asset.storage_key,
        status=asset.status.value,
        classification=asset.classification,
        metadata_json=dict(asset.metadata),
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def apply_asset_to_row(asset: MemoryAsset, row: MemoryAssetRow) -> None:
    row.space_id = str(asset.space_id)
    row.memory_scope_id = str(asset.memory_scope_id)
    row.thread_id = str(asset.thread_id) if asset.thread_id else None
    row.filename = asset.filename
    row.content_type = asset.content_type
    row.byte_size = asset.byte_size
    row.sha256_hex = asset.sha256_hex
    row.storage_backend = asset.storage_backend
    row.storage_key = asset.storage_key
    row.status = asset.status.value
    row.classification = asset.classification
    row.metadata_json = dict(asset.metadata)
    row.created_at = asset.created_at
    row.updated_at = asset.updated_at


def asset_row_to_domain(row: MemoryAssetRow) -> MemoryAsset:
    return MemoryAsset(
        id=MemoryAssetId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if row.thread_id else None,
        filename=row.filename,
        content_type=row.content_type,
        byte_size=row.byte_size,
        sha256_hex=row.sha256_hex,
        storage_backend=row.storage_backend,
        storage_key=row.storage_key,
        status=AssetStatus(row.status),
        classification=row.classification,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def asset_extraction_job_to_row(job: AssetExtractionJob) -> MemoryAssetExtractionJobRow:
    return MemoryAssetExtractionJobRow(
        id=str(job.id),
        asset_id=str(job.asset_id),
        space_id=str(job.space_id),
        memory_scope_id=str(job.memory_scope_id),
        thread_id=str(job.thread_id) if job.thread_id else None,
        parser_profile=job.parser_profile,
        parser_config_hash=job.parser_config_hash,
        source_sha256_hex=job.source_sha256_hex,
        parser_name=job.parser_name,
        parser_version=job.parser_version,
        model_version=job.model_version,
        status=job.status.value,
        attempt_count=job.attempt_count,
        safe_error_code=job.safe_error_code,
        safe_error_message=job.safe_error_message,
        result_document_ids_json=list(job.result_document_ids),
        metadata_json=dict(job.metadata),
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        lease_owner=job.lease_owner,
        lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at,
        retry_after_at=job.retry_after_at,
        cancellation_requested_at=job.cancellation_requested_at,
        retry_disposition=job.retry_disposition.value if job.retry_disposition else None,
    )


def asset_extraction_job_row_to_domain(row: MemoryAssetExtractionJobRow) -> AssetExtractionJob:
    return AssetExtractionJob(
        id=AssetExtractionJobId(row.id),
        asset_id=MemoryAssetId(row.asset_id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if row.thread_id else None,
        parser_profile=row.parser_profile,
        parser_config_hash=row.parser_config_hash,
        source_sha256_hex=row.source_sha256_hex,
        status=AssetExtractionStatus(row.status),
        attempt_count=row.attempt_count,
        safe_error_code=row.safe_error_code,
        safe_error_message=row.safe_error_message,
        parser_name=row.parser_name,
        parser_version=row.parser_version,
        model_version=row.model_version,
        result_document_ids=tuple(row.result_document_ids_json or ()),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        heartbeat_at=row.heartbeat_at,
        retry_after_at=row.retry_after_at,
        cancellation_requested_at=row.cancellation_requested_at,
        retry_disposition=(
            ExtractionRetryDisposition(row.retry_disposition) if row.retry_disposition else None
        ),
    )


def apply_asset_extraction_job_to_row(
    job: AssetExtractionJob,
    row: MemoryAssetExtractionJobRow,
) -> None:
    row.asset_id = str(job.asset_id)
    row.space_id = str(job.space_id)
    row.memory_scope_id = str(job.memory_scope_id)
    row.thread_id = str(job.thread_id) if job.thread_id else None
    row.parser_profile = job.parser_profile
    row.parser_config_hash = job.parser_config_hash
    row.source_sha256_hex = job.source_sha256_hex
    row.parser_name = job.parser_name
    row.parser_version = job.parser_version
    row.model_version = job.model_version
    row.status = job.status.value
    row.attempt_count = job.attempt_count
    row.safe_error_code = job.safe_error_code
    row.safe_error_message = job.safe_error_message
    row.result_document_ids_json = list(job.result_document_ids)
    row.metadata_json = dict(job.metadata)
    row.created_at = job.created_at
    row.updated_at = job.updated_at
    row.started_at = job.started_at
    row.finished_at = job.finished_at
    row.lease_owner = job.lease_owner
    row.lease_expires_at = job.lease_expires_at
    row.heartbeat_at = job.heartbeat_at
    row.retry_after_at = job.retry_after_at
    row.cancellation_requested_at = job.cancellation_requested_at
    row.retry_disposition = job.retry_disposition.value if job.retry_disposition else None


def extraction_artifact_to_row(artifact: ExtractionArtifact) -> MemoryAssetExtractionArtifactRow:
    return MemoryAssetExtractionArtifactRow(
        id=str(artifact.id),
        job_id=str(artifact.job_id),
        asset_id=str(artifact.asset_id),
        artifact_type=artifact.artifact_type.value,
        storage_backend=artifact.storage_backend,
        storage_key=artifact.storage_key,
        sha256_hex=artifact.sha256_hex,
        byte_size=artifact.byte_size,
        metadata_json=dict(artifact.metadata),
        created_at=artifact.created_at,
    )


def extraction_artifact_row_to_domain(
    row: MemoryAssetExtractionArtifactRow,
) -> ExtractionArtifact:
    return ExtractionArtifact(
        id=ExtractionArtifactId(row.id),
        job_id=AssetExtractionJobId(row.job_id),
        asset_id=MemoryAssetId(row.asset_id),
        artifact_type=ExtractionArtifactType(row.artifact_type),
        storage_backend=row.storage_backend,
        storage_key=row.storage_key,
        sha256_hex=row.sha256_hex,
        byte_size=row.byte_size,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
    )


def context_link_to_row(link: MemoryContextLink) -> MemoryContextLinkRow:
    return MemoryContextLinkRow(
        id=str(link.id),
        space_id=str(link.space_id),
        memory_scope_id=str(link.memory_scope_id),
        source_type=link.source_type,
        source_id=link.source_id,
        target_type=link.target_type,
        target_id=link.target_id,
        relation_type=link.relation_type,
        confidence=link.confidence,
        reason=link.reason,
        status=link.status.value,
        metadata_json=dict(link.metadata),
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def apply_context_link_to_row(link: MemoryContextLink, row: MemoryContextLinkRow) -> None:
    row.space_id = str(link.space_id)
    row.memory_scope_id = str(link.memory_scope_id)
    row.source_type = link.source_type
    row.source_id = link.source_id
    row.target_type = link.target_type
    row.target_id = link.target_id
    row.relation_type = link.relation_type
    row.confidence = link.confidence
    row.reason = link.reason
    row.status = link.status.value
    row.metadata_json = dict(link.metadata)
    row.created_at = link.created_at
    row.updated_at = link.updated_at


def context_link_row_to_domain(row: MemoryContextLinkRow) -> MemoryContextLink:
    return MemoryContextLink(
        id=MemoryContextLinkId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        source_type=row.source_type,
        source_id=row.source_id,
        target_type=row.target_type,
        target_id=row.target_id,
        relation_type=row.relation_type,
        confidence=row.confidence,
        reason=row.reason,
        status=LifecycleStatus(row.status),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def context_link_suggestion_to_row(
    suggestion: MemoryContextLinkSuggestion,
) -> MemoryContextLinkSuggestionRow:
    return MemoryContextLinkSuggestionRow(
        id=str(suggestion.id),
        space_id=str(suggestion.space_id),
        memory_scope_id=str(suggestion.memory_scope_id),
        source_type=suggestion.source_type,
        source_id=suggestion.source_id,
        target_type=suggestion.target_type,
        target_id=suggestion.target_id,
        relation_type=suggestion.relation_type,
        confidence=suggestion.confidence,
        reason=suggestion.reason,
        score=suggestion.score,
        status=suggestion.status.value,
        metadata_json=dict(suggestion.metadata),
        created_at=suggestion.created_at,
        updated_at=suggestion.updated_at,
        reviewed_at=suggestion.reviewed_at,
        review_reason=suggestion.review_reason,
    )


def apply_context_link_suggestion_to_row(
    suggestion: MemoryContextLinkSuggestion,
    row: MemoryContextLinkSuggestionRow,
) -> None:
    row.space_id = str(suggestion.space_id)
    row.memory_scope_id = str(suggestion.memory_scope_id)
    row.source_type = suggestion.source_type
    row.source_id = suggestion.source_id
    row.target_type = suggestion.target_type
    row.target_id = suggestion.target_id
    row.relation_type = suggestion.relation_type
    row.confidence = suggestion.confidence
    row.reason = suggestion.reason
    row.score = suggestion.score
    row.status = suggestion.status.value
    row.metadata_json = dict(suggestion.metadata)
    row.created_at = suggestion.created_at
    row.updated_at = suggestion.updated_at
    row.reviewed_at = suggestion.reviewed_at
    row.review_reason = suggestion.review_reason


def context_link_suggestion_row_to_domain(
    row: MemoryContextLinkSuggestionRow,
) -> MemoryContextLinkSuggestion:
    return MemoryContextLinkSuggestion(
        id=MemoryContextLinkSuggestionId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        source_type=row.source_type,
        source_id=row.source_id,
        target_type=row.target_type,
        target_id=row.target_id,
        relation_type=row.relation_type,
        confidence=row.confidence,
        reason=row.reason,
        score=float(row.score),
        status=ContextLinkSuggestionStatus(row.status),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reviewed_at=row.reviewed_at,
        review_reason=row.review_reason,
    )
