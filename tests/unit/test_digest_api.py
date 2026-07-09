from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from infinity_context_server.api.v1 import digest as digest_api
from pydantic import ValidationError


def test_digest_api_returns_evidence_only_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_ref = SimpleNamespace(
        source_type="manual",
        source_id="src_fact",
        chunk_id=None,
        char_start=None,
        char_end=None,
        quote_preview="Graphiti is the temporal graph projection engine.",
        page_number=None,
        time_start_ms=None,
        time_end_ms=None,
        bbox=None,
    )
    digest = SimpleNamespace(
        digest_id="dig_1",
        topic="Graphiti memory digest",
        rendered_markdown=(
            "Graphiti is the temporal graph projection engine.\n"
            "Add memory_digest as a read-only MCP tool. not_canonical"
        ),
        sections=(
            SimpleNamespace(
                title="Active facts",
                items=(_context_item(source_ref),),
                truncated=False,
            ),
            SimpleNamespace(
                title="Pending suggestions",
                items=(_context_item(source_ref),),
                truncated=False,
            ),
        ),
        source_refs=(source_ref,),
        token_estimate=64,
        diagnostics={"evidence_only": True},
    )
    use_case = RecordingDigestUseCase(digest=digest)
    container = _digest_container(use_case)

    async def resolve_scope(*args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(
            space_id="space_1",
            memory_scope_ids=("scope_1",),
            thread_id=None,
        )

    monkeypatch.setattr(digest_api, "should_retrieve", lambda container: True)
    monkeypatch.setattr(digest_api, "resolve_existing_context_scope", resolve_scope)

    response = asyncio.run(
        digest_api.build_digest(
            digest_api.DigestRequest(
                space_slug="default",
                memory_scope_external_ref="engineering",
                topic="Graphiti memory digest",
                include_pending_suggestions=True,
            ),
            container,
        )
    )

    data = response["data"]
    assert data["diagnostics"]["evidence_only"] is True
    assert "Graphiti is the temporal graph projection engine." in data["rendered_markdown"]
    assert "Add memory_digest as a read-only MCP tool." in data["rendered_markdown"]
    assert "not_canonical" in data["rendered_markdown"]
    assert {section["title"] for section in data["sections"]} >= {
        "Active facts",
        "Pending suggestions",
    }
    assert data["source_refs"]


def test_digest_api_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        digest_api.DigestRequest(topic="hello", unexpected="raw")


def test_digest_route_delegates_success_mapping_to_context_building_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapper = RecordingDigestResponseMapper()
    use_case = RecordingDigestUseCase()
    container = _digest_container(use_case)

    async def resolve_scope(*args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(
            space_id="space_1",
            memory_scope_ids=("scope_1", "scope_2"),
            thread_id="thread_1",
        )

    monkeypatch.setattr(digest_api, "_LEGACY_DIGEST_API_RESPONSES", mapper)
    monkeypatch.setattr(digest_api, "should_retrieve", lambda container: True)
    monkeypatch.setattr(digest_api, "resolve_existing_context_scope", resolve_scope)

    response = asyncio.run(
        digest_api.build_digest(
            digest_api.DigestRequest(
                topic="Graphiti memory digest",
                token_budget=777,
                max_facts=3,
                max_chunks=4,
                max_suggestions=5,
                include_pending_suggestions=False,
                include_superseded=True,
                include_related=False,
            ),
            container,
        )
    )

    assert response == {
        "meta": {"request_id": "req_test"},
        "data": {"digest_id": "mapped_digest", "diagnostics": {"mapped": True}},
    }
    assert mapper.digest_calls == [use_case.digest]
    assert mapper.empty_calls == []
    assert len(use_case.queries) == 1
    query = use_case.queries[0]
    assert query.space_id == "space_1"
    assert query.memory_scope_ids == ("scope_1", "scope_2")
    assert query.thread_id == "thread_1"
    assert query.topic == "Graphiti memory digest"
    assert query.token_budget == 777
    assert query.max_rendered_chars == 1234
    assert query.max_facts == 3
    assert query.max_chunks == 4
    assert query.max_suggestions == 5
    assert query.include_pending_suggestions is False
    assert query.include_superseded is True
    assert query.include_related is False
    assert container.runtime_metrics.calls[0]["diagnostics"] == {"raw": True}


def test_digest_route_delegates_empty_mapping_to_context_building_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapper = RecordingDigestResponseMapper()
    use_case = RecordingDigestUseCase()
    container = _digest_container(use_case)

    monkeypatch.setattr(digest_api, "_LEGACY_DIGEST_API_RESPONSES", mapper)
    monkeypatch.setattr(digest_api, "should_retrieve", lambda container: False)

    response = asyncio.run(
        digest_api.build_digest(
            digest_api.DigestRequest(topic="Graphiti memory digest"),
            container,
        )
    )

    assert response == {
        "meta": {"request_id": "req_test"},
        "data": {"digest_id": "mapped_empty", "diagnostics": {"empty": True}},
    }
    assert mapper.digest_calls == []
    assert mapper.empty_calls == [
        {
            "topic": "Graphiti memory digest",
            "policy_mode": "test_policy",
            "request_id": "req_test",
        }
    ]
    assert use_case.queries == []
    assert container.runtime_metrics.calls[0]["diagnostics"] == {"empty": True}


class RecordingDigestUseCase:
    def __init__(self, digest: object | None = None) -> None:
        self.queries: list[Any] = []
        self.digest = digest or SimpleNamespace(diagnostics={"raw": True})

    async def execute(self, query: object) -> object:
        self.queries.append(query)
        return self.digest


class RecordingDigestResponseMapper:
    def __init__(self) -> None:
        self.digest_calls: list[object] = []
        self.empty_calls: list[dict[str, object]] = []

    def digest_to_response(self, digest: object) -> dict[str, object]:
        self.digest_calls.append(digest)
        return {"digest_id": "mapped_digest", "diagnostics": {"mapped": True}}

    def empty_digest_response(self, **kwargs: object) -> dict[str, object]:
        self.empty_calls.append(kwargs)
        return {
            "meta": {"request_id": kwargs["request_id"]},
            "data": {"digest_id": "mapped_empty", "diagnostics": {"empty": True}},
        }


class RecordingRuntimeMetrics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_context(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _digest_container(use_case: RecordingDigestUseCase) -> SimpleNamespace:
    return SimpleNamespace(
        ids=SimpleNamespace(new_id=lambda prefix: f"{prefix}_test"),
        settings=SimpleNamespace(
            max_context_chars=1234,
            policy_mode=SimpleNamespace(value="test_policy"),
        ),
        build_memory_digest=use_case,
        runtime_metrics=RecordingRuntimeMetrics(),
    )


def _context_item(source_ref: object) -> SimpleNamespace:
    return SimpleNamespace(
        item_id="fact_1",
        item_type="fact",
        text="Graphiti is the temporal graph projection engine.",
        score=0.9,
        source_refs=(source_ref,),
        is_instruction=False,
        diagnostics={
            "memory_scope_id": "scope_1",
            "retrieval_source": "postgres_facts",
        },
    )
