import asyncio
import json
import shutil
import subprocess
import threading
import wave
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.extraction.openai_vision import OpenAIVisionImageExtractionEngine
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.application.dto import (
    CancelAssetExtractionCommand,
    RunAssetExtractionCommand,
)
from infinity_context_core.application.use_cases.asset_extraction_support import (
    ActiveAssetExtractionLeaseError,
)
from infinity_context_core.domain.assets import MemoryAssetId
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId
from infinity_context_core.domain.errors import (
    MemoryIngressLimitError,
    MemoryQuotaExceededError,
    MemoryValidationError,
)
from infinity_context_core.domain.extraction import AssetExtractionJob, AssetExtractionJobId
from infinity_context_core.ports.extraction import (
    ExtractedElement,
    ExtractionArtifactCandidate,
    ExtractionResult,
)
from infinity_context_server.admin import token_create
from infinity_context_server.api.v1.assets import (
    _read_limited_request_body,
    asset_extraction_to_response,
)
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.db import upgrade
from infinity_context_server.main import create_app
from infinity_context_server.worker import OutboxWorker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_VISION_PROVIDER_SECRET = "sk-proj-vision-secret-value1234567890"


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


class StreamingRequestStub:
    def __init__(self, chunks: list[bytes], *, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.chunks = chunks
        self.chunks_read = 0

    async def stream(self):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk


def test_asset_upload_body_reader_rejects_large_content_length_without_streaming() -> None:
    request = StreamingRequestStub(
        [b"body-should-not-be-read"],
        headers={"content-length": "10"},
    )

    with pytest.raises(MemoryIngressLimitError, match="upload limit"):
        asyncio.run(_read_limited_request_body(request, max_bytes=4))

    assert request.chunks_read == 0


def test_asset_upload_body_reader_rejects_invalid_content_length() -> None:
    request = StreamingRequestStub([b"hello"], headers={"content-length": "invalid"})

    with pytest.raises(MemoryValidationError, match="Invalid Content-Length"):
        asyncio.run(_read_limited_request_body(request, max_bytes=10))

    assert request.chunks_read == 0


def test_asset_upload_body_reader_rejects_chunked_overflow_while_streaming() -> None:
    request = StreamingRequestStub([b"12", b"345", b"should-not-be-read"])

    with pytest.raises(MemoryIngressLimitError, match="upload limit"):
        asyncio.run(_read_limited_request_body(request, max_bytes=4))

    assert request.chunks_read == 2


async def _mark_asset_extraction_running(
    client: TestClient,
    extraction_id: str,
    *,
    started_offset: timedelta = timedelta(),
    lease_offset: timedelta = timedelta(minutes=15),
    lease_owner: str = "outbox:active",
):
    container = client.app.state.container
    now = container.clock.now()
    async with container.uow_factory() as uow:
        job = await uow.asset_extractions.get_by_id(extraction_id)
        assert job is not None
        running = job.mark_running(
            now=now + started_offset,
            lease_owner=lease_owner,
            lease_expires_at=now + lease_offset,
        )
        saved = await uow.asset_extractions.save(running)
        await uow.commit()
        return saved


async def _get_asset_extract_outbox_row(client: TestClient, extraction_id: str) -> MemoryOutboxRow:
    async with AsyncSession(client.app.state.container.engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow)
                .where(MemoryOutboxRow.event_type == "asset.extract")
                .where(MemoryOutboxRow.aggregate_id == extraction_id)
                .order_by(MemoryOutboxRow.id.desc())
                .limit(1)
            )
        ).scalar_one()
        return row


def sample_pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        + f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
        + stream
        + b"\nendstream endobj\nxref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"0000000241 00000 n \n0000000311 00000 n \n"
        b"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n449\n%%EOF\n"
    )


def sample_png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (120, 40), color=(255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def sample_wav_bytes(seconds: int = 1) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000 * seconds)
    return buffer.getvalue()


class _FailingVisionResponses:
    async def create(self, **kwargs: Any) -> object:
        raise RuntimeError("simulated vision provider outage")


class _SuccessfulVisionResponse:
    output_text = json.dumps(
        {
            "summary": "Quick capture links this screenshot to MemoryScope frontend.",
            "visible_text": ["Save to MemoryScope", "Review links"],
            "screenshot_ui_summary": "A memory review panel is open.",
            "suggested_tags": ["memory", "frontend"],
            "regions": [
                {
                    "kind": "visible_text",
                    "text": "Save to MemoryScope",
                    "bbox": [12, 4, 118, 36],
                    "confidence": 0.94,
                }
            ],
            "raw_provider_payload": {
                "api_key": _VISION_PROVIDER_SECRET,
                "debug": f"Bearer {_VISION_PROVIDER_SECRET}",
            },
        }
    )


class _SuccessfulVisionResponses:
    async def create(self, **kwargs: Any) -> object:
        assert kwargs["model"] == "gpt-4.1-mini"
        assert kwargs["store"] is False
        assert kwargs["text"]["format"]["strict"] is True
        content = kwargs["input"][0]["content"]
        assert "untrusted evidence" in content[0]["text"]
        assert content[1]["detail"] == "low"
        assert content[1]["image_url"].startswith("data:image/png;base64,")
        return _SuccessfulVisionResponse()


class _SuccessfulVisionClient:
    responses = _SuccessfulVisionResponses()

    async def aclose(self) -> None:
        return None


class _FailingVisionClient:
    responses = _FailingVisionResponses()

    async def aclose(self) -> None:
        return None


class _CancelAfterIngestDocument:
    def __init__(self, *, inner: Any, cancel_use_case: Any, job_id: str) -> None:
        self._inner = inner
        self._cancel_use_case = cancel_use_case
        self._job_id = job_id

    async def execute(self, command: Any) -> Any:
        result = await self._inner.execute(command)
        await self._cancel_use_case.execute(CancelAssetExtractionCommand(job_id=self._job_id))
        return result


class _FailingArtifactBlobStorage:
    def __init__(
        self,
        *,
        inner: Any,
        fail_on_artifact_write: int = 2,
        failure_message: str = "simulated artifact storage outage",
    ) -> None:
        self._inner = inner
        self._fail_on_artifact_write = fail_on_artifact_write
        self._failure_message = failure_message
        self._artifact_write_count = 0

    async def write_bytes(self, *, storage_key: str, content: bytes) -> Any:
        if "/extractions/" in storage_key:
            self._artifact_write_count += 1
            if self._artifact_write_count >= self._fail_on_artifact_write:
                raise RuntimeError(self._failure_message)
        return await self._inner.write_bytes(storage_key=storage_key, content=content)

    async def read_bytes(self, *, storage_key: str) -> bytes:
        return await self._inner.read_bytes(storage_key=storage_key)

    async def delete(self, *, storage_key: str) -> None:
        await self._inner.delete(storage_key=storage_key)


class _QuotaFailureExtractionRequest:
    async def execute(self, command: Any) -> Any:
        raise MemoryQuotaExceededError(
            "quota blocked by provider token sk-proj-secretvalue1234567890"
        )


class _PermanentFailureExtractor:
    async def extract(self, request: Any) -> ExtractionResult:
        return ExtractionResult(
            status="failed",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            safe_error_code="asset_extraction.missing_api_key",
            safe_error_message="External AI key is not configured",
            technical_metadata={"provider": "test"},
            parser_name="permanent_failure_test",
            parser_version="v1",
        )


