from __future__ import annotations

import json
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_live_cli as subject


def _write_v5_config(tmp_path: Path, *, extraction_digest: str = "a" * 64) -> Path:
    digest = "a" * 64
    path_names = {
        "state_root",
        "secret_root",
        "report_root",
        "report_file",
        "dispatch_journal",
        "operation_journal",
        "durable_clean_state",
        "recovery_journal",
        "ingress_bearer_file",
        "evidence_key_file",
        "receipt_secret_file",
        "checkpoint_signing_key_file",
        "checkpoint_head_key_file",
        "operation_journal_signer_secret_file",
        "durable_clean_state_hmac_secret_file",
        "runtime_attestation_secret_file",
        "recovery_hmac_secret_file",
        "runtime_authority_file",
        "phase_c_package_root",
        "runtime_repo",
        "runtime_artifact_manifest",
        "node_executable",
        "adapter_runtime_pin_file",
        "recovery_report_file",
    }
    filesystem = {name: str(tmp_path / name) for name in path_names}
    filesystem.update(
        {
            "evidence_key_sha256": digest,
            "runtime_authority_sha256": digest,
            "runtime_artifact_manifest_sha256": digest,
            "node_executable_sha256": digest,
            "runtime_attestation_secret_sha256": digest,
            "adapter_runtime_pin_sha256": digest,
        }
    )
    config_path = tmp_path / "managed-v5.json"
    config_path.write_text(
        json.dumps(
            {
                "filesystem": filesystem,
                "runtime": {"mem0_adapter_origin": "http://127.0.0.1:19091"},
                "extraction_contract_file": str(
                    tmp_path / "mem0_oss_adapter_v5" / "extraction_contract.py"
                ),
                "extraction_contract_sha256": extraction_digest,
            }
        )
    )
    return config_path


def test_strict_v5_cli_config_loads_only_explicit_paths_and_pins(tmp_path: Path) -> None:
    digest = "a" * 64
    config_path = _write_v5_config(tmp_path)

    config, contract, contract_sha256 = subject._load_managed_v5_cli_config(config_path)

    assert config.filesystem.operation_journal == tmp_path / "operation_journal"
    assert config.filesystem.durable_clean_state == tmp_path / "durable_clean_state"
    assert config.filesystem.recovery_journal == tmp_path / "recovery_journal"
    assert config.runtime.mem0_adapter_origin == "http://127.0.0.1:19091"
    assert contract.name == "extraction_contract.py"
    assert contract_sha256 == digest


def test_v5_cli_config_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"filesystem":{},"filesystem":{},"runtime":{}}')

    with pytest.raises(subject.ManagedLiveCliError, match="config_invalid"):
        subject._load_managed_v5_cli_config(path)


@pytest.mark.parametrize("digest", ("a" * 63, "g" * 64, "A" * 64))
def test_v5_cli_config_rejects_non_lowercase_64_hex_extraction_digest(
    tmp_path: Path,
    digest: str,
) -> None:
    path = _write_v5_config(tmp_path, extraction_digest=digest)

    with pytest.raises(subject.ManagedLiveCliError, match="config_invalid"):
        subject._load_managed_v5_cli_config(path)


def test_executable_parser_requires_explicit_v5_config() -> None:
    action = next(
        item for item in subject._parser()._actions if item.dest == "managed_v5_config_json"
    )
    assert action.required is True
    assert action.metavar == "ABSOLUTE_PATH"


def test_main_defaults_report_out_to_validated_v5_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text('{"official":true}')
    config_path = _write_v5_config(tmp_path)
    report_file = tmp_path / "report_file"
    atomic_writes: list[Path] = []
    write_json_atomic = subject.write_json_atomic

    def record_atomic_write(path: Path, payload: object) -> None:
        atomic_writes.append(path)
        write_json_atomic(path, payload)

    monkeypatch.setattr(subject, "write_json_atomic", record_atomic_write)

    exit_code = subject.main(_main_argv(dataset, config_path))

    stdout_report = json.loads(capsys.readouterr().out)
    assert exit_code == subject.MANAGED_LIVE_CLI_NO_GO
    assert atomic_writes == [report_file]
    assert json.loads(report_file.read_text()) == stdout_report
    assert stdout_report["reason_code"] == "authorization_required"


def test_main_explicit_report_mismatch_has_stable_failure_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text('{"official":true}')
    config_path = _write_v5_config(tmp_path)
    wrong_report = tmp_path / "wrong-report.json"

    exit_code = subject.main(
        [
            *_main_argv(dataset, config_path),
            "--report-out",
            str(wrong_report),
        ]
    )

    stdout_report = json.loads(capsys.readouterr().out)
    assert exit_code == subject.MANAGED_LIVE_CLI_FAILURE
    assert stdout_report["reason_code"] == "config_invalid"
    assert stdout_report["publishable"] is False
    assert not wrong_report.exists()


def _main_argv(dataset: Path, config_path: Path) -> list[str]:
    return [
        "--dataset",
        str(dataset),
        "--profile",
        "mem0-locomo-top50-v1",
        "--case-id",
        "case-1",
        "--run-id",
        "managed-v5-default-report",
        "--infinity-api-url",
        "http://127.0.0.1:7788",
        "--mem0-api-url",
        "http://127.0.0.1:8888",
        "--subscription-runtime-url",
        "http://127.0.0.1:8890",
        "--max-extraction-tokens",
        "1000",
        "--max-total-tokens",
        "2000",
        "--mem0-runtime-implementation-sha256",
        "b" * 64,
        "--managed-v5-config-json",
        str(config_path),
    ]
