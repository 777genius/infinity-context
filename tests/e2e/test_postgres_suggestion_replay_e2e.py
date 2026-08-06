"""PostgreSQL E2E proof for unknown-commit and concurrent approval replay."""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest
from infinity_context_adapters.postgres import build_async_engine
from infinity_context_adapters.postgres.suggestion_resolution_receipts import (
    PostgresSuggestionResolutionReceiptRepository,
)
from infinity_context_adapters.postgres.unit_of_work import PostgresUnitOfWork
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from sqlalchemy import text
from sqlalchemy.engine import make_url


def test_postgres_suggestion_approval_replay_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_postgres_replay(database_url, monkeypatch))


async def _assert_postgres_replay(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    database_name = f"suggestion_replay_{uuid.uuid4().hex}"
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    app_url = parsed.set(
        drivername="postgresql+asyncpg",
        database=database_name,
    ).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=app_url,
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    headers = {"Authorization": "Bearer root-token"}
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://memory.test",
            ) as client,
        ):
            space_id, memory_scope_id = await _create_scope(client, headers)
            unknown_id = await _create_suggestion(
                client,
                headers,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                marker="POSTGRES_UNKNOWN_COMMIT_REPLAY",
            )
            await _assert_unknown_commit_replay(client, headers, unknown_id, monkeypatch)

            concurrent_id = await _create_suggestion(
                client,
                headers,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                marker="POSTGRES_CONCURRENT_REPLAY",
            )
            await _assert_concurrent_replay(client, headers, concurrent_id, monkeypatch)
        await _assert_single_effects(app_url, unknown_id, concurrent_id)
    finally:
        admin = await asyncpg.connect(admin_dsn)
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            await admin.close()


async def _create_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str]:
    space = await client.post(
        "/v1/spaces",
        json={"slug": "replay", "name": "Replay"},
        headers=headers,
    )
    space_id = str(space.json()["data"]["id"])
    memory_scope = await client.post(
        "/v1/memory-scopes",
        json={"space_id": space_id, "external_ref": "default", "name": "Default"},
        headers=headers,
    )
    return space_id, str(memory_scope.json()["data"]["id"])


async def _create_suggestion(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    marker: str,
) -> str:
    response = await client.post(
        "/v1/suggestions",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "candidate_text": marker,
            "kind": "architecture_decision",
            "safe_reason": "manual_review",
            "source_refs": [{"source_type": "manual", "source_id": marker.lower()}],
        },
        headers=headers,
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _assert_unknown_commit_replay(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    suggestion_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_commit = PostgresUnitOfWork.commit
    raised = False

    async def raise_after_commit(self) -> None:
        nonlocal raised
        await original_commit(self)
        if not raised:
            raised = True
            raise RuntimeError("commit outcome unknown")

    retry_headers = {**headers, "Idempotency-Key": "pg-unknown-commit"}
    with monkeypatch.context() as scoped:
        scoped.setattr(PostgresUnitOfWork, "commit", raise_after_commit)
        with pytest.raises(RuntimeError, match="commit outcome unknown"):
            await client.post(
                f"/v1/suggestions/{suggestion_id}/approve",
                json={"reason": "confirmed"},
                headers=retry_headers,
            )
    replay = await client.post(
        f"/v1/suggestions/{suggestion_id}/approve",
        json={"reason": "confirmed"},
        headers=retry_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["suggestion"]["status"] == "approved"


async def _assert_concurrent_replay(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    suggestion_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_get = PostgresSuggestionResolutionReceiptRepository.get
    arrivals = 0
    both_ready = asyncio.Event()

    async def synchronized_get(self, **kwargs):
        nonlocal arrivals
        result = await original_get(self, **kwargs)
        if result is None and arrivals < 2:
            arrivals += 1
            if arrivals == 2:
                both_ready.set()
            await asyncio.wait_for(both_ready.wait(), timeout=10)
        return result

    retry_headers = {**headers, "Idempotency-Key": "pg-concurrent-approve"}
    with monkeypatch.context() as scoped:
        scoped.setattr(PostgresSuggestionResolutionReceiptRepository, "get", synchronized_get)
        first, second = await asyncio.gather(
            client.post(
                f"/v1/suggestions/{suggestion_id}/approve",
                json={"reason": "confirmed"},
                headers=retry_headers,
            ),
            client.post(
                f"/v1/suggestions/{suggestion_id}/approve",
                json={"reason": "confirmed"},
                headers=retry_headers,
            ),
        )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    mismatch = await client.post(
        f"/v1/suggestions/{suggestion_id}/approve",
        json={"reason": "changed"},
        headers=retry_headers,
    )
    assert mismatch.status_code == 409


async def _assert_single_effects(
    database_url: str,
    unknown_id: str,
    concurrent_id: str,
) -> None:
    engine = build_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            for suggestion_id in (unknown_id, concurrent_id):
                counts = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM suggestion_resolution_receipts
                               WHERE suggestion_id = :suggestion_id),
                              (SELECT count(*) FROM memory_facts fact
                               JOIN memory_suggestions suggestion
                                 ON suggestion.candidate_text = fact.text
                               WHERE suggestion.id = :suggestion_id),
                              (SELECT count(*) FROM memory_outbox outbox
                               JOIN memory_facts fact ON fact.id = outbox.aggregate_id
                               JOIN memory_suggestions suggestion
                                 ON suggestion.candidate_text = fact.text
                               WHERE suggestion.id = :suggestion_id)
                            """
                        ),
                        {"suggestion_id": suggestion_id},
                    )
                ).one()
                assert tuple(counts) == (1, 1, 1)
    finally:
        await engine.dispose()
