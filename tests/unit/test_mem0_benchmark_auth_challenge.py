from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import eval as eval_module
from infinity_context_server import mem0_benchmark_auth_challenge as auth_module
from infinity_context_server.mem0_benchmark_auth_challenge import (
    MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION,
    is_safe_auth_challenge_target,
    verify_auth_challenge_response,
)
from infinity_context_server.memory_comparison_preflight import (
    MemoryComparisonPreflightConfig,
    run_memory_comparison_preflight,
)
from infinity_context_server.memory_comparison_service_probe import (
    MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV,
)

_NONCE = "ab" * 32
_TOKEN = "managed-probe-secret"


def test_auth_challenge_verification_accepts_valid_response() -> None:
    result = verify_auth_challenge_response(
        _auth_payload(_NONCE, _TOKEN),
        nonce=_NONCE,
        token=_TOKEN,
    )

    assert result.passed is True
    assert result.reason_code is None


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    [
        ("nonce_sha256", "0" * 64, "nonce_sha256_mismatch"),
        ("signature", "0" * 64, "signature_mismatch"),
        ("signature", "not-hex", "invalid_signature"),
    ],
)
def test_auth_challenge_verification_rejects_tampering(
    field: str,
    value: str,
    reason_code: str,
) -> None:
    payload = _auth_payload(_NONCE, _TOKEN)
    payload[field] = value

    result = verify_auth_challenge_response(
        payload,
        nonce=_NONCE,
        token=_TOKEN,
    )

    assert result.passed is False
    assert result.reason_code == reason_code


@pytest.mark.parametrize(
    ("url", "safe"),
    [
        ("http://127.0.0.1:8888", True),
        ("http://[::1]:8888", True),
        ("http://runtime.localhost:8888", True),
        ("https://managed.example", True),
        ("http://managed.example", False),
        ("ftp://127.0.0.1", False),
        ("https://token@managed.example", False),
        ("https://managed.example#fragment", False),
    ],
)
def test_auth_challenge_target_safety(url: str, safe: bool) -> None:
    assert is_safe_auth_challenge_target(url) is safe


def test_managed_probe_missing_token_fails_before_any_service_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str, str]] = []
    _install_fake_httpx(monkeypatch, events=events)

    result = run_memory_comparison_preflight(
        _config(tmp_path, env={"MEM0_API_KEY": "oss-secret"})
    )

    assert result["ok"] is False
    assert result["failed_checks"] == ["mem0_benchmark_auth_challenge"]
    assert _check(result, "mem0_benchmark_auth_challenge")["reason_code"] == (
        "mem0_benchmark_probe_token_missing"
    )
    assert events == []


@pytest.mark.parametrize(
    ("env", "require_runtime_contract"),
    [
        ({}, True),
        ({MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV: "1"}, False),
        ({"MEM0_BENCHMARK_PROBE_TOKEN": _TOKEN}, False),
    ],
)
def test_managed_runtime_contract_requires_service_probe(
    monkeypatch,
    tmp_path: Path,
    env: dict[str, str],
    require_runtime_contract: bool,
) -> None:
    events: list[tuple[str, str, str]] = []
    _install_fake_httpx(monkeypatch, events=events)

    result = run_memory_comparison_preflight(
        _config(
            tmp_path,
            env=env,
            probe_services=False,
            require_mem0_runtime_contract=require_runtime_contract,
        )
    )

    check = _check(result, "mem0_runtime_contract_probe_required")
    assert result["ok"] is False
    assert result["safe_to_run_live"] is False
    assert result["failed_checks"] == ["mem0_runtime_contract_probe_required"]
    assert check["reason_code"] == "mem0_runtime_contract_probe_required"
    assert events == []


