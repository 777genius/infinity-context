import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemoryServiceTokenRow,
    MemorySourceRefRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_server.admin import (
    export_memory_scope_command,
    import_memory_scope_command,
    reset_local,
    token_create,
    token_list,
    token_revoke,
)
from infinity_context_server.auth_tokens import token_hash
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.db import upgrade
from infinity_context_server.main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    return TestClient(app)


async def _load_service_token(tmp_path: Path, *, token_id: str) -> MemoryServiceTokenRow:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    try:
        async with AsyncSession(app.state.container.engine) as session:
            row = await session.get(MemoryServiceTokenRow, token_id)
            assert row is not None
            return row
    finally:
        await app.state.container.engine.dispose()


async def _mark_scope_deleted(
    app,
    *,
    space_id: str | None = None,
    memory_scope_id: str | None = None,
) -> None:
    async with AsyncSession(app.state.container.engine) as session:
        if space_id:
            space = await session.get(MemorySpaceRow, space_id)
            assert space is not None
            space.status = "deleted"
        if memory_scope_id:
            memory_scope = await session.get(MemoryScopeRow, memory_scope_id)
            assert memory_scope is not None
            memory_scope.status = "deleted"
        await session.commit()


def test_admin_token_lifecycle_and_auth_without_raw_token_in_list(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    created = asyncio.run(token_create(space_id=None, description="test token"))
    rotated = asyncio.run(token_create(space_id=None, description="rotated token"))
    listed = asyncio.run(token_list(space_id=None))

    with make_client(tmp_path) as client:
        authorized = client.get(
            "/v1/spaces",
            headers={"Authorization": f"Bearer {created['token']}"},
        )
        rotated_authorized = client.get(
            "/v1/spaces",
            headers={"Authorization": f"Bearer {rotated['token']}"},
        )

    revoked = asyncio.run(token_revoke(token_id=str(created["token_id"])))
    listed_after_revoke = asyncio.run(token_list(space_id=None))

    with make_client(tmp_path) as client:
        rejected = client.get(
            "/v1/spaces",
            headers={"Authorization": f"Bearer {created['token']}"},
        )
        rotated_still_authorized = client.get(
            "/v1/spaces",
            headers={"Authorization": f"Bearer {rotated['token']}"},
        )

    assert created["status"] == "created"
    assert str(created["token"]).startswith("mp_")
    assert created["memory_scope_ids"] is None
    assert set(created["permissions"]) == {
        "memory:admin",
        "memory:delete",
        "memory:diagnostics",
        "memory:read",
        "memory:write",
    }
    listed_ids = {item["id"] for item in listed["tokens"]}
    assert {created["token_id"], rotated["token_id"]}.issubset(listed_ids)
    assert all("token" not in item for item in listed["tokens"])
    assert all("memory_scope_ids" in item for item in listed["tokens"])
    assert all("permissions" in item for item in listed["tokens"])
    assert authorized.status_code == 200
    assert rotated_authorized.status_code == 200
    listed_after_use = asyncio.run(token_list(space_id=None))
    used_tokens = {item["id"]: item for item in listed_after_use["tokens"]}
    assert used_tokens[created["token_id"]]["last_used_at"] is not None
    assert used_tokens[rotated["token_id"]]["last_used_at"] is not None
    assert revoked == {"status": "revoked", "token_id": created["token_id"]}
    statuses = {item["id"]: item["status"] for item in listed_after_revoke["tokens"]}
    assert statuses[created["token_id"]] == "revoked"
    assert statuses[rotated["token_id"]] == "active"
    assert rejected.status_code == 401
    assert rotated_still_authorized.status_code == 200


def test_token_hash_is_stored_not_raw_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    created = asyncio.run(token_create(space_id=None, description="hash check"))
    row = asyncio.run(_load_service_token(tmp_path, token_id=str(created["token_id"])))

    assert row.token_hash == token_hash(str(created["token"]))
    assert row.token_hash != created["token"]
    assert str(created["token"]) not in str(row.__dict__)


def test_expired_service_token_is_rejected_and_never_updates_last_used(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    expired = asyncio.run(
        token_create(
            space_id=None,
            description="expired token",
            expires_at="2000-01-01T00:00:00+00:00",
        )
    )

    with make_client(tmp_path) as client:
        rejected = client.get(
            "/v1/spaces",
            headers={"Authorization": f"Bearer {expired['token']}"},
        )

    listed = asyncio.run(token_list(space_id=None))
    expired_row = next(item for item in listed["tokens"] if item["id"] == expired["token_id"])

    assert rejected.status_code == 401
    assert expired["expires_at"] == "2000-01-01T00:00:00+00:00"
    assert expired_row["expires_at"] is not None
    assert expired_row["last_used_at"] is None
    assert str(expired["token"]) not in str(listed)


def test_scoped_service_token_cannot_cross_space_or_use_unscoped_routes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'scoped.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'scoped.db'}",
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
        space_a = client.post(
            "/v1/spaces",
            json={"slug": "scope-a", "name": "Scope A"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_a["id"], "external_ref": "default", "name": "Default"},
            headers=root_headers,
        ).json()["data"]
        space_b = client.post(
            "/v1/spaces",
            json={"slug": "scope-b", "name": "Scope B"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_b["id"], "external_ref": "default", "name": "Default"},
            headers=root_headers,
        ).json()["data"]
        fact_b = client.post(
            "/v1/facts",
            json={
                "space_id": space_b["id"],
                "memory_scope_id": memory_scope_b["id"],
                "text": "SCOPED_TOKEN_LEAK_MARKER must not be readable by scope-a token.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "scope-b"}],
            },
            headers=root_headers,
        ).json()["data"]

    scoped = asyncio.run(token_create(space_id=space_a["id"], description="scope-a token"))
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}
    with TestClient(app) as client:
        same_space = client.get(
            "/v1/facts",
            params={"space_id": space_a["id"], "memory_scope_id": memory_scope_a["id"]},
            headers=scoped_headers,
        )
        cross_space = client.get(
            "/v1/facts",
            params={"space_id": space_b["id"], "memory_scope_id": memory_scope_b["id"]},
            headers=scoped_headers,
        )
        cross_space_by_id = client.get(f"/v1/facts/{fact_b['id']}", headers=scoped_headers)
        capabilities = client.get("/v1/capabilities", headers=scoped_headers)
        unscoped = client.get("/v1/spaces", headers=scoped_headers)

    assert same_space.status_code == 200
    assert cross_space.status_code == 403
    assert cross_space.json()["error"]["code"] == "memory.forbidden"
    assert cross_space_by_id.status_code == 403
    assert capabilities.status_code == 200
    assert "SCOPED_TOKEN_LEAK_MARKER" not in cross_space_by_id.text
    assert unscoped.status_code == 403


def test_service_token_permissions_are_enforced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'perms.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'perms.db'}",
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
            json={"slug": "perm-space", "name": "Permission Space"},
            headers=root_headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=root_headers,
        ).json()["data"]
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Permission matrix fact.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "permissions"}],
            },
            headers=root_headers,
        ).json()["data"]

    read_only = asyncio.run(
        token_create(
            space_id=None,
            description="read only",
            permissions=("memory:read",),
        )
    )
    write_only = asyncio.run(
        token_create(
            space_id=None,
            description="write only",
            permissions=("memory:write",),
        )
    )
    diagnostics_only = asyncio.run(
        token_create(
            space_id=None,
            description="diagnostics only",
            permissions=("memory:diagnostics",),
        )
    )
    admin_only = asyncio.run(
        token_create(
            space_id=None,
            description="admin only",
            permissions=("memory:admin",),
        )
    )

    read_headers = {"Authorization": f"Bearer {read_only['token']}"}
    write_headers = {"Authorization": f"Bearer {write_only['token']}"}
    diagnostics_headers = {"Authorization": f"Bearer {diagnostics_only['token']}"}
    admin_headers = {"Authorization": f"Bearer {admin_only['token']}"}
    with TestClient(app) as client:
        read_allowed = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope["id"]},
            headers=read_headers,
        )
        read_can_get_capabilities = client.get("/v1/capabilities", headers=read_headers)
        read_can_list_memory_scopes = client.get(
            "/v1/memory-scopes",
            params={"space_id": space["id"]},
            headers=read_headers,
        )
        read_cannot_write = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Read token must not create this.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "permissions"}],
            },
            headers=read_headers,
        )
        read_cannot_delete = client.delete(f"/v1/facts/{fact['id']}", headers=read_headers)
        read_cannot_update_memory_scope = client.patch(
            f"/v1/memory-scopes/{memory_scope['id']}",
            json={"name": "Read token renamed scope"},
            headers=read_headers,
        )
        read_cannot_delete_memory_scope = client.delete(
            f"/v1/memory-scopes/{memory_scope['id']}",
            headers=read_headers,
        )
        read_cannot_diagnose = client.get("/v1/diagnostics/outbox", headers=read_headers)

        write_allowed = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Write token may create this.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "permissions"}],
            },
            headers=write_headers,
        )
        write_capture_allowed = client.post(
            "/v1/captures",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "source_agent": "codex",
                "source_kind": "hook",
                "event_type": "UserPromptSubmit",
                "actor_role": "user",
                "source_event_id": "permission-capture",
                "text": "Remember: PERMISSION_CAPTURE_MARKER write-only token can create.",
            },
            headers=write_headers,
        )
        write_capture_id = (
            write_capture_allowed.json()["data"]["id"]
            if write_capture_allowed.status_code == 201
            else "missing"
        )
        write_cannot_read_capture = client.get(
            f"/v1/captures/{write_capture_id}",
            headers=write_headers,
        )
        write_cannot_purge_capture = client.request(
            "DELETE",
            f"/v1/captures/{write_capture_id}",
            json={"reason": "permission test"},
            headers=write_headers,
        )
        write_cannot_read = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope["id"]},
            headers=write_headers,
        )
        write_cannot_list_memory_scopes = client.get(
            "/v1/memory-scopes",
            params={"space_id": space["id"]},
            headers=write_headers,
        )
        write_can_update_memory_scope = client.patch(
            f"/v1/memory-scopes/{memory_scope['id']}",
            json={"name": "Permission Scope"},
            headers=write_headers,
        )
        write_cannot_delete_memory_scope = client.delete(
            f"/v1/memory-scopes/{memory_scope['id']}",
            headers=write_headers,
        )
        write_cannot_delete = client.delete(f"/v1/facts/{fact['id']}", headers=write_headers)

        diagnostics_allowed = client.get(
            "/v1/diagnostics/outbox",
            headers=diagnostics_headers,
        )
        diagnostics_cannot_read = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope["id"]},
            headers=diagnostics_headers,
        )
        snapshot_params = {
            "space_slug": "perm-space",
            "memory_scope_external_ref": "default",
            "redacted": False,
        }
        admin_can_read = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope["id"]},
            headers=admin_headers,
        )
        admin_can_write = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Admin token may create this.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "admin-permission"}],
            },
            headers=admin_headers,
        )
        admin_can_diagnose = client.get("/v1/diagnostics/outbox", headers=admin_headers)
        admin_can_export_snapshot = client.get(
            "/v1/export/memory_scope-snapshot",
            params=snapshot_params,
            headers=admin_headers,
        )
        snapshot_body = {
            "space_slug": "perm-space",
            "memory_scope_external_ref": "admin-restore",
            "snapshot": admin_can_export_snapshot.json()["data"],
            "manifest": admin_can_export_snapshot.json()["manifest"],
            "dry_run": False,
            "merge_strategy": "create_new_memory_scope",
            "confirmed": True,
            "source_name": "permission-matrix",
        }
        read_cannot_export_graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_slug": "perm-space",
                "memory_scope_external_ref": "default",
            },
            headers=read_headers,
        )
        read_cannot_export_snapshot = client.get(
            "/v1/export/memory_scope-snapshot",
            params=snapshot_params,
            headers=read_headers,
        )
        read_cannot_preview_snapshot = client.post(
            "/v1/export/memory_scope-snapshot/preview",
            json={
                "space_slug": "perm-space",
                "memory_scope_external_ref": "read-preview",
                "snapshot": snapshot_body["snapshot"],
                "manifest": snapshot_body["manifest"],
            },
            headers=read_headers,
        )
        read_cannot_import_snapshot = client.post(
            "/v1/export/memory_scope-snapshot/import",
            json={**snapshot_body, "memory_scope_external_ref": "read-restore"},
            headers=read_headers,
        )
        admin_can_import_snapshot = client.post(
            "/v1/export/memory_scope-snapshot/import",
            json=snapshot_body,
            headers=admin_headers,
        )

    assert read_allowed.status_code == 200
    assert read_can_get_capabilities.status_code == 200
    assert read_can_list_memory_scopes.status_code == 200
    assert read_cannot_write.status_code == 403
    assert read_cannot_delete.status_code == 403
    assert read_cannot_update_memory_scope.status_code == 403
    assert read_cannot_delete_memory_scope.status_code == 403
    assert read_cannot_diagnose.status_code == 403
    assert write_allowed.status_code == 201
    assert write_capture_allowed.status_code == 201
    assert write_cannot_read_capture.status_code == 403
    assert write_cannot_purge_capture.status_code == 403
    assert write_cannot_read.status_code == 403
    assert write_cannot_list_memory_scopes.status_code == 403
    assert write_can_update_memory_scope.status_code == 200
    assert write_cannot_delete_memory_scope.status_code == 403
    assert write_cannot_delete.status_code == 403
    assert diagnostics_allowed.status_code == 200
    assert diagnostics_cannot_read.status_code == 403
    assert admin_can_read.status_code == 200
    assert admin_can_write.status_code == 201
    assert admin_can_diagnose.status_code == 200
    assert admin_can_export_snapshot.status_code == 200
    assert admin_can_import_snapshot.status_code == 200
    assert admin_can_import_snapshot.json()["data"]["status"] == "ok"
    assert read_cannot_export_graph.status_code == 403
    assert read_cannot_export_snapshot.status_code == 403
    assert read_cannot_preview_snapshot.status_code == 403
    assert read_cannot_import_snapshot.status_code == 403
    assert read_cannot_write.json()["error"]["code"] == "memory.forbidden"
    assert read_cannot_import_snapshot.json()["error"]["code"] == "memory.forbidden"