class _SlowCancelableExtractor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def extract(self, request: Any) -> ExtractionResult:
        self.started.set()
        try:
            while True:
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _OversizedArtifactExtractor:
    async def extract(self, request: Any) -> ExtractionResult:
        raw_secret = "sk-proj-oversized-artifact-secret-value"
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            markdown="Oversized provider artifact should be bounded.",
            elements=(
                ExtractedElement(
                    kind="text",
                    text="Oversized provider artifact should be bounded.",
                    metadata={"source": "oversized_artifact_test"},
                ),
            ),
            artifacts=(
                ExtractionArtifactCandidate(
                    artifact_type="normalized_json",
                    filename="provider-large.json",
                    content_type="application/json",
                    content=(
                        f'{{"secret":"{raw_secret}","payload":"' + ("x" * 20_000) + '"}'
                    ).encode("utf-8"),
                    metadata={
                        "provider": "oversized_artifact_test",
                        "debug": f"Bearer {raw_secret}",
                        "api_key": raw_secret,
                    },
                ),
            ),
            parser_name="oversized_artifact_test",
            parser_version="v1",
        )


def test_asset_extraction_response_redacts_sensitive_diagnostic_strings() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    job = (
        AssetExtractionJob.create(
            job_id=AssetExtractionJobId("extract_1"),
            asset_id=MemoryAssetId("asset_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            parser_profile="standard_local",
            parser_config_hash="hash",
            source_sha256_hex="a" * 64,
            now=now,
        )
        .mark_failed(
            now=now,
            code="asset_extraction.provider_failed",
            message=f"provider failed with {raw_secret}",
        )
        .with_metadata_updates(
            now=now,
            metadata={
                "processing_stage": f"provider {raw_secret}",
                "progress_message": f"provider token {raw_secret}",
                "debug_message": f"Bearer {raw_secret}",
                "attempt": 1,
            },
        )
    )

    response = asset_extraction_to_response(job)
    rendered = json.dumps(response, sort_keys=True)

    assert raw_secret not in rendered
    assert "[redacted]" in response["safe_error_message"]
    assert "[redacted]" in response["metadata"]["debug_message"]
    assert "[redacted]" in response["progress"]["stage"]
    assert "[redacted]" in response["progress"]["message"]
    assert response["metadata"]["attempt"] == 1


def sample_mp4_bytes(tmp_path: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")
    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return video_path.read_bytes()


def test_text_asset_extraction_indexes_document_chunks_and_artifacts(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "alex-call-note.txt",
                "extract": "true",
            },
            content=(
                b"Alex call: keep quick capture attached to memory scopes, "
                b"threads, assets, and extracted evidence."
            ),
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        uploaded = upload.json()["data"]
        extraction = uploaded["extraction"]
        assert extraction["status"] == "pending"
        assert extraction["attempt_count"] == 0
        assert extraction["progress"] == {
            "stage": "queued",
            "percent": 0,
            "message": "Waiting for extraction worker",
            "terminal": False,
        }

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction['id']}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["attempt_count"] == 1
        assert extracted["parser_name"] == "simple_text"
        assert extracted["progress"]["stage"] == "succeeded"
        assert extracted["progress"]["percent"] == 100
        assert extracted["progress"]["terminal"] is True
        assert extracted["metadata"]["normalized_content_type"] == "text/plain"
        assert len(extracted["result_document_ids"]) == 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
        }
        markdown_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "markdown"
        )
        assert markdown_artifact["metadata"]["filename"] == "extracted.md"

        document_id = extracted["result_document_ids"][0]
        chunks = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_items = chunks.json()["data"]
        assert len(chunk_items) == 1
        assert "quick capture attached to memory scopes" in chunk_items[0]["text"]
        assert chunk_items[0]["classification"] == "unknown"
        assert chunk_items[0]["metadata"]["source_kind"] == "asset_extraction"
        assert chunk_items[0]["metadata"]["asset_id"] == uploaded["id"]
        assert chunk_items[0]["metadata"]["extraction_job_id"] == extraction["id"]
        assert chunk_items[0]["metadata"]["parser_name"] == "simple_text"
        assert chunk_items[0]["source_refs"][0]["source_type"] == "asset_extraction"
        assert chunk_items[0]["source_refs"][0]["source_id"] == extraction["id"]
        assert chunk_items[0]["source_refs"][0]["asset_id"] == uploaded["id"]
        assert chunk_items[0]["source_refs"][0]["kind"] == "text"
        assert chunk_items[0]["source_refs"][0]["provider_source"] == "simple_text"

        listed = client.get(
            f"/v1/assets/{uploaded['id']}/extractions",
            headers=auth_headers(),
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"][0]["id"] == extraction["id"]
        scope_listed = client.get(
            "/v1/asset-extractions",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
            },
            headers=auth_headers(),
        )
        assert scope_listed.status_code == 200, scope_listed.text
        assert scope_listed.json()["data"][0]["id"] == extraction["id"]
        downloaded = client.get(
            f"/v1/extraction-artifacts/{markdown_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["content-type"].startswith("text/markdown")
        assert "extracted.md" in downloaded.headers["content-disposition"]
        assert downloaded.headers["x-content-type-options"] == "nosniff"
        assert b"quick capture attached to memory scopes" in downloaded.content


def test_delete_asset_removes_source_and_extraction_artifact_blobs(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "cleanup",
                "filename": "cleanup-note.txt",
                "extract": "true",
            },
            content=b"Deleting an asset should remove extraction artifact blobs too.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        uploaded = upload.json()["data"]
        extraction_id = uploaded["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        artifact_id = next(
            item["id"]
            for item in fetched.json()["data"]["artifacts"]
            if item["artifact_type"] == "markdown"
        )
        artifact_before_delete = client.get(
            f"/v1/extraction-artifacts/{artifact_id}/download",
            headers=auth_headers(),
        )
        assert artifact_before_delete.status_code == 200, artifact_before_delete.text
        asset_before_delete = client.get(
            f"/v1/assets/{uploaded['id']}/download",
            headers=auth_headers(),
        )
        assert asset_before_delete.status_code == 200, asset_before_delete.text

        deleted = client.delete(f"/v1/assets/{uploaded['id']}", headers=auth_headers())
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["status"] == "deleted"

        asset_after_delete = client.get(
            f"/v1/assets/{uploaded['id']}/download",
            headers=auth_headers(),
        )
        assert asset_after_delete.status_code == 404, asset_after_delete.text
        artifact_after_delete = client.get(
            f"/v1/extraction-artifacts/{artifact_id}/download",
            headers=auth_headers(),
        )
        assert artifact_after_delete.status_code == 404, artifact_after_delete.text


def test_spoofed_image_mime_text_asset_extracts_as_text_with_mismatch_metadata(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "mime-mismatch",
                "filename": "not-really-a-screenshot.png",
                "extract": "true",
            },
            content=b"Plain text capture mislabeled as image/png must remain evidence.",
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert upload.status_code == 201, upload.text
        uploaded = upload.json()["data"]
        extraction = uploaded["extraction"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction['id']}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "simple_text"
        assert extracted["metadata"]["normalized_content_type"] == "text/plain"
        assert extracted["metadata"]["detected_content_type"] == "text/plain"
        assert extracted["metadata"]["mime_declared_content_type"] == "image/png"
        assert extracted["metadata"]["mime_extension_content_type"] == "image/png"
        assert extracted["metadata"]["mime_magic_content_type"] == "text/plain"
        assert extracted["metadata"]["mime_content_type_mismatch"] is True
        assert extracted["metadata"]["mime_extension_mismatch"] is True
        assert extracted["metadata"]["mime_detector_reason"] == "magic"


def test_asset_extraction_size_limit_keeps_source_asset_downloadable(tmp_path: Path) -> None:
    with make_client(tmp_path, max_asset_upload_bytes=100, extraction_max_bytes=4) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "oversized-for-extraction.txt",
                "extract": "true",
            },
            content=b"12345",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        uploaded = upload.json()["data"]
        extraction = uploaded["extraction"]
        assert extraction["status"] == "pending"

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction['id']}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "unsupported"
        assert extracted["safe_error_code"] == "asset_extraction.file_too_large"
        assert extracted["safe_error_message"] == "Asset exceeds configured extraction size limit"

        download = client.get(
            f"/v1/assets/{uploaded['id']}/download",
            headers=auth_headers(),
        )
        assert download.status_code == 200, download.text
        assert download.content == b"12345"


