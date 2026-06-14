from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app


def make_client(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_users_space_memberships_and_access_checks(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "team-space", "name": "Team Space"},
            headers=auth_headers(),
        )
        assert space.status_code == 201, space.text
        space_id = space.json()["data"]["id"]

        user = client.post(
            "/v1/users",
            json={
                "external_ref": "user:alex@example.com",
                "display_name": "Alex",
                "email": "alex@example.com",
                "metadata": {"source": "test"},
            },
            headers=auth_headers(),
        )
        assert user.status_code == 201, user.text
        user_id = user.json()["data"]["id"]

        duplicate_user = client.post(
            "/v1/users",
            json={
                "external_ref": "user:alex@example.com",
                "display_name": "Alex Duplicate",
                "email": "alex@example.com",
            },
            headers=auth_headers(),
        )
        assert duplicate_user.status_code == 200, duplicate_user.text
        assert duplicate_user.json()["data"]["id"] == user_id

        listed_users = client.get("/v1/users", headers=auth_headers())
        assert listed_users.status_code == 200, listed_users.text
        assert [item["id"] for item in listed_users.json()["data"]] == [user_id]

        owner_membership = client.post(
            f"/v1/spaces/{space_id}/memberships",
            json={"user_id": user_id, "role": "owner"},
            headers=auth_headers(),
        )
        assert owner_membership.status_code == 201, owner_membership.text
        membership_id = owner_membership.json()["data"]["id"]

        access_as_admin = client.get(
            f"/v1/spaces/{space_id}/memberships/{user_id}/access",
            params={"required_role": "admin"},
            headers=auth_headers(),
        )
        assert access_as_admin.status_code == 200, access_as_admin.text
        assert access_as_admin.json()["data"]["allowed"] is True
        assert access_as_admin.json()["data"]["membership"]["role"] == "owner"

        viewer_membership = client.post(
            f"/v1/spaces/{space_id}/memberships",
            json={"user_id": user_id, "role": "viewer"},
            headers=auth_headers(),
        )
        assert viewer_membership.status_code == 200, viewer_membership.text
        assert viewer_membership.json()["data"]["id"] == membership_id
        assert viewer_membership.json()["data"]["role"] == "viewer"

        listed_memberships = client.get(
            f"/v1/spaces/{space_id}/memberships",
            headers=auth_headers(),
        )
        assert listed_memberships.status_code == 200, listed_memberships.text
        assert [item["id"] for item in listed_memberships.json()["data"]] == [membership_id]

        member_access = client.get(
            f"/v1/spaces/{space_id}/memberships/{user_id}/access",
            params={"required_role": "member"},
            headers=auth_headers(),
        )
        viewer_access = client.get(
            f"/v1/spaces/{space_id}/memberships/{user_id}/access",
            params={"required_role": "viewer"},
            headers=auth_headers(),
        )
        assert member_access.status_code == 200, member_access.text
        assert viewer_access.status_code == 200, viewer_access.text
        assert member_access.json()["data"]["allowed"] is False
        assert viewer_access.json()["data"]["allowed"] is True