def test_memory_scope_scoped_service_token_cannot_cross_memory_scope_in_same_space(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv(
        "MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'memory_scopes.db'}"
    )
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory_scopes.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "memory_scope-scope", "name": "MemoryScope Scope"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "beta", "name": "Beta"},
            headers=root_headers,
        ).json()["data"]
        fact_b = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "text": "MEMORY_SCOPE_LEAK_MARKER must not be visible.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "memory_scope-b"}],
            },
            headers=root_headers,
        ).json()["data"]
        suggestion_b = client.post(
            "/v1/suggestions",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "candidate_text": "MEMORY_SCOPE_SUGGESTION_LEAK must not be visible.",
                "kind": "note",
                "safe_reason": "scope_test",
                "source_refs": [
                    {"source_type": "manual", "source_id": "memory_scope-b-suggestion"}
                ],
            },
            headers=root_headers,
        ).json()["data"]

    scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha only",
            permissions=("memory:read",),
        )
    )
    diagnostics_scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha diagnostics",
            permissions=("memory:diagnostics",),
        )
    )
    scoped_admin = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha admin",
            permissions=("memory:admin",),
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}
    diagnostics_headers = {"Authorization": f"Bearer {diagnostics_scoped['token']}"}
    scoped_admin_headers = {"Authorization": f"Bearer {scoped_admin['token']}"}

    with TestClient(app) as client:
        same_memory_scope = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope_a["id"]},
            headers=scoped_headers,
        )
        cross_memory_scope = client.get(
            "/v1/facts",
            params={"space_id": space["id"], "memory_scope_id": memory_scope_b["id"]},
            headers=scoped_headers,
        )
        cross_memory_scope_by_id = client.get(f"/v1/facts/{fact_b['id']}", headers=scoped_headers)
        same_memory_scope_suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "status": "pending",
            },
            headers=scoped_headers,
        )
        cross_memory_scope_suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "status": "pending",
            },
            headers=scoped_headers,
        )
        cross_memory_scope_suggestion_by_id = client.post(
            f"/v1/suggestions/{suggestion_b['id']}/reject",
            json={"reason": "must not access"},
            headers=scoped_headers,
        )
        same_memory_scope_diagnostics = client.get(
            f"/v1/diagnostics/memory-scope/{memory_scope_a['id']}",
            headers=scoped_headers,
        )
        scoped_same_memory_scope_diagnostics = client.get(
            f"/v1/diagnostics/memory-scope/{memory_scope_a['id']}",
            headers=diagnostics_headers,
        )
        cross_memory_scope_diagnostics = client.get(
            f"/v1/diagnostics/memory-scope/{memory_scope_b['id']}",
            headers=diagnostics_headers,
        )
        multi_memory_scope_context = client.post(
            "/v1/context",
            json={
                "space_id": space["id"],
                "memory_scope_ids": [memory_scope_a["id"], memory_scope_b["id"]],
                "query": "MEMORY_SCOPE_LEAK_MARKER",
            },
            headers=scoped_headers,
        )
        memory_scope_capabilities = client.get("/v1/capabilities", headers=scoped_headers)
        scoped_admin_export = client.get(
            "/v1/export/memory_scope-snapshot",
            params={
                "space_slug": "memory_scope-scope",
                "memory_scope_external_ref": "alpha",
                "redacted": False,
            },
            headers=scoped_admin_headers,
        )
        snapshot_payload = scoped_admin_export.json()
        scoped_admin_preview = client.post(
            "/v1/export/memory_scope-snapshot/preview",
            json={
                "space_slug": "memory_scope-scope",
                "memory_scope_external_ref": "alpha",
                "snapshot": snapshot_payload.get("data", {}),
                "manifest": snapshot_payload.get("manifest"),
            },
            headers=scoped_admin_headers,
        )
        scoped_admin_import_dry_run = client.post(
            "/v1/export/memory_scope-snapshot/import",
            json={
                "space_slug": "memory_scope-scope",
                "memory_scope_external_ref": "alpha",
                "snapshot": snapshot_payload.get("data", {}),
                "manifest": snapshot_payload.get("manifest"),
                "dry_run": True,
                "source_name": "scoped-admin-dry-run",
            },
            headers=scoped_admin_headers,
        )

    assert scoped["memory_scope_ids"] == [memory_scope_a["id"]]
    assert same_memory_scope.status_code == 200
    assert cross_memory_scope.status_code == 403
    assert cross_memory_scope_by_id.status_code == 403
    assert same_memory_scope_suggestions.status_code == 200
    assert cross_memory_scope_suggestions.status_code == 403
    assert cross_memory_scope_suggestion_by_id.status_code == 403
    assert same_memory_scope_diagnostics.status_code == 403
    assert scoped_same_memory_scope_diagnostics.status_code == 200
    assert cross_memory_scope_diagnostics.status_code == 403
    assert multi_memory_scope_context.status_code == 403
    assert memory_scope_capabilities.status_code == 200
    assert scoped_admin_export.status_code == 200
    assert scoped_admin_preview.status_code == 200
    assert scoped_admin_import_dry_run.status_code == 200
    assert "MEMORY_SCOPE_LEAK_MARKER" not in cross_memory_scope_by_id.text
    assert "MEMORY_SCOPE_SUGGESTION_LEAK" not in cross_memory_scope_suggestions.text


