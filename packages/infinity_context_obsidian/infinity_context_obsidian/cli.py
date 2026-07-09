"""CLI for the Obsidian connector."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from infinity_context_sdk import InfinityContextClient, InfinityContextError

from infinity_context_obsidian.conflicts import WriteConflictArtifactsUseCase
from infinity_context_obsidian.doctor import DoctorResult, DoctorVaultUseCase
from infinity_context_obsidian.gateway import SdkMemoryGateway
from infinity_context_obsidian.layout import (
    DEFAULT_LAYOUT_VERSION,
    DEFAULT_ROOT_FOLDER,
    ObsidianVaultLayout,
)
from infinity_context_obsidian.plugin_install import (
    DEFAULT_OBSIDIAN_CONFIG_DIR,
    InstallObsidianPluginUseCase,
)
from infinity_context_obsidian.setup import SetupVaultUseCase
from infinity_context_obsidian.state import SqliteSyncStateStore
from infinity_context_obsidian.sync import (
    ExportFactsToVaultUseCase,
    ImportInboxSuggestionsUseCase,
    ImportVaultChangesResult,
    ImportVaultChangesUseCase,
    PreviewVaultSyncResult,
    PreviewVaultSyncUseCase,
    SyncVaultOnceResult,
    SyncVaultOnceUseCase,
    merge_import_results,
)
from infinity_context_obsidian.vault import FilesystemVault

DEFAULT_API_URL = "http://127.0.0.1:7788"
DEFAULT_SPACE_SLUG = "default"
DEFAULT_MEMORY_SCOPE_EXTERNAL_REF = "default"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (InfinityContextError, httpx.HTTPError, ValueError, OSError) as exc:
        print(f"infinity-context-obsidian: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infinity-context-obsidian")
    subparsers = parser.add_subparsers(dest="command")

    install_plugin_parser = subparsers.add_parser(
        "install-plugin",
        help="Install the bundled thin Obsidian plugin into a vault.",
    )
    install_plugin_parser.add_argument("--vault", type=Path, required=True)
    install_plugin_parser.add_argument(
        "--obsidian-config-dir",
        default=DEFAULT_OBSIDIAN_CONFIG_DIR,
        help="Obsidian config folder relative to the vault root.",
    )
    install_plugin_parser.add_argument("--overwrite", action="store_true")
    install_plugin_parser.add_argument("--enable", action="store_true")
    install_plugin_parser.add_argument("--api-url", default=DEFAULT_API_URL)
    install_plugin_parser.add_argument("--local-cli-path", default="infinity-context")
    install_plugin_parser.add_argument("--cli-path", default="infinity-context-obsidian")
    install_plugin_parser.add_argument("--space", dest="space_slug", default=DEFAULT_SPACE_SLUG)
    install_plugin_parser.add_argument(
        "--memory_scope",
        dest="memory_scope_external_ref",
        default=DEFAULT_MEMORY_SCOPE_EXTERNAL_REF,
    )
    install_plugin_parser.add_argument("--apply-import", action="store_true")
    install_plugin_parser.add_argument("--root-folder", default=DEFAULT_ROOT_FOLDER)
    install_plugin_parser.add_argument(
        "--layout",
        dest="layout_version",
        choices=("v1", "v2"),
        default=DEFAULT_LAYOUT_VERSION,
    )
    install_plugin_parser.add_argument("--command-timeout-ms", type=int, default=30000)
    install_plugin_parser.add_argument("--json", action="store_true")
    install_plugin_parser.set_defaults(handler=_cmd_install_plugin)

    connect_parser = subparsers.add_parser(
        "connect",
        help="Initialize Infinity Context folders and guide notes inside an Obsidian vault.",
    )
    _add_common_args(connect_parser)
    connect_parser.add_argument("--overwrite", action="store_true")
    connect_parser.set_defaults(handler=_cmd_connect)

    export_parser = subparsers.add_parser("export", help="Export facts to an Obsidian vault.")
    _add_common_args(export_parser)
    export_parser.set_defaults(handler=_cmd_export)

    preview_parser = subparsers.add_parser(
        "preview",
        help="Preview sync effects without writing vault files or backend memory.",
    )
    _add_common_args(preview_parser)
    preview_parser.add_argument("--no-inbox", action="store_true")
    preview_parser.set_defaults(handler=_cmd_preview)

    import_parser = subparsers.add_parser(
        "import",
        help="Import direct managed note edits. Dry-run unless --apply is passed.",
    )
    _add_common_args(import_parser)
    import_parser.add_argument("--apply", action="store_true")
    import_parser.add_argument("--no-inbox", action="store_true")
    import_parser.set_defaults(handler=_cmd_import)

    sync_parser = subparsers.add_parser("sync", help="Run one import-then-export sync cycle.")
    _add_common_args(sync_parser)
    sync_parser.add_argument("--apply-import", action="store_true")
    sync_parser.add_argument("--no-inbox", action="store_true")
    sync_parser.set_defaults(handler=_cmd_sync)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check vault, plugin, and backend readiness without opening Obsidian.",
    )
    _add_common_args(doctor_parser)
    doctor_parser.add_argument("--no-plugin", action="store_true")
    doctor_parser.add_argument("--no-health", action="store_true")
    doctor_parser.set_defaults(handler=_cmd_doctor)

    watch_parser = subparsers.add_parser("watch", help="Poll export/import in a daemon loop.")
    _add_common_args(watch_parser)
    watch_parser.add_argument("--apply-import", action="store_true")
    watch_parser.add_argument("--no-inbox", action="store_true")
    watch_parser.add_argument("--interval", type=float, default=5.0)
    watch_parser.add_argument("--export-every", type=int, default=6)
    watch_parser.set_defaults(handler=_cmd_watch)

    return parser


def _cmd_install_plugin(args: argparse.Namespace) -> int:
    result = InstallObsidianPluginUseCase(
        vault_path=args.vault,
        obsidian_config_dir=args.obsidian_config_dir,
    ).execute(
        overwrite=args.overwrite,
        enable=args.enable,
        settings={
            "apiUrl": args.api_url,
            "token": "",
            "localCliPath": args.local_cli_path,
            "cliPath": args.cli_path,
            "vaultPathOverride": str(args.vault.expanduser().resolve()),
            "spaceSlug": args.space_slug,
            "memoryScopeExternalRef": args.memory_scope_external_ref,
            "rootFolder": args.root_folder,
            "layoutVersion": args.layout_version,
            "applyImportOnSync": args.apply_import,
            "commandTimeoutMs": max(args.command_timeout_ms, 1000),
        },
    )
    _print(
        {
            "ok": True,
            "target_dir": str(result.target_dir),
            "obsidian_config_dir": args.obsidian_config_dir,
            "written": list(result.written),
            "skipped": list(result.skipped),
            "enabled": result.enabled,
            "settings_path": str(result.settings_path) if result.settings_path else None,
            "next": (
                "Open Obsidian and run Infinity Context: Connect this vault."
                if args.enable
                else "Enable Infinity Context in Obsidian community plugins."
            ),
        },
        as_json=args.json,
    )
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument(
        "--obsidian-config-dir",
        default=DEFAULT_OBSIDIAN_CONFIG_DIR,
        help="Obsidian config folder relative to the vault root.",
    )
    parser.add_argument("--space", dest="space_slug", default=DEFAULT_SPACE_SLUG)
    parser.add_argument(
        "--memory_scope",
        dest="memory_scope_external_ref",
        default=DEFAULT_MEMORY_SCOPE_EXTERNAL_REF,
    )
    parser.add_argument(
        "--api-url",
        default=_env("MEMORY_API_URL", "MEMORY_MCP_API_URL", default=DEFAULT_API_URL),
    )
    parser.add_argument(
        "--token",
        default=_env("MEMORY_SERVICE_TOKEN", "MEMORY_MCP_AUTH_TOKEN"),
    )
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--root-folder", default=DEFAULT_ROOT_FOLDER)
    parser.add_argument(
        "--layout",
        dest="layout_version",
        choices=("v1", "v2"),
        default=DEFAULT_LAYOUT_VERSION,
    )
    parser.add_argument("--json", action="store_true")


def _cmd_connect(args: argparse.Namespace) -> int:
    context = _context(args)
    result = context["setup"].execute(
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
        overwrite=args.overwrite,
    )
    _print(
        {
            "ok": True,
            "written": list(result.written),
            "skipped": list(result.skipped),
            "next": (
                "Run infinity-context-obsidian preview before export/import to inspect "
                "planned sync effects."
            ),
        },
        as_json=args.json,
    )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    context = _context(args)
    result = context["exporter"].execute(
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    conflict_artifacts = context["conflict_writer"].execute(
        direction="export",
        changes=result.changes,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    _print(
        {
            "ok": result.conflicts == 0,
            "exported": result.exported,
            "skipped": result.skipped,
            "conflicts": result.conflicts,
            "conflict_artifacts_written": conflict_artifacts.written,
            "paths": list(result.paths),
            "conflict_artifacts": list(conflict_artifacts.paths),
        },
        as_json=args.json,
    )
    return 0 if result.conflicts == 0 else 1


def _cmd_preview(args: argparse.Namespace) -> int:
    result = _context(args)["previewer"].execute(
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
        include_inbox=not args.no_inbox,
    )
    _print(_preview_payload(result), as_json=args.json)
    return 0 if result.ok else 1


def _cmd_import(args: argparse.Namespace) -> int:
    context = _context(args)
    result = _run_import(context=context, args=args, apply=args.apply)
    conflict_artifacts = context["conflict_writer"].execute(
        direction="import",
        changes=result.changes,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    payload = _import_payload(result, applied=args.apply)
    payload["conflict_artifacts_written"] = conflict_artifacts.written
    payload["conflict_artifacts"] = list(conflict_artifacts.paths)
    _print(payload, as_json=args.json)
    return 0 if result.conflicts == 0 else 1


def _cmd_sync(args: argparse.Namespace) -> int:
    context = _context(args)
    result = context["syncer"].execute(
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
        apply_import=args.apply_import,
        include_inbox=not args.no_inbox,
    )
    import_conflicts = context["conflict_writer"].execute(
        direction="import",
        changes=result.import_result.changes,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    export_conflicts = context["conflict_writer"].execute(
        direction="export",
        changes=result.export_result.changes,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    _print(
        _sync_payload(
            result,
            applied_import=args.apply_import,
            import_conflict_artifacts=import_conflicts.paths,
            export_conflict_artifacts=export_conflicts.paths,
        ),
        as_json=args.json,
    )
    return 0 if result.ok else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    result = DoctorVaultUseCase(vault_path=args.vault).execute(
        api_url=args.api_url,
        token=args.token or None,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
        root_folder=args.root_folder,
        layout_version=args.layout_version,
        obsidian_config_dir=args.obsidian_config_dir,
        require_plugin=not args.no_plugin,
        check_health=not args.no_health,
    )
    _print(_doctor_payload(result), as_json=args.json)
    return 0 if result.ok else 1


def _cmd_watch(args: argparse.Namespace) -> int:
    context = _context(args)
    iteration = 0
    print("infinity-context-obsidian: watching vault. Press Ctrl+C to stop.")
    while True:
        imported = _run_import(context=context, args=args, apply=args.apply_import)
        import_conflicts = context["conflict_writer"].execute(
            direction="import",
            changes=imported.changes,
            space_slug=args.space_slug,
            memory_scope_external_ref=args.memory_scope_external_ref,
        )
        print(
            "import "
            f"updated={imported.updated} "
            f"would_update={imported.would_update} "
            f"suggested={imported.suggested} "
            f"would_suggest={imported.would_suggest} "
            f"conflicts={imported.conflicts} "
            f"conflict_artifacts={import_conflicts.written}"
        )
        if iteration % max(args.export_every, 1) == 0:
            exported = context["exporter"].execute(
                space_slug=args.space_slug,
                memory_scope_external_ref=args.memory_scope_external_ref,
            )
            export_conflicts = context["conflict_writer"].execute(
                direction="export",
                changes=exported.changes,
                space_slug=args.space_slug,
                memory_scope_external_ref=args.memory_scope_external_ref,
            )
            print(
                "export "
                f"exported={exported.exported} "
                f"skipped={exported.skipped} "
                f"conflicts={exported.conflicts} "
                f"conflict_artifacts={export_conflicts.written}"
            )
        iteration += 1
        time.sleep(max(args.interval, 0.5))


def _context(args: argparse.Namespace) -> dict[str, object]:
    vault = FilesystemVault(args.vault)
    layout = ObsidianVaultLayout.from_values(
        root_folder=args.root_folder,
        version=args.layout_version,
    )
    state_path = (
        args.state or args.vault.expanduser() / ".infinity-context" / "obsidian-sync.sqlite3"
    )
    state = SqliteSyncStateStore(state_path)
    gateway = SdkMemoryGateway(
        InfinityContextClient(base_url=args.api_url, token=args.token or None)
    )
    exporter = ExportFactsToVaultUseCase(
        memory=gateway,
        vault=vault,
        state=state,
        layout=layout,
    )
    importer = ImportVaultChangesUseCase(
        memory=gateway,
        vault=vault,
        state=state,
        layout=layout,
    )
    inbox_importer = ImportInboxSuggestionsUseCase(
        memory=gateway,
        vault=vault,
        state=state,
        layout=layout,
    )
    return {
        "setup": SetupVaultUseCase(vault=vault, layout=layout),
        "exporter": exporter,
        "importer": importer,
        "inbox_importer": inbox_importer,
        "previewer": PreviewVaultSyncUseCase(
            memory=gateway,
            vault=vault,
            state=state,
            layout=layout,
        ),
        "syncer": SyncVaultOnceUseCase(
            importer=importer,
            inbox_importer=inbox_importer,
            exporter=exporter,
        ),
        "conflict_writer": WriteConflictArtifactsUseCase(vault=vault, layout=layout),
    }


def _run_import(
    *,
    context: dict[str, object],
    args: argparse.Namespace,
    apply: bool,
) -> ImportVaultChangesResult:
    facts = context["importer"].execute(
        apply=apply,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
    )
    if args.no_inbox:
        return facts
    inbox = context["inbox_importer"].execute(
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref,
        apply=apply,
    )
    return merge_import_results(facts, inbox)


def _import_payload(result: ImportVaultChangesResult, *, applied: bool) -> dict[str, object]:
    changes = result.changes
    return {
        "ok": result.conflicts == 0,
        "applied": applied,
        "updated": result.updated,
        "removed": result.removed,
        "would_update": result.would_update,
        "suggested": result.suggested,
        "would_suggest": result.would_suggest,
        "conflicts": result.conflicts,
        "changes": [
            {
                **asdict(change),
                "status": change.status.value,
                "path": change.path.as_posix(),
            }
            for change in changes
        ],
    }


def _sync_payload(
    result: SyncVaultOnceResult,
    *,
    applied_import: bool,
    import_conflict_artifacts: tuple[str, ...],
    export_conflict_artifacts: tuple[str, ...],
) -> dict[str, object]:
    import_payload = _import_payload(result.import_result, applied=applied_import)
    import_payload["conflict_artifacts_written"] = len(import_conflict_artifacts)
    import_payload["conflict_artifacts"] = list(import_conflict_artifacts)
    return {
        "ok": result.ok,
        "applied_import": applied_import,
        "export_skipped": result.export_skipped,
        "export_skipped_reason": result.export_skipped_reason,
        "import": import_payload,
        "export": {
            "exported": result.export_result.exported,
            "skipped": result.export_result.skipped,
            "conflicts": result.export_result.conflicts,
            "conflict_artifacts_written": len(export_conflict_artifacts),
            "paths": list(result.export_result.paths),
            "conflict_artifacts": list(export_conflict_artifacts),
            "changes": [
                {
                    **asdict(change),
                    "status": change.status.value,
                    "path": change.path.as_posix(),
                }
                for change in result.export_result.changes
            ],
        },
    }


def _preview_payload(result: PreviewVaultSyncResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "export": {
            "would_export": result.export_plan.would_export,
            "skipped": result.export_plan.skipped,
            "conflicts": result.export_plan.conflicts,
            "changes": [
                {
                    **asdict(change),
                    "status": change.status.value,
                    "path": change.path.as_posix(),
                }
                for change in result.export_plan.changes
            ],
        },
        "import": {
            "would_update": result.import_plan.would_update,
            "would_suggest": result.import_plan.would_suggest,
            "conflicts": result.import_plan.conflicts,
            "changes": [
                {
                    **asdict(change),
                    "status": change.status.value,
                    "path": change.path.as_posix(),
                }
                for change in result.import_plan.changes
            ],
        },
    }


def _doctor_payload(result: DoctorResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "required": check.required,
                "message": check.message,
            }
            for check in result.checks
        ],
    }


def _print(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        if key == "paths" and isinstance(value, list):
            print(f"{key}:")
            for item in value:
                print(f"  {item}")
        else:
            print(f"{key}: {value}")


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


if __name__ == "__main__":
    raise SystemExit(main())
