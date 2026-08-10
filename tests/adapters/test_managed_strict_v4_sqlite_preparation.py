from __future__ import annotations

import hashlib
import importlib.util
import multiprocessing
import os
import shutil
import sqlite3
import tracemalloc
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import managed_strict_v4_sqlite_files as sqlite_files
from infinity_context_adapters.postgres.managed_cleanup_v3_sqlite_preparation import (
    SQLiteManagedCleanupV3PreparationStore,
    iter_committed_pages,
)
from infinity_context_adapters.postgres.managed_mem0_v6_sqlite_preparation import (
    SQLiteManagedMem0V6PreparationStore,
)
from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error
from infinity_context_core.ports.managed_cleanup_v3_paged_authority import (
    build_managed_cleanup_v3_authority,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    ManagedMem0V6ManifestError,
    ManagedMem0V6ManifestPage,
    build_managed_mem0_v6_manifest_context,
    domain_sha256,
    merkle_root,
    page_body,
)
from infinity_context_core.ports.managed_mem0_v6_paged_manifest import (
    build_managed_mem0_v6_paged_manifest,
)

KEY = b"strict-v4-provider-free-test-key!"


def _sha(value: int) -> str:
    return hashlib.sha256(value.to_bytes(8, "big")).hexdigest()


def _cleanup_fixture_module():
    source = Path(__file__).parent.parent / "unit/test_managed_cleanup_v3_paged_authority.py"
    spec = importlib.util.spec_from_file_location("cleanup_v3_fixture", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bootstrap_worker(store_type, path: str, barrier, outcomes) -> None:
    barrier.wait()
    try:
        store = store_type.open_or_create(path, authentication_key=KEY)
        store.close()
        outcomes.put(None)
    except BaseException as exc:
        outcomes.put(repr(exc))


def test_a1_claims_are_exact_idempotent_unique_and_gap_free(tmp_path: Path) -> None:
    path = tmp_path / "a1.sqlite"
    store = SQLiteManagedMem0V6PreparationStore.create(path, authentication_key=KEY)
    context = _sha(100)
    stage = store.begin(manifest_context_sha256=context, expected_operation_count=5_882)
    stage.claim(sequence=0, operation_sha256=_sha(0))
    stage.claim(sequence=0, operation_sha256=_sha(0))
    with pytest.raises(ManagedMem0V6ManifestError, match="duplicate_operation"):
        stage.claim(sequence=1, operation_sha256=_sha(0))
    with pytest.raises(ManagedMem0V6ManifestError, match="claim_gap"):
        stage.claim(sequence=2, operation_sha256=_sha(2))
    store.close()

    reopened = SQLiteManagedMem0V6PreparationStore.open_or_create(path, authentication_key=KEY)
    resumed = reopened.begin(manifest_context_sha256=context, expected_operation_count=5_882)
    resumed.claim(sequence=0, operation_sha256=_sha(0))
    resumed.abort()
    restarted = reopened.begin(manifest_context_sha256=context, expected_operation_count=5_882)
    restarted.claim(sequence=0, operation_sha256=_sha(1))
    reopened.close()


def test_a1_claims_checkpoint_at_512_and_drop_only_pending_crash_tail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "a1-checkpoint.sqlite"
    context = _sha(101)
    store = SQLiteManagedMem0V6PreparationStore.create(path, authentication_key=KEY)
    stage = store.begin(manifest_context_sha256=context, expected_operation_count=600)
    for sequence in range(600):
        stage.claim(sequence=sequence, operation_sha256=_sha(sequence))
    assert store.claim_checkpoint_count == 1
    assert store.max_claim_batch_observed == 512
    store.close()

    raw = sqlite3.connect(path)
    assert raw.execute("SELECT COUNT(*) FROM claims").fetchone() == (512,)
    raw.close()

    reopened = SQLiteManagedMem0V6PreparationStore.open(path, authentication_key=KEY)
    resumed = reopened.begin(manifest_context_sha256=context, expected_operation_count=600)
    for sequence in range(512, 600):
        resumed.claim(sequence=sequence, operation_sha256=_sha(sequence))
    reopened._commit_claim_batch()
    assert reopened.claim_checkpoint_count == 1
    reopened.close()

    raw = sqlite3.connect(path)
    assert raw.execute("SELECT COUNT(*) FROM claims").fetchone() == (600,)
    raw.close()


def test_a2_claims_checkpoint_at_512_and_drop_only_pending_crash_tail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "a2-checkpoint.sqlite"
    context = _sha(102)
    store = SQLiteManagedCleanupV3PreparationStore.create(path, authentication_key=KEY)
    stage = store.begin(context_sha256=context, expected_operation_count=600)
    for sequence in range(600):
        stage.claim(sequence=sequence, operation_sha256=_sha(sequence))
    assert store.claim_checkpoint_count == 1
    assert store.max_claim_batch_observed == 512
    store.close()

    raw = sqlite3.connect(path)
    assert raw.execute("SELECT COUNT(*) FROM claims").fetchone() == (512,)
    raw.close()

    reopened = SQLiteManagedCleanupV3PreparationStore.open(path, authentication_key=KEY)
    resumed = reopened.begin(context_sha256=context, expected_operation_count=600)
    for sequence in range(512, 600):
        resumed.claim(sequence=sequence, operation_sha256=_sha(sequence))
    reopened._commit_claim_batch()
    assert reopened.claim_checkpoint_count == 1
    reopened.close()

    raw = sqlite3.connect(path)
    assert raw.execute("SELECT COUNT(*) FROM claims").fetchone() == (600,)
    raw.close()


def test_file_security_rejects_symlink_hardlink_and_tamper(tmp_path: Path) -> None:
    path = tmp_path / "a2.sqlite"
    store = SQLiteManagedCleanupV3PreparationStore.create(path, authentication_key=KEY)
    context = _sha(200)
    store.begin(context_sha256=context, expected_operation_count=5_882)
    store.close()
    assert path.stat().st_mode & 0o777 == 0o600

    link = tmp_path / "link.sqlite"
    link.symlink_to(path)
    with pytest.raises(Exception, match="unsafe"):
        SQLiteManagedCleanupV3PreparationStore.open(link, authentication_key=KEY)
    link.unlink()

    hardlink = tmp_path / "hard.sqlite"
    os.link(path, hardlink)
    with pytest.raises(Exception, match="unsafe"):
        SQLiteManagedCleanupV3PreparationStore.open(path, authentication_key=KEY)
    hardlink.unlink()

    raw = sqlite3.connect(path)
    raw.execute("UPDATE sessions SET expected_operations=1")
    raw.commit()
    raw.close()
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        SQLiteManagedCleanupV3PreparationStore.open(path, authentication_key=KEY)


@pytest.mark.parametrize(
    "store_type",
    (SQLiteManagedMem0V6PreparationStore, SQLiteManagedCleanupV3PreparationStore),
)
def test_open_or_create_recovers_empty_crash_partial_bootstrap(tmp_path: Path, store_type) -> None:
    path = tmp_path / f"{store_type.__name__}.sqlite"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    store = store_type.open_or_create(path, authentication_key=KEY)
    store.close()
    reopened = store_type.open_or_create(path, authentication_key=KEY)
    reopened.close()


@pytest.mark.parametrize(
    "store_type",
    (SQLiteManagedMem0V6PreparationStore, SQLiteManagedCleanupV3PreparationStore),
)
@pytest.mark.parametrize(
    "ddl",
    (
        "CREATE TRIGGER swallow BEFORE INSERT ON sessions BEGIN SELECT RAISE(IGNORE); END",
        "CREATE VIEW session_view AS SELECT * FROM sessions",
        "CREATE TABLE attacker(value TEXT) STRICT",
        "CREATE INDEX attacker_index ON sessions(expected_operations)",
    ),
)
def test_open_rejects_exact_catalog_drift_and_swallow_trigger(
    tmp_path: Path, store_type, ddl: str
) -> None:
    path = tmp_path / f"{store_type.__name__}-{hash(ddl)}.sqlite"
    store = store_type.create(path, authentication_key=KEY)
    store.close()
    raw = sqlite3.connect(path)
    raw.execute(ddl)
    raw.commit()
    raw.close()
    with pytest.raises(StrictV4SQLiteFileError, match="schema_unsafe"):
        store_type.open(path, authentication_key=KEY)


def test_write_rechecks_catalog_after_successful_open(tmp_path: Path) -> None:
    path = tmp_path / "a2-live-trigger.sqlite"
    store = SQLiteManagedCleanupV3PreparationStore.create(path, authentication_key=KEY)
    raw = sqlite3.connect(path)
    raw.execute("CREATE TRIGGER swallow BEFORE INSERT ON sessions BEGIN SELECT RAISE(IGNORE); END")
    raw.commit()
    raw.close()
    with pytest.raises(StrictV4SQLiteFileError, match="schema_unsafe"):
        store.begin(context_sha256=_sha(900), expected_operation_count=5_882)
    store.close()


@pytest.mark.parametrize(
    "store_type",
    (SQLiteManagedMem0V6PreparationStore, SQLiteManagedCleanupV3PreparationStore),
)
def test_open_or_create_serializes_two_process_empty_bootstrap_repair(
    tmp_path: Path, store_type
) -> None:
    path = tmp_path / f"{store_type.__name__}-race.sqlite"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(3)
    outcomes = context.Queue()
    workers = [
        context.Process(
            target=_bootstrap_worker,
            args=(store_type, str(path), barrier, outcomes),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    assert [outcomes.get(timeout=2) for _ in workers] == [None, None]
    store = store_type.open(path, authentication_key=KEY)
    store.close()


@pytest.mark.parametrize(
    "store_type",
    (SQLiteManagedMem0V6PreparationStore, SQLiteManagedCleanupV3PreparationStore),
)
def test_operation_rejects_rename_and_same_path_replacement(tmp_path: Path, store_type) -> None:
    path = tmp_path / f"{store_type.__name__}-binding.sqlite"
    store = store_type.create(path, authentication_key=KEY)
    moved = tmp_path / f"{store_type.__name__}-moved.sqlite"
    path.rename(moved)
    replacement = store_type.create(path, authentication_key=KEY)
    replacement.close()
    with pytest.raises(StrictV4SQLiteFileError, match="replaced"):
        if store_type is SQLiteManagedMem0V6PreparationStore:
            store.begin(
                manifest_context_sha256=_sha(901),
                expected_operation_count=5_882,
            )
        else:
            store.begin(context_sha256=_sha(901), expected_operation_count=5_882)
    store.close()


@pytest.mark.parametrize(
    "store_type",
    (SQLiteManagedMem0V6PreparationStore, SQLiteManagedCleanupV3PreparationStore),
)
def test_create_failure_never_unlinks_same_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store_type
) -> None:
    path = tmp_path / f"{store_type.__name__}-create.sqlite"
    moved = tmp_path / f"{store_type.__name__}-create-moved.sqlite"
    replacement_bytes = b"same-path replacement must survive"

    def replace_then_fail(store) -> None:
        store._path.rename(moved)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, replacement_bytes)
        finally:
            os.close(descriptor)
        raise RuntimeError("injected create failure")

    monkeypatch.setattr(store_type, "_verify_schema", replace_then_fail)
    with pytest.raises(RuntimeError, match="injected create failure"):
        store_type.create(path, authentication_key=KEY)
    assert path.read_bytes() == replacement_bytes


def test_shared_connect_failure_bound_unlinks_and_a1_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared-connect-retry.sqlite"
    original = sqlite_files._connect
    failed = False

    def fail_once(fd: int, *, readonly: bool):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected connect failure")
        return original(fd, readonly=readonly)

    monkeypatch.setattr(sqlite_files, "_connect", fail_once)
    with pytest.raises(RuntimeError, match="injected connect failure"):
        SQLiteManagedMem0V6PreparationStore.create(path, authentication_key=KEY)
    assert not path.exists()
    store = SQLiteManagedMem0V6PreparationStore.create(path, authentication_key=KEY)
    store.close()


def test_shared_connect_failure_preserves_same_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared-connect-replacement.sqlite"
    moved = tmp_path / "shared-connect-old.sqlite"
    replacement = b"shared helper replacement survives"

    def replace_then_fail(fd: int, *, readonly: bool):
        del fd, readonly
        path.rename(moved)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, replacement)
        finally:
            os.close(descriptor)
        raise RuntimeError("injected replacement connect failure")

    monkeypatch.setattr(sqlite_files, "_connect", replace_then_fail)
    with pytest.raises(RuntimeError, match="injected replacement connect failure"):
        sqlite_files.create_strict_sqlite(path)
    assert path.read_bytes() == replacement


