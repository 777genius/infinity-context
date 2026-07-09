import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from infinity_context_server.api.v1 import memory_browser as memory_browser_api


class RecordingBuildMemoryBrowser:
    def __init__(self, result: object) -> None:
        self.result = result
        self.queries: list[object] = []

    async def execute(self, query: object) -> object:
        self.queries.append(query)
        return self.result


def test_memory_browser_delegates_scope_mapping_to_memory_scopes_public(
    monkeypatch: Any,
) -> None:
    memory_scope = SimpleNamespace(id="scope_1")
    result = _browser_result(memory_scope=memory_scope)
    browser = RecordingBuildMemoryBrowser(result)
    container = SimpleNamespace(build_memory_browser=browser)
    mapped_scopes: list[object] = []

    async def resolve_scope(_container: object, **_kwargs: object) -> object:
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1")

    def public_scope_response(scope: object) -> dict[str, str]:
        mapped_scopes.append(scope)
        return {"mapped_by": "memory_scopes_public"}

    monkeypatch.setattr(
        memory_browser_api,
        "resolve_existing_single_scope",
        resolve_scope,
    )
    monkeypatch.setattr(
        memory_browser_api.memory_scopes_feature,
        "memory_scope_to_response",
        public_scope_response,
    )

    response = asyncio.run(
        memory_browser_api.get_memory_browser(
            container=container,
            space_id="space_1",
            memory_scope_id="scope_1",
        )
    )

    assert response["data"]["memory_scope"] == {
        "mapped_by": "memory_scopes_public",
    }
    assert mapped_scopes == [memory_scope]
    assert browser.queries[0].space_id == "space_1"
    assert browser.queries[0].memory_scope_id == "scope_1"


def test_memory_browser_delegates_thread_mapping_to_memory_scopes_public(
    monkeypatch: Any,
) -> None:
    thread = SimpleNamespace(id="thread_1")
    result = _browser_result(memory_scope=_memory_scope(), threads=(thread,))
    browser = RecordingBuildMemoryBrowser(result)
    container = SimpleNamespace(build_memory_browser=browser)
    mapped_threads: list[object] = []

    async def resolve_scope(_container: object, **_kwargs: object) -> object:
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1")

    def public_thread_response(scope_thread: object) -> dict[str, str]:
        mapped_threads.append(scope_thread)
        return {"mapped_by": "memory_scopes_public"}

    monkeypatch.setattr(
        memory_browser_api,
        "resolve_existing_single_scope",
        resolve_scope,
    )
    monkeypatch.setattr(
        memory_browser_api.memory_scopes_feature,
        "thread_to_response",
        public_thread_response,
    )

    response = asyncio.run(
        memory_browser_api.get_memory_browser(
            container=container,
            space_id="space_1",
            memory_scope_id="scope_1",
        )
    )

    assert response["data"]["threads"] == [
        {"mapped_by": "memory_scopes_public"},
    ]
    assert mapped_threads == [thread]


