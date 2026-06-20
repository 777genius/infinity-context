import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_core.application import ConsolidateCaptureCommand, ConsolidateCaptureUseCase
from infinity_context_core.domain.entities import Confidence, MemoryKind, SourceRef
from infinity_context_core.ports.auto_memory import (
    CandidateOperation,
    MemoryCandidate,
    SourceProvenance,
)
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.main import create_app


class StaticExtractor:
    version = "duplicate-merge-resolution-test-extractor-v1"
    prompt_version = "duplicate-merge-resolution-test-prompt-v1"
    requires_external_ai = False

    def __init__(self, candidates: tuple[MemoryCandidate, ...]) -> None:
        self._candidates = candidates

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        return self._candidates


def test_duplicate_merge_resolution_endpoint_merges_source_refs(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "duplicate-resolve-merge.db")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Qdrant owns document vector retrieval.",
            space_slug="duplicate-resolve-merge",
            source_id="duplicate-resolve-existing",
        )
        suggestion = _create_duplicate_suggestion(
            client,
            headers=headers,
            space_slug="duplicate-resolve-merge",
            source_id="duplicate-resolve-candidate",
        )
        resolved = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-duplicate",
            json={
                "action": "merge_source_refs",
                "reason": "confirmed semantic duplicate source",
            },
            headers=headers,
        )
        active_facts = _list_facts(client, headers=headers, space_slug="duplicate-resolve-merge")
        pending = _list_suggestions(
            client,
            headers=headers,
            space_slug="duplicate-resolve-merge",
        )

    assert existing.status_code == 201
    assert resolved.status_code == 200, resolved.text
    data = resolved.json()["data"]
    assert data["fact"]["id"] == existing.json()["data"]["id"]
    assert data["fact"]["version"] == 2
    assert {ref["source_id"] for ref in data["fact"]["source_refs"]} == {
        "duplicate-resolve-existing",
        "duplicate-resolve-candidate",
    }
    assert data["suggestion"]["status"] == "approved"
    assert data["suggestion"]["review_payload"]["resolved_duplicate_action"] == (
        "merge_source_refs"
    )
    assert data["suggestion"]["review_payload"]["resolved_duplicate_effect"] == (
        "merge_source_refs_into_existing_fact"
    )
    assert [item["text"] for item in active_facts.json()["data"]] == [
        "Qdrant owns document vector retrieval."
    ]
    assert pending.json()["data"] == []


def test_duplicate_merge_resolution_endpoint_can_keep_candidate_separate(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "duplicate-resolve-separate.db")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Qdrant owns document vector retrieval.",
            space_slug="duplicate-resolve-separate",
            source_id="duplicate-separate-existing",
        )
        suggestion = _create_duplicate_suggestion(
            client,
            headers=headers,
            space_slug="duplicate-resolve-separate",
            source_id="duplicate-separate-candidate",
        )
        resolved = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-duplicate",
            json={
                "action": "keep_separate_fact",
                "reason": "the reviewer confirmed it is a separate note",
            },
            headers=headers,
        )
        active_facts = _list_facts(
            client,
            headers=headers,
            space_slug="duplicate-resolve-separate",
        )

    assert existing.status_code == 201
    assert resolved.status_code == 200, resolved.text
    data = resolved.json()["data"]
    assert data["fact"]["id"] != existing.json()["data"]["id"]
    assert data["fact"]["text"] == "Docs retrieval should use Qdrant vectors."
    assert data["suggestion"]["status"] == "approved"
    assert data["suggestion"]["review_payload"]["resolved_duplicate_action"] == (
        "keep_separate_fact"
    )
    assert data["suggestion"]["review_payload"]["resolved_duplicate_effect"] == (
        "create_new_fact_keep_existing_fact"
    )
    assert sorted(item["text"] for item in active_facts.json()["data"]) == [
        "Docs retrieval should use Qdrant vectors.",
        "Qdrant owns document vector retrieval.",
    ]


def test_duplicate_merge_resolution_rejects_stale_target_fact_version(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "duplicate-resolve-stale.db")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Qdrant owns document vector retrieval.",
            space_slug="duplicate-resolve-stale",
            source_id="duplicate-stale-existing",
        )
        suggestion = _create_duplicate_suggestion(
            client,
            headers=headers,
            space_slug="duplicate-resolve-stale",
            source_id="duplicate-stale-candidate",
        )
        updated = client.patch(
            f"/v1/facts/{existing.json()['data']['id']}",
            json={
                "expected_version": 1,
                "text": "Qdrant owns vector retrieval for document chunks.",
                "reason": "manual edit before duplicate review",
                "source_refs": [{"source_type": "manual", "source_id": "duplicate-stale-edit"}],
            },
            headers=headers,
        )
        stale_resolution = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-duplicate",
            json={
                "action": "merge_source_refs",
                "reason": "try to merge stale duplicate review",
            },
            headers=headers,
        )
        still_pending = _list_suggestions(
            client,
            headers=headers,
            space_slug="duplicate-resolve-stale",
        )

    assert existing.status_code == 201
    assert updated.status_code == 200
    assert stale_resolution.status_code == 409
    assert still_pending.json()["data"][0]["status"] == "pending"