def test_pending_asset_extraction_can_be_canceled_before_worker(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "cancel-me.txt",
                "extract": "true",
            },
            content=b"This extraction should be canceled before the worker reads it.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        canceled = client.post(
            f"/v1/asset-extractions/{extraction_id}/cancel",
            headers=auth_headers(),
        )
        assert canceled.status_code == 202, canceled.text
        canceled_data = canceled.json()["data"]
        assert canceled_data["status"] == "canceled"
        assert canceled_data["safe_error_code"] == "asset_extraction.canceled"
        assert canceled_data["progress"]["terminal"] is True
        assert canceled_data["execution"]["cancellation_requested_at"] is not None
        assert canceled_data["execution"]["available_actions"] == ["retry"]
        assert canceled_data["execution"]["retry_actionable"] is True
        assert canceled_data["execution"]["cancel_actionable"] is False
        assert canceled_data["execution"]["retry_state_reason"] == "canceled_manual_retry_available"
        assert canceled_data["execution"]["cancel_state_reason"] == "terminal_job"

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "canceled"
        assert extracted["result_document_ids"] == []
        assert extracted["artifacts"] == []


def test_canceled_asset_extraction_retry_resets_progress(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "retry-canceled.txt",
                "extract": "true",
            },
            content=b"This extraction is canceled first, then queued again.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        canceled = client.post(
            f"/v1/asset-extractions/{extraction_id}/cancel",
            headers=auth_headers(),
        )
        assert canceled.status_code == 202, canceled.text
        assert canceled.json()["data"]["progress"]["stage"] == "canceled"

        retry = client.post(
            f"/v1/asset-extractions/{extraction_id}/retry",
            headers=auth_headers(),
        )
        assert retry.status_code == 202, retry.text
        retried = retry.json()["data"]
        assert retried["status"] == "pending"
        assert retried["safe_error_code"] is None
        assert retried["progress"] == {
            "stage": "queued",
            "percent": 0,
            "message": "Waiting for extraction worker",
            "terminal": False,
        }
        assert retried["execution"]["cancellation_requested_at"] is None
        assert retried["execution"]["retry_disposition"] is None
        assert retried["execution"]["available_actions"] == ["cancel"]
        assert retried["execution"]["retry_actionable"] is False
        assert retried["execution"]["cancel_actionable"] is True
        assert retried["execution"]["retry_state_reason"] == "job_not_terminal"
        assert retried["execution"]["cancel_state_reason"] == "pending_cancel_available"


def test_active_asset_extraction_lease_blocks_duplicate_worker_run(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "active-lease.txt",
                "extract": "true",
            },
            content=b"Only one worker should extract this active asset at a time.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        running = asyncio.run(
            _mark_asset_extraction_running(
                client,
                extraction_id,
                lease_offset=timedelta(minutes=15),
            )
        )

        with pytest.raises(ActiveAssetExtractionLeaseError) as exc_info:
            asyncio.run(
                client.app.state.container.run_asset_extraction.execute(
                    RunAssetExtractionCommand(
                        job_id=extraction_id,
                        force=True,
                        worker_id="outbox:duplicate",
                    )
                )
            )

        assert exc_info.value.retry_after_at == running.lease_expires_at.replace(tzinfo=None)
        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extraction = fetched.json()["data"]
        assert extraction["status"] == "running"
        assert extraction["attempt_count"] == 1
        assert extraction["execution"]["lease_owner"] == "outbox:active"
        assert extraction["execution"]["lease_state"] == "active"
        assert extraction["execution"]["lease_seconds_remaining"] > 0
        assert extraction["execution"]["reclaimable"] is False
        assert extraction["result_document_ids"] == []
        assert extraction["artifacts"] == []


def test_expired_asset_extraction_lease_can_be_reclaimed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "expired-lease.txt",
                "extract": "true",
            },
            content=b"Expired extraction leases should be safely reclaimed by a worker.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        asyncio.run(
            _mark_asset_extraction_running(
                client,
                extraction_id,
                started_offset=-timedelta(minutes=20),
                lease_offset=-timedelta(minutes=5),
            )
        )

        stale = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert stale.status_code == 200, stale.text
        stale_execution = stale.json()["data"]["execution"]
        assert stale_execution["lease_state"] == "expired"
        assert stale_execution["lease_seconds_remaining"] == 0
        assert stale_execution["reclaimable"] is True

        result = asyncio.run(
            client.app.state.container.run_asset_extraction.execute(
                RunAssetExtractionCommand(
                    job_id=extraction_id,
                    worker_id="outbox:reclaimer",
                )
            )
        )

        assert result.job.status.value == "succeeded"
        assert result.job.attempt_count == 2
        assert result.job.lease_owner is None
        assert len(result.job.result_document_ids) == 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        execution = fetched.json()["data"]["execution"]
        assert execution["lease_state"] == "none"
        assert execution["lease_seconds_remaining"] is None
        assert execution["reclaimable"] is False


def test_cancel_requested_running_asset_extraction_is_honored(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "running-cancel.txt",
                "extract": "true",
            },
            content=b"Running extraction should honor cancellation before restarting work.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        asyncio.run(
            _mark_asset_extraction_running(
                client,
                extraction_id,
                lease_offset=timedelta(minutes=15),
            )
        )
        canceled = client.post(
            f"/v1/asset-extractions/{extraction_id}/cancel",
            headers=auth_headers(),
        )
        assert canceled.status_code == 202, canceled.text
        assert canceled.json()["data"]["status"] == "running"
        assert canceled.json()["data"]["execution"]["cancellation_requested_at"] is not None

        result = asyncio.run(
            client.app.state.container.run_asset_extraction.execute(
                RunAssetExtractionCommand(
                    job_id=extraction_id,
                    force=True,
                    worker_id="outbox:cancel-ack",
                )
            )
        )

        assert result.job.status.value == "canceled"
        assert result.job.attempt_count == 1
        assert result.job.result_document_ids == ()


def test_cancel_during_slow_asset_extraction_interrupts_worker_without_artifacts(
    tmp_path: Path,
) -> None:
    with make_client(
        tmp_path,
        extraction_cancellation_poll_seconds=0.05,
        extraction_heartbeat_seconds=0.05,
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "slow-cancel",
                "filename": "slow-cancel.txt",
                "extract": "true",
            },
            content=b"Slow extraction should be cancelable while parser work is still running.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        slow_extractor = _SlowCancelableExtractor()
        run_use_case._extractor = slow_extractor
        worker_error: list[BaseException] = []
        worker_processed: list[int] = []

        def run_worker() -> None:
            try:
                processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
            except BaseException as exc:  # pragma: no cover - asserted through worker_error
                worker_error.append(exc)
            else:
                worker_processed.append(processed)

        worker_thread = threading.Thread(target=run_worker, daemon=True)
        try:
            worker_thread.start()
            assert slow_extractor.started.wait(timeout=3)

            running = client.get(
                f"/v1/asset-extractions/{extraction_id}",
                headers=auth_headers(),
            )
            assert running.status_code == 200, running.text
            running_data = running.json()["data"]
            assert running_data["status"] == "running"
            assert running_data["progress"]["stage"] == "extracting_content"
            assert running_data["execution"]["lease_state"] == "active"
            assert running_data["execution"]["heartbeat_at"] is not None

            canceled = client.post(
                f"/v1/asset-extractions/{extraction_id}/cancel",
                headers=auth_headers(),
            )
            assert canceled.status_code == 202, canceled.text
            assert canceled.json()["data"]["status"] == "running"
            assert canceled.json()["data"]["execution"]["cancellation_requested_at"] is not None

            worker_thread.join(timeout=5)
            assert not worker_thread.is_alive()
            assert worker_error == []
            assert worker_processed == [1]
            assert slow_extractor.cancelled.wait(timeout=1)

            extracted = client.get(
                f"/v1/asset-extractions/{extraction_id}",
                headers=auth_headers(),
            )
            assert extracted.status_code == 200, extracted.text
            data = extracted.json()["data"]
            assert data["status"] == "canceled"
            assert data["safe_error_code"] == "asset_extraction.canceled"
            assert data["progress"]["terminal"] is True
            assert data["execution"]["lease_state"] == "none"
            assert data["execution"]["cancellation_requested_at"] is not None
            assert data["result_document_ids"] == []
            assert data["artifacts"] == []
        finally:
            run_use_case._extractor = original_extractor


