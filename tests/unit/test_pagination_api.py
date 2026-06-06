from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_facts_cursor_is_opaque_stable_and_scope_safe(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for text in ("FACT_CURSOR_SECRET_A", "FACT_CURSOR_SECRET_B"):
            client.post(
                "/v1/facts",
                json={
                    "space_id": "space_client_app",
                    "profile_id": "profile_default",
                    "text": text,
                    "kind": "note",
                    "source_refs": [{"source_type": "manual", "source_id": text}],
                },
                headers=auth_headers(),
            )
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_other",
                "text": "FACT_CURSOR_OTHER_PROFILE",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "other"}],
            },
            headers=auth_headers(),
        )
        page_1 = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "limit": 1,
            },
            headers=auth_headers(),
        )
        cursor = page_1.json()["next_cursor"]
        page_2 = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "limit": 1,
                "cursor": cursor,
            },
            headers=auth_headers(),
        )
        invalid = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "cursor": "not-a-valid-cursor",
            },
            headers=auth_headers(),
        )

    assert page_1.status_code == 200
    assert page_2.status_code == 200
    assert cursor
    assert "FACT_CURSOR_SECRET" not in cursor
    texts = {page_1.json()["data"][0]["text"], page_2.json()["data"][0]["text"]}
    assert texts == {"FACT_CURSOR_SECRET_A", "FACT_CURSOR_SECRET_B"}
    assert "FACT_CURSOR_OTHER_PROFILE" not in str(page_1.json())
    assert "FACT_CURSOR_OTHER_PROFILE" not in str(page_2.json())
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "memory.validation"


def test_document_chunks_cursor_is_opaque_and_ordered(tmp_path: Path) -> None:
    text = ("DOC_CURSOR_SECRET_A. " * 90) + "\n\n" + ("DOC_CURSOR_SECRET_B. " * 90)
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Cursor document",
                "text": text,
                "source_type": "document",
                "source_external_id": "doc-cursor",
            },
            headers=auth_headers(),
        ).json()["data"]
        page_1 = client.get(
            f"/v1/documents/{document['id']}/chunks",
            params={"limit": 1},
            headers=auth_headers(),
        )
        cursor = page_1.json()["next_cursor"]
        page_2 = client.get(
            f"/v1/documents/{document['id']}/chunks",
            params={"limit": 1, "cursor": cursor},
            headers=auth_headers(),
        )
        invalid = client.get(
            f"/v1/documents/{document['id']}/chunks",
            params={"cursor": "not-a-valid-cursor"},
            headers=auth_headers(),
        )

    assert page_1.status_code == 200
    assert page_2.status_code == 200
    assert cursor
    assert "DOC_CURSOR_SECRET" not in cursor
    assert page_1.json()["data"][0]["sequence"] == 0
    assert page_2.json()["data"][0]["sequence"] == 1
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "memory.validation"


def test_diagnostics_outbox_cursor_is_opaque(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for idx in range(2):
            client.post(
                "/v1/documents",
                json={
                    "space_id": "space_client_app",
                    "profile_id": "profile_default",
                    "title": f"Outbox cursor {idx}",
                    "text": f"OUTBOX_CURSOR_SECRET_{idx}",
                    "source_type": "document",
                    "source_external_id": f"outbox-cursor-{idx}",
                },
                headers=auth_headers(),
            )
        page_1 = client.get(
            "/v1/diagnostics/outbox",
            params={"limit": 1},
            headers=auth_headers(),
        )
        cursor = page_1.json()["data"]["next_cursor"]
        page_2 = client.get(
            "/v1/diagnostics/outbox",
            params={"limit": 1, "cursor": cursor},
            headers=auth_headers(),
        )
        invalid = client.get(
            "/v1/diagnostics/outbox",
            params={"cursor": "not-a-valid-cursor"},
            headers=auth_headers(),
        )

    assert page_1.status_code == 200
    assert page_2.status_code == 200
    assert cursor
    assert "OUTBOX_CURSOR_SECRET" not in cursor
    assert page_1.json()["data"]["items"][0]["id"] != page_2.json()["data"]["items"][0]["id"]
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "memory.validation"
