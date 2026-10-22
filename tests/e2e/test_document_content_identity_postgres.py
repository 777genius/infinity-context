"""Mounted HTTP + canonical PostgreSQL proof for versioned document identity."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_locator_retrieval_indexes,
    upgrade_schema,
)
from infinity_context_adapters.postgres.projected_document_ingestion import _request_fingerprint
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkEnsureScopeAdmission,
)
from infinity_context_core.application.dto import EnsureScopeCommand, IngestDocumentCommand
from infinity_context_core.application.use_cases.ensure_scope import EnsureScopeUseCase
from infinity_context_core.application.use_cases.ingest_document import IngestDocumentUseCase
from infinity_context_core.features.document_ingestion.public import legacy_document_content_digest
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.features.document_ingestion import public as document_http
from infinity_context_server.main import create_app
from postgres_test_database import STRICT_V4_TEST_ROLE_PASSWORD, PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.engine import make_url
from test_strict_v4_writer_fence_postgres import (
    _ExactDocumentAuthority,
    _seed_strict_document_run,
)

from tests.document_identity_test_support import (
    document_write_counts,
    downgrade_document_identity,
)


def test_document_identity_http_and_projection_compatibility_postgres() -> None:
    asyncio.run(_ordinary_and_projected(_database_url()))


def test_managed_document_identity_preserves_strict_v4_receipts_postgres() -> None:
    asyncio.run(_managed_http(_database_url()))


def _database_url() -> str:
    url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    return url


def _body(text_value: str, source: str, scope: dict) -> dict:
    return {
        **scope,
        "title": "Identity HTTP proof",
        "text": text_value,
        "source_type": "document",
        "source_external_id": source,
        "classification": "internal",
    }


def _app(url: str):
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=url,
            auto_create_schema=False,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )


async def _ordinary_and_projected(url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(url, prefix="document_identity", asyncpg=asyncpg)
    await database.recreate()
    app = None
    try:
        migration_engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(migration_engine)
            await build_locator_retrieval_indexes(migration_engine)
        finally:
            await migration_engine.dispose()
        app = _app(database.app_url)
        engine = app.state.container.engine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            first = await client.post(
                "/v1/documents",
                json=_body(
                    "return UserID",
                    "first",
                    {"space_slug": "identity-http", "memory_scope_external_ref": "default"},
                ),
            )
            assert first.status_code == 201, first.text
            first_data = first.json()["data"]
            scope = {key: first_data[key] for key in ("space_id", "memory_scope_id")}
            changed = await client.post(
                "/v1/documents", json=_body("return userid", "second", scope)
            )
            assert changed.status_code == 201
            assert changed.json()["data"]["id"] != first_data["id"]
            chunks = await client.get(f"/v1/documents/{changed.json()['data']['id']}/chunks")
            assert [item["text"] for item in chunks.json()["data"]] == ["return userid"]

            await downgrade_document_identity(
                engine, first_data["id"], "return UserID", explicit=False
            )
            exact = await client.post("/v1/documents", json=_body("return UserID", "first", scope))
            assert exact.status_code == 200 and exact.json()["data"]["id"] == first_data["id"]
            # The old implicit key also collides, so neither its receipt nor its
            # body-only lookup may return the old case-sensitive evidence.
            colliding = await client.post(
                "/v1/documents", json=_body("return userid", "first", scope)
            )
            assert colliding.status_code == 200
            assert colliding.json()["data"]["id"] == changed.json()["data"]["id"]

            for left, right in (
                ("if x:\n    return 1\nreturn 2", "if x:\n    return 1\n    return 2"),
                ("document-content-v2:hello", "hello"),
            ):
                a = await client.post("/v1/documents", json=_body(left, "left", scope))
                assert a.status_code == 201
                await downgrade_document_identity(
                    engine, a.json()["data"]["id"], left, explicit=False
                )
                b = await client.post("/v1/documents", json=_body(right, "right", scope))
                assert b.status_code == 201 and b.json()["data"]["id"] != a.json()["data"]["id"]

            counts = await document_write_counts(engine)
            same = _body("Concurrent identity UserID", "parallel", scope)
            replies = await asyncio.gather(
                *(
                    client.post("/v1/documents", json=same, headers={"Idempotency-Key": "parallel"})
                    for _ in range(4)
                )
            )
            assert all(reply.status_code in (200, 201) for reply in replies)
            assert len({reply.json()["data"]["id"] for reply in replies}) == 1
            after = await document_write_counts(engine)
            assert after == (counts[0] + 1, counts[1] + 2)
            distinct = await asyncio.gather(
                client.post(
                    "/v1/documents",
                    json=_body("Concurrent UserID", "race-a", scope),
                    headers={"Idempotency-Key": "different-race"},
                ),
                client.post(
                    "/v1/documents",
                    json=_body("Concurrent userid", "race-b", scope),
                    headers={"Idempotency-Key": "different-race"},
                ),
            )
            assert sorted(reply.status_code for reply in distinct) == [201, 409]
            await _assert_projected_http(client, engine, scope)
    finally:
        if app is not None:
            await app.state.container.aclose()
        await database.drop()


async def _assert_projected_http(client, engine, scope) -> None:
    for index, (source, legacy) in enumerate(
        (
            ("return ProjectID", False),
            ("return LegacyID", True),
            ("# Build Protocol\nDecision: Keep SQLite", False),
            ("# Legacy Protocol\nDecision: Keep SQLite", True),
        )
    ):
        body = _body(source, f"projection-{index}", scope)
        body["retrieval_projection"] = {
            "schema_version": "document-retrieval-projection.v1",
            "locator": f"identity-locator-{index}",
            "source_key": f"identity-source-{index}",
            "projection_generation": "generation-v1",
            "sequence_ordinal": 0,
            "actor_keys": [],
            "time_interval": None,
            "relative_time_interval": None,
            "kind": "document_fragment",
            "category": "identity-test",
            "tags": [],
        }
        key = f"projection-key-{index}"
        headers = {"Idempotency-Key": key}
        created = await client.post("/v1/documents", json=body, headers=headers)
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        if legacy:
            request = document_http.LegacyIngestDocumentRequest(**body)
            command = document_http.legacy_ingest_document_command_from_request(
                request,
                command_factory=IngestDocumentCommand,
                space_id=scope["space_id"],
                memory_scope_id=scope["memory_scope_id"],
                thread_id=None,
                idempotency_key=key,
            )
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE memory_documents SET content_hash=:hash WHERE id=:id"),
                    {"id": data["id"], "hash": legacy_document_content_digest(source)},
                )
                await connection.execute(
                    text(
                        "UPDATE memory_document_projection_receipts "
                        "SET request_fingerprint_sha256=:hash WHERE document_id=:id"
                    ),
                    {"id": data["id"], "hash": _request_fingerprint(command, legacy=True)},
                )
        exact = await client.post("/v1/documents", json=body, headers=headers)
        lossy_legacy = legacy and source.startswith("#")
        assert exact.status_code == (409 if lossy_legacy else 200), exact.text
        if not lossy_legacy:
            assert exact.json()["data"]["id"] == data["id"]
            assert exact.json()["data"]["chunk_ids"] == data["chunk_ids"]
        for replay_headers in (headers, {}):
            changed = await client.post(
                "/v1/documents", json={**body, "text": source.lower()}, headers=replay_headers
            )
            assert changed.status_code == 409, changed.text
        locator_replay = await client.post("/v1/documents", json=body)
        assert locator_replay.status_code == (409 if lossy_legacy else 200)
        if index == 0:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET char_end=char_start+length(text)-1 "
                        "WHERE document_id=:id"
                    ),
                    {"id": data["id"]},
                )
            invalid_receipt = await client.post("/v1/documents", json=body, headers=headers)
            invalid_locator = await client.post("/v1/documents", json=body)
            assert invalid_receipt.status_code == invalid_locator.status_code == 409


async def _managed_http(url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(url, prefix="managed_identity_http", asyncpg=asyncpg)
    await database.recreate()
    role, engine, app = None, None, None
    try:
        migration_engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(migration_engine)
        finally:
            await migration_engine.dispose()
        raw = await database.connect()
        try:
            await _seed_strict_document_run(raw)
        finally:
            await raw.close()
        role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer", suffix="document_writer"
        )
        runtime = make_url(database.app_url).set(
            username=role, password=STRICT_V4_TEST_ROLE_PASSWORD
        )
        engine = build_async_engine(runtime.render_as_string(hide_password=False))
        clock = SystemClock()
        uow = PostgresUnitOfWorkFactory(session_factory=build_session_factory(engine), clock=clock)
        authority = _ExactDocumentAuthority()
        scope = await ManagedBenchmarkEnsureScopeAdmission(
            uow_factory=uow,
            inner=EnsureScopeUseCase(uow_factory=uow, clock=clock),
            strict_v4_authority=authority,
        ).execute(
            EnsureScopeCommand(
                space_slug="strict-v4-document-graph",
                memory_scope_external_ref="corpus-1",
                thread_external_ref="thread-1",
            )
        )
        app = _app(database.app_url)
        ingest = IngestDocumentUseCase(
            uow_factory=uow, clock=clock, ids=UuidIdGenerator(), strict_v4_authority=authority
        )
        object.__setattr__(app.state.container, "ingest_document", ingest)
        body = _body(
            "return ManagedID",
            "managed-source",
            {
                "space_id": str(scope.space_id),
                "memory_scope_id": str(scope.memory_scope_id),
                "thread_id": str(scope.thread_id),
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            first = await client.post("/v1/documents", json=body)
            assert first.status_code == 201, first.text
            replay = await client.post("/v1/documents", json=body)
            assert replay.status_code == 200
            assert replay.json()["data"]["id"] == first.json()["data"]["id"]
            for headers in ({}, {"Idempotency-Key": "caller-key"}):
                collision = await client.post(
                    "/v1/documents", json={**body, "text": "return managedid"}, headers=headers
                )
                assert collision.status_code == 409, collision.text
            async with app.state.container.engine.connect() as connection:
                record = (
                    await connection.execute(
                        text("SELECT key,fingerprint FROM memory_idempotency_records")
                    )
                ).one()
                assert record.key.startswith("managed-benchmark-document-v4-")
                assert record.fingerprint == legacy_document_content_digest(body["text"])
    finally:
        if app is not None:
            await app.state.container.aclose()
        if engine is not None:
            await engine.dispose()
        if role is not None:
            await database.drop_runtime_roles(role)
        await database.drop()
