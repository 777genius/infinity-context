from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import multiprocessing
import os
import sqlite3

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_claims import (
    CLAIM_PAGE_SIZE,
    DurableExpectedRowClaims,
    create_claim_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    create_index_schema,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    ManagedCleanupV3Error,
)
from infinity_context_core.ports.managed_cleanup_v3_paged_authority import (
    build_managed_cleanup_v3_authority,
)
from test_managed_cleanup_v3_paged_authority import (
    _a1_authority,
    _context,
    _operation,
    _Stage,
)


class _CapturingStage(_Stage):
    def __init__(self, context_sha256: str, expected: int) -> None:
        super().__init__(context_sha256, expected, lose_commit_response=False)
        self.pages = []

    def append(self, page) -> None:
        self.pages.append(page)
        super().append(page)


class _CapturingStore:
    stage = None

    def begin(self, *, context_sha256: str, expected_operation_count: int):
        self.stage = _CapturingStage(context_sha256, expected_operation_count)
        return self.stage


def _claim_page_then_die(path: str) -> None:
    state_db = sqlite3.connect(path)
    create_claim_schema(state_db)
    claims = DurableExpectedRowClaims(sqlite3.connect(":memory:"), state_db, b"k" * 32, "f" * 64)
    claims.begin("e" * 64)
    for sequence in range(CLAIM_PAGE_SIZE + 88):
        claims.claim("e" * 64, "facts", sequence, {"id": f"fact-{sequence}"})
    os._exit(0)


@pytest.fixture(scope="module")
def authority_material():
    context = _context(LOCOMO_PROFILE)
    count = int(PROFILE_ORACLES[LOCOMO_PROFILE]["operation_count"])
    store = _CapturingStore()
    authority, _receipt = build_managed_cleanup_v3_authority(
        context=context,
        operations=(_operation(LOCOMO_PROFILE, sequence) for sequence in range(count)),
        a1_authority=_a1_authority(context, count),
        store=store,
    )
    return context, authority, tuple(store.stage.pages)


def test_index_seals_reopens_and_detects_tamper(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "expected.sqlite3"
    key = b"k" * 32
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=iter(pages),
        authentication_key=key,
    )
    first = _operation(LOCOMO_PROFILE, 0)
    assert index.lookup_sequence(0) == index.lookup_source(first.source_identity_sha256)
    assert index.has_corpus(first.corpus_identity_sha256)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert fcntl.fcntl(index._db_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        index._db.execute("UPDATE operations SET content_sha=? WHERE sequence=0", ("1" * 64,))
    index.close()

    reopened = SQLiteManagedCleanupV3ExpectedRowAuthority.open(
        path,
        context=context,
        authority=authority,
        authentication_key=key,
    )
    assert reopened.lookup_sequence(5881) is not None
    reopened.close()

    with sqlite3.connect(path) as db:
        db.execute("UPDATE operations SET content_sha=? WHERE sequence=0", ("0" * 64,))
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )


def test_index_rejects_wrong_key_and_incomplete_pages(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "expected.sqlite3"
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"a" * 32,
    )
    index.close()
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            path,
            context=context,
            authority=authority,
            authentication_key=b"b" * 32,
        )
    with pytest.raises(ManagedCleanupV3Error, match="coverage_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.create(
            tmp_path / "short.sqlite3",
            context=context,
            authority=authority,
            pages=pages[:-1],
            authentication_key=b"a" * 32,
        )


def test_fragment_descriptor_may_repeat_across_operations() -> None:
    db = sqlite3.connect(":memory:")
    create_index_schema(db)
    db.execute("INSERT INTO corpora VALUES(?,?,?)", ("c" * 64, 0, "z" * 64))
    for sequence in (0, 1):
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                "document",
                "c" * 64,
                "t" * 64,
                "u" * 64,
                f"{sequence:064x}",
                "a" * 64,
                f"{sequence + 2:064x}",
                f"{sequence + 4:064x}",
                "s" * 64,
                "r" * 64,
                0,
                "g" * 64,
                "h" * 64,
                1,
                "z" * 64,
            ),
        )
        db.execute("INSERT INTO fragments VALUES(?,?,?,?)", (sequence, 0, "f" * 64, "z" * 64))
    assert db.execute("SELECT count(*) FROM fragments").fetchone() == (2,)


