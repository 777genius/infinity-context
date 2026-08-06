from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from functools import cache
from hashlib import sha256
from pathlib import Path

import pytest
from infinity_context_server.publishable_checkpoint_journal import sqlite_transaction
from infinity_context_server.publishable_checkpoint_journal.crypto import (
    HmacSha256JournalSigner,
)
from infinity_context_server.publishable_checkpoint_journal.domain import (
    PUBLISHABLE_ANSWER_CALL_COUNT,
    PUBLISHABLE_CASE_COUNT,
    BackendTargetAuthority,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    LogicalCallIdentity,
    ManifestAuthority,
    ManifestCaseAuthority,
    ProviderCallState,
    PublishableEvaluationManifest,
    PublishableRunIdentity,
    RunPhase,
    RuntimeReceipt,
    VerifiedRuntimeReceipt,
    create_journal_event,
)
from infinity_context_server.publishable_checkpoint_journal.service import (
    NullExternalLifecycle,
    PublishableCheckpointJournalService,
)
from infinity_context_server.publishable_checkpoint_journal.sqlite_adapter import (
    SQLiteCheckpointJournal,
)
from publishable_checkpoint_crash_fixture import crash_script


class _ReceiptVerifier:
    def verify(
        self,
        *,
        identity: LogicalCallIdentity,
        receipt: RuntimeReceipt,
    ) -> VerifiedRuntimeReceipt:
        assert receipt.run_id == identity.run_id
        assert receipt.logical_call_id == identity.logical_call_id
        return VerifiedRuntimeReceipt(
            receipt=receipt,
            verifier_key_id="receipt-verifier-1",
            verification_commitment_sha256=_digest("verification"),
        )


def test_sqlite_uses_private_wal_full_foreign_key_schema(tmp_path: Path) -> None:
    private_directory = tmp_path / "private-journal"
    database_path = private_directory / "checkpoint.db"
    journal = SQLiteCheckpointJournal(
        database_path,
        private_directory=private_directory,
        busy_timeout_ms=4321,
    )

    assert journal.pragma_values() == {
        "busy_timeout": 4321,
        "foreign_keys": 1,
        "journal_mode": "wal",
        "synchronous": 2,
    }
    assert stat.S_IMODE(private_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "schema_meta",
            "run_state",
            "manifest_cases",
            "manifest_backend_targets",
            "evaluation_manifest",
            "case_lanes",
            "provider_calls",
            "private_provider_results",
            "receipt_events",
            "lifecycle_outbox",
        } <= tables
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone() == ("3",)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("schema_rows", "error_code"),
    (
        ((), "checkpoint_journal_schema_version_missing"),
        ((("schema_version", "2"),), "checkpoint_journal_schema_version_mismatch"),
        ((("schema_version", "999"),), "checkpoint_journal_schema_version_mismatch"),
        (
            (("schema_version", "3"), ("schema_version", "3")),
            "checkpoint_journal_schema_version_duplicate",
        ),
        (
            (("schema_version", "3"),),
            "checkpoint_journal_schema_layout_invalid",
        ),
    ),
)
def test_reopen_fails_closed_for_missing_wrong_or_duplicate_schema_version(
    tmp_path: Path,
    schema_rows: tuple[tuple[str, str], ...],
    error_code: str,
) -> None:
    private_directory = tmp_path / error_code
    private_directory.mkdir(mode=0o700)
    os.chmod(private_directory, 0o700)
    database_path = private_directory / "checkpoint.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE schema_meta(key TEXT, value TEXT)")
        for table in (
            "run_state",
            "manifest_cases",
            "manifest_backend_targets",
            "evaluation_manifest",
            "case_lanes",
            "provider_calls",
            "private_provider_results",
            "receipt_events",
            "lifecycle_outbox",
        ):
            connection.execute(f"CREATE TABLE {table}(placeholder TEXT)")
        connection.executemany(
            "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
            schema_rows,
        )
        connection.commit()
    finally:
        connection.close()
    os.chmod(database_path, 0o600)

    with pytest.raises(CheckpointJournalError, match=error_code):
        SQLiteCheckpointJournal(
            database_path,
            private_directory=private_directory,
        )


