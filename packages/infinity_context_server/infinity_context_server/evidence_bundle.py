"""Build auditable Infinity Context quality evidence bundles.

The scorecard can already aggregate JSON reports. This module creates those
reports in one reproducible directory so production/top-library quality claims
are backed by artifacts instead of terminal-only output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.reporting import git_metadata

from infinity_context_server.eval import (
    AUTO_MEMORY_GOLDEN_SUITE,
    GRAPH_NATIVE_GOLDEN_SUITE,
    LONG_MEMORY_GOLDEN_SUITE,
    MEMORY_QUALITY_SCORECARD_SUITE,
    MULTIMODAL_OFFLINE_GOLDEN_SUITE,
    PROMPT_CONTRACT_SUITE,
    QUALITY_GOLDEN_SUITE,
    SEMANTIC_LINKING_GOLDEN_SUITE,
    SMALL_GOLDEN_SUITE,
    memory_quality_scorecard_policy_snapshot,
    run_auto_memory_golden,
    run_graph_native_golden,
    run_long_memory_golden,
    run_memory_quality_scorecard,
    run_multimodal_offline_golden,
    run_prompt_snapshots,
    run_quality_golden,
    run_semantic_linking_golden,
    run_small_golden,
)
from infinity_context_server.top_evidence_policy import (
    FULL_PROVIDER_NESTED_TOP_EVIDENCE_KEYS,
    FULL_PROVIDER_TOP_EVIDENCE_SUITES,
    TOP_EVIDENCE_PROVENANCE_CHECKS,
    top_evidence_provenance_summary,
    top_evidence_report_policy,
)

DEFAULT_EVIDENCE_DIR = Path(".tmp") / "infinity-context-quality-evidence"


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
        SEMANTIC_LINKING_GOLDEN_SUITE,
        "semantic-linking-golden.json",
        lambda report_out: run_semantic_linking_golden(report_out=report_out),
    ),
    EvidenceSuite(
        MULTIMODAL_OFFLINE_GOLDEN_SUITE,
        "multimodal-offline-golden.json",
        lambda report_out: run_multimodal_offline_golden(report_out=report_out),
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
    expected_git_commit: str | None = None,
    allow_dirty_top_evidence: bool = False,
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

    extra_reports = _validated_extra_reports(
        extra_report_paths,
        require_top_evidence=require_top_evidence,
        expected_git_commit=expected_git_commit,
        allow_dirty_top_evidence=allow_dirty_top_evidence,
    )
    scorecard_path = output_dir / "memory-quality-scorecard.json"
    scorecard = run_memory_quality_scorecard(
        report_out=scorecard_path,
        suite_report_paths=tuple([*suite_report_paths, *extra_reports]),
        require_top_evidence=require_top_evidence,
    )
    result: dict[str, object] = {
        "suite": "infinity-context-quality-evidence-bundle",
        "ok": scorecard.get("ok") is True,
        "output_dir": str(output_dir),
        "scorecard_report_path": str(scorecard_path),
        "manifest_path": str(output_dir / "quality-evidence-manifest.json"),
        "require_top_evidence": require_top_evidence,
        "allow_dirty_top_evidence": allow_dirty_top_evidence,
        "expected_git_commit": expected_git_commit
        if expected_git_commit is not None
        else _current_git_commit()
        if require_top_evidence
        else None,
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
        allow_dirty_top_evidence=allow_dirty_top_evidence,
        expected_git_commit=result["expected_git_commit"],
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
    parser.add_argument(
        "--expected-git-commit",
        default=None,
        help=(
            "Expected git commit for strict full-provider external reports. "
            "Defaults to the current repository HEAD when --require-top-evidence is set."
        ),
    )
    parser.add_argument(
        "--allow-dirty-top-evidence",
        action="store_true",
        help=(
            "Allow strict top-evidence full-provider reports generated from a dirty worktree. "
            "Intended only for local diagnostics; publishable evidence should be clean."
        ),
    )
    args = parser.parse_args(argv)
    try:
        result = build_quality_evidence_bundle(
            output_dir=args.output_dir,
            extra_report_paths=tuple(args.extra_report),
            require_top_evidence=args.require_top_evidence,
            expected_git_commit=args.expected_git_commit,
            allow_dirty_top_evidence=args.allow_dirty_top_evidence,
        )
    except ValueError as exc:
        raise SystemExit(_safe_cli_error(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


def _safe_cli_error(exc: Exception) -> str:
    return redact_sensitive_text(str(exc).strip() or exc.__class__.__name__)[:500]


def _validated_extra_reports(
    paths: Sequence[Path],
    *,
    require_top_evidence: bool,
    expected_git_commit: str | None,
    allow_dirty_top_evidence: bool,
) -> list[Path]:
    result: list[Path] = []
    resolved_expected_commit = (
        _required_expected_git_commit(expected_git_commit)
        if require_top_evidence
        else None
    )
    for path in paths:
        if not path.exists():
            raise ValueError(f"Evidence extra report does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Evidence extra report must be a file: {path}")
        if require_top_evidence and resolved_expected_commit is not None:
            _validate_top_evidence_report_provenance(
                path,
                expected_git_commit=resolved_expected_commit,
                allow_dirty_top_evidence=allow_dirty_top_evidence,
            )
        result.append(path)
    return result


def _required_expected_git_commit(explicit_commit: str | None) -> str:
    if explicit_commit is not None and explicit_commit.strip():
        return explicit_commit.strip()
    current_commit = _current_git_commit()
    if current_commit is None:
        raise ValueError(
            "Unable to determine current git commit for strict top evidence validation"
        )
    return current_commit


def _current_git_commit() -> str | None:
    commit = git_metadata(cwd=_repository_root()).get("commit")
    return commit if isinstance(commit, str) and commit else None


def _validate_top_evidence_report_provenance(
    path: Path,
    *,
    expected_git_commit: str,
    allow_dirty_top_evidence: bool,
) -> None:
    payload = _read_json_object(path)
    _validate_top_evidence_payload_provenance(
        payload,
        source_label=str(path),
        expected_git_commit=expected_git_commit,
        allow_dirty_top_evidence=allow_dirty_top_evidence,
    )


def _validate_top_evidence_payload_provenance(
    payload: dict[str, object],
    *,
    source_label: str,
    expected_git_commit: str,
    allow_dirty_top_evidence: bool,
) -> None:
    suite = payload.get("suite")
    policy = top_evidence_report_policy(suite)
    if policy is None:
        return
    summary = top_evidence_provenance_summary(
        payload,
        policy=policy,
        allow_dirty_top_evidence=allow_dirty_top_evidence,
    )
    if summary["ok"] is not True:
        _raise_top_evidence_provenance_failure(
            summary["failed_checks"],
            source_label=source_label,
        )
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError("top evidence provenance summary accepted missing provenance")
    git = provenance.get("git")
    commit = git.get("commit") if isinstance(git, dict) else None
    dirty = git.get("dirty") if isinstance(git, dict) else None
    if not isinstance(commit, str) or not commit:
        raise AssertionError("top evidence provenance summary accepted missing git commit")
    if not isinstance(dirty, bool):
        raise AssertionError("top evidence provenance summary accepted missing dirty state")
    if commit != expected_git_commit:
        raise ValueError(
            f"Top evidence report commit mismatch: {source_label}: "
            f"expected {expected_git_commit}, got {commit}"
        )
    if dirty and not allow_dirty_top_evidence:
        raise ValueError(
            f"Top evidence report was generated from a dirty worktree: {source_label}"
        )
    if isinstance(suite, str) and suite in FULL_PROVIDER_TOP_EVIDENCE_SUITES:
        _validate_full_provider_nested_top_evidence(
            payload,
            source_label=source_label,
            expected_git_commit=expected_git_commit,
            allow_dirty_top_evidence=allow_dirty_top_evidence,
        )


def _raise_top_evidence_provenance_failure(
    failed_checks: object,
    *,
    source_label: str,
) -> None:
    failures = failed_checks if isinstance(failed_checks, list) else []
    messages = {
        "provenance_present": f"Top evidence report is missing provenance: {source_label}",
        "provenance_schema_version_1": (
            f"Top evidence report has unsupported provenance schema: {source_label}"
        ),
        "provenance_suite_allowed": (
            f"Top evidence report provenance suite mismatch: {source_label}"
        ),
        "provenance_generator_allowed": (
            f"Top evidence report has unsupported provenance generator: {source_label}"
        ),
        "provenance_git_commit_present": (
            f"Top evidence report is missing provenance git commit: {source_label}"
        ),
        "provenance_dirty_state_present": (
            f"Top evidence report is missing provenance dirty state: {source_label}"
        ),
        "provenance_git_clean_or_dirty_allowed": (
            f"Top evidence report was generated from a dirty worktree: {source_label}"
        ),
        "provenance_runtime_python_version_present": (
            "Top evidence report is missing provenance runtime python_version: "
            f"{source_label}"
        ),
        "provenance_runtime_platform_present": (
            f"Top evidence report is missing provenance runtime platform: {source_label}"
        ),
    }
    for check in TOP_EVIDENCE_PROVENANCE_CHECKS:
        if check in failures:
            raise ValueError(messages[check])
    raise ValueError(f"Top evidence report provenance validation failed: {source_label}")


def _validate_full_provider_nested_top_evidence(
    payload: dict[str, object],
    *,
    source_label: str,
    expected_git_commit: str,
    allow_dirty_top_evidence: bool,
) -> None:
    for key in FULL_PROVIDER_NESTED_TOP_EVIDENCE_KEYS:
        nested = payload.get(key)
        if nested is None:
            continue
        nested_label = f"{source_label}#{key}"
        if not isinstance(nested, dict):
            raise ValueError(
                f"Top evidence full-provider nested {key} must be an object: "
                f"{nested_label}"
            )
        _validate_top_evidence_payload_provenance(
            nested,
            source_label=nested_label,
            expected_git_commit=expected_git_commit,
            allow_dirty_top_evidence=allow_dirty_top_evidence,
        )


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Evidence extra report must be valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Evidence extra report must be a JSON object: {path}")
    return payload


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
    allow_dirty_top_evidence: bool,
    expected_git_commit: object,
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
        "suite": "infinity-context-quality-evidence-manifest",
        "require_top_evidence": require_top_evidence,
        "allow_dirty_top_evidence": allow_dirty_top_evidence,
        "expected_git_commit": expected_git_commit,
        "output_dir": str(output_dir),
        "git": _git_metadata(),
        "runtime": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "policy": memory_quality_scorecard_policy_snapshot(
            require_top_evidence=require_top_evidence,
        ),
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
        "report": _artifact_report_metadata(data),
    }


def _artifact_report_metadata(data: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    metadata: dict[str, object] = {
        key: payload[key]
        for key in ("suite", "status", "ok")
        if key in payload and isinstance(payload[key], str | bool)
    }
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        metadata["provenance"] = provenance
    return metadata or None


def _relative_path(path: Path, output_dir: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return None


def _git_metadata() -> dict[str, object]:
    return git_metadata(cwd=_repository_root())


def _repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
