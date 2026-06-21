"""Infinity Context local CLI."""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

import httpx
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.memory_scope_snapshots import (
    default_manifest_path,
    verify_snapshot_manifest,
    write_snapshot_bundle,
)
from infinity_context_sdk import InfinityContextClient, InfinityContextError, ReadScope

from infinity_context_cli import __version__
from infinity_context_cli.config import DEFAULT_API_URL, init_local_config, load_config
from infinity_context_cli.doctor import doctor_payload, run_doctor
from infinity_context_cli.mcp_config import SUPPORTED_AGENTS, render_mcp_config, write_mcp_config
from infinity_context_cli.runtime import DockerComposeRuntime


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
    except (InfinityContextError, httpx.HTTPError, ValueError) as exc:
        print(
            f"infinity-context: {_safe_cli_text(str(exc).strip() or exc.__class__.__name__)}",
            file=sys.stderr,
        )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infinity-context")
    parser.add_argument("--version", action="version", version=f"infinity-context {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize local Infinity Context config.")
    init_parser.add_argument(
        "--home",
        default=None,
        help="Install home. Defaults to ~/.infinity-context.",
    )
    init_parser.add_argument("--repo-dir", default=None, help="Infinity Context repo root.")
    init_parser.add_argument("--api-url", default=DEFAULT_API_URL)
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--json", action="store_true")
    init_parser.set_defaults(handler=_cmd_init)

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Initialize config, start local runtime, and write MCP config.",
    )
    quickstart_parser.add_argument("--home", default=None)
    quickstart_parser.add_argument("--repo-dir", default=None)
    quickstart_parser.add_argument("--api-url", default=DEFAULT_API_URL)
    quickstart_profile = quickstart_parser.add_mutually_exclusive_group()
    quickstart_profile.add_argument("--lite", action="store_true", help="Start lite stack.")
    quickstart_profile.add_argument("--full", action="store_true", help="Start full stack.")
    quickstart_parser.add_argument(
        "--agent",
        action="append",
        choices=sorted(SUPPORTED_AGENTS),
        default=None,
        help="Agent config to write. Repeat for multiple agents. Defaults to codex.",
    )
    quickstart_parser.add_argument("--all-agents", action="store_true")
    quickstart_parser.add_argument("--no-start", action="store_true")
    quickstart_parser.add_argument("--no-wait", action="store_true")
    quickstart_parser.add_argument(
        "--open-ui",
        action="store_true",
        help="Open the local memory browser after setup.",
    )
    quickstart_parser.add_argument("--wait-seconds", type=float, default=90.0)
    quickstart_parser.add_argument("--force", action="store_true")
    quickstart_parser.add_argument(
        "--include-token",
        action="store_true",
        help="Write private MCP configs with the local service token.",
    )
    quickstart_parser.add_argument("--json", action="store_true")
    quickstart_parser.set_defaults(handler=_cmd_quickstart)

    up_parser = subparsers.add_parser("up", help="Start local Infinity Context.")
    compose_profile = up_parser.add_mutually_exclusive_group()
    compose_profile.add_argument("--lite", action="store_true", help="Start lite local stack.")
    compose_profile.add_argument("--full", action="store_true", help="Start full provider stack.")
    up_parser.set_defaults(handler=_cmd_up)

    down_parser = subparsers.add_parser("down", help="Stop local Infinity Context.")
    down_parser.set_defaults(handler=_cmd_down)

    restart_parser = subparsers.add_parser("restart", help="Restart local Infinity Context.")
    compose_profile = restart_parser.add_mutually_exclusive_group()
    compose_profile.add_argument("--lite", action="store_true")
    compose_profile.add_argument("--full", action="store_true")
    restart_parser.set_defaults(handler=_cmd_restart)

    status_parser = subparsers.add_parser("status", help="Check local Infinity Context status.")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=_cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="Run local diagnostics.")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=_cmd_doctor)

    logs_parser = subparsers.add_parser("logs", help="Show docker compose logs.")
    logs_parser.add_argument("--service", default=None)
    logs_parser.add_argument("--tail", type=int, default=120)
    logs_parser.set_defaults(handler=_cmd_logs)

    ui_parser = subparsers.add_parser("ui", help="Print or open the local memory browser URL.")
    ui_parser.add_argument("--open", action="store_true", dest="open_browser")
    ui_parser.add_argument("--check", action="store_true", help="Check API readiness first.")
    ui_parser.add_argument("--json", action="store_true")
    ui_parser.set_defaults(handler=_cmd_ui)

    mcp_parser = subparsers.add_parser("mcp-config", help="Print or write MCP config.")
    mcp_parser.add_argument("--agent", choices=sorted(SUPPORTED_AGENTS), required=True)
    mcp_parser.add_argument("--write", action="store_true")
    mcp_parser.add_argument("--include-token", action="store_true")
    mcp_parser.set_defaults(handler=_cmd_mcp_config)

    digest_parser = subparsers.add_parser("digest", help="Build a memory digest.")
    digest_parser.add_argument("topic")
    digest_parser.add_argument("--space", dest="space_slug", default=None)
    digest_parser.add_argument("--memory_scope", dest="memory_scope_external_ref", default=None)
    digest_parser.add_argument("--thread", dest="thread_external_ref", default=None)
    digest_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    digest_parser.add_argument("--token-budget", type=int, default=2400)
    digest_parser.add_argument("--max-facts", type=int, default=20)
    digest_parser.add_argument("--max-chunks", type=int, default=20)
    digest_parser.add_argument("--max-suggestions", type=int, default=10)
    digest_parser.add_argument("--include-superseded", action="store_true")
    digest_parser.add_argument("--no-suggestions", action="store_true")
    digest_parser.add_argument("--no-related", action="store_true")
    digest_parser.set_defaults(handler=_cmd_digest)

    insights_parser = subparsers.add_parser("insights", help="Build memory health insights.")
    insights_parser.add_argument("--space", dest="space_slug", default=None)
    insights_parser.add_argument("--memory_scope", dest="memory_scope_external_ref", default=None)
    insights_parser.add_argument("--thread", dest="thread_external_ref", default=None)
    insights_parser.add_argument("--max-facts", type=int, default=200)
    insights_parser.add_argument("--max-documents", type=int, default=100)
    insights_parser.add_argument("--max-suggestions", type=int, default=100)
    insights_parser.add_argument("--max-captures", type=int, default=100)
    insights_parser.add_argument("--max-activity", type=int, default=50)
    insights_parser.add_argument("--json", action="store_true")
    insights_parser.set_defaults(handler=_cmd_insights)

    export_parser = subparsers.add_parser(
        "memory_scope-export",
        help="Export a portable memory_scope snapshot.",
    )
    export_parser.add_argument("--space", dest="space_slug", default=None)
    export_parser.add_argument("--memory_scope", dest="memory_scope_external_ref", default=None)
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument(
        "--include-private",
        action="store_true",
        help="Export restorable raw memory text. Default output is redacted.",
    )
    export_parser.add_argument("--manifest-out", type=Path, default=None)
    export_parser.add_argument("--no-manifest", action="store_true")
    export_parser.set_defaults(handler=_cmd_memory_scope_export)

    verify_parser = subparsers.add_parser(
        "memory_scope-verify",
        help="Verify a memory_scope snapshot manifest before import or git sync.",
    )
    verify_parser.add_argument("--snapshot", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, default=None)
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(handler=_cmd_memory_scope_verify)

    import_parser = subparsers.add_parser(
        "memory_scope-import",
        help="Import a portable memory_scope snapshot. Dry-run by default.",
    )
    import_parser.add_argument("--space", dest="space_slug", default=None)
    import_parser.add_argument("--memory_scope", dest="memory_scope_external_ref", default=None)
    import_parser.add_argument("--in", dest="in_path", type=Path, required=True)
    import_parser.add_argument(
        "--merge-strategy",
        choices=(
            "fail_on_conflict",
            "skip_existing",
            "create_new_memory_scope",
            "supersede_matching_facts",
        ),
        default="fail_on_conflict",
    )
    import_parser.add_argument("--source-name", default="cli-memory_scope-snapshot")
    import_parser.add_argument("--manifest", type=Path, default=None)
    import_parser.add_argument("--apply", action="store_true")
    import_parser.add_argument("--confirmed", action="store_true")
    import_parser.set_defaults(handler=_cmd_memory_scope_import)

    preview_import_parser = subparsers.add_parser(
        "memory_scope-import-preview",
        help="Build a read-only memory_scope snapshot import preview.",
    )
    preview_import_parser.add_argument("--space", dest="space_slug", default=None)
    preview_import_parser.add_argument(
        "--memory_scope", dest="memory_scope_external_ref", default=None
    )
    preview_import_parser.add_argument("--in", dest="in_path", type=Path, required=True)
    preview_import_parser.add_argument(
        "--merge-strategy",
        choices=(
            "fail_on_conflict",
            "skip_existing",
            "create_new_memory_scope",
            "supersede_matching_facts",
        ),
        default="fail_on_conflict",
    )
    preview_import_parser.add_argument("--manifest", type=Path, default=None)
    preview_import_parser.add_argument("--json", action="store_true")
    preview_import_parser.set_defaults(handler=_cmd_memory_scope_import_preview)

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo_dir).expanduser() if args.repo_dir else load_config().repo_dir
    config = init_local_config(
        home=Path(args.home).expanduser() if args.home else load_config().home,
        repo_dir=repo_dir,
        api_url=args.api_url,
        force=args.force,
    )
    payload = {
        "ok": True,
        "home": str(config.home),
        "repo_dir": str(config.repo_dir),
        "api_url": config.api_url,
        "env_path": str(config.env_path),
        "config_path": str(config.config_path),
        "token_configured": bool(config.service_token),
    }
    _print_payload(payload, as_json=args.json)
    return 0


