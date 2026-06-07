"""Preflight checks for publishable Memo Stack top-evidence runs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from memo_stack_core.reporting import git_metadata

from memo_stack_server.public_benchmark import (
    BenchmarkValidationError,
    load_public_benchmark_case_count,
)

DEFAULT_MIN_PUBLIC_CASES = 600
DEFAULT_MIN_PUBLIC_ACCURACY = 0.902
REQUIRED_AGENT_SCENARIO_SET = "all"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class TopEvidencePreflightResult:
    ok: bool
    checks: dict[str, bool]
    failures: tuple[str, ...]
    expected_git_commit: str | None
    allow_dirty_top_evidence: bool
    sanitized_config: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": self.checks,
            "failures": list(self.failures),
            "expected_git_commit": self.expected_git_commit,
            "allow_dirty_top_evidence": self.allow_dirty_top_evidence,
            "sanitized_config": self.sanitized_config,
            "suite": "memo-stack-top-evidence-preflight",
        }


def run_top_evidence_preflight(
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    docker_path: str | None = None,
    git: Mapping[str, object] | None = None,
) -> TopEvidencePreflightResult:
    env = os.environ if env is None else env
    cwd = cwd or _repository_root()
    docker_path = docker_path if docker_path is not None else shutil.which("docker")
    git = git if git is not None else git_metadata(cwd=cwd)
    allow_dirty = _bool_env(env, "MEMORY_QUALITY_EVIDENCE_ALLOW_DIRTY_TOP")
    min_public_cases = max(
        DEFAULT_MIN_PUBLIC_CASES,
        _positive_int_env(
            env,
            "MEMORY_TOP_EVIDENCE_MIN_PUBLIC_CASES",
            DEFAULT_MIN_PUBLIC_CASES,
        ),
    )
    min_public_accuracy = max(
        DEFAULT_MIN_PUBLIC_ACCURACY,
        _float_env(
            env,
            "MEMORY_TOP_EVIDENCE_MIN_PUBLIC_ACCURACY",
            DEFAULT_MIN_PUBLIC_ACCURACY,
        ),
    )
    if min_public_accuracy > 1.0:
        min_public_accuracy = 1.0

    failures: list[str] = []
    checks: dict[str, bool] = {}

    checks["top_evidence_case_floor_publishable"] = min_public_cases >= (
        DEFAULT_MIN_PUBLIC_CASES
    )
    checks["top_evidence_accuracy_floor_publishable"] = min_public_accuracy >= (
        DEFAULT_MIN_PUBLIC_ACCURACY
    )
    _append_failure(
        checks,
        failures,
        "top_evidence_case_floor_publishable",
        f"Top evidence case floor cannot be lower than {DEFAULT_MIN_PUBLIC_CASES}",
    )
    _append_failure(
        checks,
        failures,
        "top_evidence_accuracy_floor_publishable",
        f"Top evidence accuracy floor cannot be lower than {DEFAULT_MIN_PUBLIC_ACCURACY}",
    )

    configured_cases = _positive_int_env(
        env,
        "MEMORY_PUBLIC_BENCHMARK_MAX_CASES",
        min_public_cases,
    )
    configured_accuracy = _float_env(
        env,
        "MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY",
        min_public_accuracy,
    )

    checks["docker_available"] = bool(docker_path)
    _append_failure(checks, failures, "docker_available", "Docker executable is required")

    openai_key_present = bool(_env_first(env, "MEMORY_OPENAI_API_KEY", "OPENAI_API_KEY"))
    checks["openai_key_present"] = openai_key_present
    _append_failure(
        checks,
        failures,
        "openai_key_present",
        "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running top evidence",
    )

    agent_model = env.get("MEMORY_AGENT_BENCH_MODEL", "").strip()
    checks["agent_bench_model_present"] = bool(agent_model)
    _append_failure(
        checks,
        failures,
        "agent_bench_model_present",
        "Set MEMORY_AGENT_BENCH_MODEL before running top evidence",
    )

    agent_scenario_set = (
        env.get("MEMORY_AGENT_BENCH_SCENARIO_SET", REQUIRED_AGENT_SCENARIO_SET)
        .strip()
        .lower()
        or REQUIRED_AGENT_SCENARIO_SET
    )
    checks["agent_bench_scenario_set_all"] = (
        agent_scenario_set == REQUIRED_AGENT_SCENARIO_SET
    )
    _append_failure(
        checks,
        failures,
        "agent_bench_scenario_set_all",
        "Top evidence requires MEMORY_AGENT_BENCH_SCENARIO_SET=all",
    )

    benchmark_name = env.get("MEMORY_PUBLIC_BENCHMARK_NAME", "all").strip().lower() or "all"
    checks["public_benchmark_all"] = benchmark_name == "all"
    _append_failure(
        checks,
        failures,
        "public_benchmark_all",
        "Top evidence requires MEMORY_PUBLIC_BENCHMARK_NAME=all",
    )

    checks["public_benchmark_case_count_representative"] = configured_cases >= min_public_cases
    _append_failure(
        checks,
        failures,
        "public_benchmark_case_count_representative",
        (
            "Top evidence requires MEMORY_PUBLIC_BENCHMARK_MAX_CASES "
            f">= {min_public_cases}"
        ),
    )

    checks["public_benchmark_accuracy_floor_competitive"] = (
        configured_accuracy >= min_public_accuracy
    )
    _append_failure(
        checks,
        failures,
        "public_benchmark_accuracy_floor_competitive",
        (
            "Top evidence requires MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY "
            f">= {min_public_accuracy}"
        ),
    )

    locomo_dataset = _dataset_file(env, "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")
    longmemeval_dataset = _dataset_file(env, "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    locomo_case_count = _dataset_case_count(locomo_dataset, benchmark="locomo")
    longmemeval_case_count = _dataset_case_count(
        longmemeval_dataset,
        benchmark="longmemeval",
    )
    checks["locomo_dataset_file"] = locomo_dataset is not None
    checks["longmemeval_dataset_file"] = longmemeval_dataset is not None
    checks["locomo_dataset_valid"] = locomo_case_count is not None and locomo_case_count > 0
    checks["longmemeval_dataset_valid"] = (
        longmemeval_case_count is not None and longmemeval_case_count > 0
    )
    checks["locomo_dataset_case_count_representative"] = (
        locomo_case_count is not None and locomo_case_count >= configured_cases
    )
    checks["longmemeval_dataset_case_count_representative"] = (
        longmemeval_case_count is not None and longmemeval_case_count >= configured_cases
    )
    _append_failure(
        checks,
        failures,
        "locomo_dataset_file",
        "Set MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET to an existing JSON/JSONL file",
    )
    _append_failure(
        checks,
        failures,
        "longmemeval_dataset_file",
        "Set MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET to an existing JSON/JSONL file",
    )
    _append_failure(
        checks,
        failures,
        "locomo_dataset_valid",
        "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET must contain valid locomo cases",
    )
    _append_failure(
        checks,
        failures,
        "longmemeval_dataset_valid",
        "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET must contain valid longmemeval cases",
    )
    _append_failure(
        checks,
        failures,
        "locomo_dataset_case_count_representative",
        (
            "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET must contain at least "
            f"{configured_cases} locomo cases"
        ),
    )
    _append_failure(
        checks,
        failures,
        "longmemeval_dataset_case_count_representative",
        (
            "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET must contain at least "
            f"{configured_cases} longmemeval cases"
        ),
    )

    commit = git.get("commit")
    dirty = git.get("dirty")
    checks["git_commit_present"] = isinstance(commit, str) and bool(commit)
    checks["git_dirty_state_known"] = isinstance(dirty, bool)
    checks["git_clean_or_dirty_allowed"] = isinstance(dirty, bool) and (
        not dirty or allow_dirty
    )
    _append_failure(
        checks,
        failures,
        "git_commit_present",
        "Unable to resolve current git commit for strict top evidence",
    )
    _append_failure(
        checks,
        failures,
        "git_dirty_state_known",
        "Unable to resolve git dirty state for strict top evidence",
    )
    _append_failure(
        checks,
        failures,
        "git_clean_or_dirty_allowed",
        (
            "Working tree must be clean for publishable top evidence. "
            "Set MEMORY_QUALITY_EVIDENCE_ALLOW_DIRTY_TOP=true only for local diagnostics."
        ),
    )

    return TopEvidencePreflightResult(
        ok=all(checks.values()),
        checks=checks,
        failures=tuple(failures),
        expected_git_commit=commit if isinstance(commit, str) and commit else None,
        allow_dirty_top_evidence=allow_dirty,
        sanitized_config={
            "agent_bench_model": agent_model or None,
            "agent_bench_scenario_set": agent_scenario_set,
            "docker_available": bool(docker_path),
            "locomo_dataset": str(locomo_dataset) if locomo_dataset is not None else None,
            "longmemeval_dataset": (
                str(longmemeval_dataset) if longmemeval_dataset is not None else None
            ),
            "locomo_case_count": locomo_case_count,
            "longmemeval_case_count": longmemeval_case_count,
            "openai_key_present": openai_key_present,
            "public_benchmark_max_cases": configured_cases,
            "public_benchmark_min_accuracy": configured_accuracy,
            "public_benchmark_name": benchmark_name,
            "top_evidence_min_public_accuracy": min_public_accuracy,
            "top_evidence_min_public_cases": min_public_cases,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print safe JSON diagnostics")
    args = parser.parse_args(argv)
    result = run_top_evidence_preflight()
    payload = result.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif result.ok:
        print(f"top evidence preflight ok: commit={result.expected_git_commit}")
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.ok else 1


def _append_failure(
    checks: Mapping[str, bool],
    failures: list[str],
    check_name: str,
    message: str,
) -> None:
    if not checks[check_name]:
        failures.append(f"{check_name}: {message}")


def _env_first(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def _dataset_file(env: Mapping[str, str], name: str) -> Path | None:
    value = env.get(name, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_file() else None


def _dataset_case_count(path: Path | None, *, benchmark: str) -> int | None:
    if path is None:
        return None
    try:
        return load_public_benchmark_case_count(
            dataset_path=path,
            benchmark=benchmark,
        )
    except (BenchmarkValidationError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _positive_int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return -1.0


def _bool_env(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in TRUE_VALUES


def _repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
