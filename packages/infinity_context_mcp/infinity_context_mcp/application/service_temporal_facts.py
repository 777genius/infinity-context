"""Agent-facing audited temporal fact governance operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_helpers import stable_key


class MemoryToolTemporalFactService(MemoryToolApplicationServiceBase):
    async def confirm_fact(
        self,
        *,
        fact_id: str,
        expected_version: int,
        confirmed_at: datetime,
        confirmation_basis: str,
        **common: Any,
    ) -> dict[str, Any]:
        return await self._govern(
            operation="confirm",
            identity=(fact_id, expected_version, confirmed_at, confirmation_basis),
            side_effect="confirmed_fact",
            call=lambda scope, evidence, key: self._gateway.confirm_fact(
                scope=scope,
                fact_id=fact_id,
                expected_version=expected_version,
                confirmed_at=confirmed_at,
                confirmation_basis=confirmation_basis,
                evidence_refs=[evidence],
                idempotency_key=key,
            ),
            **common,
        )

    async def end_fact_validity(
        self,
        *,
        fact_id: str,
        expected_version: int,
        effective_at: datetime,
        reason_code: str,
        **common: Any,
    ) -> dict[str, Any]:
        return await self._govern(
            operation="end-validity",
            identity=(fact_id, expected_version, effective_at, reason_code),
            side_effect="ended_fact_validity",
            call=lambda scope, evidence, key: self._gateway.end_fact_validity(
                scope=scope,
                fact_id=fact_id,
                expected_version=expected_version,
                effective_at=effective_at,
                reason_code=reason_code,
                evidence_refs=[evidence],
                idempotency_key=key,
            ),
            **common,
        )

    async def supersede_fact(
        self,
        *,
        predecessor_fact_id: str,
        successor_fact_id: str,
        expected_predecessor_version: int,
        expected_successor_version: int,
        effective_at: datetime,
        reason_code: str,
        **common: Any,
    ) -> dict[str, Any]:
        return await self._govern(
            operation="supersede",
            identity=(
                predecessor_fact_id,
                successor_fact_id,
                expected_predecessor_version,
                expected_successor_version,
                effective_at,
                reason_code,
            ),
            side_effect="superseded_fact",
            call=lambda scope, evidence, key: self._gateway.supersede_fact(
                scope=scope,
                predecessor_fact_id=predecessor_fact_id,
                successor_fact_id=successor_fact_id,
                expected_predecessor_version=expected_predecessor_version,
                expected_successor_version=expected_successor_version,
                effective_at=effective_at,
                reason_code=reason_code,
                evidence_refs=[evidence],
                idempotency_key=key,
            ),
            **common,
        )

    async def dispute_facts(
        self,
        *,
        challenged_fact_id: str,
        challenger_fact_id: str,
        expected_challenged_version: int,
        expected_challenger_version: int,
        reason_code: str,
        **common: Any,
    ) -> dict[str, Any]:
        return await self._govern(
            operation="dispute",
            identity=(
                challenged_fact_id,
                challenger_fact_id,
                expected_challenged_version,
                expected_challenger_version,
                reason_code,
            ),
            side_effect="disputed_facts",
            call=lambda scope, evidence, key: self._gateway.dispute_facts(
                scope=scope,
                challenged_fact_id=challenged_fact_id,
                challenger_fact_id=challenger_fact_id,
                expected_challenged_version=expected_challenged_version,
                expected_challenger_version=expected_challenger_version,
                reason_code=reason_code,
                evidence_refs=[evidence],
                idempotency_key=key,
            ),
            **common,
        )

    async def reinstate_supersession(
        self,
        *,
        supersession_decision_id: str,
        expected_rejected_successor_version: int,
        expected_original_predecessor_version: int,
        reason_code: str,
        **common: Any,
    ) -> dict[str, Any]:
        return await self._govern(
            operation="reinstate",
            identity=(
                supersession_decision_id,
                expected_rejected_successor_version,
                expected_original_predecessor_version,
                reason_code,
            ),
            side_effect="reinstated_supersession",
            call=lambda scope, evidence, key: self._gateway.reinstate_supersession(
                scope=scope,
                supersession_decision_id=supersession_decision_id,
                expected_rejected_successor_version=expected_rejected_successor_version,
                expected_original_predecessor_version=expected_original_predecessor_version,
                reason_code=reason_code,
                evidence_refs=[evidence],
                idempotency_key=key,
            ),
            **common,
        )

    async def _govern(
        self,
        *,
        operation: str,
        identity: tuple[object, ...],
        side_effect: str,
        call: Callable[[object, object, str], Awaitable[dict[str, Any]]],
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_writes_allowed()
            scope = self._scope(
                space_slug,
                memory_scope_external_ref,
                thread_external_ref,
            )
            evidence = self._source_ref(
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                fallback_seed=f"temporal:{operation}:{scope}:{identity}",
            )
            key = idempotency_key or stable_key("mcp-temporal", scope, operation, identity)
            payload = await call(scope, evidence, key)
            return self._ok(
                "Audited temporal decision applied.",
                data=payload.get("data", payload),
                side_effects=[side_effect],
            )

        return await self._guard(action)


__all__ = ("MemoryToolTemporalFactService",)