def test_slow_asset_extraction_refreshes_outbox_running_heartbeat(
    tmp_path: Path,
) -> None:
    with make_client(
        tmp_path,
        extraction_cancellation_poll_seconds=0.05,
        extraction_heartbeat_seconds=0.05,
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "outbox-heartbeat",
                "filename": "outbox-heartbeat.txt",
                "extract": "true",
            },
            content=b"Outbox running heartbeat should stay fresh during slow extraction.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        slow_extractor = _SlowCancelableExtractor()
        run_use_case._extractor = slow_extractor
        worker_error: list[BaseException] = []

        def run_worker() -> None:
            try:
                asyncio.run(
                    OutboxWorker(
                        client.app.state.container,
                        running_heartbeat_interval=timedelta(seconds=0.05),
                    ).run_once(limit=10)
                )
            except BaseException as exc:  # pragma: no cover - asserted through worker_error
                worker_error.append(exc)

        worker_thread = threading.Thread(target=run_worker, daemon=True)
        try:
            worker_thread.start()
            assert slow_extractor.started.wait(timeout=3)
            initial_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
            assert initial_row.status == "running"

            assert not slow_extractor.cancelled.wait(timeout=0.2)
            refreshed_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
            assert refreshed_row.status == "running"
            assert refreshed_row.updated_at > initial_row.updated_at

            canceled = client.post(
                f"/v1/asset-extractions/{extraction_id}/cancel",
                headers=auth_headers(),
            )
            assert canceled.status_code == 202, canceled.text
            worker_thread.join(timeout=5)
            assert not worker_thread.is_alive()
            assert worker_error == []
            assert slow_extractor.cancelled.wait(timeout=1)

            done_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
            assert done_row.status == "done"
        finally:
            run_use_case._extractor = original_extractor


def test_slow_asset_extraction_parser_timeout_marks_retryable_without_artifacts(
    tmp_path: Path,
) -> None:
    with make_client(
        tmp_path,
        extraction_cancellation_poll_seconds=0.05,
        extraction_heartbeat_seconds=0.05,
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "timeout",
                "filename": "timeout-note.txt",
                "extract": "true",
            },
            content=b"Parser timeout should fail retryably without half-committed evidence.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        original_limits = run_use_case._limits
        slow_extractor = _SlowCancelableExtractor()
        run_use_case._extractor = slow_extractor
        run_use_case._limits = replace(original_limits, parser_timeout_seconds=0.1)
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._extractor = original_extractor
            run_use_case._limits = original_limits

        assert processed == 1
        assert slow_extractor.started.is_set()
        assert slow_extractor.cancelled.wait(timeout=1)

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        data = fetched.json()["data"]
        assert data["status"] == "failed"
        assert data["safe_error_code"] == "asset_extraction.parser_timeout"
        assert data["safe_error_message"] == "Asset extraction parser timed out after 0.1s"
        assert data["execution"]["retry_disposition"] == "retryable"
        assert data["execution"]["retry_after_at"] is not None
        assert data["execution"]["available_actions"] == ["retry"]
        assert data["execution"]["retry_actionable"] is True
        assert data["execution"]["cancel_actionable"] is False
        assert data["execution"]["retry_state_reason"] == "failed_retryable_backoff_active"
        assert data["execution"]["cancel_state_reason"] == "terminal_job"
        assert data["result_document_ids"] == []
        assert data["artifacts"] == []

        outbox_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
        assert outbox_row.status == "retry_pending"
        assert outbox_row.last_safe_error == "AssetExtractionParserTimeoutError"
        assert outbox_row.last_safe_diagnostic_code == "asset_extraction.parser_timeout"


def test_asset_extraction_ignores_cancel_after_document_commit(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "race-cancel.txt",
                "extract": "true",
            },
            content=(
                b"Canonical extraction evidence should not be canceled after the "
                b"document is already committed."
            ),
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_ingest_document = run_use_case._ingest_document
        run_use_case._ingest_document = _CancelAfterIngestDocument(
            inner=original_ingest_document,
            cancel_use_case=client.app.state.container.cancel_asset_extraction,
            job_id=extraction_id,
        )
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._ingest_document = original_ingest_document
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["safe_error_code"] is None
        assert extracted["metadata"]["cancellation_status"] == ("ignored_after_document_commit")
        assert extracted["execution"]["cancellation_requested_at"] is None
        assert len(extracted["result_document_ids"]) == 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
        }


def test_asset_extraction_records_cancel_after_artifact_storage(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "race-cancel-after-artifacts.txt",
                "extract": "true",
            },
            content=(
                b"Late cancellation after artifact storage should be recorded "
                b"without breaking committed evidence."
            ),
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_store_artifacts = run_use_case._store_artifacts

        async def store_artifacts_and_cancel(**kwargs: Any) -> Any:
            artifacts = await original_store_artifacts(**kwargs)
            await client.app.state.container.cancel_asset_extraction.execute(
                CancelAssetExtractionCommand(job_id=extraction_id)
            )
            return artifacts

        run_use_case._store_artifacts = store_artifacts_and_cancel
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._store_artifacts = original_store_artifacts
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["safe_error_code"] is None
        assert extracted["metadata"]["cancellation_status"] == "ignored_after_document_commit"
        assert extracted["execution"]["cancellation_requested_at"] is None
        assert len(extracted["result_document_ids"]) == 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
        }


