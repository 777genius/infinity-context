"""Shared HTTP fixtures for audited temporal context tests."""

from fastapi.testclient import TestClient


def state_temporal(valid_from: str) -> dict[str, str]:
    return {"kind": "state", "observed_at": valid_from, "valid_from": valid_from}


def audited_supersede(
    client: TestClient,
    *,
    predecessor_fact_id: str,
    successor_fact_id: str,
    effective_at: str,
    idempotency_key: str,
):
    return client.post(
        f"/v1/facts/{predecessor_fact_id}/supersede",
        json={
            "space_id": "space_client_app",
            "memory_scope_id": "memory_scope_default",
            "successor_fact_id": successor_fact_id,
            "expected_successor_version": 1,
            "expected_predecessor_version": 1,
            "effective_at": effective_at,
            "reason_code": "accepted_replacement",
            "actor_id": "context-test-reviewer",
            "evidence_refs": [
                {
                    "source_ref": {
                        "source_type": "manual",
                        "source_id": f"supersede-{idempotency_key}",
                    }
                }
            ],
        },
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": idempotency_key,
        },
    )


__all__ = ("audited_supersede", "state_temporal")
