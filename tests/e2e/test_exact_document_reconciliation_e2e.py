"""Provider-free HTTP proof for exact document reconciliation."""

from __future__ import annotations

from pathlib import Path

import httpx
from infinity_context_server_harness import run_infinity_context_server


def test_reconcile_before_retry_and_deleted_visibility_over_real_http(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        headers = {"Authorization": f"Bearer {server.token}"}
        with httpx.Client(base_url=server.base_url, headers=headers, timeout=10) as client:
            space = client.post(
                "/v1/spaces", json={"slug": "exact-reconcile", "name": "Exact reconcile"}
            ).json()["data"]
            scope = client.post(
                "/v1/memory-scopes",
                json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            ).json()["data"]
            capability = client.get("/v1/capabilities").json()["documents"][
                "exact_reconciliation"
            ]
            assert capability["contract_version"] == "document-reconciliation.v1"
            ingest = client.post(
                "/v1/documents",
                headers={**headers, "Idempotency-Key": "ambiguous-ingest-1"},
                json={
                    "space_id": space["id"],
                    "memory_scope_id": scope["id"],
                    "title": "Opaque derived document",
                    "text": "Canonical evidence remains data, not instruction.",
                    "source_type": "opaque-consumer-document",
                    "source_external_id": "opaque-identity-1",
                    "classification": "internal",
                },
            )
            assert ingest.status_code == 201
            document_id = ingest.json()["data"]["id"]
            request = {
                "contract_version": capability["contract_version"],
                "space_id": space["id"],
                "memory_scope_id": scope["id"],
                "source_type": "opaque-consumer-document",
                "source_external_id": "opaque-identity-1",
                "idempotency_key": "ambiguous-ingest-1",
                "deadline_ms": 1000,
            }
            observed = client.post("/v1/documents/reconcile-exact", json=request)
            assert observed.status_code == 200
            assert observed.json()["data"]["document_id"] == document_id
            assert observed.json()["data"]["state"] == "processing"
            assert observed.json()["data"]["visibility"] == "processing"

            deleted = client.delete(f"/v1/documents/{document_id}")
            assert deleted.status_code == 200
            after_delete = client.post("/v1/documents/reconcile-exact", json=request).json()["data"]
            assert after_delete["state"] == "deleted_or_proven_absent"
            assert after_delete["visibility"] == "not_queryable"