def test_asset_extraction_marks_failed_and_cleans_blobs_on_artifact_storage_error(
    tmp_path: Path,
) -> None:
    asset_storage_dir = tmp_path / "assets"
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "artifact-failure.txt",
                "extract": "true",
            },
            content=b"Artifact storage failure should not leave extraction running.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_blob_storage = run_use_case._blob_storage
        run_use_case._blob_storage = _FailingArtifactBlobStorage(
            inner=original_blob_storage,
            fail_on_artifact_write=2,
        )
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._blob_storage = original_blob_storage
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "failed"
        assert extracted["safe_error_code"] == "asset_extraction.runtimeerror"
        assert extracted["safe_error_message"] == "simulated artifact storage outage"
        assert extracted["execution"]["retry_disposition"] == "retryable"
        assert extracted["execution"]["retry_after_at"] is not None
        assert extracted["artifacts"] == []

        extraction_files = [
            path for path in asset_storage_dir.glob("**/extractions/**/*") if path.is_file()
        ]
        assert extraction_files == []

        retry = client.post(
            f"/v1/asset-extractions/{extraction_id}/retry",
            headers=auth_headers(),
        )
        assert retry.status_code == 202, retry.text
        assert retry.json()["data"]["status"] == "pending"

        retried_count = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert retried_count >= 1

        retried_fetch = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert retried_fetch.status_code == 200, retried_fetch.text
        retried = retried_fetch.json()["data"]
        assert retried["status"] == "succeeded"
        assert retried["safe_error_code"] is None
        assert len(retried["result_document_ids"]) == 1
        assert {item["artifact_type"] for item in retried["artifacts"]} == {
            "extracted_json",
            "markdown",
        }

        browser = client.get(
            "/v1/memory-browser",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert browser.status_code == 200, browser.text
        browser_data = browser.json()["data"]
        matching_documents = [
            item
            for item in browser_data["documents"]
            if item["source_type"] == "asset_extraction"
            and item["source_external_id"] == extraction_id
        ]
        matching_chunks = [
            item
            for item in browser_data["chunks"]
            if item["source_type"] == "asset_extraction"
            and item["source_external_id"] == extraction_id
        ]
        assert len(matching_documents) == 1
        assert len(matching_chunks) == 1


def test_asset_extraction_truncates_oversized_provider_artifacts(tmp_path: Path) -> None:
    with make_client(tmp_path, extraction_max_output_chars=1000) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "oversized-artifact.txt",
                "extract": "true",
            },
            content=b"Provider artifact should be bounded even when extraction succeeds.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        run_use_case._extractor = _OversizedArtifactExtractor()
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._extractor = original_extractor

        assert processed == 1
        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "normalized_json"
        )
        assert artifact["byte_size"] < 2_000
        assert artifact["metadata"]["artifact_truncated"] is True
        assert artifact["metadata"]["artifact_original_byte_size"] > 20_000
        assert artifact["metadata"]["artifact_byte_limit"] == 16_384
        assert artifact["metadata"]["content_type"] == "application/json"
        assert artifact["metadata"]["filename"] == "provider-large.json.truncated.json"
        assert "api_key" not in artifact["metadata"]
        assert "sk-proj-oversized-artifact-secret-value" not in json.dumps(
            artifact["metadata"],
            ensure_ascii=False,
        )
        assert "[redacted]" in json.dumps(artifact["metadata"], ensure_ascii=False)

        downloaded = client.get(
            f"/v1/extraction-artifacts/{artifact['id']}/download",
            headers=auth_headers(),
        )
        assert downloaded.status_code == 200, downloaded.text
        payload = downloaded.json()
        assert payload["truncated"] is True
        assert payload["reason"] == "artifact_byte_limit"
        assert payload["byte_limit"] == 16_384
        assert "sk-proj-oversized-artifact-secret-value" not in downloaded.text
        assert "[redacted]" in downloaded.text


def test_permanent_asset_extraction_failure_completes_outbox_without_retry(
    tmp_path: Path,
) -> None:
    async def asset_outbox_state(client: TestClient) -> tuple[str, int, str | None, str | None]:
        async with AsyncSession(client.app.state.container.engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(MemoryOutboxRow.event_type == "asset.extract")
                )
            ).scalar_one()
            return (
                row.status,
                row.attempt_count,
                row.last_safe_error,
                row.last_safe_diagnostic_code,
            )

    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "permanent-failure.txt",
                "extract": "true",
            },
            content=b"Permanent extractor failure should not burn outbox retries.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_extractor = run_use_case._extractor
        run_use_case._extractor = _PermanentFailureExtractor()
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._extractor = original_extractor
        outbox_status, outbox_attempt_count, outbox_error, outbox_diagnostic = asyncio.run(
            asset_outbox_state(client)
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
    assert outbox_error is None
    assert outbox_diagnostic is None
    assert extracted["status"] == "failed"
    assert extracted["safe_error_code"] == "asset_extraction.missing_api_key"
    assert extracted["execution"]["retry_disposition"] == "permanent"
    assert extracted["execution"]["retry_after_at"] is None
    assert extracted["attempt_count"] == 1
    assert extracted["result_document_ids"] == []
    assert extracted["artifacts"] == []


def test_asset_extraction_redacts_secret_failure_messages(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "secret-failure.txt",
                "extract": "true",
            },
            content=b"Failure messages must not leak credentials.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        run_use_case = client.app.state.container.run_asset_extraction
        original_blob_storage = run_use_case._blob_storage
        run_use_case._blob_storage = _FailingArtifactBlobStorage(
            inner=original_blob_storage,
            fail_on_artifact_write=1,
            failure_message=(
                "Authorization: Bearer sk-proj-secret-failure-token-value "
                "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
            ),
        )
        try:
            processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        finally:
            run_use_case._blob_storage = original_blob_storage
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        rendered = fetched.text

        assert extracted["status"] == "failed"
        assert "sk-proj-secret-failure-token-value" not in rendered
        assert "PRIVATE KEY" not in rendered
        assert "[redacted]" in extracted["safe_error_message"]


def test_pdf_asset_extraction_indexes_pdf_text_and_artifacts(tmp_path: Path) -> None:
    marker = "PDF_MEMORY_SCOPE_DECISION"
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "architecture-note.pdf",
                "extract": "true",
            },
            content=sample_pdf_bytes(f"{marker} Alex call linked scope thread assets"),
            headers=auth_headers({"Content-Type": "application/pdf"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "pypdf_text"
        assert extracted["metadata"]["normalized_content_type"] == "application/pdf"
        assert extracted["metadata"]["page_count"] == 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
            "media_manifest",
        }
        manifest_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "media_manifest"
        )
        manifest_download = client.get(
            f"/v1/extraction-artifacts/{manifest_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert manifest_download.status_code == 200, manifest_download.text
        manifest = json.loads(manifest_download.content)
        assert manifest["schema_version"] == "infinity_context.multimodal_manifest.v1"
        assert manifest["modalities"] == ["text", "document"]
        assert manifest["evidence_items"][0]["page_number"] == 1

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_text = " ".join(item["text"] for item in chunks.json()["data"])
        assert marker in chunk_text
        assert "linked scope thread assets" in chunk_text
        source_refs = [ref for chunk in chunks.json()["data"] for ref in chunk["source_refs"]]
        assert source_refs
        assert source_refs[0]["page_number"] == 1
        assert source_refs[0]["kind"] == "page_text"
        context = client.post(
            "/v1/context",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "query": marker,
                "token_budget": 1200,
            },
            headers=auth_headers(),
        )
        assert context.status_code == 200, context.text
        context_data = context.json()["data"]
        context_refs = [
            ref for item in context_data["items"] for ref in item.get("source_refs", [])
        ]
        assert any(ref.get("page_number") == 1 for ref in context_refs)
        assert context_data["diagnostics"]["source_refs_with_page_count"] >= 1
        assert context_data["diagnostics"]["items_with_multimodal_source_refs"] >= 1

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "source_type": "asset",
                "source_id": upload.json()["data"]["id"],
                "text": f"{marker} linked scope thread assets",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        chunk_candidate = next(
            item
            for item in suggestions.json()["data"]["candidates"]
            if item["target_type"] == "chunk"
        )
        assert chunk_candidate["metadata"]["evidence_has_page_ref"] is True
        assert "document" in chunk_candidate["metadata"]["evidence_modalities"]
        assert chunk_candidate["metadata"]["evidence_refs"][0]["page_number"] == 1

        approved = client.post(
            f"/v1/context-link-suggestions/{chunk_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "page evidence verified"},
            headers=auth_headers(),
        )
        assert approved.status_code == 200, approved.text
        link_metadata = approved.json()["data"]["link"]["metadata"]
        assert link_metadata["evidence_has_page_ref"] is True
        assert link_metadata["evidence_refs"][0]["page_number"] == 1


