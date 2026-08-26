from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import stat
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import managed_strict_v4_sqlite_files as sqlite_files
from infinity_context_adapters.postgres.managed_cleanup_v4_sqlite_journal import (
    JOURNAL_KEY_PURPOSE,
    ManagedCleanupV4JournalError,
    SQLiteManagedCleanupV4Journal,
)
from infinity_context_core.application.use_cases.managed_cleanup_v4_lifecycle import (
    build_cleanup_v4_terminal_bindings,
    complete_managed_cleanup_v4,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    StrictV4CleanupAuthorityResolver,
    build_strict_v4_cleanup_authority_readback,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_cleanup import (
    complete_strict_v4_cleanup,
    initiate_strict_v4_cleanup,
    recover_strict_v4_cleanup,
)

RUN, CONTEXT, A2 = "1" * 64, "2" * 64, "3" * 64
KEY_ID, KEY = "cleanup-test-key", b"strict-v4-cleanup-journal-test-key" * 2


class _Keys:
    def __init__(self, key: bytes = KEY) -> None:
        self.key = key
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        self.calls.append((purpose, key_id))
        if purpose != JOURNAL_KEY_PURPOSE or key_id != KEY_ID:
            raise LookupError
        return self.key


def _readback():
    return build_strict_v4_cleanup_authority_readback(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
        preparation_receipt_sha256="a" * 64,
        preparation_receipt_mac_sha256="b" * 64,
        registration_sha256="c" * 64,
        registration_mac_sha256="d" * 64,
        writer_authority_sha256="e" * 64,
        writer_authority_mac_sha256="f" * 64,
        authenticator=ProjectionReceiptAuthenticator(KEY),
        authentication_key_id=KEY_ID,
    )


def _bindings():
    return build_cleanup_v4_terminal_bindings(
        inventory_terminal_sha256="4" * 64,
        qdrant_absence_pass_sha256=("5" * 64, "6" * 64),
        graphiti_absence_pass_sha256=("7" * 64, "8" * 64),
        cognee_evidence_sha256="9" * 64,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
    )


async def _complete(*, journal, terminal_bindings, key_identity_authority):
    authenticator = ProjectionReceiptAuthenticator(
        key_identity_authority.resolve(purpose=JOURNAL_KEY_PURPOSE, key_id=KEY_ID)
    )
    authority = await StrictV4CleanupAuthorityResolver(
        run_id_sha256=RUN,
        reader=journal,
        authenticator=authenticator,
        authentication_key_id=KEY_ID,
    ).resolve()
    return await complete_managed_cleanup_v4(
        authority=authority,
        terminal_bindings=terminal_bindings,
        lifecycle=journal,
        authenticator=authenticator,
        authentication_key_id=KEY_ID,
    )


def _create(path: Path, keys: _Keys | None = None):
    keys = keys or _Keys()
    return SQLiteManagedCleanupV4Journal.create(
        path,
        readback=_readback(),
        authentication_key_id=KEY_ID,
        key_identity_authority=keys,
    )


def test_shared_connect_failure_unlinks_and_direct_journal_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "journal-connect-retry.sqlite"
    original = sqlite_files._connect
    failed = False

    def fail_once(fd: int, *, readonly: bool):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected journal connect failure")
        return original(fd, readonly=readonly)

    monkeypatch.setattr(sqlite_files, "_connect", fail_once)
    with pytest.raises(RuntimeError, match="injected journal connect failure"):
        _create(path)
    assert not path.exists()
    journal = _create(path)
    journal.close()


def test_exact_lifecycle_reopen_recovery_and_file_security(tmp_path: Path) -> None:
    path = tmp_path / "private" / "cleanup.sqlite3"
    os.mkdir(tmp_path / "private", 0o700)
    keys = _Keys()
    journal = _create(path, keys)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_nlink == 1
    authority = json.loads(  # noqa: SLF001 - white-box persistence contract proof
        journal._db.execute(  # noqa: SLF001
            "SELECT payload_json FROM cleanup_authority WHERE singleton=1"
        ).fetchone()[0]
    )
    assert authority["authority_kind"] == "strict_v4_a2"
    assert len(authority["authority_sha256"]) == 64
    assert authority["readback"]["preparation_receipt_sha256"] == "a" * 64
    assert authority["readback"]["registration_sha256"] == "c" * 64
    assert authority["readback"]["writer_authority_sha256"] == "e" * 64

    first = asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=keys))
    replay = asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=keys))
    assert first.replayed is False
    assert replay.replayed is True
    terminal = asyncio.run(
        _complete(
            journal=journal,
            terminal_bindings=_bindings(),
            key_identity_authority=keys,
        )
    )
    assert terminal.replayed is False
    journal.close()

    reopened = SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=keys)
    recovery = asyncio.run(recover_strict_v4_cleanup(journal=reopened, key_identity_authority=keys))
    assert recovery.initiation == first.receipt
    assert recovery.terminal == terminal.receipt
    assert asyncio.run(
        _complete(
            journal=reopened,
            terminal_bindings=_bindings(),
            key_identity_authority=keys,
        )
    ).replayed
    reopened.close()
    assert all(call == (JOURNAL_KEY_PURPOSE, KEY_ID) for call in keys.calls)


