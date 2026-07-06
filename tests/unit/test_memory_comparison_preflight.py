from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import eval as eval_module
from infinity_context_server.memory_comparison_preflight import (
    MEMORY_COMPARISON_PREFLIGHT_SUITE,
    MemoryComparisonPreflightCheck,
    MemoryComparisonPreflightConfig,
    run_memory_comparison_preflight,
)


def test_memory_comparison_preflight_ready_for_locomo_fast(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo-mini.json"
    _write_official_locomo_fast_dataset(dataset)

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
    assert result["diagnostics"]["safe_reporting_contracts"] == [
        {
            "name": "quality_diagnostics",
            "schema_version": "quality_diagnostics.v2",
            "report_modes": ["compact"],
            "safe_payload": True,
        },
        {
            "name": "evidence_bundle_gap_report",
            "schema_version": "evidence_bundle_gap_report.v1",
            "report_modes": ["compact"],
            "safe_payload": True,
        },
        {
            "name": "answer_context_provenance",
            "schema_version": "answer_context_provenance.v1",
            "report_modes": ["compact"],
            "safe_payload": True,
        },
        {
            "name": "answer_context_support_gaps",
            "schema_version": "answer_context_support_gaps.v1",
            "report_modes": ["compact"],
            "safe_payload": True,
        },
        {
            "name": "temporal_grounding_table",
            "schema_version": "temporal_grounding.v1",
            "report_modes": ["compact"],
            "safe_payload": True,
        },
    ]


def test_memory_comparison_preflight_accepts_wrapped_locomo_fast_dataset(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-wrapped.json"
    wrapped = {
        "data": _official_locomo_fast_dataset_payload(),
        "metadata": {"source": "locomo"},
    }
    dataset.write_text(json.dumps(wrapped), encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ready_for_locomo_fast"] is True
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["passed"] is True
    assert check["details"]["official_turn_case_count"] == 40
    assert check["details"]["selected_by_group"] == {
        "multi-hop": 10,
        "temporal": 10,
        "open-domain": 10,
        "single-hop": 10,
    }
    assert check["details"]["selected_with_turn_evidence_by_group"] == {
        "multi-hop": 10,
        "temporal": 10,
        "open-domain": 10,
        "single-hop": 10,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [{"sample_id": "unit"}],
        {"cases": [{"id": "unit"}], "metadata": {"source": "not-locomo"}},
    ],
    ids=("list", "object"),
)
def test_memory_comparison_preflight_blocks_non_locomo_json_fast_readiness(
    tmp_path: Path,
    payload: object,
) -> None:
    dataset = tmp_path / "not-locomo.json"
    dataset.write_text(json.dumps(payload), encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["safe_to_run_live"] is True
    assert result["ready_for_locomo_fast"] is False
    assert result["fast_readiness_blockers"] == [
        "locomo_fast_dataset_case_coverage"
    ]
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["reason_code"] == "locomo_fast_dataset_insufficient_cases"
    assert check["details"]["official_turn_case_count"] == 0
    assert check["details"]["missing_groups"] == [
        "multi-hop",
        "temporal",
        "open-domain",
        "single-hop",
    ]


def test_memory_comparison_preflight_blocks_underfilled_locomo_fast_dataset(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-underfilled.json"
    _write_official_locomo_fast_dataset(dataset, cases_per_group=2)

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            case_set="locomo-fast-temporal",
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["ready_for_locomo_fast"] is False
    assert result["fast_readiness_blockers"] == [
        "locomo_fast_dataset_case_coverage"
    ]
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["details"]["requested_groups"] == ["temporal"]
    assert check["details"]["requested_per_group"] == 10
    assert check["details"]["selected_by_group"] == {"temporal": 2}
    assert check["details"]["missing_groups"] == ["temporal"]


def test_memory_comparison_preflight_blocks_unbacked_locomo_evidence_refs(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-unbacked-evidence.json"
    payload = _official_locomo_fast_dataset_payload()
    for sample in payload:
        for qa in sample["qa"]:
            assert isinstance(qa, dict)
            qa["evidence"] = ["D9:99"]
    dataset.write_text(json.dumps(payload), encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["ready_for_locomo_fast"] is False
    assert result["fast_readiness_blockers"] == [
        "locomo_fast_dataset_case_coverage"
    ]
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["reason_code"] == "locomo_fast_dataset_unbacked_evidence_refs"
    assert check["details"]["selected_by_group"] == {
        "multi-hop": 10,
        "temporal": 10,
        "open-domain": 10,
        "single-hop": 10,
    }
    assert check["details"]["selected_with_turn_evidence_by_group"] == {
        "multi-hop": 0,
        "temporal": 0,
        "open-domain": 0,
        "single-hop": 0,
    }
    assert check["details"]["missing_groups"] == []
    assert check["details"]["missing_turn_evidence_groups"] == [
        "multi-hop",
        "temporal",
        "open-domain",
        "single-hop",
    ]


def test_memory_comparison_preflight_accepts_nested_textual_locomo_evidence_refs(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-nested-evidence.json"
    payload = _official_locomo_fast_dataset_payload()
    for sample in payload:
        for qa in sample["qa"]:
            assert isinstance(qa, dict)
            qa["evidence"] = [
                {"supporting_facts": [{"evidence_ref": "turn D1:1 backs this"}]}
            ]
    dataset.write_text(json.dumps(payload), encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["ready_for_locomo_fast"] is True
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["passed"] is True
    assert check["details"]["selected_with_turn_evidence_by_group"] == {
        "multi-hop": 10,
        "temporal": 10,
        "open-domain": 10,
        "single-hop": 10,
    }


def test_memory_comparison_preflight_blocks_any_underfilled_requested_group(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-one-underfilled-group.json"
    _write_official_locomo_fast_dataset(
        dataset,
        cases_per_group_by_category={1: 10, 2: 9, 3: 10, 4: 10},
    )

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            env={"MEM0_API_KEY": "secret-mem0"},
        )
    )

    assert result["ok"] is True
    assert result["ready_for_locomo_fast"] is False
    assert result["fast_readiness_blockers"] == [
        "locomo_fast_dataset_case_coverage"
    ]
    check = _check(result, "locomo_fast_dataset_case_coverage")
    assert check["details"]["selected_by_group"] == {
        "multi-hop": 10,
        "temporal": 9,
        "open-domain": 10,
        "single-hop": 10,
    }
    assert check["details"]["missing_groups"] == ["temporal"]


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
    assert _check(result, "allow_live_gate")["reason_code"] == (
        "allow_live_gate_failed"
    )
    assert _check(result, "memo_auth_token_configured")["reason_code"] == (
        "memo_auth_token_configured_failed"
    )


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
    _write_official_locomo_fast_dataset(dataset)
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
    assert payload["diagnostics"]["cli_readiness"] == {
        "preflight_only": True,
        "ready_to_run_live_benchmark": True,
        "exit_code": 0,
        "exit_reason": "ready",
    }
    assert "secret-service-token" not in captured.out
    assert "secret-mem0-token" not in captured.out
    assert "secret-service-token" not in captured.err
    assert "secret-mem0-token" not in captured.err


def test_memory_comparison_preflight_cli_exits_nonzero_when_fast_gate_degraded(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    _write_official_locomo_fast_dataset(dataset)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "secret-service-token")
    monkeypatch.setenv("MEM0_API_KEY", "secret-mem0-token")

    with pytest.raises(SystemExit) as excinfo:
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
                "all",
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
    assert excinfo.value.code == 2
    assert payload["ok"] is True
    assert payload["status"] == "degraded"
    assert payload["ready_for_locomo_fast"] is False
    assert payload["fast_readiness_blockers"] == ["locomo_fast_case_set"]
    assert payload["diagnostics"]["cli_readiness"] == {
        "preflight_only": True,
        "ready_to_run_live_benchmark": False,
        "exit_code": 2,
        "exit_reason": "fast_readiness_blockers",
    }
    assert "secret-service-token" not in captured.out
    assert "secret-mem0-token" not in captured.out


def test_memory_comparison_preflight_cli_reports_failed_readiness_exit(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    _write_official_locomo_fast_dataset(dataset)
    monkeypatch.delenv("MEMORY_EVAL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MEMORY_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("MEM0_API_KEY", "secret-mem0-token")

    with pytest.raises(SystemExit) as excinfo:
        eval_module.main(
            [
                "memory-comparison-benchmark",
                "--dataset",
                str(dataset),
                "--memo-api-url",
                "http://memo.example",
                "--mem0-url",
                "http://mem0.example",
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
    assert excinfo.value.code == 1
    assert payload["ok"] is False
    assert set(payload["failed_checks"]) == {
        "allow_live_gate",
        "memo_auth_token_configured",
    }
    assert payload["diagnostics"]["cli_readiness"] == {
        "preflight_only": True,
        "ready_to_run_live_benchmark": False,
        "exit_code": 1,
        "exit_reason": "failed_checks",
    }
    assert "secret-mem0-token" not in captured.out
    assert "secret-mem0-token" not in captured.err


def test_memory_comparison_preflight_probes_service_specific_contracts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    _write_official_locomo_fast_dataset(dataset)
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
    assert mem0_check["reason_code"] == "mem0_api_contract_missing_required_paths"


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


def test_memory_comparison_preflight_check_payload_details_are_bounded_json_safe() -> None:
    long_text = "x" * 300
    check = MemoryComparisonPreflightCheck(
        name=f"unit-{long_text}",
        passed=False,
        severity=f"required-{long_text}",
        reason=f"unit reason {long_text}",
        reason_code=f"unit_reason_{long_text}",
        details={
            f"key-{index}": float("nan") if index == 0 else "x" * 300
            for index in range(25)
        },
    )

    payload = check.to_payload()

    assert len(payload["details"]) == 20
    assert payload["name"].endswith("...")
    assert payload["severity"].endswith("...")
    assert payload["reason"].endswith("...")
    assert payload["reason_code"].endswith("...")
    assert payload["details"]["key-0"] == "nan"
    assert payload["details"]["key-1"].endswith("...")
    json.dumps(payload, allow_nan=False)


def test_memory_comparison_preflight_diagnostics_are_stable_and_bounded(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo-mini.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")

    result = run_memory_comparison_preflight(
        _config(
            dataset_path=dataset,
            top_k_cutoffs=tuple(range(1, 41)) + (50, 200),
            openai_api_key_env="CUSTOM_OPENAI_KEY",
            mem0_api_key_env="CUSTOM_MEM0_KEY",
            env={
                "CUSTOM_OPENAI_KEY": "secret-openai",
                "CUSTOM_MEM0_KEY": "secret-mem0",
            },
        )
    )

    diagnostics = result["diagnostics"]
    assert len(diagnostics["top_k_cutoffs"]) == 20
    assert diagnostics["top_k_cutoff_count"] == 42
    assert set(diagnostics["secrets"]) == {
        "auth_token_configured",
        "fallback_openai_api_key_configured",
        "fallback_openai_api_key_env",
        "mem0_api_key_configured",
        "mem0_api_key_env",
        "openai_api_key_configured",
        "openai_api_key_env",
    }
    assert diagnostics["secrets"]["mem0_api_key_env"] == "CUSTOM_MEM0_KEY"
    assert diagnostics["secrets"]["openai_api_key_env"] == "CUSTOM_OPENAI_KEY"
    serialized = json.dumps(result, sort_keys=True)
    assert "secret-openai" not in serialized
    assert "secret-mem0" not in serialized


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
    openai_api_key_env: str = "MEMORY_OPENAI_API_KEY",
    mem0_api_key_env: str = "MEM0_API_KEY",
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
        openai_api_key_env=openai_api_key_env,
        mem0_api_key_env=mem0_api_key_env,
        auth_token_configured=auth_token_configured,
        probe_services=probe_services,
        env=env or {},
    )


def _write_official_locomo_fast_dataset(
    path: Path,
    *,
    cases_per_group: int = 10,
    cases_per_group_by_category: dict[int, int] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            _official_locomo_fast_dataset_payload(
                cases_per_group=cases_per_group,
                cases_per_group_by_category=cases_per_group_by_category,
            )
        ),
        encoding="utf-8",
    )


def _official_locomo_fast_dataset_payload(
    *,
    cases_per_group: int = 10,
    cases_per_group_by_category: dict[int, int] | None = None,
) -> list[dict[str, object]]:
    qas: list[dict[str, object]] = []
    for category in (1, 2, 3, 4):
        category_case_count = (
            cases_per_group_by_category.get(category, cases_per_group)
            if cases_per_group_by_category is not None
            else cases_per_group
        )
        for index in range(category_case_count):
            qas.append(
                {
                    "question": (
                        f"What answer is needed for category {category} case {index}?"
                    ),
                    "answer": f"answer-{category}-{index}",
                    "evidence": ["D1:1"],
                    "category": category,
                }
            )
    return [
        {
            "sample_id": "unit-locomo",
            "conversation": {
                "speaker_a": "A",
                "session_1_date_time": "2023-01-01",
                "session_1": [
                    {
                        "dia_id": "D1:1",
                        "speaker": "A",
                        "text": "A compact LoCoMo fixture turn.",
                    }
                ],
            },
            "qa": qas,
        }
    ]


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