def test_image_asset_extraction_indexes_image_evidence(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "memory-screenshot.png",
                "extract": "true",
            },
            content=sample_png_bytes(),
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "image_metadata"
        assert extracted["metadata"]["image_width"] == 120
        assert extracted["metadata"]["image_height"] == 40
        assert extracted["metadata"]["ocr_status"] in {
            "extracted",
            "failed",
            "no_text",
            "unavailable",
        }
        assert extracted["metadata"]["image_region_count"] >= 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "image_regions",
            "markdown",
            "media_manifest",
        }
        manifest_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "media_manifest"
        )
        manifest_download = client.get(
            f"/v1/extraction-artifacts/{manifest_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert manifest_download.status_code == 200, manifest_download.text
        manifest = json.loads(manifest_download.content)
        assert manifest["schema_version"] == "infinity_context.multimodal_manifest.v1"
        assert manifest["modalities"] == ["text", "image"]
        assert manifest["evidence_items"][0]["bbox"] == [0.0, 0.0, 120.0, 40.0]

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_text = " ".join(item["text"] for item in chunks.json()["data"])
        assert "Image asset evidence" in chunk_text
        assert "120x40" in chunk_text
        source_refs = [ref for chunk in chunks.json()["data"] for ref in chunk["source_refs"]]
        assert source_refs[0]["bbox"] == [0.0, 0.0, 120.0, 40.0]
        context = client.post(
            "/v1/context",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "query": "bbox region",
                "token_budget": 1200,
            },
            headers=auth_headers(),
        )
        assert context.status_code == 200, context.text
        context_data = context.json()["data"]
        context_refs = [
            ref for item in context_data["items"] for ref in item.get("source_refs", [])
        ]
        assert any(ref.get("bbox") == [0.0, 0.0, 120.0, 40.0] for ref in context_refs)
        assert context_data["diagnostics"]["source_refs_with_bbox_count"] >= 1
        assert context_data["diagnostics"]["multimodal_source_ref_count"] >= 1

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "source_type": "asset",
                "source_id": upload.json()["data"]["id"],
                "text": "Image asset evidence 120x40 screenshot",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        chunk_candidate = next(
            item
            for item in suggestions.json()["data"]["candidates"]
            if item["target_type"] == "chunk"
        )
        assert chunk_candidate["metadata"]["evidence_has_bbox_ref"] is True
        assert "image" in chunk_candidate["metadata"]["evidence_modalities"]
        assert chunk_candidate["metadata"]["evidence_refs"][0]["bbox"] == [
            0.0,
            0.0,
            120.0,
            40.0,
        ]

        approved = client.post(
            f"/v1/context-link-suggestions/{chunk_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "bbox evidence verified"},
            headers=auth_headers(),
        )
        assert approved.status_code == 200, approved.text
        link_metadata = approved.json()["data"]["link"]["metadata"]
        assert link_metadata["evidence_has_bbox_ref"] is True
        assert link_metadata["evidence_refs"][0]["bbox"] == [0.0, 0.0, 120.0, 40.0]


def test_standard_vision_profile_falls_back_to_local_image_metadata(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "memory-screenshot.png",
                "parser_profile": "standard_vision",
                "extract": "true",
            },
            content=sample_png_bytes(),
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_profile"] == "standard_vision"
        assert extracted["parser_name"] == "image_metadata"
        assert extracted["metadata"]["degraded_fallback"] is True
        assert extracted["metadata"]["fallback_parser_name"] == "openai_vision_image"
        assert (
            extracted["metadata"]["fallback_safe_error_code"]
            == "asset_extraction.vision_external_ai_disabled"
        )
        assert extracted["metadata"]["vision_status"] == "disabled"
        assert (
            extracted["metadata"]["vision_error_code"]
            == "asset_extraction.vision_external_ai_disabled"
        )
        assert extracted["metadata"]["vision_model"] == "gpt-4.1-mini"
        assert extracted["metadata"]["image_width"] == 120
        assert extracted["metadata"]["image_height"] == 40
        assert extracted["metadata"]["image_region_count"] >= 1


def test_standard_vision_profile_uses_provider_and_preserves_bbox_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OpenAIVisionImageExtractionEngine,
        "_client",
        lambda self: _SuccessfulVisionClient(),
    )
    with make_client(
        tmp_path,
        extraction_external_ai_enabled=True,
        extraction_vision_detail="low",
        openai_api_key="test-key",
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "memory-screenshot.png",
                "parser_profile": "standard_vision",
                "extract": "true",
            },
            content=sample_png_bytes(),
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_profile"] == "standard_vision"
        assert extracted["parser_name"] == "openai_vision_image"
        assert extracted["model_version"] == "gpt-4.1-mini"
        assert extracted["metadata"]["vision_status"] == "extracted"
        assert extracted["metadata"]["vision_detail"] == "low"
        assert extracted["metadata"]["vision_json_status"] == "parsed"
        assert extracted["metadata"]["vision_region_count"] == 1
        assert extracted["metadata"]["vision_prompt_policy"] == ("image_text_is_untrusted_evidence")
        assert "degraded_fallback" not in extracted["metadata"]
        artifact_types = {item["artifact_type"] for item in extracted["artifacts"]}
        assert {
            "extracted_json",
            "image_regions",
            "markdown",
            "media_manifest",
            "vision_json",
        } == artifact_types
        assert _VISION_PROVIDER_SECRET not in fetched.text
        assert "api_key" not in fetched.text

        vision_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "vision_json"
        )
        vision_download = client.get(
            f"/v1/extraction-artifacts/{vision_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert vision_download.status_code == 200, vision_download.text
        vision_payload = json.loads(vision_download.content.decode("utf-8"))
        assert vision_payload["schema_name"] == "infinity_context.vision_image_evidence"
        assert vision_payload["regions"][0]["bbox"] == [12.0, 4.0, 118.0, 36.0]
        assert "raw_provider_payload" not in vision_payload
        assert _VISION_PROVIDER_SECRET not in vision_download.text
        assert "api_key" not in vision_download.text

        region_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "image_regions"
        )
        regions_download = client.get(
            f"/v1/extraction-artifacts/{region_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert regions_download.status_code == 200, regions_download.text
        regions_payload = json.loads(regions_download.content.decode("utf-8"))
        assert regions_payload["schema_name"] == "infinity_context.image_regions"
        assert any(
            region["bbox"] == [12.0, 4.0, 118.0, 36.0] for region in regions_payload["regions"]
        )
        assert _VISION_PROVIDER_SECRET not in regions_download.text

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_payload = chunks.json()["data"]
        chunk_text = " ".join(item["text"] for item in chunk_payload)
        assert "Quick capture links this screenshot" in chunk_text
        source_refs = [ref for chunk in chunk_payload for ref in chunk["source_refs"]]
        assert any(ref.get("bbox") == [12.0, 4.0, 118.0, 36.0] for ref in source_refs)

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "source_type": "asset",
                "source_id": upload.json()["data"]["id"],
                "text": "Quick capture screenshot Save to MemoryScope Review links",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        chunk_candidate = next(
            item
            for item in suggestions.json()["data"]["candidates"]
            if item["target_type"] == "chunk"
        )
        assert chunk_candidate["metadata"]["evidence_has_bbox_ref"] is True
        assert "image" in chunk_candidate["metadata"]["evidence_modalities"]
        assert any(
            ref.get("bbox") == [12.0, 4.0, 118.0, 36.0]
            for ref in chunk_candidate["metadata"]["evidence_refs"]
        )


def test_standard_vision_provider_failure_falls_back_to_local_image_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OpenAIVisionImageExtractionEngine,
        "_client",
        lambda self: _FailingVisionClient(),
    )
    with make_client(
        tmp_path,
        extraction_external_ai_enabled=True,
        openai_api_key="test-key",
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "memory-screenshot.png",
                "parser_profile": "standard_vision",
                "extract": "true",
            },
            content=sample_png_bytes(),
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_profile"] == "standard_vision"
        assert extracted["parser_name"] == "image_metadata"
        assert extracted["safe_error_code"] is None
        assert extracted["metadata"]["degraded_fallback"] is True
        assert extracted["metadata"]["fallback_parser_name"] == "openai_vision_image"
        assert (
            extracted["metadata"]["fallback_safe_error_code"]
            == "asset_extraction.vision_provider_error"
        )
        assert extracted["metadata"]["vision_status"] == "failed"
        assert (
            extracted["metadata"]["vision_error_code"] == "asset_extraction.vision_provider_error"
        )
        assert extracted["metadata"]["vision_provider"] == "openai_vision"
        assert extracted["metadata"]["vision_model"] == "gpt-4.1-mini"
        assert extracted["metadata"]["vision_provider_retryable"] is True
        assert extracted["metadata"]["vision_provider_error_type"] == "RuntimeError"
        assert extracted["metadata"]["vision_request_timeout_seconds"] == 60.0
        assert extracted["metadata"]["image_width"] == 120
        assert extracted["metadata"]["image_height"] == 40
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "image_regions",
            "markdown",
            "media_manifest",
        }


