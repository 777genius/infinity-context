from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infinity_context_core.application.context_ranked_evidence_selection import (
    RankedEvidenceBudget,
    select_ranked_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef
from infinity_context_server.api.v1 import context as context_api
from infinity_context_server.config import MemoryPolicyMode
from infinity_context_server.features.context_building import public as context_public

_RANKED_DIAGNOSTIC_KEYS = (
    "ranked_evidence_candidate_count",
    "ranked_evidence_projection_candidate_count",
    "ranked_evidence_selectable_candidate_count",
    "ranked_evidence_eligible_candidate_count",
    "ranked_evidence_returned_count",
    "ranked_evidence_compact_projection_count",
    "ranked_evidence_source_diversity_count",
    "ranked_evidence_budget_drop_count",
    "ranked_evidence_item_budget_drop_count",
    "ranked_evidence_token_budget_drop_count",
    "ranked_evidence_char_budget_drop_count",
    "ranked_evidence_instruction_drop_count",
    "ranked_evidence_unsafe_source_drop_count",
    "ranked_evidence_source_dedupe_drop_count",
)


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-test"


class _Metrics:
    def record_context(self, **kwargs: object) -> None:
        self.last = kwargs


class _BuildContext:
    def __init__(self) -> None:
        self.query = None

    async def execute(self, query):
        self.query = query
        items = tuple(
            ContextItem(
                item_id=f"rank-{index}",
                item_type="chunk",
                text=f"evidence {index} ".ljust(120, "x"),
                score=1.0 - index / 1000,
                source_refs=(
                    SourceRef(
                        source_type="episode",
                        source_id=f"session-{index}",
                    ),
                ),
            )
            for index in range(200)
        )
        selected = select_ranked_evidence(
            bundle_id="ctx-test",
            items=items,
            query=query.query,
            budget=RankedEvidenceBudget(
                max_items=query.selection_item_limit or 0,
                max_tokens=query.token_budget,
                max_chars=query.max_rendered_chars,
            ),
        ).bundle
        padded_diagnostics = {
            **{f"bounded_metadata_padding_{index:03}": index for index in range(300)},
            **selected.diagnostics,
            "ranked_evidence_internal_detail": 999,
        }
        return replace(selected, diagnostics=padded_diagnostics)


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _BuildContext]:
    scope = SimpleNamespace(
        space_id="space-1",
        memory_scope_ids=("scope-1",),
        thread_id=None,
    )

    async def resolve_scope(*args: object, **kwargs: object):
        return scope

    monkeypatch.setattr(context_api, "resolve_existing_context_scope", resolve_scope)
    build_context = _BuildContext()
    container = SimpleNamespace(
        ids=_Ids(),
        build_context=build_context,
        runtime_metrics=_Metrics(),
        settings=SimpleNamespace(
            policy_mode=MemoryPolicyMode.ACTIVE_CONTEXT,
            service_token=None,
            max_context_chars=18_000,
        ),
    )
    app = FastAPI()
    app.state.container = container
    app.include_router(context_api.router, prefix="/v1")
    return TestClient(app), build_context


def test_benchmark_search_http_returns_top_200_and_all_ranked_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, build_context = _client(monkeypatch)

    with client:
        response = client.post(
            "/v1/context/benchmark-search",
            json={
                "space_id": "space-1",
                "memory_scope_ids": ["scope-1"],
                "query": "benchmark evidence",
                "token_budget": 16_000,
                "max_evidence_items": 200,
            },
        )
        openapi = client.get("/openapi.json")

    assert response.status_code == 200, response.text
    assert "/v1/context/benchmark-search" not in openapi.json()["paths"]
    assert build_context.query.selection_mode == "ranked_evidence"
    assert build_context.query.selection_item_limit == 200
    assert build_context.query.max_rendered_chars == 64_000
    assert len(response.json()["data"]["items"]) == 200
    diagnostics = response.json()["data"]["diagnostics"]
    ranked_diagnostics = {
        key: value for key, value in diagnostics.items() if key.startswith("ranked_evidence_")
    }
    assert tuple(ranked_diagnostics) == _RANKED_DIAGNOSTIC_KEYS
    assert ranked_diagnostics["ranked_evidence_candidate_count"] == 200
    assert ranked_diagnostics["ranked_evidence_returned_count"] == 200
    assert ranked_diagnostics["ranked_evidence_source_diversity_count"] == 200
    assert ranked_diagnostics["ranked_evidence_budget_drop_count"] == 0


def test_benchmark_search_http_rejects_more_than_200_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, build_context = _client(monkeypatch)

    with client:
        response = client.post(
            "/v1/context/benchmark-search",
            json={
                "space_id": "space-1",
                "memory_scope_ids": ["scope-1"],
                "query": "benchmark evidence",
                "max_evidence_items": 201,
            },
        )

    assert response.status_code == 422
    assert build_context.query is None


@pytest.mark.parametrize(
    ("token_budget", "deployment_max_context_chars", "expected"),
    [
        (64, 18_000, 18_000),
        (16_000, 18_000, 64_000),
        (25_600, 18_000, 102_400),
        (64_000, 18_000, 256_000),
    ],
)
def test_benchmark_context_char_budget(
    token_budget: int,
    deployment_max_context_chars: int,
    expected: int,
) -> None:
    assert (
        context_public.benchmark_context_char_budget(
            token_budget=token_budget,
            deployment_max_context_chars=deployment_max_context_chars,
        )
        == expected
    )


def test_public_query_mapping_keeps_prompt_selection_defaults() -> None:
    request = context_public.ContextRequest(query="public compatibility")
    scope = SimpleNamespace(
        space_id="space-1",
        memory_scope_ids=("scope-1",),
        thread_id=None,
    )

    query = context_public.build_legacy_context_query_from_request(
        request,
        scope=scope,
        max_rendered_chars=18_000,
    )

    assert query.selection_mode == "prompt_context"
    assert query.selection_item_limit is None
    assert request.max_evidence_items == 12
