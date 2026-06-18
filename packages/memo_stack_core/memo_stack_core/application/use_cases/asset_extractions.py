"""Asset extraction orchestration use cases."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime, timedelta
from hashlib import sha256

from memo_stack_core.application.asset_extraction_mapping import (
    ASSET_EXTRACTION_SOURCE_TYPE,
    artifact_storage_key,
    asset_extraction_chunk_metadata,
    extracted_text,
    result_json,
)
from memo_stack_core.application.dto import (
    AssetExtractionResult,
    AssetExtractionsResult,
    CancelAssetExtractionCommand,
    ExtractionArtifactBytesResult,
    GetAssetExtractionQuery,
    GetExtractionArtifactQuery,
    IngestDocumentCommand,
    ListAssetExtractionsQuery,
    RequestAssetExtractionCommand,
    RetryAssetExtractionCommand,
    RunAssetExtractionCommand,
)
from memo_stack_core.application.multimodal_manifest import (
    multimodal_manifest_artifact_candidate,
    should_store_generic_multimodal_manifest,
)
from memo_stack_core.application.normalize import content_hash
from memo_stack_core.application.safe_payload import safe_metadata, safe_metadata_text
from memo_stack_core.application.use_cases.asset_extraction_support import (
    NON_RUNNABLE_EXTRACTION_STATUSES,
    ActiveAssetExtractionLeaseError,
    DeferredAssetExtractionRetryError,
    ExtractionRetryPolicy,
    actual_media_analysis_seconds,
    asset_extract_event,
    estimated_media_analysis_seconds,
    indexing_status,
    is_non_runnable_extraction_job,
    parser_config_hash,
    positive_int,
    safe_error_text,
    safe_exception_code,
    safe_exception_message,
    usage_idempotency_key,
    usage_reconciliation_idempotency_key,
)
from memo_stack_core.domain.assets import AssetStatus, MemoryAsset
from memo_stack_core.domain.errors import (
    MemoryInfrastructureError,
    MemoryNotFoundError,
    MemoryQuotaExceededError,
    MemoryValidationError,
)
from memo_stack_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    AssetExtractionStatus,
    ExtractionArtifact,
    ExtractionArtifactId,
    ExtractionRetryDisposition,
)
from memo_stack_core.domain.usage import (
    USAGE_RECONCILIATION_SOURCE_TYPE,
    ProductPlan,
    UsageRecord,
    UsageRecordId,
    UsageResource,
    UsageSubjectType,
    UsageWindow,
    admit_usage,
)
from memo_stack_core.ports.assets import BlobStoragePort
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.extraction import (
    ContentExtractionPort,
    ExtractionArtifactCandidate,
    ExtractionLimits,
    ExtractionRequest,
    ExtractionResult,
    FileTypeDetectionRequest,
    FileTypeDetectorPort,
)
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MIN_ARTIFACT_BYTE_LIMIT = 16_384
_MAX_ARTIFACT_BYTE_LIMIT = 5_000_000
_ARTIFACT_PREVIEW_CHARS = 1_000


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
        return AssetExtractionResult(job=saved, indexing_status="pending")


class GetAssetExtractionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetAssetExtractionQuery) -> AssetExtractionResult:
        async with self._uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(query.job_id)
            if job is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            artifacts = await uow.asset_extractions.list_artifacts(job_id=str(job.id))
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
            await uow.outbox.enqueue(asset_extract_event(saved))
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
        retry_policy: ExtractionRetryPolicy | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage
        self._detector = detector
        self._extractor = extractor
        self._ingest_document = ingest_document
        self._clock = clock
        self._ids = ids
        self._limits = limits
        self._artifact_storage_backend = artifact_storage_backend
        self._execution_lease = timedelta(seconds=max(30, execution_lease_seconds))
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

        try:
            content = await self._blob_storage.read_bytes(storage_key=asset.storage_key)
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
            job = await self._save_progress(
                job,
                stage="extracting_content",
                percent=45,
                message="Extracting searchable content",
            )
            job = await self._cancel_if_requested(job)
            if job.status == AssetExtractionStatus.CANCELED:
                return AssetExtractionResult(job=job, indexing_status="canceled")
            result = await self._extractor.extract(
                ExtractionRequest(
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
                )
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

            extracted_text_value = extracted_text(result)
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
            job = await self._save_progress(
                job,
                stage="indexing_memory",
                percent=90,
                message="Indexing extracted memory",
            )
            succeeded = await self._mark_succeeded(
                await self._reconcile_media_usage(job, result=result),
                result=result,
                result_document_ids=(str(ingest.document.id),),
            )
            return AssetExtractionResult(
                job=succeeded,
                artifacts=tuple(artifacts),
                indexing_status=ingest.indexing_status,
            )
        except Exception as exc:
            failed = await self._mark_failed_unless_terminal(job, exc)
            if failed.retry_disposition == ExtractionRetryDisposition.PERMANENT:
                return AssetExtractionResult(job=failed, indexing_status="failed")
            if isinstance(exc, MemoryInfrastructureError):
                raise
            raise MemoryInfrastructureError("Asset extraction failed") from exc

    async def _mark_running(self, command: RunAssetExtractionCommand) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            job = await uow.asset_extractions.get_by_id(command.job_id)
            if job is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            if job.status in NON_RUNNABLE_EXTRACTION_STATUSES:
                return job
            now = self._clock.now()
            if job.status == AssetExtractionStatus.FAILED:
                if job.retry_disposition == ExtractionRetryDisposition.PERMANENT:
                    return job
                if (
                    job.retry_after_at is not None
                    and _datetime_after(job.retry_after_at, now)
                    and not command.force
                ):
                    raise DeferredAssetExtractionRetryError(
                        job_id=str(job.id),
                        retry_after_at=job.retry_after_at,
                    )
            if job.status == AssetExtractionStatus.RUNNING:
                if job.cancellation_requested_at is not None:
                    return job
                if job.lease_expires_at is None and not command.force:
                    raise ActiveAssetExtractionLeaseError(
                        job_id=str(job.id),
                        lease_owner=job.lease_owner,
                        retry_after_at=None,
                    )
                if job.lease_expires_at is not None and _datetime_after(
                    job.lease_expires_at,
                    now,
                ):
                    raise ActiveAssetExtractionLeaseError(
                        job_id=str(job.id),
                        lease_owner=job.lease_owner,
                        retry_after_at=job.lease_expires_at,
                    )
            running = job.mark_running(
                now=now,
                lease_owner=command.worker_id or f"asset-extraction:{command.job_id}",
                lease_expires_at=now + self._execution_lease,
            )
            running = running.with_metadata_updates(
                now=now,
                metadata={
                    "processing_stage": "reading_asset",
                    "progress_percent": 10,
                    "progress_message": "Reading uploaded asset",
                    "execution_lease_seconds": int(self._execution_lease.total_seconds()),
                },
            )
            saved = await uow.asset_extractions.save(running)
            await uow.commit()
        return saved

    async def _save_progress(
        self,
        job: AssetExtractionJob,
        *,
        stage: str,
        percent: int,
        message: str,
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            if current.status != AssetExtractionStatus.RUNNING:
                return current
            now = self._clock.now()
            updated = current.record_heartbeat(
                now=now,
                lease_expires_at=now + self._execution_lease,
                metadata={
                    "processing_stage": stage,
                    "progress_percent": max(0, min(percent, 99)),
                    "progress_message": message,
                },
            )
            saved = await uow.asset_extractions.save(updated)
            await uow.commit()
        return saved

    async def _cancel_if_requested(self, job: AssetExtractionJob) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            if current.cancellation_requested_at is None:
                return current
            canceled = current.mark_canceled(
                now=self._clock.now(),
                code="asset_extraction.canceled",
                message="Extraction was canceled by request",
            )
            saved = await uow.asset_extractions.save(canceled)
            await uow.commit()
        return saved

    async def _acknowledge_cancel_after_document_commit(
        self,
        job: AssetExtractionJob,
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            if (
                current.status != AssetExtractionStatus.RUNNING
                or current.cancellation_requested_at is None
            ):
                return current
            updated = current.with_metadata_updates(
                now=self._clock.now(),
                metadata={
                    "cancellation_status": "ignored_after_document_commit",
                    "cancellation_message": (
                        "Cancellation requested after canonical document commit; "
                        "finalizing extraction to keep evidence consistent"
                    ),
                },
            )
            saved = await uow.asset_extractions.save(updated)
            await uow.commit()
        return saved

    async def _store_artifacts(
        self,
        *,
        asset: MemoryAsset,
        job: AssetExtractionJob,
        result: ExtractionResult,
        markdown: str,
    ) -> list[ExtractionArtifact]:
        candidates = [
            ExtractionArtifactCandidate(
                artifact_type="markdown",
                filename="extracted.md",
                content_type="text/markdown",
                content=markdown.encode("utf-8"),
                metadata={"parser": result.parser_name},
            ),
            ExtractionArtifactCandidate(
                artifact_type="extracted_json",
                filename="extracted.json",
                content_type="application/json",
                content=result_json(result).encode("utf-8"),
                metadata={"parser": result.parser_name},
            ),
        ]
        if should_store_generic_multimodal_manifest(result):
            candidates.append(
                multimodal_manifest_artifact_candidate(asset=asset, job=job, result=result)
            )
        candidates.extend(result.artifacts)
        byte_limit = _artifact_byte_limit(self._limits)
        stored: list[ExtractionArtifact] = []
        written_storage_keys: list[str] = []
        now = self._clock.now()
        try:
            for raw_candidate in candidates:
                candidate = _bounded_artifact_candidate(
                    raw_candidate,
                    byte_limit=byte_limit,
                )
                if not candidate.content:
                    continue
                digest = sha256(candidate.content).hexdigest()
                artifact = ExtractionArtifact.create(
                    artifact_id=ExtractionArtifactId(self._ids.new_id("artifact")),
                    job_id=job.id,
                    asset_id=job.asset_id,
                    artifact_type=candidate.artifact_type,
                    storage_backend=self._artifact_storage_backend,
                    storage_key=artifact_storage_key(
                        space_id=str(job.space_id),
                        memory_scope_id=str(job.memory_scope_id),
                        job_id=str(job.id),
                        digest=digest,
                        filename=candidate.filename,
                    ),
                    sha256_hex=digest,
                    byte_size=len(candidate.content),
                    now=now,
                    metadata={
                        "content_type": safe_metadata_text(candidate.content_type),
                        "filename": safe_metadata_text(candidate.filename),
                        "artifact_byte_limit": byte_limit,
                        **safe_metadata(candidate.metadata),
                    },
                )
                await self._blob_storage.write_bytes(
                    storage_key=artifact.storage_key,
                    content=candidate.content,
                )
                written_storage_keys.append(artifact.storage_key)
                stored.append(artifact)
            if stored:
                async with self._uow_factory() as uow:
                    persisted = []
                    for artifact in stored:
                        persisted.append(await uow.asset_extractions.create_artifact(artifact))
                    await uow.commit()
                return persisted
            return []
        except Exception:
            for storage_key in written_storage_keys:
                with suppress(Exception):
                    await self._blob_storage.delete(storage_key=storage_key)
            raise

    async def _mark_succeeded(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
        result_document_ids: tuple[str, ...],
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            if current.status != AssetExtractionStatus.RUNNING:
                now = self._clock.now()
                current = current.mark_running(
                    now=now,
                    lease_owner=f"asset-extraction:{job.id}",
                    lease_expires_at=now + self._execution_lease,
                )
            succeeded = current.mark_succeeded(
                now=self._clock.now(),
                result_document_ids=result_document_ids,
                parser_name=safe_metadata_text(result.parser_name),
                parser_version=safe_metadata_text(result.parser_version)
                if result.parser_version
                else None,
                model_version=safe_metadata_text(result.model_version)
                if result.model_version
                else None,
                metadata={
                    "normalized_content_type": safe_metadata_text(result.normalized_content_type),
                    "language": safe_metadata_text(result.language) if result.language else None,
                    "element_count": len(result.elements),
                    **safe_metadata(result.technical_metadata),
                },
            )
            saved = await uow.asset_extractions.save(succeeded)
            await uow.commit()
        return saved

    async def _reconcile_media_usage(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
    ) -> AssetExtractionJob:
        actual_seconds = actual_media_analysis_seconds(result)
        if actual_seconds is None:
            return job
        reserved_seconds = positive_int(job.metadata.get("usage_media_analysis_seconds_requested"))
        if reserved_seconds is None or reserved_seconds <= 0:
            return job
        desired_delta = actual_seconds - reserved_seconds
        reconciliation_metadata = {
            "usage_media_analysis_seconds_actual": actual_seconds,
            "usage_media_analysis_seconds_delta": desired_delta,
            "usage_media_analysis_seconds_final": actual_seconds,
            "usage_reconciled": True,
        }

        window = UsageWindow.calendar_month_for(self._clock.now())
        key = usage_reconciliation_idempotency_key(
            job_id=str(job.id),
            actual_seconds=actual_seconds,
        )
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            existing_adjustments = await uow.usage.list_for_source(
                source_type=USAGE_RECONCILIATION_SOURCE_TYPE,
                source_id=str(current.id),
                resource=UsageResource.MEDIA_ANALYSIS_SECONDS.value,
            )
            already_recorded_delta = sum(record.quantity for record in existing_adjustments)
            delta_to_record = desired_delta - already_recorded_delta
            existing = await uow.usage.find_by_idempotency_key(key)
            if delta_to_record != 0 and existing is None:
                await uow.usage.create(
                    UsageRecord.create(
                        record_id=UsageRecordId(self._ids.new_id("usage")),
                        subject_type=UsageSubjectType.SPACE.value,
                        subject_id=str(current.space_id),
                        space_id=current.space_id,
                        memory_scope_id=current.memory_scope_id,
                        resource=UsageResource.MEDIA_ANALYSIS_SECONDS.value,
                        quantity=delta_to_record,
                        source_type=USAGE_RECONCILIATION_SOURCE_TYPE,
                        source_id=str(current.id),
                        idempotency_key=key,
                        window=window,
                        now=self._clock.now(),
                        metadata={
                            "reserved_seconds": reserved_seconds,
                            "actual_seconds": actual_seconds,
                            "desired_delta_seconds": desired_delta,
                            "delta_seconds": delta_to_record,
                            "parser_profile": current.parser_profile,
                            "result_content_type": result.normalized_content_type,
                        },
                    )
                )
            updated = current.with_metadata_updates(
                now=self._clock.now(),
                metadata=reconciliation_metadata,
            )
            saved = await uow.asset_extractions.save(updated)
            await uow.commit()
        return saved

    async def _update_job_metadata(
        self,
        job: AssetExtractionJob,
        *,
        metadata: dict[str, object],
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            updated = current.with_metadata_updates(now=self._clock.now(), metadata=metadata)
            saved = await uow.asset_extractions.save(updated)
            await uow.commit()
        return saved

    async def _mark_unsupported(
        self,
        job: AssetExtractionJob,
        *,
        result: ExtractionResult,
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            unsupported = current.mark_unsupported(
                now=self._clock.now(),
                code=result.safe_error_code or "asset_extraction.unsupported",
                message=safe_error_text(result.safe_error_message or "Asset type is unsupported"),
                metadata={
                    "normalized_content_type": safe_metadata_text(result.normalized_content_type),
                    **safe_metadata(result.technical_metadata),
                },
            )
            saved = await uow.asset_extractions.save(unsupported)
            await uow.commit()
        return saved

    async def _mark_failed(
        self,
        job: AssetExtractionJob,
        *,
        code: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> AssetExtractionJob:
        async with self._uow_factory() as uow:
            current = await uow.asset_extractions.get_by_id(str(job.id))
            if current is None:
                raise MemoryNotFoundError("Asset extraction job not found")
            now = self._clock.now()
            policy_retry_disposition = self._retry_policy.disposition_for_code(code)
            retry_after_at = self._retry_policy.retry_after(
                now=now,
                attempt_count=current.attempt_count,
                code=code,
            )
            retry_exhausted = (
                policy_retry_disposition == ExtractionRetryDisposition.RETRYABLE
                and retry_after_at is None
                and current.attempt_count >= self._retry_policy.max_attempts
            )
            retry_disposition = (
                ExtractionRetryDisposition.PERMANENT
                if retry_exhausted
                else policy_retry_disposition
            )
            retry_metadata = {
                "retry_disposition": retry_disposition.value,
                "retry_after_at": retry_after_at.isoformat() if retry_after_at else None,
                "retry_max_attempts": self._retry_policy.max_attempts,
                **({"retry_exhausted": True} if retry_exhausted else {}),
            }
            failed = current.mark_failed(
                now=now,
                code=code,
                message=safe_error_text(message),
                metadata={**safe_metadata(metadata or {}), **retry_metadata},
                retry_disposition=retry_disposition,
                retry_after_at=retry_after_at,
            )
            saved = await uow.asset_extractions.save(failed)
            await uow.commit()
        return saved

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


def _datetime_after(value: datetime, reference: datetime) -> bool:
    if value.tzinfo is None and reference.tzinfo is not None:
        value = value.replace(tzinfo=reference.tzinfo)
    elif value.tzinfo is not None and reference.tzinfo is None:
        value = value.replace(tzinfo=None)
    return value > reference


def _artifact_byte_limit(limits: ExtractionLimits) -> int:
    requested = max(1, int(limits.max_output_chars)) * 4
    return min(max(requested, _MIN_ARTIFACT_BYTE_LIMIT), _MAX_ARTIFACT_BYTE_LIMIT)


def _bounded_artifact_candidate(
    candidate: ExtractionArtifactCandidate,
    *,
    byte_limit: int,
) -> ExtractionArtifactCandidate:
    if len(candidate.content) <= byte_limit:
        return candidate
    original_size = len(candidate.content)
    return ExtractionArtifactCandidate(
        artifact_type=candidate.artifact_type,
        filename=_truncated_artifact_filename(candidate.filename),
        content_type="application/json",
        content=_artifact_summary_bytes(
            candidate,
            original_size=original_size,
            byte_limit=byte_limit,
        ),
        metadata={
            **candidate.metadata,
            "artifact_truncated": True,
            "artifact_original_byte_size": original_size,
            "artifact_original_content_type": candidate.content_type,
            "artifact_original_filename": candidate.filename,
        },
    )


def _artifact_summary_bytes(
    candidate: ExtractionArtifactCandidate,
    *,
    original_size: int,
    byte_limit: int,
) -> bytes:
    preview = safe_metadata_text(
        candidate.content[: min(original_size, _ARTIFACT_PREVIEW_CHARS * 4)].decode(
            "utf-8",
            errors="replace",
        ),
        limit=_ARTIFACT_PREVIEW_CHARS,
    )
    payload = {
        "truncated": True,
        "reason": "artifact_byte_limit",
        "original_byte_size": original_size,
        "byte_limit": byte_limit,
        "original_filename": safe_metadata_text(candidate.filename),
        "original_content_type": safe_metadata_text(candidate.content_type),
        "preview": preview,
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(content) <= byte_limit:
        return content
    payload["preview"] = ""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _truncated_artifact_filename(filename: str) -> str:
    safe_name = filename.strip() or "artifact"
    if safe_name.endswith(".truncated.json"):
        return safe_name
    return f"{safe_name}.truncated.json"
