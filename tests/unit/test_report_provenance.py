from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from infinity_context_core import reporting
from infinity_context_core.reporting import build_report_provenance, with_report_provenance


def test_build_report_provenance_is_safe_and_reproducible(tmp_path: Path) -> None:
    provenance = build_report_provenance(
        generated_by="unit.generator",
        suite="unit-suite",
        run_id="unit-run",
        project="unit-project",
        cwd=tmp_path,
    )

    assert provenance["schema_version"] == 1
    assert provenance["generated_by"] == "unit.generator"
    assert provenance["suite"] == "unit-suite"
    assert provenance["run_id"] == "unit-run"
    assert provenance["project"] == "unit-project"
    assert set(provenance["git"]) == {"commit", "short_commit", "dirty"}
    assert provenance["git"]["commit"] is None
    assert provenance["git"]["dirty"] is None
    assert provenance["runtime"]["python_version"]
    assert provenance["runtime"]["platform"]


def test_git_dirty_distinguishes_clean_worktree_from_unavailable_git(monkeypatch) -> None:
    monkeypatch.setattr(reporting, "_git_output", lambda *_, cwd=None: "")

    assert reporting.git_dirty() is False


def test_git_metadata_uses_common_git_path_when_path_lookup_misses(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fallback_git = tmp_path / "git"
    fallback_git.write_text("#!/bin/sh\n", encoding="utf-8")
    fallback_git.chmod(0o755)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        output = "abc123\n" if command[-1] == "HEAD" else ""
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(reporting.shutil, "which", lambda _: None)
    monkeypatch.setattr(reporting, "_COMMON_GIT_EXECUTABLES", (str(fallback_git),))
    monkeypatch.setattr(reporting.subprocess, "run", fake_run)

    assert reporting.git_metadata(cwd=tmp_path) == {
        "commit": "abc123",
        "short_commit": "abc123",
        "dirty": False,
    }
    assert commands == [
        [str(fallback_git), "rev-parse", "HEAD"],
        [str(fallback_git), "rev-parse", "--short", "HEAD"],
        [str(fallback_git), "status", "--short"],
    ]


def test_with_report_provenance_does_not_mutate_source_report(tmp_path: Path) -> None:
    report = {"suite": "unit-suite", "ok": True}

    result = with_report_provenance(
        report,
        generated_by="unit.generator",
        run_id="unit-run",
        cwd=tmp_path,
    )

    assert "provenance" not in report
    assert result["suite"] == "unit-suite"
    assert result["provenance"]["generated_by"] == "unit.generator"
    assert result["provenance"]["suite"] == "unit-suite"
    assert result["provenance"]["run_id"] == "unit-run"