def test_scoped_service_tokens_reject_inactive_path_resource_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'inactive.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'inactive.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "inactive-scope", "name": "Inactive Scope"},
            headers=root_headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "INACTIVE_SCOPE_PATH_MARKER must not leak after scope deletion.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "inactive-scope"}],
            },
            headers=root_headers,
        ).json()["data"]

    memory_scope_scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope["id"],),
            description="inactive memory_scope token",
            permissions=("memory:read",),
        )
    )
    space_scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            description="inactive space token",
            permissions=("memory:read",),
        )
    )
    memory_scope_headers = {"Authorization": f"Bearer {memory_scope_scoped['token']}"}
    space_headers = {"Authorization": f"Bearer {space_scoped['token']}"}

    with TestClient(app) as client:
        memory_scope_before = client.get(f"/v1/facts/{fact['id']}", headers=memory_scope_headers)
        space_before = client.get(f"/v1/facts/{fact['id']}", headers=space_headers)

    asyncio.run(_mark_scope_deleted(app, memory_scope_id=memory_scope["id"]))
    with TestClient(app) as client:
        inactive_memory_scope = client.get(f"/v1/facts/{fact['id']}", headers=memory_scope_headers)

    asyncio.run(_mark_scope_deleted(app, space_id=space["id"]))
    with TestClient(app) as client:
        inactive_space = client.get(f"/v1/facts/{fact['id']}", headers=space_headers)

    assert memory_scope_before.status_code == 200
    assert space_before.status_code == 200
    assert inactive_memory_scope.status_code == 403
    assert inactive_space.status_code == 403
    assert "INACTIVE_SCOPE_PATH_MARKER" not in inactive_memory_scope.text
    assert "INACTIVE_SCOPE_PATH_MARKER" not in inactive_space.text


