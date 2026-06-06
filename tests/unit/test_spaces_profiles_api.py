from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, MemoryPolicyMode, Settings
from memo_stack_server.main import create_app


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


def test_create_and_list_spaces_profiles(tmp_path: Path) -> None:
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
        profile = client.post(
            "/v1/profiles",
            json={
                "space_id": space_id,
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        profile_id = profile.json()["data"]["id"]
        duplicate_profile = client.post(
            "/v1/profiles",
            json={
                "space_id": space_id,
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        spaces = client.get("/v1/spaces", headers=auth_headers())
        profiles = client.get(
            "/v1/profiles",
            params={"space_id": space_id},
            headers=auth_headers(),
        )

    assert space.status_code == 201
    assert duplicate_space.status_code == 200
    assert duplicate_space.json()["data"]["id"] == space_id
    assert profile.status_code == 201
    assert duplicate_profile.status_code == 200
    assert duplicate_profile.json()["data"]["id"] == profile_id
    assert [item["id"] for item in spaces.json()["data"]] == [space_id]
    assert [item["id"] for item in profiles.json()["data"]] == [profile_id]


def test_profile_requires_existing_space(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/profiles",
            json={
                "space_id": "space_missing",
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "memory.not_found"


def test_disabled_policy_blocks_space_profile_writes(tmp_path: Path) -> None:
    with make_client(tmp_path, policy_mode=MemoryPolicyMode.DISABLED) as client:
        response = client.post(
            "/v1/spaces",
            json={"slug": "blocked", "name": "Blocked"},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"