def test_managed_probe_verifies_challenge_then_existing_contracts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str, str]] = []
    monkeypatch.setattr(auth_module, "generate_auth_challenge_nonce", lambda: _NONCE)
    _install_fake_httpx(
        monkeypatch,
        events=events,
        post_response=_FakeResponse(200, _auth_payload(_NONCE, _TOKEN)),
        get_responses={
            ("https://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("https://mem0.example", "/openapi.json"): _FakeResponse(
                200, {"paths": {"/memories": {}, "/search": {}}}
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            tmp_path,
            env={
                "MEM0_API_KEY": "oss-secret",
                "MEM0_BENCHMARK_PROBE_TOKEN": _TOKEN,
            },
        )
    )

    assert result["ok"] is True
    assert _check(result, "mem0_benchmark_auth_challenge")["passed"] is True
    assert events == [
        ("POST", "https://mem0.example", "/benchmark/auth-challenge"),
        ("GET", "https://memo.example", "/v1/health"),
        ("GET", "https://mem0.example", "/openapi.json"),
    ]


def test_managed_probe_rejects_missing_endpoint_and_redacts_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_signature = "cd" * 32
    events: list[tuple[str, str, str]] = []
    monkeypatch.setattr(auth_module, "generate_auth_challenge_nonce", lambda: _NONCE)
    _install_fake_httpx(
        monkeypatch,
        events=events,
        post_response=_FakeResponse(404, {"signature": raw_signature}),
        get_responses={
            ("https://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("https://mem0.example", "/openapi.json"): _FakeResponse(
                200, {"paths": {"/memories": {}, "/search": {}}}
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            tmp_path,
            env={
                "MEM0_API_KEY": "oss-secret",
                "MEM0_BENCHMARK_PROBE_TOKEN": _TOKEN,
            },
        )
    )

    serialized = json.dumps(result, sort_keys=True)
    check = _check(result, "mem0_benchmark_auth_challenge")
    assert result["ok"] is False
    assert check["reason_code"] == "mem0_benchmark_auth_challenge_unhealthy_status"
    assert _TOKEN not in serialized
    assert _NONCE not in serialized
    assert raw_signature not in serialized
    assert events == [
        ("POST", "https://mem0.example", "/benchmark/auth-challenge")
    ]


def test_tampered_challenge_stops_all_subsequent_service_probes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str, str]] = []
    payload = _auth_payload(_NONCE, _TOKEN)
    payload["signature"] = "0" * 64
    monkeypatch.setattr(auth_module, "generate_auth_challenge_nonce", lambda: _NONCE)
    _install_fake_httpx(
        monkeypatch,
        events=events,
        post_response=_FakeResponse(200, payload),
        get_responses={
            ("https://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("https://mem0.example", "/openapi.json"): _FakeResponse(
                200, {"paths": {"/memories": {}, "/search": {}}}
            ),
        },
    )

    result = run_memory_comparison_preflight(
        _config(
            tmp_path,
            env={"MEM0_BENCHMARK_PROBE_TOKEN": _TOKEN},
        )
    )

    assert result["ok"] is False
    assert _check(result, "mem0_benchmark_auth_challenge")["reason_code"] == (
        "signature_mismatch"
    )
    assert events == [
        ("POST", "https://mem0.example", "/benchmark/auth-challenge")
    ]


def test_managed_probe_rejects_unsafe_target_without_service_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str, str]] = []
    _install_fake_httpx(monkeypatch, events=events)

    result = run_memory_comparison_preflight(
        _config(
            tmp_path,
            mem0_url="http://managed.example",
            env={"MEM0_BENCHMARK_PROBE_TOKEN": _TOKEN},
        )
    )

    assert result["ok"] is False
    assert _check(result, "mem0_benchmark_auth_challenge")["reason_code"] == (
        "mem0_benchmark_auth_challenge_unsafe_target"
    )
    assert events == []


@pytest.mark.parametrize("token_value", [None, "", "   "])
def test_preflight_only_cli_rejects_missing_or_blank_probe_token(
    monkeypatch,
    capsys,
    tmp_path: Path,
    token_value: str | None,
) -> None:
    dataset = tmp_path / "locomo.json"
    _write_locomo_fast_dataset(dataset)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "memo-secret")
    monkeypatch.setenv("MEM0_API_KEY", "oss-secret")
    monkeypatch.setenv(MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV, "1")
    monkeypatch.delenv("MEM0_BENCHMARK_PROBE_TOKEN", raising=False)
    if token_value is not None:
        monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", token_value)
    events: list[tuple[str, str, str]] = []
    _install_fake_httpx(monkeypatch, events=events)

    with pytest.raises(SystemExit) as excinfo:
        eval_module.main(_managed_preflight_cli_args(dataset))

    output = capsys.readouterr().out
    payload = json.loads(output)
    check = _check(payload, "mem0_benchmark_auth_challenge")
    assert excinfo.value.code == 1
    assert payload["ok"] is False
    assert payload["safe_to_run_live"] is False
    assert check["reason_code"] == "mem0_benchmark_probe_token_missing"
    assert events == []