def test_memory_browser_delegates_target_feature_mapping_to_public_seams(
    monkeypatch: Any,
) -> None:
    fact = SimpleNamespace(id="fact_1")
    document = SimpleNamespace(id="doc_1")
    chunk = SimpleNamespace(id="chunk_1")
    extraction_job = SimpleNamespace(id="extraction_1")
    asset = SimpleNamespace(id="asset_1")
    result = _browser_result(
        memory_scope=_memory_scope(),
        facts=(fact,),
        documents=(document,),
        chunks=(chunk,),
        extraction_jobs=(extraction_job,),
        assets=(asset,),
    )
    browser = RecordingBuildMemoryBrowser(result)
    container = SimpleNamespace(build_memory_browser=browser)
    mapped: dict[str, list[object]] = {
        "facts": [],
        "documents": [],
        "chunks": [],
        "extraction_jobs": [],
        "assets": [],
    }

    async def resolve_scope(_container: object, **_kwargs: object) -> object:
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1")

    def public_fact_response(item: object) -> dict[str, str]:
        mapped["facts"].append(item)
        return {"mapped_by": "memory_facts_public"}

    def public_document_response(item: object) -> dict[str, str]:
        mapped["documents"].append(item)
        return {"mapped_by": "document_ingestion_public_document"}

    def public_chunk_response(item: object) -> dict[str, str]:
        mapped["chunks"].append(item)
        return {"mapped_by": "document_ingestion_public_chunk"}

    def public_extraction_response(item: object) -> dict[str, str]:
        mapped["extraction_jobs"].append(item)
        return {"mapped_by": "document_ingestion_public_extraction"}

    def public_asset_response(item: object) -> dict[str, str]:
        mapped["assets"].append(item)
        return {"mapped_by": "document_ingestion_public_asset"}

    monkeypatch.setattr(
        memory_browser_api,
        "resolve_existing_single_scope",
        resolve_scope,
    )
    monkeypatch.setattr(
        memory_browser_api.memory_facts_feature,
        "fact_to_response",
        public_fact_response,
    )
    monkeypatch.setattr(
        memory_browser_api.document_ingestion_feature,
        "document_to_response",
        public_document_response,
    )
    monkeypatch.setattr(
        memory_browser_api.document_ingestion_feature,
        "chunk_to_response",
        public_chunk_response,
    )
    monkeypatch.setattr(
        memory_browser_api.document_ingestion_feature,
        "asset_extraction_to_response",
        public_extraction_response,
    )
    monkeypatch.setattr(
        memory_browser_api.document_ingestion_feature,
        "asset_to_response",
        public_asset_response,
    )

    response = asyncio.run(
        memory_browser_api.get_memory_browser(
            container=container,
            space_id="space_1",
            memory_scope_id="scope_1",
        )
    )

    assert response["data"]["facts"] == [{"mapped_by": "memory_facts_public"}]
    assert response["data"]["documents"] == [
        {"mapped_by": "document_ingestion_public_document"}
    ]
    assert response["data"]["chunks"] == [
        {"mapped_by": "document_ingestion_public_chunk"}
    ]
    assert response["data"]["extraction_jobs"] == [
        {"mapped_by": "document_ingestion_public_extraction"}
    ]
    assert response["data"]["assets"] == [
        {"mapped_by": "document_ingestion_public_asset"}
    ]
    assert mapped == {
        "facts": [fact],
        "documents": [document],
        "chunks": [chunk],
        "extraction_jobs": [extraction_job],
        "assets": [asset],
    }


