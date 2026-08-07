"""Exact-result replay policy for externally retryable suggestion resolutions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256

from infinity_context_core.application.dto_suggestions_capture import SuggestionResult
from infinity_context_core.application.suggestion_fact_resolution import (
    authorize_suggestion_review,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.features.memory_facts.public import ReviewedFactMutationResult
from infinity_context_core.features.review_governance.public import (
    SuggestionResolutionReceipt,
    SuggestionResolutionReceiptRepositoryPort,
    SuggestionReviewScope,
)


def suggestion_resolution_identity(
    *,
    suggestion_id: str,
    operation: str,
    idempotency_key: str | None,
    request: Mapping[str, object],
) -> tuple[str, str]:
    normalized_key = (
        idempotency_key.strip()
        if idempotency_key is not None
        else f"suggestion-resolution:{suggestion_id}:{operation}"
    )
    if not normalized_key:
        raise MemoryValidationError("Idempotency-Key cannot be blank")
    if len(normalized_key) > 160:
        raise MemoryValidationError("Idempotency-Key exceeds 160 characters")
    canonical_request = {
        "suggestion_id": suggestion_id,
        "operation": operation,
        **dict(request),
    }
    fingerprint = sha256(
        json.dumps(
            canonical_request,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return normalized_key, fingerprint


async def load_suggestion_resolution_replay(
    repository: SuggestionResolutionReceiptRepositoryPort,
    *,
    suggestion_id: str,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
    review_scope: SuggestionReviewScope | None,
) -> SuggestionResult | None:
    receipt = await repository.get(
        suggestion_id=suggestion_id,
        operation=operation,
        idempotency_key=idempotency_key,
    )
    if receipt is None:
        return None
    authorize_suggestion_review(receipt.result_suggestion, review_scope)
    if receipt.request_fingerprint != request_fingerprint:
        raise MemoryConflictError("Idempotency-Key was reused with a different review request")
    return SuggestionResult(
        suggestion=receipt.result_suggestion,
        fact=receipt.result_fact,
        indexing_status=receipt.indexing_status,
        replayed=True,
    )


def new_suggestion_resolution_receipt(
    *,
    result: SuggestionResult,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
    outcome: ReviewedFactMutationResult | None,
    created_at: datetime,
) -> SuggestionResolutionReceipt:
    return SuggestionResolutionReceipt(
        suggestion_id=str(result.suggestion.id),
        space_id=str(result.suggestion.space_id),
        memory_scope_id=str(result.suggestion.memory_scope_id),
        operation=operation,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        result_suggestion=result.suggestion,
        result_fact=outcome.primary_fact if outcome is not None else None,
        indexing_status=result.indexing_status,
        affected_fact_ids=(
            tuple(fact.identity.fact_id for fact in outcome.affected_facts)
            if outcome is not None
            else ()
        ),
        affected_fact_versions=(
            tuple(fact.visibility.version for fact in outcome.affected_facts)
            if outcome is not None
            else ()
        ),
        temporal_decision_id=(
            outcome.decision.decision_id
            if outcome is not None and outcome.decision is not None
            else None
        ),
        relation_id=(
            outcome.relation.relation_id
            if outcome is not None and outcome.relation is not None
            else None
        ),
        outbox_message_ids=outcome.outbox_message_ids if outcome is not None else (),
        created_at=created_at,
    )


__all__ = (
    "load_suggestion_resolution_replay",
    "new_suggestion_resolution_receipt",
    "suggestion_resolution_identity",
)
