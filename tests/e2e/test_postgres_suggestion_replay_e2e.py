"""PostgreSQL E2E proof for unknown-commit and concurrent approval replay."""

from __future__ import annotations

import asyncio
import os
from hashlib import sha256

import httpx
import pytest
from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_snapshot_from_json,
)
from infinity_context_adapters.postgres import build_async_engine
from infinity_context_adapters.postgres.mappers import suggestion_from_json
from infinity_context_adapters.postgres.suggestion_resolution_receipts import (
    PostgresSuggestionResolutionReceiptRepository,
)
from infinity_context_adapters.postgres.unit_of_work import PostgresUnitOfWork
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.features.memory_facts.public import (
    fact_to_response,
    suggestion_to_response,
)
from infinity_context_server.main import create_app
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


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
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="suggestion_replay",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    await database.recreate()

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database.app_url,
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
            target = await _create_fact(
                client,
                headers,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                marker="POSTGRES_UNKNOWN_COMMIT_PREDECESSOR",
            )
            unknown_id = await _create_suggestion(
                client,
                headers,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                marker="POSTGRES_UNKNOWN_COMMIT_REPLAY",
                target_fact_id=str(target["id"]),
                target_fact_version=int(target["version"]),
                resolution_kind="supersede",
            )
            replay_result = await _assert_unknown_commit_replay(
                client,
                headers,
                unknown_id,
                monkeypatch,
            )

            concurrent_id = await _create_suggestion(
                client,
                headers,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                marker="POSTGRES_CONCURRENT_REPLAY",
            )
            await _assert_concurrent_replay(client, headers, concurrent_id, monkeypatch)
        await _assert_exact_supersession_effects(
            database.app_url,
            suggestion_id=unknown_id,
            predecessor_id=str(target["id"]),
            replay_result=replay_result,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )
        await _assert_single_remember_effects(database.app_url, concurrent_id)
    finally:
        await database.drop()


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
    target_fact_id: str | None = None,
    target_fact_version: int | None = None,
    resolution_kind: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "space_id": space_id,
        "memory_scope_id": memory_scope_id,
        "candidate_text": marker,
        "kind": "architecture_decision",
        "safe_reason": "manual_review",
        "source_refs": [{"source_type": "manual", "source_id": marker.lower()}],
    }
    if target_fact_id is not None:
        payload["target_fact_id"] = target_fact_id
        payload["target_fact_version"] = target_fact_version
        payload["resolution_kind"] = resolution_kind
    response = await client.post(
        "/v1/suggestions",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _create_fact(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    marker: str,
) -> dict[str, object]:
    response = await client.post(
        "/v1/facts",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "text": marker,
            "kind": "architecture_decision",
            "source_refs": [{"source_type": "manual", "source_id": marker.lower()}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _assert_unknown_commit_replay(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    suggestion_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
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
    repeated = await client.post(
        f"/v1/suggestions/{suggestion_id}/approve",
        json={"reason": "confirmed"},
        headers=retry_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json() == replay.json()
    result = dict(replay.json()["data"])
    assert result["suggestion"]["status"] == "approved"
    canonical_fact = await client.get(f"/v1/facts/{result['fact']['id']}", headers=headers)
    assert canonical_fact.status_code == 200
    replayed_fact = dict(result["fact"])
    assert replayed_fact.pop("indexing_status") == "pending"
    assert (
        replayed_fact.pop("content_sha256")
        == sha256(str(replayed_fact["text"]).encode("utf-8")).hexdigest()
    )
    assert replayed_fact == canonical_fact.json()["data"]
    suggestions = await client.get(
        "/v1/suggestions",
        params={
            "space_id": result["suggestion"]["space_id"],
            "memory_scope_id": result["suggestion"]["memory_scope_id"],
            "status": "approved",
        },
        headers=headers,
    )
    assert suggestions.status_code == 200
    canonical_suggestion = next(
        item for item in suggestions.json()["data"] if item["id"] == suggestion_id
    )
    assert result["suggestion"] == canonical_suggestion
    return result


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


async def _assert_single_remember_effects(
    database_url: str,
    suggestion_id: str,
) -> None:
    engine = build_async_engine(database_url)
    try:
        async with engine.connect() as connection:
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


async def _assert_exact_supersession_effects(
    database_url: str,
    *,
    suggestion_id: str,
    predecessor_id: str,
    replay_result: dict[str, object],
    space_id: str,
    memory_scope_id: str,
) -> None:
    engine = build_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            receipt = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT * FROM suggestion_resolution_receipts
                        WHERE suggestion_id = :suggestion_id
                        """
                        ),
                        {"suggestion_id": suggestion_id},
                    )
                )
                .mappings()
                .one()
            )
            successor = dict(replay_result["fact"])
            successor_id = str(successor["id"])
            successor_version = int(successor["version"])
            assert receipt["space_id"] == space_id
            assert receipt["memory_scope_id"] == memory_scope_id
            assert (
                suggestion_to_response(suggestion_from_json(receipt["result_suggestion_json"]))
                == replay_result["suggestion"]
            )
            assert (
                fact_to_response(
                    memory_fact_snapshot_from_json(receipt["result_fact_json"]),
                    receipt["indexing_status"],
                )
                == successor
            )
            assert receipt["result_fact_id"] == successor_id
            assert receipt["result_fact_version"] == successor_version
            assert receipt["affected_fact_ids_json"] == [successor_id, predecessor_id]
            assert receipt["affected_fact_versions_json"] == [successor_version, 2]
            assert len(receipt["outbox_message_ids_json"]) == 2
            assert receipt["temporal_decision_id"] is not None
            assert receipt["relation_id"] is not None

            decision = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT * FROM memory_fact_temporal_decisions
                        WHERE id = :decision_id
                        """
                        ),
                        {"decision_id": receipt["temporal_decision_id"]},
                    )
                )
                .mappings()
                .one()
            )
            relation = (
                (
                    await connection.execute(
                        text("SELECT * FROM memory_fact_relations WHERE id = :relation_id"),
                        {"relation_id": receipt["relation_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert decision["space_id"] == relation["space_id"] == space_id
            assert decision["memory_scope_id"] == relation["memory_scope_id"] == memory_scope_id
            assert decision["source_fact_id"] == relation["source_fact_id"] == successor_id
            assert (
                decision["source_fact_version"]
                == relation["source_fact_version"]
                == successor_version
            )
            assert decision["target_fact_id"] == relation["target_fact_id"] == predecessor_id
            assert decision["target_fact_version"] == relation["target_fact_version"] == 2
            assert relation["temporal_decision_id"] == decision["id"]
            assert relation["valid_from"] == decision["effective_at"]
            assert decision["outbox_message_ids_json"] == receipt["outbox_message_ids_json"]

            outbox_ids = receipt["outbox_message_ids_json"]
            outbox = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT message_key, aggregate_id, aggregate_version
                        FROM memory_outbox
                        WHERE (aggregate_id = :successor_id
                               AND aggregate_version = :successor_version)
                           OR (aggregate_id = :predecessor_id
                               AND aggregate_version = 2)
                        """
                        ),
                        {
                            "successor_id": successor_id,
                            "successor_version": successor_version,
                            "predecessor_id": predecessor_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert len(outbox) == 2
            assert {row["message_key"] for row in outbox} == set(outbox_ids)
            assert {(row["aggregate_id"], row["aggregate_version"]) for row in outbox} == {
                (successor_id, successor_version),
                (predecessor_id, 2),
            }
            exact_counts = (
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
                          (SELECT count(*) FROM memory_fact_temporal_decisions
                           WHERE source_fact_id = :successor_id
                             AND target_fact_id = :predecessor_id),
                          (SELECT count(*) FROM memory_fact_relations
                           WHERE source_fact_id = :successor_id
                             AND target_fact_id = :predecessor_id)
                        """
                    ),
                    {
                        "suggestion_id": suggestion_id,
                        "successor_id": successor_id,
                        "predecessor_id": predecessor_id,
                    },
                )
            ).one()
            assert tuple(exact_counts) == (1, 1, 1, 1)
    finally:
        await engine.dispose()