def _cmd_quickstart(args: argparse.Namespace) -> int:
    current = load_config()
    repo_dir = Path(args.repo_dir).expanduser() if args.repo_dir else current.repo_dir
    home = Path(args.home).expanduser() if args.home else current.home
    config = init_local_config(
        home=home,
        repo_dir=repo_dir,
        api_url=args.api_url,
        force=args.force,
    )
    compose_profile = "full" if args.full else "lite"
    runtime_result = None
    if not args.no_start:
        runtime_result = DockerComposeRuntime(config=config).up(compose_profile)
    status = None
    if runtime_result is not None and runtime_result.ok:
        status = (
            _status_payload(config)
            if args.no_wait
            else _wait_for_status(config, timeout_seconds=args.wait_seconds)
        )
    agents = sorted(SUPPORTED_AGENTS) if args.all_agents else sorted(set(args.agent or ["codex"]))
    mcp_configs = [
        {
            "agent": agent,
            "path": str(
                write_mcp_config(
                    agent=agent,
                    config=config,
                    include_token=args.include_token,
                )
            ),
            "token_included": bool(args.include_token),
        }
        for agent in agents
    ]
    payload = {
        "ok": _quickstart_ok(
            runtime_result=runtime_result,
            status=status,
            no_start=args.no_start,
        ),
        "home": str(config.home),
        "repo_dir": str(config.repo_dir),
        "api_url": config.api_url,
        "ui_url": _ui_url(config),
        "compose_profile": compose_profile,
        "runtime": _runtime_payload(runtime_result) if runtime_result is not None else None,
        "status": status,
        "mcp_configs": mcp_configs,
        "token_included": bool(args.include_token),
        "opened_ui": False,
        "local_experience": _quickstart_local_experience(
            config=config,
            agents=agents,
            mcp_configs=mcp_configs,
            status=status,
            no_start=args.no_start,
        ),
        "next_steps": _quickstart_next_steps(
            agents=agents,
            home=config.home,
            include_token=args.include_token,
            no_start=args.no_start,
            open_ui=args.open_ui,
        ),
    }
    if args.open_ui and payload["ok"]:
        payload["opened_ui"] = bool(webbrowser.open(payload["ui_url"]))
    _print_quickstart_payload(payload, as_json=args.json)
    return 0 if payload["ok"] else 1


