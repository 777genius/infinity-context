"""Shared report provenance helpers for Infinity Context quality evidence."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_COMMON_GIT_EXECUTABLES = ("/usr/bin/git", "/bin/git", "/usr/local/bin/git")


def build_report_provenance(
    *,
    generated_by: str,
    suite: str,
    run_id: str | None = None,
    project: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Build reproducibility metadata for benchmark and canary reports."""

    provenance: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": generated_by,
        "suite": suite,
        "git": git_metadata(cwd=cwd),
        "runtime": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    if run_id is not None:
        provenance["run_id"] = run_id
    if project is not None:
        provenance["project"] = project
    return provenance


def with_report_provenance(
    report: dict[str, object],
    *,
    generated_by: str,
    suite: str | None = None,
    run_id: str | None = None,
    project: str | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    """Return a report copy with a fresh provenance block."""

    resolved_suite = suite or str(report.get("suite") or "")
    result = dict(report)
    result["provenance"] = build_report_provenance(
        generated_by=generated_by,
        suite=resolved_suite,
        run_id=run_id,
        project=project,
        cwd=cwd,
    )
    return result


def git_metadata(*, cwd: Path | None = None) -> dict[str, Any]:
    return {
        "commit": _git_output("rev-parse", "HEAD", cwd=cwd),
        "short_commit": _git_output("rev-parse", "--short", "HEAD", cwd=cwd),
        "dirty": git_dirty(cwd=cwd),
    }


def git_dirty(*, cwd: Path | None = None) -> bool | None:
    status = _git_output("status", "--short", cwd=cwd)
    return None if status is None else bool(status.strip())


def _git_output(*args: str, cwd: Path | None = None) -> str | None:
    git = _git_executable()
    if git is None:
        return None
    try:
        completed = subprocess.run(
            [git, *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _git_executable() -> str | None:
    git = shutil.which("git")
    if git:
        return git
    for candidate in _COMMON_GIT_EXECUTABLES:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None
