import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.repositories import PostgresSuggestionRepository
from infinity_context_adapters.postgres.unit_of_work import PostgresUnitOfWork
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
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
    )


def test_approval_rolls_back_fact_outbox_and_suggestion_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "memory.db"
    headers = {"Authorization": "Bearer test-token"}
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "candidate_text": "ATOMIC_REVIEW_ROLLBACK marker.",
                "kind": "architecture_decision",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": "review-1"}],
            },
            headers=headers,
        )
        suggestion_id = created.json()["data"]["id"]

        async def fail_after_fact_mutation(self, suggestion):
            del self, suggestion
            raise RuntimeError("review failpoint")

        with monkeypatch.context() as scoped:
            scoped.setattr(PostgresSuggestionRepository, "save", fail_after_fact_mutation)
            with pytest.raises(RuntimeError, match="review failpoint"):
                client.post(
                    f"/v1/suggestions/{suggestion_id}/approve",
                    json={"reason": "exercise rollback"},
                    headers=headers,
                )

    with sqlite3.connect(database_path) as connection:
        suggestion_status = connection.execute(
            "SELECT status FROM memory_suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        fact_count = connection.execute(
            "SELECT COUNT(*) FROM memory_facts WHERE text = ?",
            ("ATOMIC_REVIEW_ROLLBACK marker.",),
        ).fetchone()
        outbox_count = connection.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE aggregate_type = 'fact'"
        ).fetchone()

    assert suggestion_status == ("pending",)
    assert fact_count == (0,)
    assert outbox_count == (0,)


def test_approval_replays_exact_result_after_unknown_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "memory.db"
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "approve-unknown-commit-1",
    }
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "candidate_text": "EXACT_REVIEW_REPLAY marker.",
                "kind": "architecture_decision",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": "review-2"}],
            },
            headers=headers,
        )
        suggestion_id = created.json()["data"]["id"]
        original_commit = PostgresUnitOfWork.commit
        raised = False

        async def raise_after_committed(self):
            nonlocal raised
            await original_commit(self)
            if not raised:
                raised = True
                raise RuntimeError("commit outcome unknown")

        with monkeypatch.context() as scoped:
            scoped.setattr(PostgresUnitOfWork, "commit", raise_after_committed)
            with pytest.raises(RuntimeError, match="commit outcome unknown"):
                client.post(
                    f"/v1/suggestions/{suggestion_id}/approve",
                    json={"reason": "confirmed"},
                    headers=headers,
                )

        replay = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": "confirmed"},
            headers=headers,
        )
        repeated_replay = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": "confirmed"},
            headers=headers,
        )
        mismatched_retry = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": "different request"},
            headers=headers,
        )

    assert replay.status_code == 200
    assert repeated_replay.status_code == 200
    assert replay.json() == repeated_replay.json()
    assert replay.json()["data"]["suggestion"]["status"] == "approved"
    assert replay.json()["data"]["fact"]["text"] == "EXACT_REVIEW_REPLAY marker."
    assert mismatched_retry.status_code == 409

    with sqlite3.connect(database_path) as connection:
        fact_count = connection.execute(
            "SELECT COUNT(*) FROM memory_facts WHERE text = ?",
            ("EXACT_REVIEW_REPLAY marker.",),
        ).fetchone()
        outbox_count = connection.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE aggregate_type = 'fact'"
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM suggestion_resolution_receipts WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()

    assert fact_count == (1,)
    assert outbox_count == (1,)
    assert receipt_count == (1,)


@pytest.mark.parametrize(
    ("action", "expected_status"),
    (("reject", "rejected"), ("expire", "expired")),
)
def test_terminal_review_replays_exact_result_after_unknown_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_status: str,
) -> None:
    database_path = tmp_path / "memory.db"
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": f"{action}-unknown-commit-1",
    }
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "candidate_text": f"EXACT_{action.upper()}_REPLAY marker.",
                "kind": "architecture_decision",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": f"review-{action}"}],
            },
            headers=headers,
        )
        suggestion_id = created.json()["data"]["id"]
        original_commit = PostgresUnitOfWork.commit
        raised = False

        async def raise_after_committed(self):
            nonlocal raised
            await original_commit(self)
            if not raised:
                raised = True
                raise RuntimeError("commit outcome unknown")

        with monkeypatch.context() as scoped:
            scoped.setattr(PostgresUnitOfWork, "commit", raise_after_committed)
            with pytest.raises(RuntimeError, match="commit outcome unknown"):
                client.post(
                    f"/v1/suggestions/{suggestion_id}/{action}",
                    json={"reason": "reviewed"},
                    headers=headers,
                )

        replay = client.post(
            f"/v1/suggestions/{suggestion_id}/{action}",
            json={"reason": "reviewed"},
            headers=headers,
        )
        repeated_replay = client.post(
            f"/v1/suggestions/{suggestion_id}/{action}",
            json={"reason": "reviewed"},
            headers=headers,
        )
        mismatched_retry = client.post(
            f"/v1/suggestions/{suggestion_id}/{action}",
            json={"reason": "different request"},
            headers=headers,
        )

    assert replay.status_code == 200
    assert repeated_replay.status_code == 200
    assert replay.json() == repeated_replay.json()
    assert replay.json()["data"]["status"] == expected_status
    assert replay.json()["data"]["review_audit"]["event_count"] == 1
    assert mismatched_retry.status_code == 409

    with sqlite3.connect(database_path) as connection:
        receipt_count = connection.execute(
            """
            SELECT COUNT(*) FROM suggestion_resolution_receipts
            WHERE suggestion_id = ? AND operation = ?
            """,
            (suggestion_id, action),
        ).fetchone()

    assert receipt_count == (1,)


@pytest.mark.parametrize(
    ("action", "json_column", "json_path", "replacement", "error"),
    (
        (
            "approve",
            "result_fact_json",
            "$.identity.fact_id",
            "fact-corrupt",
            "fact snapshot identity mismatch",
        ),
        (
            "reject",
            "result_suggestion_json",
            "$.id",
            "suggestion-corrupt",
            "must match its suggestion",
        ),
    ),
)
def test_suggestion_replay_fails_closed_on_snapshot_identity_drift(
    tmp_path: Path,
    action: str,
    json_column: str,
    json_path: str,
    replacement: str,
    error: str,
) -> None:
    database_path = tmp_path / "memory.db"
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": f"{action}-corrupt-receipt-1",
    }
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "candidate_text": f"CORRUPT_{action.upper()}_RECEIPT marker.",
                "kind": "architecture_decision",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": "review-corrupt"}],
            },
            headers=headers,
        )
        suggestion_id = created.json()["data"]["id"]
        first = client.post(
            f"/v1/suggestions/{suggestion_id}/{action}",
            json={"reason": "reviewed"},
            headers=headers,
        )
        assert first.status_code == 200

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                f"""
                UPDATE suggestion_resolution_receipts
                SET {json_column} = json_set({json_column}, ?, ?)
                WHERE suggestion_id = ? AND operation = ?
                """,  # noqa: S608 - column names are test-controlled parameters
                (json_path, replacement, suggestion_id, action),
            )
            connection.commit()

        with pytest.raises(ValueError, match=error):
            client.post(
                f"/v1/suggestions/{suggestion_id}/{action}",
                json={"reason": "reviewed"},
                headers=headers,
            )
