"""Mounted recall regression: stale or foreign head hits must not starve good evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_adapters.noop import NoopGraphMemoryAdapter
from infinity_context_core.application import BuildContextUseCase
from infinity_context_core.application import context_collectors as collectors
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.ports.adapters import VectorCandidate, VectorSearchResult

from tests.unit.test_context_provider_consistency import (
    FakeEmbeddingAdapter,
    FakeVectorAdapter,
    auth_headers,
    make_client,
)


def seed(client, *, name, scope="memory_scope_default", text=None):
    response = client.post(
        "/v1/documents",
        headers=auth_headers(),
        json={
            "space_id": "space_client_app",
            "memory_scope_id": scope,
            "title": name,
            "text": text or f"{name}: The release owner is Mara. Keep the signed checklist.",
            "source_type": "document",
            "source_external_id": name,
            "classification": "internal",
        },
    )
    assert response.status_code == 201, response.text
    document = response.json()["data"]
    response = client.get(f"/v1/documents/{document['id']}/chunks", headers=auth_headers())
    assert response.status_code == 200, response.text
    return document, response.json()["data"][0]["id"]


class RankedVector(FakeVectorAdapter):
    def __init__(self, ids):
        super().__init__(ids[0])
        self.ids = ids

    async def search_chunks(self, **kwargs):
        self.search_calls.append(kwargs)
        # Deliberately untrusted index: even a foreign canonical id claims the requested scope.
        return VectorSearchResult.ok(
            [
                VectorCandidate(
                    chunk_id=chunk_id,
                    space_id=kwargs["space_id"],
                    memory_scope_id=kwargs["memory_scope_ids"][0],
                    score=1.0 - index * 0.01,
                    projection_version="v1",
                )
                for index, chunk_id in enumerate(self.ids[: kwargs["limit"]])
            ]
        )


@pytest.mark.parametrize("head_kind", ["missing", "deleted", "foreign"])
def test_mounted_context_recovers_eligible_evidence_below_ineligible_head(
    tmp_path, monkeypatch, head_kind
):
    with make_client(tmp_path) as client:
        _, valid_id = seed(client, name="ELIGIBLE_RELEASE_EVIDENCE")
        if head_kind == "missing":
            bad_id = "chunk_missing_in_canonical_store"
        else:
            bad_doc, bad_id = seed(
                client,
                name="DO_NOT_RENDER_HEAD",
                scope="memory_scope_secondary"
                if head_kind == "foreign"
                else "memory_scope_default",
            )
            if head_kind == "deleted":
                response = client.delete(f"/v1/documents/{bad_doc['id']}", headers=auth_headers())
                assert response.status_code == 200, response.text
        provider = RankedVector((bad_id, valid_id))
        container = client.app.state.container
        packed = []

        class RecordingPacker(ContextPacker):
            def pack(self, **kwargs):
                result = super().pack(**kwargs)
                packed.append(result.bundle)
                return result

        builder = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=provider,
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
            clock=container.clock,
            packer=RecordingPacker(),
        )
        client.app.state.container = replace(container, build_context=builder)
        payload = {
            "space_id": "space_client_app",
            "memory_scope_ids": ["memory_scope_default"],
            "query": "deployment coordinator",
            "max_chunks": 1,
            "max_facts": 0,
            "max_evidence_items": 1,
            "token_budget": 512,
        }
        # The baseline uses the exact old candidate allowance, not a fake failure.
        with monkeypatch.context() as baseline:
            baseline.setattr(
                collectors,
                "_vector_query_candidate_limit",
                collectors._per_query_retrieval_limit,
                raising=False,
            )
            before = client.post("/v1/context", headers=auth_headers(), json=payload)
        after = client.post("/v1/context", headers=auth_headers(), json=payload)
        assert before.status_code == after.status_code == 200, (before.text, after.text)
        previous, current = before.json()["data"], after.json()["data"]
        assert previous["items"] == []
        assert previous["diagnostics"]["keyword_chunks_considered"] == 0
        assert current["diagnostics"]["vector_hydrated_count"] == 1
        assert current["diagnostics"]["stale_vector_drop_count"] == 1
        assert [item["item_id"] for item in current["items"]] == [valid_id]
        assert "ELIGIBLE_RELEASE_EVIDENCE" in current["rendered_text"]
        assert "DO_NOT_RENDER_HEAD" not in current["rendered_text"]
        assert packed[-1].token_estimate <= payload["token_budget"]
        assert all(item["source_refs"] for item in current["items"])
        assert all(not item["is_instruction"] for item in current["items"])
        assert provider.search_calls[0]["limit"] == 1
        assert provider.search_calls[-1]["limit"] == 2


@pytest.mark.parametrize("total_limit", [0, 1, 2, 5, 30, 200, 2000])
@pytest.mark.parametrize("query_count", [1, 2, 8])
def test_vector_overfetch_is_bounded_by_existing_hydration_pool(total_limit, query_count):
    actual = collectors._vector_query_candidate_limit(
        total_limit=total_limit, query_count=query_count
    )
    original = collectors._per_query_retrieval_limit(
        total_limit=total_limit, query_count=query_count
    )
    assert actual == min(collectors._candidate_pool_limit(total_limit), 2 * original)
    assert 0 <= actual <= 240
