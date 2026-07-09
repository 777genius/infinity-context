"""Server process/orchestration boundaries."""

from __future__ import annotations

from infinity_context_server.processes.extractions import ExtractionOutboxProcess
from infinity_context_server.processes.outbox import (
    ClaimedOutboxJob,
    OutboxEventDispatcher,
    OutboxEventHandler,
    OutboxHandlerRegistry,
    merge_outbox_handlers,
)
from infinity_context_server.processes.projections import (
    OutboxProjectionError,
    ProjectionOutboxProcess,
)


def build_outbox_event_dispatcher(container) -> OutboxEventDispatcher:
    return OutboxEventDispatcher(
        merge_outbox_handlers(
            ProjectionOutboxProcess(container).handlers(),
            ExtractionOutboxProcess(container).handlers(),
        )
    )


__all__ = (
    "ClaimedOutboxJob",
    "ExtractionOutboxProcess",
    "OutboxEventDispatcher",
    "OutboxEventHandler",
    "OutboxHandlerRegistry",
    "OutboxProjectionError",
    "ProjectionOutboxProcess",
    "build_outbox_event_dispatcher",
    "merge_outbox_handlers",
)
