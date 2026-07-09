"""Non-UI MCP smoke for Obsidian vault setup tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
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
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOKEN = "obsidian-mcp-e2e-token"
LIVE_SPACE = "mcp-live"
PROFILE = "default"
TEXT_START = "<!-- infinity-context-managed:fact-text:start -->"
TEXT_END = "<!-- infinity-context-managed:fact-text:end -->"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    temp_dir = Path(tempfile.mkdtemp(prefix="infinity-context-obsidian-mcp-"))
    try:
        payload = asyncio.run(_run(temp_dir))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(temp_dir, ignore_errors=True)


async def _run(temp_dir: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    missing_vault = temp_dir / "missing-vault"
    missing_home = temp_dir / "missing-home"
    local_home = temp_dir / "memo-home"
    prepare_home = temp_dir / "prepare-home"
    prepare_vault = temp_dir / "PrepareVault"
    live_vault = temp_dir / "LiveVault"
    custom_config_vault = temp_dir / "CustomConfigVault"
    unsafe_vault = temp_dir / "UnsafeVault"
    vault = temp_dir / "Vault"
    vault.mkdir()
    prepare_vault.mkdir()
    live_vault.mkdir()
    custom_config_vault.mkdir()
    unsafe_vault.mkdir()

    disabled = await _with_session(
        repo_root=repo_root,
        env={
            "MEMORY_MCP_OBSIDIAN_ENABLED": "false",
            "MEMORY_MCP_OBSIDIAN_VAULT": str(missing_vault),
        },
        callback=lambda session: _call(session, "memory_obsidian_status", {}),
    )
    _assert(disabled["ok"] is True, "disabled status should return ok")
    _assert(
        disabled["data"]["status"] == "disabled",
        "disabled status should report disabled",
    )
    _assert(not missing_vault.exists(), "disabled status must not touch the vault")

    local_disabled = await _with_session(
        repo_root=repo_root,
        env={
            "MEMORY_MCP_LOCAL_RUNTIME_ENABLED": "false",
            "MEMORY_MCP_LOCAL_RUNTIME_HOME": str(missing_home),
        },
        callback=lambda session: _call(session, "memory_local_runtime_status", {}),
    )
    _assert(local_disabled["ok"] is True, "local runtime disabled status should return ok")
    _assert(
        local_disabled["data"]["status"] == "disabled",
        "local runtime disabled status should report disabled",
    )
    _assert(not missing_home.exists(), "local runtime disabled status must not touch home")

    local_env = {
        "MEMORY_MCP_LOCAL_RUNTIME_ENABLED": "true",
        "MEMORY_MCP_LOCAL_RUNTIME_START_ENABLED": "false",
        "MEMORY_MCP_LOCAL_RUNTIME_HOME": str(local_home),
        "MEMORY_MCP_LOCAL_RUNTIME_REPO_DIR": str(repo_root),
    }
    local_init_dry_run = await _with_session(
        repo_root=repo_root,
        env=local_env,
        callback=lambda session: _call(session, "memory_local_runtime_init", {"apply": False}),
    )
    _assert(local_init_dry_run["ok"] is True, "local runtime init dry-run should succeed")
    _assert(
        local_init_dry_run["data"]["dry_run"] is True,
        "local runtime init should be dry-run by default",
    )
    _assert(not (local_home / "config.toml").exists(), "local runtime dry-run must not write")

    local_init_applied = await _with_session(
        repo_root=repo_root,
        env=local_env,
        callback=lambda session: _call(session, "memory_local_runtime_init", {"apply": True}),
    )
    _assert(local_init_applied["ok"] is True, "local runtime init apply should succeed")
    _assert((local_home / "config.toml").exists(), "local runtime init should write config")
    _assert((local_home / ".env").exists(), "local runtime init should write env")
    _assert(
        "MEMORY_SERVICE_TOKEN" not in json.dumps(local_init_applied, sort_keys=True),
        "local runtime init response must not expose token names",
    )

    local_start_dry_run = await _with_session(
        repo_root=repo_root,
        env=local_env,
        callback=lambda session: _call(
            session,
            "memory_local_runtime_start",
            {"memory_scope": "lite", "apply": False},
        ),
    )
    _assert(
        local_start_dry_run["data"]["status"] == "start_planned",
        "local runtime start dry-run should only plan",
    )

    local_start_blocked = await _with_session(
        repo_root=repo_root,
        env=local_env,
        callback=lambda session: _call_error(
            session,
            "memory_local_runtime_start",
            {"memory_scope": "lite", "apply": True},
        ),
    )
    _assert(
        local_start_blocked["error"]["code"]
        == "infinity_context_mcp.local_runtime.start_disabled",
        "local runtime start should require the start env gate",
    )

    prepare_env = {
        "MEMORY_MCP_API_URL": "http://127.0.0.1:9",
        "MEMORY_MCP_LOCAL_RUNTIME_ENABLED": "true",
        "MEMORY_MCP_LOCAL_RUNTIME_START_ENABLED": "false",
        "MEMORY_MCP_LOCAL_RUNTIME_HOME": str(prepare_home),
        "MEMORY_MCP_LOCAL_RUNTIME_REPO_DIR": str(repo_root),
        "MEMORY_MCP_OBSIDIAN_ENABLED": "true",
        "MEMORY_MCP_OBSIDIAN_SYNC_ENABLED": "false",
        "MEMORY_MCP_OBSIDIAN_VAULT": str(prepare_vault),
        "MEMORY_MCP_OBSIDIAN_ROOT_FOLDER": "Infinity Context",
        "MEMORY_MCP_OBSIDIAN_LAYOUT": "v2",
        "MEMORY_MCP_DEFAULT_SPACE_SLUG": "prepare-smoke",
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
    }
    prepare_dry_run = await _with_session(
        repo_root=repo_root,
        env=prepare_env,
        callback=lambda session: _call(session, "memory_obsidian_prepare", {"apply": False}),
    )
    prepare_facts = (
        prepare_vault
        / "Infinity Context/spaces/prepare-smoke/memory_scopes/default/generated/facts"
    )
    _assert(prepare_dry_run["ok"] is True, "prepare dry-run should succeed")
    _assert(
        prepare_dry_run["data"]["status"] == "prepare_planned",
        "prepare dry-run should be planned",
    )
    _assert(not (prepare_home / "config.toml").exists(), "prepare dry-run must not write config")
    _assert(not prepare_facts.exists(), "prepare dry-run must not write vault folders")

    prepare_applied = await _with_session(
        repo_root=repo_root,
        env=prepare_env,
        callback=lambda session: _call(session, "memory_obsidian_prepare", {"apply": True}),
    )
    _assert(prepare_applied["ok"] is True, "prepare apply should succeed")
    _assert(
        prepare_applied["data"]["status"] == "prepared_backend_not_ready",
        "prepare apply should stop before preview when backend is not ready",
    )
    _assert((prepare_home / "config.toml").exists(), "prepare apply should write config")
    _assert(prepare_facts.exists(), "prepare apply should write V2 facts dir")
    _assert(
        (prepare_vault / ".obsidian/plugins/infinity-context/main.js").exists(),
        "prepare apply should install plugin bundle",
    )
    _assert(
        "local_runtime_started" not in prepare_applied["diagnostics"]["side_effects"],
        "prepare apply must not start local runtime",
    )
    _assert(
        "obsidian_sync" not in prepare_applied["diagnostics"]["side_effects"],
        "prepare apply must not run mutating sync",
    )

    custom_config_env = {
        "MEMORY_MCP_OBSIDIAN_ENABLED": "true",
        "MEMORY_MCP_OBSIDIAN_SYNC_ENABLED": "false",
        "MEMORY_MCP_OBSIDIAN_VAULT": str(custom_config_vault),
        "MEMORY_MCP_OBSIDIAN_CONFIG_DIR": ".obsidian-dev",
        "MEMORY_MCP_OBSIDIAN_ROOT_FOLDER": "Infinity Context",
        "MEMORY_MCP_OBSIDIAN_LAYOUT": "v2",
        "MEMORY_MCP_DEFAULT_SPACE_SLUG": "custom-config-smoke",
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
    }
    custom_config_setup = await _with_session(
        repo_root=repo_root,
        env=custom_config_env,
        callback=lambda session: _call(
            session,
            "memory_obsidian_setup",
            {"apply": True, "install_plugin": True, "enable_plugin": True},
        ),
    )
    custom_config_plugin = custom_config_vault / ".obsidian-dev/plugins/infinity-context"
    _assert(custom_config_setup["ok"] is True, "custom config setup should succeed")
    _assert(
        custom_config_setup["data"]["obsidian_config_dir"] == ".obsidian-dev",
        "custom config setup should echo configured Obsidian config dir",
    )
    _assert(
        (custom_config_plugin / "main.js").exists(),
        "custom config setup should install plugin under the configured dir",
    )
    _assert(
        (custom_config_vault / ".obsidian-dev/community-plugins.json").exists(),
        "custom config setup should enable plugin under the configured dir",
    )
    _assert(
        not (custom_config_vault / ".obsidian/plugins/infinity-context").exists(),
        "custom config setup must not write the default .obsidian plugin dir",
    )
    custom_config_status = await _with_session(
        repo_root=repo_root,
        env=custom_config_env,
        callback=lambda session: _call(
            session,
            "memory_obsidian_status",
            {"require_plugin": True},
        ),
    )
    custom_config_checks = {
        check["name"]: check for check in custom_config_status["data"]["checks"]
    }
    _assert(
        custom_config_status["data"]["obsidian_config_dir"] == ".obsidian-dev",
        "custom config status should echo configured Obsidian config dir",
    )
    for check_name in ("plugin_installed", "plugin_enabled", "plugin_settings"):
        _assert(
            custom_config_checks[check_name]["ok"] is True,
            f"custom config status should pass {check_name}",
        )
    _assert(
        custom_config_status["data"]["status"] == "needs_attention"
        and custom_config_checks["backend_health"]["ok"] is False,
        "custom config status should only be degraded because isolated smoke has no backend",
    )

    common_env = {
        "MEMORY_MCP_OBSIDIAN_ENABLED": "true",
        "MEMORY_MCP_OBSIDIAN_SYNC_ENABLED": "false",
        "MEMORY_MCP_OBSIDIAN_VAULT": str(vault),
        "MEMORY_MCP_OBSIDIAN_ROOT_FOLDER": "Infinity Context",
        "MEMORY_MCP_OBSIDIAN_LAYOUT": "v2",
        "MEMORY_MCP_DEFAULT_SPACE_SLUG": "mcp-smoke",
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
    }
    dry_run = await _with_session(
        repo_root=repo_root,
        env=common_env,
        callback=lambda session: _call(
            session,
            "memory_obsidian_setup",
            {"apply": False, "install_plugin": True, "enable_plugin": True},
        ),
    )
    expected_facts = (
        vault / "Infinity Context/spaces/mcp-smoke/memory_scopes/default/generated/facts"
    )
    _assert(dry_run["ok"] is True, "dry-run setup should succeed")
    _assert(dry_run["data"]["dry_run"] is True, "dry-run setup should remain dry")
    _assert(dry_run["data"]["would_install_plugin"] is True, "dry-run should plan plugin install")
    _assert(not expected_facts.exists(), "dry-run setup must not write scoped folders")

    applied = await _with_session(
        repo_root=repo_root,
        env=common_env,
        callback=lambda session: _call(
            session,
            "memory_obsidian_setup",
            {"apply": True, "install_plugin": True, "enable_plugin": True},
        ),
    )
    _assert(applied["ok"] is True, "applied setup should succeed")
    _assert(applied["data"]["plugin_installed"] is True, "plugin should be installed")
    _assert(applied["data"]["plugin_enabled"] is True, "plugin should be enabled")
    _assert(expected_facts.exists(), "applied setup should write V2 facts dir")
    _assert((vault / "Infinity Context/README.md").exists(), "applied setup should write README")
    _assert(
        (vault / ".obsidian/plugins/infinity-context/main.js").exists(),
        "applied setup should install plugin bundle",
    )
    plugin_settings = json.loads(
        (vault / ".obsidian/plugins/infinity-context/data.json").read_text(encoding="utf-8")
    )
    _assert(plugin_settings["localCliPath"] == "infinity-context", "plugin settings need local CLI")

    status = await _with_session(
        repo_root=repo_root,
        env=common_env,
        callback=lambda session: _call(session, "memory_obsidian_status", {}),
    )
    _assert(status["ok"] is True, "enabled status should return ok")
    _assert(status["data"]["status"] in {"ready", "needs_attention"}, "status should be computed")

    sync_disabled = await _with_session(
        repo_root=repo_root,
        env=common_env,
        callback=lambda session: _call_error(
            session,
            "memory_obsidian_sync",
            {"apply": True, "apply_import": True},
        ),
    )
    _assert(
        sync_disabled["error"]["code"] == "infinity_context_mcp.obsidian.sync_disabled",
        "mutating sync should require the sync env gate",
    )

    unsafe_layout = await _with_session(
        repo_root=repo_root,
        env={
            **common_env,
            "MEMORY_MCP_OBSIDIAN_VAULT": str(unsafe_vault),
        },
        callback=lambda session: _call_error(
            session,
            "memory_obsidian_setup",
            {"apply": True, "root_folder": "../escape"},
        ),
    )
    _assert(
        unsafe_layout["error"]["code"] == "infinity_context_mcp.obsidian.error",
        "unsafe root folder should return an Obsidian MCP error",
    )
    _assert(
        not any(unsafe_vault.iterdir()),
        "unsafe root folder must not create vault files",
    )

    live_report = await _run_live_backend_sync(
        repo_root=repo_root,
        temp_dir=temp_dir,
        vault=live_vault,
    )

    return {
        "ok": True,
        "vault": str(vault),
        "disabled_status": disabled["data"]["status"],
        "setup_status": applied["data"]["status"],
        "status_after_setup": status["data"]["status"],
        "sync_disabled_code": sync_disabled["error"]["code"],
        "local_runtime_init_status": local_init_applied["data"]["status"],
        "local_runtime_start_disabled_code": local_start_blocked["error"]["code"],
        "prepare_status": prepare_applied["data"]["status"],
        "custom_config_status": custom_config_status["data"]["status"],
        "custom_config_plugin_checks_ok": all(
            custom_config_checks[name]["ok"]
            for name in ("plugin_installed", "plugin_enabled", "plugin_settings")
        ),
        "custom_config_plugin_dir": str(custom_config_plugin),
        "facts_dir": str(expected_facts),
        "unsafe_layout_code": unsafe_layout["error"]["code"],
        "live_backend_sync": live_report,
    }


async def _run_live_backend_sync(
    *,
    repo_root: Path,
    temp_dir: Path,
    vault: Path,
) -> dict[str, Any]:
    db_path = temp_dir / "mcp-live-memory.db"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = Process(target=_run_server, args=(db_path, port), daemon=True)
    server.start()
    try:
        _wait_for_health(base_url)
        fact = _create_fact(base_url, text="MCP Obsidian live initial fact.")
        env = {
            "MEMORY_MCP_API_URL": base_url,
            "MEMORY_MCP_AUTH_TOKEN": TOKEN,
            "MEMORY_MCP_OBSIDIAN_ENABLED": "true",
            "MEMORY_MCP_OBSIDIAN_SYNC_ENABLED": "true",
            "MEMORY_MCP_OBSIDIAN_VAULT": str(vault),
            "MEMORY_MCP_OBSIDIAN_ROOT_FOLDER": "Infinity Context",
            "MEMORY_MCP_OBSIDIAN_LAYOUT": "v2",
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": LIVE_SPACE,
            "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": PROFILE,
        }

        setup = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_setup",
                {"apply": True, "install_plugin": True, "enable_plugin": True},
            ),
        )
        live_facts_dir = (
            vault / f"Infinity Context/spaces/{LIVE_SPACE}/memory_scopes/{PROFILE}/generated/facts"
        )
        _assert(setup["ok"] is True, "live MCP setup should succeed")
        _assert(setup["data"]["plugin_installed"] is True, "live setup should install plugin")
        _assert(setup["data"]["plugin_enabled"] is True, "live setup should enable plugin")
        _assert(live_facts_dir.exists(), "live setup should write scoped facts directory")
        plugin_settings = json.loads(
            (vault / ".obsidian/plugins/infinity-context/data.json").read_text(encoding="utf-8")
        )
        _assert(plugin_settings["apiUrl"] == base_url, "plugin settings should use live API URL")
        _assert(
            plugin_settings["vaultPathOverride"] == str(vault.resolve()),
            "plugin settings should pin resolved vault",
        )
        _assert(plugin_settings["spaceSlug"] == LIVE_SPACE, "plugin settings should pin space")
        _assert(plugin_settings["token"] == "", "MCP plugin install must not persist service token")

        status = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_status",
                {"require_plugin": True},
            ),
        )
        _assert(
            status["data"]["status"] == "ready",
            f"live MCP status should be ready: {status['data']}",
        )

        preview = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(session, "memory_obsidian_preview", {}),
        )
        _assert(preview["data"]["status"] == "preview_ok", "live preview should be ok")
        _assert(
            preview["data"]["export_result"]["exported"] >= 1,
            "live preview should see backend export",
        )
        _assert(not _fact_files(vault), "live preview must not write fact notes")

        dry_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(session, "memory_obsidian_sync", {"apply": False}),
        )
        _assert(dry_sync["data"]["dry_run"] is True, "apply=false sync should stay dry-run")
        _assert(not _fact_files(vault), "apply=false sync must not write fact notes")

        export_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": True},
            ),
        )
        _assert(export_sync["data"]["status"] == "sync_ok", "live export sync should be ok")
        _assert(
            "obsidian_sync" in export_sync["diagnostics"]["side_effects"],
            "mutating MCP sync should report side effect",
        )
        fact_file = _only_fact_file(vault)
        _assert(
            fact["text"] in fact_file.read_text(encoding="utf-8"),
            "fact note should be exported",
        )

        _replace_managed_text(fact_file, "MCP Obsidian live markdown edit.")
        edit_preview = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(session, "memory_obsidian_preview", {}),
        )
        _assert(
            edit_preview["data"]["import_result"]["would_update"] == 1,
            "live preview should detect direct markdown edit",
        )
        _assert(
            _get_fact(base_url, fact["id"])["text"] == "MCP Obsidian live initial fact.",
            "preview must not update backend fact",
        )

        no_import_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": False},
            ),
        )
        _assert(
            no_import_sync["data"]["status"] == "sync_needs_review",
            "apply without apply_import should pause direct edit",
        )
        _assert(no_import_sync["data"]["export_skipped"] is True, "direct edit should pause export")
        _assert(
            _get_fact(base_url, fact["id"])["text"] == "MCP Obsidian live initial fact.",
            "apply_import=false must not update backend fact",
        )
        _assert(
            "MCP Obsidian live markdown edit." in fact_file.read_text(encoding="utf-8"),
            "apply_import=false must leave markdown edit for review",
        )

        import_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": True},
            ),
        )
        _assert(import_sync["data"]["status"] == "sync_ok", "apply_import sync should succeed")
        _assert(import_sync["data"]["import_result"]["updated"] == 1, "direct edit should import")
        updated = _get_fact(base_url, fact["id"])
        _assert(updated["text"] == "MCP Obsidian live markdown edit.", "backend should import edit")
        _assert(updated["version"] == 2, "backend fact should increment version")

        marker = "MCP Obsidian live inbox suggestion marker."
        _write_inbox_note(vault, marker)
        inbox_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": True},
            ),
        )
        _assert(inbox_sync["data"]["import_result"]["suggested"] == 1, "inbox should suggest")
        repeat_inbox_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": True},
            ),
        )
        _assert(
            repeat_inbox_sync["data"]["import_result"]["suggested"] == 0,
            "repeat MCP sync must not duplicate inbox suggestion",
        )
        matching = [
            item for item in _list_suggestions(base_url) if marker in item["candidate_text"]
        ]
        _assert(len(matching) == 1, "backend should contain exactly one MCP inbox suggestion")

        backend_update = _update_fact(
            base_url,
            fact["id"],
            expected_version=updated["version"],
            text="MCP Obsidian backend update before stale edit.",
        )
        _replace_managed_text(fact_file, "MCP Obsidian stale local edit.")
        stale_sync = await _with_session(
            repo_root=repo_root,
            env=env,
            callback=lambda session: _call(
                session,
                "memory_obsidian_sync",
                {"apply": True, "apply_import": True},
            ),
        )
        _assert(
            stale_sync["data"]["status"] == "sync_needs_review",
            "stale MCP sync should need review",
        )
        _assert(stale_sync["data"]["import_result"]["conflicts"] == 1, "stale edit should conflict")
        _assert(stale_sync["data"]["export_skipped"] is True, "stale conflict should skip export")
        conflict_artifacts = stale_sync["data"]["import_result"]["conflict_artifacts"]
        _assert(conflict_artifacts, "stale MCP sync should write conflict artifact")
        _assert(
            all((vault / path).exists() for path in conflict_artifacts),
            "MCP conflict artifact paths should exist",
        )
        _assert(
            "MCP Obsidian stale local edit." in fact_file.read_text(encoding="utf-8"),
            "stale MCP local edit must remain in note",
        )
        _assert(
            _get_fact(base_url, fact["id"])["text"] == backend_update["text"],
            "stale MCP sync must not overwrite backend fact",
        )

        return {
            "base_url": base_url,
            "fact_id": fact["id"],
            "status": status["data"]["status"],
            "exported": export_sync["data"]["export_result"]["exported"],
            "direct_edit_imported_version": updated["version"],
            "suggestions_matching_marker": len(matching),
            "stale_conflict_artifacts_written": stale_sync["data"]["import_result"][
                "conflict_artifacts_written"
            ],
        }
    finally:
        server.terminate()
        server.join(timeout=5)


def _run_server(db_path: Path, port: int) -> None:
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/v1/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"Infinity Context server did not become healthy at {base_url}")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _create_fact(base_url: str, *, text: str) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url}/v1/facts",
        headers=_headers(),
        json={
            "space_slug": LIVE_SPACE,
            "memory_scope_external_ref": PROFILE,
            "text": text,
            "kind": "note",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_id": "obsidian-mcp-live-seed",
                    "quote_preview": text,
                }
            ],
        },
        timeout=5,
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def _get_fact(base_url: str, fact_id: str) -> dict[str, Any]:
    response = httpx.get(f"{base_url}/v1/facts/{fact_id}", headers=_headers(), timeout=5)
    response.raise_for_status()
    return dict(response.json()["data"])


def _update_fact(
    base_url: str,
    fact_id: str,
    *,
    expected_version: int,
    text: str,
) -> dict[str, Any]:
    response = httpx.patch(
        f"{base_url}/v1/facts/{fact_id}",
        headers=_headers(),
        json={
            "expected_version": expected_version,
            "text": text,
            "reason": "MCP Obsidian live smoke backend-side update",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_id": "obsidian-mcp-live-backend-update",
                    "quote_preview": text,
                }
            ],
        },
        timeout=5,
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def _list_suggestions(base_url: str) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{base_url}/v1/suggestions",
        headers=_headers(),
        params={
            "space_slug": LIVE_SPACE,
            "memory_scope_external_ref": PROFILE,
            "status": "pending",
        },
        timeout=5,
    )
    response.raise_for_status()
    return [dict(item) for item in response.json()["data"]]


def _fact_files(vault: Path) -> list[Path]:
    files = sorted((vault / "Infinity Context").glob("**/generated/facts/*.md"))
    return [path for path in files if not path.name.startswith(".")]


def _only_fact_file(vault: Path) -> Path:
    files = _fact_files(vault)
    _assert(len(files) == 1, f"expected exactly one exported fact note, got {files}")
    return files[0]


def _replace_managed_text(path: Path, text: str) -> None:
    old = path.read_text(encoding="utf-8")
    start = old.index(TEXT_START) + len(TEXT_START)
    end = old.index(TEXT_END)
    path.write_text(old[:start] + f"\n{text}\n" + old[end:], encoding="utf-8")


def _write_inbox_note(vault: Path, text: str) -> None:
    path = (
        vault
        / f"Infinity Context/spaces/{LIVE_SPACE}/memory_scopes/{PROFILE}/inbox/mcp-live-inbox.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _with_session(
    *,
    repo_root: Path,
    env: dict[str, str],
    callback,
) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "infinity_context_mcp"],
        env=_python_env(repo_root, env),
        cwd=str(repo_root),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        expected = {
            "memory_local_runtime_status",
            "memory_local_runtime_init",
            "memory_local_runtime_doctor",
            "memory_local_runtime_start",
            "memory_obsidian_prepare",
            "memory_obsidian_status",
            "memory_obsidian_setup",
            "memory_obsidian_preview",
            "memory_obsidian_sync",
        }
        missing = expected - tool_names
        _assert(not missing, f"missing MCP Obsidian tools: {sorted(missing)}")
        return await callback(session)


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    _assert(result.isError is False, f"{name} returned MCP error")
    return _structured(result)


async def _call_error(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    _assert(result.isError is True, f"{name} should return MCP error")
    return _structured(result)


def _structured(result: Any) -> dict[str, Any]:
    if result.structuredContent is not None:
        return dict(result.structuredContent)
    return json.loads(result.content[0].text)


def _python_env(repo_root: Path, extra: dict[str, str]) -> dict[str, str]:
    package_paths = [
        "packages/infinity_context_core",
        "packages/infinity_context_adapters",
        "packages/infinity_context_server",
        "packages/infinity_context_sdk",
        "packages/infinity_context_cli",
        "packages/infinity_context_obsidian",
        "packages/infinity_context_mcp",
    ]
    return {
        **os.environ,
        **extra,
        "MEMORY_MCP_TRANSPORT": "stdio",
        "PYTHONPATH": os.pathsep.join(str(repo_root / path) for path in package_paths),
    }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
