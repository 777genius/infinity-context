from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from infinity_context_server import eval as eval_module
from infinity_context_server.memory_comparison_preflight import (
    MEMORY_COMPARISON_PREFLIGHT_SUITE,
    MemoryComparisonPreflightConfig,
    run_memory_comparison_preflight,
)


def test_memory_comparison_preflight_ready_for_locomo_fast(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["suite"] == MEMORY_COMPARISON_PREFLIGHT_SUITE
    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["safe_to_run_live"] is True
    assert result["ready_for_locomo_fast"] is True
    assert result["failed_checks"] == []
    assert result["warnings"] == []


def test_memory_comparison_preflight_reports_missing_required_gates(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            allow_live=False,
            auth_token_configured=False,
            env={},
        )
    )

    assert result["ok"] is False
    assert result["safe_to_run_live"] is False
    assert result["ready_for_locomo_fast"] is False
    assert set(result["failed_checks"]) == {
        "allow_live_gate",
        "memo_auth_token_configured",
    }
    assert result["warnings"] == ["mem0_api_key_configured"]


def test_memory_comparison_preflight_gates_openai_without_leaking_keys(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            answerer_provider="openai",
            answerer_model=None,
            allow_paid_llm=False,
            env={
                "MEM0_API_KEY": "secret-mem0-value",
                "MEMORY_OPENAI_API_KEY": "secret-openai-value",
            },
        )
    )

    serialized = json.dumps(result, sort_keys=True)
    assert result["ok"] is False
    assert result["safe_to_run_paid_llm"] is False
    assert "paid_llm_gate" in result["failed_checks"]
    assert "openai_answerer_model_configured" in result["failed_checks"]
    assert "secret-mem0-value" not in serialized
    assert "secret-openai-value" not in serialized


def test_memory_comparison_preflight_flags_full_case_set_not_fast_ready(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            case_set="all",
            report_mode="full",
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["safe_to_run_live"] is True
    assert result["ready_for_locomo_fast"] is False
    assert set(result["fast_readiness_blockers"]) == {
        "locomo_fast_case_set",
        "compact_report_mode",
    }


def test_memory_comparison_preflight_cli_prints_sanitized_json(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "secret-service-token")
    monkeypatch.setenv("MEM0_API_KEY", "secret-mem0-token")

    eval_module.main(
        [
            "memory-comparison-benchmark",
            "--dataset",
            str(dataset),
            "--memo-api-url",
            "http://memo.example",
            "--mem0-url",
            "http://mem0.example",
            "--allow-live",
            "--case-set",
            "locomo-fast",
            "--locomo-ingest-mode",
            "official-turns",
            "--report-mode",
            "compact",
            "--top-k",
            "200",
            "--preflight-only",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["suite"] == MEMORY_COMPARISON_PREFLIGHT_SUITE
    assert payload["ok"] is True
    assert payload["ready_for_locomo_fast"] is True
    assert "secret-service-token" not in captured.out
    assert "secret-mem0-token" not in captured.out
    assert "secret-service-token" not in captured.err
    assert "secret-mem0-token" not in captured.err


def test_memory_comparison_preflight_probes_service_specific_contracts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    requests: list[tuple[str, str]] = []
    _install_fake_httpx(
        monkeypatch,
        requests=requests,
        responses={
            ("http://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("http://mem0.example", "/openapi.json"): _FakeResponse(
                200,
                {"paths": {"/memories": {}, "/search": {}, "/other": {}}},
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
            probe_services=True,
        )
    )

    assert result["ok"] is True
    assert _check(result, "memo_api_reachable")["reason"] is None
    assert _check(result, "mem0_api_reachable")["reason"] is None
    assert result["ready_for_locomo_fast"] is True
    assert requests == [
        ("http://memo.example", "/v1/health"),
        ("http://mem0.example", "/openapi.json"),
    ]


def test_memory_comparison_preflight_rejects_wrong_mem0_service_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    _install_fake_httpx(
        monkeypatch,
        responses={
            ("http://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("http://mem0.example", "/openapi.json"): _FakeResponse(
                200,
                {"paths": {"/v1/context": {}, "/v1/facts": {}}},
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
            probe_services=True,
        )
    )

    mem0_check = _check(result, "mem0_api_reachable")
    assert result["ok"] is False
    assert result["ready_for_locomo_fast"] is False
    assert result["failed_checks"] == ["mem0_api_reachable"]
    assert mem0_check["details"]["required_paths"] == ["/memories", "/search"]
    assert mem0_check["details"]["matched_paths"] == []


def test_memory_comparison_preflight_rejects_wrong_memo_service_health(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    _install_fake_httpx(
        monkeypatch,
        responses={
            ("http://memo.example", "/v1/health"): _FakeResponse(404, {"detail": "nope"}),
            ("http://mem0.example", "/openapi.json"): _FakeResponse(
                200,
                {"paths": {"/memories": {}, "/search": {}}},
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
            probe_services=True,
        )
    )

    assert result["ok"] is False
    assert result["failed_checks"] == ["memo_api_reachable"]
    assert _check(result, "memo_api_reachable")["details"]["path"] == "/v1/health"


def _config(
    *,
    dataset_path: Path,
    case_set: str = "locomo-fast",
    locomo_ingest_mode: str = "official-turns",
    report_mode: str = "compact",
    top_k: int = 200,
    top_k_cutoffs: tuple[int, ...] = (10, 20, 50, 200),
    allow_live: bool = True,
    allow_paid_llm: bool = False,
    answerer_provider: str = "deterministic",
    judge_provider: str = "deterministic",
    answerer_model: str | None = None,
    judge_model: str | None = None,
    auth_token_configured: bool = True,
    probe_services: bool = False,
    env: dict[str, str] | None = None,
) -> MemoryComparisonPreflightConfig:
    return MemoryComparisonPreflightConfig(
        dataset_path=dataset_path,
        memo_api_url="http://memo.example",
        mem0_url="http://mem0.example",
        case_set=case_set,
        locomo_ingest_mode=locomo_ingest_mode,
        report_mode=report_mode,
        top_k=top_k,
        top_k_cutoffs=top_k_cutoffs,
        allow_live=allow_live,
        allow_paid_llm=allow_paid_llm,
        answerer_provider=answerer_provider,
        judge_provider=judge_provider,
        answerer_model=answerer_model,
        judge_model=judge_model,
        openai_api_key_env="MEMORY_OPENAI_API_KEY",
        mem0_api_key_env="MEM0_API_KEY",
        auth_token_configured=auth_token_configured,
        probe_services=probe_services,
        env=env or {},
    )


def _check(result: dict[str, object], name: str) -> dict[str, object]:
    checks = result["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check["name"] == name:
            return check
    raise AssertionError(f"missing check: {name}")


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _install_fake_httpx(
    monkeypatch,
    *,
    responses: dict[tuple[str, str], _FakeResponse],
    requests: list[tuple[str, str]] | None = None,
) -> None:
    class FakeClient:
        def __init__(self, *, base_url: str, **_: object) -> None:
            self._base_url = base_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, path: str) -> _FakeResponse:
            if requests is not None:
                requests.append((self._base_url, path))
            return responses[(self._base_url, path)]

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=FakeClient))
