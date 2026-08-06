"""End-to-end repository isolation across auth, writes, captures and recall."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import MemoryCaptureRow, MemoryFactRow
from infinity_context_core.features.agent_authorization.public import (
    AgentScopeResolutionMethod,
    WorkspaceScopeClaim,
    encode_workspace_scope_claim,
)
from infinity_context_core.features.code_identity.public import CodeScope, CodeScopeLevel
from infinity_context_server.admin import token_create
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.db import upgrade
from infinity_context_server.main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def test_repository_token_locks_writes_captures_and_canonical_recall(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'repository-memory.db'}"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", database_url)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database_url,
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "repository-memory", "name": "Repository Memory"},
            headers=root_headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space["id"],
                "external_ref": "default",
                "name": "Default",
            },
            headers=root_headers,
        ).json()["data"]
        invalid_mixed_scope = client.post(
            "/v1/code-repositories/resolve",
            json={
                "space_id": space["id"],
                "evidence": [
                    {
                        "kind": "local_registry",
                        "digest": hashlib.sha256(b"mixed-branch-commit").hexdigest(),
                    }
                ],
                "provider": "local",
                "allow_create": True,
                "initial_code_scope": {
                    "scope_level": "branch",
                    "branch": "main",
                    "commit_sha": "a" * 40,
                },
            },
            headers=root_headers,
        )
        assert invalid_mixed_scope.status_code == 409
        global_fact = client.post(
            "/v1/facts",
            json=_fact_payload(
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
                text="REPOSITORY_VISIBILITY_MARKER global shared fact",
                source_id="global",
            ),
            headers=root_headers,
        )
        assert global_fact.status_code == 201
        enrollment_a = _enroll_repository(client, root_headers, space["id"], "repo-a")
        enrollment_b = _enroll_repository(client, root_headers, space["id"], "repo-b")
        repository_a = str(enrollment_a["repository_id"])
        repository_b = str(enrollment_b["repository_id"])
        feature_scope_a = _register_branch_scope(
            client,
            root_headers,
            space_id=space["id"],
            repository_id=repository_a,
            branch="feature",
        )

    token_a = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope["id"],),
            repository_id=repository_a,
            description="repository a",
            permissions=("memory:read", "memory:capture", "memory:fact_write"),
        )
    )
    token_b = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope["id"],),
            repository_id=repository_b,
            description="repository b",
            permissions=("memory:read", "memory:capture", "memory:fact_write"),
        )
    )
    capture_token = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope["id"],),
            repository_id=repository_a,
            description="repository a hook capture only",
            permissions=("memory:read", "memory:capture"),
        )
    )
    main_scope_a = _initial_scope_id(enrollment_a)
    main_scope_b = _initial_scope_id(enrollment_b)
    headers_a = _repository_headers(token_a["token"], enrollment_a, main_scope_a)
    headers_b = _repository_headers(token_b["token"], enrollment_b, main_scope_b)
    capture_headers = _repository_headers(
        capture_token["token"],
        enrollment_a,
        main_scope_a,
    )

    with TestClient(app) as client:
        fact_a = client.post(
            "/v1/facts",
            json=_fact_payload(
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
                text="REPOSITORY_VISIBILITY_MARKER alpha private fact",
                source_id="repo-a",
            ),
            headers=headers_a,
        )
        fact_b = client.post(
            "/v1/facts",
            json=_fact_payload(
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
                text="REPOSITORY_VISIBILITY_MARKER beta private fact",
                source_id="repo-b",
            ),
            headers=headers_b,
        )
        cross_repository_write = client.post(
            "/v1/facts",
            json={
                **_fact_payload(
                    space_id=space["id"],
                    memory_scope_id=memory_scope["id"],
                    text="REPOSITORY_VISIBILITY_MARKER attempted leak",
                    source_id="attempted-leak",
                ),
                "repository_id": repository_b,
            },
            headers=headers_a,
        )
        context_a = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers=headers_a,
        )
        context_b = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers=headers_b,
        )
        cross_repository_context = client.post(
            "/v1/context",
            json={
                **_context_payload(space["id"], memory_scope["id"]),
                "repository_id": repository_b,
            },
            headers=headers_a,
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "source_agent": "test-agent",
                "event_type": "tool_result",
                "text": "repository a capture",
                    "metadata": {"code_scope_id": main_scope_a},
                "consolidate": False,
            },
            headers=headers_a,
        )
        cross_repository_capture = client.post(
            "/v1/captures",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "source_agent": "test-agent",
                "event_type": "tool_result",
                "text": "attempted cross repository capture",
                "metadata": {"repository_id": repository_b},
                "consolidate": False,
            },
            headers=headers_a,
        )
        feature_headers = _repository_headers(
            token_a["token"],
            enrollment_a,
            feature_scope_a,
        )
        feature_fact = client.post(
            "/v1/facts",
            json=_fact_payload(
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
                text="REPOSITORY_VISIBILITY_MARKER feature branch fact",
                source_id="repo-a-feature",
            ),
            headers=feature_headers,
        )
        feature_context = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers=feature_headers,
        )
        main_context_after_switch = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers=headers_a,
        )
        invalid_claim = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers={
                **feature_headers,
                "X-Infinity-Workspace-Claim": (
                    feature_headers["X-Infinity-Workspace-Claim"][:-1]
                    + (
                        "0"
                        if feature_headers["X-Infinity-Workspace-Claim"][-1] != "0"
                        else "1"
                    )
                ),
            },
        )
        missing_dynamic_claim = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers={"Authorization": f"Bearer {token_a['token']}"},
        )
        forged_scope = CodeScope(
            repository_id=repository_a,
            scope_level=CodeScopeLevel.BRANCH,
            branch="forged-unregistered",
        ).code_scope_id
        forged_dynamic_claim = client.post(
            "/v1/context",
            json=_context_payload(space["id"], memory_scope["id"]),
            headers=_repository_headers(token_a["token"], enrollment_a, forged_scope),
        )
        capture_only_write = client.post(
            "/v1/facts",
            json=_fact_payload(
                space_id=space["id"],
                memory_scope_id=memory_scope["id"],
                text="REPOSITORY_VISIBILITY_MARKER policy bypass attempt",
                source_id="capture-only-write",
            ),
            headers=capture_headers,
        )
        capture_only_capture = client.post(
            "/v1/captures",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "source_agent": "capture-only-agent",
                "event_type": "tool_result",
                "text": "capture capability remains usable",
                "consolidate": False,
            },
            headers=capture_headers,
        )
        target_fact_id = global_fact.json()["data"]["id"]
        relation_a = client.post(
            f"/v1/facts/{target_fact_id}/relations",
            json={
                "target_fact_id": fact_a.json()["data"]["id"],
                "relation_type": "supports",
                "reason": "repository a evidence",
            },
            headers=root_headers,
        )
        relation_b = client.post(
            f"/v1/facts/{target_fact_id}/relations",
            json={
                "target_fact_id": fact_b.json()["data"]["id"],
                "relation_type": "supports",
                "reason": "repository b evidence",
            },
            headers=root_headers,
        )
        root_related = client.get(
            f"/v1/facts/{target_fact_id}/related",
            headers=root_headers,
        )
        repository_a_related = client.get(
            f"/v1/facts/{target_fact_id}/related",
            headers=headers_a,
        )
        root_relations = client.get(
            f"/v1/facts/{target_fact_id}/relations",
            headers=root_headers,
        )
        repository_a_relations = client.get(
            f"/v1/facts/{target_fact_id}/relations",
            headers=headers_a,
        )

    assert fact_a.status_code == 201
    assert fact_b.status_code == 201
    assert cross_repository_write.status_code == 403
    assert cross_repository_context.status_code == 403
    assert capture.status_code == 201
    assert cross_repository_capture.status_code == 403
    assert feature_fact.status_code == 201
    assert feature_context.status_code == 200
    assert main_context_after_switch.status_code == 200
    assert invalid_claim.status_code == 403
    assert missing_dynamic_claim.status_code == 403
    assert forged_dynamic_claim.status_code == 403
    assert capture_only_write.status_code == 403
    assert capture_only_capture.status_code == 201
    assert relation_a.status_code == 201
    assert relation_b.status_code == 201
    assert root_related.status_code == 200
    assert repository_a_related.status_code == 200
    assert root_relations.status_code == 200
    assert repository_a_relations.status_code == 200
    assert context_a.status_code == 200
    assert context_b.status_code == 200
    assert "global shared fact" in context_a.text
    assert "alpha private fact" in context_a.text
    assert "beta private fact" not in context_a.text
    assert "global shared fact" in context_b.text
    assert "beta private fact" in context_b.text
    assert "alpha private fact" not in context_b.text
    assert "feature branch fact" in feature_context.text
    assert "alpha private fact" not in feature_context.text
    assert "alpha private fact" in main_context_after_switch.text
    assert "feature branch fact" not in main_context_after_switch.text
    root_related_ids = {item["id"] for item in root_related.json()["data"]["items"]}
    repository_a_related_ids = {item["id"] for item in repository_a_related.json()["data"]["items"]}
    assert fact_a.json()["data"]["id"] not in root_related_ids
    assert fact_b.json()["data"]["id"] not in root_related_ids
    assert fact_a.json()["data"]["id"] in repository_a_related_ids
    assert fact_b.json()["data"]["id"] not in repository_a_related_ids
    root_relation_fact_ids = {
        item["related_fact"]["id"] for item in root_relations.json()["data"]["items"]
    }
    repository_a_relation_fact_ids = {
        item["related_fact"]["id"] for item in repository_a_relations.json()["data"]["items"]
    }
    assert root_relation_fact_ids == set()
    assert repository_a_relation_fact_ids == {fact_a.json()["data"]["id"]}

    fact_rows, capture_row = asyncio.run(
        _load_written_rows(
            app,
            fact_ids=(fact_a.json()["data"]["id"], fact_b.json()["data"]["id"]),
            capture_id=capture.json()["data"]["id"],
        )
    )
    assert {row.id: row.repository_id for row in fact_rows} == {
        fact_a.json()["data"]["id"]: repository_a,
        fact_b.json()["data"]["id"]: repository_b,
    }
    assert capture_row.metadata_json["repository_id"] == repository_a
    assert capture_row.metadata_json["code_scope_id"] == main_scope_a


def _repository_headers(
    token: str,
    enrollment: dict[str, object],
    code_scope_id: str,
) -> dict[str, str]:
    repository_id = str(enrollment["repository_id"])
    binding_id = str(enrollment["binding_id"])
    binding_version = int(enrollment["binding_version"])
    binding_grant = str(enrollment["binding_grant"])
    claim = WorkspaceScopeClaim(
        issued_at_epoch_seconds=int(time.time()),
        repository_id=repository_id,
        code_scope_id=code_scope_id,
        resolution_method=AgentScopeResolutionMethod.TRUSTED_BINDING,
        binding_id=binding_id,
        binding_version=binding_version,
    )
    encoded = encode_workspace_scope_claim(claim)
    envelope = f"v1.{encoded}"
    signature = hmac.new(
        binding_grant.encode("utf-8"),
        envelope.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "X-Infinity-Workspace-Claim": f"{envelope}.{signature}",
        "X-Infinity-Workspace-Grant": binding_grant,
    }


def _enroll_repository(
    client: TestClient,
    headers: dict[str, str],
    space_id: str,
    marker: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/code-repositories/resolve",
        json={
            "space_id": space_id,
            "evidence": [
                {
                    "kind": "local_registry",
                    "digest": hashlib.sha256(marker.encode()).hexdigest(),
                }
            ],
            "provider": "local",
            "allow_create": True,
            "safe_label": marker,
            "initial_code_scope": {
                "scope_level": "branch",
                "branch": "main",
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def _register_branch_scope(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str,
    repository_id: str,
    branch: str,
) -> str:
    response = client.post(
        f"/v1/code-repositories/{repository_id}/scopes",
        json={
            "space_id": space_id,
            "scope_level": "branch",
            "branch": branch,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["code_scope_id"])


def _initial_scope_id(enrollment: dict[str, object]) -> str:
    value = enrollment.get("initial_code_scope")
    assert isinstance(value, dict)
    return str(value["code_scope_id"])


def _fact_payload(
    *,
    space_id: str,
    memory_scope_id: str,
    text: str,
    source_id: str,
) -> dict[str, object]:
    return {
        "space_id": space_id,
        "memory_scope_id": memory_scope_id,
        "text": text,
        "kind": "note",
        "source_refs": [{"source_type": "manual", "source_id": source_id}],
    }


def _context_payload(space_id: str, memory_scope_id: str) -> dict[str, object]:
    return {
        "space_id": space_id,
        "memory_scope_ids": [memory_scope_id],
        "query": "REPOSITORY_VISIBILITY_MARKER",
        "token_budget": 1024,
        "max_facts": 20,
    }


async def _load_written_rows(
    app,
    *,
    fact_ids: tuple[str, str],
    capture_id: str,
) -> tuple[tuple[MemoryFactRow, ...], MemoryCaptureRow]:
    async with AsyncSession(app.state.container.engine) as session:
        fact_rows = tuple(
            (
                await session.execute(select(MemoryFactRow).where(MemoryFactRow.id.in_(fact_ids)))
            ).scalars()
        )
        capture_row = await session.get(MemoryCaptureRow, capture_id)
        assert capture_row is not None
        return fact_rows, capture_row
