from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_adapters.postgres import (
    managed_cleanup_v3_expected_row_bootstrap as bootstrap_module,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_files import (
    close_secure_sqlite,
    create_secure_sqlite,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error
from test_managed_cleanup_v3_expected_row_authority import (
    authority_material as authority_material,
)


def _empty_bootstrap(path) -> None:
    db, descriptor = create_secure_sqlite(path)
    close_secure_sqlite(db, descriptor)


def _recover(path, material, key=b"b" * 32):
    context, authority, pages = material
    return SQLiteManagedCleanupV3ExpectedRowAuthority.create_or_open_repairable_bootstrap(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )


def test_create_or_open_repairs_kill_before_schema(tmp_path, authority_material) -> None:
    path = tmp_path / "killed-bootstrap.sqlite3"
    _empty_bootstrap(path)
    recovered = _recover(path, authority_material)
    try:
        assert recovered.lookup_sequence(0) is not None
        assert path.with_name(f"{path.name}.claims").exists()
    finally:
        recovered.close()


def test_create_or_open_concurrent_repair_is_serialized(tmp_path, authority_material) -> None:
    path = tmp_path / "concurrent-bootstrap.sqlite3"
    _empty_bootstrap(path)

    def recover_once() -> bool:
        recovered = _recover(path, authority_material, b"c" * 32)
        try:
            return recovered.lookup_sequence(0) is not None
        finally:
            recovered.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _item: recover_once(), range(2))) == [True, True]


def test_create_or_open_rejects_symlink_bootstrap(tmp_path, authority_material) -> None:
    target = tmp_path / "symlink-target"
    target.write_bytes(b"do not touch")
    path = tmp_path / "symlink-bootstrap.sqlite3"
    path.symlink_to(target)
    with pytest.raises(ManagedCleanupV3Error, match="file_(open|unsafe)"):
        _recover(path, authority_material, b"d" * 32)
    assert path.is_symlink()
    assert target.read_bytes() == b"do not touch"


def test_create_or_open_rejects_hardlinked_bootstrap(tmp_path, authority_material) -> None:
    path = tmp_path / "hardlink-bootstrap.sqlite3"
    _empty_bootstrap(path)
    alias = tmp_path / "hardlink-alias.sqlite3"
    os.link(path, alias)
    with pytest.raises(ManagedCleanupV3Error, match="file_unsafe"):
        _recover(path, authority_material, b"e" * 32)
    assert path.exists() and alias.exists()


def test_create_or_open_rejects_path_replacement(tmp_path, authority_material, monkeypatch) -> None:
    path = tmp_path / "replaced-bootstrap.sqlite3"
    _empty_bootstrap(path)
    replacement = tmp_path / "replacement.sqlite3"
    replacement.write_bytes(b"replacement")
    os.chmod(replacement, 0o600)
    original = bootstrap_module.unlink_secure_file

    def replace_before_unlink(candidate, descriptor):
        os.replace(replacement, candidate)
        original(candidate, descriptor)

    monkeypatch.setattr(bootstrap_module, "unlink_secure_file", replace_before_unlink)
    with pytest.raises(ManagedCleanupV3Error, match="file_(replaced|unsafe)"):
        _recover(path, authority_material, b"f" * 32)
    assert path.read_bytes() == b"replacement"
    assert not path.with_name(f"{path.name}.claims").exists()


def test_create_or_open_never_repairs_nonempty_main(tmp_path, authority_material) -> None:
    path = tmp_path / "nonempty-bootstrap.sqlite3"
    _empty_bootstrap(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE attacker_data(value TEXT)")
        db.execute("INSERT INTO attacker_data VALUES('preserve')")
    os.chmod(path, 0o600)
    with pytest.raises((ManagedCleanupV3Error, sqlite3.DatabaseError)):
        _recover(path, authority_material, b"g" * 32)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM attacker_data").fetchone() == ("preserve",)
