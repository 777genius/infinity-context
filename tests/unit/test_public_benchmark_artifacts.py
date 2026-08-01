from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from infinity_context_server.public_benchmark_artifacts import write_json_atomic


def test_atomic_json_is_private_and_preserves_existing_file_on_failure(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    write_json_atomic(report, {"status": "previous"})

    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    with pytest.raises(TypeError):
        write_json_atomic(report, {"bad": object()})

    assert json.loads(report.read_text(encoding="utf-8")) == {"status": "previous"}
    assert not list(tmp_path.glob(".report.json.*.tmp"))


def test_atomic_json_rejects_non_finite_numbers(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    write_json_atomic(report, {"status": "previous"})

    with pytest.raises(ValueError):
        write_json_atomic(report, {"bad": float("nan")})

    assert json.loads(report.read_text(encoding="utf-8")) == {"status": "previous"}
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".report.json.*.tmp"))
