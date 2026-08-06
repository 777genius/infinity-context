"""Atomic process boundary for suggestion review plus canonical fact mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol

from infinity_context_core.features.memory_facts.public import (
    MemoryFactSnapshot,
    ReviewedFactMutationPort,
)


@dataclass(frozen=True, slots=True)
class SuggestionResolutionReceipt:
    """Immutable exact result of one externally retryable review decision."""

    suggestion_id: str
    operation: str
    idempotency_key: str
    request_fingerprint: str
    result_suggestion: Any
    result_fact: MemoryFactSnapshot | None
    indexing_status: str | None
    affected_fact_ids: tuple[str, ...]
    affected_fact_versions: tuple[int, ...]
    temporal_decision_id: str | None
    relation_id: str | None
    outbox_message_ids: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "suggestion_id",
            "operation",
            "idempotency_key",
            "request_fingerprint",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Suggestion resolution receipt {field_name} cannot be blank")
        if str(getattr(self.result_suggestion, "id", "")) != self.suggestion_id:
            raise ValueError("Suggestion resolution receipt must match its suggestion")
        if len(self.affected_fact_ids) != len(self.affected_fact_versions):
            raise ValueError("Suggestion resolution receipt fact ids and versions must align")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Suggestion resolution receipt created_at must be timezone-aware")


class SuggestionResolutionReceiptRepositoryPort(Protocol):
    async def get(
        self,
        *,
        suggestion_id: str,
        operation: str,
        idempotency_key: str,
    ) -> SuggestionResolutionReceipt | None: ...

    async def create(
        self,
        receipt: SuggestionResolutionReceipt,
    ) -> SuggestionResolutionReceipt: ...


class SuggestionReviewRepositoryPort(Protocol):
    """Minimal legacy-suggestion seam retained during the strangler migration."""

    async def get_for_update(self, suggestion_id: str) -> Any: ...

    async def save(self, suggestion: Any) -> Any: ...


class SuggestionResolutionUnitOfWorkPort(Protocol):
    suggestions: SuggestionReviewRepositoryPort
    suggestion_resolution_receipts: SuggestionResolutionReceiptRepositoryPort
    reviewed_facts: ReviewedFactMutationPort

    async def __aenter__(self) -> SuggestionResolutionUnitOfWorkPort: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SuggestionResolutionUnitOfWorkFactoryPort(Protocol):
    def __call__(self) -> SuggestionResolutionUnitOfWorkPort: ...


__all__ = (
    "SuggestionResolutionReceipt",
    "SuggestionResolutionReceiptRepositoryPort",
    "SuggestionResolutionUnitOfWorkFactoryPort",
    "SuggestionResolutionUnitOfWorkPort",
    "SuggestionReviewRepositoryPort",
)