def test_uncommitted_a2_pages_are_unreachable_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "a2.sqlite"
    context = _sha(300)
    terminal = _sha(301)
    store = SQLiteManagedCleanupV3PreparationStore.create(path, authentication_key=KEY)
    stage = store.begin(context_sha256=context, expected_operation_count=5_882)
    stage.claim(sequence=0, operation_sha256=_sha(0))
    store.close()
    with pytest.raises(ManagedCleanupV3Error, match="commit_missing"):
        list(
            iter_committed_pages(
                path,
                context_sha256=context,
                terminal_commitment_sha256=terminal,
                authentication_key=KEY,
            )
        )
    reopened = SQLiteManagedCleanupV3PreparationStore.open_or_create(path, authentication_key=KEY)
    resumed = reopened.begin(context_sha256=context, expected_operation_count=5_882)
    resumed.claim(sequence=0, operation_sha256=_sha(0))
    resumed.abort()
    reopened.close()


def test_full_locomo_a1_fixed_512_commit_and_reopen(tmp_path: Path) -> None:
    context = build_managed_mem0_v6_manifest_context(
        profile_id="mem0-locomo-top50-v1",
        run_id_sha256=_sha(10),
        binding_commitment_sha256=_sha(11),
        publishable_profile_commitment_sha256=_sha(12),
        methodology_commitment_sha256=_sha(13),
        dataset_sha256=_sha(14),
        admission_commitment_sha256=_sha(15),
        ingestion_root_sha256=_sha(16),
    )
    path = tmp_path / "a1-full.sqlite"
    store = SQLiteManagedMem0V6PreparationStore.create(path, authentication_key=KEY)
    result = build_managed_mem0_v6_paged_manifest(
        context=context,
        operation_sha256=(_sha(i) for i in range(5_882)),
        page_store=store,
        uniqueness_factory=store,
    )
    assert result.authority.page_size == 512
    assert result.authority.page_count == 12
    assert store.max_claim_batch_observed == 512
    store.close()
    reopened = SQLiteManagedMem0V6PreparationStore.open(path, authentication_key=KEY)
    assert reopened.read_operation_page(
        manifest_context_sha256=context.manifest_context_sha256,
        start_sequence=0,
    ) == tuple(_sha(i) for i in range(512))
    assert reopened.read_operation_page(
        manifest_context_sha256=context.manifest_context_sha256,
        start_sequence=5_632,
    ) == tuple(_sha(i) for i in range(5_632, 5_882))
    with pytest.raises(ManagedMem0V6ManifestError, match="claim_page_invalid"):
        reopened.read_operation_page(
            manifest_context_sha256=context.manifest_context_sha256,
            start_sequence=1,
        )
    stage = reopened.begin(
        manifest_context_sha256=context.manifest_context_sha256,
        expected_page_count=12,
    )
    assert stage.readback() == result.store_receipt
    assert stage.commit(result.authority) == result.store_receipt
    reopened.close()
    prepared_path = tmp_path / "a1-prepared-crash.sqlite"
    shutil.copy2(path, prepared_path)
    prepared = SQLiteManagedMem0V6PreparationStore.open(prepared_path, authentication_key=KEY)
    prepared_row = prepared._session(context.manifest_context_sha256)
    assert prepared_row is not None
    with prepared._write():
        prepared._update_state(
            context.manifest_context_sha256,
            int(prepared_row[0]),
            int(prepared_row[1]),
            "prepared",
            prepared_row[3],
            prepared_row[4],
            None,
        )
    prepared.close()
    resumed = SQLiteManagedMem0V6PreparationStore.open_or_create(
        prepared_path, authentication_key=KEY
    )
    resumed_stage = resumed.begin(
        manifest_context_sha256=context.manifest_context_sha256,
        expected_page_count=12,
    )
    assert resumed_stage.readback() is None
    resumed_stage.prepare(result.authority)
    assert resumed_stage.commit(result.authority) == result.store_receipt
    resumed.close()
    live_path = tmp_path / "a1-mutate-after-open.sqlite"
    shutil.copy2(path, live_path)
    live = SQLiteManagedMem0V6PreparationStore.open(live_path, authentication_key=KEY)
    raw = sqlite3.connect(live_path)
    raw.execute("DELETE FROM claims WHERE sequence=0")
    raw.commit()
    raw.close()
    live_stage = live.begin(
        manifest_context_sha256=context.manifest_context_sha256,
        expected_page_count=12,
    )
    with pytest.raises(ManagedMem0V6ManifestError, match="coverage_invalid"):
        live_stage.readback()
    live.close()
    for table in ("claims", "pages"):
        damaged = tmp_path / f"a1-missing-{table}.sqlite"
        shutil.copy2(path, damaged)
        raw = sqlite3.connect(damaged)
        raw.execute(f"DELETE FROM {table} WHERE rowid=(SELECT rowid FROM {table} LIMIT 1)")
        raw.commit()
        raw.close()
        with pytest.raises(ManagedMem0V6ManifestError, match="coverage_invalid"):
            SQLiteManagedMem0V6PreparationStore.open(damaged, authentication_key=KEY)


