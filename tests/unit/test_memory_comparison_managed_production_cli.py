from __future__ import annotations

import inspect
import json
import os
import stat
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_production_cli as subject
from infinity_context_server.memory_comparison_full_profiles import PROFILE_LOCOMO_TOP_50

_PRIVATE_GOLD = "PRIVATE-GOLD-MUST-NOT-LEAK"
_PRIVATE_ENV_SECRET = "PRIVATE-ENV-MUST-NOT-LEAK"
_CASE_ID = "raw-sample-a:qa:1"


def _dataset_bytes() -> bytes:
    return json.dumps(
        [
            {
                "sample_id": "raw-sample-a",
                "conversation": {
                    "speaker_a": "Alice",
                    "speaker_b": "Bob",
                    "session_1_date_time": "1:56 pm on 8 May, 2023",
                    "session_1": [
                        {
                            "dia_id": "D1:1",
                            "speaker": "Alice",
                            "text": "sanitized corpus memory",
                        }
                    ],
                },
                "qa": [
                    {
                        "question": "private question",
                        "answer": _PRIVATE_GOLD,
                        "evidence": ["D1:1"],
                        "category": 4,
                    }
                ],
            }
        ],
        separators=(",", ":"),
    ).encode()


def _config(
    tmp_path: Path,
    *,
    report_out: Path | None = None,
    selected_case_ids: tuple[str, ...] = (_CASE_ID,),
    max_total_tokens: int = 100_000,
) -> subject.ManagedProductionCliConfig:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(_dataset_bytes())
    return subject.ManagedProductionCliConfig(
        dataset_path=dataset,
        profile_id=PROFILE_LOCOMO_TOP_50,
        selected_case_ids=selected_case_ids,
        max_total_tokens=max_total_tokens,
        report_out=report_out,
    )


def _accept_official_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subject,
        "managed_dataset_metadata_from_bytes",
        lambda **_: object(),
    )


