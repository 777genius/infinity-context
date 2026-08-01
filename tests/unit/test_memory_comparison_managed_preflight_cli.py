from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import infinity_context_server.memory_comparison_managed_preflight_cli as cli_module
import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedDatasetMetadata,
)
from infinity_context_server.memory_comparison_managed_preflight_cli import (
    MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION,
    MANAGED_PREFLIGHT_CLI_SUITE,
    ManagedPreflightCliConfig,
    ManagedPreflightCliError,
    run_managed_preflight_cli,
)

_INFINITY_URL = "https://private-infinity.example.test/internal"
_MEM0_URL = "https://private-mem0.example.test"
_SECRETS = {
    "MEMORY_OPENAI_API_KEY": "sk-proj-openai-secret-value-1234567890",
    "MEMORY_EVAL_AUTH_TOKEN": "infinity-secret-value",
    "MEM0_API_KEY": "mem0-secret-value-1234567890",
}


def _config(
    tmp_path: Path,
    *,
    report_out: Path | None = None,
) -> ManagedPreflightCliConfig:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b"official-fixture-placeholder")
    return ManagedPreflightCliConfig(
        dataset_path=dataset,
        profile_id=PROFILE_LOCOMO_TOP_50,
        infinity_api_url=_INFINITY_URL,
        mem0_api_url=_MEM0_URL,
        report_out=report_out,
    )


def _metadata() -> ManagedDatasetMetadata:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return ManagedDatasetMetadata(
        profile_id=profile.profile_id,
        benchmark=profile.benchmark,
        dataset_sha256=profile.expected_dataset_hash,
        case_count=profile.expected_case_count,
        distribution=dict(profile.expected_distribution),
        corpus_count=profile.expected_corpus_count,
    )


def _stub_official_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "managed_dataset_metadata_from_bytes",
        lambda **_: _metadata(),
    )


def test_static_cli_success_is_private_atomic_and_never_publishable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_official_metadata(monkeypatch)
    report_out = tmp_path / "managed-preflight.json"
    config = _config(tmp_path, report_out=report_out)

    report = run_managed_preflight_cli(config, env=_SECRETS)

    assert report["suite"] == MANAGED_PREFLIGHT_CLI_SUITE
    assert report["schema_version"] == MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION
    assert report["ok"] is True
    assert report["static_checks_passed"] is True
    assert report["credentials_verified"] is False
    assert report["status"] == "static_checks_passed"
    for key in (
        "diagnostic_only",
        "provider_calls_performed",
        "live_state_touched",
        "execution_authority_created",
        "live_success",
        "eligible",
        "publishable",
    ):
        assert report[key] is (key == "diagnostic_only")
    serialized = json.dumps(report, sort_keys=True)
    assert _INFINITY_URL not in serialized
    assert _MEM0_URL not in serialized
    assert str(tmp_path) not in serialized
    assert all(secret not in serialized for secret in _SECRETS.values())
    assert {item["endpoint_scheme"] for item in report["backends"]} == {"https"}
    assert "credential_binding_id" not in serialized
    assert "binding_id" not in serialized
    assert all(len(item["endpoint_sha256"]) == 64 for item in report["backends"])

    assert json.loads(report_out.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(report_out.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".managed-preflight.json.*.tmp"))


def test_missing_any_required_credential_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_official_metadata(monkeypatch)
    config = _config(tmp_path)

    for missing in _SECRETS:
        env = dict(_SECRETS)
        env.pop(missing)
        report = run_managed_preflight_cli(config, env=env)
        assert report["ok"] is False
        assert report["reason_code"] == "credential_missing"
        assert report["static_checks_passed"] is False
        assert report["publishable"] is False
        assert report["provider_calls_performed"] is False


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("MEMORY_OPENAI_API_KEY", "sk-too-short"),
        ("MEMORY_EVAL_AUTH_TOKEN", "x"),
        ("MEM0_API_KEY", "x"),
    ),
)
def test_weak_credential_shapes_are_presence_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _stub_official_metadata(monkeypatch)
    report = run_managed_preflight_cli(_config(tmp_path), env={**_SECRETS, name: value})
    assert report["reason_code"] == "credential_missing"
    assert report["static_checks_passed"] is False


def test_auth_and_openai_fallback_envs_are_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_official_metadata(monkeypatch)
    config = _config(tmp_path)
    env = {
        "OPENAI_API_KEY": _SECRETS["MEMORY_OPENAI_API_KEY"],
        "MEMORY_SERVICE_TOKEN": _SECRETS["MEMORY_EVAL_AUTH_TOKEN"],
        "MEM0_API_KEY": _SECRETS["MEM0_API_KEY"],
    }

    report = run_managed_preflight_cli(config, env=env)

    assert report["ok"] is True
    assert report["static_checks_passed"] is True


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
        b"not-json",
    ),
)
def test_real_strict_dataset_loader_rejects_non_official_bytes(
    tmp_path: Path,
    payload: bytes,
) -> None:
    config = _config(tmp_path)
    config.dataset_path.write_bytes(payload)

    report = run_managed_preflight_cli(config, env=_SECRETS)

    assert report["ok"] is False
    assert report["publishable"] is False
    assert report["provider_calls_performed"] is False
    assert report["reason_code"] in {
        "dataset_metadata_invalid",
        "dataset_unreadable",
    }


