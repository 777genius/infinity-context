from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "memo-stack-agent-plugin"
GEMINI_HOOK_PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "memo-stack-agent-plugin-gemini-hooks"
PLUGIN_KIT = PROJECT_ROOT / "scripts" / "plugin-kit-ai-local"
INTEGRATION_ID = "memo-stack-agent-plugin"
GEMINI_HOOK_INTEGRATION_ID = "memo-stack-agent-plugin-gemini-hooks"
INSTALL_TARGETS = ("codex", "claude", "opencode", "cursor")
GEMINI_HOOK_INSTALL_TARGETS = ("gemini",)
InstallSpec = tuple[str, Path, tuple[str, ...]]
SOURCE_ROOT_MARKER = ".memo-stack-source-root"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or update the Memory Agent plugin.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for spec in install_specs():
        command, action = install_command(spec, dry_run=args.dry_run)
        integration_id, _plugin_root, _targets = spec
        print(f"{integration_id} {action}: {' '.join(command)}", file=sys.stderr)
        exit_code = subprocess.call(command, cwd=PROJECT_ROOT)
        if exit_code != 0:
            return exit_code
        if not args.dry_run:
            write_source_root_markers(spec)
    return 0


def install_specs() -> tuple[InstallSpec, ...]:
    return (
        (INTEGRATION_ID, PLUGIN_ROOT, INSTALL_TARGETS),
        (GEMINI_HOOK_INTEGRATION_ID, GEMINI_HOOK_PLUGIN_ROOT, GEMINI_HOOK_INSTALL_TARGETS),
    )


def install_command(spec: InstallSpec, *, dry_run: bool) -> tuple[list[str], str]:
    integration_id, plugin_root, targets = spec
    if is_managed(integration_id):
        command = [str(PLUGIN_KIT), "update", integration_id]
        action = "update"
    else:
        command = [str(PLUGIN_KIT), "add", str(plugin_root)]
        for target in targets:
            command.extend(["--target", target])
        action = "add"
    if dry_run:
        command.append("--dry-run")
    return command, action


def write_source_root_markers(spec: InstallSpec) -> None:
    integration_id, plugin_root, targets = spec
    for target in targets:
        for materialized_root in materialized_runtime_roots(target, integration_id):
            marker = materialized_root / SOURCE_ROOT_MARKER
            marker.write_text(f"{PROJECT_ROOT}\n", encoding="utf-8")
            sync_runtime_bin(plugin_root, materialized_root)


def materialized_runtime_roots(target: str, integration_id: str) -> tuple[Path, ...]:
    materialized_root = materialized_plugin_root(target, integration_id)
    if not materialized_root.exists():
        return ()
    roots = [materialized_root]
    nested_plugin_root = materialized_root / "plugins" / integration_id
    if nested_plugin_root.exists():
        roots.append(nested_plugin_root)
    return tuple(roots)


def sync_runtime_bin(plugin_root: Path, materialized_root: Path) -> None:
    source_bin = plugin_root / "bin"
    if not source_bin.exists():
        return
    destination_bin = materialized_root / "bin"
    if destination_bin.exists():
        shutil.rmtree(destination_bin)
    shutil.copytree(source_bin, destination_bin)


def materialized_plugin_root(target: str, integration_id: str) -> Path:
    base = Path(
        os.getenv(
            "PLUGIN_KIT_AI_MATERIALIZED_ROOT",
            str(Path.home() / ".plugin-kit-ai" / "materialized"),
        )
    )
    return base / target / integration_id


def is_managed(integration_id: str = INTEGRATION_ID) -> bool:
    state_path = Path(
        os.getenv("PLUGIN_KIT_AI_STATE_PATH", str(Path.home() / ".plugin-kit-ai" / "state.json"))
    )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    installations = state.get("installations")
    if not isinstance(installations, list):
        return False
    return any(
        isinstance(item, dict) and item.get("integration_id") == integration_id
        for item in installations
    )


if __name__ == "__main__":
    raise SystemExit(main())
