#!/usr/bin/env python3
"""Smoke test a self-hosted Infinity Context compose deployment."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from scripts.clean_full_smoke_redaction import redact_text
except ModuleNotFoundError:
    from clean_full_smoke_redaction import redact_text

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.selfhost.yml"
DEFAULT_ENV_FILE = ROOT / ".env.selfhost"
PLACEHOLDER_PREFIX = "change-me"
SERVICE_TOKEN_ENV = "MEMORY_SERVICE_TOKEN"
SELFHOST_SECRET_ENVS = (
    "INFINITY_CONTEXT_SELFHOST_ADMIN_PASSWORD",
    "INFINITY_CONTEXT_SELFHOST_MIGRATOR_PASSWORD",
    "INFINITY_CONTEXT_SELFHOST_RUNTIME_PASSWORD",
    "INFINITY_CONTEXT_SELFHOST_CANONICAL_WRITER_PASSWORD",
    "INFINITY_CONTEXT_SELFHOST_REGISTRAR_PASSWORD",
    "INFINITY_CONTEXT_SELFHOST_SEALER_PASSWORD",
)
REQUIRED_SECRET_ENVS = (SERVICE_TOKEN_ENV, *SELFHOST_SECRET_ENVS)


class SmokeFailure(RuntimeError):
    pass


def main() -> int:
    args = _parse_args()
    env_file = args.env_file.resolve()
    env_values = _read_env_file(env_file)
    _validate_env(env_file, env_values)
    if args.validate_env_only:
        return 0

    compose = _compose_base_command(args.compose, env_file)
    if args.full:
        compose.extend(["--profile", "full"])

    env = os.environ.copy()
    env.update(env_values)

    try:
        _run([*compose, "up", "-d", "--build"], env=env, timeout=args.compose_timeout)
        base_url = _base_url(args, env_values)
        token = env_values[SERVICE_TOKEN_ENV]
        _wait_for_health(base_url, token, timeout_seconds=args.timeout_seconds)
        _verify_extraction_flow(base_url, token, timeout_seconds=args.timeout_seconds)
    finally:
        if not args.keep_stack:
            _run([*compose, "down"], env=env, timeout=args.compose_timeout, check=False)

    print(json.dumps({"status": "ok", "base_url": base_url}, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Self-host env file. Defaults to .env.selfhost.",
    )
    parser.add_argument(
        "--compose",
        default=os.environ.get("COMPOSE", "docker compose"),
        help="Compose command, for example 'docker compose'.",
    )
    parser.add_argument("--full", action="store_true", help="Include the full provider profile.")
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Do not run compose down after the smoke.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--compose-timeout", type=float, default=600.0)
    parser.add_argument("--base-url", default="")
    parser.add_argument(
        "--validate-env-only",
        action="store_true",
        help="Validate required self-host secrets without starting Compose.",
    )
    return parser.parse_args()


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SmokeFailure(f"Missing env file: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _validate_env(path: Path, values: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_SECRET_ENVS if not values.get(key)]
    if missing:
        raise SmokeFailure(f"{path} is missing required values: {', '.join(missing)}")
    placeholders = [
        key for key in REQUIRED_SECRET_ENVS if values[key].startswith(PLACEHOLDER_PREFIX)
    ]
    if placeholders:
        raise SmokeFailure(f"Replace placeholder values in {path}: {', '.join(placeholders)}")
    secrets = [values[key] for key in REQUIRED_SECRET_ENVS]
    if len(set(secrets)) != len(secrets):
        raise SmokeFailure("Self-host secrets must contain seven distinct values")


def _compose_base_command(compose: str, env_file: Path) -> list[str]:
    return [
        *shlex.split(compose),
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE_FILE),
    ]


def _base_url(args: argparse.Namespace, env_values: dict[str, str]) -> str:
    if args.base_url:
        return args.base_url.rstrip("/")
    port = env_values.get("MEMORY_SERVER_PORT") or "7788"
    return f"http://127.0.0.1:{port}"


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and process.returncode != 0:
        raise SmokeFailure(
            _redact_text(
                "Command failed: "
                + shlex.join(command)
                + f"\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}",
                env=env,
            )
        )
    return process


def _wait_for_health(base_url: str, token: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = _request_json(
                "GET",
                f"{base_url}/v1/health",
                token=token,
                timeout=5,
            )
            if response.get("status") == "ok":
                return
        except Exception as exc:  # noqa: BLE001 - keep smoke diagnostics compact.
            last_error = _redact_text(str(exc), env={"MEMORY_SERVICE_TOKEN": token})
        time.sleep(1)
    raise SmokeFailure(f"Health check did not pass within {timeout_seconds}s: {last_error}")


def _verify_extraction_flow(base_url: str, token: str, *, timeout_seconds: float) -> None:
    marker = f"SELFHOST_SMOKE_{time.time_ns()}"
    query = urllib.parse.urlencode(
        {
            "space_slug": "selfhost-smoke",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "smoke",
            "filename": "selfhost-smoke.txt",
            "extract": "true",
        }
    )
    upload = _request_json(
        "POST",
        f"{base_url}/v1/assets?{query}",
        token=token,
        body=(
            f"{marker}: self-hosted extraction worker should ingest this text into document chunks."
        ).encode(),
        content_type="text/plain",
        timeout=10,
    )
    extraction_id = upload["data"]["extraction"]["id"]

    extraction = _wait_for_extraction(
        base_url,
        token,
        extraction_id=extraction_id,
        marker=marker,
        timeout_seconds=timeout_seconds,
    )
    document_ids = extraction.get("result_document_ids") or []
    if len(document_ids) != 1:
        raise SmokeFailure(f"Expected one extracted document, got {document_ids!r}")
    chunks = _request_json(
        "GET",
        f"{base_url}/v1/documents/{document_ids[0]}/chunks",
        token=token,
        timeout=10,
    )
    chunk_text = " ".join(str(item.get("text") or "") for item in chunks.get("data") or [])
    if marker not in chunk_text:
        raise SmokeFailure("Extracted document chunks did not contain the smoke marker")


def _wait_for_extraction(
    base_url: str,
    token: str,
    *,
    extraction_id: str,
    marker: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        response = _request_json(
            "GET",
            f"{base_url}/v1/asset-extractions/{extraction_id}",
            token=token,
            timeout=10,
        )
        data = response["data"]
        last_status = str(data.get("status"))
        if last_status == "succeeded":
            return data
        if last_status in {"failed", "unsupported"}:
            raise SmokeFailure(
                f"Extraction {extraction_id} ended with {last_status} for {marker}: {data}"
            )
        time.sleep(1)
    raise SmokeFailure(
        f"Extraction {extraction_id} did not succeed within {timeout_seconds}s; "
        f"last status: {last_status}"
    )


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        safe_raw = _redact_text(raw, env={"MEMORY_SERVICE_TOKEN": token})
        raise SmokeFailure(f"{method} {url} failed with HTTP {exc.code}: {safe_raw}") from exc
    return json.loads(payload.decode("utf-8"))


def _redact_text(text: str, *, env: dict[str, str] | None = None) -> str:
    return redact_text(text, env=env or os.environ)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(
            json.dumps(
                {"status": "failed", "error": _redact_text(str(exc))},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
