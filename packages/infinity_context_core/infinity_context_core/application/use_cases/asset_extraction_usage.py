"""Idempotent reconciliation of actual extraction media usage."""

from __future__ import annotations

from infinity_context_core.application.use_cases.asset_extraction_support import (
    actual_media_analysis_seconds,
    positive_int,
    usage_reconciliation_idempotency_key,
)
from infinity_context_core.domain.errors import MemoryNotFoundError
from infinity_context_core.domain.extraction import AssetExtractionJob
from infinity_context_core.domain.usage import (
    USAGE_RECONCILIATION_SOURCE_TYPE,
    UsageRecord,
    UsageRecordId,
    UsageResource,
    UsageSubjectType,
    UsageWindow,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.extraction import ExtractionResult
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


async def reconcile_media_usage(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort,
    ids: IdGeneratorPort,
    job: AssetExtractionJob,
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

    window = UsageWindow.calendar_month_for(clock.now())
    key = usage_reconciliation_idempotency_key(
        job_id=str(job.id),
        actual_seconds=actual_seconds,
    )
    async with uow_factory() as uow:
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
                    record_id=UsageRecordId(ids.new_id("usage")),
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
                    now=clock.now(),
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
            now=clock.now(),
            metadata=reconciliation_metadata,
        )
        saved = await uow.asset_extractions.save(updated)
        await uow.commit()
    return saved