def test_memory_browser_returns_scope_threads_and_visual_summary(
    monkeypatch: Any,
) -> None:
    memory_scope = _memory_scope()
    result = _browser_result(
        memory_scope=memory_scope,
        threads=(
            SimpleNamespace(
                id="thread_1",
                space_id="space_1",
                memory_scope_id="scope_1",
                external_ref="alex-call",
                status=_enum("active"),
                created_at=_now(),
                updated_at=_now(),
            ),
        ),
        stats={
            "facts": 1,
            "episodes": 1,
            "documents": 1,
            "chunks": 2,
            "extraction_jobs": 1,
            "threads": 1,
            "captures": 1,
            "assets": 1,
            "anchors": 2,
            "context_links": 1,
            "context_link_suggestions": 1,
            "pending_context_link_suggestions": 1,
            "active_context_links": 1,
        },
        visual_summary={
            "status": "review_needed",
            "evidence_count": 7,
            "relationship_count": 1,
            "pending_review_count": 1,
            "active_link_count": 1,
            "processing_job_count": 0,
            "failed_job_count": 0,
            "visible_sources": ["captures"],
            "limit_reached": False,
            "health_hints": ["pending_review"],
        },
        quick_actions=(
            {
                "id": "review_pending_links",
                "label": "Review pending links",
                "priority": 1,
            },
        ),
    )
    browser = RecordingBuildMemoryBrowser(result)
    container = SimpleNamespace(build_memory_browser=browser)

    async def resolve_scope(_container: object, **_kwargs: object) -> object:
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1")

    monkeypatch.setattr(
        memory_browser_api,
        "resolve_existing_single_scope",
        resolve_scope,
    )

    response = asyncio.run(
        memory_browser_api.get_memory_browser(
            container=container,
            space_slug="browser",
            memory_scope_external_ref="project-atlas",
            limit=100,
        )
    )

    data = response["data"]
    assert set(data) == {
        "generated_at",
        "memory_scope",
        "facts",
        "episodes",
        "documents",
        "chunks",
        "extraction_jobs",
        "threads",
        "captures",
        "assets",
        "anchors",
        "context_links",
        "context_link_suggestions",
        "stats",
        "visual_summary",
        "quick_actions",
        "diagnostics",
    }
    assert data["memory_scope"] == {
        "id": "scope_1",
        "space_id": "space_1",
        "external_ref": "project-atlas",
        "name": "Project Atlas",
        "status": "active",
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    assert data["threads"] == [
        {
            "id": "thread_1",
            "space_id": "space_1",
            "memory_scope_id": "scope_1",
            "external_ref": "alex-call",
            "status": "active",
            "created_at": _now().isoformat(),
            "updated_at": _now().isoformat(),
        }
    ]
    assert data["facts"] == []
    assert data["episodes"] == []
    assert data["documents"] == []
    assert data["chunks"] == []
    assert data["extraction_jobs"] == []
    assert data["captures"] == []
    assert data["assets"] == []
    assert data["anchors"] == []
    assert data["context_links"] == []
    assert data["context_link_suggestions"] == []
    assert data["stats"]["active_context_links"] == 1
    assert data["visual_summary"]["status"] == "review_needed"
    assert data["visual_summary"]["evidence_count"] == 7
    assert data["quick_actions"][0]["id"] == "review_pending_links"
    assert data["diagnostics"]["browser_version"] == "memory-browser-v1"
    assert data["diagnostics"]["visual_summary_version"] == "visual-memory-summary-v1"
    assert browser.queries[0].limit == 100


def test_memory_browser_empty_scope_response_includes_visual_next_action(
    monkeypatch: Any,
) -> None:
    async def resolve_scope(_container: object, **_kwargs: object) -> object | None:
        return None

    monkeypatch.setattr(
        memory_browser_api,
        "resolve_existing_single_scope",
        resolve_scope,
    )

    response = asyncio.run(
        memory_browser_api.get_memory_browser(
            container=SimpleNamespace(),
            space_slug="browser",
            memory_scope_external_ref="missing-scope",
        )
    )

    data = response["data"]
    assert data["memory_scope"] is None
    assert data["visual_summary"]["status"] == "empty"
    assert data["visual_summary"]["health_hints"] == ["scope_not_found", "empty_scope"]
    assert data["quick_actions"][0]["id"] == "create_memory_scope"


def _browser_result(
    *,
    memory_scope: object,
    facts: tuple[object, ...] = (),
    documents: tuple[object, ...] = (),
    chunks: tuple[object, ...] = (),
    extraction_jobs: tuple[object, ...] = (),
    threads: tuple[object, ...] = (),
    assets: tuple[object, ...] = (),
    stats: dict[str, int] | None = None,
    visual_summary: dict[str, object] | None = None,
    quick_actions: tuple[dict[str, object], ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        generated_at=_now(),
        memory_scope=memory_scope,
        facts=facts,
        episodes=[],
        documents=documents,
        chunks=chunks,
        extraction_jobs=extraction_jobs,
        threads=threads,
        captures=[],
        assets=assets,
        anchors=[],
        context_links=[],
        context_link_suggestions=[],
        stats=stats or {},
        visual_summary=visual_summary or {},
        quick_actions=quick_actions,
        diagnostics={
            "browser_version": "memory-browser-v1",
            "visual_summary_version": "visual-memory-summary-v1",
            "statuses": {"episode": "active", "chunk": "active"},
        },
    )


def _memory_scope() -> SimpleNamespace:
    return SimpleNamespace(
        id="scope_1",
        space_id="space_1",
        external_ref="project-atlas",
        name="Project Atlas",
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _enum(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)
