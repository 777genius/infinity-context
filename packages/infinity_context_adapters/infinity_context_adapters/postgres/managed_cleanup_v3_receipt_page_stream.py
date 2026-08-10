"""Bounded global keyset streams for cleanup-v3 receipt preflight."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_scratch_sql import (
    LINK_PAGE_SQL,
    PAYLOAD_PAGE_SQL,
    RECEIPT_PAGE_SIZE,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    fail,
    integer_value,
)


@dataclass(slots=True)
class ReceiptPreflightMetrics:
    receipt_pages: int = 0
    link_pages: int = 0
    payload_pages: int = 0
    max_receipt_page: int = 0
    max_link_page: int = 0
    max_payload_page: int = 0
    max_retained_identities: int = 0
    scratch_checkpoints: int = 0
    max_pending_mutations: int = 0


class GlobalKeysetStream(ABC):
    """One bounded keyset stream shared by all receipt groups."""

    def __init__(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        metrics: ReceiptPreflightMetrics,
        sql: str,
        page_error: str,
        order_error: str,
    ) -> None:
        self._connection = connection
        self._context = context
        self._metrics = metrics
        self._sql = sql
        self._page_error = page_error
        self._order_error = order_error
        self._after = (-1, -1)
        self._page: list[Any] = []
        self._index = 0
        self._exhausted = False

    async def peek(self) -> Any | None:
        if self._index < len(self._page):
            return self._page[self._index]
        if self._exhausted:
            return None
        rows = await self._connection.fetch(
            self._sql,
            self._context.run_id_sha256,
            self._context.context_sha256,
            self._context.space_id,
            *self._after,
            RECEIPT_PAGE_SIZE,
        )
        self._record_page(len(rows))
        self._metrics.max_retained_identities = max(
            self._metrics.max_retained_identities, len(rows)
        )
        if len(rows) > RECEIPT_PAGE_SIZE:
            fail(self._page_error)
        self._page = rows
        self._index = 0
        self._exhausted = len(rows) < RECEIPT_PAGE_SIZE
        return self._page[0] if self._page else None

    @abstractmethod
    def _record_page(self, size: int) -> None:
        """Record query-specific page metrics."""

    def advance(self) -> None:
        raw = self._page[self._index]
        key = (integer_value(raw["outbox_id"]), integer_value(raw["ordinal"]))
        if key <= self._after:
            fail(self._order_error)
        self._after = key
        self._index += 1


class GlobalLinkStream(GlobalKeysetStream):
    def __init__(self, connection, context, metrics) -> None:
        super().__init__(
            connection, context, metrics, LINK_PAGE_SQL, "link_page_invalid", "link_order_invalid"
        )

    def _record_page(self, size: int) -> None:
        self._metrics.link_pages += 1
        self._metrics.max_link_page = max(self._metrics.max_link_page, size)


class GlobalPayloadStream(GlobalKeysetStream):
    def __init__(self, connection, context, metrics) -> None:
        super().__init__(
            connection,
            context,
            metrics,
            PAYLOAD_PAGE_SQL,
            "payload_page_invalid",
            "payload_order_invalid",
        )

    def _record_page(self, size: int) -> None:
        self._metrics.payload_pages += 1
        self._metrics.max_payload_page = max(self._metrics.max_payload_page, size)


__all__ = (
    "GlobalLinkStream",
    "GlobalPayloadStream",
    "ReceiptPreflightMetrics",
)
