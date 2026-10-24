"""Canonical job transitions, each using its own existing transaction boundary."""

from __future__ import annotations

from datetime import timedelta

from infinity_context_core.application.context_link_candidate_policy import (
    source_text_risk_metadata,
)
from infinity_context_core.application.dto import RunAssetExtractionCommand
from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text
from infinity_context_core.application.use_cases.asset_extraction_support import (
    NON_RUNNABLE_EXTRACTION_STATUSES,
    ActiveAssetExtractionLeaseError,
    DeferredAssetExtractionRetryError,
    ExtractionRetryPolicy,
    safe_error_text,
)
from infinity_context_core.application.use_cases.asset_extraction_support import (
    datetime_after as _datetime_after,
)
from infinity_context_core.domain.errors import MemoryNotFoundError
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionStatus,
    ExtractionRetryDisposition,
    extraction_datetime_utc,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.extraction import ExtractionResult
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


async def get_current_job(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    job_id: str,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(job_id)
    if current is None:
        raise MemoryNotFoundError("Asset extraction job not found")
    return current


async def mark_running(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    execution_lease: timedelta,
    limits_metadata: dict[str, object],
    command: RunAssetExtractionCommand,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        job = await uow.asset_extractions.get_by_id(command.job_id)
        if job is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        if job.status in NON_RUNNABLE_EXTRACTION_STATUSES:
            return job
        now = clock.now()
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
            lease_expires_at=now + execution_lease,
        )
        running = running.with_metadata_updates(
            now=now,
            metadata={
                "processing_stage": "reading_asset",
                "progress_percent": 10,
                "progress_message": "Reading uploaded asset",
                "execution_lease_seconds": int(execution_lease.total_seconds()),
                **limits_metadata,
            },
        )
        saved = await uow.asset_extractions.save(running)
        await uow.commit()
    return saved


async def save_progress(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    execution_lease: timedelta,
    job: AssetExtractionJob,
    stage: str,
    percent: int,
    message: str,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        if (
            not current.same_running_attempt(job)
            or current.cancellation_requested_at is not None
        ):
            return current
        now = max(
            extraction_datetime_utc(value)
            for value in (clock.now(), current.updated_at, current.heartbeat_at)
            if value is not None
        )
        expiry = max(
            extraction_datetime_utc(value)
            for value in (now + execution_lease, current.lease_expires_at)
            if value is not None
        )
        updated = current.record_heartbeat(
            now=now,
            lease_expires_at=expiry,
            metadata={
                "processing_stage": stage,
                "progress_percent": max(0, min(percent, 99)),
                "progress_message": message,
            },
        )
        saved = await uow.asset_extractions.save_running_progress(updated, expected=current)
        await uow.commit()
    return saved


async def cancel_if_requested(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    job: AssetExtractionJob,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        if current.cancellation_requested_at is None:
            return current
        canceled = current.mark_canceled(
            now=clock.now(),
            code="asset_extraction.canceled",
            message="Extraction was canceled by request",
        )
        saved = await uow.asset_extractions.save(canceled)
        await uow.commit()
    return saved


async def acknowledge_cancel_after_document_commit(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    job: AssetExtractionJob,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        if (
            current.status != AssetExtractionStatus.RUNNING
            or current.cancellation_requested_at is None
        ):
            return current
        updated = current.with_metadata_updates(
            now=clock.now(),
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


async def mark_succeeded(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    job: AssetExtractionJob,
    result: ExtractionResult,
    extracted_text_value: str,
    result_document_ids: tuple[str, ...],
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        if current.status != AssetExtractionStatus.RUNNING:
            skipped = current.with_metadata_updates(
                now=clock.now(),
                metadata={
                    "success_finalization_status": "skipped_non_running_state",
                    "success_finalization_skipped_status": current.status.value,
                },
            )
            saved = await uow.asset_extractions.save(skipped)
            await uow.commit()
            return saved
        succeeded = current.mark_succeeded(
            now=clock.now(),
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
                **source_text_risk_metadata(extracted_text_value),
            },
        )
        saved = await uow.asset_extractions.save(succeeded)
        await uow.commit()
    return saved


async def update_job_metadata(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    job: AssetExtractionJob,
    metadata: dict[str, object],
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        updated = current.with_metadata_updates(now=clock.now(), metadata=metadata)
        saved = await uow.asset_extractions.save(updated)
        await uow.commit()
    return saved


async def mark_unsupported(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    job: AssetExtractionJob,
    result: ExtractionResult,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        unsupported = current.mark_unsupported(
            now=clock.now(),
            code=result.safe_error_code or "asset_extraction.unsupported",
            message=safe_error_text(result.safe_error_message or "Asset type is unsupported"),
            parser_name=safe_metadata_text(result.parser_name) if result.parser_name else None,
            parser_version=safe_metadata_text(result.parser_version)
            if result.parser_version
            else None,
            model_version=safe_metadata_text(result.model_version)
            if result.model_version
            else None,
            metadata={
                "normalized_content_type": safe_metadata_text(result.normalized_content_type),
                **safe_metadata(result.technical_metadata),
            },
        )
        saved = await uow.asset_extractions.save(unsupported)
        await uow.commit()
    return saved


async def mark_failed(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    retry_policy: ExtractionRetryPolicy,
    job: AssetExtractionJob,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> AssetExtractionJob:
    async with uow_factory() as uow:
        current = await uow.asset_extractions.get_by_id(str(job.id))
        if current is None:
            raise MemoryNotFoundError("Asset extraction job not found")
        now = clock.now()
        policy_retry_disposition = retry_policy.disposition_for_code(code)
        retry_after_at = retry_policy.retry_after(
            now=now,
            attempt_count=current.attempt_count,
            code=code,
        )
        retry_exhausted = (
            policy_retry_disposition == ExtractionRetryDisposition.RETRYABLE
            and retry_after_at is None
            and current.attempt_count >= retry_policy.max_attempts
        )
        retry_disposition = (
            ExtractionRetryDisposition.PERMANENT if retry_exhausted else policy_retry_disposition
        )
        retry_metadata = {
            "retry_disposition": retry_disposition.value,
            "retry_after_at": retry_after_at.isoformat() if retry_after_at else None,
            "retry_max_attempts": retry_policy.max_attempts,
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
