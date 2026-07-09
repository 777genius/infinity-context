from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_server.config import DeployProfile, MemoryPolicyMode, Settings
from infinity_context_server.main import create_app


def make_client(tmp_path: Path, **overrides: object) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_create_and_list_spaces_memory_scopes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        )
        space_id = space.json()["data"]["id"]
        duplicate_space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        )
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        memory_scope_id = memory_scope.json()["data"]["id"]
        duplicate_memory_scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        spaces = client.get("/v1/spaces", headers=auth_headers())
        memory_scopes = client.get(
            "/v1/memory-scopes",
            params={"space_id": space_id},
            headers=auth_headers(),
        )

    assert space.status_code == 201
    assert duplicate_space.status_code == 200
    assert duplicate_space.json()["data"]["id"] == space_id
    assert memory_scope.status_code == 201
    assert duplicate_memory_scope.status_code == 200
    assert duplicate_memory_scope.json()["data"]["id"] == memory_scope_id
    assert [item["id"] for item in spaces.json()["data"]] == [space_id]
    assert [item["id"] for item in memory_scopes.json()["data"]] == [memory_scope_id]


def test_memory_scope_requires_existing_space(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": "space_missing",
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "memory.not_found"


def test_update_and_delete_memory_scope(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        )
        space_id = space.json()["data"]["id"]
        memory_scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        memory_scope_id = memory_scope.json()["data"]["id"]

        updated = client.patch(
            f"/v1/memory-scopes/{memory_scope_id}",
            json={"external_ref": "sales-crm", "name": "Sales CRM"},
            headers=auth_headers(),
        )
        listed_after_update = client.get(
            "/v1/memory-scopes",
            params={"space_id": space_id},
            headers=auth_headers(),
        )
        deleted = client.delete(
            f"/v1/memory-scopes/{memory_scope_id}",
            headers=auth_headers(),
        )
        listed_after_delete = client.get(
            "/v1/memory-scopes",
            params={"space_id": space_id},
            headers=auth_headers(),
        )
        recreated = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "sales-crm",
                "name": "Sales CRM Restored",
            },
            headers=auth_headers(),
        )

    assert updated.status_code == 200
    assert updated.json()["data"]["external_ref"] == "sales-crm"
    assert updated.json()["data"]["name"] == "Sales CRM"
    assert [item["external_ref"] for item in listed_after_update.json()["data"]] == ["sales-crm"]
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert listed_after_delete.json()["data"] == []
    assert recreated.status_code == 200
    assert recreated.json()["data"]["id"] == memory_scope_id
    assert recreated.json()["data"]["status"] == "active"
    assert recreated.json()["data"]["name"] == "Sales CRM Restored"


def test_update_memory_scope_rejects_duplicate_ref(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "client-app", "name": "Client App"},
            headers=auth_headers(),
        )
        space_id = space.json()["data"]["id"]
        first = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "first",
                "name": "First",
            },
            headers=auth_headers(),
        )
        second = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": "second",
                "name": "Second",
            },
            headers=auth_headers(),
        )

        duplicate = client.patch(
            f"/v1/memory-scopes/{second.json()['data']['id']}",
            json={"external_ref": first.json()["data"]["external_ref"]},
            headers=auth_headers(),
        )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "memory.conflict"


def test_disabled_policy_blocks_space_memory_scope_writes(tmp_path: Path) -> None:
    with make_client(tmp_path, policy_mode=MemoryPolicyMode.DISABLED) as client:
        response = client.post(
            "/v1/spaces",
            json={"slug": "blocked", "name": "Blocked"},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"
