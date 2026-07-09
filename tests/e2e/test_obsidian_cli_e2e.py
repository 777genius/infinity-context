from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from infinity_context_obsidian.layout import ObsidianVaultLayout
from infinity_context_obsidian.note_format import TEXT_END, TEXT_START
from infinity_context_server_harness import PROJECT_ROOT, python_env, run_infinity_context_server


def test_obsidian_cli_syncs_real_backend_without_opening_obsidian(tmp_path: Path) -> None:
    vault_path = tmp_path / "vault"
    space_slug = "obsidian-cli-e2e"
    memory_scope_ref = "default"
    marker = f"OBSIDIAN_CLI_E2E_{time.time_ns()}"
    initial_text = f"{marker}: Obsidian CLI exports backend facts without UI."
    local_update_text = f"{marker}: Obsidian CLI imports managed note edits."
    inbox_text = f"{marker}: Obsidian CLI imports inbox notes as suggestions."
    stale_local_text = f"{marker}: Obsidian CLI stale local edit survives."
    backend_update_text = f"{marker}: Obsidian CLI backend update wins stale race."

    with (
        run_infinity_context_server(tmp_path, database_name="obsidian-cli.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        fact = _remember_fact(
            client,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            text=initial_text,
            idempotency_key=f"{marker}:fact",
        )
        common = [
            "--vault",
            str(vault_path),
            "--space",
            space_slug,
            "--memory_scope",
            memory_scope_ref,
            "--api-url",
            server.base_url,
            "--token",
            server.token,
            "--layout",
            "v2",
            "--json",
        ]

        connected = _run_obsidian_cli(["connect", *common])
        assert connected["ok"] is True

        exported = _run_obsidian_cli(["sync", *common, "--apply-import"])
        fact_path = vault_path / ObsidianVaultLayout.from_values(version="v2").fact_note_path(
            fact["id"],
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_ref,
        )
        assert exported["ok"] is True
        assert exported["export"]["exported"] == 1
        assert initial_text in fact_path.read_text(encoding="utf-8")

        _replace_managed_text(fact_path, local_update_text)
        dry_run = _run_obsidian_cli(["sync", *common], expected_returncode=1)
        assert dry_run["export_skipped"] is True
        assert dry_run["import"]["would_update"] == 1
        assert _get_fact(client, fact["id"])["text"] == initial_text

        applied = _run_obsidian_cli(["sync", *common, "--apply-import"])
        updated_fact = _get_fact(client, fact["id"])
        assert applied["ok"] is True
        assert applied["import"]["updated"] == 1
        assert updated_fact["text"] == local_update_text
        assert updated_fact["version"] == 2
        assert "infinity_context_version: 2" in fact_path.read_text(encoding="utf-8")

        inbox_path = (
            vault_path
            / "Infinity Context/spaces/obsidian-cli-e2e/memory_scopes/default/inbox/idea.md"
        )
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(inbox_text, encoding="utf-8")
        suggested = _run_obsidian_cli(["sync", *common, "--apply-import"])
        assert suggested["import"]["suggested"] == 1
        assert (
            _suggestion_texts(
                client, space_slug=space_slug, memory_scope_ref=memory_scope_ref
            ).count(inbox_text)
            == 1
        )

        repeated_suggestion = _run_obsidian_cli(["sync", *common, "--apply-import"])
        assert repeated_suggestion["import"]["suggested"] == 0
        assert (
            _suggestion_texts(
                client, space_slug=space_slug, memory_scope_ref=memory_scope_ref
            ).count(inbox_text)
            == 1
        )

        _replace_managed_text(fact_path, stale_local_text)
        backend_updated = _update_fact(
            client,
            fact_id=fact["id"],
            expected_version=2,
            text=backend_update_text,
            source_id=f"{marker}:backend-race",
        )
        assert backend_updated["version"] == 3

        stale = _run_obsidian_cli(["sync", *common, "--apply-import"], expected_returncode=1)
        assert stale["ok"] is False
        assert stale["export_skipped"] is True
        assert stale["import"]["conflicts"] == 1
        assert stale["import"]["conflict_artifacts_written"] == 1
        assert stale_local_text in fact_path.read_text(encoding="utf-8")
        assert _get_fact(client, fact["id"])["text"] == backend_update_text

        conflict_path = vault_path / stale["import"]["conflict_artifacts"][0]
        assert conflict_path.exists()
        conflict_path.unlink()
        recreated = _run_obsidian_cli(
            ["sync", *common, "--apply-import"],
            expected_returncode=1,
        )
        assert recreated["import"]["conflict_artifacts"] == stale["import"]["conflict_artifacts"]
        assert conflict_path.exists()


def test_obsidian_cli_doctor_supports_custom_obsidian_config_dir(
    tmp_path: Path,
) -> None:
    vault_path = tmp_path / "vault"
    space_slug = "obsidian-custom-config-e2e"
    memory_scope_ref = "default"

    with run_infinity_context_server(
        tmp_path,
        database_name="obsidian-custom-config.db",
    ) as server:
        common = [
            "--vault",
            str(vault_path),
            "--space",
            space_slug,
            "--memory_scope",
            memory_scope_ref,
            "--api-url",
            server.base_url,
            "--token",
            server.token,
            "--layout",
            "v2",
            "--json",
        ]
        config_dir = ".obsidian-dev"

        connected = _run_obsidian_cli(["connect", *common])
        installed = _run_obsidian_cli(
            [
                "install-plugin",
                "--vault",
                str(vault_path),
                "--obsidian-config-dir",
                config_dir,
                "--enable",
                "--api-url",
                server.base_url,
                "--space",
                space_slug,
                "--memory_scope",
                memory_scope_ref,
                "--json",
            ]
        )
        doctor = _run_obsidian_cli(
            [
                "doctor",
                *common,
                "--obsidian-config-dir",
                config_dir,
            ]
        )

    plugin_dir = vault_path / config_dir / "plugins/infinity-context"
    enabled_path = vault_path / config_dir / "community-plugins.json"

    assert connected["ok"] is True
    assert installed["ok"] is True
    assert installed["target_dir"] == str(plugin_dir.resolve())
    assert doctor["ok"] is True
    assert (plugin_dir / "main.js").exists()
    assert json.loads(enabled_path.read_text(encoding="utf-8")) == ["infinity-context"]
    assert not (vault_path / ".obsidian/plugins/infinity-context").exists()


def _run_obsidian_cli(
    args: list[str],
    *,
    expected_returncode: int = 0,
) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "infinity_context_obsidian.cli", *args],
        cwd=PROJECT_ROOT,
        env=python_env({}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == expected_returncode, (
        f"unexpected return code {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def _remember_fact(
    client: httpx.Client,
    *,
    space_slug: str,
    memory_scope_ref: str,
    text: str,
    idempotency_key: str,
) -> dict[str, Any]:
    response = client.post(
        "/v1/facts",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "text": text,
            "kind": "architecture_decision",
            "source_refs": [{"source_type": "manual", "source_id": idempotency_key}],
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def _update_fact(
    client: httpx.Client,
    *,
    fact_id: str,
    expected_version: int,
    text: str,
    source_id: str,
) -> dict[str, Any]:
    response = client.patch(
        f"/v1/facts/{fact_id}",
        json={
            "expected_version": expected_version,
            "text": text,
            "reason": "E2E backend race update",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
    )
    response.raise_for_status()
    return dict(response.json()["data"])


def _get_fact(client: httpx.Client, fact_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/facts/{fact_id}")
    response.raise_for_status()
    return dict(response.json()["data"])


def _suggestion_texts(
    client: httpx.Client,
    *,
    space_slug: str,
    memory_scope_ref: str,
) -> list[str]:
    response = client.get(
        "/v1/suggestions",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "status": "pending",
            "limit": 100,
        },
    )
    response.raise_for_status()
    return [str(item["candidate_text"]) for item in response.json()["data"]]


def _replace_managed_text(path: Path, new_text: str) -> None:
    old = path.read_text(encoding="utf-8")
    start = old.index(TEXT_START) + len(TEXT_START)
    end = old.index(TEXT_END)
    path.write_text(old[:start] + f"\n{new_text}\n" + old[end:], encoding="utf-8")
