"""Preflight checks for publishable Infinity Context top-evidence runs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from infinity_context_core.reporting import git_metadata

from infinity_context_server.eval_constants import (
    _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS,
    LOCOMO_BENCHMARK_SUITE,
    LONGMEMEVAL_BENCHMARK_SUITE,
)
from infinity_context_server.public_benchmark import (
    BenchmarkValidationError,
    load_public_benchmark_dataset_profile,
)

DEFAULT_MIN_PUBLIC_CASES = max(
    int(floor["min_case_count"])
    for floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.values()
)
DEFAULT_MIN_PUBLIC_ACCURACY = max(
    float(floor["min_accuracy"])
    for floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.values()
)
DEFAULT_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS = 60.0
MAX_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS = 120.0
MIN_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS = 5.0
REQUIRED_MULTIMODAL_AUDIO_TYPES = frozenset({".mp3", ".wav"})
REQUIRED_AGENT_SCENARIO_SET = "all"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
SAFE_VISION_DETAILS = frozenset({"auto", "high", "low"})


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
            "suite": "infinity-context-top-evidence-preflight",
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
    requested_public_case_floor = _positive_int_env(
        env,
        "MEMORY_TOP_EVIDENCE_MIN_PUBLIC_CASES",
        DEFAULT_MIN_PUBLIC_CASES,
    )
    public_case_floor_overridden = requested_public_case_floor > DEFAULT_MIN_PUBLIC_CASES
    min_public_cases = max(
        DEFAULT_MIN_PUBLIC_CASES,
        requested_public_case_floor,
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
    multimodal_required_audio_types = _suffix_set_env(
        env,
        "MEMORY_MULTIMODAL_PROVIDER_REQUIRED_AUDIO_TYPES",
        REQUIRED_MULTIMODAL_AUDIO_TYPES,
    )
    multimodal_invalid_key_probe = _bool_env(
        env,
        "MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY",
    )
    multimodal_skip_invalid_key_probe = _bool_env(
        env,
        "MEMORY_MULTIMODAL_PROVIDER_SKIP_INVALID_KEY_PROBE",
    )
    multimodal_timeout_seconds = _float_env(
        env,
        "MEMORY_EXTRACTION_PROVIDER_TIMEOUT_SECONDS",
        DEFAULT_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS,
    )
    vision_model = env.get("MEMORY_EXTRACTION_VISION_MODEL", "gpt-4.1-mini").strip()
    vision_detail = env.get("MEMORY_EXTRACTION_VISION_DETAIL", "low").strip().lower()
    transcription_model = env.get(
        "MEMORY_TRANSCRIPTION_OPENAI_MODEL",
        "gpt-4o-mini-transcribe",
    ).strip()

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
    competitive_floor_mode = _bool_env(env, "MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR")

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

    checks["multimodal_live_invalid_key_probe_enabled"] = (
        multimodal_invalid_key_probe and not multimodal_skip_invalid_key_probe
    )
    _append_failure(
        checks,
        failures,
        "multimodal_live_invalid_key_probe_enabled",
        (
            "Set MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY=1 and do not set "
            "MEMORY_MULTIMODAL_PROVIDER_SKIP_INVALID_KEY_PROBE for publishable "
            "multimodal provider evidence"
        ),
    )

    checks["multimodal_live_audio_format_matrix"] = REQUIRED_MULTIMODAL_AUDIO_TYPES.issubset(
        multimodal_required_audio_types
    )
    _append_failure(
        checks,
        failures,
        "multimodal_live_audio_format_matrix",
        "Top multimodal evidence must require both .wav and .mp3 transcription fixtures",
    )

    checks["multimodal_live_vision_model_present"] = _safe_model_name(vision_model)
    _append_failure(
        checks,
        failures,
        "multimodal_live_vision_model_present",
        "Set MEMORY_EXTRACTION_VISION_MODEL to a real provider model",
    )

    checks["multimodal_live_transcription_model_present"] = _safe_model_name(
        transcription_model
    )
    _append_failure(
        checks,
        failures,
        "multimodal_live_transcription_model_present",
        "Set MEMORY_TRANSCRIPTION_OPENAI_MODEL to a real provider model",
    )

    checks["multimodal_live_vision_detail_valid"] = vision_detail in SAFE_VISION_DETAILS
    _append_failure(
        checks,
        failures,
        "multimodal_live_vision_detail_valid",
        "MEMORY_EXTRACTION_VISION_DETAIL must be low, high or auto",
    )

    checks["multimodal_live_timeout_bounded"] = (
        MIN_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS
        <= multimodal_timeout_seconds
        <= MAX_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS
    )
    _append_failure(
        checks,
        failures,
        "multimodal_live_timeout_bounded",
        (
            "MEMORY_EXTRACTION_PROVIDER_TIMEOUT_SECONDS must be between "
            f"{MIN_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS:g} and "
            f"{MAX_MULTIMODAL_PROVIDER_TIMEOUT_SECONDS:g}"
        ),
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
    checks["public_benchmark_competitive_floor_mode"] = competitive_floor_mode
    _append_failure(
        checks,
        failures,
        "public_benchmark_competitive_floor_mode",
        "Top evidence requires MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR=true",
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
    locomo_profile = _dataset_profile(locomo_dataset, benchmark="locomo")
    longmemeval_profile = _dataset_profile(
        longmemeval_dataset,
        benchmark="longmemeval",
    )
    locomo_case_count = _profile_int(locomo_profile, "case_count")
    longmemeval_case_count = _profile_int(longmemeval_profile, "case_count")
    locomo_unique_case_id_count = _profile_int(locomo_profile, "unique_case_id_count")
    longmemeval_unique_case_id_count = _profile_int(
        longmemeval_profile,
        "unique_case_id_count",
    )
    locomo_duplicate_case_id_count = _profile_int(
        locomo_profile,
        "duplicate_case_id_count",
    )
    longmemeval_duplicate_case_id_count = _profile_int(
        longmemeval_profile,
        "duplicate_case_id_count",
    )
    locomo_dataset_sha256 = _profile_str(locomo_profile, "dataset_hash")
    longmemeval_dataset_sha256 = _profile_str(longmemeval_profile, "dataset_hash")
    checks["locomo_dataset_file"] = locomo_dataset is not None
    checks["longmemeval_dataset_file"] = longmemeval_dataset is not None
    checks["locomo_dataset_valid"] = locomo_case_count is not None and locomo_case_count > 0
    checks["longmemeval_dataset_valid"] = (
        longmemeval_case_count is not None and longmemeval_case_count > 0
    )
    locomo_min_cases = _public_benchmark_required_case_count(
        LOCOMO_BENCHMARK_SUITE,
        min_public_cases=min_public_cases,
        floor_overridden=public_case_floor_overridden,
    )
    longmemeval_min_cases = _public_benchmark_required_case_count(
        LONGMEMEVAL_BENCHMARK_SUITE,
        min_public_cases=min_public_cases,
        floor_overridden=public_case_floor_overridden,
    )
    checks["locomo_dataset_case_count_representative"] = (
        locomo_case_count is not None and locomo_case_count >= locomo_min_cases
    )
    checks["longmemeval_dataset_case_count_representative"] = (
        longmemeval_case_count is not None and longmemeval_case_count >= longmemeval_min_cases
    )
    checks["locomo_dataset_unique_case_ids"] = (
        locomo_unique_case_id_count is not None
        and locomo_unique_case_id_count >= locomo_min_cases
        and locomo_duplicate_case_id_count == 0
    )
    checks["longmemeval_dataset_unique_case_ids"] = (
        longmemeval_unique_case_id_count is not None
        and longmemeval_unique_case_id_count >= longmemeval_min_cases
        and longmemeval_duplicate_case_id_count == 0
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
            f"{locomo_min_cases} locomo cases"
        ),
    )
    _append_failure(
        checks,
        failures,
        "longmemeval_dataset_case_count_representative",
        (
            "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET must contain at least "
            f"{longmemeval_min_cases} longmemeval cases"
        ),
    )
    _append_failure(
        checks,
        failures,
        "locomo_dataset_unique_case_ids",
        (
            "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET must contain at least "
            f"{locomo_min_cases} unique locomo case IDs and no duplicate case IDs"
        ),
    )
    _append_failure(
        checks,
        failures,
        "longmemeval_dataset_unique_case_ids",
        (
            "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET must contain at least "
            f"{longmemeval_min_cases} unique longmemeval case IDs and no duplicate case IDs"
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
            "locomo_dataset": locomo_dataset.name if locomo_dataset is not None else None,
            "locomo_dataset_sha256": locomo_dataset_sha256,
            "locomo_duplicate_case_id_count": locomo_duplicate_case_id_count,
            "locomo_unique_case_id_count": locomo_unique_case_id_count,
            "longmemeval_dataset": (
                longmemeval_dataset.name if longmemeval_dataset is not None else None
            ),
            "longmemeval_dataset_sha256": longmemeval_dataset_sha256,
            "longmemeval_duplicate_case_id_count": longmemeval_duplicate_case_id_count,
            "longmemeval_unique_case_id_count": longmemeval_unique_case_id_count,
            "locomo_case_count": locomo_case_count,
            "longmemeval_case_count": longmemeval_case_count,
            "multimodal_invalid_key_probe_enabled": multimodal_invalid_key_probe,
            "multimodal_required_audio_types": sorted(multimodal_required_audio_types),
            "multimodal_skip_invalid_key_probe": multimodal_skip_invalid_key_probe,
            "multimodal_timeout_seconds": multimodal_timeout_seconds,
            "openai_key_present": openai_key_present,
            "public_benchmark_competitive_floor_mode": competitive_floor_mode,
            "public_benchmark_competitive_floors": {
                name: dict(floor)
                for name, floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.items()
            },
            "public_benchmark_max_cases": configured_cases,
            "public_benchmark_min_accuracy": configured_accuracy,
            "public_benchmark_name": benchmark_name,
            "top_evidence_min_public_accuracy": min_public_accuracy,
            "top_evidence_min_public_cases": min_public_cases,
            "transcription_model": transcription_model or None,
            "vision_detail": vision_detail,
            "vision_model": vision_model or None,
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


def _dataset_profile(path: Path | None, *, benchmark: str) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        return load_public_benchmark_dataset_profile(
            dataset_path=path,
            benchmark=benchmark,
        )
    except (BenchmarkValidationError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _profile_int(profile: Mapping[str, object] | None, key: str) -> int | None:
    if profile is None:
        return None
    value = profile.get(key)
    return value if isinstance(value, int) else None


def _profile_str(profile: Mapping[str, object] | None, key: str) -> str | None:
    if profile is None:
        return None
    value = profile.get(key)
    return value if isinstance(value, str) and value else None


def _public_benchmark_required_case_count(
    benchmark: str,
    *,
    min_public_cases: int,
    floor_overridden: bool,
) -> int:
    floor = _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS[benchmark]
    min_case_count = int(floor["min_case_count"])
    return max(min_case_count, min_public_cases) if floor_overridden else min_case_count


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


def _suffix_set_env(
    env: Mapping[str, str],
    name: str,
    default: frozenset[str],
) -> frozenset[str]:
    value = env.get(name, "").strip()
    if not value:
        return default
    suffixes: set[str] = set()
    for raw_item in value.replace(";", ",").split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        suffixes.add(item if item.startswith(".") else f".{item}")
    return frozenset(suffixes)


def _bool_env(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in TRUE_VALUES


def _safe_model_name(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    return text not in {"disabled", "mock", "noop", "none", "off"}


def _repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
