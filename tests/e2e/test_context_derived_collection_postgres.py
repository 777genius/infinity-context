"""Opt-in canonical visibility and resource races for concurrent legacy context."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from infinity_context_adapters.noop import NoopGraphMemoryAdapter, SystemClock
from infinity_context_adapters.postgres import upgrade_schema
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application import BuildContextUseCase
from infinity_context_core.application.context_derived_collection import collect_derived_context
from infinity_context_core.ports.adapters import GraphSearchResult, PortStatus, VectorUpsertItem
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.unit.test_context_derived_collection_integration import (
    sequential_collection,
    without_timings,
)
from tests.unit.test_context_provider_consistency import FakeEmbeddingAdapter, FakeVectorAdapter


@asynccontextmanager
async def postgres_context_runtime():
    url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("requires isolated INFINITY_CONTEXT_TEST_POSTGRES_URL")
    database = PostgresTestDatabase.from_url(
        url, prefix="derived_context", asyncpg=pytest.importorskip("asyncpg")
    )
    await database.recreate()
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database.app_url,
            auto_create_schema=False,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    container = app.state.container
    try:
        await upgrade_schema(container.engine)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            yield client, container, database
    finally:
        await container.aclose()
        await database.drop()


async def seed_document(client):
    response = await client.post(
        "/v1/documents",
        json={
            "space_slug": "derived-context",
            "memory_scope_external_ref": "default",
            "title": "Atlas outbox evidence",
            "text": "Project Atlas uses durable outbox delivery and canonical hydration.",
            "source_type": "document",
            "source_external_id": "atlas-context-evidence",
            "classification": "internal",
        },
    )
    assert response.status_code == 201, response.text
    document = response.json()["data"]
    chunks = await client.get(f"/v1/documents/{document['id']}/chunks")
    assert chunks.status_code == 200, chunks.text
    return document, chunks.json()["data"][0]["id"]


def context_payload():
    return {
        "space_slug": "derived-context",
        "memory_scope_external_ref": "default",
        "query": "Project Atlas outbox canonical hydration",
        "token_budget": 1024,
        "max_chunks": 5,
        "max_facts": 5,
    }


def test_mounted_postgres_context_revalidates_delete_after_early_lane_hydration():
    async def exercise():
        async with postgres_context_runtime() as (client, container, _):
            document, chunk_id = await seed_document(client)
            hydrated = asyncio.Event()
            graph_entered = asyncio.Event()
            release_graph = asyncio.Event()

            class Graph(FakeVectorAdapter):
                async def search(self, **kwargs):
                    graph_entered.set()
                    await release_graph.wait()
                    return GraphSearchResult.ok([])

            builder = BuildContextUseCase(
                uow_factory=container.uow_factory,
                ids=container.ids,
                vector_index=FakeVectorAdapter(chunk_id),
                graph_index=Graph(chunk_id),
                embedder=FakeEmbeddingAdapter(),
                clock=container.clock,
            )
            original = builder._vector_collector

            class SignalHydrated:
                async def collect(self, **kwargs):
                    result = await original.collect(**kwargs)
                    assert any(str(chunk.id) == chunk_id for chunk in result)
                    hydrated.set()
                    return result

            builder._vector_collector = SignalHydrated()
            client._transport.app.state.container = replace(container, build_context=builder)
            operation = asyncio.create_task(client.post("/v1/context", json=context_payload()))
            try:
                async with asyncio.timeout(10):
                    await hydrated.wait()
                    await graph_entered.wait()
                    deletion = await client.delete(f"/v1/documents/{document['id']}")
                    assert deletion.status_code == 200, deletion.text
                    release_graph.set()
                    response = await operation
                assert response.status_code == 200, response.text
                data = response.json()["data"]
                assert data["items"] == []
                assert "durable outbox delivery" not in data["rendered_text"]
                assert data["diagnostics"]["vector_hydrated_count"] == 1
            finally:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(exercise())


def test_postgres_connection_wait_cancellation_closes_uows_and_next_collection_runs():
    async def exercise():
        async with postgres_context_runtime() as (_, _, database):
            engine = create_async_engine(database.app_url, pool_size=1, max_overflow=0)
            factory = PostgresUnitOfWorkFactory(
                session_factory=build_session_factory(engine), clock=SystemClock()
            )
            entered = [asyncio.Event() for _ in range(3)]
            closed = []

            def lane(index):
                async def collect(private):
                    try:
                        async with factory() as uow:
                            entered[index].set()
                            result = await uow._session.execute(text("SELECT 1"))
                            return result.scalar_one()
                    finally:
                        closed.append(index)

                return collect

            try:
                async with engine.connect():
                    operation = asyncio.create_task(
                        collect_derived_context(
                            vector=lane(0), graph=lane(1), rag=lane(2), diagnostics={}
                        )
                    )
                    async with asyncio.timeout(5):
                        await asyncio.gather(*(event.wait() for event in entered))
                        operation.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await operation
                    assert sorted(closed) == [0, 1, 2]
                    assert engine.pool.checkedout() == 1
                assert engine.pool.checkedout() == 0
                async with asyncio.timeout(5):
                    assert await collect_derived_context(
                        vector=lane(0), graph=lane(1), rag=lane(2), diagnostics={}
                    ) == (1, 1, 1)
                assert engine.pool.checkedout() == 0
            finally:
                await engine.dispose()

    asyncio.run(exercise())


def test_populated_qdrant_mounted_context_preserves_output_and_rejects_stale_hit(monkeypatch):
    qdrant_url = os.getenv("INFINITY_SANDBOX_QDRANT_URL")
    if not qdrant_url:
        pytest.skip("requires disposable INFINITY_SANDBOX_QDRANT_URL")

    async def exercise():
        from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter
        from infinity_context_core.application.use_cases import build_context as module
        from qdrant_client import AsyncQdrantClient

        collection = f"derived_context_{uuid4().hex}"
        provider = QdrantVectorMemoryAdapter(
            url=qdrant_url, collection_name=collection, vector_size=3
        )
        admin = AsyncQdrantClient(url=qdrant_url, trust_env=False)
        try:
            async with postgres_context_runtime() as (client, container, _):
                document, chunk_id = await seed_document(client)
                write = await provider.upsert_chunks(
                    (
                        VectorUpsertItem(
                            chunk_id=chunk_id,
                            space_id=document["space_id"],
                            memory_scope_id=document["memory_scope_id"],
                            thread_id=None,
                            text="Project Atlas canonical hydration",
                            vector=(0.1, 0.2, 0.3),
                            projection_version="v1",
                            metadata={"canonical_version": 1},
                        ),
                    )
                )
                assert write.status == PortStatus.OK, write.diagnostics
                builder = BuildContextUseCase(
                    uow_factory=container.uow_factory,
                    ids=container.ids,
                    vector_index=provider,
                    graph_index=NoopGraphMemoryAdapter(),
                    embedder=FakeEmbeddingAdapter(),
                )
                client._transport.app.state.container = replace(container, build_context=builder)
                concurrent = module.collect_derived_context
                monkeypatch.setattr(module, "collect_derived_context", sequential_collection)
                baseline = await client.post("/v1/context", json=context_payload())
                monkeypatch.setattr(module, "collect_derived_context", concurrent)
                candidate = await client.post("/v1/context", json=context_payload())
                assert baseline.status_code == candidate.status_code == 200
                # Route-generated request IDs are deliberately outside semantic equality.
                before, after = baseline.json()["data"], candidate.json()["data"]
                assert without_timings(before) == without_timings(after)
                assert after["diagnostics"]["vector_hydrated_count"] == 1
                assert chunk_id in str(after["items"])
                assert (await client.delete(f"/v1/documents/{document['id']}")).status_code == 200
                stale = await client.post("/v1/context", json=context_payload())
                assert stale.status_code == 200, stale.text
                assert stale.json()["data"]["items"] == []
                assert stale.json()["data"]["diagnostics"]["stale_vector_drop_count"] == 1
        finally:
            if await admin.collection_exists(collection):
                await admin.delete_collection(collection)
            await admin.close()

    asyncio.run(exercise())