def _cmd_up(args: argparse.Namespace) -> int:
    config = load_config()
    compose_profile = "full" if args.full else "lite"
    result = DockerComposeRuntime(config=config).up(compose_profile)
    _print_runtime_result(result)
    return 0 if result.ok else result.returncode or 1


def _cmd_down(_args: argparse.Namespace) -> int:
    result = DockerComposeRuntime(config=load_config()).down()
    _print_runtime_result(result)
    return 0 if result.ok else result.returncode or 1


def _cmd_restart(args: argparse.Namespace) -> int:
    config = load_config()
    runtime = DockerComposeRuntime(config=config)
    down = runtime.down()
    _print_runtime_result(down)
    if not down.ok:
        return down.returncode or 1
    compose_profile = "full" if args.full else "lite"
    up = runtime.up(compose_profile)
    _print_runtime_result(up)
    return 0 if up.ok else up.returncode or 1


def _cmd_status(args: argparse.Namespace) -> int:
    config = load_config()
    payload = _status_payload(config)
    _print_payload(payload, as_json=args.json)
    return 0 if payload["ok"] else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config()
    payload = doctor_payload(config, run_doctor(config))
    _print_payload(payload, as_json=args.json)
    return 0 if payload["ok"] else 1


def _cmd_logs(args: argparse.Namespace) -> int:
    result = DockerComposeRuntime(config=load_config()).logs(args.service, args.tail)
    _print_runtime_result(result)
    return 0 if result.ok else result.returncode or 1


