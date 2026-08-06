"""Real persistence contract for stable episode ingestion receipts."""

from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'episode-replay.db'}",
                auto_create_schema=True,
                service_token="test-token",
                qdrant_enabled=False,
                graphiti_enabled=False,
                embeddings_enabled=False,
            )
        )
    )


def test_episode_api_create_and_replay_return_identical_canonical_ids(tmp_path: Path) -> None:
    request = {
        "space_slug": "benchmark-replay",
        "memory_scope_external_ref": "ic_" + "1" * 64,
        "thread_external_ref": "ic_" + "1" * 64,
        "source_type": "transcript",
        "source_external_id": "iu_" + "2" * 64,
        "idempotency_key": "iu_" + "2" * 64,
        "text": "Stable canonical episode replay.",
        "occurred_at": "2024-01-02T03:04:05Z",
        "speaker": "user",
        "trust_level": "medium",
        "kind_hint": "raw_transcript_chunk",
    }
    headers = {"Authorization": "Bearer test-token"}
    with _client(tmp_path) as client:
        created = client.post("/v1/episodes", json=request, headers=headers)
        replayed = client.post("/v1/episodes", json=request, headers=headers)

    assert created.status_code == replayed.status_code == 200
    created_data = created.json()["data"]
    replayed_data = replayed.json()["data"]
    assert created_data["episode_id"] == replayed_data["episode_id"]
    assert created_data["chunk_ids"] == replayed_data["chunk_ids"]
    assert created_data["chunk_ids"]
    assert {key: created_data[key] for key in ("space_id", "memory_scope_id", "thread_id")} == {
        key: replayed_data[key] for key in ("space_id", "memory_scope_id", "thread_id")
    }
    assert created_data["stored_chunks"] == 1
    assert created_data["duplicate_chunks"] == 0
    assert replayed_data["stored_chunks"] == 0
    assert replayed_data["duplicate_chunks"] == 1
