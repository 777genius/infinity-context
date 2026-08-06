"""HTTP methods for audited temporal fact governance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_mcp.domain.models import MemoryScope, SourceRef


class HttpMemoryTemporalFactGatewayMixin:
    async def confirm_fact(
        self,
        *,
        scope: MemoryScope,
        fact_id: str,
        expected_version: int,
        confirmed_at: datetime,
        confirmation_basis: str,
        evidence_refs: list[SourceRef],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._temporal_request(
            path=f"/v1/facts/{fact_id}/confirm",
            scope=scope,
            idempotency_key=idempotency_key,
            body={
                "expected_version": expected_version,
                "confirmed_at": confirmed_at.isoformat(),
                "confirmation_basis": confirmation_basis,
                "evidence_refs": _evidence_payload(evidence_refs),
            },
        )

    async def end_fact_validity(
        self,
        *,
        scope: MemoryScope,
        fact_id: str,
        expected_version: int,
        effective_at: datetime,
        reason_code: str,
        evidence_refs: list[SourceRef],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._temporal_request(
            path=f"/v1/facts/{fact_id}/end-validity",
            scope=scope,
            idempotency_key=idempotency_key,
            body={
                "expected_version": expected_version,
                "effective_at": effective_at.isoformat(),
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
            },
        )

    async def supersede_fact(
        self,
        *,
        scope: MemoryScope,
        predecessor_fact_id: str,
        successor_fact_id: str,
        expected_predecessor_version: int,
        expected_successor_version: int,
        effective_at: datetime,
        reason_code: str,
        evidence_refs: list[SourceRef],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._temporal_request(
            path=f"/v1/facts/{predecessor_fact_id}/supersede",
            scope=scope,
            idempotency_key=idempotency_key,
            body={
                "successor_fact_id": successor_fact_id,
                "expected_predecessor_version": expected_predecessor_version,
                "expected_successor_version": expected_successor_version,
                "effective_at": effective_at.isoformat(),
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
            },
        )

    async def dispute_facts(
        self,
        *,
        scope: MemoryScope,
        challenged_fact_id: str,
        challenger_fact_id: str,
        expected_challenged_version: int,
        expected_challenger_version: int,
        reason_code: str,
        evidence_refs: list[SourceRef],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._temporal_request(
            path=f"/v1/facts/{challenged_fact_id}/dispute",
            scope=scope,
            idempotency_key=idempotency_key,
            body={
                "challenger_fact_id": challenger_fact_id,
                "expected_challenged_version": expected_challenged_version,
                "expected_challenger_version": expected_challenger_version,
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
            },
        )

    async def reinstate_supersession(
        self,
        *,
        scope: MemoryScope,
        supersession_decision_id: str,
        expected_rejected_successor_version: int,
        expected_original_predecessor_version: int,
        reason_code: str,
        evidence_refs: list[SourceRef],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._temporal_request(
            path="/v1/facts/reinstate-supersession",
            scope=scope,
            idempotency_key=idempotency_key,
            body={
                "supersession_decision_id": supersession_decision_id,
                "expected_rejected_successor_version": expected_rejected_successor_version,
                "expected_original_predecessor_version": expected_original_predecessor_version,
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
            },
        )

    async def _temporal_request(
        self,
        *,
        path: str,
        scope: MemoryScope,
        idempotency_key: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            idempotency_key=idempotency_key,
            json={
                **body,
                "space_slug": scope.space_slug,
                "memory_scope_external_ref": scope.memory_scope_external_ref,
                "thread_external_ref": scope.thread_external_ref,
            },
        )


def _evidence_payload(evidence_refs: list[SourceRef]) -> list[dict[str, object]]:
    return [{"source_ref": source.to_payload()} for source in evidence_refs]


__all__ = ("HttpMemoryTemporalFactGatewayMixin",)
