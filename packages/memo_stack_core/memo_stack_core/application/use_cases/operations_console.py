"""Operational read model for memory ingestion and link review."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    MemoryOperationsConsoleQuery,
    MemoryOperationsConsoleResult,
)
from memo_stack_core.domain.extraction import AssetExtractionStatus
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_RETRYABLE_EXTRACTION_STATUSES = {
    AssetExtractionStatus.FAILED.value,
    AssetExtractionStatus.UNSUPPORTED.value,
    AssetExtractionStatus.CANCELED.value,
    AssetExtractionStatus.STALE.value,
}


class BuildMemoryOperationsConsoleUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        query: MemoryOperationsConsoleQuery,
    ) -> MemoryOperationsConsoleResult:
        limit = max(1, min(query.limit, 200))
        thread_id = str(query.thread_id) if query.thread_id else None
        async with self._uow_factory() as uow:
            extraction_counts = await uow.asset_extractions.count_by_status_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=thread_id,
            )
            link_suggestion_counts = await uow.context_link_suggestions.count_by_status_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
            )
            extraction_jobs = await uow.asset_extractions.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=thread_id,
                status=None,
                limit=limit,
            )
            suggestions = await uow.context_link_suggestions.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                status=None,
                limit=limit,
            )

        diagnostics = _diagnostics(
            extraction_status_counts=extraction_counts,
            link_suggestion_status_counts=link_suggestion_counts,
            extraction_job_count=len(extraction_jobs),
            suggestion_count=len(suggestions),
        )
        return MemoryOperationsConsoleResult(
            generated_at=self._clock.now(),
            scope={
                "space_id": str(query.space_id),
                "memory_scope_id": str(query.memory_scope_id),
                "thread_id": thread_id,
            },
            extraction_status_counts=extraction_counts,
            link_suggestion_status_counts=link_suggestion_counts,
            extraction_jobs=tuple(extraction_jobs),
            context_link_suggestions=tuple(suggestions),
            diagnostics=diagnostics,
        )


def _diagnostics(
    *,
    extraction_status_counts: dict[str, int],
    link_suggestion_status_counts: dict[str, int],
    extraction_job_count: int,
    suggestion_count: int,
) -> dict[str, object]:
    retryable_count = sum(
        extraction_status_counts.get(status, 0) for status in _RETRYABLE_EXTRACTION_STATUSES
    )
    active_count = sum(
        extraction_status_counts.get(status, 0)
        for status in (AssetExtractionStatus.PENDING.value, AssetExtractionStatus.RUNNING.value)
    )
    pending_suggestions = link_suggestion_status_counts.get("pending", 0)
    reviewed_suggestions = sum(
        link_suggestion_status_counts.get(status, 0) for status in ("approved", "rejected")
    )
    return {
        "console_version": "memory-operations-console-v1",
        "extraction_active_count": active_count,
        "extraction_retryable_count": retryable_count,
        "extraction_returned_count": extraction_job_count,
        "link_suggestion_pending_count": pending_suggestions,
        "link_suggestion_reviewed_count": reviewed_suggestions,
        "link_suggestion_returned_count": suggestion_count,
        "link_suggestion_explainability": {
            "stored_fields": (
                "reason",
                "score",
                "confidence",
                "reviewed_at",
                "review_reason",
                "metadata.target_label",
                "metadata.target_preview",
                "metadata.target_tier",
                "metadata.resolver_version",
                "metadata.reason_codes",
                "metadata.matched_terms",
            ),
            "no_suggestion_note": (
                "Suggestions are stored only when persisted link discovery finds visible "
                "same-scope candidates for a capture or asset. Empty results usually mean "
                "no visible candidate matched the source text strongly enough, the source "
                "was not persisted, or an active link already exists."
            ),
            "no_suggestion_reasons": (
                {
                    "code": "no_visible_same_scope_candidate",
                    "label": (
                        "No visible same-scope memory matched the source text strongly enough."
                    ),
                },
                {
                    "code": "source_not_persisted",
                    "label": (
                        "The source capture or asset may not be persisted with a stable id yet."
                    ),
                },
                {
                    "code": "already_linked",
                    "label": "An active link may already exist, so duplicates are hidden.",
                },
                {
                    "code": "not_pending",
                    "label": (
                        "Suggestions that were approved, rejected, expired, or "
                        "superseded are outside the pending queue."
                    ),
                },
            ),
        },
        "extraction_observability": {
            "stored_fields": (
                "status",
                "attempt_count",
                "safe_error_code",
                "safe_error_message",
                "progress",
                "execution.lease_owner",
                "execution.heartbeat_at",
                "execution.retry_after_at",
                "execution.retry_disposition",
                "execution.cancellation_requested_at",
            )
        },
    }
