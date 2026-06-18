import asyncio
import json
import shutil
import subprocess
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from memo_stack_adapters.extraction.transcription.openai_adapter import (
    OpenAISpeechTranscriptionAdapter,
)
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.main import create_app
from memo_stack_server.worker import OutboxWorker

_PROVIDER_SECRET = "sk-proj-transcript-secret-value1234567890"


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
    video_path = tmp_path / "product-demo.mp4"
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


class _FakeTranscriptionResponse:
    text = "Alex discussed memory scopes from a voice note."
    language = "en"
    duration = 1.0
    segments = [
        {
            "id": f"segment Bearer {_PROVIDER_SECRET}",
            "start": 0.0,
            "end": 1.0,
            "text": "Alex discussed memory scopes from a voice note.",
        }
    ]
    usage = {
        "debug": f"provider token {_PROVIDER_SECRET}",
        "api_key": _PROVIDER_SECRET,
    }


class _FakeAudioTranscriptions:
    async def create(self, **kwargs: Any) -> _FakeTranscriptionResponse:
        assert kwargs["model"] == "gpt-4o-mini-transcribe"
        assert kwargs["response_format"] == "json"
        assert kwargs["file"].name == "voice-note.wav"
        return _FakeTranscriptionResponse()


class _FakeAudioClient:
    transcriptions = _FakeAudioTranscriptions()


class _FakeTranscriptionClient:
    audio = _FakeAudioClient()

    async def aclose(self) -> None:
        return None


class _FakeVideoTranscriptionResponse:
    text = "Alex narrated the product demo while showing the memory review panel."
    language = "en"
    duration = 1.0
    segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Alex narrated the product demo while showing the memory review panel.",
        }
    ]


class _FakeVideoAudioTranscriptions:
    async def create(self, **kwargs: Any) -> _FakeVideoTranscriptionResponse:
        assert kwargs["model"] == "gpt-4o-mini-transcribe"
        assert kwargs["response_format"] == "json"
        assert kwargs["file"].name == "product-demo.mp4"
        return _FakeVideoTranscriptionResponse()


class _FakeVideoAudioClient:
    transcriptions = _FakeVideoAudioTranscriptions()


class _FakeVideoTranscriptionClient:
    audio = _FakeVideoAudioClient()

    async def aclose(self) -> None:
        return None


class _FailingAudioTranscriptions:
    async def create(self, **kwargs: Any) -> object:
        raise RuntimeError("simulated provider outage")


class _FailingAudioClient:
    transcriptions = _FailingAudioTranscriptions()


class _FailingTranscriptionClient:
    audio = _FailingAudioClient()

    async def aclose(self) -> None:
        return None