def test_timed_text_transcript_extraction_stores_transcript_artifact(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "alex-call",
                "filename": "alex-call-transcript",
                "extract": "true",
            },
            content=(
                b"1\n00:00:01,000 --> 00:00:03,000\n"
                b"Alex asked to connect memory scope with uploaded evidence.\n\n"
                b"2\n00:00:04,000 --> 00:00:06,500\n"
                b"The frontend should show suggested links before saving.\n"
            ),
            headers=auth_headers({"Content-Type": "application/x-subrip"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "timed_text_transcript"
        assert extracted["metadata"]["segment_count"] == 2
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
            "media_manifest",
            "transcript",
        }
        transcript_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "transcript"
        )

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_text = " ".join(item["text"] for item in chunks.json()["data"])
        assert "connect memory scope with uploaded evidence" in chunk_text
        source_refs = [ref for chunk in chunks.json()["data"] for ref in chunk["source_refs"]]
        assert any(ref.get("time_start_ms") == 1000 for ref in source_refs)
        assert any(ref.get("time_end_ms") == 6500 for ref in source_refs)

        downloaded = client.get(
            f"/v1/extraction-artifacts/{transcript_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert downloaded.status_code == 200, downloaded.text
        assert b"00:00:01.000 --> 00:00:03.000" in downloaded.content


def test_audio_asset_extraction_indexes_media_metadata(tmp_path: Path) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "voice-notes",
                "filename": "voice-note.wav",
                "extract": "true",
                "estimated_media_seconds": 1,
            },
            content=sample_wav_bytes(),
            headers=auth_headers({"Content-Type": "audio/wav"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "media_metadata"
        assert extracted["metadata"]["duration_seconds"] > 0
        assert extracted["metadata"]["transcript_status"] == "not_configured"
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
            "media_manifest",
        }


def test_media_extraction_reconciles_unknown_duration_reservation(
    tmp_path: Path,
) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "voice-notes",
                "filename": "short-voice-note.wav",
                "extract": "true",
            },
            content=sample_wav_bytes(),
            headers=auth_headers({"Content-Type": "audio/wav"}),
        )
        assert upload.status_code == 201, upload.text
        extraction = upload.json()["data"]["extraction"]
        assert extraction["usage"]["media_analysis_seconds_requested"] == 600

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction['id']}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        usage = fetched.json()["data"]["usage"]
        assert usage["media_analysis_seconds_requested"] == 600
        assert usage["media_analysis_seconds_actual"] == 1
        assert usage["media_analysis_seconds_delta"] == -599
        assert usage["media_analysis_seconds_final"] == 1
        assert usage["reconciled"] is True

        summary = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["data"]["resources"][0]["used"] == 1


def test_media_extraction_reconciles_underestimated_duration(
    tmp_path: Path,
) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "voice-notes",
                "filename": "longer-voice-note.wav",
                "extract": "true",
                "estimated_media_seconds": 1,
            },
            content=sample_wav_bytes(seconds=2),
            headers=auth_headers({"Content-Type": "audio/wav"}),
        )
        assert upload.status_code == 201, upload.text
        extraction = upload.json()["data"]["extraction"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction['id']}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        usage = fetched.json()["data"]["usage"]
        assert usage["media_analysis_seconds_requested"] == 1
        assert usage["media_analysis_seconds_actual"] == 2
        assert usage["media_analysis_seconds_delta"] == 1
        assert usage["media_analysis_seconds_final"] == 2
        assert usage["reconciled"] is True

        summary = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["data"]["resources"][0]["used"] == 2


