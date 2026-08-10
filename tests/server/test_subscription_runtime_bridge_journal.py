from __future__ import annotations

import multiprocessing
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeDivergenceError,
    BridgeJournal,
    BridgeJournalError,
    HmacJournalIntegrity,
    OutcomeUnknown,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from subscription_runtime_bridge_test_support import (
    JOURNAL_KEY,
    AttestedFakeTransport,
    FakeSecrets,
    TestAuthenticatedCipher,
    make_binding,
    make_pool,
    make_request,
)

MAX_BYTES = 256 * 1024


def test_private_exact_schema_permissions_and_bound_destroy(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))

    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert database.stat().st_uid == os.geteuid()
    assert database.stat().st_nlink == 1
    connection = sqlite3.connect(database)
    try:
        objects = connection.execute(
            """SELECT type, name FROM sqlite_schema
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        ).fetchall()
        assert objects == [
            ("index", "bridge_intents_logical_call"),
            ("table", "bridge_intents"),
            ("table", "bridge_journal_metadata"),
            ("table", "bridge_results"),
        ]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()
    assert not database.with_name(f"{database.name}-wal").exists()

    journal.destroy()
    assert not database.exists()


def test_exact_intent_replay_and_divergence(tmp_path: Path) -> None:
    pool = make_pool()
    binding = make_binding()
    bridge, intent = derive_bridge_intent(
        pool=pool,
        binding=binding,
        request_body=make_request(),
        maximum_request_bytes=MAX_BYTES,
    )
    assert bridge == pool.select(binding)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )

    first = journal.record_intent(intent)
    replay = journal.record_intent(intent)
    assert first.dispatch_granted is True
    assert replay.dispatch_granted is False
    assert isinstance(replay.outcome, OutcomeUnknown)

    _bridge, divergent = derive_bridge_intent(
        pool=pool,
        binding=binding,
        request_body=make_request(prompt="changed private prompt"),
        maximum_request_bytes=MAX_BYTES,
    )
    with pytest.raises(BridgeDivergenceError, match="intent_divergence"):
        journal.record_intent(divergent)

    _bridge, duplicate_logical_call = derive_bridge_intent(
        pool=pool,
        binding=replace(binding, intent_id="different-intent-same-logical-call"),
        request_body=make_request(),
        maximum_request_bytes=MAX_BYTES,
    )
    with pytest.raises(BridgeDivergenceError, match="logical_call_divergence"):
        journal.record_intent(duplicate_logical_call)
    assert journal.statistics().intent_count == 1
    assert journal.statistics().result_count == 0
    assert journal.statistics().event_count == 1
    journal.close()


def test_exact_result_replay_and_divergence(tmp_path: Path) -> None:
    journal, completed = _completed_journal(tmp_path / "private" / "bridge.sqlite3")
    exact = journal.record_result(completed.readback.intent, completed.readback.result)
    assert exact == completed.readback
    divergent = replace(
        completed.readback.result,
        encrypted_output=completed.readback.result.encrypted_output + b"changed",
    )
    with pytest.raises(BridgeDivergenceError, match="result_divergence"):
        journal.record_result(completed.readback.intent, divergent)
    statistics = journal.statistics()
    assert (statistics.intent_count, statistics.result_count, statistics.event_count) == (1, 1, 2)
    journal.close()


def test_two_connections_grant_exactly_one_dispatch(tmp_path: Path) -> None:
    pool = make_pool()
    binding = make_binding()
    _bridge, intent = derive_bridge_intent(
        pool=pool,
        binding=binding,
        request_body=make_request(),
        maximum_request_bytes=MAX_BYTES,
    )
    database = tmp_path / "private" / "bridge.sqlite3"
    created = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    created.close()
    first = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    second = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    barrier = Barrier(2)

    def claim(journal: BridgeJournal) -> bool:
        barrier.wait()
        return journal.record_intent(intent).dispatch_granted

    with ThreadPoolExecutor(max_workers=2) as executor:
        grants = list(executor.map(claim, (first, second)))
    assert sorted(grants) == [False, True]
    assert isinstance(first.lookup_outcome(binding.intent_id), OutcomeUnknown)
    first.close()
    second.close()


def test_two_processes_grant_exactly_one_dispatch(tmp_path: Path) -> None:
    pool = make_pool()
    binding = make_binding()
    _bridge, intent = derive_bridge_intent(
        pool=pool,
        binding=binding,
        request_body=make_request(),
        maximum_request_bytes=MAX_BYTES,
    )
    database = tmp_path / "private" / "bridge.sqlite3"
    created = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    created.close()
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_process_claim,
            args=(str(database), JOURNAL_KEY, intent, queue),
        )
        for _index in range(2)
    ]

    for process in processes:
        process.start()
    grants = [queue.get(timeout=10) for _process in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert sorted(grants) == [False, True]
    reopened = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    assert isinstance(reopened.lookup_outcome(binding.intent_id), OutcomeUnknown)
    reopened.close()


def test_wrong_journal_key_rejects_reopen(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    journal.close()

    with pytest.raises(BridgeJournalError, match="head_hmac"):
        BridgeJournal.open(
            database,
            integrity=HmacJournalIntegrity(b"wrong-journal-key-32-bytes-minimum!"),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE bridge_intents SET request_body_sha256 = '" + "0" * 64 + "'",
        "UPDATE bridge_results SET encrypted_output = X'00'",
        "UPDATE bridge_journal_metadata SET head_hmac_sha256 = '" + "0" * 64 + "'",
        "DELETE FROM bridge_results",
        "UPDATE bridge_journal_metadata SET event_count = 0",
    ],
)
def test_metadata_intent_result_and_truncation_style_row_tamper_rejected(
    tmp_path: Path,
    statement: str,
) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    journal, _outcome = _completed_journal(database)
    journal.close()
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))


def test_schema_extra_object_and_file_truncation_rejected(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    journal, _outcome = _completed_journal(database)
    journal.close()
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE injected (value TEXT)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(BridgeJournalError, match="schema_invalid"):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))

    second_database = tmp_path / "second-private" / "bridge.sqlite3"
    second = BridgeJournal.create(
        second_database,
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    second.close()
    with second_database.open("r+b") as stream:
        stream.truncate(max(1, second_database.stat().st_size // 2))
    with pytest.raises(BridgeJournalError):
        BridgeJournal.open(second_database, integrity=HmacJournalIntegrity(JOURNAL_KEY))


def test_hardlink_symlink_mode_and_parent_security_rejected(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    journal.close()
    hardlink = database.with_name("linked.sqlite3")
    os.link(database, hardlink)
    with pytest.raises(BridgeJournalError, match="file_unsafe"):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    hardlink.unlink()

    symlink = database.with_name("symlink.sqlite3")
    symlink.symlink_to(database)
    with pytest.raises(BridgeJournalError, match="file_unsafe"):
        BridgeJournal.open(symlink, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    symlink.unlink()

    database.chmod(0o640)
    with pytest.raises(BridgeJournalError, match="file_unsafe"):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    database.chmod(0o600)
    database.parent.chmod(0o750)
    with pytest.raises(BridgeJournalError, match="parent_unsafe"):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))


def test_replacement_is_never_unlinked_by_bound_cleanup(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    displaced = database.with_name("displaced.sqlite3")
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    database.rename(displaced)
    descriptor = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)

    with pytest.raises(BridgeJournalError):
        journal.destroy()
    assert database.exists()
    assert database.stat().st_size == 0
    assert displaced.exists()


def test_ciphertext_swap_between_authenticated_rows_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "private" / "bridge.sqlite3"
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    adapter = SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=TestAuthenticatedCipher(),
        maximum_request_bytes=MAX_BYTES,
        maximum_response_bytes=MAX_BYTES,
    )
    for index in (1, 2):
        assert isinstance(
            adapter.execute(
                binding=make_binding(index),
                canonical_request_body=make_request(prompt=f"private prompt {index}"),
            ),
            TerminalBridgeCall,
        )
    journal.close()
    connection = sqlite3.connect(database)
    try:
        first_ciphertext = connection.execute(
            "SELECT encrypted_output FROM bridge_results WHERE intent_id = ?",
            (make_binding(1).intent_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE bridge_results SET encrypted_output = ? WHERE intent_id = ?",
            (first_ciphertext, make_binding(2).intent_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(BridgeJournalError, match="result_hmac"):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))


def _completed_journal(database: Path):
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    adapter = SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=TestAuthenticatedCipher(),
        maximum_request_bytes=MAX_BYTES,
        maximum_response_bytes=MAX_BYTES,
    )
    outcome = adapter.execute(
        binding=make_binding(),
        canonical_request_body=make_request(),
    )
    assert isinstance(outcome, TerminalBridgeCall)
    return journal, outcome


def _process_claim(database: str, key: bytes, intent, queue) -> None:
    journal = BridgeJournal.open(Path(database), integrity=HmacJournalIntegrity(key))
    try:
        queue.put(journal.record_intent(intent).dispatch_granted)
    finally:
        journal.close()