def test_duplicate_merge_review_response_adds_default_options_for_legacy_payload(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "duplicate-legacy-options.db")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Qdrant owns document vector retrieval.",
            space_slug="duplicate-legacy-options",
            source_id="duplicate-legacy-existing",
        )
        response = client.post(
            "/v1/suggestions",
            json={
                "space_slug": "duplicate-legacy-options",
                "memory_scope_external_ref": "default",
                "candidate_text": "Docs retrieval should use Qdrant vectors.",
                "kind": "note",
                "operation": "review",
                "target_fact_id": existing.json()["data"]["id"],
                "target_fact_version": 1,
                "source_refs": [{"source_type": "manual", "source_id": "duplicate-legacy"}],
                "confidence": "medium",
                "trust_level": "medium",
                "safe_reason": "legacy duplicate merge payload",
                "review_payload": {
                    "review_kind": "duplicate_fact_merge",
                    "dedupe_match_type": "semantic_token_overlap",
                },
            },
            headers=headers,
        )

    assert existing.status_code == 201
    assert response.status_code == 201, response.text
    suggestion = response.json()["data"]
    assert suggestion["available_review_actions"] == [
        "approve",
        "reject",
        "expire",
        "resolve_duplicate",
    ]
    assert suggestion["review_resolution_options"][0]["id"] == "merge_source_refs"
    assert suggestion["review_resolution_options"][1]["id"] == "keep_separate_fact"
    assert suggestion["review_payload"]["recommended_action"] == (
        "merge_source_refs_into_existing_fact"
    )
    assert suggestion["review_payload"]["recommended_resolution_action"] == "merge_source_refs"
    assert suggestion["review_payload"]["review_risk"] == "medium"
    assert suggestion["review_payload"]["requires_review"] is True
    assert suggestion["review_payload"]["auto_merge_eligible"] is False
    assert "legacy_payload" in suggestion["review_payload"]["recommendation_reason_codes"]


def _capture_app(tmp_path: Path, database_name: str):
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / database_name}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.AUTO_APPLY_SAFE,
        )
    )


def _create_duplicate_suggestion(
    client: TestClient,
    *,
    headers: dict[str, str],
    space_slug: str,
    source_id: str,
) -> dict[str, object]:
    capture = _create_capture(
        client,
        headers=headers,
        text="Remember: Docs retrieval should use Qdrant vectors.",
        space_slug=space_slug,
    )
    _consolidate(
        client,
        capture_id=capture.json()["data"]["id"],
        extractor=StaticExtractor(
            (
                _candidate(
                    "Docs retrieval should use Qdrant vectors.",
                    source_id=source_id,
                ),
            )
        ),
    )
    suggestions = _list_suggestions(client, headers=headers, space_slug=space_slug)
    return suggestions.json()["data"][0]


def _create_fact(
    client: TestClient,
    *,
    headers: dict[str, str],
    text: str,
    space_slug: str,
    source_id: str,
):
    return client.post(
        "/v1/facts",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
        headers=headers,
    )


def _create_capture(
    client: TestClient,
    *,
    headers: dict[str, str],
    text: str,
    space_slug: str,
):
    return client.post(
        "/v1/captures",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "source_agent": "codex",
            "source_kind": "hook",
            "event_type": "UserPromptSubmit",
            "actor_role": "user",
            "source_event_id": text,
            "text": text,
            "trust_level": "high",
            "source_authority": "explicit_user_command",
            "sensitivity": "low",
            "consolidate": True,
        },
        headers=headers,
    )


def _candidate(text: str, *, source_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        text=text,
        kind=MemoryKind.NOTE,
        confidence=Confidence.HIGH,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id=source_id,
                quote_preview=text,
            ),
        ),
        safe_reason="duplicate merge resolution test",
        operation_hint=CandidateOperation.ADD,
        tags=("test",),
        ttl_policy="durable",
    )


def _consolidate(
    client: TestClient,
    *,
    capture_id: str,
    extractor: StaticExtractor,
):
    container = client.app.state.container
    use_case = ConsolidateCaptureUseCase(
        uow_factory=container.uow_factory,
        clock=container.clock,
        ids=container.ids,
        extractor=extractor,
        auto_apply_safe_enabled=True,
    )
    return asyncio.run(use_case.execute(ConsolidateCaptureCommand(capture_id=capture_id)))


def _list_facts(client: TestClient, *, headers: dict[str, str], space_slug: str):
    return client.get(
        "/v1/facts",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": "active",
        },
        headers=headers,
    )


def _list_suggestions(client: TestClient, *, headers: dict[str, str], space_slug: str):
    return client.get(
        "/v1/suggestions",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": "pending",
        },
        headers=headers,
    )
