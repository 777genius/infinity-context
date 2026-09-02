"""Canonical evidence setup shared by focused facts API tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def create_document_chunk(
    client: TestClient,
    *,
    scope: dict[str, str],
    suffix: str,
    headers: dict[str, str],
) -> str:
    document = client.post(
        "/v1/documents",
        json={
            **scope,
            "title": f"Canonical evidence {suffix}",
            "text": f"Canonical evidence marker {suffix}.",
            "source_type": "document",
            "source_external_id": f"evidence-{suffix}",
            "classification": "internal",
        },
        headers=headers,
    )
    assert document.status_code == 201, document.text
    document_id: Any = document.json()["data"]["id"]
    chunks = client.get(f"/v1/documents/{document_id}/chunks", headers=headers)
    assert chunks.status_code == 200, chunks.text
    return str(chunks.json()["data"][0]["id"])


__all__ = ("create_document_chunk",)
