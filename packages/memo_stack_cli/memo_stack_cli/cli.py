"""Memo Stack local CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from memo_stack_sdk import MemoStackClient, MemoStackError, ReadScope

from memo_stack_cli import __version__
from memo_stack_cli.config import DEFAULT_API_URL, init_local_config, load_config
from memo_stack_cli.doctor import doctor_payload, run_doctor
from memo_stack_cli.mcp_config import SUPPORTED_AGENTS, render_mcp_config, write_mcp_config
from memo_stack_cli.runtime import DockerComposeRuntime
from memo_stack_cli.snapshots import (
    default_manifest_path,
    verify_snapshot_manifest,
    write_snapshot_bundle,
)


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
    except (MemoStackError, httpx.HTTPError, ValueError) as exc:
        print(f"memo-stack: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memo-stack")
    parser.add_argument("--version", action="version", version=f"memo-stack {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize local Memo Stack config.")
    init_parser.add_argument(
        "--home",
        default=None,
        help="Install home. Defaults to ~/.memo-stack.",
    )
    init_parser.add_argument("--repo-dir", default=None, help="Memo Stack repo root.")
    init_parser.add_argument("--api-url", default=DEFAULT_API_URL)
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--json", action="store_true")
    init_parser.set_defaults(handler=_cmd_init)

    up_parser = subparsers.add_parser("up", help="Start local Memo Stack.")
    profile = up_parser.add_mutually_exclusive_group()
    profile.add_argument("--lite", action="store_true", help="Start lite local stack.")
    profile.add_argument("--full", action="store_true", help="Start full provider stack.")
    up_parser.set_defaults(handler=_cmd_up)

    down_parser = subparsers.add_parser("down", help="Stop local Memo Stack.")
    down_parser.set_defaults(handler=_cmd_down)

    restart_parser = subparsers.add_parser("restart", help="Restart local Memo Stack.")
    profile = restart_parser.add_mutually_exclusive_group()
    profile.add_argument("--lite", action="store_true")
    profile.add_argument("--full", action="store_true")
    restart_parser.set_defaults(handler=_cmd_restart)

    status_parser = subparsers.add_parser("status", help="Check local Memo Stack status.")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=_cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="Run local diagnostics.")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=_cmd_doctor)

    logs_parser = subparsers.add_parser("logs", help="Show docker compose logs.")
    logs_parser.add_argument("--service", default=None)
    logs_parser.add_argument("--tail", type=int, default=120)
    logs_parser.set_defaults(handler=_cmd_logs)

    mcp_parser = subparsers.add_parser("mcp-config", help="Print or write MCP config.")
    mcp_parser.add_argument("--agent", choices=sorted(SUPPORTED_AGENTS), required=True)
    mcp_parser.add_argument("--write", action="store_true")
    mcp_parser.add_argument("--include-token", action="store_true")
    mcp_parser.set_defaults(handler=_cmd_mcp_config)

    digest_parser = subparsers.add_parser("digest", help="Build a memory digest.")
    digest_parser.add_argument("topic")
    digest_parser.add_argument("--space", dest="space_slug", default=None)
    digest_parser.add_argument("--profile", dest="profile_external_ref", default=None)
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
    insights_parser.add_argument("--profile", dest="profile_external_ref", default=None)
    insights_parser.add_argument("--thread", dest="thread_external_ref", default=None)
    insights_parser.add_argument("--max-facts", type=int, default=200)
    insights_parser.add_argument("--max-documents", type=int, default=100)
    insights_parser.add_argument("--max-suggestions", type=int, default=100)
    insights_parser.add_argument("--max-captures", type=int, default=100)
    insights_parser.add_argument("--json", action="store_true")
    insights_parser.set_defaults(handler=_cmd_insights)

    export_parser = subparsers.add_parser(
        "profile-export",
        help="Export a portable profile snapshot.",
    )
    export_parser.add_argument("--space", dest="space_slug", default=None)
    export_parser.add_argument("--profile", dest="profile_external_ref", default=None)
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument(
        "--include-private",
        action="store_true",
        help="Export restorable raw memory text. Default output is redacted.",
    )
    export_parser.add_argument("--manifest-out", type=Path, default=None)
    export_parser.add_argument("--no-manifest", action="store_true")
    export_parser.set_defaults(handler=_cmd_profile_export)

    verify_parser = subparsers.add_parser(
        "profile-verify",
        help="Verify a profile snapshot manifest before import or git sync.",
    )
    verify_parser.add_argument("--snapshot", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, default=None)
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(handler=_cmd_profile_verify)

    import_parser = subparsers.add_parser(
        "profile-import",
        help="Import a portable profile snapshot. Dry-run by default.",
    )
    import_parser.add_argument("--space", dest="space_slug", default=None)
    import_parser.add_argument("--profile", dest="profile_external_ref", default=None)
    import_parser.add_argument("--in", dest="in_path", type=Path, required=True)
    import_parser.add_argument(
        "--merge-strategy",
        choices=(
            "fail_on_conflict",
            "skip_existing",
            "create_new_profile",
            "supersede_matching_facts",
        ),
        default="fail_on_conflict",
    )
    import_parser.add_argument("--source-name", default="cli-profile-snapshot")
    import_parser.add_argument("--manifest", type=Path, default=None)
    import_parser.add_argument("--apply", action="store_true")
    import_parser.add_argument("--confirmed", action="store_true")
    import_parser.set_defaults(handler=_cmd_profile_import)

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


def _cmd_up(args: argparse.Namespace) -> int:
    config = load_config()
    profile = "full" if args.full else "lite"
    result = DockerComposeRuntime(config=config).up(profile)
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
    profile = "full" if args.full else "lite"
    up = runtime.up(profile)
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
    client = MemoStackClient(base_url=config.api_url, token=config.service_token)
    payload = client.build_digest(
        topic=args.topic,
        read_scope=ReadScope(
            space_slug=args.space_slug or config.default_space_slug,
            profile_external_ref=args.profile_external_ref
            or config.default_profile_external_ref,
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
    client = MemoStackClient(base_url=config.api_url, token=config.service_token)
    payload = client.build_insights(
        scope=_read_scope_from_args(args, config),
        max_facts=args.max_facts,
        max_documents=args.max_documents,
        max_suggestions=args.max_suggestions,
        max_captures=args.max_captures,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    print(f"health_score: {data.get('health_score')}")
    metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
    action_items = data.get("action_items", [])
    print(f"pending_suggestions: {_nested(metrics, 'suggestions', 'pending')}")
    print(f"expired_active_facts: {_nested(metrics, 'facts', 'expired_active')}")
    print(f"documents_without_chunks: {_nested(metrics, 'documents', 'without_chunks')}")
    print(f"action_items: {len(action_items) if isinstance(action_items, list) else 0}")
    return 0


def _cmd_profile_export(args: argparse.Namespace) -> int:
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
    client = MemoStackClient(base_url=config.api_url, token=config.service_token)
    payload = client.export_profile_snapshot(
        space_slug=args.space_slug or config.default_space_slug,
        profile_external_ref=args.profile_external_ref or config.default_profile_external_ref,
        redacted=redacted,
    )
    snapshot = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(snapshot, dict):
        raise ValueError("profile export response did not contain a snapshot object")
    write_snapshot_bundle(
        snapshot=snapshot,
        snapshot_path=out_path,
        manifest_path=manifest_path,
        space_slug=args.space_slug or config.default_space_slug,
        profile_external_ref=args.profile_external_ref or config.default_profile_external_ref,
        redacted=redacted,
    )
    print(f"snapshot: {out_path}")
    if manifest_path is not None:
        print(f"manifest: {manifest_path}")
    return 0


def _cmd_profile_verify(args: argparse.Namespace) -> int:
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


def _cmd_profile_import(args: argparse.Namespace) -> int:
    snapshot_path = args.in_path.expanduser()
    if args.manifest is not None:
        verification = verify_snapshot_manifest(
            snapshot_path=snapshot_path,
            manifest_path=args.manifest.expanduser(),
        )
        if not verification["ok"]:
            raise ValueError(
                "profile snapshot manifest verification failed: "
                + ", ".join(verification["errors"])
            )
    if args.apply and not args.confirmed:
        raise ValueError("profile-import --apply requires --confirmed")
    config = load_config()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    client = MemoStackClient(base_url=config.api_url, token=config.service_token)
    payload = client.import_profile_snapshot(
        space_slug=args.space_slug or config.default_space_slug,
        profile_external_ref=args.profile_external_ref or config.default_profile_external_ref,
        snapshot=snapshot,
        dry_run=not args.apply,
        merge_strategy=args.merge_strategy,
        confirmed=args.confirmed,
        source_name=args.source_name,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
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


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"body": response.text[:500]}
    return {"status_code": response.status_code, "data": payload}


def _print_runtime_result(result) -> None:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _read_scope_from_args(args: argparse.Namespace, config) -> ReadScope:
    return ReadScope(
        space_slug=args.space_slug or config.default_space_slug,
        profile_external_ref=args.profile_external_ref
        or config.default_profile_external_ref,
        thread_external_ref=args.thread_external_ref,
    )


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
