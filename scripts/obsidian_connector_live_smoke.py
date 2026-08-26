"""Live E2E smoke for the Infinity Context Obsidian connector.

This starts a real FastAPI server over a temporary SQLite database, creates a
temporary Obsidian-style vault folder, then drives the connector through its CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from multiprocessing import Process
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app

TOKEN = "obsidian-e2e-token"
SPACE = "obsidian-e2e"
PROFILE = "default"
PLUGIN_ID = "infinity-context"
TEXT_START = "<!-- infinity-context-managed:fact-text:start -->"
TEXT_END = "<!-- infinity-context-managed:fact-text:end -->"


def main() -> int:
    args = parse_args()
    root = args.work_dir or Path(tempfile.mkdtemp(prefix="infinity-context-obsidian-e2e-"))
    root.mkdir(parents=True, exist_ok=True)
    vault = root / "Vault"
    vault.mkdir(exist_ok=True)
    db_path = root / "memory.db"
    port = args.port or free_port()
    base_url = f"http://127.0.0.1:{port}"

    server = Process(target=run_server, args=(db_path, port), daemon=True)
    server.start()
    try:
        wait_for_health(base_url)
        fact = create_fact(base_url)

        connect = run_connector(root, vault, base_url, "connect")
        assert_true(connect["ok"] is True, "connect should succeed")
        assert_true((vault / "Infinity Context/README.md").exists(), "connect should write README")

        preview = run_connector(root, vault, base_url, "preview")
        assert_true(preview["export"]["would_export"] >= 1, "preview should see backend fact")

        first_sync = run_connector(root, vault, base_url, "sync", "--apply-import")
        assert_true(first_sync["ok"] is True, "first sync should succeed")
        assert_true(first_sync["export"]["exported"] >= 1, "first sync should export fact")

        fact_file = only_fact_file(vault)
        fact_text = fact_file.read_text(encoding="utf-8")
        assert_true(fact["text"] in fact_text, "exported note should contain backend fact")

        replace_managed_text(fact_file, "Obsidian E2E updated from markdown.")
        second_sync = run_connector(root, vault, base_url, "sync", "--apply-import")
        assert_true(second_sync["ok"] is True, "second sync should succeed")
        assert_true(second_sync["import"]["updated"] == 1, "second sync should import edit")

        updated_fact = get_fact(base_url, fact["id"])
        assert_true(
            updated_fact["text"] == "Obsidian E2E updated from markdown.",
            "backend fact should reflect Obsidian markdown edit",
        )
        assert_true(updated_fact["version"] == 2, "backend fact version should increment")

        write_inbox_note(vault, "Obsidian E2E inbox suggestion marker.")
        third_sync = run_connector(root, vault, base_url, "sync", "--apply-import")
        assert_true(third_sync["ok"] is True, "third sync should succeed")
        assert_true(third_sync["import"]["suggested"] == 1, "inbox should create suggestion")

        fourth_sync = run_connector(root, vault, base_url, "sync", "--apply-import")
        assert_true(fourth_sync["ok"] is True, "repeat sync should succeed")
        assert_true(
            fourth_sync["import"]["suggested"] == 0,
            "repeat sync should not duplicate unchanged inbox suggestion",
        )

        suggestions = list_suggestions(base_url)
        matching = [
            item
            for item in suggestions
            if "Obsidian E2E inbox suggestion marker." in item["candidate_text"]
        ]
        assert_true(len(matching) == 1, "backend should contain exactly one inbox suggestion")

        fact_file.unlink()
        recreate_sync = run_connector(root, vault, base_url, "sync", "--apply-import")
        assert_true(recreate_sync["ok"] is True, "sync should recreate deleted fact note")
        fact_file = only_fact_file(vault)
        assert_true(
            "Obsidian E2E updated from markdown." in fact_file.read_text(encoding="utf-8"),
            "recreated fact note should contain current backend text",
        )

        backend_side = update_fact(
            base_url,
            fact["id"],
            expected_version=updated_fact["version"],
            text="Backend side update before stale markdown.",
        )
        replace_managed_text(fact_file, "Obsidian E2E stale local edit.")
        stale_exit, stale_payload = run_connector_with_exit(
            root,
            vault,
            base_url,
            "sync",
            "--apply-import",
        )
        assert_true(stale_exit == 1, "stale local edit should make sync exit nonzero")
        assert_true(
            stale_payload["import"]["conflicts"] == 1,
            "stale local edit should report import conflict",
        )
        assert_true(
            stale_payload["export_skipped"] is True,
            "sync should skip export while import conflict exists",
        )
        assert_true(
            stale_payload["import"]["conflict_artifacts_written"] >= 1,
            "stale conflict should write visible artifact",
        )
        assert_true(
            any(
                (vault / path).exists()
                for path in stale_payload["import"]["conflict_artifacts"]
            ),
            "stale conflict artifact path should exist in vault",
        )
        stale_note_text = fact_file.read_text(encoding="utf-8")
        assert_true(
            "Obsidian E2E stale local edit." in stale_note_text,
            "stale local edit should remain in vault for review",
        )
        assert_true(
            "Backend side update before stale markdown." not in stale_note_text,
            "conflict path must not overwrite stale local edit",
        )
        after_conflict = get_fact(base_url, fact["id"])
        assert_true(
            after_conflict["text"] == backend_side["text"],
            "stale local edit must not overwrite backend fact",
        )

        plugin_install = install_plugin(root, vault, base_url)
        assert_true(plugin_install["enabled"] is True, "plugin should be enabled in vault")
        assert_true(
            (vault / ".obsidian/plugins/infinity-context/main.js").exists(),
            "plugin bundle should be installable into the vault",
        )
        enabled_plugins = json.loads(
            (vault / ".obsidian/community-plugins.json").read_text(encoding="utf-8")
        )
        assert_true(PLUGIN_ID in enabled_plugins, "plugin id should be enabled")

        doctor = run_connector(root, vault, base_url, "doctor")
        assert_true(doctor["ok"] is True, "doctor should report ready integration")

        report = {
            "ok": True,
            "base_url": base_url,
            "vault": str(vault),
            "db": str(db_path),
            "fact_id": fact["id"],
            "updated_fact_version": after_conflict["version"],
            "suggestions_matching_marker": len(matching),
            "deleted_note_recreated": True,
            "stale_conflict_artifacts_written": stale_payload["import"][
                "conflict_artifacts_written"
            ],
            "doctor_ok": doctor["ok"],
            "plugin_install_dir": str(vault / ".obsidian/plugins/infinity-context"),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        server.terminate()
        server.join(timeout=5)
        if not args.keep and args.work_dir is None:
            shutil.rmtree(root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--keep", action="store_true")
    return parser.parse_args()


def run_server(db_path: Path, port: int) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            auto_create_schema=True,
            host="127.0.0.1",
            port=port,
            service_token=TOKEN,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            ui_enabled=False,
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/v1/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"Infinity Context server did not become healthy at {base_url}")


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def create_fact(base_url: str) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url}/v1/facts",
        headers=headers(),
        json={
            "space_slug": SPACE,
            "memory_scope_external_ref": PROFILE,
            "text": "Obsidian E2E initial fact.",
            "kind": "note",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_id": "obsidian-e2e-seed",
                    "quote_preview": "Obsidian E2E initial fact.",
                }
            ],
        },
        timeout=5,
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def get_fact(base_url: str, fact_id: str) -> dict[str, Any]:
    response = httpx.get(f"{base_url}/v1/facts/{fact_id}", headers=headers(), timeout=5)
    response.raise_for_status()
    return dict(response.json()["data"])


def update_fact(
    base_url: str,
    fact_id: str,
    *,
    expected_version: int,
    text: str,
) -> dict[str, Any]:
    response = httpx.patch(
        f"{base_url}/v1/facts/{fact_id}",
        headers=headers(),
        json={
            "expected_version": expected_version,
            "text": text,
            "reason": "Obsidian live smoke backend-side update",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_id": "obsidian-e2e-backend-update",
                    "quote_preview": text,
                }
            ],
        },
        timeout=5,
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def list_suggestions(base_url: str) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{base_url}/v1/suggestions",
        headers=headers(),
        params={
            "space_slug": SPACE,
            "memory_scope_external_ref": PROFILE,
            "status": "pending",
        },
        timeout=5,
    )
    response.raise_for_status()
    return [dict(item) for item in response.json()["data"]]


def run_connector(
    root: Path,
    vault: Path,
    base_url: str,
    command: str,
    *extra_args: str,
) -> dict[str, Any]:
    returncode, payload = run_connector_with_exit(
        root,
        vault,
        base_url,
        command,
        *extra_args,
    )
    if returncode != 0:
        raise AssertionError(
            f"Connector failed ({returncode}) for command {command}: "
            f"{json.dumps(payload, indent=2, sort_keys=True)}"
        )
    return payload


def run_connector_with_exit(
    root: Path,
    vault: Path,
    base_url: str,
    command: str,
    *extra_args: str,
) -> tuple[int, dict[str, Any]]:
    cmd = [
        sys.executable,
        "-m",
        "infinity_context_obsidian.cli",
        command,
        "--vault",
        str(vault),
        "--space",
        SPACE,
        "--memory_scope",
        PROFILE,
        "--api-url",
        base_url,
        "--token",
        TOKEN,
        "--json",
        *extra_args,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath()
    result = subprocess.run(
        cmd,
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    try:
        payload = dict(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"Connector returned non-JSON output ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from exc
    return result.returncode, payload


def install_plugin(root: Path, vault: Path, base_url: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "infinity_context_obsidian.cli",
        "install-plugin",
        "--vault",
        str(vault),
        "--enable",
        "--api-url",
        base_url,
        "--space",
        SPACE,
        "--memory_scope",
        PROFILE,
        "--apply-import",
        "--json",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath()
    result = subprocess.run(
        cmd,
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Plugin install failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return dict(json.loads(result.stdout))


def pythonpath() -> str:
    repo = Path(__file__).resolve().parents[1]
    paths = [
        repo / "packages/infinity_context_core",
        repo / "packages/infinity_context_adapters",
        repo / "packages/infinity_context_server",
        repo / "packages/infinity_context_runtime_bridge",
        repo / "packages/infinity_context_sdk",
        repo / "packages/infinity_context_obsidian",
    ]
    existing = os.environ.get("PYTHONPATH")
    values = [path.as_posix() for path in paths]
    if existing:
        values.append(existing)
    return os.pathsep.join(values)


def only_fact_file(vault: Path) -> Path:
    files = sorted((vault / "Infinity Context").glob("**/generated/facts/*.md"))
    files = [path for path in files if not path.name.startswith(".")]
    assert_true(len(files) == 1, f"expected exactly one exported fact note, got {files}")
    return files[0]


def replace_managed_text(path: Path, text: str) -> None:
    old = path.read_text(encoding="utf-8")
    start = old.index(TEXT_START) + len(TEXT_START)
    end = old.index(TEXT_END)
    path.write_text(old[:start] + f"\n{text}\n" + old[end:], encoding="utf-8")


def write_inbox_note(vault: Path, text: str) -> None:
    path = vault / "Infinity Context/spaces/obsidian-e2e/memory_scopes/default/inbox/e2e-inbox.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
