"""Postgres exact-result receipts for suggestion review decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from infinity_context_core.features.review_governance.public import (
    SuggestionResolutionReceipt,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_snapshot_from_json,
    memory_fact_snapshot_to_json,
)
from infinity_context_adapters.postgres.feature_models import SuggestionResolutionReceiptRow
from infinity_context_adapters.postgres.mappers import suggestion_from_json, suggestion_to_json


class PostgresSuggestionResolutionReceiptRepository:
    """Append-only receipt repository bound to the review transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        suggestion_id: str,
        operation: str,
        idempotency_key: str,
    ) -> SuggestionResolutionReceipt | None:
        row = (
            await self._session.execute(
                select(SuggestionResolutionReceiptRow).where(
                    SuggestionResolutionReceiptRow.suggestion_id == suggestion_id,
                    SuggestionResolutionReceiptRow.operation == operation,
                    SuggestionResolutionReceiptRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return _receipt_from_row(row) if row is not None else None

    async def create(
        self,
        receipt: SuggestionResolutionReceipt,
    ) -> SuggestionResolutionReceipt:
        existing = await self.get(
            suggestion_id=receipt.suggestion_id,
            operation=receipt.operation,
            idempotency_key=receipt.idempotency_key,
        )
        if existing is not None:
            if existing == receipt:
                return existing
            raise ValueError("Suggestion resolution receipt is append-only")
        self._session.add(
            SuggestionResolutionReceiptRow(
                id=_receipt_id(receipt),
                suggestion_id=receipt.suggestion_id,
                space_id=receipt.space_id,
                memory_scope_id=receipt.memory_scope_id,
                operation=receipt.operation,
                idempotency_key=receipt.idempotency_key,
                request_fingerprint=receipt.request_fingerprint,
                result_suggestion_json=suggestion_to_json(receipt.result_suggestion),
                result_fact_json=(
                    memory_fact_snapshot_to_json(receipt.result_fact)
                    if receipt.result_fact is not None
                    else None
                ),
                result_fact_id=(
                    receipt.result_fact.identity.fact_id
                    if receipt.result_fact is not None
                    else None
                ),
                result_fact_version=(
                    receipt.result_fact.visibility.version
                    if receipt.result_fact is not None
                    else None
                ),
                indexing_status=receipt.indexing_status,
                affected_fact_ids_json=list(receipt.affected_fact_ids),
                affected_fact_versions_json=list(receipt.affected_fact_versions),
                temporal_decision_id=receipt.temporal_decision_id,
                relation_id=receipt.relation_id,
                outbox_message_ids_json=list(receipt.outbox_message_ids),
                created_at=receipt.created_at,
            )
        )
        return receipt


def _receipt_from_row(row: SuggestionResolutionReceiptRow) -> SuggestionResolutionReceipt:
    result_suggestion = suggestion_from_json(row.result_suggestion_json)
    result_fact = (
        memory_fact_snapshot_from_json(row.result_fact_json)
        if row.result_fact_json is not None
        else None
    )
    if result_fact is None:
        if row.result_fact_id is not None or row.result_fact_version is not None:
            raise ValueError("Suggestion resolution receipt fact snapshot identity mismatch")
    elif (
        result_fact.identity.fact_id != row.result_fact_id
        or result_fact.visibility.version != row.result_fact_version
    ):
        raise ValueError("Suggestion resolution receipt fact snapshot identity mismatch")
    return SuggestionResolutionReceipt(
        suggestion_id=row.suggestion_id,
        space_id=row.space_id,
        memory_scope_id=row.memory_scope_id,
        operation=row.operation,
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        result_suggestion=result_suggestion,
        result_fact=result_fact,
        indexing_status=row.indexing_status,
        affected_fact_ids=tuple(row.affected_fact_ids_json),
        affected_fact_versions=tuple(row.affected_fact_versions_json),
        temporal_decision_id=row.temporal_decision_id,
        relation_id=row.relation_id,
        outbox_message_ids=tuple(row.outbox_message_ids_json),
        created_at=_aware(row.created_at),
    )


def _receipt_id(receipt: SuggestionResolutionReceipt) -> str:
    raw = "\x1f".join((receipt.suggestion_id, receipt.operation, receipt.idempotency_key)).encode(
        "utf-8"
    )
    return sha256(raw).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ("PostgresSuggestionResolutionReceiptRepository",)
