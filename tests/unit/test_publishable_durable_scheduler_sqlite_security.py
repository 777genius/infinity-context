from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    SUITE_SEAL_READBACK_POLICY_SHA256,
    SchedulerRunnerError,
    SchedulerStepDisposition,
    SchedulerSuiteSeal,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    ANSWER_CIPHERTEXT_BYTES_CAP,
    SchedulerSQLiteError,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)
from publishable_durable_scheduler_test_support import built_runs, sha
from test_publishable_durable_scheduler_sqlite import (
    _runner_open,
    _RunnerBoundary,
    _RunnerRenderer,
    _seed_runner_committed,
)

_SECRET = b"s" * 32


@pytest.fixture(scope="module")
def prepared():
    suite, locomo, _ = built_runs()
    return suite, *locomo


def _store(tmp_path: Path, prepared):
    suite, run, manifest = prepared
    private = tmp_path / "private"
    return SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )


def _database(tmp_path: Path) -> Path:
    return tmp_path / "private" / "scheduler.sqlite3"


def _suite_seal_store(tmp_path: Path, suite):
    private = tmp_path / "seal-private"
    return SQLiteSchedulerSuiteSealStore(
        private / "suite-seal.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite_authority_sha256=suite.commitment_sha256,
    )


def _suite_seal(suite) -> SchedulerSuiteSeal:
    return SchedulerSuiteSeal(
        suite_authority_sha256=suite.commitment_sha256,
        runtime_provenance_sha256=suite.runtime_provenance_sha256,
        ordered_run_authority_sha256=tuple(
            run_authority_from_suite(suite, run_index=index).commitment_sha256 for index in range(2)
        ),
        ordered_evaluation_receipt_root_sha256=(sha("root-0"), sha("root-1")),
        ordered_extraction_terminal_sha256=(sha("terminal-0"), sha("terminal-1")),
        ordered_authenticated_extraction_terminal_sha256=(
            sha("authenticated-0"),
            sha("authenticated-1"),
        ),
        renderer_policy_sha256=sha("renderer"),
        private_answer_policy_sha256=sha("private-answer"),
        receipt_verifier_policy_sha256=suite.bridge_boot.receipt_verifier_policy_sha256,
        outcome_readback_policy_sha256=sha("outcome-readback"),
        extraction_terminal_read_policy_sha256=sha("extraction-read"),
        seal_readback_policy_sha256=SUITE_SEAL_READBACK_POLICY_SHA256,
        case_count=PUBLISHABLE_SUITE_CASE_COUNT,
        evaluation_call_count=PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        extraction_operation_count=PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
        charged_tokens=8_160,
    )


def _intent(store: SQLiteDurableSchedulerStore, call_id: str) -> None:
    store.acquire_lease(
        call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    store.bind_request(call_id, lease_id="lease-1", request_sha256=sha("request"))
    store.record_dispatch_intent(
        call_id,
        lease_id="lease-1",
        now_unix_ms=2_100,
        bridge_boot_authority_sha256=store.read_run().bridge_boot_authority_sha256,
        intent_sha256=sha("intent"),
    )


def _mutate(database: Path, statement: str, parameters: tuple[object, ...] = ()) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def test_rejects_unsafe_directory_database_symlink_and_hardlink(tmp_path: Path, prepared) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o755)
    with pytest.raises(SchedulerSQLiteError, match="private_directory_unsafe"):
        _store(tmp_path, prepared)
    private.chmod(0o700)
    store = _store(tmp_path, prepared)
    store.verify()
    database = _database(tmp_path)
    database.chmod(0o644)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)
    database.chmod(0o600)
    hardlink = private / "scheduler-hardlink.sqlite3"
    os.link(database, hardlink)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)
    hardlink.unlink()
    database.unlink()
    target = private / "target.sqlite3"
    target.touch(mode=0o600)
    database.symlink_to(target.name)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)


