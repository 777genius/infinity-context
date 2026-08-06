"""Audited temporal fact decisions used by deterministic eval fixtures."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from infinity_context_server.eval_common import _with_idempotency


def supersede_eval_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    predecessor_response: httpx.Response,
    successor_response: httpx.Response,
    idempotency_key: str,
    evidence_source_id: str,
    reason_code: str,
) -> httpx.Response:
    predecessor = _fact_data(predecessor_response)
    successor = _fact_data(successor_response)
    temporal = successor.get("temporal", {}) if successor is not None else {}
    effective_at = temporal.get("valid_from") if isinstance(temporal, dict) else None
    if (
        predecessor is None
        or successor is None
        or not predecessor.get("id")
        or not successor.get("id")
        or not isinstance(predecessor.get("version"), int)
        or not isinstance(successor.get("version"), int)
        or not effective_at
    ):
        return httpx.Response(status_code=500)
    return client.post(
        f"/v1/facts/{predecessor['id']}/supersede",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "successor_fact_id": successor["id"],
            "expected_successor_version": successor["version"],
            "expected_predecessor_version": predecessor["version"],
            "effective_at": effective_at,
            "reason_code": reason_code,
            "actor_id": "quality-eval",
            "evidence_refs": _evidence_refs(evidence_source_id),
        },
        headers=_with_idempotency(headers, idempotency_key),
    )


def dispute_eval_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    challenged_response: httpx.Response,
    challenger_response: httpx.Response,
    idempotency_key: str,
    evidence_source_id: str,
    reason_code: str,
) -> httpx.Response:
    challenged = _fact_data(challenged_response)
    challenger = _fact_data(challenger_response)
    if (
        challenged is None
        or challenger is None
        or not challenged.get("id")
        or not challenger.get("id")
        or not isinstance(challenged.get("version"), int)
        or not isinstance(challenger.get("version"), int)
    ):
        return httpx.Response(status_code=500)
    return client.post(
        f"/v1/facts/{challenged['id']}/dispute",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "challenger_fact_id": challenger["id"],
            "expected_challenger_version": challenger["version"],
            "expected_challenged_version": challenged["version"],
            "reason_code": reason_code,
            "actor_id": "quality-eval",
            "evidence_refs": _evidence_refs(evidence_source_id),
        },
        headers=_with_idempotency(headers, idempotency_key),
    )


def _fact_data(response: httpx.Response) -> dict[str, object] | None:
    data = response.json().get("data", {})
    return data if isinstance(data, dict) else None


def _evidence_refs(source_id: str) -> list[dict[str, dict[str, str]]]:
    return [{"source_ref": {"source_type": "manual", "source_id": source_id}}]


__all__ = ("dispute_eval_fact", "supersede_eval_fact")
