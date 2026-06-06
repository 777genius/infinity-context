"""Build auditable Memo Stack quality evidence bundles.

The scorecard can already aggregate JSON reports. This module creates those
reports in one reproducible directory so production/top-library quality claims
are backed by artifacts instead of terminal-only output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from memo_stack_server.eval import (
    AUTO_MEMORY_GOLDEN_SUITE,
    GRAPH_NATIVE_GOLDEN_SUITE,
    LONG_MEMORY_GOLDEN_SUITE,
    MEMORY_QUALITY_SCORECARD_SUITE,
    PROMPT_CONTRACT_SUITE,
    QUALITY_GOLDEN_SUITE,
    SMALL_GOLDEN_SUITE,
    run_auto_memory_golden,
    run_graph_native_golden,
    run_long_memory_golden,
    run_memory_quality_scorecard,
    run_prompt_snapshots,
    run_quality_golden,
    run_small_golden,
)

DEFAULT_EVIDENCE_DIR = Path(".tmp") / "memo-stack-quality-evidence"


@dataclass(frozen=True)
class EvidenceSuite:
    suite: str
    filename: str
    runner: Callable[[Path], dict[str, object]]


DETERMINISTIC_EVIDENCE_SUITES: tuple[EvidenceSuite, ...] = (
    EvidenceSuite(
        SMALL_GOLDEN_SUITE,
        "small-golden.json",
        lambda report_out: run_small_golden(report_out=report_out),
    ),
    EvidenceSuite(
        QUALITY_GOLDEN_SUITE,
        "quality-golden.json",
        lambda report_out: run_quality_golden(report_out=report_out),
    ),
    EvidenceSuite(
        LONG_MEMORY_GOLDEN_SUITE,
        "long-memory-golden.json",
        lambda report_out: run_long_memory_golden(report_out=report_out),
    ),
    EvidenceSuite(
        AUTO_MEMORY_GOLDEN_SUITE,
        "auto-memory-golden.json",
        lambda report_out: run_auto_memory_golden(report_out=report_out),
    ),
    EvidenceSuite(
        GRAPH_NATIVE_GOLDEN_SUITE,
        "graph-native-golden.json",
        lambda report_out: run_graph_native_golden(report_out=report_out),
    ),
    EvidenceSuite(
        PROMPT_CONTRACT_SUITE,
        "prompt-contract.json",
        lambda report_out: run_prompt_snapshots(report_out=report_out),
    ),
)


def build_quality_evidence_bundle(
    *,
    output_dir: Path = DEFAULT_EVIDENCE_DIR,
    extra_report_paths: Sequence[Path] = (),
    require_top_evidence: bool = False,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suite_report_paths: list[Path] = []
    suite_summaries: list[dict[str, object]] = []

    for evidence_suite in DETERMINISTIC_EVIDENCE_SUITES:
        report_path = output_dir / evidence_suite.filename
        result = evidence_suite.runner(report_path)
        suite_report_paths.append(report_path)
        suite_summaries.append(
            {
                "suite": evidence_suite.suite,
                "ok": result.get("ok") is True,
                "report_path": str(report_path),
            }
        )

    extra_reports = _validated_extra_reports(extra_report_paths)
    scorecard_path = output_dir / "memory-quality-scorecard.json"
    scorecard = run_memory_quality_scorecard(
        report_out=scorecard_path,
        suite_report_paths=tuple([*suite_report_paths, *extra_reports]),
        require_top_evidence=require_top_evidence,
    )
    result: dict[str, object] = {
        "suite": "memo-stack-quality-evidence-bundle",
        "ok": scorecard.get("ok") is True,
        "output_dir": str(output_dir),
        "scorecard_report_path": str(scorecard_path),
        "manifest_path": str(output_dir / "quality-evidence-manifest.json"),
        "require_top_evidence": require_top_evidence,
        "deterministic_reports": suite_summaries,
        "extra_report_paths": [str(path) for path in extra_reports],
        "scorecard": {
            "suite": MEMORY_QUALITY_SCORECARD_SUITE,
            "ok": scorecard.get("ok") is True,
            "maturity_score_10": _nested_get(scorecard, "score", "maturity_score_10"),
            "confidence_tier": _nested_get(
                scorecard,
                "external_evidence",
                "confidence_tier",
            ),
            "top_library_comparison_ready": _nested_get(
                scorecard,
                "external_evidence",
                "top_library_comparison_ready",
            ),
            "evidence_gaps": _nested_get(scorecard, "external_evidence", "evidence_gaps"),
        },
    }
    bundle_path = output_dir / "quality-evidence-bundle.json"
    _write_json(bundle_path, result)
    manifest = _build_manifest(
        output_dir=output_dir,
        deterministic_report_paths=suite_report_paths,
        extra_report_paths=extra_reports,
        scorecard_path=scorecard_path,
        bundle_path=bundle_path,
        require_top_evidence=require_top_evidence,
    )
    _write_json(output_dir / "quality-evidence-manifest.json", manifest)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--extra-report",
        action="append",
        type=Path,
        default=[],
        help="Existing full-provider, agent-behavior or public benchmark report JSON.",
    )
    parser.add_argument(
        "--require-top-evidence",
        action="store_true",
        help="Fail unless full-provider, real-agent and public benchmark evidence passes.",
    )
    args = parser.parse_args(argv)
    try:
        result = build_quality_evidence_bundle(
            output_dir=args.output_dir,
            extra_report_paths=tuple(args.extra_report),
            require_top_evidence=args.require_top_evidence,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


def _validated_extra_reports(paths: Sequence[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if not path.exists():
            raise ValueError(f"Evidence extra report does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Evidence extra report must be a file: {path}")
        result.append(path)
    return result


def _nested_get(payload: dict[str, object], *keys: str) -> object:
    value: object = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _build_manifest(
    *,
    output_dir: Path,
    deterministic_report_paths: Sequence[Path],
    extra_report_paths: Sequence[Path],
    scorecard_path: Path,
    bundle_path: Path,
    require_top_evidence: bool,
) -> dict[str, object]:
    artifacts = [
        *(
            _artifact_summary(path, kind="deterministic_report", output_dir=output_dir)
            for path in deterministic_report_paths
        ),
        *(
            _artifact_summary(path, kind="external_report", output_dir=output_dir)
            for path in extra_report_paths
        ),
        _artifact_summary(scorecard_path, kind="scorecard", output_dir=output_dir),
        _artifact_summary(bundle_path, kind="bundle_summary", output_dir=output_dir),
    ]
    return {
        "schema_version": 1,
        "suite": "memo-stack-quality-evidence-manifest",
        "require_top_evidence": require_top_evidence,
        "output_dir": str(output_dir),
        "git": _git_metadata(),
        "runtime": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "artifacts": artifacts,
    }


def _artifact_summary(path: Path, *, kind: str, output_dir: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "kind": kind,
        "path": str(path),
        "relative_path": _relative_path(path, output_dir),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _relative_path(path: Path, output_dir: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return None


def _git_metadata() -> dict[str, object]:
    repo_root = _repository_root()
    return {
        "commit": _git_output("rev-parse", "HEAD", cwd=repo_root),
        "short_commit": _git_output("rev-parse", "--short", "HEAD", cwd=repo_root),
        "dirty": _git_dirty(cwd=repo_root),
    }


def _repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_dirty(*, cwd: Path | None) -> bool | None:
    status = _git_output("status", "--short", cwd=cwd)
    return None if status is None else bool(status.strip())


def _git_output(*args: str, cwd: Path | None) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            check=False,
            cwd=cwd,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
