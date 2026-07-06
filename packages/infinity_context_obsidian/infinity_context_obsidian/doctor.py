"""Local readiness checks for an Obsidian vault integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from infinity_context_obsidian.layout import ObsidianVaultLayout
from infinity_context_obsidian.plugin_install import (
    DEFAULT_OBSIDIAN_CONFIG_DIR,
    PLUGIN_FILES,
    PLUGIN_ID,
    plugin_dir,
    resolve_obsidian_config_dir,
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str
    required: bool = True


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.required)


@dataclass
class DoctorVaultUseCase:
    vault_path: Path

    def execute(
        self,
        *,
        api_url: str,
        token: str | None,
        space_slug: str,
        memory_scope_external_ref: str,
        root_folder: str = "Infinity Context",
        layout_version: str = "v2",
        obsidian_config_dir: str = DEFAULT_OBSIDIAN_CONFIG_DIR,
        require_plugin: bool = True,
        check_health: bool = True,
    ) -> DoctorResult:
        vault = self.vault_path.expanduser().resolve()
        layout = ObsidianVaultLayout.from_values(
            root_folder=root_folder,
            version=layout_version,
        )
        checks: list[DoctorCheck] = []
        checks.append(_check_vault_exists(vault))
        checks.append(_check_vault_writable(vault))
        checks.extend(
            _check_connected_layout(
                vault=vault,
                layout=layout,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
            )
        )
        if require_plugin:
            checks.extend(
                _check_plugin(
                    vault=vault,
                    api_url=api_url,
                    space_slug=space_slug,
                    memory_scope_external_ref=memory_scope_external_ref,
                    root_folder=root_folder,
                    layout_version=layout_version,
                    obsidian_config_dir=obsidian_config_dir,
                )
            )
        if check_health:
            checks.append(_check_backend_health(api_url=api_url, token=token))
        return DoctorResult(checks=tuple(checks))


def _check_vault_exists(vault: Path) -> DoctorCheck:
    exists = vault.is_dir()
    return DoctorCheck(
        name="vault_exists",
        ok=exists,
        message=f"Vault directory exists at {vault}" if exists else f"Missing vault {vault}",
    )


def _check_vault_writable(vault: Path) -> DoctorCheck:
    try:
        state_dir = vault / ".infinity-context"
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        os.replace(probe, state_dir / ".doctor-write-test.done")
        (state_dir / ".doctor-write-test.done").unlink(missing_ok=True)
        return DoctorCheck(
            name="vault_writable",
            ok=True,
            message="Vault can store sync state",
        )
    except OSError as exc:
        return DoctorCheck(
            name="vault_writable",
            ok=False,
            message=f"Vault is not writable: {exc}",
        )


def _check_connected_layout(
    *,
    vault: Path,
    layout: ObsidianVaultLayout,
    space_slug: str,
    memory_scope_external_ref: str,
) -> tuple[DoctorCheck, ...]:
    expected = (
        (("infinity_context_readme",), (vault / layout.root_dir() / "README.md",)),
        (
            ("generated_facts_dir",),
            tuple(
                vault / path
                for path in layout.fact_scan_dirs(
                    space_slug=space_slug,
                    memory_scope_external_ref=memory_scope_external_ref,
                )
            ),
        ),
        (
            ("inbox_dir",),
            tuple(
                vault / path
                for path in layout.inbox_scan_dirs(
                    space_slug=space_slug,
                    memory_scope_external_ref=memory_scope_external_ref,
                )
            ),
        ),
        (
            ("conflicts_dir",),
            (
                vault
                / layout.conflicts_dir(
                    space_slug=space_slug,
                    memory_scope_external_ref=memory_scope_external_ref,
                ),
                vault / layout.root_dir() / "conflicts",
            ),
        ),
    )
    checks: list[DoctorCheck] = []
    for (name,), paths in expected:
        checks.append(_check_any_path(vault=vault, name=name, paths=paths))
    return tuple(checks)


def _check_any_path(
    *,
    vault: Path,
    name: str,
    paths: tuple[Path, ...],
) -> DoctorCheck:
    for path in paths:
        if path.exists():
            return DoctorCheck(
                name=name,
                ok=True,
                message=f"Found {path.relative_to(vault)}",
            )
    expected = paths[0].relative_to(vault)
    return DoctorCheck(
        name=name,
        ok=False,
        message=f"Missing {expected}; run connect",
    )


def _check_plugin(
    *,
    vault: Path,
    api_url: str,
    space_slug: str,
    memory_scope_external_ref: str,
    root_folder: str,
    layout_version: str,
    obsidian_config_dir: str,
) -> tuple[DoctorCheck, ...]:
    plugin_directory = plugin_dir(vault, obsidian_config_dir)
    checks = [
        DoctorCheck(
            name="plugin_installed",
            ok=plugin_directory.is_dir()
            and all((plugin_directory / name).exists() for name in PLUGIN_FILES),
            message=f"Plugin bundle found at {plugin_directory}"
            if plugin_directory.is_dir()
            else "Plugin bundle is missing; run install-plugin --enable",
        )
    ]
    checks.append(_check_plugin_enabled(vault, obsidian_config_dir))
    checks.append(
        _check_plugin_settings(
            vault=vault,
            plugin_dir=plugin_directory,
            api_url=api_url,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            root_folder=root_folder,
            layout_version=layout_version,
        )
    )
    return tuple(checks)


def _check_plugin_enabled(vault: Path, obsidian_config_dir: str) -> DoctorCheck:
    plugins_path = resolve_obsidian_config_dir(vault, obsidian_config_dir) / (
        "community-plugins.json"
    )
    try:
        plugins = _read_json_array(plugins_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return DoctorCheck(
            name="plugin_enabled",
            ok=False,
            message=f"Cannot read enabled plugin list: {exc}",
        )
    ok = PLUGIN_ID in plugins
    return DoctorCheck(
        name="plugin_enabled",
        ok=ok,
        message=(
            "Infinity Context plugin is enabled"
            if ok
            else "Infinity Context plugin is not enabled"
        ),
    )


def _check_plugin_settings(
    *,
    vault: Path,
    plugin_dir: Path,
    api_url: str,
    space_slug: str,
    memory_scope_external_ref: str,
    root_folder: str,
    layout_version: str,
) -> DoctorCheck:
    settings_path = plugin_dir / "data.json"
    try:
        settings = _read_json_object(settings_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return DoctorCheck(
            name="plugin_settings",
            ok=False,
            message=f"Cannot read plugin settings: {exc}",
        )

    expected = {
        "apiUrl": api_url,
        "spaceSlug": space_slug,
        "memoryScopeExternalRef": memory_scope_external_ref,
        "rootFolder": root_folder,
        "layoutVersion": layout_version,
        "vaultPathOverride": str(vault),
    }
    mismatches = [
        key
        for key, value in expected.items()
        if str(settings.get(key) or "") != str(value)
    ]
    return DoctorCheck(
        name="plugin_settings",
        ok=not mismatches,
        message="Plugin settings match CLI arguments"
        if not mismatches
        else f"Plugin settings mismatch: {', '.join(mismatches)}",
    )


def _check_backend_health(*, api_url: str, token: str | None) -> DoctorCheck:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        response = httpx.get(f"{api_url.rstrip('/')}/v1/health", headers=headers, timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return DoctorCheck(
            name="backend_health",
            ok=False,
            message=f"Backend health check failed: {exc}",
        )
    return DoctorCheck(
        name="backend_health",
        ok=True,
        message=f"Backend is reachable at {api_url}",
    )


def _read_json_array(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError(f"Expected JSON string array at {path}")
    return list(data)


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return dict(data)