def test_memory_scope_scoped_external_ref_match_is_bound_to_token_space(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ref-space.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'ref-space.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space_a = client.post(
            "/v1/spaces",
            json={"slug": "ref-space-a", "name": "Ref Space A"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_a["id"], "external_ref": "default", "name": "Default"},
            headers=root_headers,
        ).json()["data"]
        space_b = client.post(
            "/v1/spaces",
            json={"slug": "ref-space-b", "name": "Ref Space B"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space_b["id"], "external_ref": "default", "name": "Default"},
            headers=root_headers,
        ).json()["data"]
        fact_b = client.post(
            "/v1/facts",
            json={
                "space_id": space_b["id"],
                "memory_scope_id": memory_scope_b["id"],
                "text": "MEMORY_SCOPE_REF_SPACE_MARKER must not leak to space-a token.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "ref-space-b"}],
            },
            headers=root_headers,
        ).json()["data"]

    scoped = asyncio.run(
        token_create(
            space_id=space_a["id"],
            memory_scope_ids=("default",),
            description="space-a default by external ref",
            permissions=("memory:read",),
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}

    asyncio.run(_mark_scope_deleted(app, memory_scope_id=memory_scope_a["id"]))
    with TestClient(app) as client:
        same_space_deleted = client.get(
            "/v1/facts",
            params={"space_id": space_a["id"], "memory_scope_id": "default"},
            headers=scoped_headers,
        )
        cross_space_path = client.get(f"/v1/facts/{fact_b['id']}", headers=scoped_headers)

    assert same_space_deleted.status_code == 403
    assert cross_space_path.status_code == 403
    assert "MEMORY_SCOPE_REF_SPACE_MARKER" not in cross_space_path.text


def test_memory_scope_scoped_service_token_requires_space_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    try:
        asyncio.run(
            token_create(
                space_id=None,
                memory_scope_ids=("default",),
                description="ambiguous memory_scope token",
            )
        )
    except ValueError as exc:
        assert "requires a space scope" in str(exc)
    else:
        raise AssertionError("Expected memory_scope-scoped token without space to fail")


def test_scoped_service_token_create_requires_existing_active_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'scope-create.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'scope-create.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "token-scope-create", "name": "Token Scope Create"},
            headers=root_headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]

    slug_scoped = asyncio.run(
        token_create(
            space_id="token-scope-create",
            memory_scope_ids=("alpha",),
            description="slug scoped",
        )
    )

    missing_space_error = None
    try:
        asyncio.run(token_create(space_id="space_missing", description="missing space"))
    except ValueError as exc:
        missing_space_error = str(exc)

    missing_memory_scope_error = None
    try:
        asyncio.run(
            token_create(
                space_id=space["id"],
                memory_scope_ids=("memory_scope_missing",),
                description="missing memory_scope",
            )
        )
    except ValueError as exc:
        missing_memory_scope_error = str(exc)

    asyncio.run(_mark_scope_deleted(app, memory_scope_id=memory_scope["id"]))
    deleted_memory_scope_error = None
    try:
        asyncio.run(
            token_create(
                space_id=space["id"],
                memory_scope_ids=(memory_scope["id"],),
                description="deleted memory_scope",
            )
        )
    except ValueError as exc:
        deleted_memory_scope_error = str(exc)

    asyncio.run(_mark_scope_deleted(app, space_id=space["id"]))
    deleted_space_error = None
    try:
        asyncio.run(token_create(space_id=space["id"], description="deleted space"))
    except ValueError as exc:
        deleted_space_error = str(exc)

    assert slug_scoped["space_id"] == "token-scope-create"
    assert slug_scoped["memory_scope_ids"] == ["alpha"]
    assert missing_space_error == "Scoped service token space must exist and be active"
    assert missing_memory_scope_error == (
        "MemoryScope scoped service token memory_scopes must exist and be active"
    )
    assert deleted_memory_scope_error == (
        "MemoryScope scoped service token memory_scopes must exist and be active"
    )
    assert deleted_space_error == "Scoped service token space must exist and be active"


def test_memory_scope_scoped_write_token_can_create_suggestion_only_in_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'suggest.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'suggest.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "suggest-scope", "name": "Suggest Scope"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "beta", "name": "Beta"},
            headers=root_headers,
        )

    scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha write",
            permissions=("memory:write",),
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}
    payload = {
        "space_slug": "suggest-scope",
        "memory_scope_external_ref": "alpha",
        "candidate_text": "Scoped suggestion can be written.",
        "kind": "note",
        "safe_reason": "scope_test",
        "source_refs": [{"source_type": "manual", "source_id": "scope-write"}],
    }
    with TestClient(app) as client:
        same_memory_scope = client.post(
            "/v1/suggestions",
            json=payload,
            headers=scoped_headers,
        )
        cross_memory_scope = client.post(
            "/v1/suggestions",
            json={**payload, "memory_scope_external_ref": "beta"},
            headers=scoped_headers,
        )

    assert same_memory_scope.status_code == 201
    assert cross_memory_scope.status_code == 403
    assert "Scoped suggestion can be written" not in cross_memory_scope.text