def test_claim_bijection_rejects_duplicate_replacing_missing(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        tmp_path / "claims.sqlite3",
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"c" * 32,
    )
    session = "1" * 64
    index.begin_verification(authority.terminal_commitment_sha256, session)
    index._claims.claim(session, "facts", 0, {"id": "physical-a"})
    index._claims.claim(session, "facts", 0, {"id": "physical-a"})
    with pytest.raises(ManagedCleanupV3Error, match="claim_conflict"):
        index._claims.claim(session, "facts", 0, {"id": "physical-b"})
    with pytest.raises(ManagedCleanupV3Error, match="coverage_incomplete"):
        index.finalize_verification(authority.terminal_commitment_sha256, session)
    index.close()


def test_new_session_cannot_union_partial_prior_claims(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        tmp_path / "sessions.sqlite3",
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"f" * 32,
    )
    first_session, second_session = "2" * 64, "3" * 64
    terminal = authority.terminal_commitment_sha256
    index.begin_verification(terminal, first_session)
    index._claims.claim(first_session, "facts", 0, {"id": "physical-a"})
    index.begin_verification(terminal, second_session)
    index._claims.claim(second_session, "facts", 1, {"id": "physical-b"})
    index.flush_verification_page(terminal, second_session)
    with pytest.raises(ManagedCleanupV3Error, match="coverage_incomplete"):
        index.finalize_verification(terminal, second_session)
    count = index._claim_db.execute("SELECT count(*) FROM verification_claims").fetchone()
    assert count == (1,)
    index.abort_verification(terminal, second_session)
    index.close()


def test_claim_pages_checkpoint_at_512_for_longmem_scale() -> None:
    authority_db = sqlite3.connect(":memory:")
    state_db = sqlite3.connect(":memory:")
    create_claim_schema(state_db)
    claims = DurableExpectedRowClaims(authority_db, state_db, b"k" * 32, "f" * 64)
    session = "e" * 64
    synthetic_claims = 366_440
    claims.begin(session)

    for sequence in range(synthetic_claims):
        claims.claim(session, "facts", sequence, {"id": f"fact-{sequence}"})
    claims.flush_verification_page(session)

    assert claims.metrics.claim_checkpoints == 716
    assert claims.metrics.max_pending_claims == CLAIM_PAGE_SIZE
    assert state_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (
        synthetic_claims,
    )
    claims.close()
    authority_db.close()
    state_db.close()


def test_finalize_rejects_unflushed_claim_page(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        tmp_path / "unflushed.sqlite3",
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"u" * 32,
    )
    terminal, session = authority.terminal_commitment_sha256, "6" * 64
    index.begin_verification(terminal, session)
    index._claims.claim(session, "facts", 0, {"id": "physical-a"})

    with pytest.raises(ManagedCleanupV3Error, match="claims_page_unflushed"):
        index.finalize_verification(terminal, session)
    index.abort_verification(terminal, session)
    assert index._claim_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (0,)
    assert index._claim_db.execute("SELECT count(*) FROM verification_session").fetchone() == (0,)
    index.close()


def test_process_death_discards_only_unflushed_claim_page(tmp_path) -> None:
    path = tmp_path / "hard-death.sqlite3"
    process = multiprocessing.get_context("fork").Process(
        target=_claim_page_then_die, args=(str(path),)
    )
    process.start()
    process.join(timeout=30)

    assert process.exitcode == 0
    state_db = sqlite3.connect(path)
    assert state_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (
        CLAIM_PAGE_SIZE,
    )
    authority_db = sqlite3.connect(":memory:")
    claims = DurableExpectedRowClaims(authority_db, state_db, b"k" * 32, "f" * 64)
    claims.begin("e" * 64)
    claims.claim(
        "e" * 64,
        "facts",
        CLAIM_PAGE_SIZE,
        {"id": f"fact-{CLAIM_PAGE_SIZE}"},
    )
    claims.flush_verification_page("e" * 64)
    assert state_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (
        CLAIM_PAGE_SIZE + 1,
    )
    claims.close()
    authority_db.close()
    state_db.close()


def test_authorized_new_session_resets_finalized_scratch(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        tmp_path / "finalized-reset.sqlite3",
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"z" * 32,
    )
    first_session, second_session = "4" * 64, "5" * 64
    terminal = authority.terminal_commitment_sha256
    index.begin_verification(terminal, first_session)
    with index._claim_db:
        index._claim_db.execute(
            "UPDATE verification_session SET state='finalized', session_mac=? WHERE singleton=1",
            (
                index._claims._session_mac(
                    "finalized",
                    first_session,
                    index._claims._authenticated_claims_sha(first_session)[0],
                ),
            ),
        )
    with pytest.raises(ManagedCleanupV3Error, match="session_finalized"):
        index.begin_verification(terminal, second_session)
    index.begin_new_verification(terminal, second_session)
    assert index._claim_db.execute(
        "SELECT state,session_sha FROM verification_session"
    ).fetchone() == ("active", second_session)
    assert index._claim_db.execute("SELECT count(*) FROM verification_claims").fetchone() == (0,)
    index.close()


