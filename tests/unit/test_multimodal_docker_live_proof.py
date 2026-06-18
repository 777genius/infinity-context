from __future__ import annotations

import json
import subprocess
import urllib.parse
from typing import Any

from scripts import multimodal_docker_live_proof as proof


def test_docker_live_proof_runs_compose_flow_and_redacts_token() -> None:
    args = proof._parse_args(
        [
            "--no-build",
            "--project-name",
            "memo-stack-proof-test",
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
    assert report["components"]["container_dependencies"]["versions"]["ffmpeg"]
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
        "up" in command and "memo_stack_extraction_worker" in command
        for command in commands
    )
    assert any("down" in command and "-v" in command for command in commands)
    assert "secret-proof-token" not in json.dumps(report)


def test_docker_live_proof_degrades_on_daemon_timeout() -> None:
    args = proof._parse_args(
        [
            "--project-name",
            "memo-stack-proof-test",
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
    assert report["failure"]["operator_action"] == "start_docker_daemon"
    assert report["components"]["docker_daemon"]["status"] == "degraded"
    assert report["components"]["docker_daemon"]["user_retryable"] is True
    assert report["components"]["docker_daemon"]["operator_action"] == "start_docker_daemon"
    assert report["components"]["cleanup"]["status"] == "unknown"


def test_makefile_exposes_multimodal_docker_live_proof_target() -> None:
    makefile = (proof.ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-multimodal-docker-live-proof" in makefile
    assert "$(PYTHON) scripts/multimodal_docker_live_proof.py" in makefile


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