def test_preflight_only_cli_wires_managed_auth_challenge(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    _write_locomo_fast_dataset(dataset)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "memo-secret")
    monkeypatch.setenv("MEM0_API_KEY", "oss-secret")
    monkeypatch.setenv(MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV, "1")
    monkeypatch.setenv("MEM0_BENCHMARK_PROBE_TOKEN", _TOKEN)
    monkeypatch.setattr(auth_module, "generate_auth_challenge_nonce", lambda: _NONCE)
    _install_fake_httpx(
        monkeypatch,
        post_response=_FakeResponse(200, _auth_payload(_NONCE, _TOKEN)),
        get_responses={
            ("https://memo.example", "/v1/health"): _FakeResponse(200, {"ok": True}),
            ("https://mem0.example", "/openapi.json"): _FakeResponse(
                200, {"paths": {"/memories": {}, "/search": {}}}
            ),
        },
    )

    eval_module.main(
        [
            "memory-comparison-benchmark",
            "--dataset",
            str(dataset),
            "--memo-api-url",
            "https://memo.example",
            "--mem0-url",
            "https://mem0.example",
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
            "--preflight-probe-services",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["ready_for_locomo_fast"] is True
    assert payload["diagnostics"]["require_mem0_runtime_contract"] is True
    assert payload["diagnostics"]["secrets"][
        "mem0_benchmark_probe_token_configured"
    ] is True
    assert _TOKEN not in output
    assert _NONCE not in output


def _managed_preflight_cli_args(dataset: Path) -> list[str]:
    return [
        "memory-comparison-benchmark",
        "--dataset",
        str(dataset),
        "--memo-api-url",
        "https://memo.example",
        "--mem0-url",
        "https://mem0.example",
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
        "--preflight-probe-services",
    ]


def _config(
    tmp_path: Path,
    *,
    mem0_url: str = "https://mem0.example",
    env: dict[str, str],
    probe_services: bool = True,
    require_mem0_runtime_contract: bool = True,
) -> MemoryComparisonPreflightConfig:
    dataset = tmp_path / "dataset.json"
    dataset.write_text('[{"sample_id":"unit"}]', encoding="utf-8")
    return MemoryComparisonPreflightConfig(
        dataset_path=dataset,
        memo_api_url="https://memo.example",
        mem0_url=mem0_url,
        case_set="all",
        locomo_ingest_mode="official-turns",
        report_mode="compact",
        top_k=200,
        top_k_cutoffs=(10, 20, 50, 200),
        allow_live=True,
        allow_paid_llm=False,
        answerer_provider="deterministic",
        judge_provider="deterministic",
        answerer_model=None,
        judge_model=None,
        openai_api_key_env="MEMORY_OPENAI_API_KEY",
        mem0_api_key_env="MEM0_API_KEY",
        auth_token_configured=True,
        probe_services=probe_services,
        require_mem0_runtime_contract=require_mem0_runtime_contract,
        env=env,
    )


def _auth_payload(nonce: str, token: str) -> dict[str, str]:
    message = f"{MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION}\n{nonce}"
    return {
        "schema_version": MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION,
        "nonce_sha256": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
        "signature": hmac.new(
            token.encode("utf-8"), message.encode("ascii"), hashlib.sha256
        ).hexdigest(),
    }


def _check(result: dict[str, object], name: str) -> dict[str, object]:
    for check in result["checks"]:
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
    events: list[tuple[str, str, str]] | None = None,
    post_response: _FakeResponse | None = None,
    get_responses: dict[tuple[str, str], _FakeResponse] | None = None,
) -> None:
    class FakeClient:
        def __init__(self, *, base_url: str, **_: object) -> None:
            self._base_url = base_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, path: str, **kwargs: object) -> _FakeResponse:
            if events is not None:
                events.append(("POST", self._base_url, path))
            assert kwargs == {
                "headers": {"X-Benchmark-Probe-Token": _TOKEN},
                "json": {"nonce": _NONCE},
            }
            assert post_response is not None
            return post_response

        def get(self, path: str) -> _FakeResponse:
            if events is not None:
                events.append(("GET", self._base_url, path))
            assert get_responses is not None
            return get_responses[(self._base_url, path)]

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=FakeClient))


def _write_locomo_fast_dataset(path: Path) -> None:
    qas = [
        {
            "question": f"question-{category}-{index}",
            "answer": f"answer-{category}-{index}",
            "evidence": ["D1:1"],
            "category": category,
        }
        for category in (1, 2, 3, 4)
        for index in range(10)
    ]
    path.write_text(
        json.dumps(
            [
                {
                    "sample_id": "unit",
                    "conversation": {
                        "speaker_a": "A",
                        "session_1_date_time": "2023-01-01",
                        "session_1": [
                            {"dia_id": "D1:1", "speaker": "A", "text": "turn"}
                        ],
                    },
                    "qa": qas,
                }
            ]
        ),
        encoding="utf-8",
    )
