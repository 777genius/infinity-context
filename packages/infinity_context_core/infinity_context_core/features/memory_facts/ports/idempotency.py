"""Idempotent lifecycle operation receipts owned by memory_facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.memory_facts.domain import MemoryFactSnapshot


class MemoryFactIdempotencyConflict(RuntimeError):
    """A concurrent transaction won the same canonical idempotency identity."""


@dataclass(frozen=True, slots=True)
class MemoryFactOperationReceipt:
    """Immutable result of one externally retryable lifecycle command."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None
    idempotency_key: str
    operation: str
    request_fingerprint: str
    result_fact: MemoryFactSnapshot
    outbox_message_ids: tuple[str, ...]
    created_at: datetime
    tombstone_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "space_id",
            "memory_scope_id",
            "idempotency_key",
            "operation",
            "request_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"Operation receipt {name} cannot be blank")
        if self.result_fact.identity.scope.space_id != self.space_id:
            raise ValueError("Operation receipt result must belong to its space")
        if self.result_fact.identity.scope.memory_scope_id != self.memory_scope_id:
            raise ValueError("Operation receipt result must belong to its memory scope")
        if self.result_fact.identity.scope.thread_id != self.thread_id:
            raise ValueError("Operation receipt result must belong to its thread scope")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Operation receipt created_at must be timezone-aware")


class MemoryFactOperationReceiptPort(Protocol):
    async def create(
        self,
        receipt: MemoryFactOperationReceipt,
    ) -> MemoryFactOperationReceipt:
        """Persist one immutable receipt in the fact transaction."""

    async def get(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> MemoryFactOperationReceipt | None:
        """Load a receipt by the caller-visible idempotency identity."""


__all__ = (
    "MemoryFactIdempotencyConflict",
    "MemoryFactOperationReceipt",
    "MemoryFactOperationReceiptPort",
)
