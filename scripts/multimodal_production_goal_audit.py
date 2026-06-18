#!/usr/bin/env python3
"""Audit proof artifacts for the multimodal production goal."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SUITE = "memo-stack-multimodal-production-goal-audit"

DEFAULT_FRONTEND_REPORT = ".e2e-artifacts/frontend-marionette-local-e2e.json"
DEFAULT_DOCKER_REPORT = ".e2e-artifacts/multimodal-docker-live-proof.json"
DEFAULT_PROVIDER_REPORT = ".e2e-artifacts/multimodal-live-provider-canary.json"

REQUIRED_FRONTEND_FLOWS = frozenset(
    {
        "memory_scope_management",
        "capture_link_approve",
        "context_link_reject",
        "attachment_capture_extraction",
        "manual_context_link_override",
        "anchor_lifecycle_cleanup",
    }
)
REQUIRED_DOCKER_COMPONENTS = frozenset(
    {
        "docker_daemon",
        "compose_config",
        "compose_stack",
        "container_dependencies",
        "health",
        "capabilities",
        "extraction_flow",
        "cleanup",
    }
)
REQUIRED_DOCKER_FILES = frozenset(
    {
        "docker-proof.txt",
        "docker-proof.pdf",
        "docker-proof.png",
        "docker-proof.wav",
        "docker-proof.mp4",
    }
)
FORBIDDEN_CORE_IMPORT_MARKERS = (
    "import fastapi",
    "from fastapi",
    "import sqlalchemy",
    "from sqlalchemy",
    "import qdrant",
    "from qdrant",
    "import qdrant_client",
    "from qdrant_client",
    "import graphiti",
    "from graphiti",
    "import openai",
    "from openai",
    "memo_stack_server",
    "memo_stack_adapters",
)
SECRET_MARKERS = ("sk-", "Bearer ")


@dataclass(frozen=True)
class GoalAuditResult:
    ok: bool
    checks: dict[str, bool]
    failures: tuple[str, ...]
    reports: dict[str, object]
    git: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "suite": SUITE,
            "ok": self.ok,
            "checks": dict(self.checks),
            "failures": list(self.failures),
            "reports": dict(self.reports),
            "git": dict(self.git),
            "secrets_redacted": True,
        }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_goal_audit(
        root=Path(args.root),
        frontend_report=Path(args.frontend_report),
        docker_report=Path(args.docker_report),
        provider_report=Path(args.provider_report),
        require_clean_git=not args.allow_dirty,
    )
    payload = result.as_dict()
    if args.report_out:
        report_path = Path(args.report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.ok else 1


def run_goal_audit(
    *,
    root: Path,
    frontend_report: Path = Path(DEFAULT_FRONTEND_REPORT),
    docker_report: Path = Path(DEFAULT_DOCKER_REPORT),
    provider_report: Path = Path(DEFAULT_PROVIDER_REPORT),
    require_clean_git: bool = True,
    git: Mapping[str, object] | None = None,
) -> GoalAuditResult:
    root = root.resolve()
    frontend = _load_report(root / frontend_report)
    docker = _load_report(root / docker_report)
    provider = _load_report(root / provider_report)
    git = dict(git) if git is not None else _git_info(root)

    checks: dict[str, bool] = {}
    failures: list[str] = []

    _check(
        checks,
        failures,
        "git_commit_present",
        bool(git.get("commit")),
        "Current git commit could not be resolved",
    )
    _check(
        checks,
        failures,
        "git_clean",
        (not bool(git.get("dirty"))) if require_clean_git else True,
        "Working tree must be clean for final multimodal production proof",
    )

    core_boundary_ok = _core_boundary_ok(root / "packages/memo_stack_core/memo_stack_core")
    _check(
        checks,
        failures,
        "core_boundary_clean",
        core_boundary_ok,
        "memo_stack_core imports forbidden server/adapters/provider dependencies",
    )

    _audit_frontend_report(frontend, checks=checks, failures=failures)
    _audit_docker_report(docker, checks=checks, failures=failures)
    _audit_provider_report(provider, checks=checks, failures=failures)

    serialized_reports = json.dumps(
        {
            "frontend": frontend,
            "docker": docker,
            "provider": provider,
        },
        sort_keys=True,
    )
    _check(
        checks,
        failures,
        "proof_reports_do_not_leak_secrets",
        not any(marker in serialized_reports for marker in SECRET_MARKERS),
        "Proof reports contain a provider credential marker or secret-like value",
    )

    reports = {
        "frontend": _report_summary(frontend),
        "docker": _report_summary(docker),
        "provider": _report_summary(provider),
    }
    return GoalAuditResult(
        ok=all(checks.values()),
        checks=checks,
        failures=tuple(failures),
        reports=reports,
        git=git,
    )


def _audit_frontend_report(
    report: Mapping[str, object] | None,
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "frontend_marionette_report_present",
        report is not None,
        f"Missing frontend Marionette report at {DEFAULT_FRONTEND_REPORT}",
    )
    if report is None:
        return
    flow = report.get("flow_coverage") if isinstance(report.get("flow_coverage"), dict) else {}
    completed = set(_string_list(flow.get("completed_flows")))
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    _check(
        checks,
        failures,
        "frontend_marionette_passed",
        report.get("ok") is True,
        "Frontend Marionette local E2E did not pass",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Frontend Marionette proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_flows_complete",
        flow.get("status") == "succeeded" and REQUIRED_FRONTEND_FLOWS.issubset(completed),
        "Frontend Marionette proof did not complete every required review/capture flow",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_components_succeeded",
        _components_succeeded(
            components,
            {"server", "worker", "flutter_marionette", "flutter_runtime_log"},
        ),
        "Frontend Marionette server, worker, Flutter, or runtime log component failed",
    )


def _audit_docker_report(
    report: Mapping[str, object] | None,
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "docker_live_report_present",
        report is not None,
        f"Missing Docker live proof report at {DEFAULT_DOCKER_REPORT}",
    )
    if report is None:
        return
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    extraction = components.get("extraction_flow") if isinstance(components, dict) else {}
    raw_cases = extraction.get("cases") if isinstance(extraction, dict) else None
    cases = raw_cases if isinstance(raw_cases, list) else []
    filenames = {str(item.get("filename")) for item in cases if isinstance(item, dict)}
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    _check(
        checks,
        failures,
        "docker_live_proof_passed",
        report.get("ok") is True,
        "Docker multimodal live proof did not pass",
    )
    _check(
        checks,
        failures,
        "docker_live_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Docker live proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "docker_live_components_succeeded",
        _components_succeeded(components, REQUIRED_DOCKER_COMPONENTS),
        "Docker live proof did not succeed for every required runtime component",
    )
    _check(
        checks,
        failures,
        "docker_live_extraction_cases_complete",
        REQUIRED_DOCKER_FILES.issubset(filenames),
        "Docker live proof did not extract every required multimodal file type",
    )


def _audit_provider_report(
    report: Mapping[str, object] | None,
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "live_provider_report_present",
        report is not None,
        f"Missing live provider canary report at {DEFAULT_PROVIDER_REPORT}",
    )
    if report is None:
        return
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    _check(
        checks,
        failures,
        "live_provider_proof_passed",
        report.get("ok") is True,
        "Live provider canary did not pass",
    )
    _check(
        checks,
        failures,
        "live_provider_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Live provider proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "live_provider_key_present",
        report.get("provider_key_present") is True,
        "Live provider proof needs MEMORY_OPENAI_API_KEY or OPENAI_API_KEY",
    )
    _check(
        checks,
        failures,
        "live_provider_components_succeeded",
        _components_succeeded(components, {"vision", "transcription"}),
        "Live provider vision and transcription checks must both succeed",
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_repository_root()))
    parser.add_argument("--frontend-report", default=DEFAULT_FRONTEND_REPORT)
    parser.add_argument("--docker-report", default=DEFAULT_DOCKER_REPORT)
    parser.add_argument("--provider-report", default=DEFAULT_PROVIDER_REPORT)
    parser.add_argument(
        "--report-out",
        default=os.environ.get(
            "MEMORY_MULTIMODAL_PRODUCTION_GOAL_AUDIT_REPORT_OUT",
            ".e2e-artifacts/multimodal-production-goal-audit.json",
        ),
    )
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args(argv)


def _load_report(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _core_boundary_ok(path: Path) -> bool:
    if not path.exists():
        return False
    for file_path in path.rglob("*.py"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return False
        lowered = content.lower()
        if any(marker in lowered for marker in FORBIDDEN_CORE_IMPORT_MARKERS):
            return False
    return True


def _components_succeeded(
    components: Mapping[str, object],
    required: set[str] | frozenset[str],
) -> bool:
    for name in required:
        component = components.get(name)
        if not isinstance(component, dict) or component.get("status") != "succeeded":
            return False
    return True


def _check(
    checks: dict[str, bool],
    failures: list[str],
    name: str,
    ok: bool,
    failure: str,
) -> None:
    checks[name] = bool(ok)
    if not ok:
        failures.append(failure)


def _report_summary(report: Mapping[str, object] | None) -> dict[str, object]:
    if report is None:
        return {"present": False}
    summary: dict[str, object] = {
        "present": True,
        "suite": _safe_text(report.get("suite")),
        "ok": report.get("ok") is True,
    }
    git = report.get("git")
    if isinstance(git, dict):
        summary["git"] = {
            "short_commit": _safe_text(git.get("short_commit")),
            "dirty": git.get("dirty") is True,
        }
    return summary


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _safe_text(value: object, *, limit: int = 160) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


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
    return result.stdout.strip()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