class _EnvironmentAccessForbidden(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment access forbidden: {key}")

    def get(self, key: str, default: object = None) -> object:
        del default
        raise AssertionError(f"environment access forbidden: {key}")

    def __iter__(self):
        raise AssertionError("environment iteration forbidden")


def test_no_go_is_decided_before_environment_credentials_readiness_or_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_official_metadata(monkeypatch)
    monkeypatch.setattr(os, "environ", _EnvironmentAccessForbidden())
    report = subject.run_managed_production_cli(_config(tmp_path))

    assert report["status"] == "no-go-pre-readiness"
    assert report["provider_kind"] == "subscription-runtime"
    assert report["scope"] == "canary"
    assert report["selected_case_count"] == 1
    assert report["credentials_read"] is False
    assert report["readiness_provider_calls_already_performed"] == 0
    assert report["provider_calls_performed"] == 0
    assert report["backend_calls_performed"] == 0
    assert report["live_state_touched"] is False
    assert report["publishable"] is False
    assert report["blockers"] == [
        "managed_http_policy_mem0_exact_source_identity_unavailable",
        "managed_http_policy_evidence_capabilities_unavailable",
    ]
    assert report["planned_limits"] == {
        "benchmark_max_provider_calls": 4,
        "readiness_max_provider_calls": 1,
        "total_max_provider_calls": 5,
        "benchmark_reserved_token_ceiling": 100_000,
        "max_output_tokens_per_call": 4096,
        "readiness_max_output_tokens": 8,
        "readiness_max_total_tokens": 512,
    }


def test_json_and_private_atomic_report_never_expose_gold_case_ids_or_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_official_metadata(monkeypatch)
    report_out = tmp_path / "managed-production.json"
    config = _config(tmp_path, report_out=report_out)

    report = subject.run_managed_production_cli(config)

    rendered = json.dumps(report, sort_keys=True)
    assert json.loads(report_out.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(report_out.stat().st_mode) == 0o600
    assert _PRIVATE_GOLD not in rendered
    assert _CASE_ID not in rendered
    assert str(tmp_path) not in rendered
    assert str(config.dataset_path) not in rendered


def test_process_openai_values_are_never_read_or_rendered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_official_metadata(monkeypatch)
    monkeypatch.setenv("MEMORY_OPENAI_API_KEY", _PRIVATE_ENV_SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", _PRIVATE_ENV_SECRET)

    report = subject.run_managed_production_cli(_config(tmp_path))

    assert _PRIVATE_ENV_SECRET not in json.dumps(report, sort_keys=True)
    source = inspect.getsource(subject)
    assert "memory_comparison_managed_runtime_credentials" not in source
    assert "memory_comparison_managed_live_admission" not in source
    assert "memory_comparison_managed_live_composition" not in source
    assert "memory_comparison_managed_http" not in source
    assert "OPENAI_API_KEY" not in source
    assert "os.environ" not in source


def test_official_dataset_validation_precedes_case_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "managed_dataset_metadata_from_bytes",
        lambda **_: (_ for _ in ()).throw(
            subject.ManagedPreflightError("dataset_mismatch")
        ),
    )
    monkeypatch.setattr(
        subject,
        "managed_policy_cases_from_dataset",
        lambda **_: pytest.fail("case projection must not follow invalid official metadata"),
    )

    report = subject.run_managed_production_cli(_config(tmp_path))

    assert report["status"] == "sealed-failure"
    assert report["reason_code"] == "dataset_invalid"
    assert report["credentials_read"] is False


@pytest.mark.parametrize(
    ("case_ids", "max_total_tokens"),
    (
        ((), 1),
        ((_CASE_ID, _CASE_ID), 1),
        (tuple(f"case-{index}" for index in range(9)), 1),
        ((_CASE_ID,), 0),
        ((_CASE_ID,), subject.MANAGED_PRODUCTION_CLI_MAX_TOTAL_TOKENS + 1),
    ),
)
def test_config_rejects_unbounded_or_ambiguous_canary_inputs(
    tmp_path: Path,
    case_ids: tuple[str, ...],
    max_total_tokens: int,
) -> None:
    with pytest.raises(subject.ManagedProductionCliError) as caught:
        _config(
            tmp_path,
            selected_case_ids=case_ids,
            max_total_tokens=max_total_tokens,
        )
    assert caught.value.code == "config_invalid"


def test_unknown_or_out_of_order_case_selection_is_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_official_metadata(monkeypatch)
    unknown = "private-unknown-case"
    report = subject.run_managed_production_cli(
        _config(tmp_path, selected_case_ids=(unknown,))
    )

    rendered = json.dumps(report, sort_keys=True)
    assert report["reason_code"] == "selection_invalid"
    assert unknown not in rendered
    assert _PRIVATE_GOLD not in rendered


def test_dataset_size_and_report_collision_fail_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(subject, "MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES", 4)
    oversized = subject.run_managed_production_cli(config)
    assert oversized["reason_code"] == "dataset_too_large"

    monkeypatch.setattr(subject, "MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES", 402_653_184)
    collision = subject.run_managed_production_cli(
        subject.ManagedProductionCliConfig(
            dataset_path=config.dataset_path,
            profile_id=config.profile_id,
            selected_case_ids=config.selected_case_ids,
            max_total_tokens=config.max_total_tokens,
            report_out=config.dataset_path,
        )
    )
    assert collision["reason_code"] == "artifact_path_invalid"
    assert config.dataset_path.read_bytes() == _dataset_bytes()


def test_main_prints_one_safe_json_line_and_returns_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _accept_official_metadata(monkeypatch)
    config = _config(tmp_path)

    exit_code = subject.main(
        [
            "--dataset",
            str(config.dataset_path),
            "--profile",
            config.profile_id,
            "--case-id",
            _CASE_ID,
            "--max-total-tokens",
            "100000",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == subject.MANAGED_PRODUCTION_EXIT_NO_GO
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    report = json.loads(captured.out)
    assert report["status"] == "no-go-pre-readiness"
    assert _PRIVATE_GOLD not in captured.out
    assert _CASE_ID not in captured.out


@pytest.mark.parametrize(
    "forbidden",
    (
        ("--scope", "full"),
        ("--provider", "openai-api-key"),
        ("--openai-api-key-env", "MEMORY_OPENAI_API_KEY"),
    ),
)
def test_parser_has_no_full_provider_or_openai_escape_hatch(
    tmp_path: Path,
    forbidden: tuple[str, str],
) -> None:
    config = _config(tmp_path)
    with pytest.raises(SystemExit) as caught:
        subject.main(
            [
                "--dataset",
                str(config.dataset_path),
                "--profile",
                config.profile_id,
                "--case-id",
                _CASE_ID,
                "--max-total-tokens",
                "100000",
                *forbidden,
            ]
        )
    assert caught.value.code == 2


def test_project_registers_sealed_production_entrypoint() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert (
        "infinity-context-managed-production = "
        '"infinity_context_server.memory_comparison_managed_production_cli:main"'
        in text
    )