def test_reopen_rejects_extra_schema_object(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    journal, _ = _service(private_directory)
    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute("CREATE TABLE unexpected_extra(value TEXT)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_schema_layout_invalid",
    ):
        SQLiteCheckpointJournal(
            journal.database_path,
            private_directory=private_directory,
        )


def test_sqlite_enforces_receipt_uniqueness_and_foreign_keys(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    manifest = _manifest()
    service.initialize(run, manifest)
    first, second = manifest.calls[:2]
    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO provider_calls(
                run_id, logical_call_id, phase, provider_receipt_id
            ) VALUES (?, ?, 'committed', ?)
            """,
            (run.run_id, first.logical_call_id, "receipt-unique"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(
                """
                INSERT INTO provider_calls(
                    run_id, logical_call_id, phase, provider_receipt_id
                ) VALUES (?, ?, 'committed', ?)
                """,
                (run.run_id, second.logical_call_id, "receipt-unique"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                """
                INSERT INTO provider_calls(run_id, logical_call_id, phase)
                VALUES (?, ?, 'reserved')
                """,
                (run.run_id, "f" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                """
                INSERT INTO private_provider_results(
                    run_id, logical_call_id, receipt_identity_json,
                    request_commitment_sha256, receipt_commitment_sha256,
                    verifier_key_id, verification_commitment_sha256
                ) VALUES (?, ?, '{}', ?, ?, 'verifier', ?)
                """,
                (run.run_id, second.logical_call_id, "a" * 64, "b" * 64, "c" * 64),
            )
    finally:
        connection.close()


def test_adapter_rejects_shared_or_unsafe_parent_without_chmodding_it(
    tmp_path: Path,
) -> None:
    shared_directory = tmp_path / "shared"
    shared_directory.mkdir(mode=0o755)
    os.chmod(shared_directory, 0o755)

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_private_directory_unsafe",
    ):
        SQLiteCheckpointJournal(
            shared_directory / "checkpoint.db",
            private_directory=shared_directory,
        )

    assert stat.S_IMODE(shared_directory.stat().st_mode) == 0o755


def test_adapter_rejects_private_directory_symlink(tmp_path: Path) -> None:
    target_directory = tmp_path / "private-target"
    target_directory.mkdir(mode=0o700)
    os.chmod(target_directory, 0o700)
    private_directory = tmp_path / "private-link"
    private_directory.symlink_to(target_directory, target_is_directory=True)

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_private_directory_unsafe",
    ):
        SQLiteCheckpointJournal(
            private_directory / "checkpoint.db",
            private_directory=private_directory,
        )

    assert stat.S_IMODE(target_directory.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("fault_point", "expected_phase", "expected_unknown"),
    (
        ("reserved", CallPhase.RESERVED, False),
        ("dispatched", CallPhase.OUTCOME_UNKNOWN, True),
        ("committed", CallPhase.COMMITTED, False),
    ),
)
def test_subprocess_crash_reopen_preserves_safe_evaluation_state(
    tmp_path: Path,
    fault_point: str,
    expected_phase: CallPhase,
    expected_unknown: bool,
) -> None:
    private_directory = tmp_path / f"{fault_point}-private"
    database_path = private_directory / "checkpoint.db"
    completed = subprocess.run(
        [sys.executable, "-c", crash_script(database_path, fault_point)],
        check=False,
        env=_subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr

    journal, service = _service(private_directory)
    resumed = service.resume("run-1")
    call = _manifest().calls[0]
    states = tuple(journal.iter_calls(run_id="run-1"))  # Exhaustion closes SQLite.
    state = states[0]

    assert state.identity == call
    assert state.phase is expected_phase
    assert (resumed.run.phase is RunPhase.RECONCILIATION_REQUIRED) is expected_unknown
    assert resumed.outcome_unknown_count == (1 if expected_unknown else 0)
    if expected_unknown:
        with pytest.raises(
            CheckpointJournalError,
            match="checkpoint_journal_outcome_unknown_retry_blocked",
        ):
            service.mark_dispatched(call)


def test_concurrent_identical_reservation_has_one_durable_event_winner(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "private"
    first_journal, first_service = _service(private_directory)
    _, second_service = _service(private_directory)
    run = _run()
    call = _manifest().calls[0]
    first_service.initialize(run, _manifest())
    barrier = threading.Barrier(2)

    def reserve(service: PublishableCheckpointJournalService) -> ProviderCallState:
        assert barrier.wait(timeout=5) in (0, 1)
        return service.reserve(call)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(reserve, (first_service, second_service)))

    assert results == (
        ProviderCallState(identity=call, phase=CallPhase.RESERVED),
        ProviderCallState(identity=call, phase=CallPhase.RESERVED),
    )
    assert first_service.verify_chain(run.run_id).event_count == 2
    assert sum(1 for _ in first_journal.iter_calls(run_id=run.run_id)) == 1


def test_exact_6160_manifest_resume_streams_without_all_row_materialization(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    manifest = _manifest()
    service.initialize(run, manifest)

    _seed_evaluation_state(
        journal,
        manifest,
        phase=CallPhase.DISPATCHED,
        include_private_results=False,
    )

    streaming_service = PublishableCheckpointJournalService(
        journal=_NoMaterializationJournal(journal),
        signer=HmacSha256JournalSigner(key_id="journal-key-1", secret=b"journal-secret"),
        receipt_verifier=_ReceiptVerifier(),
        external_lifecycle=NullExternalLifecycle(),
    )
    resumed = streaming_service.resume(run.run_id)

    assert resumed.newly_outcome_unknown_count == 6160
    assert resumed.outcome_unknown_count == 6160
    assert (
        sum(
            1
            for _ in journal.iter_calls(
                run_id=run.run_id,
                phases=(CallPhase.OUTCOME_UNKNOWN,),
                batch_size=127,
            )
        )
        == 6160
    )


def test_evaluation_seal_requires_exact_full_6160_manifest_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    manifest = _manifest()
    service.initialize(run, manifest)

    _seed_evaluation_state(
        journal,
        manifest,
        phase=CallPhase.COMMITTED,
        include_private_results=True,
    )
    for name in (
        "iter_manifest_identities",
        "iter_manifest_cases",
        "iter_manifest_backend_targets",
    ):
        original = getattr(sqlite_transaction, name)
        monkeypatch.setattr(
            sqlite_transaction,
            name,
            lambda *args, _original=original, **kwargs: _NoMaterializationIterator(
                _original(*args, **kwargs)
            ),
        )
    streaming_service = PublishableCheckpointJournalService(
        journal=_NoMaterializationJournal(journal),
        signer=HmacSha256JournalSigner(
            key_id="journal-key-1",
            secret=b"journal-secret",
        ),
        receipt_verifier=_ReceiptVerifier(),
        external_lifecycle=NullExternalLifecycle(),
    )
    sealed = streaming_service.seal_evaluation(run.run_id)

    assert sealed.phase is RunPhase.EVALUATION_SEALED
    assert streaming_service.seal_evaluation(run.run_id) == sealed

    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute(
            "DELETE FROM private_provider_results WHERE run_id = ? AND logical_call_id = ?",
            (run.run_id, manifest.calls[0].logical_call_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_run_state_mismatch",
    ):
        streaming_service.seal_evaluation(run.run_id)


def test_evaluation_seal_rejects_tampered_persisted_manifest(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    manifest = _manifest()
    service.initialize(run, manifest)

    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute(
            """
            UPDATE evaluation_manifest
            SET case_alias = ?
            WHERE run_id = ? AND ordinal = 0
            """,
            ("alias-tampered", run.run_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_call_row_identity_drift",
    ):
        service.initialize(run, manifest)


def test_semantic_replay_rejects_unsigned_run_phase_and_identity_tamper(
    tmp_path: Path,
) -> None:
    for column, value, error_code in (
        (
            "phase",
            RunPhase.EVALUATION_SEALED.value,
            "checkpoint_journal_chain_run_state_mismatch",
        ),
        (
            "profile_commitment_sha256",
            _digest("tampered-profile"),
            "checkpoint_journal_chain_run_identity_mismatch",
        ),
    ):
        private_directory = tmp_path / column
        journal, service = _service(private_directory)
        run = _run()
        service.initialize(run, _manifest())
        connection = sqlite3.connect(journal.database_path)
        try:
            connection.execute(
                f"UPDATE run_state SET {column} = ? WHERE run_id = ?",
                (value, run.run_id),
            )
            connection.commit()
        finally:
            connection.close()

        with pytest.raises(CheckpointJournalError, match=error_code):
            service.verify_chain(run.run_id)


def test_evaluation_seal_rejects_signed_commits_without_private_results(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    manifest = _manifest()
    service.initialize(run, manifest)
    _seed_evaluation_state(
        journal,
        manifest,
        phase=CallPhase.COMMITTED,
        include_private_results=False,
    )

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_run_state_mismatch",
    ):
        service.seal_evaluation(run.run_id)


def test_semantic_replay_rejects_manufactured_provider_call_state(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    call = _manifest().calls[0]
    service.initialize(run, _manifest())
    with journal.write_transaction() as transaction:
        transaction.put_call(_committed_state(call))

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_run_state_mismatch",
    ):
        service.seal_evaluation(run.run_id)


def test_committed_result_stores_only_compact_receipt_identity(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    call = _manifest().calls[0]
    service.initialize(run, _manifest())
    service.reserve(
        call,
        request_commitment_sha256=_digest(f"request-{call.ordinal}"),
    )
    service.mark_dispatched(call)
    service.commit(call, _receipt(call))

    connection = sqlite3.connect(journal.database_path)
    try:
        row = connection.execute(
            """
            SELECT receipt_identity_json, receipt_commitment_sha256
            FROM private_provider_results
            """
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert "provider_body" not in row[0]
    assert "result_commitment_sha256" in row[0]
    assert row[1] == _receipt(call).result_commitment_sha256


def test_committed_call_row_without_request_commitment_fails_closed(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    call = _manifest().calls[0]
    service.initialize(run, _manifest())
    service.reserve(
        call,
        request_commitment_sha256=_digest(f"request-{call.ordinal}"),
    )
    service.mark_dispatched(call)
    service.commit(call, _receipt(call))

    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute(
            """
            UPDATE provider_calls
            SET request_commitment_sha256 = NULL
            WHERE run_id = ? AND logical_call_id = ?
            """,
            (run.run_id, call.logical_call_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_call_row_invalid",
    ):
        tuple(journal.iter_calls(run_id=run.run_id))


def test_private_result_idempotency_rejects_receipt_commitment_divergence(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "private"
    journal, service = _service(private_directory)
    run = _run()
    call = _manifest().calls[0]
    receipt = _receipt(call)
    service.initialize(run, _manifest())
    service.reserve(
        call,
        request_commitment_sha256=receipt.request_commitment_sha256,
    )
    service.mark_dispatched(call)
    service.commit(call, receipt)
    states = tuple(journal.iter_calls(run_id=run.run_id))
    state = states[0]
    verified = _ReceiptVerifier().verify(identity=call, receipt=receipt)

    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute(
            """
            UPDATE private_provider_results
            SET receipt_commitment_sha256 = ?
            WHERE run_id = ? AND logical_call_id = ?
            """,
            (_digest("divergent-result"), run.run_id, call.logical_call_id),
        )
        connection.commit()
    finally:
        connection.close()

    with (
        pytest.raises(
            CheckpointJournalError,
            match="checkpoint_journal_private_result_divergent",
        ),
        journal.write_transaction() as transaction,
    ):
        transaction.put_private_provider_result(
            state=state,
            verified_receipt=verified,
        )


def _service(
    private_directory: Path,
) -> tuple[SQLiteCheckpointJournal, PublishableCheckpointJournalService]:
    journal = SQLiteCheckpointJournal(
        private_directory / "checkpoint.db",
        private_directory=private_directory,
    )
    service = PublishableCheckpointJournalService(
        journal=journal,
        signer=HmacSha256JournalSigner(key_id="journal-key-1", secret=b"journal-secret"),
        receipt_verifier=_ReceiptVerifier(),
        external_lifecycle=NullExternalLifecycle(),
    )
    return journal, service


@cache
def _authority() -> ManifestAuthority:
    return ManifestAuthority(
        ordered_cases=tuple(
            ManifestCaseAuthority(
                case_id=f"case-{ordinal}",
                case_alias=f"alias-{ordinal}",
            )
            for ordinal in range(PUBLISHABLE_CASE_COUNT)
        ),
        backend_targets=(
            BackendTargetAuthority(
                backend_role="backend-0",
                backend_target_id="target-0",
                backend_target_commitment_sha256=_digest("target-0"),
            ),
            BackendTargetAuthority(
                backend_role="backend-1",
                backend_target_id="target-1",
                backend_target_commitment_sha256=_digest("target-1"),
            ),
        ),
    )


@cache
def _manifest() -> PublishableEvaluationManifest:
    authority = _authority()
    answers = tuple(
        _identity(
            stage=CallStage.ANSWER,
            ordinal=ordinal,
            case_id=f"case-{ordinal // 2}",
            case_alias=f"alias-{ordinal // 2}",
            backend_role=f"backend-{ordinal % 2}",
            backend_target_id=f"target-{ordinal % 2}",
            backend_target_commitment_sha256=_digest(f"target-{ordinal % 2}"),
        )
        for ordinal in range(PUBLISHABLE_ANSWER_CALL_COUNT)
    )
    judges = tuple(
        _identity(
            stage=CallStage.JUDGE,
            ordinal=PUBLISHABLE_ANSWER_CALL_COUNT + answer.ordinal,
            case_id=answer.case_id,
            case_alias=answer.case_alias,
            backend_role=answer.backend_role,
            backend_target_id=answer.backend_target_id,
            backend_target_commitment_sha256=(answer.backend_target_commitment_sha256),
            depends_on_logical_call_id=answer.logical_call_id,
        )
        for answer in answers
    )
    return PublishableEvaluationManifest(
        authority=authority,
        calls=answers + judges,
    )


def _run() -> PublishableRunIdentity:
    manifest = _manifest()
    return PublishableRunIdentity(
        run_id="run-1",
        profile_id="profile-1",
        profile_commitment_sha256=_digest("profile"),
        dataset_commitment_sha256=_digest("dataset"),
        methodology_commitment_sha256=_digest("methodology"),
        source_commit_sha256=_digest("source"),
        runtime_pin_sha256=_digest("runtime-pin"),
        case_manifest_sha256=manifest.case_manifest_sha256,
        manifest_authority_commitment_sha256=(manifest.manifest_authority_commitment_sha256),
        evaluation_manifest_commitment_sha256=manifest.commitment_sha256,
        signer_key_id="journal-key-1",
    )


def _identity(
    *,
    stage: CallStage,
    ordinal: int,
    case_id: str = "case-0",
    case_alias: str = "alias-0",
    backend_role: str = "backend-0",
    backend_target_id: str = "target-0",
    backend_target_commitment_sha256: str | None = None,
    depends_on_logical_call_id: str | None = None,
) -> LogicalCallIdentity:
    return LogicalCallIdentity(
        run_id="run-1",
        case_id=case_id,
        case_alias=case_alias,
        backend_role=backend_role,
        backend_target_id=backend_target_id,
        backend_target_commitment_sha256=(
            backend_target_commitment_sha256 or _digest(backend_target_id)
        ),
        stage=stage,
        ordinal=ordinal,
        depends_on_logical_call_id=depends_on_logical_call_id,
    )


def _receipt(call: LogicalCallIdentity) -> RuntimeReceipt:
    return RuntimeReceipt(
        run_id=call.run_id,
        logical_call_id=call.logical_call_id,
        request_commitment_sha256=_digest(f"request-{call.ordinal}"),
        provider_receipt_id=f"receipt-{call.ordinal}",
        result_commitment_sha256=_digest(f"result-{call.ordinal}"),
    )


def _committed_state(identity: LogicalCallIdentity) -> ProviderCallState:
    return ProviderCallState(
        identity=identity,
        phase=CallPhase.COMMITTED,
        request_commitment_sha256=_digest(f"request-{identity.ordinal}"),
        receipt=_receipt(identity),
        verifier_key_id="receipt-verifier-1",
        verification_commitment_sha256=_digest("verification"),
    )


def _seed_evaluation_state(
    journal: SQLiteCheckpointJournal,
    manifest: PublishableEvaluationManifest,
    *,
    phase: CallPhase,
    include_private_results: bool,
) -> None:
    signer = HmacSha256JournalSigner(
        key_id="journal-key-1",
        secret=b"journal-secret",
    )
    with journal.write_transaction() as transaction:
        run = transaction.get_run(manifest.run_id)
        assert run is not None
        for identity in manifest.calls:
            request_commitment = _digest(f"request-{identity.ordinal}")
            run = _seed_event(
                transaction,
                run,
                signer=signer,
                event_type="call_reserved",
                logical_call_id=identity.logical_call_id,
                payload={
                    "ordinal": identity.ordinal,
                    "replay_key": identity.replay_key,
                    "stage": identity.stage.value,
                },
            )
            run = _seed_event(
                transaction,
                run,
                signer=signer,
                event_type="request_bound",
                logical_call_id=identity.logical_call_id,
                payload={
                    "ordinal": identity.ordinal,
                    "request_commitment_sha256": request_commitment,
                },
            )
            run = _seed_event(
                transaction,
                run,
                signer=signer,
                event_type="call_dispatched",
                logical_call_id=identity.logical_call_id,
                payload={
                    "ordinal": identity.ordinal,
                    "request_commitment_sha256": request_commitment,
                    "stage": identity.stage.value,
                },
            )
            if phase is CallPhase.DISPATCHED:
                transaction.put_call(
                    ProviderCallState(
                        identity=identity,
                        phase=CallPhase.DISPATCHED,
                        request_commitment_sha256=request_commitment,
                    )
                )
                continue
            state = _committed_state(identity)
            transaction.put_call(state)
            verified = VerifiedRuntimeReceipt(
                receipt=state.receipt,
                verifier_key_id=state.verifier_key_id,
                verification_commitment_sha256=(state.verification_commitment_sha256),
            )
            if include_private_results:
                transaction.put_private_provider_result(
                    state=state,
                    verified_receipt=verified,
                )
            receipt = state.receipt
            assert receipt is not None
            run = _seed_event(
                transaction,
                run,
                signer=signer,
                event_type="call_committed",
                logical_call_id=identity.logical_call_id,
                payload={
                    "ordinal": identity.ordinal,
                    "provider_receipt_id": receipt.provider_receipt_id,
                    "request_commitment_sha256": request_commitment,
                    "result_commitment_sha256": (receipt.result_commitment_sha256),
                    "verifier_key_id": verified.verifier_key_id,
                    "verification_commitment_sha256": (verified.verification_commitment_sha256),
                },
            )
        transaction.put_run(run)


def _seed_event(
    transaction,
    run,
    *,
    signer: HmacSha256JournalSigner,
    event_type: str,
    logical_call_id: str,
    payload: dict[str, object],
):
    event = create_journal_event(
        run_id=run.identity.run_id,
        sequence=run.event_count + 1,
        event_type=event_type,
        logical_call_id=logical_call_id,
        payload=payload,
        predecessor_event_sha256=run.head_event_sha256,
        signer_key_id=signer.key_id,
        sign=signer.sign,
    )
    transaction.append_event(event)
    return replace(
        run,
        event_count=event.sequence,
        head_event_sha256=event.event_sha256,
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[2] / "packages" / "infinity_context_server")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        package_root if not existing else f"{package_root}{os.pathsep}{existing}"
    )
    return environment


class _NoMaterializationIterator:
    def __init__(self, source: Iterator[object]) -> None:
        self._source = source

    def __iter__(self) -> _NoMaterializationIterator:
        return self

    def __next__(self) -> object:
        return next(self._source)

    def __length_hint__(self) -> int:
        raise AssertionError("all-row materialization is forbidden")


class _NoMaterializationTransaction:
    def __init__(self, transaction: object) -> None:
        self._transaction = transaction

    def __getattr__(self, name: str) -> object:
        return getattr(self._transaction, name)

    def iter_calls(self, **kwargs: object) -> Iterator[object]:
        return _NoMaterializationIterator(self._transaction.iter_calls(**kwargs))

    def iter_events(self, **kwargs: object) -> Iterator[object]:
        return _NoMaterializationIterator(self._transaction.iter_events(**kwargs))


class _NoMaterializationJournal:
    def __init__(self, journal: SQLiteCheckpointJournal) -> None:
        self._journal = journal

    @property
    def schema_version(self) -> str:
        return self._journal.schema_version

    @contextmanager
    def write_transaction(self):
        with self._journal.write_transaction() as transaction:
            yield _NoMaterializationTransaction(transaction)

    def iter_pending_lifecycle_events(self, **kwargs: object) -> Iterator[object]:
        return self._journal.iter_pending_lifecycle_events(**kwargs)
