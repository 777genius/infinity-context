from __future__ import annotations

import json
import shutil
import subprocess
import urllib.parse
from typing import Any

import pytest

from scripts import multimodal_docker_live_proof as proof


def test_docker_live_proof_runs_compose_flow_and_redacts_token(monkeypatch) -> None:
    monkeypatch.setattr(proof, "_docker_context_show", lambda _command: "desktop-linux")
    args = proof._parse_args(
        [
            "--no-build",
            "--project-name",
            "infinity-context-proof-test",
            "--service-token",
            "secret-proof-token",
            "--server-port",
            "18181",
            "--postgres-port",
            "18182",
            "--qdrant-port",
            "18183",
            "--neo4j-http-port",
            "18184",
            "--neo4j-bolt-port",
            "18185",
        ]
    )
    commands: list[list[str]] = []
    uploaded: dict[str, dict[str, Any]] = {}

    def run_cmd(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        text = " ".join(command)
        if command[:2] == ["docker", "info"]:
            return _completed(command, stdout="29.0.0\n")
        if "config" in command:
            return _completed(command)
        if "up" in command:
            return _completed(command, stdout="started\n")
        if "down" in command:
            return _completed(command, stdout="removed\n")
        if "exec" in command and "ffmpeg" in text:
            return _completed(command, stdout="ffmpeg version 7.1\n")
        if "exec" in command and "ffprobe" in text:
            return _completed(command, stdout="ffprobe version 7.1\n")
        if "exec" in command and "tesseract" in text:
            return _completed(command, stdout="tesseract 5.5.1\n")
        if "exec" in command and "docling" in text:
            return _completed(command, stdout="2.102.1\n")
        raise AssertionError(f"Unexpected command: {command}")

    def request_json(
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if method == "GET" and parsed.path == "/v1/health":
            return {"status": "ok"}
        if method == "GET" and parsed.path == "/v1/capabilities":
            return {
                "extraction": {
                    "modality_actions": {
                        "document": {},
                        "image": {},
                        "audio": {},
                        "video": {},
                    },
                    "providers": {"local": {}, "docling": {}},
                    "evidence_contract": {},
                    "feature_contract": {},
                    "provider_contract": {
                        "transcription": {
                            "endpoint": "/v1/audio/transcriptions",
                            "max_provider_upload_bytes": 26214400,
                            "effective_max_upload_bytes": 26214400,
                            "supported_file_types": [
                                ".m4a",
                                ".mp3",
                                ".mp4",
                                ".mpeg",
                                ".mpga",
                                ".wav",
                                ".webm",
                            ],
                        },
                        "vision": {
                            "endpoint_family": "responses",
                            "model": "gpt-4.1-mini",
                            "detail_levels": ["low", "high", "auto"],
                            "max_provider_binary_upload_bytes": 402650094,
                            "max_provider_payload_bytes": 536870912,
                            "max_images_per_request": 1500,
                            "effective_max_upload_bytes": 26214400,
                            "supported_file_types": [
                                ".gif",
                                ".jpeg",
                                ".jpg",
                                ".png",
                                ".webp",
                            ],
                        },
                    },
                    "manifest_contract": {},
                    "file_type_detection": {},
                }
            }
        if method == "POST" and parsed.path == "/v1/assets":
            query = urllib.parse.parse_qs(parsed.query)
            filename = query["filename"][0]
            extraction_id = f"extract-{len(uploaded) + 1}"
            document_id = f"doc-{len(uploaded) + 1}"
            uploaded[extraction_id] = {
                "filename": filename,
                "document_id": document_id,
                "content": (content or b"").decode("utf-8", errors="ignore"),
                "content_type": content_type,
            }
            return {"data": {"extraction": {"id": extraction_id}}}
        if method == "GET" and parsed.path.startswith("/v1/asset-extractions/"):
            extraction_id = parsed.path.rsplit("/", 1)[-1]
            item = uploaded[extraction_id]
            filename = item["filename"]
            artifact_map = {
                "docker-proof.txt": ["extracted_json", "markdown"],
                "docker-proof.pdf": ["extracted_json", "markdown"],
                "docker-proof.png": ["extracted_json", "image_regions", "markdown"],
                "docker-proof.wav": ["extracted_json", "markdown", "media_manifest"],
                "docker-proof.mp4": [
                    "extracted_json",
                    "keyframe",
                    "markdown",
                    "media_manifest",
                    "video_frame_timeline",
                ],
            }
            parser_map = {
                "docker-proof.txt": "simple_text",
                "docker-proof.pdf": "pypdf_text",
                "docker-proof.png": "image_metadata",
                "docker-proof.wav": "media_metadata",
                "docker-proof.mp4": "media_metadata",
            }
            return {
                "data": {
                    "status": "succeeded",
                    "parser_name": parser_map[filename],
                    "artifacts": [
                        {"artifact_type": artifact_type}
                        for artifact_type in artifact_map[filename]
                    ],
                    "result_document_ids": [item["document_id"]],
                }
            }
        if method == "GET" and parsed.path.startswith("/v1/documents/"):
            document_id = parsed.path.split("/")[3]
            item = next(
                value for value in uploaded.values() if value["document_id"] == document_id
            )
            chunk_text = {
                "docker-proof.txt": item["content"],
                "docker-proof.pdf": item["content"],
                "docker-proof.png": "Image asset evidence with OCR metadata",
                "docker-proof.wav": "Media asset evidence with ffprobe metadata",
                "docker-proof.mp4": "Media asset evidence with keyframe metadata",
            }[item["filename"]]
            return {"data": [{"text": chunk_text}]}
        raise AssertionError(f"Unexpected request: {method} {url}")

    report = proof.run_multimodal_docker_live_proof(
        args,
        run_cmd=run_cmd,
        request_json=request_json,
        sleep=lambda _: None,
    )

    assert report["ok"] is True
    assert report["components"]["compose_stack"]["status"] == "succeeded"
    assert report["components"]["compose_stack"]["state"] == "running"
    assert report["components"]["container_dependencies"]["versions"]["ffmpeg"]
    assert report["components"]["capabilities"]["provider_contract"]["ok"] is True
    assert (
        report["components"]["capabilities"]["provider_contract"][
            "transcription_max_provider_upload_bytes"
        ]
        == 26214400
    )
    assert (
        report["components"]["capabilities"]["provider_contract"][
            "transcription_effective_max_upload_bytes"
        ]
        == 26214400
    )
    assert report["components"]["capabilities"]["provider_contract"][
        "vision_detail_levels"
    ] == ["low", "high", "auto"]
    assert (
        report["components"]["capabilities"]["provider_contract"][
            "vision_max_provider_binary_upload_bytes"
        ]
        == 402650094
    )
    assert (
        report["components"]["capabilities"]["provider_contract"][
            "vision_max_provider_payload_bytes"
        ]
        == 536870912
    )
    assert (
        report["components"]["capabilities"]["provider_contract"][
            "vision_max_images_per_request"
        ]
        == 1500
    )
    assert "provider_contract" in report["components"]["capabilities"]["contract_names"]
    cases = report["components"]["extraction_flow"]["cases"]
    assert len(cases) == 5
    filenames = {case["filename"] for case in cases}
    assert {
        "docker-proof.pdf",
        "docker-proof.png",
        "docker-proof.wav",
        "docker-proof.mp4",
    }.issubset(filenames)
    assert any("--profile" in command and "lite" in command for command in commands)
    assert any(
        "up" in command and "infinity_context_extraction_worker" in command
        for command in commands
    )
    assert any("down" in command and "-v" in command for command in commands)
    assert "secret-proof-token" not in json.dumps(report)


def test_docker_live_proof_degrades_on_daemon_timeout(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/infinity-context-secret-docker.sock")
    monkeypatch.setattr(proof, "_docker_context_show", lambda _command: "desktop-linux")
    args = proof._parse_args(
        [
            "--project-name",
            "infinity-context-proof-test",
            "--docker-timeout-seconds",
            "1",
            "--server-port",
            "18181",
            "--postgres-port",
            "18182",
            "--qdrant-port",
            "18183",
            "--neo4j-http-port",
            "18184",
            "--neo4j-bolt-port",
            "18185",
        ]
    )

    def run_cmd(command: list[str]) -> subprocess.CompletedProcess[str]:
        if "config" in command:
            return _completed(command)
        raise subprocess.TimeoutExpired(command, timeout=1)

    report = proof.run_multimodal_docker_live_proof(
        args,
        run_cmd=run_cmd,
        request_json=lambda *_args, **_kwargs: {},
        sleep=lambda _: None,
    )

    assert report["ok"] is False
    assert report["failure"]["component"] == "docker_daemon"
    assert report["failure"]["reason"] == "docker_daemon_timeout"
    assert report["failure"]["degraded"] is True
    assert report["failure"]["user_retryable"] is True
    assert report["failure"]["operator_action"] == "start_or_restart_docker_daemon"
    assert report["components"]["compose_config"]["status"] == "succeeded"
    assert report["failure"]["diagnostics"]["docker_context"] == "desktop-linux"
    assert report["failure"]["diagnostics"]["docker_context_current"] == "desktop-linux"
    assert report["failure"]["diagnostics"]["docker_host"] == {
        "configured": True,
        "kind": "unix",
        "socket": {
            "exists": False,
            "is_socket": False,
            "is_symlink": False,
        },
    }
    assert "desktop_socket_exists" in report["failure"]["message"]
    assert report["components"]["docker_daemon"]["status"] == "degraded"
    assert report["components"]["docker_daemon"]["user_retryable"] is True
    assert (
        report["components"]["docker_daemon"]["operator_action"]
        == "start_or_restart_docker_daemon"
    )
    assert report["components"]["docker_daemon"]["diagnostics"] == report["failure"][
        "diagnostics"
    ]
    assert report["components"]["cleanup"]["status"] == "unknown"
    rendered = json.dumps(report)
    assert "infinity-context-secret-docker.sock" not in rendered
    assert "secret-proof-token" not in rendered


def test_docker_live_proof_degrades_on_compose_config_timeout(monkeypatch) -> None:
    monkeypatch.setattr(proof, "_docker_context_show", lambda _command: "desktop-linux")
    args = proof._parse_args(
        [
            "--project-name",
            "infinity-context-proof-test",
            "--compose-timeout-seconds",
            "1",
            "--server-port",
            "18181",
            "--postgres-port",
            "18182",
            "--qdrant-port",
            "18183",
            "--neo4j-http-port",
            "18184",
            "--neo4j-bolt-port",
            "18185",
        ]
    )

    def run_cmd(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert "config" in command
        raise subprocess.TimeoutExpired(command, timeout=1)

    report = proof.run_multimodal_docker_live_proof(
        args,
        run_cmd=run_cmd,
        request_json=lambda *_args, **_kwargs: {},
        sleep=lambda _: None,
    )

    assert report["ok"] is False
    assert report["failure"]["component"] == "compose_config"
    assert report["failure"]["reason"] == "compose_config_timeout"
    assert report["failure"]["degraded"] is True
    assert report["failure"]["user_retryable"] is False
    assert report["failure"]["operator_action"] == "inspect_compose_stack"
    assert report["components"]["compose_config"]["status"] == "degraded"
    assert report["components"]["docker_daemon"]["status"] == "unknown"
    assert report["components"]["cleanup"]["status"] == "unknown"


def test_makefile_exposes_multimodal_docker_live_proof_target() -> None:
    makefile = (proof.ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: infinity-context-multimodal-docker-live-proof" in makefile
    assert "$(PYTHON) scripts/multimodal_docker_live_proof.py" in makefile


def test_sample_mp4_fixture_contains_extractable_video_frame(tmp_path) -> None:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        pytest.skip("ffprobe and ffmpeg are required to validate the MP4 fixture")

    video_path = tmp_path / "docker-proof.mp4"
    frame_path = tmp_path / "keyframe.jpg"
    video_path.write_bytes(proof._sample_mp4_bytes())

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(probe.stdout)
    assert any(
        stream.get("codec_type") == "video" for stream in payload.get("streams", [])
    )

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-ss",
            "0",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(frame_path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    assert frame_path.stat().st_size > 0


def _completed(
    command: list[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