def _cmd_ui(args: argparse.Namespace) -> int:
    config = load_config()
    payload: dict[str, Any] = {
        "ok": True,
        "ui_url": _ui_url(config),
        "api_url": config.api_url,
        "opened": False,
        "status": None,
    }
    if args.check:
        status = _status_payload(config)
        payload["status"] = status
        payload["ok"] = bool(status.get("ok"))
    if args.open_browser:
        payload["opened"] = bool(webbrowser.open(payload["ui_url"]))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload["ui_url"])
        if args.check and not payload["ok"]:
            print("warning: local API is not ready", file=sys.stderr)
    return 0 if payload["ok"] else 1


def _cmd_mcp_config(args: argparse.Namespace) -> int:
    config = load_config()
    if args.write:
        path = write_mcp_config(
            agent=args.agent,
            config=config,
            include_token=args.include_token,
        )
        print(str(path))
    else:
        print(
            render_mcp_config(
                agent=args.agent,
                config=config,
                include_token=args.include_token,
            )
        )
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    config = load_config()
    client = InfinityContextClient(base_url=config.api_url, token=config.service_token)
    payload = client.build_digest(
        topic=args.topic,
        read_scope=ReadScope(
            space_slug=args.space_slug or config.default_space_slug,
            memory_scope_external_ref=args.memory_scope_external_ref
            or config.default_memory_scope_external_ref,
            thread_external_ref=args.thread_external_ref,
        ),
        token_budget=args.token_budget,
        max_facts=args.max_facts,
        max_chunks=args.max_chunks,
        max_suggestions=args.max_suggestions,
        include_pending_suggestions=not args.no_suggestions,
        include_superseded=args.include_superseded,
        include_related=not args.no_related,
        format=args.format,
    )
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(str(data.get("rendered_markdown") or ""))
    return 0


