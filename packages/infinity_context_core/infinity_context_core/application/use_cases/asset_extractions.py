"""Asset extraction orchestration use cases."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta

from infinity_context_core.application.asset_extraction_mapping import (
    ASSET_EXTRACTION_SOURCE_TYPE,
    asset_extraction_chunk_metadata,
    extracted_text,
)
from infinity_context_core.application.asset_upload_policy import (
    assess_asset_upload,
    detect_magic_content_type,
)
from infinity_context_core.application.dto import (
    AssetExtractionResult,
    AssetExtractionsResult,
    CancelAssetExtractionCommand,
    DeduplicationInfo,
    ExtractionArtifactBytesResult,
    GetAssetExtractionQuery,
    GetExtractionArtifactQuery,
    IngestDocumentCommand,
    ListAssetExtractionsQuery,
    RequestAssetExtractionCommand,
    RetryAssetExtractionCommand,
    RunAssetExtractionCommand,
)
from infinity_context_core.application.extraction_resource_policy import (
    assess_extraction_archive_resource_limits,
    assess_extraction_resource_limits,
    assess_extraction_result_resource_limits,
    extraction_limits_metadata,
    normalize_extraction_limits,
)
from infinity_context_core.application.normalize import content_hash
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.application.use_cases.asset_extraction_artifacts import (
    _artifact_byte_limit,  # noqa: F401 - retain the original helper import path.
    _artifact_summary_bytes,  # noqa: F401 - retain the original helper import path.
    _bounded_artifact_candidate,  # noqa: F401 - retain the original helper import path.
    _truncated_artifact_filename,  # noqa: F401 - retain the original helper import path.
    store_artifacts,
)
from infinity_context_core.application.use_cases.asset_extraction_lifecycle import (
    acknowledge_cancel_after_document_commit,
    cancel_if_requested,
    get_current_job,
    mark_failed,
    mark_running,
    mark_succeeded,
    mark_unsupported,
    save_progress,
    update_job_metadata,
)
from infinity_context_core.application.use_cases.asset_extraction_result_policy import (
    _append_limit_applied,  # noqa: F401 - retain the original helper import path.
    _apply_extracted_text_limit,
    _file_type_detection_metadata,
    _resource_limit_result,
    _upload_policy_rejection_result,
    _upload_policy_revalidation_metadata,
)
from infinity_context_core.application.use_cases.asset_extraction_support import (
    AssetExtractionParserTimeoutError,
    ExtractionRetryPolicy,
    asset_extract_event,
    estimated_media_analysis_seconds,
    indexing_status,
    is_non_runnable_extraction_job,
    parser_config_hash,
    safe_exception_code,
    safe_exception_message,
    usage_idempotency_key,
)
from infinity_context_core.application.use_cases.asset_extraction_support import (
    datetime_after as _datetime_after,
)
from infinity_context_core.application.use_cases.asset_extraction_usage import (
    reconcile_media_usage,
)
from infinity_context_core.domain.assets import AssetStatus, MemoryAsset
from infinity_context_core.domain.errors import (
    MemoryInfrastructureError,
    MemoryIngressLimitError,
    MemoryNotFoundError,
    MemoryQuotaExceededError,
    MemoryValidationError,
)
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    AssetExtractionStatus,
    ExtractionArtifact,
    ExtractionRetryDisposition,
)
from infinity_context_core.domain.usage import (
    ProductPlan,
    UsageRecord,
    UsageRecordId,
    UsageResource,
    UsageSubjectType,
    UsageWindow,
    admit_usage,
)
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.extraction import (
    ContentExtractionPort,
    ExtractionLimits,
    ExtractionRequest,
    ExtractionResult,
    FileTypeDetectionRequest,
    FileTypeDetectorPort,
)
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


class RequestAssetExtractionUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        plan: ProductPlan,
        default_parser_profile: str = "standard_local",
        default_unknown_media_seconds: int = 600,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._plan = plan
        self._default_parser_profile = default_parser_profile
        self._default_unknown_media_seconds = max(1, default_unknown_media_seconds)

    async def execute(self, command: RequestAssetExtractionCommand) -> AssetExtractionResult:
        parser_profile = (command.parser_profile or self._default_parser_profile).strip()
        if not parser_profile:
            raise MemoryValidationError("Parser profile is required")
        parser_config_hash_value = parser_config_hash(parser_profile)
        async with self._uow_factory() as uow:
            asset = await uow.assets.get_by_id(command.asset_id)
            if asset is None or asset.status != AssetStatus.STORED:
                raise MemoryNotFoundError("Asset not found")
            existing = await uow.asset_extractions.find_active_for_asset_profile(
                asset_id=str(asset.id),
                parser_profile=parser_profile,
                parser_config_hash=parser_config_hash_value,
                source_sha256_hex=asset.sha256_hex,
            )
            if existing is not None:
                artifacts = await uow.asset_extractions.list_artifacts(job_id=str(existing.id))
                return AssetExtractionResult(
                    job=existing,
                    artifacts=tuple(artifacts),
                    duplicate=True,
                    indexing_status=indexing_status(existing.status),
                    deduplication=DeduplicationInfo(
                        duplicate=True,
                        status="active_job_match",
                        reason_code="asset_extraction_dedup.active_job_match",
                        scope="asset",
                        duplicate_of_job_id=str(existing.id),
                        storage_key_reused=None,
                        blob_written=False,
                        artifact_count=len(artifacts),
                    ),
                )
            reusable = await uow.asset_extractions.find_reusable_succeeded_for_scope_source(
                space_id=str(asset.space_id),
                memory_scope_id=str(asset.memory_scope_id),
                asset_id=str(asset.id),
                parser_profile=parser_profile,
                parser_config_hash=parser_config_hash_value,
                source_sha256_hex=asset.sha256_hex,
            )
            if reusable is not None:
                now = self._clock.now()
                source_artifacts = await uow.asset_extractions.list_artifacts(
                    job_id=str(reusable.id)
                )
                job = AssetExtractionJob.create(
                    job_id=AssetExtractionJobId(self._ids.new_id("extract")),
                    asset_id=asset.id,
                    space_id=asset.space_id,
                    memory_scope_id=asset.memory_scope_id,
                    thread_id=asset.thread_id,
                    parser_profile=parser_profile,
                    parser_config_hash=parser_config_hash_value,
                    source_sha256_hex=asset.sha256_hex,
                    now=now,
                    metadata={
                        "filename": asset.filename,
                        "content_type": asset.content_type,
                        "usage_plan_tier": self._plan.tier.value,
                        "usage_media_analysis_seconds_requested": 0,
                    },
                ).mark_reused(
                    now=now,
                    source_job_id=str(reusable.id),
                    source_asset_id=str(reusable.asset_id),
                    source_artifact_count=len(source_artifacts),
                    result_document_ids=reusable.result_document_ids,
                    parser_name=reusable.parser_name or "asset-extraction-reuse",
                    parser_version=reusable.parser_version,
                    model_version=reusable.model_version,
                    metadata={
                        "source_parser_profile": reusable.parser_profile,
                        "source_parser_config_hash": reusable.parser_config_hash,
                    },
                )
                saved = await uow.asset_extractions.create(job)
                await uow.commit()
                return AssetExtractionResult(
                    job=saved,
                    artifacts=tuple(source_artifacts),
                    duplicate=True,
                    indexing_status=indexing_status(saved.status),
                    deduplication=DeduplicationInfo(
                        duplicate=True,
                        status="source_job_reused",
                        reason_code="asset_extraction_dedup.source_job_reused",
                        scope="memory_scope",
                        duplicate_of_asset_id=str(reusable.asset_id),
                        duplicate_of_job_id=str(reusable.id),
                        blob_written=False,
                        artifact_count=len(source_artifacts),
                    ),
                )

            now = self._clock.now()
            window = UsageWindow.calendar_month_for(now)
            estimated_media_seconds = estimated_media_analysis_seconds(
                asset,
                default_unknown_media_seconds=self._default_unknown_media_seconds,
            )
            usage_decision = None
            if estimated_media_seconds > 0:
                used = await uow.usage.sum_quantity(
                    subject_type=UsageSubjectType.SPACE.value,
                    subject_id=str(asset.space_id),
                    resource=UsageResource.MEDIA_ANALYSIS_SECONDS.value,
                    window_start=window.start,
                    window_end=window.end,
                )
                usage_decision = admit_usage(
                    plan=self._plan,
                    resource=UsageResource.MEDIA_ANALYSIS_SECONDS,
                    used=used,
                    requested=estimated_media_seconds,
                    window=window,
                )
                if not usage_decision.allowed:
                    raise MemoryQuotaExceededError("Media analysis monthly quota would be exceeded")
            job = AssetExtractionJob.create(
                job_id=AssetExtractionJobId(self._ids.new_id("extract")),
                asset_id=asset.id,
                space_id=asset.space_id,
                memory_scope_id=asset.memory_scope_id,
                thread_id=asset.thread_id,
                parser_profile=parser_profile,
                parser_config_hash=parser_config_hash_value,
                source_sha256_hex=asset.sha256_hex,
                now=now,
                metadata={
                    "filename": asset.filename,
                    "content_type": asset.content_type,
                    "processing_stage": "queued",
                    "progress_percent": 0,
                    "progress_message": "Waiting for extraction worker",
                    "usage_plan_tier": self._plan.tier.value,
                    "usage_media_analysis_seconds_requested": estimated_media_seconds,
                    "usage_media_analysis_seconds_limit": (
                        self._plan.media_analysis_seconds_per_month
                    ),
                    "usage_window_start": window.start.isoformat(),
                    "usage_window_end": window.end.isoformat(),
                    **(
                        {
                            "usage_media_analysis_seconds_used": (usage_decision.snapshot.used),
                            "usage_media_analysis_seconds_remaining": (
                                usage_decision.snapshot.remaining
                            ),
                        }
                        if usage_decision is not None
                        else {}
                    ),
                },
            )
            saved = await uow.asset_extractions.create(job)
            if estimated_media_seconds > 0:
                usage_key = usage_idempotency_key(
                    asset_id=str(asset.id),
                    parser_profile=parser_profile,
                    parser_config_hash=parser_config_hash_value,
                    source_sha256_hex=asset.sha256_hex,
                )
                existing_usage = await uow.usage.find_by_idempotency_key(usage_key)
                if existing_usage is None:
                    await uow.usage.create(
                        UsageRecord.create(
                            record_id=UsageRecordId(self._ids.new_id("usage")),
                            subject_type=UsageSubjectType.SPACE.value,
                            subject_id=str(asset.space_id),
                            space_id=asset.space_id,
                            memory_scope_id=asset.memory_scope_id,
                            resource=UsageResource.MEDIA_ANALYSIS_SECONDS.value,
                            quantity=estimated_media_seconds,
                            source_type="asset_extraction",
                            source_id=str(saved.id),
                            idempotency_key=usage_key,
                            window=window,
                            now=now,
                            metadata={
                                "asset_id": str(asset.id),
                                "parser_profile": parser_profile,
                                "filename": asset.filename,
                                "content_type": asset.content_type,
                            },
                        )
                    )
            await uow.outbox.enqueue(asset_extract_event(saved))
            await uow.commit()
        return AssetExtractionResult(
            job=saved,
            indexing_status="pending",
            deduplication=DeduplicationInfo(
                duplicate=False,
                status="new_job_queued",
                reason_code="asset_extraction_dedup.new_job_queued",
                scope="none",
                blob_written=False,
            ),
        )


class GetAssetExtractionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetAssetExtractionQuery) -> AssetExtractionResult:
        async with self._uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(query.job_id)
            if job is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            artifacts = await uow.asset_extractions.list_artifacts(job_id=str(job.id))
            if not artifacts:
                reused_from_job_id = _metadata_text(job.metadata, "reused_from_job_id")
                if reused_from_job_id:
                    artifacts = await uow.asset_extractions.list_artifacts(
                        job_id=reused_from_job_id
                    )
        return AssetExtractionResult(
            job=job,
            artifacts=tuple(artifacts),
            indexing_status=indexing_status(job.status),
        )


class ListAssetExtractionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListAssetExtractionsQuery) -> AssetExtractionsResult:
        async with self._uow_factory() as uow:
            if query.asset_id:
                jobs = await uow.asset_extractions.list_for_asset(
                    asset_id=query.asset_id,
                    status=query.status,
                    limit=query.limit,
                    cursor_created_at=query.cursor_created_at,
                    cursor_id=query.cursor_id,
                )
            elif query.space_id and query.memory_scope_id:
                jobs = await uow.asset_extractions.list_for_scope(
                    space_id=str(query.space_id),
                    memory_scope_id=str(query.memory_scope_id),
                    thread_id=str(query.thread_id) if query.thread_id else None,
                    status=query.status,
                    limit=query.limit,
                    cursor_created_at=query.cursor_created_at,
                    cursor_id=query.cursor_id,
                )
            else:
                raise MemoryValidationError("asset_id or space_id and memory_scope_id are required")
        return AssetExtractionsResult(jobs=tuple(jobs))


class ReadExtractionArtifactBytesUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        blob_storage: BlobStoragePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage

    async def execute(self, query: GetExtractionArtifactQuery) -> ExtractionArtifactBytesResult:
        async with self._uow_factory() as uow:
            artifact = await uow.asset_extractions.get_artifact_by_id(query.artifact_id)
        if artifact is None:
            raise MemoryNotFoundError("Extraction artifact not found")
        content = await self._blob_storage.read_bytes(storage_key=artifact.storage_key)
        return ExtractionArtifactBytesResult(artifact=artifact, content=content)


class RetryAssetExtractionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RetryAssetExtractionCommand) -> AssetExtractionResult:
        async with self._uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(command.job_id)
            if job is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            retried = job.reset_for_retry(now=self._clock.now())
            saved = await uow.asset_extractions.save(retried)
            await uow.outbox.enqueue_or_reschedule(asset_extract_event(saved))
            await uow.commit()
        return AssetExtractionResult(job=saved, indexing_status="pending")


class CancelAssetExtractionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: CancelAssetExtractionCommand) -> AssetExtractionResult:
        async with self._uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(command.job_id)
            if job is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            canceled = job.request_cancellation(now=self._clock.now())
            saved = await uow.asset_extractions.save(canceled)
            await uow.commit()
        return AssetExtractionResult(job=saved, indexing_status=indexing_status(saved.status))


class RunAssetExtractionUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        blob_storage: BlobStoragePort,
        detector: FileTypeDetectorPort,
        extractor: ContentExtractionPort,
        ingest_document,
        clock: ClockPort,
        ids: IdGeneratorPort,
        limits: ExtractionLimits,
        artifact_storage_backend: str = "local",
        execution_lease_seconds: int = 900,
        cancellation_poll_seconds: float = 1.0,
        heartbeat_seconds: float = 15.0,
        retry_policy: ExtractionRetryPolicy | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage
        self._detector = detector
        self._extractor = extractor
        self._ingest_document = ingest_document
        self._clock = clock
        self._ids = ids
        self._limits_metadata = extraction_limits_metadata(limits)
        self._limits = normalize_extraction_limits(limits)
        self._artifact_storage_backend = artifact_storage_backend
        self._execution_lease = timedelta(seconds=max(30, execution_lease_seconds))
        self._cancellation_poll_seconds = max(0.05, float(cancellation_poll_seconds))
        self._heartbeat_interval = timedelta(
            seconds=max(self._cancellation_poll_seconds, float(heartbeat_seconds))
        )
        self._retry_policy = retry_policy or ExtractionRetryPolicy()

    async def execute(self, command: RunAssetExtractionCommand) -> AssetExtractionResult:
        job = await self._mark_running(command)
        if is_non_runnable_extraction_job(job):
            async with self._uow_factory() as uow:
                artifacts = await uow.asset_extractions.list_artifacts(job_id=str(job.id))
            return AssetExtractionResult(
                job=job,
                artifacts=tuple(artifacts),
                indexing_status=indexing_status(job.status),
            )
        job = await self._cancel_if_requested(job)
        if job.status == AssetExtractionStatus.CANCELED:
            return AssetExtractionResult(job=job, indexing_status="canceled")
        async with self._uow_factory() as uow:
            asset = await uow.assets.get_by_id(str(job.asset_id))
        if asset is None or asset.status != AssetStatus.STORED:
            failed = await self._mark_failed(
                job,
                code="asset_extraction.asset_missing",
                message="Asset is missing or unavailable",
            )
            return AssetExtractionResult(job=failed, indexing_status="failed")
        resource_decision = assess_extraction_resource_limits(
            asset_byte_size=asset.byte_size,
            limits=self._limits,
        )
        if not resource_decision.allowed:
            unsupported = await self._mark_unsupported(
                job,
                result=_resource_limit_result(
                    asset=asset,
                    code=resource_decision.code,
                    message=resource_decision.message,
                    metadata={**resource_decision.metadata, **self._limits_metadata},
                ),
            )
            return AssetExtractionResult(job=unsupported, indexing_status="unsupported")

        try:
            content = await self._blob_storage.read_bytes(storage_key=asset.storage_key)
            resource_decision = assess_extraction_resource_limits(
                asset_byte_size=len(content),
                limits=self._limits,
                byte_size_source="blob_content_length",
            )
            if not resource_decision.allowed:
                unsupported = await self._mark_unsupported(
                    job,
                    result=_resource_limit_result(
                        asset=asset,
                        code=resource_decision.code,
                        message=resource_decision.message,
                        metadata={**resource_decision.metadata, **self._limits_metadata},
                    ),
                )
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")
            try:
                upload_assessment = assess_asset_upload(
                    filename=asset.filename,
                    declared_content_type=asset.content_type,
                    content=content,
                    max_image_pixels=self._limits.max_image_pixels,
                )
            except MemoryIngressLimitError as exc:
                unsupported = await self._mark_unsupported(
                    job,
                    result=_upload_policy_rejection_result(
                        asset=asset,
                        content=content,
                        message=str(exc),
                    ),
                )
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")
            job = await self._update_job_metadata(
                job,
                metadata=_upload_policy_revalidation_metadata(upload_assessment.metadata),
            )
            job = await self._save_progress(
                job,
                stage="detecting_type",
                percent=20,
                message="Detecting file type",
            )
            job = await self._cancel_if_requested(job)
            if job.status == AssetExtractionStatus.CANCELED:
                return AssetExtractionResult(job=job, indexing_status="canceled")
            detection = await self._detector.detect(
                FileTypeDetectionRequest(
                    filename=asset.filename,
                    declared_content_type=asset.content_type,
                    content=content,
                )
            )
            job = await self._update_job_metadata(
                job,
                metadata=_file_type_detection_metadata(detection),
            )
            archive_decision = assess_extraction_archive_resource_limits(
                filename=asset.filename,
                declared_content_type=asset.content_type,
                detected_content_type=detection.content_type,
                magic_content_type=detect_magic_content_type(content),
                content=content,
                limits=self._limits,
            )
            job = await self._update_job_metadata(
                job,
                metadata=archive_decision.metadata,
            )
            if not archive_decision.allowed:
                unsupported = await self._mark_unsupported(
                    job,
                    result=_resource_limit_result(
                        asset=asset,
                        code=archive_decision.code,
                        message=archive_decision.message,
                        metadata={**archive_decision.metadata, **self._limits_metadata},
                    ),
                )
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")
            job = await self._save_progress(
                job,
                stage="extracting_content",
                percent=45,
                message="Extracting searchable content",
            )
            job = await self._cancel_if_requested(job)
            if job.status == AssetExtractionStatus.CANCELED:
                return AssetExtractionResult(job=job, indexing_status="canceled")
            job, result = await self._extract_with_supervision(
                job,
                request=ExtractionRequest(
                    job_id=str(job.id),
                    asset_id=str(asset.id),
                    filename=asset.filename,
                    declared_content_type=asset.content_type,
                    detected_content_type=detection.content_type,
                    byte_size=asset.byte_size,
                    sha256_hex=asset.sha256_hex,
                    content=content,
                    parser_profile=job.parser_profile,
                    limits=self._limits,
                ),
            )
            if result is None:
                return AssetExtractionResult(
                    job=job,
                    indexing_status=indexing_status(job.status),
                )
            job = await self._cancel_if_requested(job)
            if job.status == AssetExtractionStatus.CANCELED:
                return AssetExtractionResult(job=job, indexing_status="canceled")

            if result.status == "unsupported":
                job = await self._reconcile_media_usage(job, result=result)
                unsupported = await self._mark_unsupported(job, result=result)
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")
            if result.status != "succeeded":
                failed = await self._mark_failed(
                    job,
                    code=result.safe_error_code or "asset_extraction.invalid_status",
                    message=result.safe_error_message or "Extractor returned invalid status",
                    metadata=result.technical_metadata,
                )
                if failed.retry_disposition == ExtractionRetryDisposition.PERMANENT:
                    return AssetExtractionResult(job=failed, indexing_status="failed")
                raise MemoryInfrastructureError("Asset extraction returned invalid status")

            result_resource_decision = assess_extraction_result_resource_limits(
                result_metadata=result.technical_metadata,
                limits=self._limits,
            )
            if not result_resource_decision.allowed:
                resource_result = _resource_limit_result(
                    asset=asset,
                    code=result_resource_decision.code,
                    message=result_resource_decision.message,
                    metadata={
                        **result_resource_decision.metadata,
                        "parser_name": result.parser_name,
                        "normalized_content_type": result.normalized_content_type,
                    },
                )
                job = await self._reconcile_media_usage(job, result=resource_result)
                unsupported = await self._mark_unsupported(job, result=resource_result)
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")
            result = replace(
                result,
                technical_metadata={
                    **dict(result.technical_metadata),
                    **result_resource_decision.metadata,
                },
            )

            extracted_text_value = extracted_text(result)
            result, extracted_text_value = _apply_extracted_text_limit(
                result=result,
                extracted_text_value=extracted_text_value,
                limits=self._limits,
            )
            if not extracted_text_value.strip():
                job = await self._reconcile_media_usage(job, result=result)
                unsupported = await self._mark_unsupported(
                    job,
                    result=ExtractionResult(
                        status="unsupported",
                        normalized_content_type=result.normalized_content_type,
                        title=result.title,
                        technical_metadata=result.technical_metadata,
                        diagnostics=result.diagnostics,
                        parser_name=result.parser_name,
                        parser_version=result.parser_version,
                        model_version=result.model_version,
                        safe_error_code="asset_extraction.empty_text",
                        safe_error_message="Extractor returned no searchable text",
                    ),
                )
                return AssetExtractionResult(job=unsupported, indexing_status="unsupported")

            ingest = await self._ingest_document.execute(
                IngestDocumentCommand(
                    space_id=asset.space_id,
                    memory_scope_id=asset.memory_scope_id,
                    thread_id=asset.thread_id,
                    title=result.title or asset.filename,
                    source_type=ASSET_EXTRACTION_SOURCE_TYPE,
                    source_external_id=str(job.id),
                    text=extracted_text_value,
                    idempotency_key=(
                        f"asset_extraction:{job.id}:{content_hash(extracted_text_value)}"
                    ),
                    classification=asset.classification,
                    chunk_metadata=asset_extraction_chunk_metadata(
                        asset=asset,
                        job=job,
                        result=result,
                        extracted_text_value=extracted_text_value,
                    ),
                )
            )
            job = await self._save_progress(
                job,
                stage="storing_artifacts",
                percent=80,
                message="Storing extracted evidence",
            )
            job = await self._acknowledge_cancel_after_document_commit(job)
            artifacts = await self._store_artifacts(
                asset=asset,
                job=job,
                result=result,
                markdown=extracted_text_value,
            )
            job = await self._acknowledge_cancel_after_document_commit(job)
            job = await self._save_progress(
                job,
                stage="indexing_memory",
                percent=90,
                message="Indexing extracted memory",
            )
            succeeded = await self._mark_succeeded(
                await self._reconcile_media_usage(job, result=result),
                result=result,
                extracted_text_value=extracted_text_value,
                result_document_ids=(str(ingest.document.id),),
            )
            return AssetExtractionResult(
                job=succeeded,
                artifacts=tuple(artifacts),
                indexing_status=indexing_status(succeeded.status),
            )
        except Exception as exc:
            failed = await self._mark_failed_unless_terminal(job, exc)
            if failed.retry_disposition == ExtractionRetryDisposition.PERMANENT:
                return AssetExtractionResult(
                    job=failed,
                    indexing_status=indexing_status(failed.status),
                )
            if isinstance(exc, MemoryInfrastructureError):
                raise
            raise MemoryInfrastructureError("Asset extraction failed") from exc

    async def _extract_with_supervision(
        self,
        job: AssetExtractionJob,
        *,
        request: ExtractionRequest,
    ) -> tuple[AssetExtractionJob, ExtractionResult | None]:
        task = asyncio.create_task(self._extractor.extract(request))
        last_heartbeat_at = self._clock.now()
        timeout_seconds = max(0.001, float(request.limits.parser_timeout_seconds))
        started_at = self._clock.now()
        try:
            while True:
                now = self._clock.now()
                elapsed_seconds = max(0.0, (now - started_at).total_seconds())
                remaining_seconds = timeout_seconds - elapsed_seconds
                if remaining_seconds <= 0:
                    await self._cancel_supervised_task(task)
                    raise AssetExtractionParserTimeoutError(timeout_seconds=timeout_seconds)
                done, _pending = await asyncio.wait(
                    {task},
                    timeout=min(self._cancellation_poll_seconds, remaining_seconds),
                )
                if task in done:
                    return job, task.result()
                current = await self._get_current_job(str(job.id))
                if current.status != AssetExtractionStatus.RUNNING:
                    await self._cancel_supervised_task(task)
                    return current, None
                if current.cancellation_requested_at is not None:
                    canceled = await self._cancel_if_requested(current)
                    await self._cancel_supervised_task(task)
                    return canceled, None
                if _datetime_after(now, last_heartbeat_at + self._heartbeat_interval):
                    job = await self._save_progress(
                        current,
                        stage="extracting_content",
                        percent=45,
                        message="Extracting searchable content",
                    )
                    last_heartbeat_at = now
                else:
                    job = current
        except asyncio.CancelledError:
            await self._cancel_supervised_task(task)
            raise
        except Exception:
            await self._cancel_supervised_task(task)
            raise

    async def _cancel_supervised_task(self, task: asyncio.Task[ExtractionResult]) -> None:
        if task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _get_current_job(self, job_id: str) -> AssetExtractionJob:
        return await get_current_job(uow_factory=self._uow_factory, job_id=job_id)

    async def _mark_running(self, command: RunAssetExtractionCommand) -> AssetExtractionJob:
        return await mark_running(
            uow_factory=self._uow_factory,
            clock=self._clock,
            execution_lease=self._execution_lease,
            limits_metadata=self._limits_metadata,
            command=command,
        )

    async def _save_progress(
        self,
        job: AssetExtractionJob,
        *,
        stage: str,
        percent: int,
        message: str,
    ) -> AssetExtractionJob:
        return await save_progress(
            uow_factory=self._uow_factory,
            clock=self._clock,
            execution_lease=self._execution_lease,
            job=job,
            stage=stage,
            percent=percent,
            message=message,
        )

    async def _cancel_if_requested(self, job: AssetExtractionJob) -> AssetExtractionJob:
        return await cancel_if_requested(uow_factory=self._uow_factory, clock=self._clock, job=job)

    async def _acknowledge_cancel_after_document_commit(
        self,
        job: AssetExtractionJob,
    ) -> AssetExtractionJob:
        return await acknowledge_cancel_after_document_commit(
            uow_factory=self._uow_factory,
            clock=self._clock,
            job=job,
        )

    async def _store_artifacts(
        self,
        *,
        asset: MemoryAsset,
        job: AssetExtractionJob,
        result: ExtractionResult,
        markdown: str,
    ) -> list[ExtractionArtifact]:
        return await store_artifacts(
            uow_factory=self._uow_factory,
            blob_storage=self._blob_storage,
            clock=self._clock,
            ids=self._ids,
            limits=self._limits,
            artifact_storage_backend=self._artifact_storage_backend,
            asset=asset,
            job=job,
            result=result,
            markdown=markdown,
        )

    async def _mark_succeeded(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
        extracted_text_value: str,
        result_document_ids: tuple[str, ...],
    ) -> AssetExtractionJob:
        return await mark_succeeded(
            uow_factory=self._uow_factory,
            clock=self._clock,
            job=job,
            result=result,
            extracted_text_value=extracted_text_value,
            result_document_ids=result_document_ids,
        )

    async def _reconcile_media_usage(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
    ) -> AssetExtractionJob:
        return await reconcile_media_usage(
            uow_factory=self._uow_factory,
            clock=self._clock,
            ids=self._ids,
            job=job,
            result=result,
        )

    async def _update_job_metadata(
        self,
        job: AssetExtractionJob,
        *,
        metadata: dict[str, object],
    ) -> AssetExtractionJob:
        return await update_job_metadata(
            uow_factory=self._uow_factory,
            clock=self._clock,
            job=job,
            metadata=metadata,
        )

    async def _mark_unsupported(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
    ) -> AssetExtractionJob:
        return await mark_unsupported(
            uow_factory=self._uow_factory,
            clock=self._clock,
            job=job,
            result=result,
        )

    async def _mark_failed(
        self,
        job: AssetExtractionJob,
        *,
        code: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> AssetExtractionJob:
        return await mark_failed(
            uow_factory=self._uow_factory,
            clock=self._clock,
            retry_policy=self._retry_policy,
            job=job,
            code=code,
            message=message,
            metadata=metadata,
        )

    async def _mark_failed_unless_terminal(
        self,
        job: AssetExtractionJob,
        exc: Exception,
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found") from exc
        if current.status in {
            AssetExtractionStatus.SUCCEEDED,
            AssetExtractionStatus.FAILED,
            AssetExtractionStatus.UNSUPPORTED,
            AssetExtractionStatus.CANCELED,
            AssetExtractionStatus.STALE,
        }:
            return current
        return await self._mark_failed(
            current,
            code=safe_exception_code(exc),
            message=safe_exception_message(exc),
        )


def _metadata_text(metadata: object, key: str, *, limit: int = 120) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    safe_value = safe_metadata_text(value, limit=limit).strip()
    return safe_value or None
