"""Server process/orchestration boundaries."""

from __future__ import annotations

from infinity_context_server.processes.code_repository_enrollment import (
    CodeRepositoryEnrollmentProcess,
    CodeRepositoryEnrollmentResult,
)
from infinity_context_server.processes.code_scope_authorization import (
    CodeScopeAuthorizationProcess,
)
from infinity_context_server.processes.extractions import ExtractionOutboxProcess
from infinity_context_server.processes.fact_projections import FactProjectionOutboxProcess
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
from infinity_context_server.processes.vector_rebuild import GenericVectorRebuildProcess
from infinity_context_server.processes.workspace_scope_claim_verification import (
    WorkspaceScopeClaimVerificationProcess,
)


def build_outbox_event_dispatcher(container) -> OutboxEventDispatcher:
    projections = ProjectionOutboxProcess(container)
    fact_projections = FactProjectionOutboxProcess(container)
    return OutboxEventDispatcher(
        merge_outbox_handlers(
            projections.vector_handlers(),
            GenericVectorRebuildProcess(container).handlers(),
            fact_projections.legacy_handlers(),
            projections.document_handlers(),
            ExtractionOutboxProcess(container).handlers(),
            fact_projections.canonical_handlers(),
        )
    )


__all__ = (
    "ClaimedOutboxJob",
    "CodeRepositoryEnrollmentProcess",
    "CodeRepositoryEnrollmentResult",
    "CodeScopeAuthorizationProcess",
    "ExtractionOutboxProcess",
    "FactProjectionOutboxProcess",
    "OutboxEventDispatcher",
    "OutboxEventHandler",
    "OutboxHandlerRegistry",
    "OutboxProjectionError",
    "ProjectionOutboxProcess",
    "WorkspaceScopeClaimVerificationProcess",
    "build_outbox_event_dispatcher",
    "merge_outbox_handlers",
)