def test_longmemeval_a1_finalization_retains_at_most_one_512_claim_batch(
    tmp_path: Path,
) -> None:
    operation_count = 124_344
    page_count = (operation_count + MANAGED_MEM0_V6_PAGE_SIZE - 1) // 512
    context = _sha(400)
    store = SQLiteManagedMem0V6PreparationStore.create(
        tmp_path / "a1-longmemeval.sqlite", authentication_key=KEY
    )
    unique = store.begin(
        manifest_context_sha256=context,
        expected_operation_count=operation_count,
    )
    pages = store.begin(
        manifest_context_sha256=context,
        expected_page_count=page_count,
    )
    for sequence in range(operation_count):
        unique.claim(sequence=sequence, operation_sha256=_sha(sequence))
    commitments: list[str] = []
    for page_index, start in enumerate(range(0, operation_count, 512)):
        operations = tuple(_sha(i) for i in range(start, min(start + 512, operation_count)))
        body = page_body(
            profile_id="mem0-longmemeval-top50-v1",
            manifest_context_sha256=context,
            page_index=page_index,
            start_sequence=start,
            ordered_operation_sha256=operations,
        )
        page = ManagedMem0V6ManifestPage(
            profile_id="mem0-longmemeval-top50-v1",
            manifest_context_sha256=context,
            page_index=page_index,
            start_sequence=start,
            end_sequence_exclusive=start + len(operations),
            ordered_operation_sha256=operations,
            page_commitment_sha256=domain_sha256(PAGE_COMMITMENT_DOMAIN, body),
        )
        pages.append(page)
        commitments.append(page.page_commitment_sha256)
    root = merkle_root(tuple(commitments))
    tracemalloc.start()
    unique.finalize(
        operation_count=operation_count,
        ordered_operations_root_sha256=root,
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert store.max_claim_batch_observed == 512
    assert store.claim_checkpoint_count == page_count
    assert peak < 8 * 1024 * 1024
    store.close()


class _AmbiguousStore:
    def __init__(self, inner: SQLiteManagedCleanupV3PreparationStore) -> None:
        self.inner = inner

    def begin(self, **values):
        return _AmbiguousStage(self.inner.begin(**values))


class _AmbiguousStage:
    def __init__(self, inner) -> None:
        self.inner = inner

    def claim(self, **values) -> None:
        self.inner.claim(**values)

    def append(self, page) -> None:
        self.inner.append(page)

    def commit(self, authority):
        self.inner.commit(authority)
        raise OSError("connection dropped after durable commit")

    def readback(self):
        return self.inner.readback()

    def abort(self) -> None:
        self.inner.abort()


def test_full_locomo_a2_recovers_ambiguous_commit_and_streams_expected_count(
    tmp_path: Path,
) -> None:
    fixture = _cleanup_fixture_module()
    context = fixture._context(fixture.LOCOMO_PROFILE)
    a1 = fixture._a1_authority(context, 5_882)
    path = tmp_path / "a2.sqlite"
    store = SQLiteManagedCleanupV3PreparationStore.create(path, authentication_key=KEY)
    authority, receipt = build_managed_cleanup_v3_authority(
        context=context,
        operations=(fixture._operation(fixture.LOCOMO_PROFILE, i) for i in range(5_882)),
        a1_authority=a1,
        store=_AmbiguousStore(store),
    )
    assert 0 < store.max_claim_batch_observed <= 512
    store.close()
    pages = iter_committed_pages(
        path,
        context_sha256=context.context_sha256,
        terminal_commitment_sha256=authority.terminal_commitment_sha256,
        authentication_key=KEY,
    )
    first_page = next(pages)
    raw = sqlite3.connect(path, timeout=0)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        raw.execute("DELETE FROM pages WHERE page_index=1")
        raw.commit()
    raw.close()
    count = len(first_page.operations)
    page_count = 1
    for page in pages:
        count += len(page.operations)
        page_count += 1
    assert count == 5_882
    assert page_count == receipt.page_count
    binding_path = tmp_path / "a2-iterator-binding.sqlite"
    shutil.copy2(path, binding_path)
    bound_pages = iter_committed_pages(
        binding_path,
        context_sha256=context.context_sha256,
        terminal_commitment_sha256=authority.terminal_commitment_sha256,
        authentication_key=KEY,
    )
    next(bound_pages)
    moved_binding = tmp_path / "a2-iterator-moved.sqlite"
    binding_path.rename(moved_binding)
    shutil.copy2(moved_binding, binding_path)
    with pytest.raises(StrictV4SQLiteFileError, match="replaced"):
        next(bound_pages)
    bound_pages.close()
    prepared_path = tmp_path / "a2-prepared-crash.sqlite"
    shutil.copy2(path, prepared_path)
    prepared = SQLiteManagedCleanupV3PreparationStore.open(prepared_path, authentication_key=KEY)
    prepared_row = prepared._session(context.context_sha256)
    assert prepared_row is not None
    with prepared._write():
        prepared._update_state(
            context.context_sha256,
            int(prepared_row[0]),
            "prepared",
            prepared_row[2],
            prepared_row[3],
            None,
        )
    prepared.close()
    resumed = SQLiteManagedCleanupV3PreparationStore.open_or_create(
        prepared_path, authentication_key=KEY
    )
    resumed_stage = resumed.begin(
        context_sha256=context.context_sha256,
        expected_operation_count=5_882,
    )
    assert resumed_stage.readback() is None
    resumed_stage.prepare(authority)
    assert resumed_stage.commit(authority) == receipt
    resumed.close()
    live_path = tmp_path / "a2-mutate-after-open.sqlite"
    shutil.copy2(path, live_path)
    live = SQLiteManagedCleanupV3PreparationStore.open(live_path, authentication_key=KEY)
    raw = sqlite3.connect(live_path)
    raw.execute("DELETE FROM claims WHERE sequence=0")
    raw.commit()
    raw.close()
    live_stage = live.begin(
        context_sha256=context.context_sha256,
        expected_operation_count=5_882,
    )
    with pytest.raises(ManagedCleanupV3Error, match="coverage_invalid"):
        live_stage.readback()
    live.close()
    for table in ("claims", "pages"):
        damaged = tmp_path / f"a2-missing-{table}.sqlite"
        shutil.copy2(path, damaged)
        raw = sqlite3.connect(damaged)
        raw.execute(f"DELETE FROM {table} WHERE rowid=(SELECT rowid FROM {table} LIMIT 1)")
        raw.commit()
        raw.close()
        with pytest.raises(ManagedCleanupV3Error, match="coverage_invalid"):
            SQLiteManagedCleanupV3PreparationStore.open(damaged, authentication_key=KEY)
