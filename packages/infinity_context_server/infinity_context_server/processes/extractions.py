"""Outbox process handlers for extraction and capture use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from infinity_context_core.application import ConsolidateCaptureCommand, RunAssetExtractionCommand

from infinity_context_server.processes.outbox import ClaimedOutboxJob, OutboxHandlerRegistry

if TYPE_CHECKING:
    from infinity_context_server.composition import Container


class ExtractionOutboxProcess:
    def __init__(self, container: Container) -> None:
        self._container = container

    def handlers(self) -> OutboxHandlerRegistry:
        return {
            "capture.consolidate": self.handle_capture_consolidate,
            "asset.extract": self.handle_asset_extract,
        }

    async def handle_capture_consolidate(self, job: ClaimedOutboxJob) -> None:
        await self._container.consolidate_capture.execute(
            ConsolidateCaptureCommand(
                capture_id=str(job.payload_json.get("capture_id") or job.aggregate_id),
                force=job.attempt_count > 0,
            )
        )

    async def handle_asset_extract(self, job: ClaimedOutboxJob) -> None:
        await self._container.run_asset_extraction.execute(
            RunAssetExtractionCommand(
                job_id=str(job.payload_json.get("job_id") or job.aggregate_id),
                force=job.attempt_count > 0,
                worker_id=f"outbox:{job.id}",
            )
        )