def test_begin_immediate_rolls_back_interrupted_append(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.sqlite3"
    journal = _create(path)

    def deny_head_update(action, table, _column, _database, _trigger):
        if action == sqlite3.SQLITE_UPDATE and table == "journal_head":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    journal._db.set_authorizer(deny_head_update)  # noqa: SLF001 - crash injection
    with pytest.raises(sqlite3.DatabaseError, match="authorized"):
        asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=_Keys()))
    journal._db.set_authorizer(None)  # noqa: SLF001
    assert asyncio.run(journal.read_initiation(RUN)) is None
    assert (
        asyncio.run(
            initiate_strict_v4_cleanup(journal=journal, key_identity_authority=_Keys())
        ).replayed
        is False
    )
    journal.close()


def test_two_connections_are_exact_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.sqlite3"
    original = _create(path)
    original.close()
    left = SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=_Keys())
    right = SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=_Keys())

    async def race():
        return await asyncio.gather(
            initiate_strict_v4_cleanup(journal=left, key_identity_authority=_Keys()),
            initiate_strict_v4_cleanup(journal=right, key_identity_authority=_Keys()),
        )

    values = asyncio.run(race())
    assert sorted(item.replayed for item in values) == [False, True]
    left.close()
    right.close()


def test_library_completion_rejects_self_signed_terminal_bindings(tmp_path: Path) -> None:
    journal = _create(tmp_path / "cleanup.sqlite3")
    asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=_Keys()))
    with pytest.raises(ManagedCleanupV4JournalError, match="completion_evidence_invalid"):
        asyncio.run(
            complete_strict_v4_cleanup(
                journal=journal,
                terminal_evidence=_bindings(),  # type: ignore[arg-type]
                key_identity_authority=_Keys(),
            )
        )
    assert asyncio.run(journal.read_terminal(RUN)) is None
    journal.close()


@pytest.mark.parametrize(
    ("statement", "error"),
    [
        (
            "UPDATE cleanup_authority SET payload_json=replace(payload_json,'2222','aaaa')",
            "authentication_invalid",
        ),
        ("UPDATE journal_metadata SET schema_fingerprint_sha256='bad'", "metadata_invalid"),
        ("DELETE FROM lifecycle_events WHERE event_kind='terminal'", "head_invalid"),
        ("CREATE TABLE rogue(value TEXT) STRICT", "schema_invalid"),
    ],
)
def test_authenticated_tamper_and_event_truncation_fail_closed(
    tmp_path: Path, statement: str, error: str
) -> None:
    path = tmp_path / "cleanup.sqlite3"
    journal = _create(path)
    asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=_Keys()))
    asyncio.run(
        _complete(
            journal=journal,
            terminal_bindings=_bindings(),
            key_identity_authority=_Keys(),
        )
    )
    journal.close()
    with sqlite3.connect(path) as db:
        db.execute(statement)
    with pytest.raises(ManagedCleanupV4JournalError, match=error):
        SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=_Keys())


