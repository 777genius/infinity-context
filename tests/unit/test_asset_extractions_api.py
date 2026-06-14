import asyncio
import shutil
import subprocess
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from memo_stack_server.admin import token_create
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.db import upgrade
from memo_stack_server.main import create_app
from memo_stack_server.worker import OutboxWorker


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
        assert b"quick capture attached to memory scopes" in downloaded.content


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
        }

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
        }

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
        assert extracted["metadata"]["image_width"] == 120
        assert extracted["metadata"]["image_height"] == 40
        assert extracted["metadata"]["image_region_count"] >= 1


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
            content=b"not a real mp4 file",
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
