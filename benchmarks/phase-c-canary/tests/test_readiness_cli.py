from __future__ import annotations

import json
import sys
from pathlib import Path

from phase_c_canary.cli import main
from phase_c_canary.readiness import CanaryPhase, default_readiness_policy


def test_historical_usage_is_only_a_conservative_ceiling() -> None:
    policy = default_readiness_policy()
    assert policy.phase is CanaryPhase.READINESS_CALIBRATION
    assert policy.historical_conservative_token_ceiling == 8063
    assert not hasattr(policy, "expected_tokens")
    assert not hasattr(policy, "token_baseline")


def test_fake_cli_is_provider_free_preflight(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    assert main(["--mode", "fake", "--journal", str(tmp_path / "offline.sqlite3")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "authority_schema": 1,
        "live_enabled": False,
        "mode": "fake",
        "provider_usage_schema": 3,
    }
