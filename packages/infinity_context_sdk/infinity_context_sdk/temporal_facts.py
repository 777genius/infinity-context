"""Audited temporal fact governance methods for the public SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import infinity_context_sdk._payloads as _payloads
from infinity_context_sdk.scopes import MemoryScope


class _RequestClient(Protocol):
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]: ...


class InfinityContextTemporalFactsMixin:
    def confirm_fact(
        self: _RequestClient,
        fact_id: str,
        *,
        expected_version: int,
        confirmed_at: datetime,
        confirmation_basis: str,
        evidence_refs: list[dict[str, Any]],
        idempotency_key: str,
        actor_id: str | None = None,
        **scope: Any,
    ) -> dict[str, Any]:
        return self._temporal_fact_request(
            f"/v1/facts/{fact_id}/confirm",
            scope=scope,
            idempotency_key=idempotency_key,
            payload={
                "expected_version": expected_version,
                "confirmed_at": _aware_isoformat(confirmed_at),
                "confirmation_basis": confirmation_basis,
                "evidence_refs": _evidence_payload(evidence_refs),
                "actor_id": actor_id,
            },
        )

    def end_fact_validity(
        self: _RequestClient,
        fact_id: str,
        *,
        expected_version: int,
        effective_at: datetime,
        reason_code: str,
        evidence_refs: list[dict[str, Any]],
        idempotency_key: str,
        actor_id: str | None = None,
        **scope: Any,
    ) -> dict[str, Any]:
        return self._temporal_fact_request(
            f"/v1/facts/{fact_id}/end-validity",
            scope=scope,
            idempotency_key=idempotency_key,
            payload={
                "expected_version": expected_version,
                "effective_at": _aware_isoformat(effective_at),
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
                "actor_id": actor_id,
            },
        )

    def supersede_fact(
        self: _RequestClient,
        predecessor_fact_id: str,
        *,
        successor_fact_id: str,
        expected_predecessor_version: int,
        expected_successor_version: int,
        effective_at: datetime,
        reason_code: str,
        evidence_refs: list[dict[str, Any]],
        idempotency_key: str,
        actor_id: str | None = None,
        **scope: Any,
    ) -> dict[str, Any]:
        return self._temporal_fact_request(
            f"/v1/facts/{predecessor_fact_id}/supersede",
            scope=scope,
            idempotency_key=idempotency_key,
            payload={
                "successor_fact_id": successor_fact_id,
                "expected_predecessor_version": expected_predecessor_version,
                "expected_successor_version": expected_successor_version,
                "effective_at": _aware_isoformat(effective_at),
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
                "actor_id": actor_id,
            },
        )

    def dispute_facts(
        self: _RequestClient,
        challenged_fact_id: str,
        *,
        challenger_fact_id: str,
        expected_challenged_version: int,
        expected_challenger_version: int,
        reason_code: str,
        evidence_refs: list[dict[str, Any]],
        idempotency_key: str,
        actor_id: str | None = None,
        **scope: Any,
    ) -> dict[str, Any]:
        return self._temporal_fact_request(
            f"/v1/facts/{challenged_fact_id}/dispute",
            scope=scope,
            idempotency_key=idempotency_key,
            payload={
                "challenger_fact_id": challenger_fact_id,
                "expected_challenged_version": expected_challenged_version,
                "expected_challenger_version": expected_challenger_version,
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
                "actor_id": actor_id,
            },
        )

    def reinstate_supersession(
        self: _RequestClient,
        *,
        supersession_decision_id: str,
        expected_rejected_successor_version: int,
        expected_original_predecessor_version: int,
        reason_code: str,
        evidence_refs: list[dict[str, Any]],
        idempotency_key: str,
        actor_id: str | None = None,
        **scope: Any,
    ) -> dict[str, Any]:
        return self._temporal_fact_request(
            "/v1/facts/reinstate-supersession",
            scope=scope,
            idempotency_key=idempotency_key,
            payload={
                "supersession_decision_id": supersession_decision_id,
                "expected_rejected_successor_version": expected_rejected_successor_version,
                "expected_original_predecessor_version": expected_original_predecessor_version,
                "reason_code": reason_code,
                "evidence_refs": _evidence_payload(evidence_refs),
                "actor_id": actor_id,
            },
        )

    def _temporal_fact_request(
        self: _RequestClient,
        path: str,
        *,
        scope: dict[str, Any],
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope_payload = _scope_payload(scope)
        return self._request(
            "POST",
            path,
            json=_payloads.without_none({**scope_payload, **payload}),
            idempotency_key=idempotency_key,
        )


def _scope_payload(values: dict[str, Any]) -> dict[str, Any]:
    explicit = values.pop("scope", None)
    if values.get("memory_scope_id") is None and explicit is not None:
        if not isinstance(explicit, MemoryScope):
            raise TypeError("scope must be a MemoryScope")
        payload = explicit.to_payload()
    else:
        payload = _payloads.single_scope_body(
            space_id=values.pop("space_id", None),
            memory_scope_id=values.pop("memory_scope_id", None),
            thread_id=values.pop("thread_id", None),
            space_slug=values.pop("space_slug", None),
            memory_scope_external_ref=values.pop("memory_scope_external_ref", None),
            thread_external_ref=values.pop("thread_external_ref", None),
        )
    if values:
        raise TypeError(f"Unknown temporal fact scope arguments: {sorted(values)}")
    _payloads.validate_single_scope_payload(payload)
    return payload


def _aware_isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Temporal fact timestamps must be timezone-aware")
    return value.isoformat()


def _evidence_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise ValueError("Temporal fact decisions require evidence_refs")
    return [{"source_ref": item} for item in items]


__all__ = ("InfinityContextTemporalFactsMixin",)
