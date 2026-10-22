from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryIdempotencyRecordRow
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.document_identity_test_support import (
    document_write_counts,
    downgrade_document_identity,
)

HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    with TestClient(app) as http:
        yield http


def payload(text: str, source: str = "identity-source"):
    return {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "title": "Document identity",
        "text": text,
        "source_type": "document",
        "source_external_id": source,
        "classification": "internal",
    }


@pytest.mark.parametrize(
    "left,right",
    (
        ("return UserID", "return userid"),
        ("if x:\n    return 1\nreturn 2", "if x:\n    return 1\n    return 2"),
    ),
)
def test_new_documents_do_not_fold_case_or_indentation(client, left, right):
    first = client.post("/v1/documents", json=payload(left), headers=HEADERS)
    second = client.post("/v1/documents", json=payload(right, "other"), headers=HEADERS)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    second_id = second.json()["data"]["id"]
    chunks = client.get(f"/v1/documents/{second_id}/chunks", headers=HEADERS).json()["data"]
    assert [chunk["text"] for chunk in chunks] == [right]
    counts = asyncio.run(document_write_counts(client.app.state.container.engine))
    replay = client.post("/v1/documents", json=payload(right, "other"), headers=HEADERS)
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == second_id
    assert asyncio.run(document_write_counts(client.app.state.container.engine)) == counts


def test_exact_and_line_ending_retries_preserve_new_long_document(client):
    text = "\r\n".join(f"Line {index}: Preserve UserID and  indentation." for index in range(80))
    first = client.post("/v1/documents", json=payload(text), headers=HEADERS)
    for retry_text in (text, text.replace("\r\n", "\n")):
        replay = client.post("/v1/documents", json=payload(retry_text), headers=HEADERS)
        assert replay.status_code == 200, replay.text
        assert replay.json()["data"]["id"] == first.json()["data"]["id"]
        assert replay.json()["data"]["chunk_ids"] == first.json()["data"]["chunk_ids"]


@pytest.mark.parametrize("legacy", (False, True))
def test_explicit_key_changed_content_fails_closed(client, legacy):
    headers = {**HEADERS, "Idempotency-Key": "same-explicit-key"}
    first = client.post("/v1/documents", json=payload("return UserID"), headers=headers)
    document_id = first.json()["data"]["id"]
    if legacy:
        asyncio.run(
            downgrade_document_identity(
                client.app.state.container.engine, document_id, "return UserID", explicit=True
            )
        )
    counts = asyncio.run(document_write_counts(client.app.state.container.engine))
    replay = client.post("/v1/documents", json=payload("return UserID"), headers=headers)
    assert replay.status_code == 200, replay.text
    changed = client.post("/v1/documents", json=payload("return userid"), headers=headers)
    assert changed.status_code == 409
    assert asyncio.run(document_write_counts(client.app.state.container.engine)) == counts


def test_legacy_implicit_receipt_and_content_dedupe_require_source_equality(client):
    first = client.post("/v1/documents", json=payload("return UserID"), headers=HEADERS)
    document_id = first.json()["data"]["id"]
    asyncio.run(
        downgrade_document_identity(
            client.app.state.container.engine, document_id, "return UserID", explicit=False
        )
    )
    exact = client.post("/v1/documents", json=payload("return UserID"), headers=HEADERS)
    assert exact.status_code == 200 and exact.json()["data"]["id"] == document_id
    for source in ("identity-source", "other-origin"):
        changed = client.post(
            "/v1/documents", json=payload("return userid", source), headers=HEADERS
        )
        assert changed.status_code in (200, 201), changed.text
        assert changed.json()["data"]["id"] != document_id
    # Ordinary body-only dedupe has historically ignored title/source labels.
    relabeled = {**payload("return UserID", "renamed-origin"), "title": "Renamed"}
    result = client.post("/v1/documents", json=relabeled, headers=HEADERS)
    assert result.status_code == 200 and result.json()["data"]["id"] == document_id


def test_lossy_legacy_source_is_never_guessed_or_rebound(client):
    text = "# Build Protocol\nDecision: Keep SQLite"
    headers = {**HEADERS, "Idempotency-Key": "lossy-explicit"}
    first = client.post("/v1/documents", json=payload(text), headers=headers)
    document_id = first.json()["data"]["id"]
    asyncio.run(
        downgrade_document_identity(
            client.app.state.container.engine, document_id, text, explicit=True
        )
    )
    ambiguous = client.post("/v1/documents", json=payload(text), headers=headers)
    assert ambiguous.status_code == 409
    new = client.post("/v1/documents", json=payload(text), headers=HEADERS)
    assert new.status_code == 201 and new.json()["data"]["id"] != document_id
    replay = client.post("/v1/documents", json=payload(text), headers=HEADERS)
    assert replay.status_code == 200 and replay.json()["data"]["id"] == new.json()["data"]["id"]


