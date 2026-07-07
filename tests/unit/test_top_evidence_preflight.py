from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server import top_evidence_preflight
from infinity_context_server.top_evidence_preflight import run_top_evidence_preflight


def _top_evidence_env(
    tmp_path: Path,
    *,
    locomo_case_count: int = 600,
    longmemeval_case_count: int = 500,
    **overrides: str,
) -> dict[str, str]:
    locomo = tmp_path / "locomo.json"
    longmemeval = tmp_path / "longmemeval.json"
    locomo.write_text(
        json.dumps(_benchmark_cases("locomo", count=locomo_case_count)),
        encoding="utf-8",
    )
    longmemeval.write_text(
        json.dumps(_benchmark_cases("longmemeval", count=longmemeval_case_count)),
        encoding="utf-8",
    )
    env = {
        "MEMORY_OPENAI_API_KEY": "sk-test-secret-value",
        "MEMORY_AGENT_BENCH_MODEL": "gpt-test",
        "MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY": "1",
        "MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR": "true",
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
    assert payload["schema_version"] == "top-evidence-preflight.v1"
    assert payload["failure_codes"] == []
    assert payload["checks"]["public_benchmark_case_count_representative"] is True
    assert payload["checks"]["agent_bench_scenario_set_all"] is True
    assert payload["checks"]["multimodal_live_invalid_key_probe_enabled"] is True
    assert payload["checks"]["multimodal_live_audio_format_matrix"] is True
    assert payload["checks"]["locomo_dataset_valid"] is True
    assert payload["checks"]["longmemeval_dataset_valid"] is True
    assert payload["checks"]["locomo_dataset_unique_case_ids"] is True
    assert payload["checks"]["longmemeval_dataset_unique_case_ids"] is True
    assert payload["sanitized_config"]["agent_bench_scenario_set"] == "all"
    assert payload["sanitized_config"]["multimodal_required_audio_types"] == [
        ".mp3",
        ".wav",
    ]
    assert payload["sanitized_config"]["multimodal_invalid_key_probe_enabled"] is True
    assert payload["sanitized_config"]["multimodal_skip_invalid_key_probe"] is False
    assert payload["sanitized_config"]["locomo_case_count"] == 600
    assert payload["sanitized_config"]["longmemeval_case_count"] == 500
    assert payload["sanitized_config"]["locomo_dataset"] == "locomo.json"
    assert payload["sanitized_config"]["longmemeval_dataset"] == "longmemeval.json"
    assert len(str(payload["sanitized_config"]["locomo_dataset_sha256"])) == 64
    assert len(str(payload["sanitized_config"]["longmemeval_dataset_sha256"])) == 64
    assert payload["sanitized_config"]["locomo_unique_case_id_count"] == 600
    assert payload["sanitized_config"]["longmemeval_unique_case_id_count"] == 500
    assert payload["sanitized_config"]["locomo_duplicate_case_id_count"] == 0
    assert payload["sanitized_config"]["longmemeval_duplicate_case_id_count"] == 0
    assert payload["sanitized_config"]["public_benchmark_competitive_floor_mode"] is True
    assert payload["sanitized_config"]["public_benchmark_min_accuracy"] == 0.947
    assert "sk-test-secret-value" not in json.dumps(payload)
    assert str(tmp_path) not in json.dumps(payload)


def test_top_evidence_preflight_lightweight_profile_counts_cases(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo.json"
    dataset.write_text(json.dumps(_benchmark_cases("locomo", count=3)), encoding="utf-8")

    profile = top_evidence_preflight._lightweight_dataset_profile(
        dataset,
        benchmark="locomo",
    )

    assert profile is not None
    assert profile["case_count"] == 3
    assert profile["unique_case_id_count"] == 3
    assert profile["duplicate_case_id_count"] == 0
    assert profile["dataset_path_label"] == "locomo.json"
    assert len(str(profile["dataset_hash"])) == 64


def test_top_evidence_preflight_accepts_openai_key_file_without_leak(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "openai.key"
    key_file.write_text("sk-test-secret-from-file", encoding="utf-8")
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_OPENAI_API_KEY="",
            OPENAI_API_KEY="",
            MEMORY_OPENAI_API_KEY_FILE=str(key_file),
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    payload = result.as_dict()
    rendered = json.dumps(payload, sort_keys=True)

    assert result.ok is True
    assert payload["checks"]["openai_key_present"] is True
    assert payload["sanitized_config"]["openai_key_file_present"] is True
    assert payload["sanitized_config"]["openai_key_present"] is True
    assert "sk-test-secret-from-file" not in rendered
    assert str(key_file) not in rendered
    assert str(tmp_path) not in rendered


def test_top_evidence_preflight_falls_back_to_standard_docker_path_when_path_is_restricted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\n", encoding="utf-8")
    docker.chmod(0o755)
    monkeypatch.setattr(
        top_evidence_preflight,
        "TOP_EVIDENCE_EXECUTABLE_FALLBACK_DIRS",
        (bin_dir,),
    )

    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, PATH=""),
        cwd=tmp_path,
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is True
    assert result.checks["docker_available"] is True
    assert result.sanitized_config["docker_available"] is True


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
    assert result.failure_codes == ("git_clean_or_dirty_allowed",)
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


def test_top_evidence_preflight_requires_public_benchmark_competitive_mode(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(tmp_path, MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR="false"),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["public_benchmark_competitive_floor_mode"] is False
    assert any("COMPETITIVE_FLOOR=true" in failure for failure in result.failures)


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


def test_top_evidence_preflight_requires_multimodal_invalid_key_probe(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY="0",
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["multimodal_live_invalid_key_probe_enabled"] is False
    assert result.sanitized_config["multimodal_invalid_key_probe_enabled"] is False
    assert any("PROBE_INVALID_KEY=1" in failure for failure in result.failures)


def test_top_evidence_preflight_rejects_skipped_multimodal_invalid_key_probe(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_MULTIMODAL_PROVIDER_SKIP_INVALID_KEY_PROBE="1",
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["multimodal_live_invalid_key_probe_enabled"] is False
    assert result.sanitized_config["multimodal_skip_invalid_key_probe"] is True
    assert any("SKIP_INVALID_KEY_PROBE" in failure for failure in result.failures)


def test_top_evidence_preflight_requires_wav_and_mp3_multimodal_audio_matrix(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_MULTIMODAL_PROVIDER_REQUIRED_AUDIO_TYPES="wav",
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["multimodal_live_audio_format_matrix"] is False
    assert result.sanitized_config["multimodal_required_audio_types"] == [".wav"]
    assert any("both .wav and .mp3" in failure for failure in result.failures)


def test_top_evidence_preflight_rejects_non_provider_multimodal_models(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            MEMORY_EXTRACTION_VISION_MODEL="mock",
            MEMORY_TRANSCRIPTION_OPENAI_MODEL="disabled",
            MEMORY_EXTRACTION_VISION_DETAIL="ultra",
            MEMORY_EXTRACTION_PROVIDER_TIMEOUT_SECONDS="240",
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["multimodal_live_vision_model_present"] is False
    assert result.checks["multimodal_live_transcription_model_present"] is False
    assert result.checks["multimodal_live_vision_detail_valid"] is False
    assert result.checks["multimodal_live_timeout_bounded"] is False
    assert result.sanitized_config["vision_model"] == "mock"
    assert result.sanitized_config["transcription_model"] == "disabled"


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
    assert result.sanitized_config["top_evidence_min_public_accuracy"] == 0.947
    assert result.sanitized_config["public_benchmark_max_cases"] == 600
    assert result.sanitized_config["public_benchmark_min_accuracy"] == 0.947


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


def test_top_evidence_preflight_rejects_dataset_case_count_below_floor(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env=_top_evidence_env(
            tmp_path,
            locomo_case_count=599,
            longmemeval_case_count=499,
        ),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["locomo_dataset_case_count_representative"] is False
    assert result.checks["longmemeval_dataset_case_count_representative"] is False
    assert result.sanitized_config["locomo_case_count"] == 599
    assert result.sanitized_config["longmemeval_case_count"] == 499


def test_top_evidence_preflight_rejects_duplicate_public_benchmark_case_ids(
    tmp_path: Path,
) -> None:
    env = _top_evidence_env(tmp_path)
    duplicate_cases = _benchmark_cases("locomo", count=600)
    for item in duplicate_cases:
        item["case_id"] = "duplicate-locomo-case"
    Path(env["MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET"]).write_text(
        json.dumps(duplicate_cases),
        encoding="utf-8",
    )

    result = run_top_evidence_preflight(
        env=env,
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["locomo_dataset_case_count_representative"] is True
    assert result.checks["locomo_dataset_unique_case_ids"] is False
    assert result.sanitized_config["locomo_case_count"] == 600
    assert result.sanitized_config["locomo_unique_case_id_count"] == 1
    assert result.sanitized_config["locomo_duplicate_case_id_count"] == 599
    assert any("unique locomo case IDs" in failure for failure in result.failures)


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
