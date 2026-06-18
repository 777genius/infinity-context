#!/usr/bin/env python3
"""Run a Docker-backed multimodal ingestion proof without leaking secrets."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import shutil
import socket
import stat
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"
SUITE = "infinity-context-multimodal-docker-live-proof"
DEFAULT_REPORT = ".e2e-artifacts/multimodal-docker-live-proof.json"

RunCommand = Callable[[list[str]], subprocess.CompletedProcess[str]]
RequestJson = Callable[..., dict[str, Any]]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class DockerProofFailure(RuntimeError):
    component: str
    reason: str
    message: str
    degraded: bool = False
    diagnostics: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_multimodal_docker_live_proof(args)
    _write_report(report, args.report_out)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["ok"] is True:
        return 0
    failure = report.get("failure")
    if isinstance(failure, dict) and failure.get("degraded") is True:
        return 2
    return 1


def run_multimodal_docker_live_proof(
    args: argparse.Namespace,
    *,
    run_cmd: RunCommand | None = None,
    request_json: RequestJson | None = None,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    ports = _ports(args)
    project_name = args.project_name or f"infinity-context-multimodal-{int(time.time() * 1000)}"
    token = args.service_token or f"local-proof-{uuid.uuid4().hex}"
    env = _compose_env(args, ports=ports, token=token)
    run_cmd = run_cmd or _command_runner(args, env=env)
    request_json = request_json or _request_json_factory(token)
    report = _base_report(args, project_name=project_name, ports=ports, token=token)
    stack_started = False

    try:
        _prove_compose_config(args, project_name, run_cmd=run_cmd, report=report, env=env)
        _prove_docker_daemon(args, run_cmd=run_cmd, report=report, env=env)
        _start_stack(args, project_name, run_cmd=run_cmd, report=report, env=env)
        stack_started = True
        _prove_container_dependencies(
            args,
            project_name,
            run_cmd=run_cmd,
            report=report,
            env=env,
        )
        base_url = f"http://127.0.0.1:{ports['server']}"
        _wait_for_health(
            base_url,
            token,
            request_json=request_json,
            report=report,
            sleep=sleep,
            timeout_seconds=args.startup_timeout_seconds,
        )
        _prove_capabilities(base_url, request_json=request_json, report=report)
        _prove_extraction_flow(
            base_url,
            request_json=request_json,
            report=report,
            sleep=sleep,
            timeout_seconds=args.extraction_timeout_seconds,
        )
        report["ok"] = True
    except DockerProofFailure as exc:
        report["ok"] = False
        report["failure"] = {
            "component": exc.component,
            "reason": exc.reason,
            "message": _safe_text(exc.message, env=env),
            "degraded": exc.degraded,
            **_recovery_policy(status="degraded" if exc.degraded else "failed", reason=exc.reason),
        }
        if exc.diagnostics:
            report["failure"]["diagnostics"] = exc.diagnostics
        _mark_component(
            report,
            exc.component,
            "degraded" if exc.degraded else "failed",
            reason=exc.reason,
            diagnostics=exc.diagnostics,
        )
    finally:
        if stack_started and not args.keep_stack:
            _cleanup_stack(args, project_name, run_cmd=run_cmd, report=report, env=env)
        report["finished_at"] = _utc_now()
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("lite", "full"),
        default=os.environ.get("MEMORY_MULTIMODAL_DOCKER_PROFILE", "lite"),
    )
    parser.add_argument("--compose", default=os.environ.get("COMPOSE", "docker compose"))
    parser.add_argument("--docker", default=os.environ.get("DOCKER", "docker"))
    parser.add_argument("--project-name")
    parser.add_argument("--service-token")
    parser.add_argument("--server-port", type=int)
    parser.add_argument("--postgres-port", type=int)
    parser.add_argument("--qdrant-port", type=int)
    parser.add_argument("--neo4j-http-port", type=int)
    parser.add_argument("--neo4j-bolt-port", type=int)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--keep-stack", action="store_true")
    parser.add_argument("--docker-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--compose-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--startup-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--extraction-timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--report-out",
        default=os.environ.get(
            "MEMORY_MULTIMODAL_DOCKER_PROOF_REPORT_OUT",
            DEFAULT_REPORT,
        ),
    )
    return parser.parse_args(argv)


def _base_report(
    args: argparse.Namespace,
    *,
    project_name: str,
    ports: dict[str, int],
    token: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "suite": SUITE,
        "ok": False,
        "secrets_redacted": True,
        "generated_at": _utc_now(),
        "git": _git_info(),
        "compose": {
            "project_name": project_name,
            "file": COMPOSE_FILE.name,
            "profile": args.profile,
            "build": not args.no_build,
        },
        "network": {
            "server_port": ports["server"],
            "postgres_port": ports["postgres"],
            "qdrant_port": ports["qdrant"],
            "neo4j_http_port": ports["neo4j_http"],
            "neo4j_bolt_port": ports["neo4j_bolt"],
        },
        "credentials": {
            "service_token_configured": bool(token),
            "provider_key_present": bool(
                os.environ.get("MEMORY_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
            ),
        },
        "docker_client": _docker_client_diagnostics(args),
        "components": {
            "docker_daemon": _component("unknown"),
            "compose_config": _component("unknown"),
            "compose_stack": _component("unknown"),
            "container_dependencies": _component("unknown"),
            "health": _component("unknown"),
            "capabilities": _component("unknown"),
            "extraction_flow": _component("unknown"),
            "cleanup": _component("unknown"),
        },
    }


def _prove_docker_daemon(
    args: argparse.Namespace,
    *,
    run_cmd: RunCommand,
    report: dict[str, Any],
    env: dict[str, str],
) -> None:
    diagnostics = _docker_client_diagnostics(args)
    try:
        result = run_cmd([args.docker, "info", "--format", "{{.ServerVersion}}"])
    except subprocess.TimeoutExpired as exc:
        raise DockerProofFailure(
            "docker_daemon",
            "docker_daemon_timeout",
            (
                f"Docker daemon did not answer within {args.docker_timeout_seconds}s; "
                f"{_docker_diagnostic_summary(diagnostics)}"
            ),
            degraded=True,
            diagnostics=diagnostics,
        ) from exc
    except OSError as exc:
        raise DockerProofFailure(
            "docker_daemon",
            "docker_cli_unavailable",
            str(exc),
            degraded=True,
            diagnostics=diagnostics,
        ) from exc
    if result.returncode != 0:
        raise DockerProofFailure(
            "docker_daemon",
            "docker_daemon_unavailable",
            _safe_completed(result, env=env),
            degraded=True,
            diagnostics=diagnostics,
        )
    _mark_component(
        report,
        "docker_daemon",
        "succeeded",
        server_version=result.stdout.strip()[:80],
    )


def _prove_compose_config(
    args: argparse.Namespace,
    project_name: str,
    *,
    run_cmd: RunCommand,
    report: dict[str, Any],
    env: dict[str, str],
) -> None:
    command = [*_compose_base(args, project_name), "config", "--quiet"]
    try:
        result = run_cmd(command)
    except subprocess.TimeoutExpired as exc:
        raise DockerProofFailure(
            "compose_config",
            "compose_config_timeout",
            f"Docker Compose config did not answer within {args.compose_timeout_seconds}s",
            degraded=True,
        ) from exc
    if result.returncode != 0:
        raise DockerProofFailure(
            "compose_config",
            "compose_config_failed",
            _safe_completed(result, env=env),
        )
    _mark_component(report, "compose_config", "succeeded")


def _start_stack(
    args: argparse.Namespace,
    project_name: str,
    *,
    run_cmd: RunCommand,
    report: dict[str, Any],
    env: dict[str, str],
) -> None:
    services = _profile_services(args.profile)
    command = [
        *_compose_base(args, project_name),
        "--profile",
        args.profile,
        "up",
        "-d",
        *(("--build",) if not args.no_build else ()),
        *services,
    ]
    result = run_cmd(command)
    if result.returncode != 0:
        raise DockerProofFailure(
            "compose_stack",
            "compose_up_failed",
            _safe_completed(result, env=env),
        )
    _mark_component(report, "compose_stack", "succeeded", state="running", services=services)


def _prove_container_dependencies(
    args: argparse.Namespace,
    project_name: str,
    *,
    run_cmd: RunCommand,
    report: dict[str, Any],
    env: dict[str, str],
) -> None:
    service = (
        "infinity_context_server_full"
        if args.profile == "full"
        else "infinity_context_server"
    )
    checks = {
        "ffmpeg": "ffmpeg -version | head -n 1",
        "ffprobe": "ffprobe -version | head -n 1",
        "tesseract": "tesseract --version | head -n 1",
        "docling": (
            "python - <<'PY'\n"
            "import importlib.metadata\n"
            "print(importlib.metadata.version('docling'))\n"
            "PY"
        ),
    }
    versions: dict[str, str] = {}
    for name, shell in checks.items():
        result = run_cmd(
            [*_compose_base(args, project_name), "exec", "-T", service, "sh", "-lc", shell]
        )
        if result.returncode != 0:
            raise DockerProofFailure(
                "container_dependencies",
                f"{name}_missing",
                _safe_completed(result, env=env),
            )
        versions[name] = (
            result.stdout.strip().splitlines()[0][:160] if result.stdout.strip() else "ok"
        )
    _mark_component(report, "container_dependencies", "succeeded", versions=versions)


def _wait_for_health(
    base_url: str,
    token: str,
    *,
    request_json: RequestJson,
    report: dict[str, Any],
    sleep: Sleep,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = request_json("GET", f"{base_url}/v1/health")
            if payload.get("status") == "ok":
                _mark_component(
                    report,
                    "health",
                    "succeeded",
                    health_status=payload.get("status"),
                )
                return
        except DockerProofFailure as exc:
            last_error = _safe_text(str(exc), env={"MEMORY_SERVICE_TOKEN": token})
        sleep(1)
    raise DockerProofFailure(
        "health",
        "health_timeout",
        f"Server did not become healthy within {timeout_seconds}s: {last_error}",
    )


def _prove_capabilities(
    base_url: str,
    *,
    request_json: RequestJson,
    report: dict[str, Any],
) -> None:
    payload = request_json("GET", f"{base_url}/v1/capabilities")
    extraction = payload.get("extraction") if isinstance(payload, dict) else None
    if not isinstance(extraction, dict):
        raise DockerProofFailure(
            "capabilities",
            "extraction_contract_missing",
            "Missing extraction capability contract",
        )
    modality_actions = extraction.get("modality_actions")
    providers = extraction.get("providers")
    if not isinstance(modality_actions, dict) or not isinstance(providers, dict):
        raise DockerProofFailure(
            "capabilities",
            "extraction_contract_incomplete",
            "Incomplete extraction capability contract",
        )
    provider_contract = extraction.get("provider_contract")
    if not isinstance(provider_contract, dict):
        raise DockerProofFailure(
            "capabilities",
            "provider_contract_missing",
            "Missing extraction provider capability contract",
        )
    provider_contract_summary = _provider_contract_summary(provider_contract)
    if not provider_contract_summary["ok"]:
        raise DockerProofFailure(
            "capabilities",
            "provider_contract_incomplete",
            "Incomplete extraction provider capability contract",
            diagnostics=provider_contract_summary,
        )
    contract_names = sorted(
        key
        for key in (
            "evidence_contract",
            "feature_contract",
            "provider_contract",
            "manifest_contract",
            "file_type_detection",
        )
        if isinstance(extraction.get(key), dict)
    )
    _mark_component(
        report,
        "capabilities",
        "succeeded",
        modalities=sorted(str(key) for key in modality_actions)[:20],
        provider_names=sorted(str(key) for key in providers)[:20],
        contract_names=contract_names,
        provider_contract=provider_contract_summary,
    )


def _provider_contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    transcription = contract.get("transcription")
    vision = contract.get("vision")
    transcription = transcription if isinstance(transcription, dict) else {}
    vision = vision if isinstance(vision, dict) else {}
    audio_suffixes = _string_list(transcription.get("supported_file_types"))
    vision_suffixes = _string_list(vision.get("supported_file_types"))
    vision_detail_levels = _string_list(vision.get("detail_levels"))
    transcription_max_upload_bytes = _positive_int(
        transcription.get("max_provider_upload_bytes")
    )
    transcription_effective_max_upload_bytes = _positive_int(
        transcription.get("effective_max_upload_bytes")
    )
    vision_max_binary_upload_bytes = _positive_int(
        vision.get("max_provider_binary_upload_bytes")
    )
    vision_max_payload_bytes = _positive_int(vision.get("max_provider_payload_bytes"))
    vision_max_images_per_request = _positive_int(vision.get("max_images_per_request"))
    vision_effective_max_upload_bytes = _positive_int(vision.get("effective_max_upload_bytes"))
    audio_ok = (
        transcription.get("endpoint") == "/v1/audio/transcriptions"
        and transcription_max_upload_bytes == 25 * 1024 * 1024
        and transcription_effective_max_upload_bytes is not None
        and set(audio_suffixes)
        == {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm"}
    )
    vision_ok = (
        vision.get("endpoint_family") == "responses"
        and set(vision_suffixes) == {".gif", ".jpeg", ".jpg", ".png", ".webp"}
        and {"low", "high", "auto"}.issubset(set(vision_detail_levels))
        and set(vision_detail_levels).issubset({"low", "high", "original", "auto"})
        and vision_max_binary_upload_bytes is not None
        and vision_max_payload_bytes is not None
        and vision_max_images_per_request is not None
        and vision_effective_max_upload_bytes is not None
    )
    return {
        "ok": audio_ok and vision_ok and not ({".flac", ".ogg"} & set(audio_suffixes)),
        "transcription_endpoint": transcription.get("endpoint"),
        "transcription_max_provider_upload_bytes": transcription_max_upload_bytes,
        "transcription_effective_max_upload_bytes": transcription_effective_max_upload_bytes,
        "transcription_supported_file_types": audio_suffixes,
        "vision_endpoint_family": vision.get("endpoint_family"),
        "vision_model": vision.get("model"),
        "vision_detail_levels": vision_detail_levels,
        "vision_max_provider_binary_upload_bytes": vision_max_binary_upload_bytes,
        "vision_max_provider_payload_bytes": vision_max_payload_bytes,
        "vision_max_images_per_request": vision_max_images_per_request,
        "vision_effective_max_upload_bytes": vision_effective_max_upload_bytes,
        "vision_supported_file_types": vision_suffixes,
    }


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)][:50]


def _prove_extraction_flow(
    base_url: str,
    *,
    request_json: RequestJson,
    report: dict[str, Any],
    sleep: Sleep,
    timeout_seconds: float,
) -> None:
    marker = f"DOCKER_PROOF_{time.time_ns()}"
    cases = (
        _AssetCase(
            filename="docker-proof.txt",
            content_type="text/plain",
            content=f"{marker} text extraction proof from Docker worker.".encode(),
            expected_artifacts={"extracted_json", "markdown"},
            expected_text=marker,
        ),
        _AssetCase(
            filename="docker-proof.pdf",
            content_type="application/pdf",
            content=_sample_pdf_bytes(f"{marker} document extraction proof from Docker worker"),
            expected_artifacts={"extracted_json", "markdown"},
            expected_text=marker,
        ),
        _AssetCase(
            filename="docker-proof.png",
            content_type="image/png",
            content=_sample_png_bytes(),
            expected_artifacts={"extracted_json", "image_regions", "markdown"},
            expected_text="Image asset evidence",
        ),
        _AssetCase(
            filename="docker-proof.wav",
            content_type="audio/wav",
            content=_sample_wav_bytes(),
            expected_artifacts={"extracted_json", "markdown", "media_manifest"},
            expected_text="Media asset evidence",
        ),
        _AssetCase(
            filename="docker-proof.mp4",
            content_type="video/mp4",
            content=_sample_mp4_bytes(),
            expected_artifacts={
                "extracted_json",
                "keyframe",
                "markdown",
                "media_manifest",
                "video_frame_timeline",
            },
            expected_text="Media asset",
        ),
    )
    completed: list[dict[str, Any]] = []
    for case in cases:
        upload = _upload_asset(base_url, request_json=request_json, case=case)
        extraction_id = str(upload["data"]["extraction"]["id"])
        extraction = _wait_for_extraction(
            base_url,
            extraction_id=extraction_id,
            request_json=request_json,
            sleep=sleep,
            timeout_seconds=timeout_seconds,
        )
        artifacts = {
            str(item.get("artifact_type")) for item in extraction.get("artifacts") or []
        }
        if not case.expected_artifacts.issubset(artifacts):
            message = (
                f"{case.filename} expected artifacts {sorted(case.expected_artifacts)}, "
                f"got {sorted(artifacts)}"
            )
            raise DockerProofFailure(
                "extraction_flow",
                "artifact_contract_mismatch",
                message,
            )
        document_ids = extraction.get("result_document_ids") or []
        if not document_ids:
            raise DockerProofFailure(
                "extraction_flow",
                "document_missing",
                f"{case.filename} did not create a document",
            )
        chunks = request_json("GET", f"{base_url}/v1/documents/{document_ids[0]}/chunks")
        chunk_text = " ".join(str(item.get("text") or "") for item in chunks.get("data") or [])
        if case.expected_text not in chunk_text:
            raise DockerProofFailure(
                "extraction_flow",
                "chunk_text_missing",
                f"{case.filename} expected text was not found in extracted chunks",
            )
        completed.append(
            {
                "filename": case.filename,
                "status": extraction.get("status"),
                "parser_name": extraction.get("parser_name"),
                "artifact_types": sorted(artifacts),
                "document_count": len(document_ids),
            }
        )
    _mark_component(report, "extraction_flow", "succeeded", cases=completed)


def _upload_asset(
    base_url: str,
    *,
    request_json: RequestJson,
    case: _AssetCase,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "space_slug": "docker-proof",
            "memory_scope_external_ref": "multimodal",
            "thread_external_ref": "live-proof",
            "filename": case.filename,
            "extract": "true",
            "estimated_media_seconds": "1",
        }
    )
    return request_json(
        "POST",
        f"{base_url}/v1/assets?{query}",
        content=case.content,
        content_type=case.content_type,
    )


def _wait_for_extraction(
    base_url: str,
    *,
    extraction_id: str,
    request_json: RequestJson,
    sleep: Sleep,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        payload = request_json("GET", f"{base_url}/v1/asset-extractions/{extraction_id}")
        extraction = payload.get("data")
        if not isinstance(extraction, dict):
            raise DockerProofFailure(
                "extraction_flow",
                "extraction_payload_invalid",
                "Extraction response payload is invalid",
            )
        last_status = str(extraction.get("status") or "unknown")
        if last_status == "succeeded":
            return extraction
        if last_status in {"failed", "unsupported", "canceled"}:
            raise DockerProofFailure(
                "extraction_flow",
                f"extraction_{last_status}",
                f"Extraction {extraction_id} reached {last_status}",
            )
        sleep(1)
    raise DockerProofFailure(
        "extraction_flow",
        "extraction_timeout",
        (
            f"Extraction {extraction_id} did not finish within {timeout_seconds}s; "
            f"last_status={last_status}"
        ),
    )


def _cleanup_stack(
    args: argparse.Namespace,
    project_name: str,
    *,
    run_cmd: RunCommand,
    report: dict[str, Any],
    env: dict[str, str],
) -> None:
    result = run_cmd([*_compose_base(args, project_name), "down", "-v", "--remove-orphans"])
    if result.returncode == 0:
        _mark_component(report, "cleanup", "succeeded")
    else:
        _mark_component(
            report,
            "cleanup",
            "failed",
            reason="compose_down_failed",
            message=_safe_completed(result, env=env),
        )


@dataclass(frozen=True)
class _AssetCase:
    filename: str
    content_type: str
    content: bytes
    expected_artifacts: set[str]
    expected_text: str


def _command_runner(args: argparse.Namespace, *, env: dict[str, str]) -> RunCommand:
    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        timeout = (
            args.docker_timeout_seconds
            if command[:2] == [args.docker, "info"]
            else args.compose_timeout_seconds
        )
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    return run


def _request_json_factory(token: str) -> RequestJson:
    def request_json(
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            url,
            data=content,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise DockerProofFailure(
                "extraction_flow",
                "http_error",
                f"HTTP {exc.code}: {body}",
            ) from exc
        except urllib.error.URLError as exc:
            raise DockerProofFailure("health", "http_unavailable", str(exc.reason)) from exc
        return json.loads(raw.decode("utf-8"))

    return request_json


def _compose_base(args: argparse.Namespace, project_name: str) -> list[str]:
    return [*shlex.split(args.compose), "-p", project_name, "-f", str(COMPOSE_FILE)]


def _profile_services(profile: str) -> tuple[str, ...]:
    if profile == "full":
        return (
            "infinity_context_server_full",
            "infinity_context_worker_full",
            "infinity_context_extraction_worker_full",
        )
    return (
        "infinity_context_server",
        "infinity_context_worker",
        "infinity_context_extraction_worker",
    )


def _compose_env(args: argparse.Namespace, *, ports: dict[str, int], token: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_SERVICE_TOKEN": token,
            "MEMORY_SERVER_PORT": str(ports["server"]),
            "MEMORY_POSTGRES_PORT": str(ports["postgres"]),
            "MEMORY_QDRANT_PORT": str(ports["qdrant"]),
            "MEMORY_NEO4J_HTTP_PORT": str(ports["neo4j_http"]),
            "MEMORY_NEO4J_BOLT_PORT": str(ports["neo4j_bolt"]),
            "MEMORY_DEFAULT_SPACE_SLUG": "docker-proof",
            "MEMORY_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "multimodal",
            "MEMORY_EXTRACTION_DEFAULT_PROFILE": "standard_local",
            "MEMORY_TRANSCRIPTION_PROVIDER": "disabled"
            if args.profile == "lite"
            else os.environ.get("MEMORY_TRANSCRIPTION_PROVIDER", "openai"),
        }
    )
    return env


def _ports(args: argparse.Namespace) -> dict[str, int]:
    return {
        "server": args.server_port or _free_port(),
        "postgres": args.postgres_port or _free_port(),
        "qdrant": args.qdrant_port or _free_port(),
        "neo4j_http": args.neo4j_http_port or _free_port(),
        "neo4j_bolt": args.neo4j_bolt_port or _free_port(),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _component(status: str, **values: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status}
    payload.update({key: value for key, value in values.items() if value is not None})
    reason = payload.get("reason")
    payload.update(
        _recovery_policy(
            status=status,
            reason=reason if isinstance(reason, str) else None,
        )
    )
    return payload


def _docker_client_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    docker_cmd = _first_command_token(args.docker)
    compose_cmd = _first_command_token(args.compose)
    docker_host = os.environ.get("DOCKER_HOST") or ""
    return {
        "docker_cli": _cli_diagnostic(docker_cmd),
        "compose_cli": _cli_diagnostic(compose_cmd),
        "docker_context": _safe_diagnostic_value(os.environ.get("DOCKER_CONTEXT")),
        "docker_context_current": _safe_diagnostic_value(_docker_context_show(args.docker)),
        "docker_host": _docker_host_diagnostic(docker_host),
        "known_sockets": {
            "var_run": _socket_status(Path("/var/run/docker.sock")),
            "desktop": _socket_status(Path.home() / ".docker/run/docker.sock"),
        },
        "timeouts": {
            "docker_seconds": args.docker_timeout_seconds,
            "compose_seconds": args.compose_timeout_seconds,
        },
    }


def _first_command_token(value: str) -> str:
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = []
    return parts[0] if parts else value


def _cli_diagnostic(command: str) -> dict[str, Any]:
    resolved = shutil.which(command)
    return {
        "command": Path(command).name,
        "found": bool(resolved or Path(command).exists()),
    }


def _docker_context_show(docker_command: str) -> str | None:
    try:
        command = [*shlex.split(docker_command), "context", "show"]
    except ValueError:
        return None
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _docker_host_diagnostic(value: str) -> dict[str, Any]:
    if not value:
        return {"configured": False}
    lowered = value.lower()
    if lowered.startswith("unix://"):
        return {
            "configured": True,
            "kind": "unix",
            "socket": _socket_status(Path(value.removeprefix("unix://"))),
        }
    if lowered.startswith("tcp://"):
        return {"configured": True, "kind": "tcp"}
    if lowered.startswith("npipe://"):
        return {"configured": True, "kind": "npipe"}
    return {"configured": True, "kind": "other"}


def _socket_status(path: Path) -> dict[str, Any]:
    try:
        file_stat = path.stat()
    except OSError:
        return {
            "exists": False,
            "is_socket": False,
            "is_symlink": path.is_symlink(),
        }
    return {
        "exists": True,
        "is_socket": stat.S_ISSOCK(file_stat.st_mode),
        "is_symlink": path.is_symlink(),
    }


def _docker_diagnostic_summary(diagnostics: dict[str, Any]) -> str:
    known_sockets = diagnostics.get("known_sockets")
    socket_status = known_sockets if isinstance(known_sockets, dict) else {}
    var_run = socket_status.get("var_run") if isinstance(socket_status.get("var_run"), dict) else {}
    desktop = socket_status.get("desktop") if isinstance(socket_status.get("desktop"), dict) else {}
    docker_host = diagnostics.get("docker_host")
    docker_host_configured = (
        docker_host.get("configured") if isinstance(docker_host, dict) else False
    )
    docker_context = diagnostics.get("docker_context") or diagnostics.get(
        "docker_context_current"
    )
    return (
        f"docker_context_configured={bool(docker_context)}; "
        f"docker_host_configured={bool(docker_host_configured)}; "
        f"var_run_socket_exists={bool(var_run.get('exists'))}; "
        f"desktop_socket_exists={bool(desktop.get('exists'))}"
    )


def _safe_diagnostic_value(value: str | None) -> str | None:
    if not value:
        return None
    return value[:80]


def _mark_component(report: dict[str, Any], name: str, status: str, **values: Any) -> None:
    report["components"][name] = _component(status, **values)


def _recovery_policy(*, status: str, reason: str | None) -> dict[str, Any]:
    if status in {"running", "succeeded", "unknown"}:
        return {}
    normalized = (reason or status).strip().lower()
    if normalized in {"docker_daemon_timeout", "docker_daemon_unavailable"}:
        return {
            "user_retryable": True,
            "operator_action": "start_or_restart_docker_daemon",
        }
    if normalized == "docker_cli_unavailable":
        return {
            "user_retryable": False,
            "operator_action": "install_docker_cli",
        }
    if "compose" in normalized:
        return {
            "user_retryable": False,
            "operator_action": "inspect_compose_stack",
        }
    if "health" in normalized or "startup" in normalized:
        return {
            "user_retryable": True,
            "operator_action": "inspect_service_logs",
        }
    if "extraction_timeout" in normalized:
        return {
            "user_retryable": True,
            "operator_action": "inspect_worker_logs",
        }
    if "extraction_" in normalized:
        return {
            "user_retryable": False,
            "operator_action": "inspect_extraction_diagnostics",
        }
    return {
        "user_retryable": False,
        "operator_action": "inspect_docker_proof",
    }


def _safe_completed(result: subprocess.CompletedProcess[str], *, env: dict[str, str]) -> str:
    text = (
        f"exit_code={result.returncode}\n"
        f"stdout:\n{result.stdout[-2000:]}\n"
        f"stderr:\n{result.stderr[-2000:]}"
    )
    return _safe_text(text, env=env)


def _safe_text(value: str, *, env: dict[str, str]) -> str:
    redacted = value.replace(str(ROOT), "<project_root>")
    for key, secret in env.items():
        if not secret or len(secret) < 4:
            continue
        normalized = key.lower()
        sensitive_markers = ("token", "secret", "password", "api_key", "key")
        if any(marker in normalized for marker in sensitive_markers):
            redacted = redacted.replace(secret, "<redacted>")
    return redacted[:4000]


def _write_report(report: dict[str, Any], report_out: str | None) -> None:
    if not report_out:
        return
    path = Path(report_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_info() -> dict[str, Any]:
    return {
        "commit": _git_output("rev-parse", "HEAD"),
        "short_commit": _git_output("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git_output("status", "--short")),
    }


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sample_wav_bytes() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000)
    return output.getvalue()


def _sample_pdf_bytes(text: str) -> bytes:
    safe_text = "".join(ch if ch.isalnum() or ch in " ._-" else " " for ch in text)
    stream = f"BT /F1 18 Tf 72 720 Td ({safe_text}) Tj ET".encode("latin-1")
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


def _sample_mp4_bytes() -> bytes:
    return base64.b64decode(
        "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAABB1tZGF0AAACrgYF//+q3EXpvebZSLeW"
        "LNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENv"
        "cHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNh"
        "YmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBw"
        "c3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhk"
        "Y3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRz"
        "PTEgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2Vk"
        "PTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRh"
        "cHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBr"
        "ZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1i"
        "dHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQw"
        "IGFxPTE6MS4wMACAAAAAFGWIhAA7//73Tr8Cm1TCKgNYle7xAAAACUGaJGxDv/6rgAAAAAhBnkJ4hf9VwQAAAAgB"
        "nmF0Qr9awAAAAAgBnmNqQr9awQAAAA9BmmhJqEFomUwId//+q4EAAAAKQZ6GRREsL/9VwQAAAAgBnqV0Qr9awQAA"
        "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"
    )


def _sample_png_bytes() -> bytes:
    width = 120
    height = 48
    pixels = bytearray([255, 255, 255] * width * height)
    for y in range(12, 36):
        for x in range(16, 104):
            if (x + y) % 9 == 0 or y in {12, 35} or x in {16, 103}:
                index = (y * width + x) * 3
                pixels[index : index + 3] = b"\x10\x10\x10"
    return _encode_png(width, height, bytes(pixels))


def _encode_png(width: int, height: int, rgb: bytes) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    rows = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return b"".join(
        (
            signature,
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(rows, 9)),
            _png_chunk(b"IEND", b""),
        )
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


if __name__ == "__main__":
    sys.exit(main())