def test_audio_asset_extraction_uses_api_first_transcription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OpenAISpeechTranscriptionAdapter,
        "_client",
        lambda self: _FakeTranscriptionClient(),
    )
    with make_client(
        tmp_path,
        extraction_external_ai_enabled=True,
        extraction_default_profile="media_api",
        openai_api_key="test-key",
        transcription_provider="openai",
        transcription_openai_model="gpt-4o-mini-transcribe",
    ) as client:
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
        assert extracted["parser_name"] == "speech_transcription"
        assert extracted["model_version"] == "gpt-4o-mini-transcribe"
        assert extracted["metadata"]["transcript_status"] == "extracted"
        assert extracted["metadata"]["transcription_provider"] == "openai_transcription"
        assert extracted["metadata"]["transcript_feature_names"] == "segments,time_ranges"
        assert extracted["metadata"]["has_time_ranges"] is True
        assert extracted["metadata"]["has_speaker_labels"] is False
        assert extracted["metadata"]["has_word_timestamps"] is False
        assert extracted["usage"]["media_analysis_seconds_actual"] == 1
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
            "media_manifest",
            "transcript",
            "transcript_json",
        }
        transcript_json_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "transcript_json"
        )
        transcript_download = client.get(
            f"/v1/extraction-artifacts/{transcript_json_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert transcript_download.status_code == 200, transcript_download.text
        transcript_payload = json.loads(transcript_download.content.decode("utf-8"))
        assert transcript_payload["schema_name"] == "memo_stack.transcript"
        assert transcript_payload["features"] == {
            "transcript_features": ["segments", "time_ranges"],
            "transcript_feature_names": "segments,time_ranges",
            "has_time_ranges": True,
            "has_speaker_labels": False,
            "has_word_timestamps": False,
        }
        assert transcript_payload["segments"][0]["start_ms"] == 0
        assert transcript_payload["segments"][0]["end_ms"] == 1000
        assert _PROVIDER_SECRET not in transcript_download.text
        assert "api_key" not in transcript_payload["provider"]["diagnostics"]
        assert "[redacted]" in json.dumps(transcript_payload, ensure_ascii=False)

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        first_chunk = chunks.json()["data"][0]
        assert "Alex discussed memory scopes" in first_chunk["text"]
        source_refs = first_chunk["source_refs"]
        assert source_refs[0]["source_type"] == "asset_extraction"
        assert source_refs[0]["asset_id"] == upload.json()["data"]["id"]
        assert source_refs[0]["time_start_ms"] == 0
        assert source_refs[0]["time_end_ms"] == 1000


def test_video_asset_extraction_uses_api_transcript_and_keyframes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    monkeypatch.setattr(
        OpenAISpeechTranscriptionAdapter,
        "_client",
        lambda self: _FakeVideoTranscriptionClient(),
    )
    with make_client(
        tmp_path,
        extraction_external_ai_enabled=True,
        extraction_default_profile="media_api",
        openai_api_key="test-key",
        transcription_provider="openai",
        transcription_openai_model="gpt-4o-mini-transcribe",
    ) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screen-recordings",
                "filename": "product-demo.mp4",
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
        assert extracted["parser_name"] == "speech_transcription"
        assert extracted["metadata"]["transcript_status"] == "extracted"
        assert extracted["metadata"]["keyframe_status"] == "extracted"
        assert extracted["metadata"]["video_keyframe_count"] >= 1
        artifact_types = {item["artifact_type"] for item in extracted["artifacts"]}
        assert {
            "extracted_json",
            "keyframe",
            "markdown",
            "media_manifest",
            "transcript",
            "transcript_json",
            "video_frame_timeline",
        }.issubset(artifact_types)

        transcript_artifact = next(
            item for item in extracted["artifacts"] if item["artifact_type"] == "transcript_json"
        )
        transcript_download = client.get(
            f"/v1/extraction-artifacts/{transcript_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert transcript_download.status_code == 200, transcript_download.text
        transcript_payload = json.loads(transcript_download.content.decode("utf-8"))
        assert transcript_payload["schema_name"] == "memo_stack.transcript"
        assert transcript_payload["segments"][0]["start_ms"] == 0
        assert transcript_payload["segments"][0]["end_ms"] == 1000

        timeline_artifact = next(
            item
            for item in extracted["artifacts"]
            if item["artifact_type"] == "video_frame_timeline"
        )
        timeline_download = client.get(
            f"/v1/extraction-artifacts/{timeline_artifact['id']}/download",
            headers=auth_headers(),
        )
        assert timeline_download.status_code == 200, timeline_download.text
        timeline_payload = json.loads(timeline_download.content.decode("utf-8"))
        assert timeline_payload["schema_name"] == "memo_stack.video_frame_timeline"
        assert timeline_payload["frames"]

        chunks = client.get(
            f"/v1/documents/{extracted['result_document_ids'][0]}/chunks",
            headers=auth_headers(),
        )
        assert chunks.status_code == 200, chunks.text
        chunk_payload = chunks.json()["data"]
        chunk_text = " ".join(item["text"] for item in chunk_payload)
        assert "Alex narrated the product demo" in chunk_text
        source_refs = [ref for chunk in chunk_payload for ref in chunk["source_refs"]]
        assert any(ref.get("time_start_ms") == 0 for ref in source_refs)
        assert any(ref.get("time_end_ms") == 1000 for ref in source_refs)


def test_audio_asset_extraction_provider_failure_falls_back_to_media_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")

    monkeypatch.setattr(
        OpenAISpeechTranscriptionAdapter,
        "_client",
        lambda self: _FailingTranscriptionClient(),
    )
    with make_client(
        tmp_path,
        extraction_external_ai_enabled=True,
        extraction_default_profile="media_api",
        openai_api_key="test-key",
        transcription_provider="openai",
        transcription_openai_model="gpt-4o-mini-transcribe",
    ) as client:
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
        assert extracted["parser_profile"] == "media_api"
        assert extracted["parser_name"] == "media_metadata"
        assert extracted["safe_error_code"] is None
        assert extracted["metadata"]["degraded_fallback"] is True
        assert extracted["metadata"]["transcript_status"] == "failed"
        assert (
            extracted["metadata"]["transcript_error_code"]
            == "asset_extraction.transcription_provider_error"
        )
        assert extracted["metadata"]["transcription_provider"] == "openai_transcription"
        assert extracted["metadata"]["transcription_model"] == "gpt-4o-mini-transcribe"
        assert extracted["metadata"]["transcript_provider_retryable"] is True
        assert extracted["metadata"]["transcript_provider_error_type"] == "RuntimeError"
        assert extracted["metadata"]["transcript_request_timeout_seconds"] == 60.0
        assert extracted["metadata"]["duration_seconds"] > 0
        assert {item["artifact_type"] for item in extracted["artifacts"]} == {
            "extracted_json",
            "markdown",
            "media_manifest",
        }
        assert extracted["usage"]["media_analysis_seconds_requested"] == 1
        assert extracted["usage"]["media_analysis_seconds_actual"] == 1
        assert extracted["usage"]["reconciled"] is True