def test_secure_files_reject_links_and_closed_use(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "secure.sqlite3"
    key = b"d" * 32
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    symlink = tmp_path / "symlink.sqlite3"
    symlink.symlink_to(path)
    with pytest.raises(ManagedCleanupV3Error, match="file_(open|unsafe)"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            symlink,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    hardlink = tmp_path / "hardlink.sqlite3"
    os.link(path, hardlink)
    with pytest.raises(ManagedCleanupV3Error, match="file_unsafe"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            hardlink,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    hardlink.unlink()
    moved = tmp_path / "moved.sqlite3"
    os.replace(path, moved)
    sqlite3.connect(path).close()
    os.chmod(path, 0o600)
    assert os.fstat(index._db_fd).st_ino == moved.stat().st_ino
    assert os.fstat(index._db_fd).st_ino != path.stat().st_ino
    with pytest.raises(ManagedCleanupV3Error, match="file_replaced"):
        index.lookup_sequence(0)
    key_buffer = index._claims._key
    with pytest.raises(ManagedCleanupV3Error, match="file_replaced"):
        index.close()
    index.close()
    assert not any(key_buffer)
    with pytest.raises(ManagedCleanupV3Error, match="closed"):
        index.lookup_sequence(0)


def test_create_failure_does_not_unlink_replacement(
    tmp_path, authority_material, monkeypatch
) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "create-replaced.sqlite3"
    moved = tmp_path / "create-original.sqlite3"

    def replace_then_fail(*_args, **_kwargs) -> None:
        os.replace(path, moved)
        path.write_bytes(b"replacement-must-survive")
        os.chmod(path, 0o600)
        raise RuntimeError("injected create failure")

    monkeypatch.setattr(
        "infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority._ingest",
        replace_then_fail,
    )
    with pytest.raises(RuntimeError, match="injected create failure"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.create(
            path,
            context=context,
            authority=authority,
            pages=pages,
            authentication_key=b"r" * 32,
        )
    assert path.read_bytes() == b"replacement-must-survive"
    assert moved.exists()


def test_rejects_rehashed_legacy_v3_index_metadata(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "legacy.sqlite3"
    key = b"e" * 32
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    index.close()
    with sqlite3.connect(path) as db:
        payload_json = db.execute("SELECT payload_json FROM metadata WHERE singleton=1").fetchone()[
            0
        ]
        payload = json.loads(payload_json)
        payload["schema_version"] = "managed-cleanup-v3-expected-row-index.v1"
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        old_tag = hmac.new(
            key,
            b"managed-cleanup-v3-expected-row-index/v1\0" + encoded,
            hashlib.sha256,
        ).hexdigest()
        db.execute(
            "UPDATE metadata SET payload_json=?,authentication_tag=? WHERE singleton=1",
            (encoded.decode("ascii"), old_tag),
        )
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )


def test_open_closes_both_handles_when_claim_sidecar_is_invalid(
    tmp_path, authority_material
) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "claim-failure.sqlite3"
    key = b"y" * 32
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=key,
    )
    index.close()
    claim_path = path.with_name(f"{path.name}.claims")
    claim_path.write_bytes(b"not a sqlite database")
    os.chmod(claim_path, 0o600)
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(sqlite3.DatabaseError):
        SQLiteManagedCleanupV3ExpectedRowAuthority.open(
            path,
            context=context,
            authority=authority,
            authentication_key=key,
        )
    assert len(os.listdir("/proc/self/fd")) == before


def test_open_holds_snapshot_and_rejects_same_inode_mutation(tmp_path, authority_material) -> None:
    context, authority, pages = authority_material
    path = tmp_path / "immutable-snapshot.sqlite3"
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
        path,
        context=context,
        authority=authority,
        pages=pages,
        authentication_key=b"i" * 32,
    )
    inode = path.stat().st_ino
    writer = sqlite3.connect(path, timeout=0.01)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("UPDATE operations SET content_sha=? WHERE sequence=0", ("7" * 64,))
            writer.commit()
    finally:
        writer.close()
    with path.open("ab") as raw_writer:
        raw_writer.write(b"same-inode-tamper")
    assert path.stat().st_ino == inode
    with pytest.raises(ManagedCleanupV3Error, match="content_changed"):
        index.lookup_sequence(0)
    with pytest.raises(ManagedCleanupV3Error, match="content_changed"):
        index.close()
    index.close()
