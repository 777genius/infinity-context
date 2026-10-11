"""Actual TCP proofs; V2 uses adapter-seeded canonical rows, not production qualification."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from infinity_context_server_harness import (
    _start_logged_process,
    free_port,
    python_env,
    run_infinity_context_server,
    stop_process,
    wait_for_health,
)

_INTERVAL = (
    "How many days passed between the day Morgan started watering a herb garden "
    "and the day Morgan harvested fresh herbs?"
)


def _post(client, path, body):
    response = client.post(path, json=body)
    assert response.is_success
    return response.json()["data"]


@pytest.mark.parametrize("limit", [2, 3, 4])
def test_legacy_temporal_tcp_evidence_and_bounds(tmp_path, limit):
    with (
        run_infinity_context_server(
            tmp_path, extra_env={"MEMORY_MAX_CONTEXT_CHARS": "6000"}
        ) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=30,
        ) as client,
    ):
        texts = [
            "On March 1, 2026 Morgan started watering a herb garden.",
            "On March 9, 2026 Morgan harvested fresh herbs from the garden.",
        ]
        texts += [
            f"Morgan discussed watering and harvesting herbs in garden guide {i}." for i in range(6)
        ]
        documents = []
        for i, text in enumerate(texts):
            doc = _post(
                client,
                "/v1/documents",
                {
                    "space_slug": "small",
                    "memory_scope_external_ref": "garden",
                    "thread_external_ref": "visit",
                    "title": f"Garden note {i}",
                    "text": text,
                    "source_type": "document",
                    "source_external_id": f"garden-note-{i}",
                    "classification": "internal",
                },
            )
            documents.append(doc["id"])
            _post(client, f"/v1/documents/{doc['id']}/process", {})
        for scope, thread in (("other", "visit"), ("garden", "other")):
            doc = _post(
                client,
                "/v1/documents",
                {
                    "space_slug": "small",
                    "memory_scope_external_ref": scope,
                    "thread_external_ref": thread,
                    "title": "Unrelated roof note",
                    "text": "Cedar roofing budget.",
                    "source_type": "document",
                    "source_external_id": f"roof-{scope}-{thread}",
                    "classification": "internal",
                },
            )
            _post(client, f"/v1/documents/{doc['id']}/process", {})
        body = {
            "space_slug": "small",
            "memory_scope_external_ref": "garden",
            "thread_external_ref": "visit",
            "query": _INTERVAL,
            "max_facts": 0,
            "max_chunks": limit,
            "token_budget": 4000,
        }
        data = _post(client, "/v1/context", body)
        for phrase in ("March 1, 2026", "March 9, 2026"):
            assert phrase in data["rendered_text"]
            assert any(phrase in item["text"] for item in data["items"])
        sources = {ref["source_id"] for item in data["items"] for ref in item["source_refs"]}
        assert {"garden-note-0", "garden-note-1"} <= sources
        assert len(data["rendered_text"]) <= 6000
        counters = data["diagnostics"]
        assert counters["keyword_chunks_dropped_by_relevance"] == sum(
            counters[f"keyword_chunks_dropped_by_{reason}"]
            for reason in ("project_identity", "anchor_conflict", "insufficient_relevance")
        )
        ranked = _post(
            client,
            "/v1/context/benchmark-search",
            {**body, "max_chunks": 50, "max_evidence_items": limit},
        )
        assert len(ranked["items"]) <= limit
        assert all(
            any(phrase in item["text"] for item in ranked["items"])
            for phrase in ("March 1, 2026", "March 9, 2026")
        )
        tight = _post(client, "/v1/context", {**body, "token_budget": 64})
        # Legacy accounts item content; rendered header/citations add fixed overhead.
        assert len(tight["items"]) < len(data["items"])
        from infinity_context_core.application.normalize import estimate_tokens

        assert sum(estimate_tokens(item["text"]) + 16 for item in tight["items"]) <= 64
        assert len(tight["rendered_text"]) <= 6000
        for change in (
            {"memory_scope_external_ref": "other"},
            {"thread_external_ref": "other"},
        ):
            isolated = _post(client, "/v1/context", {**body, **change})
            assert not any(
                phrase in isolated["rendered_text"] for phrase in ("March 1, 2026", "March 9, 2026")
            )
        assert client.delete(f"/v1/documents/{documents[1]}").is_success
        missing = _post(client, "/v1/context", body)
        assert "March 9, 2026" not in missing["rendered_text"]


def _serve_v2_ru():
    # Executed only in the test subprocess. Keep normal routes/auth/lifespan.
    import uvicorn
    from infinity_context_adapters.postgres.locator_retrieval import (
        PostgresCanonicalLocatorReader,
        PostgresLocatorCandidateProvider,
    )
    from infinity_context_adapters.postgres.unit_of_work import build_session_factory
    from infinity_context_server import main
    from infinity_context_server.composition import build_container
    from infinity_context_server.config import Settings
    from infinity_context_server.features.context_building.retrieval_service import (
        LocatorRetrievalService,
        RetrievalLaneRuntime,
    )
    from sqlalchemy import text

    if os.getenv("MEMORY_SMALL_ALIASES_OFF") == "true":
        import infinity_context_adapters.postgres.locator_retrieval as lexical

        lexical.generated_keyword_aliases = lambda canonical: ()
        lexical.keyword_family_key = lambda folded: folded
    container = build_container(Settings())
    sessions = build_session_factory(container.engine)

    async def health():
        async with sessions() as session:
            return (await session.execute(text("SELECT 1"))).scalar() == 1

    service = LocatorRetrievalService(
        lanes=(
            RetrievalLaneRuntime(
                "postgres_keyword", PostgresLocatorCandidateProvider(sessions), health
            ),
        ),
        canonical_reader=PostgresCanonicalLocatorReader(sessions),
        service_revision=("a" if os.getenv("MEMORY_SMALL_ALIASES_OFF") == "true" else "b") * 40,
        index_profile_digest="1" * 64,
        profile_kind="test",
    )

    class DeadlineService:
        async def descriptor(self):
            return await service.descriptor()

        async def execute(self, request, *, deadline_monotonic, **kwargs):
            async with asyncio.timeout_at(deadline_monotonic):
                return await service.execute(request, **kwargs)

    async def capture_descriptor():
        descriptor = await service.descriptor()
        await container.engine.dispose()  # next loop must open its own asyncpg connections
        return descriptor

    descriptor = asyncio.run(capture_descriptor())
    Path(os.environ["MEMORY_SMALL_DESCRIPTOR"]).write_text(json.dumps(descriptor.to_dict()))
    with patch.object(
        main,
        "build_container",
        return_value=replace(container, locator_retrieval=DeadlineService()),
    ):
        app = main.create_app()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["MEMORY_PORT"]), log_level="error")


async def _seed_ru(database):
    from infinity_context_adapters.postgres import build_async_engine
    from infinity_context_adapters.postgres.migration_runner import upgrade_schema
    from infinity_context_adapters.postgres.models import (
        MemoryChunkRow,
        MemoryDocumentRow,
        MemoryScopeRow,
        MemorySpaceRow,
        MemoryThreadRow,
    )
    from infinity_context_server.auth_tokens import create_service_token
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = build_async_engine(database.app_url)
    now = datetime.now(UTC)
    words = (
        "встреча",
        "релиз",
        "документ",
        "решение",
        "настройка",
        "встрече",
        "релизер",
        "1000%",
        "draft",
        "retired",
    )
    try:
        await upgrade_schema(engine)
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                MemorySpaceRow(
                    id="space", slug="small", name="Small", created_at=now, updated_at=now
                )
            )
            await session.flush()
            session.add(
                MemoryScopeRow(
                    id="scope",
                    space_id="space",
                    external_ref="ru",
                    name="RU",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                MemoryThreadRow(
                    id="other-thread",
                    space_id="space",
                    memory_scope_id="scope",
                    external_ref="other",
                    created_at=now,
                    updated_at=now,
                )
            )
            rows = []
            for i, word in enumerate(words):
                identity = f"ru-{i}"
                parent = MemoryDocumentRow(
                    id=identity,
                    space_id="space",
                    memory_scope_id="scope",
                    title="Synthetic lexical note",
                    source_type="document",
                    source_external_id=identity,
                    content_hash=identity,
                    classification="internal",
                    retrieval_projected=True,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                session.add(parent)
                await session.flush()
                row = MemoryChunkRow(
                    id=identity,
                    space_id="space",
                    memory_scope_id="scope",
                    document_id=identity,
                    source_type="document",
                    source_external_id=identity,
                    source_hash=identity,
                    kind="document",
                    text=word + " launch",
                    normalized_text=word + " launch",
                    sequence=0,
                    char_start=0,
                    char_end=len(word) + 7,
                    token_estimate=3,
                    classification="internal",
                    created_at=now,
                    updated_at=now,
                    metadata_json={},
                    retrieval_locator=f"lexical-note-{i}",
                    retrieval_source_key=identity,
                    retrieval_projection_generation="test-generation",
                    retrieval_sequence_ordinal=0,
                    retrieval_kind="record_block",
                    retrieval_category="human",
                )
                rows.append(row)
                session.add(row)
                await session.flush()
                if word == "draft":
                    parent.status = "deleted"
            # True same-source neighbors plus a wrong-generation row at radius one.
            seed = rows[1]
            for offset, generation in ((1, "test-generation"), (2, "wrong")):
                values = {
                    column.name: getattr(seed, column.name) for column in seed.__table__.columns
                }
                values.update(
                    id=f"neighbor-{offset}",
                    source_hash=f"neighbor-{offset}",
                    retrieval_locator=f"neighbor-{offset}",
                    sequence=offset,
                    retrieval_sequence_ordinal=1,
                    retrieval_projection_generation=generation,
                    text="Unrelated neighbor.",
                    normalized_text="unrelated neighbor.",
                )
                session.add(MemoryChunkRow(**values))
            rows[9].status = "deleted"
        token = await create_service_token(
            engine=engine,
            now=now,
            token_id="read",
            description="Scoped test read",
            space_id="space",
            memory_scope_ids=("scope",),
            permissions=("memory:read",),
        )
        return token.token, words
    finally:
        await engine.dispose()


@pytest.mark.parametrize("aliases_enabled", [False, True])
def test_v2_ru_adapter_seeded_postgres_tcp_matrix(tmp_path, aliases_enabled):
    from infinity_context_contracts.features.context_building import (
        RetrievalHardFiltersDto,
        RetrievalSoftPreferencesDto,
        RetrievalSourceGenerationDto,
    )
    from postgres_test_database import PostgresTestDatabase

    url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Prerequisite unavailable: disposable PostgreSQL URL; gate incomplete")
    database = PostgresTestDatabase.from_url(
        url, prefix="memory_small_ru", asyncpg=pytest.importorskip("asyncpg")
    )
    asyncio.run(database.recreate())
    server = None
    try:
        token, words = asyncio.run(_seed_ru(database))
        port = free_port()
        descriptor_path = tmp_path / "descriptor.json"
        env = python_env(
            {
                "MEMORY_DEPLOY_PROFILE": "test",
                "MEMORY_DATABASE_URL": database.app_url,
                "MEMORY_AUTO_CREATE_SCHEMA": "false",
                "MEMORY_SERVICE_TOKEN": "test-root",
                "MEMORY_QDRANT_ENABLED": "false",
                "MEMORY_GRAPHITI_ENABLED": "false",
                "MEMORY_EMBEDDINGS_ENABLED": "false",
                "MEMORY_PORT": str(port),
                "MEMORY_SMALL_DESCRIPTOR": str(descriptor_path),
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": str(tmp_path),
                "MEMORY_SMALL_ALIASES_OFF": str(not aliases_enabled).lower(),
            }
        )
        env["PYTHONPATH"] += os.pathsep + str(Path(__file__).parent)
        command = "import runpy,sys; runpy.run_path(sys.argv[1])['_serve_v2_ru']()"
        server = _start_logged_process(
            [sys.executable, "-c", command, str(Path(__file__).resolve())],
            env=env,
            log_dir=tmp_path,
            name="memory-small-ru",
        )
        base_url = f"http://127.0.0.1:{port}"
        wait_for_health(base_url, server)
        descriptor = json.loads(descriptor_path.read_text())
        with httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=5
        ) as client:
            timings = []
            exact_count = morphological_count = negative_false_positives = 0

            def retrieve(query, *, scope=None, filters=None, radius=0):
                filter_payload = RetrievalHardFiltersDto(
                    source_generations=tuple(
                        RetrievalSourceGenerationDto(f"ru-{i}", "test-generation")
                        for i in range(len(words))
                    )
                ).to_dict()
                filter_payload.update(filters or {})
                started = time.perf_counter()
                response = client.post(
                    "/v1/context/retrieve",
                    json={
                        "contract_version": "context-retrieval.v2",
                        "capability_fingerprint": descriptor["capability_fingerprint"],
                        "profile_id": descriptor["profile_id"],
                        "scope": scope
                        or {"space_id": "space", "memory_scope_id": "scope", "thread_id": None},
                        "queries": [{"query_id": "q1", "query": query, "weight_micros": 1000000}],
                        "filters": filter_payload,
                        "soft_preferences": RetrievalSoftPreferencesDto().to_dict(),
                        "bounds": {
                            "candidate_limit": 10,
                            "result_limit": 5,
                            "neighbor_radius": radius,
                            "response_byte_limit": 16384,
                            "deadline_ms": 2000,
                        },
                    },
                )
                timings.append(time.perf_counter() - started)
                return response

            def candidates(response):
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == ("available" if data["candidates"] else "unqualified")
                assert all(
                    outcome["status"] == "available" for outcome in data["provider_outcomes"]
                )
                assert len(response.content) <= 16384 and len(data["candidates"]) <= 5
                return data["candidates"]

            for i, form in enumerate(("встрече", "релизе", "документе", "решении", "настройке")):
                for query in (words[i], form, form + " launch"):
                    first = candidates(retrieve(query))
                    found = any(hit["locator"] == f"lexical-note-{i}" for hit in first)
                    assert found == (aliases_enabled or query == words[i])
                    if query == words[i]:
                        exact_count += int(found)
                    elif query == form:
                        morphological_count += int(found)
                    again = candidates(retrieve(query))
                    assert [(hit["locator"], hit["fused_score"]) for hit in first] == [
                        (hit["locator"], hit["fused_score"]) for hit in again
                    ]
            reverse = candidates(retrieve("встреча"))
            assert any(hit["locator"] == "lexical-note-5" for hit in reverse) == aliases_enabled
            for query in (
                "релиза extra",
                "релиза",
                "неизвестное",
                "что известно о",
                "100%",
                "релиз релизе extra",
            ):
                hits = candidates(retrieve(query))
                legacy_duplicate_signal = not aliases_enabled and query == "релиз релизе extra"
                if query != "релиза":
                    negative_false_positives += int(bool(hits))
                assert (
                    any(hit["locator"] == "lexical-note-6" for hit in hits)
                    == legacy_duplicate_signal
                )
                if query != "релиза" and not legacy_duplicate_signal:
                    assert not hits
            paired_forms = candidates(retrieve("релиз релизе"))
            assert (
                any(hit["locator"] == "lexical-note-1" for hit in paired_forms) == aliases_enabled
            )
            # Existing original-term substring policy is unchanged.
            assert any(hit["locator"] == "lexical-note-6" for hit in paired_forms)
            for scope in (
                {"space_id": "other", "memory_scope_id": "scope", "thread_id": None},
                {"space_id": "space", "memory_scope_id": "other", "thread_id": None},
            ):
                assert retrieve("релиз", scope=scope).status_code == 403
            assert not candidates(retrieve("draft"))
            assert not candidates(retrieve("retired"))
            assert not candidates(
                retrieve(
                    "релиз",
                    scope={
                        "space_id": "space",
                        "memory_scope_id": "scope",
                        "thread_id": "other-thread",
                    },
                )
            )
            assert not candidates(
                retrieve(
                    "релиз",
                    filters={
                        "source_generations": [
                            {"source_key": "ru-1", "projection_generation": "wrong"}
                        ]
                    },
                )
            )
            # Contract rejects contradictory include/exclude filters before retrieval.
            assert (
                retrieve(
                    "релиз",
                    filters={
                        "source_generations": [
                            {"source_key": "ru-1", "projection_generation": "test-generation"}
                        ],
                        "excluded_source_keys": ["ru-1"],
                    },
                ).status_code
                == 400
            )
            hits = candidates(retrieve("релиз", radius=1))
            neighbors = [neighbor for hit in hits for neighbor in hit["neighbors"]]
            assert any(neighbor["locator"] == "neighbor-1" for neighbor in neighbors)
            assert all(
                neighbor["source_key"] == "ru-1" and neighbor["locator"] != "neighbor-2"
                for neighbor in neighbors
            )
            ordered = sorted(timings)
            (tmp_path / "matrix-summary.json").write_text(
                json.dumps(
                    {
                        "aliases_enabled": aliases_enabled,
                        "request_count": len(timings),
                        "exact_positive_count": exact_count,
                        "morphological_positive_count": morphological_count,
                        "negative_false_positive_count": negative_false_positives,
                        "p50_seconds": statistics.median(timings),
                        "p95_seconds": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
                    }
                )
            )
    finally:
        if server is not None:
            stop_process(server)
        asyncio.run(database.drop())