def test_memory_scope_scoped_service_token_accepts_external_refs_without_cross_memory_scope_leak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'external.db'}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'external.db'}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "external-scope", "name": "External Scope"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_alpha = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "beta", "name": "Beta"},
            headers=root_headers,
        )

    scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_alpha["id"],),
            description="alpha external refs",
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}
    allowed_scope = {
        "space_slug": "external-scope",
        "memory_scope_external_ref": "alpha",
        "thread_external_ref": "external-session-alpha",
    }
    denied_scope = {
        "space_slug": "external-scope",
        "memory_scope_external_ref": "beta",
        "thread_external_ref": "external-session-beta",
    }

    with TestClient(app) as client:
        episode = client.post(
            "/v1/episodes",
            json={
                **allowed_scope,
                "source_type": "system_audio",
                "source_external_id": "external-event-alpha",
                "text": "EXTERNAL_SCOPE_ALPHA_MARKER must be readable by alpha token.",
                "kind_hint": "constraint",
                "idempotency_key": "external-event-alpha",
            },
            headers=scoped_headers,
        )
        context = client.post(
            "/v1/context",
            json={
                **allowed_scope,
                "query": "EXTERNAL_SCOPE_ALPHA_MARKER",
                "token_budget": 512,
            },
            headers=scoped_headers,
        )
        denied_context = client.post(
            "/v1/context",
            json={**denied_scope, "query": "EXTERNAL_SCOPE_ALPHA_MARKER"},
            headers=scoped_headers,
        )
        denied_document = client.post(
            "/v1/documents",
            json={
                **denied_scope,
                "title": "Denied beta document",
                "text": "EXTERNAL_SCOPE_BETA_MARKER must not be written.",
                "source_type": "document",
                "source_external_id": "external-doc-beta",
            },
            headers=scoped_headers,
        )
        fact = client.post(
            "/v1/facts",
            json={
                **allowed_scope,
                "text": "EXTERNAL_SCOPE_FACT_ALPHA_MARKER can be written by alpha token.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "external-fact-alpha"}],
            },
            headers=scoped_headers,
        )
        denied_fact = client.post(
            "/v1/facts",
            json={
                **denied_scope,
                "text": "EXTERNAL_SCOPE_FACT_BETA_MARKER must not be written.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "external-fact-beta"}],
            },
            headers=scoped_headers,
        )

    assert episode.status_code == 200
    assert context.status_code == 200
    assert "EXTERNAL_SCOPE_ALPHA_MARKER" in context.json()["data"]["rendered_text"]
    assert denied_context.status_code == 403
    assert denied_document.status_code == 403
    assert fact.status_code == 201
    assert denied_fact.status_code == 403
    assert "EXTERNAL_SCOPE_BETA_MARKER" not in denied_document.text
    assert "EXTERNAL_SCOPE_FACT_BETA_MARKER" not in denied_fact.text


def test_reset_local_refuses_without_confirmation_and_server_memory_scope(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "local")
    refused = asyncio.run(reset_local(confirmed=False))
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "server")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    server_refused = asyncio.run(reset_local(confirmed=True))

    assert refused["status"] == "refused"
    assert server_refused == {
        "status": "refused",
        "reason": "reset-local is forbidden in server deploy profile",
    }


def test_export_redacted_mode_omits_restricted_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "transfer.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers={"Authorization": "Bearer root-token"},
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers={"Authorization": "Bearer root-token"},
        ).json()["data"]
        client.post(
            "/v1/documents",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "title": "Transfer notes",
                "text": "TRANSFER_SECRET_MARKER must be redacted from chunk export.",
                "source_type": "document",
                "source_external_id": "transfer-doc",
            },
            headers={"Authorization": "Bearer root-token"},
        )
        client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Transfer fact text should be redacted.",
                "kind": "note",
                "classification": "restricted",
                "source_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "transfer-fact",
                        "quote_preview": "SOURCE_REF_SECRET_MARKER must be redacted from export.",
                    }
                ],
            },
            headers={"Authorization": "Bearer root-token"},
        )

    out = tmp_path / "memory_scope-export.json"
    exported = asyncio.run(
        export_memory_scope_command(
            space="client-app",
            memory_scope="default",
            out=str(out),
            redacted=True,
        )
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    imported = asyncio.run(
        import_memory_scope_command(
            space="dry-run-space",
            memory_scope="dry-run-memory_scope",
            file=str(out),
            dry_run=True,
            merge_strategy="fail_on_conflict",
        )
    )
    refused_import = asyncio.run(
        import_memory_scope_command(
            space="write-space",
            memory_scope="write-memory_scope",
            file=str(out),
            dry_run=False,
            merge_strategy="skip_existing",
        )
    )
    refused_redacted_import = asyncio.run(
        import_memory_scope_command(
            space="write-space",
            memory_scope="write-memory_scope",
            file=str(out),
            dry_run=False,
            merge_strategy="skip_existing",
            confirmed=True,
        )
    )
    dry_run_scope = asyncio.run(
        export_memory_scope_command(
            space="dry-run-space",
            memory_scope="dry-run-memory_scope",
            out=str(tmp_path / "dry-run-export.json"),
            redacted=True,
        )
    )

    assert exported["status"] == "ok"
    assert exported["facts"] == 1
    assert exported["chunks"] == 1
    assert "TRANSFER_SECRET_MARKER" not in out.read_text(encoding="utf-8")
    assert "SOURCE_REF_SECRET_MARKER" not in out.read_text(encoding="utf-8")
    assert payload["facts"][0]["text"] is None
    assert payload["chunks"][0]["text"] is None
    assert payload["source_refs"][0]["quote_preview"] is None
    assert imported["status"] == "conflict"
    assert imported["dry_run"] is True
    assert refused_import == {
        "status": "refused",
        "reason": "import-memory_scope requires --i-understand-this-writes-canonical-memory",
    }
    assert refused_redacted_import == {
        "status": "refused",
        "reason": "redacted_memory_scope_export_cannot_be_imported",
    }
    assert dry_run_scope["status"] == "not_found"


def test_export_memory_scope_refuses_deleted_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "deleted-transfer.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "deleted-export", "name": "Deleted Export"},
            headers=headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=headers,
        ).json()["data"]
        deleted_space = client.post(
            "/v1/spaces",
            json={"slug": "deleted-export-space", "name": "Deleted Export Space"},
            headers=headers,
        ).json()["data"]
        deleted_space_memory_scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": deleted_space["id"],
                "external_ref": "default",
                "name": "Default",
            },
            headers=headers,
        ).json()["data"]
        for scope_space, scope_memory_scope, marker in (
            (space, memory_scope, "DELETED_MEMORY_SCOPE_EXPORT_SECRET"),
            (deleted_space, deleted_space_memory_scope, "DELETED_SPACE_EXPORT_SECRET"),
        ):
            client.post(
                "/v1/facts",
                json={
                    "space_id": scope_space["id"],
                    "memory_scope_id": scope_memory_scope["id"],
                    "text": f"{marker} must not be exported after scope deletion.",
                    "kind": "note",
                    "source_refs": [{"source_type": "manual", "source_id": marker.lower()}],
                },
                headers=headers,
            )

    asyncio.run(_mark_scope_deleted(app, memory_scope_id=memory_scope["id"]))
    asyncio.run(_mark_scope_deleted(app, space_id=deleted_space["id"]))
    deleted_memory_scope_out = tmp_path / "deleted-memory_scope-export.json"
    deleted_space_out = tmp_path / "deleted-space-export.json"

    deleted_memory_scope_export = asyncio.run(
        export_memory_scope_command(
            space="deleted-export",
            memory_scope="default",
            out=str(deleted_memory_scope_out),
            redacted=False,
        )
    )
    deleted_space_export = asyncio.run(
        export_memory_scope_command(
            space="deleted-export-space",
            memory_scope="default",
            out=str(deleted_space_out),
            redacted=False,
        )
    )

    assert deleted_memory_scope_export == {
        "status": "not_found",
        "out": str(deleted_memory_scope_out),
    }
    assert deleted_space_export == {"status": "not_found", "out": str(deleted_space_out)}
    assert not deleted_memory_scope_out.exists()
    assert not deleted_space_out.exists()