def test_truncated_file_symlink_hardlink_and_wrong_key_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.sqlite3"
    journal = _create(path)
    journal.close()

    wrong = _Keys(b"wrong-cleanup-journal-key-material" * 2)
    with pytest.raises(ManagedCleanupV4JournalError, match="authentication_invalid"):
        SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=wrong)

    symlink = tmp_path / "symlink.sqlite3"
    symlink.symlink_to(path)
    with pytest.raises(Exception, match="unsafe|failed"):
        SQLiteManagedCleanupV4Journal.open(symlink, key_identity_authority=_Keys())

    hardlink = tmp_path / "hardlink.sqlite3"
    os.link(path, hardlink)
    with pytest.raises(Exception, match="unsafe"):
        SQLiteManagedCleanupV4Journal.open(path, key_identity_authority=_Keys())
    hardlink.unlink()

    truncated = tmp_path / "truncated.sqlite3"
    shutil.copy2(path, truncated)
    truncated.chmod(0o600)
    with truncated.open("r+b") as stream:
        stream.truncate(512)
    with pytest.raises((sqlite3.DatabaseError, ManagedCleanupV4JournalError)):
        SQLiteManagedCleanupV4Journal.open(truncated, key_identity_authority=_Keys())


def test_open_descriptor_rejects_same_path_replacement(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.sqlite3"
    journal = _create(path)
    moved = tmp_path / "moved.sqlite3"
    path.rename(moved)
    path.write_bytes(b"replacement")
    path.chmod(0o600)
    with pytest.raises(ManagedCleanupV4JournalError, match="file_invalid"):
        asyncio.run(journal.read_initiation(RUN))
    with pytest.raises(ManagedCleanupV4JournalError, match="file_invalid"):
        journal.close()


def test_write_rejects_replacement_before_commit_and_rolls_back(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cleanup.sqlite3"
    displaced = tmp_path / "displaced.sqlite3"
    journal = _create(path)
    replaced = False

    def replace_during_head_update(action, table, _column, _database, _trigger):
        nonlocal replaced
        if action == sqlite3.SQLITE_UPDATE and table == "journal_head" and not replaced:
            replaced = True
            path.rename(displaced)
            path.write_bytes(b"replacement")
            path.chmod(0o600)
        return sqlite3.SQLITE_OK

    journal._db.set_authorizer(replace_during_head_update)  # noqa: SLF001
    with pytest.raises(ManagedCleanupV4JournalError, match="file_invalid"):
        asyncio.run(initiate_strict_v4_cleanup(journal=journal, key_identity_authority=_Keys()))
    journal._db.set_authorizer(None)  # noqa: SLF001
    with pytest.raises(ManagedCleanupV4JournalError, match="file_invalid"):
        journal.close()

    original = SQLiteManagedCleanupV4Journal.open(displaced, key_identity_authority=_Keys())
    assert asyncio.run(original.read_initiation(RUN)) is None
    original.close()
    assert path.read_bytes() == b"replacement"


def test_create_is_exclusive_and_authority_authentication_is_required(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.sqlite3"
    journal = _create(path)
    with pytest.raises(Exception, match="create_failed"):
        _create(path)
    journal.close()
    with pytest.raises(Exception, match="authentication"):
        SQLiteManagedCleanupV4Journal.create(
            tmp_path / "foreign.sqlite3",
            readback=_readback(),
            authentication_key_id=KEY_ID,
            key_identity_authority=_Keys(b"foreign-key-material-is-long-enough" * 2),
        )


def test_create_failure_never_unlinks_path_replacement(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cleanup.sqlite3"
    displaced = tmp_path / "displaced.sqlite3"

    def replace_then_fail(self, _readback) -> None:
        path.rename(displaced)
        path.write_bytes(b"do-not-delete-replacement")
        path.chmod(0o600)
        raise RuntimeError("injected create failure")

    monkeypatch.setattr(SQLiteManagedCleanupV4Journal, "_initialize", replace_then_fail)
    with pytest.raises(RuntimeError, match="injected create failure"):
        _create(path)
    assert path.read_bytes() == b"do-not-delete-replacement"
    assert displaced.exists()
