from __future__ import annotations

import json
from pathlib import Path

from memo_stack_server.top_evidence_preflight import run_top_evidence_preflight


def _top_evidence_env(
    tmp_path: Path,
    *,
    case_count: int = 600,
    **overrides: str,
) -> dict[str, str]:
    locomo = tmp_path / "locomo.json"
    longmemeval = tmp_path / "longmemeval.json"
    locomo.write_text(
        json.dumps(_benchmark_cases("locomo", count=case_count)),
        encoding="utf-8",
    )
    longmemeval.write_text(
        json.dumps(_benchmark_cases("longmemeval", count=case_count)),
        encoding="utf-8",
    )
    env = {
        "MEMORY_OPENAI_API_KEY": "sk-test-secret-value",
        "MEMORY_AGENT_BENCH_MODEL": "gpt-test",
        "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET": str(locomo),
        "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET": str(longmemeval),
    }
    env.update(overrides)
    return env


def _benchmark_cases(benchmark: str, *, count: int) -> list[dict[str, object]]:
    return [
        {
            "benchmark": benchmark,
            "case_id": f"{benchmark}-{index}",
            "question": f"What is marker {index} for {benchmark}?",
            "expected_terms": [f"{benchmark}-marker-{index}"],
            "memories": [f"{benchmark}-marker-{index} is stored in memory."],
        }
        for index in range(count)
    ]


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
    assert payload["checks"]["agent_bench_scenario_set_all"] is True
    assert payload["checks"]["locomo_dataset_valid"] is True
    assert payload["checks"]["longmemeval_dataset_valid"] is True
    assert payload["sanitized_config"]["agent_bench_scenario_set"] == "all"
    assert payload["sanitized_config"]["locomo_case_count"] == 600
    assert payload["sanitized_config"]["longmemeval_case_count"] == 600
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


def test_top_evidence_preflight_rejects_partial_agent_scenario_set(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_AGENT_BENCH_SCENARIO_SET="realistic"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["agent_bench_scenario_set_all"] is False
    assert result.sanitized_config["agent_bench_scenario_set"] == "realistic"
    assert any("SCENARIO_SET=all" in failure for failure in result.failures)


def test_top_evidence_preflight_ignores_lower_publishable_floor_overrides(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_TOP_EVIDENCE_MIN_PUBLIC_CASES="1",
            MEMORY_TOP_EVIDENCE_MIN_PUBLIC_ACCURACY="0.1",
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is True
    assert result.sanitized_config["top_evidence_min_public_cases"] == 600
    assert result.sanitized_config["top_evidence_min_public_accuracy"] == 0.902
    assert result.sanitized_config["public_benchmark_max_cases"] == 600
    assert result.sanitized_config["public_benchmark_min_accuracy"] == 0.902


def test_top_evidence_preflight_allows_only_stricter_case_floor_overrides(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_TOP_EVIDENCE_MIN_PUBLIC_CASES="700"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["public_benchmark_case_count_representative"] is True
    assert result.checks["locomo_dataset_case_count_representative"] is False
    assert result.checks["longmemeval_dataset_case_count_representative"] is False
    assert result.sanitized_config["top_evidence_min_public_cases"] == 700
    assert result.sanitized_config["public_benchmark_max_cases"] == 700


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


def test_top_evidence_preflight_rejects_empty_dataset_file(tmp_path: Path) -> None:
    env = _top_evidence_env(tmp_path)
    Path(env["MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET"]).write_text("[]", encoding="utf-8")

    result = run_top_evidence_preflight(
        env=env,
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["locomo_dataset_valid"] is False
    assert result.checks["locomo_dataset_case_count_representative"] is False
    assert any("valid locomo cases" in failure for failure in result.failures)


def test_top_evidence_preflight_rejects_dataset_case_count_below_config(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, case_count=599),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["locomo_dataset_case_count_representative"] is False
    assert result.checks["longmemeval_dataset_case_count_representative"] is False
    assert result.sanitized_config["locomo_case_count"] == 599
    assert result.sanitized_config["longmemeval_case_count"] == 599


def test_top_evidence_preflight_rejects_dataset_with_wrong_benchmark_cases(
    tmp_path: Path,
) -> None:
    env = _top_evidence_env(tmp_path)
    Path(env["MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET"]).write_text(
        json.dumps(_benchmark_cases("longmemeval", count=600)),
        encoding="utf-8",
    )

    result = run_top_evidence_preflight(
        env=env,
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["locomo_dataset_valid"] is False
    assert result.sanitized_config["locomo_case_count"] == 0


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
