from __future__ import annotations

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_adapters.postgres import (
    managed_cleanup_v3_expected_row_authority as authority_module,
)
from infinity_context_adapters.postgres import (
    managed_cleanup_v3_expected_row_files as files_module,
)
from infinity_context_adapters.postgres import (
    managed_cleanup_v3_expected_row_sidecar as sidecar_module,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error
from test_managed_cleanup_v3_expected_row_authority import (
    authority_material as authority_material,
)


def test_open_or_repair_claims_recovers_missing_hard_death_sidecar(
    tmp_path, authority_material
) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "hard-death.sqlite3"
    key = b"u" * 32
    created = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    created.close()
    claim_path = path.with_name(f"{path.name}.claims")
    claim_path.unlink()
    with pytest.raises(ManagedCleanupV3Error, match="file_open"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    repaired = SQLiteManagedCleanupV3ExpectedRowAuthority.open_or_repair_claims(
        path,
        context=context,
        authority=authority,
        authentication_key=key,
    )
    assert repaired.lookup_sequence(0) is not None
    assert repaired._claim_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (0,)
    repaired.close()


def test_repair_authenticates_main_before_creating_sidecar(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "tampered-main.sqlite3"
    key = b"v" * 32
    created = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    created.close()
    claim_path = path.with_name(f"{path.name}.claims")
    claim_path.unlink()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE operations SET content_sha=? WHERE sequence=0", ("9" * 64,))
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open_or_repair_claims(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    assert not claim_path.exists()


def test_repair_never_replaces_existing_symlink_or_divergent_sidecar(
    tmp_path, authority_material
) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "divergent.sqlite3"
    key = b"w" * 32
    created = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    created.close()
    claim_path = path.with_name(f"{path.name}.claims")
    with sqlite3.connect(claim_path) as db:
        db.execute("UPDATE claims_metadata SET authentication_tag=?", ("0" * 64,))
    with pytest.raises(ManagedCleanupV3Error, match="sidecar_authentication_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open_or_repair_claims(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    claim_path.unlink()
    target = tmp_path / "symlink-target"
    target.write_bytes(b"do not replace")
    claim_path.symlink_to(target)
    with pytest.raises(ManagedCleanupV3Error, match="file_(open|unsafe)"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open_or_repair_claims(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    assert claim_path.is_symlink()
    assert target.read_bytes() == b"do not replace"


def test_repair_race_is_exactly_idempotent(tmp_path, authority_material, monkeypatch) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "repair-race.sqlite3"
    key = b"x" * 32
    created = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    created.close()
    path.with_name(f"{path.name}.claims").unlink()
    barrier = threading.Barrier(2)
    original = authority_module.repair_missing_claim_sidecar

    def raced_repair(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(authority_module, "repair_missing_claim_sidecar", raced_repair)

    def repair_once() -> bool:
        repaired = SQLiteManagedCleanupV3ExpectedRowAuthority.open_or_repair_claims(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
        try:
            return repaired.lookup_sequence(0) is not None
        finally:
            repaired.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _item: repair_once(), range(2))) == [True, True]


def test_sidecar_create_failure_does_not_unlink_replacement(
    tmp_path, authority_material, monkeypatch
) -> None:
    context, authority, _pages = authority_material
    path = tmp_path / "replaced.claims"
    moved = tmp_path / "original.claims"

    def replace_then_fail(_db) -> None:
        os.replace(path, moved)
        path.write_bytes(b"replacement-must-survive")
        os.chmod(path, 0o600)
        raise RuntimeError("injected sidecar failure")

    monkeypatch.setattr(sidecar_module, "configure_index", replace_then_fail)
    with pytest.raises(RuntimeError, match="injected sidecar failure"):
        sidecar_module.create_claim_sidecar(
            path,
            context_sha256=context.context_sha256,
            authority_terminal_sha256=authority.terminal_commitment_sha256,
            authentication_key=b"s" * 32,
        )
    assert path.read_bytes() == b"replacement-must-survive"
    assert moved.exists()


def test_claim_operations_reject_sidecar_path_replacement(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "sidecar-path-binding.sqlite3"
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"t" * 32,
    )
    claim_path = path.with_name(f"{path.name}.claims")
    moved = tmp_path / "sidecar-original.claims"
    os.replace(claim_path, moved)
    claim_path.write_bytes(b"replacement")
    os.chmod(claim_path, 0o600)
    terminal = authority.terminal_commitment_sha256
    with pytest.raises(ManagedCleanupV3Error, match="file_replaced"):
        index.begin_verification(terminal, "6" * 64)
    key_buffer = index._claims._key
    with pytest.raises(ManagedCleanupV3Error, match="file_replaced"):
        index.close()
    assert not any(key_buffer)


def test_sidecar_connect_failure_removes_exact_bootstrap_and_retry_succeeds(
    tmp_path, authority_material, monkeypatch
) -> None:
    context, authority, _pages = authority_material
    path = tmp_path / "connect-failure.claims"
    original_connect = files_module._connect_descriptor

    def fail_connect(_descriptor, *, readonly):
        assert not readonly
        raise RuntimeError("injected connect failure")

    monkeypatch.setattr(files_module, "_connect_descriptor", fail_connect)
    with pytest.raises(RuntimeError, match="injected connect failure"):
        sidecar_module.create_claim_sidecar(
            path,
            context_sha256=context.context_sha256,
            authority_terminal_sha256=authority.terminal_commitment_sha256,
            authentication_key=b"c" * 32,
        )
    assert not path.exists()
    monkeypatch.setattr(files_module, "_connect_descriptor", original_connect)
    db, descriptor = sidecar_module.create_claim_sidecar(
        path,
        context_sha256=context.context_sha256,
        authority_terminal_sha256=authority.terminal_commitment_sha256,
        authentication_key=b"c" * 32,
    )
    files_module.close_secure_sqlite(db, descriptor)


def test_connect_failure_never_unlinks_replacement(
    tmp_path, authority_material, monkeypatch
) -> None:
    context, authority, _pages = authority_material
    path = tmp_path / "connect-replaced.claims"
    moved = tmp_path / "connect-original.claims"

    def replace_then_fail(_descriptor, *, readonly):
        assert not readonly
        os.replace(path, moved)
        path.write_bytes(b"replacement-must-survive")
        os.chmod(path, 0o600)
        raise RuntimeError("injected connect replacement")

    monkeypatch.setattr(files_module, "_connect_descriptor", replace_then_fail)
    with pytest.raises(RuntimeError, match="injected connect replacement"):
        sidecar_module.create_claim_sidecar(
            path,
            context_sha256=context.context_sha256,
            authority_terminal_sha256=authority.terminal_commitment_sha256,
            authentication_key=b"d" * 32,
        )
    assert path.read_bytes() == b"replacement-must-survive"
    assert moved.exists()