def test_import_memory_scope_enqueues_projection_reindex_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "import.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    fixture = tmp_path / "memory_scope-import.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "space": {"slug": "source-space"},
                "memory_scope": {"external_ref": "source-memory_scope"},
                "facts": [
                    {
                        "id": "fact_imported_reindex",
                        "kind": "architecture_decision",
                        "text": "Imported facts should enqueue graph reindex.",
                        "status": "active",
                        "confidence": "medium",
                        "trust_level": "medium",
                        "classification": "internal",
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "documents": [
                    {
                        "id": "doc_imported_reindex",
                        "title": "Imported document",
                        "source_type": "document",
                        "source_external_id": "doc-imported",
                        "content_hash": "doc-imported-hash",
                        "classification": "internal",
                        "status": "active",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "chunks": [
                    {
                        "id": "chunk_imported_reindex",
                        "document_id": "doc_imported_reindex",
                        "source_type": "document",
                        "source_external_id": "doc-imported",
                        "source_hash": "chunk-imported-hash",
                        "kind": "document_section",
                        "text": "Imported chunks should enqueue vector reindex.",
                        "normalized_text": "imported chunks should enqueue vector reindex.",
                        "status": "active",
                        "sequence": 0,
                        "char_start": 0,
                        "char_end": 48,
                        "token_estimate": 12,
                        "classification": "internal",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {},
                    }
                ],
                "source_refs": [
                    {
                        "fact_id": "fact_imported_reindex",
                        "fact_version": 1,
                        "source_type": "import",
                        "source_id": "fixture",
                        "chunk_id": "chunk_imported_reindex",
                        "quote_preview": "bounded source ref",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = asyncio.run(
        import_memory_scope_command(
            space="import-space",
            memory_scope="default",
            file=str(fixture),
            dry_run=False,
            merge_strategy="fail_on_conflict",
            confirmed=True,
        )
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    with TestClient(app) as client:
        outbox = client.get(
            "/v1/diagnostics/outbox",
            headers={"Authorization": "Bearer root-token"},
        )

    items = outbox.json()["data"]["items"]
    event_types = {item["event_type"] for item in items}
    fairness_keys = {item["fairness_key"] for item in items}

    assert imported["status"] == "ok"
    assert imported["imported"] == {
        "threads": 0,
        "facts": 1,
        "documents": 1,
        "episodes": 0,
        "chunks": 1,
        "assets": 0,
        "asset_extraction_jobs": 0,
        "extraction_artifacts": 0,
        "captures": 0,
        "anchors": 0,
        "context_links": 0,
        "context_link_suggestions": 0,
        "relations": 0,
        "source_refs": 1,
    }
    assert event_types == {"graph.upsert_fact", "vector.upsert_chunk"}
    assert fairness_keys == {"fact:fact_imported_reindex", "chunk:chunk_imported_reindex"}
    assert all(item["workload_class"] == "projection" for item in items)


def test_import_memory_scope_drops_thread_ids_without_thread_transfer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "thread-import.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    fixture = tmp_path / "thread-memory_scope-import.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "space": {"slug": "source-space"},
                "memory_scope": {"external_ref": "source-memory_scope"},
                "facts": [
                    {
                        "id": "fact_imported_thread",
                        "thread_id": "thread_source_only",
                        "kind": "architecture_decision",
                        "text": "Imported fact thread ids should not become orphan refs.",
                        "status": "active",
                        "confidence": "medium",
                        "trust_level": "medium",
                        "classification": "internal",
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "documents": [
                    {
                        "id": "doc_imported_thread",
                        "thread_id": "thread_source_only",
                        "title": "Imported threaded document",
                        "source_type": "document",
                        "source_external_id": "doc-imported-thread",
                        "content_hash": "doc-imported-thread-hash",
                        "classification": "internal",
                        "status": "active",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "chunks": [
                    {
                        "id": "chunk_imported_thread",
                        "thread_id": "thread_source_only",
                        "document_id": "doc_imported_thread",
                        "source_type": "document",
                        "source_external_id": "doc-imported-thread",
                        "source_hash": "chunk-imported-thread-hash",
                        "kind": "document_section",
                        "text": "Imported chunk thread ids should not become orphan refs.",
                        "normalized_text": (
                            "imported chunk thread ids should not become orphan refs."
                        ),
                        "status": "active",
                        "sequence": 0,
                        "char_start": 0,
                        "char_end": 57,
                        "token_estimate": 14,
                        "classification": "internal",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {},
                    }
                ],
                "source_refs": [
                    {
                        "fact_id": "fact_imported_thread",
                        "fact_version": 1,
                        "source_type": "import",
                        "source_id": "fixture",
                        "chunk_id": "chunk_imported_thread",
                        "quote_preview": "thread source ref",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = asyncio.run(
        import_memory_scope_command(
            space="thread-import-space",
            memory_scope="default",
            file=str(fixture),
            dry_run=False,
            merge_strategy="fail_on_conflict",
            confirmed=True,
        )
    )

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    async def load_thread_refs() -> tuple[str | None, str | None, str | None]:
        async with AsyncSession(app.state.container.engine) as session:
            fact = await session.get(MemoryFactRow, "fact_imported_thread")
            document = await session.get(MemoryDocumentRow, "doc_imported_thread")
            chunk = await session.get(MemoryChunkRow, "chunk_imported_thread")
            assert fact is not None
            assert document is not None
            assert chunk is not None
            return fact.thread_id, document.thread_id, chunk.thread_id

    fact_thread_id, document_thread_id, chunk_thread_id = asyncio.run(load_thread_refs())

    assert imported["status"] == "ok"
    assert imported["imported"] == {
        "threads": 0,
        "facts": 1,
        "documents": 1,
        "episodes": 0,
        "chunks": 1,
        "assets": 0,
        "asset_extraction_jobs": 0,
        "extraction_artifacts": 0,
        "captures": 0,
        "anchors": 0,
        "context_links": 0,
        "context_link_suggestions": 0,
        "relations": 0,
        "source_refs": 1,
    }
    assert fact_thread_id is None
    assert document_thread_id is None
    assert chunk_thread_id is None


def test_import_memory_scope_transfers_episode_chunks_with_import_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "episode-import.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    fixture = tmp_path / "episode-memory_scope-import.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "space": {"slug": "source-space"},
                "memory_scope": {"external_ref": "source-memory_scope"},
                "facts": [
                    {
                        "id": "fact_imported_episode_ref",
                        "thread_id": "thread_source_only",
                        "kind": "preference",
                        "text": "Imported episode chunks should remain evidence.",
                        "status": "active",
                        "confidence": "medium",
                        "trust_level": "medium",
                        "classification": "internal",
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "documents": [],
                "episodes": [
                    {
                        "id": "episode_imported_ref",
                        "thread_id": "thread_source_only",
                        "source_type": "conversation",
                        "source_external_id": "episode-imported-ref",
                        "text": "Episode import transcript should survive snapshot transfer.",
                        "speaker": "user",
                        "trust_level": "high",
                        "status": "active",
                        "occurred_at": "2026-01-01T00:00:00+00:00",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {"language": "en"},
                    }
                ],
                "chunks": [
                    {
                        "id": "chunk_imported_episode_ref",
                        "thread_id": "thread_source_only",
                        "document_id": None,
                        "episode_id": "episode_imported_ref",
                        "source_type": "conversation",
                        "source_external_id": "episode-imported-ref",
                        "source_hash": "chunk-imported-episode-ref-hash",
                        "kind": "episode_excerpt",
                        "text": "Episode import transcript should survive snapshot transfer.",
                        "normalized_text": (
                            "episode import transcript should survive snapshot transfer."
                        ),
                        "status": "active",
                        "sequence": 0,
                        "char_start": 0,
                        "char_end": 57,
                        "token_estimate": 14,
                        "classification": "internal",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {"episode_id": "episode_imported_ref"},
                    }
                ],
                "source_refs": [
                    {
                        "fact_id": "fact_imported_episode_ref",
                        "fact_version": 1,
                        "source_type": "import",
                        "source_id": "fixture",
                        "chunk_id": "chunk_imported_episode_ref",
                        "quote_preview": "episode source ref",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = asyncio.run(
        import_memory_scope_command(
            space="episode-import-space",
            memory_scope="default",
            file=str(fixture),
            dry_run=False,
            merge_strategy="fail_on_conflict",
            confirmed=True,
        )
    )

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    async def load_imported_rows() -> tuple[
        MemoryEpisodeRow,
        MemoryChunkRow,
        MemoryThreadRow,
        list[MemorySourceRefRow],
    ]:
        async with AsyncSession(app.state.container.engine) as session:
            episode = await session.get(MemoryEpisodeRow, "episode_imported_ref")
            chunk = await session.get(MemoryChunkRow, "chunk_imported_episode_ref")
            refs = list(
                (
                    await session.execute(
                        select(MemorySourceRefRow).where(
                            MemorySourceRefRow.fact_id == "fact_imported_episode_ref"
                        )
                    )
                ).scalars()
            )
            assert episode is not None
            assert chunk is not None
            thread = await session.get(MemoryThreadRow, episode.thread_id)
            assert thread is not None
            return episode, chunk, thread, refs

    episode, chunk, thread, refs = asyncio.run(load_imported_rows())

    assert imported["status"] == "ok"
    assert imported["imported"] == {
        "threads": 0,
        "facts": 1,
        "documents": 0,
        "episodes": 1,
        "chunks": 1,
        "assets": 0,
        "asset_extraction_jobs": 0,
        "extraction_artifacts": 0,
        "captures": 0,
        "anchors": 0,
        "context_links": 0,
        "context_link_suggestions": 0,
        "relations": 0,
        "source_refs": 1,
    }
    assert episode.thread_id != "thread_source_only"
    assert episode.thread_id == thread.id
    assert thread.external_ref.startswith("imported-thread_source_only-")
    assert chunk.thread_id == episode.thread_id
    assert chunk.episode_id == episode.id
    assert refs[0].chunk_id == chunk.id


def test_import_memory_scope_skips_episode_chunks_without_episode_transfer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "episode-chunk-import.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    fixture = tmp_path / "episode-chunk-memory_scope-import.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "space": {"slug": "source-space"},
                "memory_scope": {"external_ref": "source-memory_scope"},
                "facts": [
                    {
                        "id": "fact_imported_episode_chunk",
                        "thread_id": "thread_source_only",
                        "kind": "preference",
                        "text": "Imported facts should survive unsupported episode chunks.",
                        "status": "active",
                        "confidence": "medium",
                        "trust_level": "medium",
                        "classification": "internal",
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "documents": [],
                "chunks": [
                    {
                        "id": "chunk_imported_episode_only",
                        "thread_id": "thread_source_only",
                        "document_id": None,
                        "episode_id": "episode_source_only",
                        "source_type": "conversation",
                        "source_external_id": "episode-source",
                        "source_hash": "chunk-imported-episode-only-hash",
                        "kind": "episode_excerpt",
                        "text": "Unsupported episode chunks should not be imported.",
                        "normalized_text": "unsupported episode chunks should not be imported.",
                        "status": "active",
                        "sequence": 0,
                        "char_start": 0,
                        "char_end": 51,
                        "token_estimate": 13,
                        "classification": "internal",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {},
                    },
                    {
                        "id": "chunk_imported_missing_document",
                        "thread_id": "thread_source_only",
                        "document_id": "doc_not_in_payload",
                        "episode_id": None,
                        "source_type": "document",
                        "source_external_id": "missing-doc-source",
                        "source_hash": "chunk-imported-missing-doc-hash",
                        "kind": "document_section",
                        "text": "Chunks cannot point at documents outside the import payload.",
                        "normalized_text": (
                            "chunks cannot point at documents outside the import payload."
                        ),
                        "status": "active",
                        "sequence": 1,
                        "char_start": 0,
                        "char_end": 59,
                        "token_estimate": 15,
                        "classification": "internal",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "metadata_json": {},
                    },
                ],
                "source_refs": [
                    {
                        "fact_id": "fact_imported_episode_chunk",
                        "fact_version": 1,
                        "source_type": "import",
                        "source_id": "fixture",
                        "chunk_id": "chunk_imported_episode_only",
                        "quote_preview": "episode source ref",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = asyncio.run(
        import_memory_scope_command(
            space="episode-chunk-import-space",
            memory_scope="default",
            file=str(fixture),
            dry_run=False,
            merge_strategy="fail_on_conflict",
            confirmed=True,
        )
    )

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    async def load_imported_rows() -> tuple[MemoryFactRow | None, list[MemorySourceRefRow]]:
        async with AsyncSession(app.state.container.engine) as session:
            fact = await session.get(MemoryFactRow, "fact_imported_episode_chunk")
            episode_chunk = await session.get(MemoryChunkRow, "chunk_imported_episode_only")
            missing_document_chunk = await session.get(
                MemoryChunkRow,
                "chunk_imported_missing_document",
            )
            refs = list(
                (
                    await session.execute(
                        select(MemorySourceRefRow).where(
                            MemorySourceRefRow.fact_id == "fact_imported_episode_chunk"
                        )
                    )
                ).scalars()
            )
            assert episode_chunk is None
            assert missing_document_chunk is None
            return fact, refs

    fact, refs = asyncio.run(load_imported_rows())

    assert imported["status"] == "ok"
    assert imported["imported"] == {
        "threads": 0,
        "facts": 1,
        "documents": 0,
        "episodes": 0,
        "chunks": 0,
        "assets": 0,
        "asset_extraction_jobs": 0,
        "extraction_artifacts": 0,
        "captures": 0,
        "anchors": 0,
        "context_links": 0,
        "context_link_suggestions": 0,
        "relations": 0,
        "source_refs": 0,
    }
    assert fact is not None
    assert len(refs) == 1
    assert refs[0].chunk_id is None
    assert refs[0].source_type == "import"


def test_import_memory_scope_create_new_memory_scope_rewrites_canonical_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "create-new-memory_scope.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=headers,
        ).json()["data"]
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Portable import should not overwrite the original memory_scope.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "portable-fact"}],
            },
            headers=headers,
        ).json()["data"]

    export_path = tmp_path / "memory_scope-export.json"
    exported = asyncio.run(
        export_memory_scope_command(
            space="client-app",
            memory_scope="default",
            out=str(export_path),
            redacted=False,
        )
    )
    imported = asyncio.run(
        import_memory_scope_command(
            space="client-app",
            memory_scope="default",
            file=str(export_path),
            dry_run=False,
            merge_strategy="create_new_memory_scope",
            confirmed=True,
        )
    )

    async def load_rows() -> tuple[list[MemoryFactRow], list[dict[str, str]]]:
        async with AsyncSession(app.state.container.engine) as session:
            facts = list(
                (
                    await session.execute(
                        select(MemoryFactRow).order_by(
                            MemoryFactRow.memory_scope_id,
                            MemoryFactRow.id,
                        )
                    )
                ).scalars()
            )
        with TestClient(app) as client:
            memory_scopes = client.get(
                "/v1/memory-scopes",
                params={"space_id": space["id"]},
                headers=headers,
            ).json()["data"]
        return facts, memory_scopes

    facts, memory_scopes = asyncio.run(load_rows())
    created_memory_scope = imported["created_memory_scope"]
    new_memory_scope_facts = [
        row for row in facts if row.memory_scope_id == created_memory_scope["id"]
    ]
    original_memory_scope_facts = [
        row for row in facts if row.memory_scope_id == memory_scope["id"]
    ]

    assert exported["status"] == "ok"
    assert imported["status"] == "ok"
    assert imported["merge_strategy"] == "create_new_memory_scope"
    assert created_memory_scope["external_ref"].startswith("default-import-")
    assert {item["external_ref"] for item in memory_scopes} == {
        "default",
        created_memory_scope["external_ref"],
    }
    assert [row.id for row in original_memory_scope_facts] == [fact["id"]]
    assert len(new_memory_scope_facts) == 1
    assert new_memory_scope_facts[0].id != fact["id"]
    assert new_memory_scope_facts[0].text == fact["text"]


def test_import_memory_scope_supersede_matching_facts_keeps_history_and_reindexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "supersede-import.db"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            service_token="root-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=headers,
        ).json()["data"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "default", "name": "Default"},
            headers=headers,
        ).json()["data"]
        original = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope["id"],
                "text": "Old imported fact value.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "original"}],
            },
            headers=headers,
        ).json()["data"]

    fixture = tmp_path / "supersede-memory_scope.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "space": {"slug": "source-space"},
                "memory_scope": {"external_ref": "source-memory_scope"},
                "facts": [
                    {
                        "id": original["id"],
                        "kind": "note",
                        "text": "New imported fact value.",
                        "status": "active",
                        "confidence": "medium",
                        "trust_level": "medium",
                        "classification": "internal",
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "documents": [],
                "chunks": [],
                "source_refs": [
                    {
                        "fact_id": original["id"],
                        "fact_version": 1,
                        "source_type": "import",
                        "source_id": "supersede-fixture",
                        "quote_preview": "new value",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = asyncio.run(
        import_memory_scope_command(
            space="client-app",
            memory_scope="default",
            file=str(fixture),
            dry_run=False,
            merge_strategy="supersede_matching_facts",
            confirmed=True,
        )
    )

    async def load_rows() -> tuple[list[MemoryFactRow], list[MemoryOutboxRow]]:
        async with AsyncSession(app.state.container.engine) as session:
            facts = list(
                (
                    await session.execute(
                        select(MemoryFactRow).order_by(MemoryFactRow.created_at, MemoryFactRow.id)
                    )
                ).scalars()
            )
            outbox = list(
                (
                    await session.execute(select(MemoryOutboxRow).order_by(MemoryOutboxRow.id))
                ).scalars()
            )
            return facts, outbox

    facts, outbox = asyncio.run(load_rows())
    original_row = next(row for row in facts if row.id == original["id"])
    imported_rows = [row for row in facts if row.id != original["id"]]
    event_pairs = {(row.event_type, row.aggregate_id) for row in outbox}

    assert imported["status"] == "ok"
    assert imported["merge_strategy"] == "supersede_matching_facts"
    assert original_row.status == "superseded"
    assert original_row.version == 2
    assert len(imported_rows) == 1
    assert imported_rows[0].status == "active"
    assert imported_rows[0].text == "New imported fact value."
    assert ("graph.delete_fact", original["id"]) in event_pairs
    assert ("graph.upsert_fact", imported_rows[0].id) in event_pairs
