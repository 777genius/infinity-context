from __future__ import annotations

import json
from pathlib import Path

from memo_stack_server.top_evidence_preflight import run_top_evidence_preflight


def _top_evidence_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    locomo = tmp_path / "locomo.json"
    longmemeval = tmp_path / "longmemeval.json"
    locomo.write_text("[]", encoding="utf-8")
    longmemeval.write_text("[]", encoding="utf-8")
    env = {
        "MEMORY_OPENAI_API_KEY": "sk-test-secret-value",
        "MEMORY_AGENT_BENCH_MODEL": "gpt-test",
        "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET": str(locomo),
        "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET": str(longmemeval),
    }
    env.update(overrides)
    return env


def test_top_evidence_preflight_accepts_clean_publishable_config(tmp_path: Path) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    payload = result.as_dict()

    assert result.ok is True
    assert result.expected_git_commit == "abc123"
    assert result.allow_dirty_top_evidence is False
    assert result.failures == ()
    assert payload["checks"]["public_benchmark_case_count_representative"] is True
    assert "sk-test-secret-value" not in json.dumps(payload)


def test_top_evidence_preflight_rejects_dirty_worktree_without_override(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": True},
    )

    assert result.ok is False
    assert result.checks["git_clean_or_dirty_allowed"] is False
    assert any("Working tree must be clean" in failure for failure in result.failures)


def test_top_evidence_preflight_allows_dirty_only_for_explicit_diagnostics(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_QUALITY_EVIDENCE_ALLOW_DIRTY_TOP="true"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": True},
    )

    assert result.ok is True
    assert result.allow_dirty_top_evidence is True


def test_top_evidence_preflight_rejects_tiny_public_benchmark_config(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_PUBLIC_BENCHMARK_MAX_CASES="1"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["public_benchmark_case_count_representative"] is False
    assert any("MAX_CASES >= 600" in failure for failure in result.failures)


def test_top_evidence_preflight_rejects_missing_dataset_file(tmp_path: Path) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET=str(tmp_path / "missing.json"),
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["longmemeval_dataset_file"] is False
    assert any("LONGMEMEVAL_DATASET" in failure for failure in result.failures)


def test_top_evidence_preflight_requires_all_public_benchmarks(tmp_path: Path) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_PUBLIC_BENCHMARK_NAME="locomo"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["public_benchmark_all"] is False
    assert any("BENCHMARK_NAME=all" in failure for failure in result.failures)
