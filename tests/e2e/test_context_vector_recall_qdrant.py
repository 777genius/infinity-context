"""Real-store retrieval acceptance; deterministic embeddings, never a live-LLM score."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from infinity_context_adapters.noop import NoopGraphMemoryAdapter
from infinity_context_core.application import BuildContextUseCase
from infinity_context_core.application import context_collectors as collectors
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.ports.adapters import PortStatus, VectorUpsertItem

from tests.context_retrieval_test_support import (
    CONTEXT_CHAR_BUDGET,
    DeterministicBatchEmbeddings,
)
from tests.context_retrieval_test_support import (
    retrieval_context_payload as payload,
)
from tests.e2e.test_context_derived_collection_postgres import postgres_context_runtime


@asynccontextmanager
async def qdrant_runtime():
    url = os.getenv("INFINITY_SANDBOX_QDRANT_URL")
    if not url:
        pytest.skip("requires disposable INFINITY_SANDBOX_QDRANT_URL")
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}, "loopback only"
    pytest.importorskip("qdrant_client")
    from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter
    from qdrant_client import AsyncQdrantClient

    name = f"recall_reserve_{uuid4().hex}"
    provider = QdrantVectorMemoryAdapter(url=url, collection_name=name, vector_size=3)
    admin = AsyncQdrantClient(url=url, trust_env=False)
    try:
        yield provider
    finally:
        if await admin.collection_exists(name):
            await admin.delete_collection(name)
        await admin.close()


async def seed(client, name, *, scope="default"):
    response = await client.post(
        "/v1/documents",
        json={
            "space_slug": "recall-reserve",
            "memory_scope_external_ref": scope,
            "title": name,
            "text": f"{name}: The release owner is Mara. Keep the signed checklist.",
            "source_type": "document",
            "source_external_id": name,
            "classification": "internal",
        },
    )
    assert response.status_code == 201, response.text
    document = response.json()["data"]
    response = await client.get(f"/v1/documents/{document['id']}/chunks")
    assert response.status_code == 200, response.text
    return document, response.json()["data"][0]["id"]


def vector_item(chunk_id, document, vector):
    return VectorUpsertItem(
        chunk_id=chunk_id,
        space_id=document["space_id"],
        memory_scope_id=document["memory_scope_id"],
        thread_id=None,
        text="derived preview is not canonical truth",
        vector=vector,
        projection_version="v1",
        metadata={"canonical_version": 1},
    )


def mount_builder(client, container, provider):
    builder = BuildContextUseCase(
        uow_factory=container.uow_factory,
        ids=container.ids,
        vector_index=provider,
        graph_index=NoopGraphMemoryAdapter(),
        embedder=DeterministicBatchEmbeddings(),
        clock=container.clock,
    )
    client._transport.app.state.container = replace(
        container,
        build_context=builder,
        settings=container.settings.model_copy(update={"max_context_chars": CONTEXT_CHAR_BUDGET}),
    )


@pytest.mark.parametrize("head_kind", ["missing", "deleted", "foreign"])
def test_real_qdrant_reserve_recovers_evidence_without_widening_healthy_context(
    monkeypatch, head_kind
):
    async def exercise():
        async with (
            qdrant_runtime() as provider,
            postgres_context_runtime() as (client, container, _),
        ):
            document, good_id = await seed(client, "ELIGIBLE_RELEASE_EVIDENCE")
            _, tail_id = await seed(client, "UNNEEDED_HEALTHY_TAIL")
            if head_kind == "missing":
                bad_id = f"missing_{uuid4().hex}"
            else:
                bad_doc, bad_id = await seed(
                    client,
                    "DO_NOT_RENDER_HEAD",
                    scope="private-other" if head_kind == "foreign" else "default",
                )
                if head_kind == "deleted":
                    response = await client.delete(f"/v1/documents/{bad_doc['id']}")
                    assert response.status_code == 200, response.text
            # The foreign case deliberately mislabels a derived index row. Postgres must win.
            write = await provider.upsert_chunks(
                (
                    vector_item(bad_id, document, (0.1, 0.2, 0.3)),
                    vector_item(good_id, document, (0.12, 0.22, 0.27)),
                    vector_item(tail_id, document, (0.3, 0.2, 0.1)),
                )
            )
            assert write.status == PortStatus.OK, write.diagnostics
            mount_builder(client, container, provider)
            with monkeypatch.context() as baseline:
                baseline.setattr(
                    collectors,
                    "_vector_query_candidate_limit",
                    collectors._per_query_retrieval_limit,
                )
                before = await client.post("/v1/context", json=payload())
            after = await client.post("/v1/context", json=payload())
            assert before.status_code == after.status_code == 200, (before.text, after.text)
            previous, current = before.json()["data"], after.json()["data"]
            assert previous["items"] == []
            assert previous["diagnostics"]["keyword_chunks_considered"] == 0
            assert current["diagnostics"]["vector_hydrated_count"] == 1
            assert current["diagnostics"]["stale_vector_drop_count"] == 1
            assert [item["item_id"] for item in current["items"]] == [good_id]
            assert "ELIGIBLE_RELEASE_EVIDENCE" in current["rendered_text"]
            assert "DO_NOT_RENDER_HEAD" not in current["rendered_text"]
            assert current["diagnostics"]["max_rendered_chars"] == CONTEXT_CHAR_BUDGET
            assert len(current["rendered_text"]) <= CONTEXT_CHAR_BUDGET
            assert all(
                item["source_refs"] and not item["is_instruction"] for item in current["items"]
            )

            deleted = await provider.delete_chunks_if_version((bad_id,), canonical_version=1)
            assert deleted.status == PortStatus.OK, deleted.diagnostics
            with monkeypatch.context() as baseline:
                baseline.setattr(
                    collectors,
                    "_vector_query_candidate_limit",
                    collectors._per_query_retrieval_limit,
                )
                before = await client.post("/v1/context", json=payload())
            after = await client.post("/v1/context", json=payload())
            assert before.status_code == after.status_code == 200
            previous, current = before.json()["data"], after.json()["data"]
            assert previous["items"] == current["items"]
            assert previous["rendered_text"] == current["rendered_text"]
            assert "UNNEEDED_HEALTHY_TAIL" not in current["rendered_text"]
            assert current["diagnostics"]["vector_hydrated_count"] == 2

    asyncio.run(exercise())


def test_mounted_real_store_query_fanout_records_paired_latency_without_timing_gate(monkeypatch):
    async def exercise():
        from infinity_context_core.application.use_cases import build_context as module

        original = collectors.collect_query_results

        async def serial(queries, search, *, timeout_seconds):
            return await original(queries, search, timeout_seconds=timeout_seconds, concurrency=1)

        plan = QueryExpansionPlan(
            original_query="deployment coordinator",
            expansions=tuple(
                QueryExpansion(query=f"deployment coordinator variant {i}", reason=f"test_{i}")
                for i in range(1, 8)
            ),
        )
        monkeypatch.setattr(module, "build_query_expansion_plan", lambda *args, **kwargs: plan)
        profiles = []
        async with (
            qdrant_runtime() as provider,
            postgres_context_runtime() as (client, container, _),
        ):
            document, good_id = await seed(client, "ELIGIBLE_RELEASE_EVIDENCE")
            write = await provider.upsert_chunks((vector_item(good_id, document, (0.1, 0.2, 0.3)),))
            assert write.status == PortStatus.OK, write.diagnostics

            class MeasuredProvider:
                delay = 0.0
                calls = active = peak = 0

                async def capabilities(self):
                    return await provider.capabilities()

                async def search_chunks(self, **kwargs):
                    self.calls += 1
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    try:
                        if self.delay:
                            await asyncio.sleep(self.delay)
                        return await provider.search_chunks(**kwargs)
                    finally:
                        self.active -= 1

            measured = MeasuredProvider()
            mount_builder(client, container, measured)
            semantic_reference = None
            for delay in (0.0, 0.03):
                measured.delay = delay
                samples = {"serial": [], "bounded": []}
                peaks = {"serial": [], "bounded": []}
                # Alternate order so a fixed warmup/cache direction cannot favor one mode.
                for iteration in range(6):
                    modes = ("serial", "bounded") if iteration % 2 == 0 else ("bounded", "serial")
                    for mode in modes:
                        measured.calls = measured.peak = 0
                        monkeypatch.setattr(
                            collectors,
                            "collect_query_results",
                            serial if mode == "serial" else original,
                        )
                        started = perf_counter()
                        response = await client.post("/v1/context", json=payload())
                        elapsed = perf_counter() - started
                        assert response.status_code == 200, response.text
                        data = response.json()["data"]
                        semantic = (data["items"], data["rendered_text"])
                        if semantic_reference is None:
                            semantic_reference = semantic
                        assert semantic == semantic_reference
                        assert measured.calls == 8
                        assert measured.active == 0
                        assert measured.peak == (1 if mode == "serial" else 4)
                        assert data["diagnostics"]["vector_query_degraded_count"] == 0
                        if iteration:  # Exclude the first paired warmup of each profile.
                            samples[mode].append(round(elapsed * 1000, 3))
                            peaks[mode].append(measured.peak)
                profiles.append(
                    {
                        "injected_delay_ms": delay * 1000,
                        "samples_ms": samples,
                        "median_ms": {
                            mode: statistics.median(values) for mode, values in samples.items()
                        },
                        "peak_inflight": peaks,
                        "provider_calls_per_request": 8,
                        "identical_rendered_evidence": True,
                    }
                )
        report = {
            "kind": "paired_mounted_context_retrieval_not_llm_answer_quality",
            "stores": "real PostgreSQL and real Qdrant",
            "embeddings": "deterministic three-dimensional fixture",
            "query_plan": "fixed eight-variant fixture",
            "baseline": "same collector and candidate policy with serial scheduling reference",
            "candidate": "four-worker bounded scheduling",
            "profiles": profiles,
        }
        destination = os.getenv("INFINITY_CONTEXT_RETRIEVAL_BENCH_REPORT")
        if destination:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))

    asyncio.run(exercise())