def test_report_path_cannot_overwrite_dataset(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    original = config.dataset_path.read_bytes()
    config = ManagedPreflightCliConfig(
        dataset_path=config.dataset_path,
        profile_id=config.profile_id,
        infinity_api_url=config.infinity_api_url,
        mem0_api_url=config.mem0_api_url,
        report_out=config.dataset_path,
    )

    report = run_managed_preflight_cli(config, env=_SECRETS)

    assert report["ok"] is False
    assert report["reason_code"] == "artifact_path_invalid"
    assert config.dataset_path.read_bytes() == original


def test_dataset_size_is_bounded_before_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    config.dataset_path.write_bytes(b"12345")
    monkeypatch.setattr(cli_module, "MANAGED_PREFLIGHT_MAX_DATASET_BYTES", 4)

    report = run_managed_preflight_cli(config, env=_SECRETS)

    assert report["ok"] is False
    assert report["reason_code"] == "dataset_too_large"


def test_invalid_environment_variable_name_is_rejected_without_value(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b"fixture")
    secret = "sk-proj-never-echo-this-secret"

    with pytest.raises(ManagedPreflightCliError) as caught:
        ManagedPreflightCliConfig(
            dataset_path=dataset,
            profile_id=PROFILE_LOCOMO_TOP_50,
            infinity_api_url=_INFINITY_URL,
            mem0_api_url=_MEM0_URL,
            openai_api_key_env=secret,
        )

    assert caught.value.code == "config_invalid"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_artifact_write_failure_is_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_official_metadata(monkeypatch)
    config = _config(tmp_path, report_out=tmp_path / "report.json")
    monkeypatch.setattr(
        cli_module,
        "write_json_atomic",
        lambda *_: (_ for _ in ()).throw(OSError("sensitive-path")),
    )

    with pytest.raises(ManagedPreflightCliError) as caught:
        run_managed_preflight_cli(config, env=_SECRETS)

    assert caught.value.code == "artifact_write_failed"
    assert "sensitive-path" not in str(caught.value)


def test_import_has_no_live_transport_or_managed_runner_dependency() -> None:
    code = """
import sys
import infinity_context_server.memory_comparison_managed_preflight_cli
forbidden = {
    "infinity_context_server.memory_comparison_http",
    "infinity_context_server.memory_comparison_managed_run",
    "infinity_context_server.memory_comparison_openai_official_transport",
    "infinity_context_server.memory_comparison_full_run_components",
    "infinity_context_server.memory_comparison_locomo_transport",
    "infinity_context_server.memory_comparison_probe_transport",
    "httpx",
}
assert forbidden.isdisjoint(sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )


def test_main_maps_arguments_and_prints_static_only_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b"fixture")
    seen: list[ManagedPreflightCliConfig] = []

    def fake_run(config: ManagedPreflightCliConfig) -> dict[str, object]:
        seen.append(config)
        return {
            "ok": True,
            "diagnostic_only": True,
            "static_checks_passed": True,
            "provider_calls_performed": False,
            "live_state_touched": False,
            "execution_authority_created": False,
            "eligible": False,
            "publishable": False,
            "live_success": False,
        }

    monkeypatch.setattr(cli_module, "run_managed_preflight_cli", fake_run)

    exit_code = cli_module.main(
        [
            "--dataset",
            str(dataset),
            "--profile",
            PROFILE_LOCOMO_TOP_50,
            "--infinity-api-url",
            _INFINITY_URL,
            "--mem0-api-url",
            _MEM0_URL,
        ]
    )

    assert exit_code == 0
    assert len(seen) == 1
    assert seen[0].dataset_path == dataset
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["publishable"] is False
    assert report["provider_calls_performed"] is False


@pytest.mark.parametrize("forbidden_flag", ("--allow-live", "--probe-services"))
def test_main_rejects_any_live_or_probe_flag(
    tmp_path: Path,
    forbidden_flag: str,
) -> None:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b"fixture")

    with pytest.raises(SystemExit) as caught:
        cli_module.main(
            [
                "--dataset",
                str(dataset),
                "--profile",
                PROFILE_LOCOMO_TOP_50,
                "--infinity-api-url",
                _INFINITY_URL,
                "--mem0-api-url",
                _MEM0_URL,
                forbidden_flag,
            ]
        )

    assert caught.value.code == 2


def test_main_converts_composition_errors_to_safe_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b"fixture")
    monkeypatch.setattr(
        cli_module,
        "run_managed_preflight_cli",
        lambda _: (_ for _ in ()).throw(ManagedPreflightCliError("artifact_write_failed")),
    )

    exit_code = cli_module.main(
        [
            "--dataset",
            str(dataset),
            "--profile",
            PROFILE_LOCOMO_TOP_50,
            "--infinity-api-url",
            _INFINITY_URL,
            "--mem0-api-url",
            _MEM0_URL,
        ]
    )

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["reason_code"] == "artifact_write_failed"
    assert report["publishable"] is False
    assert str(tmp_path) not in json.dumps(report)


def test_project_registers_dedicated_static_preflight_entrypoint() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert (
        "infinity-context-managed-preflight = "
        '"infinity_context_server.memory_comparison_managed_preflight_cli:main"' in text
    )


def test_openai_key_shape_is_checked_without_echoing_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_official_metadata(monkeypatch)
    config = _config(tmp_path)
    env = dict(_SECRETS)
    raw = "not-an-official-openai-key"
    env["MEMORY_OPENAI_API_KEY"] = raw

    report = run_managed_preflight_cli(config, env=env)

    assert report["ok"] is False
    assert report["reason_code"] == "credential_missing"
    assert raw not in json.dumps(report)