def test_rejects_foreign_owned_database(
    tmp_path: Path,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(tmp_path, prepared)
    database = _database(tmp_path)
    original_lstat = Path.lstat

    def foreign_owned_lstat(path: Path) -> os.stat_result:
        info = original_lstat(path)
        if path != database:
            return info
        values = list(info)
        values[4] = os.geteuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", foreign_owned_lstat)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)


@pytest.mark.parametrize(
    ("statement", "match"),
    [
        ("UPDATE scheduler_calls SET phase = 'committed' WHERE ordinal = 0", "authentication"),
        ("UPDATE scheduler_runs SET consumed_tokens = 1", "authentication"),
        (
            "UPDATE scheduler_events SET event_kind = 'tampered' WHERE event_id = 1",
            "event_authentication",
        ),
    ],
)
def test_authenticated_rows_and_events_reject_tamper(
    tmp_path: Path, prepared, statement: str, match: str
) -> None:
    _store(tmp_path, prepared)
    _mutate(_database(tmp_path), statement)
    with pytest.raises(SchedulerSQLiteError, match=match):
        _store(tmp_path, prepared)


def test_ciphertext_tamper_and_oversize_are_rejected(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    call = store.read_calls(after_ordinal=-1, limit=1)[0]
    _intent(store, call.logical_call_id)
    with pytest.raises(SchedulerSQLiteError, match="ciphertext_invalid"):
        store.commit_outcome(
            call.logical_call_id,
            intent_sha256=sha("intent"),
            receipt_sha256=sha("receipt"),
            completion_tokens=1,
            charged_tokens=1,
            answer_ciphertext=b"x" * (ANSWER_CIPHERTEXT_BYTES_CAP + 1),
        )
    store.commit_outcome(
        call.logical_call_id,
        intent_sha256=sha("intent"),
        receipt_sha256=sha("receipt"),
        completion_tokens=1,
        charged_tokens=1,
        answer_ciphertext=b"opaque-ciphertext",
    )
    _mutate(
        _database(tmp_path),
        "UPDATE scheduler_calls SET answer_ciphertext = ? WHERE ordinal = 0",
        (b"tampered-ciphertext",),
    )
    with pytest.raises(SchedulerSQLiteError, match="ciphertext_authentication"):
        _store(tmp_path, prepared)


def test_event_tail_truncation_and_extra_schema_are_rejected(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    call = store.read_calls(after_ordinal=-1, limit=1)[0]
    store.acquire_lease(
        call.logical_call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    _mutate(_database(tmp_path), "DELETE FROM scheduler_events WHERE event_id = 2")
    with pytest.raises(SchedulerSQLiteError, match="event_head"):
        _store(tmp_path, prepared)

    other = tmp_path / "other"
    other.mkdir()
    _store(other, prepared)
    _mutate(_database(other), "CREATE TABLE untrusted_extra (value TEXT)")
    with pytest.raises(SchedulerSQLiteError, match="schema_invalid"):
        _store(other, prepared)


def test_corrupt_and_truncated_database_fail_closed(tmp_path: Path, prepared) -> None:
    _store(tmp_path, prepared)
    database = _database(tmp_path)
    database.write_bytes(b"not a sqlite database")
    database.chmod(0o600)
    with pytest.raises(SchedulerSQLiteError, match="integrity_invalid|schema_invalid"):
        _store(tmp_path, prepared)

    other = tmp_path / "truncated"
    other.mkdir()
    _store(other, prepared)
    truncated = _database(other)
    contents = truncated.read_bytes()
    truncated.write_bytes(contents[:4096])
    truncated.chmod(0o600)
    with pytest.raises(SchedulerSQLiteError, match="integrity_invalid|schema_invalid"):
        _store(other, prepared)


@pytest.mark.parametrize("dependency_mode", ["ignored", "substituted"])
def test_runner_judge_renderer_must_use_exact_private_dependency(
    tmp_path: Path,
    dependency_mode: str,
) -> None:
    prepared = built_runs()
    renderer = _RunnerRenderer(dependency_mode=dependency_mode)
    runner, boundary, _, _ = _runner_open(tmp_path, prepared, renderer=renderer)
    assert runner.run_next().disposition is SchedulerStepDisposition.COMMITTED
    with pytest.raises(SchedulerRunnerError, match="request_policy_binding_invalid"):
        runner.run_next()
    assert boundary.calls == 1
    assert runner._entries[0].store.read_calls(after_ordinal=0, limit=1)[0].phase is (
        SchedulerCallPhase.PLANNED
    )


def test_runner_exact_two_run_cardinality_is_2040_cases_and_8160_calls(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    manifests = (prepared[1][1], prepared[2][1])
    assert runner.paid_go_ready is False
    assert runner.case_count == PUBLISHABLE_SUITE_CASE_COUNT == 2_040
    assert runner.evaluation_call_count == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT == 8_160
    assert tuple(item.authority.call_count for item in manifests) == (6_160, 2_000)
    assert sum(item.authority.call_count for item in manifests) == 8_160
    assert sum(entry.run.binding.profile.case_count for entry in runner._entries) == 2_040


def test_existing_suite_seal_fences_recreated_run_stores_without_dispatch(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    for entry in runner._entries:
        _seed_runner_committed(entry.store)
    runner.seal()
    for name in ("locomo", "longmemeval"):
        (tmp_path / name / "scheduler.sqlite3").unlink()
    boundary = _RunnerBoundary(runner._suite.bridge_boot.commitment_sha256)
    with pytest.raises(SchedulerRunnerError, match="suite_seal_run_binding_invalid"):
        _runner_open(tmp_path, prepared, boundary=boundary)
    assert boundary.calls == 0


def test_suite_seal_store_exact_replay_and_divergence(tmp_path: Path) -> None:
    suite = built_runs()[0]
    store = _suite_seal_store(tmp_path, suite)
    seal = _suite_seal(suite)
    assert store.persist_exact(seal) == seal
    assert _suite_seal_store(tmp_path, suite).read() == seal
    assert seal.runtime_provenance_sha256 == suite.runtime_provenance_sha256
    with pytest.raises(SchedulerRunnerError, match="suite_seal_divergent"):
        store.persist_exact(replace(seal, charged_tokens=seal.charged_tokens + 1))
    with pytest.raises(SchedulerRunnerError, match="suite_seal_divergent"):
        store.persist_exact(replace(seal, runtime_provenance_sha256="f" * 64))


@pytest.mark.parametrize(
    "mutation",
    ["delete_meta", "delete_seal", "delete_both", "truncate", "extra_schema"],
)
def test_suite_seal_store_rejects_rollback_truncation_and_schema_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    suite = built_runs()[0]
    store = _suite_seal_store(tmp_path, suite)
    store.persist_exact(_suite_seal(suite))
    database = tmp_path / "seal-private" / "suite-seal.sqlite3"
    if mutation == "truncate":
        database.write_bytes(b"")
        database.chmod(0o600)
    else:
        connection = sqlite3.connect(database)
        try:
            if mutation in ("delete_meta", "delete_both"):
                connection.execute("DELETE FROM suite_seal_meta")
            if mutation in ("delete_seal", "delete_both"):
                connection.execute("DELETE FROM suite_seals")
            if mutation == "extra_schema":
                connection.execute("CREATE TABLE forged (value TEXT)")
            connection.commit()
        finally:
            connection.close()
    with pytest.raises(SchedulerRunnerError):
        _suite_seal_store(tmp_path, suite)


def test_suite_seal_store_rejects_noncanonical_and_linked_paths(tmp_path: Path) -> None:
    suite = built_runs()[0]
    store = _suite_seal_store(tmp_path, suite)
    assert store.read() is None
    private = tmp_path / "seal-private"
    database = private / "suite-seal.sqlite3"
    hardlink = private / "hardlink.sqlite3"
    os.link(database, hardlink)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        SQLiteSchedulerSuiteSealStore(
            hardlink,
            private_directory=private,
            authentication_secret=_SECRET,
            suite_authority_sha256=suite.commitment_sha256,
        )
    hardlink.unlink()
    alias = tmp_path / "private-alias"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(SchedulerSQLiteError, match="private_directory_unsafe"):
        SQLiteSchedulerSuiteSealStore(
            alias / "suite-seal.sqlite3",
            private_directory=alias,
            authentication_secret=_SECRET,
            suite_authority_sha256=suite.commitment_sha256,
        )
