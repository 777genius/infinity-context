"""Rollback and SQLite-open identity hardening for the fresh-chain ledger."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from infinity_context_server.publishable_fresh_chain_canary.ledger import (
    FreshChainCanaryLedger,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_head_anchor import (
    ANCHOR_SUFFIX,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainLedgerError,
)
from test_publishable_fresh_chain_canary_ledger import KEY, _digest, _intent, _ledger


def _reopen(ledger: FreshChainCanaryLedger) -> FreshChainCanaryLedger:
    return FreshChainCanaryLedger.open(
        ledger.path,
        authentication_secret=KEY,
        plan=ledger.plan,
        require_existing=True,
    )


def test_external_head_anchor_rejects_prior_authentic_file_rollback(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    backup = tmp_path / "authentic-prior.sqlite3"
    shutil.copyfile(ledger.path, backup)
    _intent(ledger, "mem0_extraction", 0, _digest("4"))

    os.replace(backup, ledger.path)
    os.chmod(ledger.path, 0o600)

    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_anchor_invalid"):
        _reopen(ledger)


def test_external_head_anchor_rejects_same_inode_authentic_content_restore(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    prior = ledger.path.read_bytes()
    identity = ledger.path.stat().st_ino
    _intent(ledger, "mem0_extraction", 0, _digest("4"))

    ledger.path.write_bytes(prior)
    ledger.path.chmod(0o600)
    assert ledger.path.stat().st_ino == identity

    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_rollback_detected"):
        _reopen(ledger)


def test_deleted_anchor_cannot_reauthorize_authentic_prior_ledger(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    prior = ledger.path.read_bytes()
    _intent(ledger, "mem0_extraction", 0, _digest("4"))

    ledger.path.write_bytes(prior)
    ledger.path.chmod(0o600)
    ledger.path.with_name(ledger.path.name + ANCHOR_SUFFIX).unlink()

    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_anchor_missing"):
        _reopen(ledger)


def test_sqlite_connect_uses_pinned_open_file_during_timed_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _ledger(tmp_path)
    expected = ledger.read_snapshot()
    decoy = tmp_path / "decoy.sqlite3"
    shutil.copyfile(ledger.path, decoy)
    decoy.chmod(0o600)
    parked = tmp_path / "parked.sqlite3"
    real_connect = sqlite3.connect
    swaps = 0

    def swapping_connect(*args: object, **kwargs: object):
        nonlocal swaps
        os.replace(ledger.path, parked)
        os.replace(decoy, ledger.path)
        try:
            connection = real_connect(*args, **kwargs)
        finally:
            os.replace(ledger.path, decoy)
            os.replace(parked, ledger.path)
        swaps += 1
        return connection

    monkeypatch.setattr(sqlite3, "connect", swapping_connect)

    assert ledger.read_snapshot() == expected
    assert swaps == 1
