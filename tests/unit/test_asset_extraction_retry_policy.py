import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import MemoryOutboxRow
from memo_stack_core.application.use_cases.asset_extraction_support import (
    ExtractionRetryPolicy,
)
from memo_stack_core.domain.extraction import ExtractionRetryDisposition
from memo_stack_core.ports.extraction import ExtractionResult
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.main import create_app
from memo_stack_server.worker import OutboxWorker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def make_client(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            capture_mode=CaptureMode.SUGGEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-token"}
    if extra:
        headers.update(extra)
    return headers


async def _mark_asset_extraction_failed(
    client: TestClient,
    extraction_id: str,
    *,
    retry_after_offset: timedelta,
):
    container = client.app.state.container
    now = container.clock.now()
    async with container.uow_factory() as uow:
        job = await uow.asset_extractions.get_by_id(extraction_id)
        assert job is not None
        running = job.mark_running(
            now=now,
            lease_owner="outbox:failed",
            lease_expires_at=now + timedelta(minutes=15),
        )
        failed = running.mark_failed(
            now=now + timedelta(seconds=1),
            code="asset_extraction.provider_timeout",
            message="provider retry should wait for retry_after_at",
            retry_disposition=ExtractionRetryDisposition.RETRYABLE,
            retry_after_at=now + retry_after_offset,
        )
        saved = await uow.asset_extractions.save(failed)
        await uow.commit()
        return saved


async def _asset_extract_outbox_state(
    client: TestClient,
) -> tuple[str, int, datetime, str | None]:
    async with AsyncSession(client.app.state.container.engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow).where(MemoryOutboxRow.event_type == "asset.extract")
            )
        ).scalar_one()
        return (
            row.status,
            row.attempt_count,
            row.next_attempt_at,
            row.last_safe_diagnostic_code,
        )


class _TransientFailureExtractor:
    async def extract(self, request: Any) -> ExtractionResult:
        return ExtractionResult(
            status="failed",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            safe_error_code="asset_extraction.provider_timeout",
            safe_error_message="Provider timed out",
            technical_metadata={"provider": "test"},
            parser_name="transient_failure_test",
            parser_version="v1",
        )


def _upload_text_asset(client: TestClient, *, filename: str) -> str:
    upload = client.post(
        "/v1/assets",
        params={
            "space_slug": "quick-capture",
            "memory_scope_external_ref": "frontend",
            "thread_external_ref": "alex-call",
            "filename": filename,
            "extract": "true",
        },
        content=b"Provider retry policy should be safe for production ingestion.",
        headers=auth_headers({"Content-Type": "text/plain"}),
    )
    assert upload.status_code == 201, upload.text
    return upload.json()["data"]["extraction"]["id"]


def test_failed_asset_extraction_retry_after_defers_worker_without_burning_attempt(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        extraction_id = _upload_text_asset(client, filename="retry-after.txt")
        failed = asyncio.run(
            _mark_asset_extraction_failed(
                client,
                extraction_id,
                retry_after_offset=timedelta(minutes=5),
            )
        )

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        outbox_status, outbox_attempt_count, outbox_next_attempt_at, outbox_diagnostic = (
            asyncio.run(_asset_extract_outbox_state(client))
        )
        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extraction = fetched.json()["data"]

    assert processed == 1
    assert outbox_status == "retry_pending"
    assert outbox_attempt_count == 0
    assert outbox_diagnostic == "asset_extraction.retry_not_ready"
    assert failed.retry_after_at is not None
    assert outbox_next_attempt_at.replace(tzinfo=None) == failed.retry_after_at.replace(
        tzinfo=None
    )
    assert extraction["status"] == "failed"
    assert extraction["attempt_count"] == 1
    assert extraction["execution"]["retry_disposition"] == "retryable"
    assert extraction["execution"]["retry_after_at"] is not None
    assert extraction["result_document_ids"] == []
    assert extraction["artifacts"] == []


def test_retryable_asset_extraction_failure_becomes_permanent_after_attempt_budget(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        extraction_id = _upload_text_asset(client, filename="retry-exhausted.txt")
        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        original_retry_policy = run_use_case._retry_policy
        run_use_case._extractor = _TransientFailureExtractor()
        run_use_case._retry_policy = ExtractionRetryPolicy(max_attempts=1)
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._extractor = original_extractor
            run_use_case._retry_policy = original_retry_policy
        outbox_status, outbox_attempt_count, _, outbox_diagnostic = asyncio.run(
            _asset_extract_outbox_state(client)
        )
        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]

    assert processed == 1
    assert outbox_status == "done"
    assert outbox_attempt_count == 0
    assert outbox_diagnostic is None
    assert extracted["status"] == "failed"
    assert extracted["safe_error_code"] == "asset_extraction.provider_timeout"
    assert extracted["execution"]["retry_disposition"] == "permanent"
    assert extracted["execution"]["retry_after_at"] is None
    assert extracted["metadata"]["retry_exhausted"] is True
    assert extracted["metadata"]["retry_max_attempts"] == 1
    assert extracted["attempt_count"] == 1
    assert extracted["result_document_ids"] == []
    assert extracted["artifacts"] == []
