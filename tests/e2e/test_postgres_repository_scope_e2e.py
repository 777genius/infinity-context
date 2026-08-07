"""Real PostgreSQL E2E for dynamic repository and CodeScope isolation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time

import httpx
import pytest
from infinity_context_adapters.postgres import build_async_engine
from infinity_context_core.features.agent_authorization.public import (
    AgentScopeResolutionMethod,
    WorkspaceScopeClaim,
    encode_workspace_scope_claim,
)
from infinity_context_core.features.code_identity.public import CodeScope, CodeScopeLevel
from infinity_context_server.admin import token_create
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.main import create_app
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_postgres_repository_scope_full_flow_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_postgres_repository_scope(database_url, monkeypatch))


async def _assert_postgres_repository_scope(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="repository_scope",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    await database.recreate()
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", database.app_url)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database.app_url,
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://memory.test",
            ) as client,
        ):
            space_id, memory_scope_id = await _create_scope(client, root_headers)
            enrollment_a = await _enroll_repository(client, root_headers, space_id, "repo-a")
            enrollment_b = await _enroll_repository(client, root_headers, space_id, "repo-b")
            repository_a = str(enrollment_a["repository_id"])
            repository_b = str(enrollment_b["repository_id"])
            main_scope_a = _initial_scope_id(enrollment_a)
            main_scope_b = _initial_scope_id(enrollment_b)
            feature_scope_a = await _register_branch_scope(
                client,
                root_headers,
                space_id=space_id,
                repository_id=repository_a,
                branch="feature",
            )
            token_a = await token_create(
                space_id=space_id,
                memory_scope_ids=(memory_scope_id,),
                repository_id=repository_a,
                description="repository a",
                permissions=("memory:read", "memory:capture", "memory:fact_write"),
            )
            token_b = await token_create(
                space_id=space_id,
                memory_scope_ids=(memory_scope_id,),
                repository_id=repository_b,
                description="repository b",
                permissions=("memory:read", "memory:capture", "memory:fact_write"),
            )
            headers_a = _repository_headers(str(token_a["token"]), enrollment_a, main_scope_a)
            headers_b = _repository_headers(str(token_b["token"]), enrollment_b, main_scope_b)
            feature_headers = _repository_headers(
                str(token_a["token"]),
                enrollment_a,
                feature_scope_a,
            )

            global_fact = await _create_fact(
                client,
                root_headers,
                space_id,
                memory_scope_id,
                "POSTGRES_REPOSITORY_SCOPE global",
                "global",
            )
            fact_a = await _create_fact(
                client,
                headers_a,
                space_id,
                memory_scope_id,
                "POSTGRES_REPOSITORY_SCOPE alpha",
                "repo-a",
            )
            fact_b = await _create_fact(
                client,
                headers_b,
                space_id,
                memory_scope_id,
                "POSTGRES_REPOSITORY_SCOPE beta",
                "repo-b",
            )
            feature_fact = await _create_fact(
                client,
                feature_headers,
                space_id,
                memory_scope_id,
                "POSTGRES_REPOSITORY_SCOPE feature",
                "repo-a-feature",
            )
            cross_write = await client.post(
                "/v1/facts",
                json={
                    **_fact_payload(
                        space_id,
                        memory_scope_id,
                        "POSTGRES_REPOSITORY_SCOPE attempted leak",
                        "attempted-leak",
                    ),
                    "repository_id": repository_b,
                },
                headers=headers_a,
            )
            capture = await client.post(
                "/v1/captures",
                json={
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "source_agent": "postgres-e2e",
                    "event_type": "tool_result",
                    "text": "repository a capture",
                    "metadata": {"code_scope_id": main_scope_a},
                    "consolidate": False,
                },
                headers=headers_a,
            )
            cross_capture = await client.post(
                "/v1/captures",
                json={
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "source_agent": "postgres-e2e",
                    "event_type": "tool_result",
                    "text": "attempted repository b capture",
                    "metadata": {"repository_id": repository_b},
                    "consolidate": False,
                },
                headers=headers_a,
            )
            context_a = await _context(client, headers_a, space_id, memory_scope_id)
            context_b = await _context(client, headers_b, space_id, memory_scope_id)
            feature_context = await _context(client, feature_headers, space_id, memory_scope_id)
            missing_claim = await _context(
                client,
                {"Authorization": f"Bearer {token_a['token']}"},
                space_id,
                memory_scope_id,
            )
            forged_scope = CodeScope(
                repository_id=repository_a,
                scope_level=CodeScopeLevel.BRANCH,
                branch="unregistered",
            ).code_scope_id
            forged_claim = await _context(
                client,
                _repository_headers(str(token_a["token"]), enrollment_a, forged_scope),
                space_id,
                memory_scope_id,
            )

        assert global_fact.status_code == 201
        assert fact_a.status_code == fact_b.status_code == feature_fact.status_code == 201
        assert cross_write.status_code == 403
        assert capture.status_code == 201
        assert cross_capture.status_code == 403
        assert missing_claim.status_code == forged_claim.status_code == 403
        assert context_a.status_code == context_b.status_code == feature_context.status_code == 200
        rendered_a = str(context_a.json()["data"]["rendered_text"])
        rendered_b = str(context_b.json()["data"]["rendered_text"])
        rendered_feature = str(feature_context.json()["data"]["rendered_text"])
        assert "global" in rendered_a and "alpha" in rendered_a
        assert "beta" not in rendered_a and "feature" not in rendered_a
        assert "global" in rendered_b and "beta" in rendered_b
        assert "alpha" not in rendered_b
        assert "feature" in rendered_feature
        assert "alpha" not in rendered_feature and "beta" not in rendered_feature
        await _assert_postgres_scope_rows(
            database.app_url,
            fact_a_id=str(fact_a.json()["data"]["id"]),
            fact_b_id=str(fact_b.json()["data"]["id"]),
            feature_fact_id=str(feature_fact.json()["data"]["id"]),
            capture_id=str(capture.json()["data"]["id"]),
            repository_a=repository_a,
            repository_b=repository_b,
            main_scope_a=main_scope_a,
            main_scope_b=main_scope_b,
            feature_scope_a=feature_scope_a,
        )
    finally:
        await database.drop()


async def _create_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str]:
    space = await client.post(
        "/v1/spaces",
        json={"slug": "repository-scope-e2e", "name": "Repository Scope E2E"},
        headers=headers,
    )
    assert space.status_code == 201, space.text
    space_id = str(space.json()["data"]["id"])
    memory_scope = await client.post(
        "/v1/memory-scopes",
        json={"space_id": space_id, "external_ref": "default", "name": "Default"},
        headers=headers,
    )
    assert memory_scope.status_code == 201, memory_scope.text
    return space_id, str(memory_scope.json()["data"]["id"])


async def _enroll_repository(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    space_id: str,
    marker: str,
) -> dict[str, object]:
    response = await client.post(
        "/v1/code-repositories/resolve",
        json={
            "space_id": space_id,
            "evidence": [
                {"kind": "local_registry", "digest": hashlib.sha256(marker.encode()).hexdigest()}
            ],
            "provider": "local",
            "allow_create": True,
            "safe_label": marker,
            "initial_code_scope": {"scope_level": "branch", "branch": "main"},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _register_branch_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    space_id: str,
    repository_id: str,
    branch: str,
) -> str:
    response = await client.post(
        f"/v1/code-repositories/{repository_id}/scopes",
        json={"space_id": space_id, "scope_level": "branch", "branch": branch},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["code_scope_id"])


def _repository_headers(
    token: str,
    enrollment: dict[str, object],
    code_scope_id: str,
) -> dict[str, str]:
    binding_grant = str(enrollment["binding_grant"])
    claim = WorkspaceScopeClaim(
        issued_at_epoch_seconds=int(time.time()),
        repository_id=str(enrollment["repository_id"]),
        code_scope_id=code_scope_id,
        resolution_method=AgentScopeResolutionMethod.TRUSTED_BINDING,
        binding_id=str(enrollment["binding_id"]),
        binding_version=int(enrollment["binding_version"]),
    )
    encoded = encode_workspace_scope_claim(claim)
    envelope = f"v1.{encoded}"
    signature = hmac.new(
        binding_grant.encode(),
        envelope.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "X-Infinity-Workspace-Claim": f"{envelope}.{signature}",
        "X-Infinity-Workspace-Grant": binding_grant,
    }


async def _create_fact(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    space_id: str,
    memory_scope_id: str,
    marker: str,
    source_id: str,
) -> httpx.Response:
    return await client.post(
        "/v1/facts",
        json=_fact_payload(space_id, memory_scope_id, marker, source_id),
        headers=headers,
    )


def _fact_payload(
    space_id: str,
    memory_scope_id: str,
    marker: str,
    source_id: str,
) -> dict[str, object]:
    return {
        "space_id": space_id,
        "memory_scope_id": memory_scope_id,
        "text": marker,
        "kind": "note",
        "source_refs": [{"source_type": "manual", "source_id": source_id}],
    }


async def _context(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    space_id: str,
    memory_scope_id: str,
) -> httpx.Response:
    return await client.post(
        "/v1/context",
        json={
            "space_id": space_id,
            "memory_scope_ids": [memory_scope_id],
            "query": "POSTGRES_REPOSITORY_SCOPE",
            "token_budget": 1024,
            "max_facts": 20,
        },
        headers=headers,
    )


def _initial_scope_id(enrollment: dict[str, object]) -> str:
    initial = enrollment.get("initial_code_scope")
    assert isinstance(initial, dict)
    return str(initial["code_scope_id"])


async def _assert_postgres_scope_rows(
    database_url: str,
    *,
    fact_a_id: str,
    fact_b_id: str,
    feature_fact_id: str,
    capture_id: str,
    repository_a: str,
    repository_b: str,
    main_scope_a: str,
    main_scope_b: str,
    feature_scope_a: str,
) -> None:
    engine = build_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            facts = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT id, repository_id, code_scope_id FROM memory_facts
                        WHERE id IN (:fact_a_id, :fact_b_id, :feature_fact_id)
                        """
                        ),
                        {
                            "fact_a_id": fact_a_id,
                            "fact_b_id": fact_b_id,
                            "feature_fact_id": feature_fact_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            capture = (
                (
                    await connection.execute(
                        text("SELECT metadata_json FROM memory_captures WHERE id = :capture_id"),
                        {"capture_id": capture_id},
                    )
                )
                .mappings()
                .one()
            )
        assert {row["id"]: (row["repository_id"], row["code_scope_id"]) for row in facts} == {
            fact_a_id: (repository_a, main_scope_a),
            fact_b_id: (repository_b, main_scope_b),
            feature_fact_id: (repository_a, feature_scope_a),
        }
        assert capture["metadata_json"]["repository_id"] == repository_a
        assert capture["metadata_json"]["code_scope_id"] == main_scope_a
    finally:
        await engine.dispose()