def test_video_asset_extraction_stores_keyframe_artifact(tmp_path: Path) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screen-recordings",
                "filename": "demo-recording.mp4",
                "extract": "true",
                "estimated_media_seconds": 1,
            },
            content=sample_mp4_bytes(tmp_path),
            headers=auth_headers({"Content-Type": "video/mp4"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "succeeded"
        assert extracted["parser_name"] == "media_metadata"
        assert extracted["metadata"]["duration_seconds"] > 0
        assert extracted["metadata"]["keyframe_status"] == "extracted"
        artifact_types = {item["artifact_type"] for item in extracted["artifacts"]}
        assert {"extracted_json", "keyframe", "markdown", "media_manifest"}.issubset(artifact_types)
        assert "video_frame_timeline" in artifact_types
        assert extracted["metadata"]["video_keyframe_count"] >= 1
        timeline_artifact = next(
            item
            for item in extracted["artifacts"]
            if item["artifact_type"] == "video_frame_timeline"
        )
        timeline = client.get(
            f"/v1/extraction-artifacts/{timeline_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert timeline.status_code == 200, timeline.text
        timeline_payload = json.loads(timeline.content.decode("utf-8"))
        first_frame = timeline_payload["frames"][0]
        assert first_frame["selection"] == "sampled_keyframe"
        assert first_frame["time_start_ms"] <= first_frame["selected_at_ms"]
        assert first_frame["time_end_ms"] >= first_frame["selected_at_ms"]


def test_asset_extraction_request_is_idempotent_before_and_after_worker(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "capture.txt",
            },
            content=b"Store this once and do not create duplicate extraction jobs.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        asset_id = upload.json()["data"]["id"]

        first = client.post(
            f"/v1/assets/{asset_id}/extractions",
            headers=auth_headers(),
        )
        second = client.post(
            f"/v1/assets/{asset_id}/extractions",
            headers=auth_headers(),
        )
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        first_data = first.json()["data"]
        second_data = second.json()["data"]
        assert first_data["duplicate"] is False
        assert second_data["duplicate"] is True
        assert second_data["id"] == first_data["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        after_worker = client.post(
            f"/v1/assets/{asset_id}/extractions",
            headers=auth_headers(),
        )
        assert after_worker.status_code == 202, after_worker.text
        after_worker_data = after_worker.json()["data"]
        assert after_worker_data["duplicate"] is True
        assert after_worker_data["id"] == first_data["id"]
        assert after_worker_data["status"] == "succeeded"


def test_unsupported_asset_extraction_finishes_without_document_or_retry(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "scan.pdf",
                "extract": "true",
            },
            content=b"%PDF-1.7\n% fake unit pdf bytes\n",
            headers=auth_headers({"Content-Type": "application/pdf"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "unsupported"
        assert extracted["safe_error_code"] == "asset_extraction.pdf_parse_failed"
        assert extracted["result_document_ids"] == []
        assert extracted["artifacts"] == []
        assert extracted["attempt_count"] == 1
        assert extracted["execution"]["available_actions"] == ["retry"]
        assert extracted["execution"]["retry_actionable"] is True
        assert extracted["execution"]["cancel_actionable"] is False
        assert (
            extracted["execution"]["retry_state_reason"]
            == "unsupported_after_provider_or_parser_fix"
        )
        assert extracted["execution"]["cancel_state_reason"] == "terminal_job"


def test_invalid_media_asset_extraction_finishes_unsupported(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "broken-recording.mp4",
                "extract": "true",
                "estimated_media_seconds": 30,
            },
            content=b"\x00\x01not a real mp4 file\x00\x02",
            headers=auth_headers({"Content-Type": "video/mp4"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        processed = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed >= 1

        fetched = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert fetched.status_code == 200, fetched.text
        extracted = fetched.json()["data"]
        assert extracted["status"] == "unsupported"
        assert extracted["safe_error_code"] in {
            "asset_extraction.media_probe_failed",
            "asset_extraction.media_probe_unavailable",
        }
        assert extracted["result_document_ids"] == []
        assert extracted["artifacts"] == []
        assert extracted["usage"]["media_analysis_seconds_requested"] == 30
        assert extracted["usage"]["media_analysis_seconds_actual"] == 0
        assert extracted["usage"]["media_analysis_seconds_delta"] == -30
        assert extracted["usage"]["media_analysis_seconds_final"] == 0
        assert extracted["usage"]["reconciled"] is True

        usage = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert usage.status_code == 200, usage.text
        assert usage.json()["data"]["resources"][0]["used"] == 0

        retry = client.post(
            f"/v1/asset-extractions/{extraction_id}/retry",
            headers=auth_headers(),
        )
        assert retry.status_code == 202, retry.text

        processed_retry = asyncio.run(OutboxWorker(client.app.state.container).run_once(limit=10))
        assert processed_retry >= 1

        after_retry = client.get(
            f"/v1/asset-extractions/{extraction_id}",
            headers=auth_headers(),
        )
        assert after_retry.status_code == 200, after_retry.text
        retried = after_retry.json()["data"]
        assert retried["attempt_count"] == 2
        assert retried["usage"]["media_analysis_seconds_requested"] == 30
        assert retried["usage"]["media_analysis_seconds_actual"] == 0
        assert retried["usage"]["media_analysis_seconds_delta"] == -30
        assert retried["usage"]["media_analysis_seconds_final"] == 0

        usage_after_retry = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert usage_after_retry.status_code == 200, usage_after_retry.text
        assert usage_after_retry.json()["data"]["resources"][0]["used"] == 0


def test_scoped_tokens_cannot_read_cross_scope_extraction_jobs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'scoped-extractions.db'}"
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
            capture_mode=CaptureMode.SUGGEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "scoped-extractions", "name": "Scoped Extractions"},
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
        upload_a = client.post(
            "/v1/assets",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "filename": "alpha.txt",
                "extract": "true",
            },
            content=b"alpha extraction",
            headers={**root_headers, "Content-Type": "text/plain"},
        ).json()["data"]
        upload_b = client.post(
            "/v1/assets",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "filename": "beta.txt",
                "extract": "true",
            },
            content=b"beta extraction secret",
            headers={**root_headers, "Content-Type": "text/plain"},
        ).json()["data"]

    scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha extraction scope",
            permissions=("memory:read",),
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}

    with TestClient(app) as client:
        asyncio.run(OutboxWorker(app.state.container).run_once(limit=10))
        same_scope = client.get(
            f"/v1/asset-extractions/{upload_a['extraction']['id']}",
            headers=scoped_headers,
        )
        cross_scope = client.get(
            f"/v1/asset-extractions/{upload_b['extraction']['id']}",
            headers=scoped_headers,
        )
        artifact_a = same_scope.json()["data"]["artifacts"][0]
        artifact_b = client.get(
            f"/v1/asset-extractions/{upload_b['extraction']['id']}",
            headers=root_headers,
        ).json()["data"]["artifacts"][0]
        same_artifact = client.get(
            f"/v1/extraction-artifacts/{artifact_a['id']}/download",
            headers=scoped_headers,
        )
        cross_artifact = client.get(
            f"/v1/extraction-artifacts/{artifact_b['id']}/download",
            headers=scoped_headers,
        )

    assert same_scope.status_code == 200, same_scope.text
    assert cross_scope.status_code == 403
    assert same_artifact.status_code == 200
    assert cross_artifact.status_code == 403
    assert "beta extraction secret" not in cross_scope.text
    assert "beta extraction secret" not in cross_artifact.text


def test_upload_extract_quota_error_redacts_sensitive_message(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.app.state.container = replace(
            client.app.state.container,
            request_asset_extraction=_QuotaFailureExtractionRequest(),
        )

        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "over-quota.txt",
                "extract": "true",
            },
            content=b"keep this text but redact quota diagnostics",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )

    assert upload.status_code == 201, upload.text
    error = upload.json()["data"]["extraction_error"]
    assert error["code"] == "memory.quota_exceeded"
    assert error["retryable"] is False
    assert "[redacted]" in error["message"]
    assert "sk-proj-secretvalue1234567890" not in error["message"]


def test_media_extraction_consumes_free_plan_quota_and_blocks_overage(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        first = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "long-call.mp3",
                "extract": "true",
                "estimated_media_seconds": 9 * 60 * 60,
            },
            content=b"fake mp3 bytes",
            headers=auth_headers({"Content-Type": "audio/mpeg"}),
        )
        assert first.status_code == 201, first.text
        extraction = first.json()["data"]["extraction"]
        assert extraction["usage"]["plan_tier"] == "free"
        assert extraction["usage"]["media_analysis_seconds_requested"] == 9 * 60 * 60
        assert extraction["usage"]["media_analysis_seconds_limit"] == 10 * 60 * 60
        assert extraction["usage"]["media_analysis_seconds_remaining_before_request"] == (
            10 * 60 * 60
        )

        usage = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert usage.status_code == 200, usage.text
        resource = usage.json()["data"]["resources"][0]
        assert resource["resource"] == "media_analysis_seconds"
        assert resource["used"] == 9 * 60 * 60
        assert resource["remaining"] == 60 * 60

        upload_overage_asset = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "follow-up.mp4",
                "estimated_media_seconds": 2 * 60 * 60,
            },
            content=b"fake mp4 bytes",
            headers=auth_headers({"Content-Type": "video/mp4"}),
        )
        assert upload_overage_asset.status_code == 201, upload_overage_asset.text
        overage_asset_id = upload_overage_asset.json()["data"]["id"]

        overage = client.post(
            f"/v1/assets/{overage_asset_id}/extractions",
            headers=auth_headers(),
        )
        assert overage.status_code == 402, overage.text
        assert overage.json()["error"]["code"] == "memory.quota_exceeded"


def test_unknown_media_duration_reserves_default_media_quota(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        uploaded = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "filename": "voice-note.mp3",
                "extract": "true",
            },
            content=b"fake mp3 bytes",
            headers=auth_headers({"Content-Type": "audio/mpeg"}),
        )
        assert uploaded.status_code == 201, uploaded.text
        extraction = uploaded.json()["data"]["extraction"]
        assert extraction["usage"]["media_analysis_seconds_requested"] == 600

        usage = client.get(
            "/v1/usage",
            params={"space_slug": "quick-capture"},
            headers=auth_headers(),
        )
        assert usage.status_code == 200, usage.text
        assert usage.json()["data"]["resources"][0]["used"] == 600
