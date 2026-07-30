from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from infinity_context_server import ranked_evidence_semantic_gate_cli as cli


def _required_args(tmp_path: Path) -> list[str]:
    return [
        "--dataset",
        str(tmp_path / "dataset.json"),
        "--benchmark",
        "locomo",
        "--case-id",
        "locomo:conv-1:qa:1",
    ]


def _payload(*, ok: bool = True) -> dict[str, object]:
    return {
        "schema_version": "ranked-evidence-semantic-gate.v1",
        "status": "passed" if ok else "failed",
        "ok": ok,
        "metrics": {"case_count": 1},
    }


def test_defaults_are_forwarded_and_stdout_is_compact_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_gate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return _payload()

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", fake_gate)

    assert cli.main(_required_args(tmp_path)) == 0

    assert captured == {
        "dataset_path": tmp_path / "dataset.json",
        "benchmark": "locomo",
        "case_ids": ("locomo:conv-1:qa:1",),
        "cutoffs": (10, 20, 50, 200),
        "reference_cutoff": 200,
        "token_budget": 25_600,
        "max_facts": 200,
        "max_chunks": 200,
        "locomo_ingest_mode": "official-turns",
        "local_database_url": None,
        "report_out": None,
    }
    rendered = capsys.readouterr().out
    assert (
        rendered
        == json.dumps(
            _payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def test_explicit_repeatable_values_and_paths_are_forwarded_in_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    report_out = tmp_path / "report.json"

    def fake_gate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return _payload()

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", fake_gate)
    args = _required_args(tmp_path) + [
        "--case-id",
        "locomo:conv-2:qa:3",
        "--cutoff",
        "5",
        "--cutoff",
        "25",
        "--reference-cutoff",
        "25",
        "--token-budget",
        "4096",
        "--max-facts",
        "150",
        "--max-chunks",
        "175",
        "--locomo-ingest-mode",
        "rich-documents",
        "--local-database-url",
        "sqlite+aiosqlite:////tmp/local-gate.db",
        "--report-out",
        str(report_out),
    ]

    assert cli.main(args) == 0
    capsys.readouterr()

    assert captured["case_ids"] == (
        "locomo:conv-1:qa:1",
        "locomo:conv-2:qa:3",
    )
    assert captured["cutoffs"] == (5, 25)
    assert captured["reference_cutoff"] == 25
    assert captured["token_budget"] == 4096
    assert captured["max_facts"] == 150
    assert captured["max_chunks"] == 175
    assert captured["locomo_ingest_mode"] == "rich-documents"
    assert captured["local_database_url"] == "sqlite+aiosqlite:////tmp/local-gate.db"
    assert captured["report_out"] == report_out


@pytest.mark.parametrize(("ok", "expected_exit"), [(True, 0), (False, 1)])
def test_exit_status_follows_exact_gate_ok(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    ok: bool,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_ranked_evidence_semantic_gate",
        lambda **_kwargs: _payload(ok=ok),
    )

    assert cli.main(_required_args(tmp_path)) == expected_exit
    assert json.loads(capsys.readouterr().out)["ok"] is ok


def test_truthy_non_boolean_ok_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_ranked_evidence_semantic_gate",
        lambda **_kwargs: {"ok": "true", "status": "malformed"},
    )

    assert cli.main(_required_args(tmp_path)) == 1
    assert json.loads(capsys.readouterr().out)["ok"] == "true"


def test_gate_validation_is_not_reimplemented_by_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_gate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return _payload(ok=False)

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", fake_gate)
    args = _required_args(tmp_path) + [
        "--cutoff",
        "20",
        "--cutoff",
        "10",
        "--reference-cutoff",
        "999",
        "--token-budget",
        "1",
    ]

    assert cli.main(args) == 1
    capsys.readouterr()
    assert captured["cutoffs"] == (20, 10)
    assert captured["reference_cutoff"] == 999
    assert captured["token_budget"] == 1


def test_report_payload_matches_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    expected = _payload()
    report_out = tmp_path / "report.json"

    def fake_gate(**kwargs: object) -> dict[str, object]:
        path = kwargs["report_out"]
        assert isinstance(path, Path)
        path.write_text(json.dumps(expected), encoding="utf-8")
        return expected

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", fake_gate)
    args = _required_args(tmp_path) + ["--report-out", str(report_out)]

    assert cli.main(args) == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    report_payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert stdout_payload == report_payload == expected


def test_exception_is_sanitized_without_secret_or_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    database_url = "sqlite+aiosqlite:////tmp/super-secret.db?token=secret-value"

    def raising_gate(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError(f"connection failed for {database_url}")

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", raising_gate)
    args = _required_args(tmp_path) + ["--local-database-url", database_url]

    assert cli.main(args) == 1
    rendered = capsys.readouterr().out
    assert database_url not in rendered
    assert "connection failed" not in rendered
    assert json.loads(rendered) == {
        "ok": False,
        "schema_version": "ranked-evidence-semantic-gate.v1",
        "status": "internal_failure",
    }


def test_database_url_in_gate_payload_fails_closed_without_leak(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    database_url = "sqlite+aiosqlite:////tmp/private.db"
    monkeypatch.setattr(
        cli,
        "run_ranked_evidence_semantic_gate",
        lambda **_kwargs: {"ok": True, "database_url": database_url},
    )

    args = _required_args(tmp_path) + ["--local-database-url", database_url]
    assert cli.main(args) == 1
    rendered = capsys.readouterr().out
    assert database_url not in rendered
    assert json.loads(rendered)["status"] == "internal_failure"


def test_keyboard_interrupt_is_sanitized_and_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def interrupted_gate(**_kwargs: object) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_ranked_evidence_semantic_gate", interrupted_gate)

    assert cli.main(_required_args(tmp_path)) == 130
    assert json.loads(capsys.readouterr().out)["status"] == "interrupted"


def test_argparse_errors_exit_two_with_safe_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--dataset", str(tmp_path / "dataset.json")])

    assert exc_info.value.code == 2
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "schema_version": "ranked-evidence-semantic-gate.v1",
        "status": "invalid_arguments",
    }


def test_argparse_error_does_not_echo_database_url(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    database_url = "sqlite+aiosqlite:////tmp/private.db?token=secret-value"
    args = _required_args(tmp_path) + [
        "--local-database-url",
        database_url,
        "--unsupported",
        database_url,
    ]

    with pytest.raises(SystemExit) as exc_info:
        cli.main(args)

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert database_url not in captured.out
    assert database_url not in captured.err
    assert json.loads(captured.out)["status"] == "invalid_arguments"


def test_help_exposes_no_remote_or_provider_surface() -> None:
    help_text = cli._parser().format_help().lower()

    assert "--api-url" not in help_text
    assert "--auth" not in help_text
    assert "mem0" not in help_text
    assert "openai" not in help_text
    assert "provider-free" in help_text


def test_module_help_subprocess_is_stable_and_provider_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "infinity_context_server.ranked_evidence_semantic_gate_cli",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "--case-id" in result.stdout
    assert "--api-url" not in result.stdout
    assert "mem0" not in result.stdout.lower()
