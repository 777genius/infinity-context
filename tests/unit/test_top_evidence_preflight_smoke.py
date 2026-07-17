from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server import top_evidence_preflight
from infinity_context_server.top_evidence_preflight import (
    TopEvidencePreflightResult,
    run_top_evidence_preflight,
)


def _subscription_runtime_bridge(tmp_path: Path) -> Path:
    bridge = tmp_path / "subscription-runtime-codex"
    bridge.write_text("#!/bin/sh\n", encoding="utf-8")
    bridge.chmod(0o755)
    return bridge


def _subscription_runtime_env(bridge: Path, **overrides: str) -> dict[str, str]:
    env = {
        "MEMORY_LLM_PROVIDER": "subscription-runtime",
        "MEMORY_LLM_PROVIDER_BRIDGE_COMMAND": str(bridge),
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


def test_top_evidence_preflight_default_remains_publishable_strict(
    tmp_path: Path,
) -> None:
    bridge = _subscription_runtime_bridge(tmp_path)

    result = run_top_evidence_preflight(
        env=_subscription_runtime_env(bridge),
        cwd=tmp_path,
        docker_path="/usr/bin/docker",
        git={"commit": "abc123", "dirty": False},
    )
    payload = result.as_dict()

    assert result.ok is False
    assert payload["mode"] == "publishable"
    assert payload["publishable"] is True
    assert payload["sanitized_config"]["mode"] == "publishable"
    assert payload["sanitized_config"]["publishable"] is True
    assert "llm_provider_ready" not in result.failure_codes
    assert "agent_bench_model_present" in result.failure_codes
    assert "multimodal_live_invalid_key_probe_enabled" in result.failure_codes
    assert "public_benchmark_competitive_floor_mode" in result.failure_codes
    assert "locomo_dataset_file" in result.failure_codes
    assert "longmemeval_dataset_file" in result.failure_codes


def test_top_evidence_preflight_smoke_accepts_runtime_bridge_without_datasets(
    tmp_path: Path,
) -> None:
    bridge = _subscription_runtime_bridge(tmp_path)

    result = run_top_evidence_preflight(
        env=_subscription_runtime_env(
            bridge,
            MEMORY_TOP_EVIDENCE_PREFLIGHT_MODE="smoke",
        ),
        cwd=tmp_path,
        docker_path="",
        git={"commit": "abc123", "dirty": False},
    )
    payload = result.as_dict()
    rendered = json.dumps(payload, sort_keys=True)

    assert result.ok is True
    assert result.failures == ()
    assert result.failure_codes == ()
    assert payload["mode"] == "smoke"
    assert payload["publishable"] is False
    assert payload["sanitized_config"]["mode"] == "smoke"
    assert payload["sanitized_config"]["publishable"] is False
    assert payload["checks"]["llm_provider_ready"] is True
    assert payload["checks"]["git_clean_or_dirty_allowed"] is True
    assert payload["checks"]["docker_available"] is False
    assert payload["checks"]["agent_bench_model_present"] is False
    assert payload["checks"]["locomo_dataset_file"] is False
    assert payload["checks"]["longmemeval_dataset_file"] is False
    assert payload["checks"]["multimodal_live_invalid_key_probe_enabled"] is False
    assert str(bridge) not in rendered
    assert str(tmp_path) not in rendered


def test_top_evidence_preflight_smoke_profiles_provided_datasets_without_paths(
    tmp_path: Path,
) -> None:
    bridge = _subscription_runtime_bridge(tmp_path)
    locomo = tmp_path / "locomo.json"
    longmemeval = tmp_path / "longmemeval.json"
    locomo.write_text(json.dumps(_benchmark_cases("locomo", count=1)), encoding="utf-8")
    longmemeval.write_text(
        json.dumps(_benchmark_cases("longmemeval", count=2)),
        encoding="utf-8",
    )

    result = run_top_evidence_preflight(
        env=_subscription_runtime_env(
            bridge,
            MEMORY_TOP_EVIDENCE_PREFLIGHT_MODE="smoke",
            MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET=str(locomo),
            MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET=str(longmemeval),
        ),
        cwd=tmp_path,
        docker_path="",
        git={"commit": "abc123", "dirty": False},
    )
    payload = result.as_dict()
    sanitized_config = payload["sanitized_config"]
    rendered = json.dumps(payload, sort_keys=True)

    assert result.ok is True
    assert payload["checks"]["locomo_dataset_case_count_representative"] is False
    assert payload["checks"]["longmemeval_dataset_case_count_representative"] is False
    assert sanitized_config["locomo_dataset"] == "locomo.json"
    assert sanitized_config["longmemeval_dataset"] == "longmemeval.json"
    assert sanitized_config["locomo_case_count"] == 1
    assert sanitized_config["longmemeval_case_count"] == 2
    assert len(str(sanitized_config["locomo_dataset_sha256"])) == 64
    assert len(str(sanitized_config["longmemeval_dataset_sha256"])) == 64
    assert str(locomo) not in rendered
    assert str(longmemeval) not in rendered
    assert str(tmp_path) not in rendered


def test_top_evidence_preflight_smoke_still_requires_llm_provider(
    tmp_path: Path,
) -> None:
    result = run_top_evidence_preflight(
        env={"MEMORY_TOP_EVIDENCE_PREFLIGHT_MODE": "smoke"},
        cwd=tmp_path,
        docker_path="",
        git={"commit": "abc123", "dirty": False},
    )
    payload = result.as_dict()

    assert result.ok is False
    assert result.failure_codes == ("llm_provider_ready",)
    assert payload["mode"] == "smoke"
    assert payload["publishable"] is False
    assert payload["checks"]["llm_provider_ready"] is False
    assert payload["sanitized_config"]["llm_provider"]["failure_code"] == (
        "llm_provider_missing"
    )


def test_top_evidence_preflight_cli_accepts_smoke_mode(monkeypatch, capsys) -> None:
    seen: dict[str, str | None] = {}

    def fake_run_top_evidence_preflight(
        *,
        mode: str | None = None,
    ) -> TopEvidencePreflightResult:
        seen["mode"] = mode
        return TopEvidencePreflightResult(
            ok=True,
            mode="smoke",
            publishable=False,
            checks={},
            failures=(),
            failure_codes=(),
            expected_git_commit="abc123",
            allow_dirty_top_evidence=False,
            sanitized_config={"mode": "smoke", "publishable": False},
        )

    monkeypatch.setattr(
        top_evidence_preflight,
        "run_top_evidence_preflight",
        fake_run_top_evidence_preflight,
    )

    assert top_evidence_preflight.main(["--mode", "smoke", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert seen["mode"] == "smoke"
    assert payload["mode"] == "smoke"
    assert payload["publishable"] is False
    assert payload["sanitized_config"]["mode"] == "smoke"
    assert payload["sanitized_config"]["publishable"] is False
