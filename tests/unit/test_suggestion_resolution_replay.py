"""Authorization and identity invariants for exact suggestion replay."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.suggestion_resolution_replay import (
    load_suggestion_resolution_replay,
    suggestion_resolution_identity,
)
from infinity_context_core.domain.entities import (
    MemoryKind,
    MemoryScopeId,
    MemorySuggestion,
    MemorySuggestionId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_core.features.review_governance.public import (
    SuggestionResolutionReceipt,
    SuggestionReviewScope,
)

NOW = datetime(2026, 8, 6, tzinfo=UTC)


def test_scoped_reviewer_can_replay_after_grant_shape_changes() -> None:
    async def run() -> None:
        request = {
            "reason": "confirmed",
            "force": False,
            "actor_id": "reviewer-1",
        }
        idempotency_key, fingerprint = suggestion_resolution_identity(
            suggestion_id="suggestion-1",
            operation="approve",
            idempotency_key="unknown-commit-1",
            request=request,
        )
        suggestion = MemorySuggestion.create(
            suggestion_id=MemorySuggestionId("suggestion-1"),
            space_id=SpaceId("space-1"),
            memory_scope_id=MemoryScopeId("scope-1"),
            candidate_text="Use the repository-scoped architecture.",
            kind=MemoryKind.ARCHITECTURE_DECISION,
            source_refs=(SourceRef(source_type="manual", source_id="review-1"),),
            safe_reason="manual review",
            review_payload={
                "repository_id": "repository-1",
                "code_scope_id": "code-scope-1",
            },
            now=NOW,
        ).approve(now=NOW, reason="confirmed")
        receipt = SuggestionResolutionReceipt(
            suggestion_id="suggestion-1",
            space_id="space-1",
            memory_scope_id="scope-1",
            operation="approve",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            result_suggestion=suggestion,
            result_fact=None,
            indexing_status="pending",
            affected_fact_ids=(),
            affected_fact_versions=(),
            temporal_decision_id=None,
            relation_id=None,
            outbox_message_ids=(),
            created_at=NOW,
        )
        repository = _ReceiptRepository(receipt)

        replay = await load_suggestion_resolution_replay(
            repository,
            suggestion_id="suggestion-1",
            operation="approve",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            review_scope=SuggestionReviewScope(
                space_id="space-1",
                memory_scope_ids=("scope-extra", "scope-1"),
                repository_id="repository-1",
                code_scope_id="code-scope-1",
            ),
        )

        assert replay is not None
        assert replay.replayed is True
        assert replay.suggestion == suggestion

        with pytest.raises(MemoryForbiddenError):
            await load_suggestion_resolution_replay(
                repository,
                suggestion_id="suggestion-1",
                operation="approve",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                review_scope=SuggestionReviewScope(
                    space_id="space-1",
                    memory_scope_ids=("scope-1",),
                    repository_id="repository-other",
                    code_scope_id="code-scope-1",
                ),
            )

    asyncio.run(run())


def test_receipt_rejects_scope_drift_from_exact_suggestion_snapshot() -> None:
    suggestion = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("suggestion-1"),
        space_id=SpaceId("space-1"),
        memory_scope_id=MemoryScopeId("scope-1"),
        candidate_text="Keep audit receipts tenant-bound.",
        kind=MemoryKind.ARCHITECTURE_DECISION,
        source_refs=(SourceRef(source_type="manual", source_id="review-1"),),
        safe_reason="manual review",
        now=NOW,
    ).approve(now=NOW, reason="confirmed")

    with pytest.raises(ValueError, match="suggestion memory scope"):
        SuggestionResolutionReceipt(
            suggestion_id="suggestion-1",
            space_id="space-1",
            memory_scope_id="scope-other",
            operation="approve",
            idempotency_key="approve-1",
            request_fingerprint="a" * 64,
            result_suggestion=suggestion,
            result_fact=None,
            indexing_status="pending",
            affected_fact_ids=(),
            affected_fact_versions=(),
            temporal_decision_id=None,
            relation_id=None,
            outbox_message_ids=(),
            created_at=NOW,
        )


class _ReceiptRepository:
    def __init__(self, receipt: SuggestionResolutionReceipt) -> None:
        self._receipt = receipt

    async def get(
        self,
        *,
        suggestion_id: str,
        operation: str,
        idempotency_key: str,
    ) -> SuggestionResolutionReceipt | None:
        if (
            suggestion_id,
            operation,
            idempotency_key,
        ) == (
            self._receipt.suggestion_id,
            self._receipt.operation,
            self._receipt.idempotency_key,
        ):
            return self._receipt
        return None

    async def create(
        self,
        receipt: SuggestionResolutionReceipt,
    ) -> SuggestionResolutionReceipt:
        self._receipt = receipt
        return receipt
