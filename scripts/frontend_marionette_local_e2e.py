#!/usr/bin/env python3
"""Run the Flutter Marionette memory flow against a local server and worker."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SUITE = "memo-stack-frontend-marionette-local-e2e"
MAX_RUNTIME_LOG_MARKERS = 12
MAX_RUNTIME_LOG_SNIPPET_CHARS = 240
FLUTTER_RUNTIME_ERROR_MARKERS = (
    "EXCEPTION CAUGHT BY",
    "Another exception was thrown",
    "RenderFlex overflowed",
    "A RenderFlex overflowed",
    "Codec failed to produce an image",
    "[ERROR:flutter/runtime",
    "Unhandled Exception",
)


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    frontend_dir = (root / args.frontend_dir).resolve()
    python_bin = _resolve_python(args.python, root=root)
    flutter_bin = _resolve_flutter(args.flutter)
    dart_bin = _resolve_dart(flutter_bin)
    run_id = str(int(time.time() * 1000))
    scope_ref = args.scope_ref or f"marionette-local-proof-{run_id}"
    report = _base_report(
        args,
        root=root,
        frontend_dir=frontend_dir,
        scope_ref=scope_ref,
        run_id=run_id,
    )
    exit_code = 1

    tmp_ctx = tempfile.TemporaryDirectory(prefix="memo-stack-marionette.")
    tmp_root = Path(tmp_ctx.name)
    flow_report_path = tmp_root / "marionette-flow-report.json"
    processes: list[subprocess.Popen[bytes]] = []
    try:
        server_env = _server_env(
            tmp_root=tmp_root,
            host=args.host,
            port=args.port,
            service_token=args.service_token,
        )
        server = _start(
            [str(python_bin), "-m", "memo_stack_server.main"],
            cwd=root,
            env=server_env,
        )
        processes.append(server)
        _wait_for_health(
            f"http://{args.host}:{args.port}/healthz",
            server,
            timeout_seconds=args.server_startup_timeout,
        )
        report["components"]["server"] = _component("succeeded")

        worker = _start(
            [
                str(python_bin),
                "-m",
                "memo_stack_server.worker",
                "--loop",
                "--role",
                "all",
                "--sleep-seconds",
                "1",
                "--limit",
                "10",
            ],
            cwd=root,
            env=server_env,
        )
        processes.append(worker)
        report["components"]["worker"] = _component("running")

        marionette_env = os.environ.copy()
        marionette_env.update(
            {
                "FLUTTER_BIN": str(flutter_bin),
                "MEMO_STACK_BACKEND_HOST": args.host,
                "MEMO_STACK_BACKEND_PORT": str(args.port),
                "MEMO_STACK_SERVICE_TOKEN": args.service_token,
                "MEMO_STACK_SPACE_SLUG": args.space_slug,
                "MEMO_STACK_MEMORY_SCOPE_EXTERNAL_REF": scope_ref,
                "MEMO_STACK_E2E_STARTUP_TIMEOUT": str(args.flutter_startup_timeout),
                "MEMO_STACK_E2E_CALL_TIMEOUT": str(args.call_timeout),
                "MEMO_STACK_E2E_DEVICE": args.device,
                "MEMO_STACK_E2E_RUN_ID": run_id,
                "MEMO_STACK_E2E_FLOW_REPORT_OUT": str(flow_report_path),
            }
        )
        marionette_exit_code, runtime_log = _run_streaming_process_and_collect_runtime_log(
            [str(dart_bin), "run", "tool/marionette_anchor_lifecycle_e2e.dart"],
            cwd=frontend_dir,
            env=marionette_env,
        )
        report["components"]["flutter_runtime_log"] = runtime_log
        report["components"]["flutter_marionette"] = _component(
            "succeeded" if marionette_exit_code == 0 else "failed",
            exit_code=marionette_exit_code,
        )
        runtime_ok = runtime_log.get("status") == "succeeded"
        exit_code = marionette_exit_code if marionette_exit_code != 0 else (0 if runtime_ok else 1)
        if exit_code == 0:
            report["components"]["worker"] = _component("succeeded")
        report["ok"] = marionette_exit_code == 0 and runtime_ok
        return exit_code
    except Exception as exc:
        report["ok"] = False
        report["failure"] = {
            "type": exc.__class__.__name__,
            "message": str(exc)[:240],
        }
        _mark_unknown_components_failed(report, exc)
        raise
    finally:
        _stop_processes(reversed(processes))
        report["exit_code"] = exit_code
        report["finished_at"] = _utc_now()
        _attach_flow_report(report, flow_report_path)
        _write_report(report, args.report_out)
        if args.keep_temp:
            print(f"kept temp dir: {tmp_root}", file=sys.stderr)
        else:
            tmp_ctx.cleanup()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Memo Stack frontend Marionette E2E with local server and worker."
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--flutter", default=os.environ.get("FLUTTER", "flutter"))
    parser.add_argument("--frontend-dir", default="frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17789)
    parser.add_argument("--service-token", default="local-dev-token")
    parser.add_argument("--space-slug", default="marionette-local-proof")
    parser.add_argument("--scope-ref")
    parser.add_argument("--device", default="macos")
    parser.add_argument("--server-startup-timeout", type=int, default=90)
    parser.add_argument("--flutter-startup-timeout", type=int, default=180)
    parser.add_argument("--call-timeout", type=int, default=45)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument(
        "--report-out",
        default=os.environ.get("MEMORY_FRONTEND_MARIONETTE_REPORT_OUT"),
        help="Optional path for the JSON local Marionette proof report.",
    )
    return parser.parse_args()


def _base_report(
    args: argparse.Namespace,
    *,
    root: Path,
    frontend_dir: Path,
    scope_ref: str,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite": SUITE,
        "ok": False,
        "secrets_redacted": True,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "git": _git_info(root),
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "frontend": {
            "dir_name": frontend_dir.name,
            "device": args.device,
        },
        "backend": {
            "host": args.host,
            "port": args.port,
            "profile": "test",
            "database": "sqlite",
        },
        "scope": {
            "space_slug": args.space_slug,
            "memory_scope_external_ref": scope_ref,
        },
        "components": {
            "server": _component("unknown"),
            "worker": _component("unknown"),
            "flutter_marionette": _component("unknown"),
            "flutter_runtime_log": _component("unknown"),
        },
    }


def _component(status: str, **values: object) -> dict[str, object]:
    component: dict[str, object] = {"status": status}
    for key, value in values.items():
        if value is not None:
            component[key] = value
    return component


def _write_report(report: dict[str, object], report_out: str | None) -> None:
    if not report_out:
        return
    path = Path(report_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _attach_flow_report(report: dict[str, object], flow_report_path: Path) -> None:
    if not flow_report_path.exists():
        report["flow_coverage"] = _component("missing")
        return
    try:
        payload = json.loads(flow_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["flow_coverage"] = _component(
            "invalid",
            reason=exc.__class__.__name__,
        )
        return
    if not isinstance(payload, dict):
        report["flow_coverage"] = _component("invalid", reason="not_object")
        return
    safe_payload: dict[str, object] = {}
    for key in (
        "schema_version",
        "status",
        "run_marker",
        "completed_flow_count",
        "completed_flows",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, bool)) or value is None:
            safe_payload[key] = value
        elif isinstance(value, list):
            safe_payload[key] = [str(item)[:120] for item in value[:50]]
    report["flow_coverage"] = safe_payload


def _mark_unknown_components_failed(report: dict[str, object], exc: Exception) -> None:
    components = report.get("components")
    if not isinstance(components, dict):
        return
    for value in components.values():
        if not isinstance(value, dict) or value.get("status") != "unknown":
            continue
        value["status"] = "failed"
        value["reason"] = exc.__class__.__name__


def _run_streaming_process_and_collect_runtime_log(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> tuple[int, dict[str, object]]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    markers: list[dict[str, str]] = []
    if process.stdout is not None:
        for line in process.stdout:
            print(line, end="")
            _collect_flutter_runtime_marker(line, markers)
    return int(process.wait()), _flutter_runtime_log_component(markers)


def _collect_flutter_runtime_marker(line: str, markers: list[dict[str, str]]) -> None:
    if len(markers) >= MAX_RUNTIME_LOG_MARKERS:
        return
    lowered = line.lower()
    for marker in FLUTTER_RUNTIME_ERROR_MARKERS:
        if marker.lower() not in lowered:
            continue
        markers.append(
            {
                "marker": marker,
                "snippet": _safe_log_snippet(line),
            }
        )
        return


def _flutter_runtime_log_component(markers: list[dict[str, str]]) -> dict[str, object]:
    return _component(
        "succeeded" if not markers else "failed",
        forbidden_marker_count=len(markers),
        markers=markers,
    )


def _safe_log_snippet(line: str) -> str:
    snippet = line.replace("\r", "").strip()
    snippet = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", snippet)
    snippet = re.sub(r"sk-[A-Za-z0-9_-]{6,}", "sk-<redacted>", snippet)
    return snippet[:MAX_RUNTIME_LOG_SNIPPET_CHARS]


def _git_info(root: Path) -> dict[str, object]:
    commit = _git_output(root, "rev-parse", "HEAD")
    short_commit = _git_output(root, "rev-parse", "--short", "HEAD")
    dirty = _git_output(root, "status", "--short")
    return {
        "commit": commit,
        "short_commit": short_commit,
        "dirty": bool(dirty),
    }


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
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


def _server_env(
    *,
    tmp_root: Path,
    host: str,
    port: int,
    service_token: str,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_DEPLOY_PROFILE": "test",
            "MEMORY_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_root / 'memory.db'}",
            "MEMORY_AUTO_CREATE_SCHEMA": "true",
            "MEMORY_HOST": host,
            "MEMORY_PORT": str(port),
            "MEMORY_SERVICE_TOKEN": service_token,
            "MEMORY_CAPTURE_MODE": "suggest",
            "MEMORY_QDRANT_ENABLED": "false",
            "MEMORY_GRAPHITI_ENABLED": "false",
            "MEMORY_EMBEDDINGS_ENABLED": "false",
            "MEMORY_ASSET_STORAGE_DIR": str(tmp_root / "assets"),
        }
    )
    return env


def _resolve_flutter(value: str) -> Path:
    candidates = [
        value,
        str(Path.home() / "dev/flutter/bin/flutter"),
        str(Path.home() / "dev/projects/flutter/bin/flutter"),
    ]
    for candidate in candidates:
        resolved = shutil.which(candidate) if os.path.sep not in candidate else candidate
        if resolved and Path(resolved).exists():
            return Path(resolved).resolve()
    return Path(value)


def _resolve_python(value: str, *, root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def _resolve_dart(flutter_bin: Path) -> Path:
    adjacent = flutter_bin.parent / "dart"
    if adjacent.exists():
        return adjacent.resolve()
    dart = shutil.which("dart")
    if dart:
        return Path(dart).resolve()
    return Path("dart")


def _start(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    print(f"starting: {' '.join(command)}", file=sys.stderr)
    return subprocess.Popen(command, cwd=cwd, env=env)


def _wait_for_health(url: str, process: subprocess.Popen[bytes], *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before health check: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"server health check timed out: {url}; last_error={last_error}")


def _stop_processes(processes) -> None:
    for process in processes:
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