def _cmd_insights(args: argparse.Namespace) -> int:
    config = load_config()
    client = InfinityContextClient(base_url=config.api_url, token=config.service_token)
    payload = client.build_insights(
        scope=_read_scope_from_args(args, config),
        max_facts=args.max_facts,
        max_documents=args.max_documents,
        max_suggestions=args.max_suggestions,
        max_captures=args.max_captures,
        max_activity=args.max_activity,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    print(f"health_score: {data.get('health_score')}")
    metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
    action_items = data.get("action_items", [])
    consolidation_plan = data.get("consolidation_plan", [])
    print(f"pending_suggestions: {_nested(metrics, 'suggestions', 'pending')}")
    print(f"expired_active_facts: {_nested(metrics, 'facts', 'expired_active')}")
    print(f"documents_without_chunks: {_nested(metrics, 'documents', 'without_chunks')}")
    print(f"action_items: {len(action_items) if isinstance(action_items, list) else 0}")
    print(
        "consolidation_plan: "
        f"{len(consolidation_plan) if isinstance(consolidation_plan, list) else 0}"
    )
    if isinstance(consolidation_plan, list):
        for item in consolidation_plan[:3]:
            if not isinstance(item, dict):
                continue
            fact_ids = item.get("candidate_fact_ids")
            fact_label = (
                ", ".join(str(value) for value in fact_ids[:3])
                if isinstance(fact_ids, list)
                else ""
            )
            print(
                "  - "
                f"{item.get('plan_type')}: {item.get('canonical_candidate_id')}"
                f"{' <- ' + fact_label if fact_label else ''}"
            )
    return 0


def _cmd_memory_scope_export(args: argparse.Namespace) -> int:
    config = load_config()
    out_path = args.out.expanduser()
    redacted = not args.include_private
    manifest_path = None
    if not args.no_manifest:
        manifest_path = (
            args.manifest_out.expanduser()
            if args.manifest_out is not None
            else default_manifest_path(out_path)
        )
    client = InfinityContextClient(base_url=config.api_url, token=config.service_token)
    payload = client.export_memory_scope_snapshot(
        space_slug=args.space_slug or config.default_space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref
        or config.default_memory_scope_external_ref,
        redacted=redacted,
    )
    snapshot = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(snapshot, dict):
        raise ValueError("memory_scope export response did not contain a snapshot object")
    write_snapshot_bundle(
        snapshot=snapshot,
        snapshot_path=out_path,
        manifest_path=manifest_path,
        space_slug=args.space_slug or config.default_space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref
        or config.default_memory_scope_external_ref,
        redacted=redacted,
    )
    print(f"snapshot: {out_path}")
    if manifest_path is not None:
        print(f"manifest: {manifest_path}")
    return 0


def _cmd_memory_scope_verify(args: argparse.Namespace) -> int:
    snapshot_path = args.snapshot.expanduser()
    manifest_path = (
        args.manifest.expanduser()
        if args.manifest is not None
        else default_manifest_path(snapshot_path)
    )
    result = verify_snapshot_manifest(
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"ok: {result['ok']}")
        print(f"snapshot: {snapshot_path}")
        print(f"manifest: {manifest_path}")
        if result["errors"]:
            print(f"errors: {', '.join(result['errors'])}")
    return 0 if result["ok"] else 1


def _cmd_memory_scope_import(args: argparse.Namespace) -> int:
    snapshot_path = args.in_path.expanduser()
    if args.manifest is not None:
        verification = verify_snapshot_manifest(
            snapshot_path=snapshot_path,
            manifest_path=args.manifest.expanduser(),
        )
        if not verification["ok"]:
            raise ValueError(
                "memory_scope snapshot manifest verification failed: "
                + ", ".join(verification["errors"])
            )
    if args.apply and not args.confirmed:
        raise ValueError("memory_scope-import --apply requires --confirmed")
    config = load_config()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    client = InfinityContextClient(base_url=config.api_url, token=config.service_token)
    payload = client.import_memory_scope_snapshot(
        space_slug=args.space_slug or config.default_space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref
        or config.default_memory_scope_external_ref,
        snapshot=snapshot,
        dry_run=not args.apply,
        merge_strategy=args.merge_strategy,
        confirmed=args.confirmed,
        source_name=args.source_name,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_memory_scope_import_preview(args: argparse.Namespace) -> int:
    snapshot_path = args.in_path.expanduser()
    manifest = None
    if args.manifest is not None:
        manifest_path = args.manifest.expanduser()
        verification = verify_snapshot_manifest(
            snapshot_path=snapshot_path,
            manifest_path=manifest_path,
        )
        if not verification["ok"]:
            raise ValueError(
                "memory_scope snapshot manifest verification failed: "
                + ", ".join(verification["errors"])
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = load_config()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    client = InfinityContextClient(base_url=config.api_url, token=config.service_token)
    payload = client.preview_memory_scope_snapshot_import(
        space_slug=args.space_slug or config.default_space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref
        or config.default_memory_scope_external_ref,
        snapshot=snapshot,
        manifest=manifest,
        merge_strategy=args.merge_strategy,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    preview = data.get("preview", {}) if isinstance(data.get("preview"), dict) else {}
    print(f"status: {data.get('status')}")
    print(f"dry_run: {data.get('dry_run')}")
    print(f"conflict_count: {data.get('conflict_count', preview.get('conflict_count'))}")
    print(f"would_import: {json.dumps(preview.get('would_import', {}), sort_keys=True)}")
    print(f"would_skip: {json.dumps(preview.get('would_skip', {}), sort_keys=True)}")
    if preview.get("would_supersede"):
        print(f"would_supersede: {json.dumps(preview['would_supersede'], sort_keys=True)}")
    warnings = preview.get("warnings", [])
    if warnings:
        print(f"warnings: {', '.join(str(item) for item in warnings)}")
    return 0


def _status_payload(config) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {config.service_token}"}
    payload: dict[str, Any] = {
        "ok": False,
        "api_url": config.api_url,
        "home": str(config.home),
        "repo_dir": str(config.repo_dir),
        "health": None,
        "capabilities": None,
    }
    try:
        with httpx.Client(base_url=config.api_url, timeout=3.0, headers=headers) as client:
            health = client.get("/v1/health")
            capabilities = client.get("/v1/capabilities")
            payload["health"] = _response_payload(health)
            payload["capabilities"] = _response_payload(capabilities)
            payload["ok"] = health.is_success and capabilities.is_success
    except httpx.HTTPError as exc:
        payload["error"] = exc.__class__.__name__
    return payload


def _wait_for_status(config, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    status = _status_payload(config)
    while not status["ok"] and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        status = _status_payload(config)
    return status


def _ui_url(config) -> str:
    return f"{config.api_url.rstrip('/')}/ui/"


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"body": _safe_cli_text(response.text, limit=500)}
    return {"status_code": response.status_code, "data": payload}


def _runtime_payload(result) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "command": list(result.command),
        "returncode": result.returncode,
        "stdout": _safe_cli_text(result.stdout, limit=1000),
        "stderr": _safe_cli_text(result.stderr, limit=1000),
    }


def _quickstart_ok(*, runtime_result, status: dict[str, Any] | None, no_start: bool) -> bool:
    if no_start:
        return True
    return bool(runtime_result is not None and runtime_result.ok and status and status.get("ok"))


def _quickstart_next_steps(
    *,
    agents: list[str],
    home: Path,
    include_token: bool,
    no_start: bool,
    open_ui: bool,
) -> list[str]:
    steps = []
    if no_start:
        steps.append("Start the local runtime with: infinity-context up --lite")
    steps.append("Check readiness with: infinity-context status")
    if open_ui:
        steps.append("Visual memory opened with: infinity-context ui --open")
    else:
        steps.append("Open visual memory with: infinity-context ui --open")
    if include_token:
        steps.append("Add the generated MCP config path to your agent.")
    else:
        steps.append(f"Generated MCP config reads its local token from: {home / '.env'}")
        steps.append("Add the generated MCP config path to your agent.")
    if agents:
        steps.append(f"Generated MCP config for: {', '.join(agents)}")
    return steps


def _quickstart_local_experience(
    *,
    config,
    agents: list[str],
    mcp_configs: list[dict[str, Any]],
    status: dict[str, Any] | None,
    no_start: bool,
) -> dict[str, Any]:
    runtime_ready = bool(status and status.get("ok"))
    mcp_paths = [item["path"] for item in mcp_configs if item.get("path")]
    return {
        "status": _quickstart_local_experience_status(
            no_start=no_start,
            runtime_ready=runtime_ready,
            mcp_ready=bool(mcp_paths),
        ),
        "api_url": config.api_url,
        "ui_url": _ui_url(config),
        "visual_memory_ready": runtime_ready,
        "mcp_ready": bool(mcp_paths),
        "ready_agents": agents,
        "mcp_config_paths": mcp_paths,
        "first_capture": {
            "surface": "visual_memory_browser",
            "tab": "Capture",
            "supports": ["text_note", "file_evidence"],
        },
    }


def _quickstart_local_experience_status(
    *,
    no_start: bool,
    runtime_ready: bool,
    mcp_ready: bool,
) -> str:
    if no_start and mcp_ready:
        return "configured_not_started"
    if runtime_ready and mcp_ready:
        return "ready"
    if not runtime_ready:
        return "runtime_not_ready"
    return "mcp_config_not_ready"


def _print_quickstart_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"ok: {payload['ok']}")
    print(f"home: {payload['home']}")
    print(f"api_url: {payload['api_url']}")
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        print(f"runtime: {'started' if runtime.get('ok') else 'failed'}")
        if not runtime.get("ok") and runtime.get("stderr"):
            print(f"runtime_error: {runtime['stderr']}", file=sys.stderr)
    else:
        print("runtime: skipped")
    status = payload.get("status")
    if isinstance(status, dict):
        print(f"status: {'ready' if status.get('ok') else 'not_ready'}")
    experience = payload.get("local_experience")
    if isinstance(experience, dict):
        print(f"experience: {experience.get('status')}")
        print(
            "visual_memory: "
            f"{'ready' if experience.get('visual_memory_ready') else 'not_ready'} "
            f"({experience.get('ui_url')})"
        )
        ready_agents = experience.get("ready_agents") or []
        if ready_agents:
            print(f"mcp_ready_for: {', '.join(str(agent) for agent in ready_agents)}")
    if payload.get("opened_ui"):
        print(f"ui: opened {payload.get('ui_url')}")
    else:
        print(f"ui: {payload.get('ui_url')}")
    for item in payload.get("mcp_configs", []):
        if isinstance(item, dict):
            token_note = (
                "private token included" if item.get("token_included") else "token redacted"
            )
            print(f"mcp_config[{item.get('agent')}]: {item.get('path')} ({token_note})")
    print("next_steps:")
    for step in payload.get("next_steps", []):
        print(f"  - {step}")


def _print_runtime_result(result) -> None:
    if result.stdout:
        print(_safe_cli_text(result.stdout), end="")
    if result.stderr:
        print(_safe_cli_text(result.stderr), end="", file=sys.stderr)


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _read_scope_from_args(args: argparse.Namespace, config) -> ReadScope:
    return ReadScope(
        space_slug=args.space_slug or config.default_space_slug,
        memory_scope_external_ref=args.memory_scope_external_ref
        or config.default_memory_scope_external_ref,
        thread_external_ref=args.thread_external_ref,
    )


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_cli_text(value: str, *, limit: int | None = None) -> str:
    redacted = redact_sensitive_text(value or "Unexpected CLI error")
    return redacted if limit is None else redacted[:limit]