@pytest.mark.parametrize(
    "corruption", ("wrong_type", "wrong_chunk", "missing_chunk", "invalid_span")
)
def test_document_receipts_cannot_replay_corrupt_canonical_evidence(client, corruption):
    headers = {**HEADERS, "Idempotency-Key": "corrupt-key"}
    first = client.post("/v1/documents", json=payload("return UserID"), headers=headers)
    document_id = first.json()["data"]["id"]

    async def corrupt():
        async with AsyncSession(client.app.state.container.engine) as session:
            if corruption == "wrong_type":
                record = (
                    await session.execute(
                        select(MemoryIdempotencyRecordRow).where(
                            MemoryIdempotencyRecordRow.result_id == document_id
                        )
                    )
                ).scalar_one()
                record.result_type = "fact"
            else:
                chunk = (
                    await session.execute(
                        select(MemoryChunkRow).where(MemoryChunkRow.document_id == document_id)
                    )
                ).scalar_one()
                if corruption == "missing_chunk":
                    chunk.status = "deleted"
                elif corruption == "invalid_span":
                    chunk.char_end = chunk.char_start + len(chunk.text) - 1
                else:
                    chunk.text = "Unrelated stored evidence"
            await session.commit()

    asyncio.run(corrupt())
    replay = client.post("/v1/documents", json=payload("return UserID"), headers=headers)
    assert replay.status_code == 500
    assert replay.json()["error"]["code"] == "memory.internal"


@pytest.mark.parametrize("changed", (False, True))
def test_flush_and_commit_conflicts_recover_only_from_fresh_validated_reads(client, changed):
    headers = {**HEADERS, "Idempotency-Key": "forced-write-conflict"}
    original = payload("return UserID")
    first = client.post("/v1/documents", json=original, headers=headers)
    container = client.app.state.container
    counts = asyncio.run(document_write_counts(container.engine))
    hidden = _HideInitialDocumentReads(container.ingest_document._uow_factory)
    container.ingest_document._uow_factory = hidden
    request = {**original, "text": "return userid"} if changed else original
    replay = client.post("/v1/documents", json=request, headers=headers)
    assert replay.status_code == (409 if changed else 200), replay.text
    assert hidden.opened == 2
    if not changed:
        assert hidden.flush_conflicts == 1
        assert replay.json()["data"]["id"] == first.json()["data"]["id"]
    assert asyncio.run(document_write_counts(container.engine)) == counts


def test_recovery_of_shared_body_binds_the_losing_explicit_key(client):
    original = payload("return UserID")
    first = client.post(
        "/v1/documents", json=original, headers={**HEADERS, "Idempotency-Key": "winner"}
    )
    container = client.app.state.container
    counts = asyncio.run(document_write_counts(container.engine))
    hidden = _HideInitialDocumentReads(container.ingest_document._uow_factory)
    container.ingest_document._uow_factory = hidden
    loser_headers = {**HEADERS, "Idempotency-Key": "loser"}
    recovered = client.post("/v1/documents", json=original, headers=loser_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["id"] == first.json()["data"]["id"]
    assert hidden.opened == 2 and hidden.flush_conflicts == 1
    # A returned successful replay must have durably bound its caller key.
    changed = client.post(
        "/v1/documents", json={**original, "text": "return userid"}, headers=loser_headers
    )
    assert changed.status_code == 409, changed.text
    assert asyncio.run(document_write_counts(container.engine)) == counts


class _HideInitialDocumentReads:
    def __init__(self, delegate):
        self.delegate = delegate
        self.opened = 0
        self.flush_conflicts = 0

    def __call__(self):
        self.opened += 1
        uow = self.delegate()
        return _InitialDocumentReadsUow(uow, self) if self.opened == 1 else uow


class _InitialDocumentReadsUow:
    def __init__(self, delegate, owner):
        self.delegate, self.owner = delegate, owner

    async def __aenter__(self):
        await self.delegate.__aenter__()
        self.documents = _InitialDocumentRepository(self.delegate.documents, self.owner)
        self.idempotency = _InitialReceiptRepository(self.delegate.idempotency)
        return self

    async def __aexit__(self, *args):
        return await self.delegate.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _InitialDocumentRepository:
    def __init__(self, delegate, owner):
        self.delegate, self.owner = delegate, owner

    async def find_active_by_content_hash(self, **_kwargs):
        return None

    async def create(self, document):
        try:
            return await self.delegate.create(document)
        except MemoryConflictError:
            self.owner.flush_conflicts += 1
            raise

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _InitialReceiptRepository:
    def __init__(self, delegate):
        self.delegate = delegate

    async def find(self, **_kwargs):
        return None

    def __getattr__(self, name):
        return getattr(self.delegate, name)
