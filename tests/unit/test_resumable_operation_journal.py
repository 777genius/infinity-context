"""Focused characterization of the generic signed operation journal."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pytest
from infinity_context_server.resumable_operation_journal import (
    HmacSha256OperationJournalSigner,
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    OperationRunIdentity,
    OperationRunPhase,
    OperationRunState,
    ResumableOperationJournalService,
    RetryDisposition,
    VerifiedOperationReceipt,
)
from infinity_context_server.resumable_operation_journal.domain import (
    create_operation_event,
)
from infinity_context_server.resumable_operation_journal.service import (
    AllowAllOperationManifestPolicy,
)
from infinity_context_server.resumable_operation_journal.sqlite import (
    SQLiteOperationJournal,
    SQLiteOperationJournalTransaction,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_SECRET = b"operation-journal-test-secret-32-bytes-minimum"


@dataclass
class _Verifier:
    calls: int = 0

    def verify(self, *, identity, receipt):
        self.calls += 1
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id="verifier-v1",
            verification_commitment_sha256=_C,
        )


@dataclass
class _Notifications:
    events: list[str] = field(default_factory=list)
    fail: bool = False

    def deliver(self, event):
        if self.fail:
            raise RuntimeError("offline")
        self.events.append(event.event_sha256)


def _fixture(tmp_path, *, notifications=None):
    private = tmp_path / "journal"
    journal = SQLiteOperationJournal(private / "operations.sqlite3", private_directory=private)
    signer = HmacSha256OperationJournalSigner(key_id="signer-v1", secret=_SECRET)
    operations = (
        LogicalOperationIdentity(
            run_id="run-1",
            operation_key="ingest-1",
            operation_kind="ingest",
            ordinal=0,
            authority_commitment_sha256=_A,
            retry_disposition=RetryDisposition.IDEMPOTENT_REPLAY,
        ),
        LogicalOperationIdentity(
            run_id="run-1",
            operation_key="answer-1",
            operation_kind="provider_answer",
            ordinal=1,
            authority_commitment_sha256=_B,
            retry_disposition=RetryDisposition.QUARANTINE_UNKNOWN,
        ),
    )
    manifest = OperationManifest(operations)
    identity = OperationRunIdentity(
        run_id="run-1",
        operation_namespace="characterization",
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=_C,
        signer_key_id=signer.key_id,
        expected_operation_count=2,
    )
    verifier = _Verifier()
    sink = notifications or _Notifications()
    service = ResumableOperationJournalService(
        journal=journal,
        signer=signer,
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=verifier,
        notifications=sink,
    )
    return service, journal, identity, manifest, operations, verifier, sink


def _receipt(operation, request_hash, receipt_id):
    return OperationReceipt(
        run_id=operation.run_id,
        logical_operation_id=operation.logical_operation_id,
        request_commitment_sha256=request_hash,
        receipt_id=receipt_id,
        result_commitment_sha256=_B,
    )


def _append_signed_event(
    journal,
    identity,
    *,
    event_type,
    logical_operation_id,
    payload,
):
    signer = HmacSha256OperationJournalSigner(key_id="signer-v1", secret=_SECRET)
    with journal.write_transaction() as transaction:
        run = transaction.get_run(identity.run_id)
        assert run is not None
        event = create_operation_event(
            run=run,
            event_type=event_type,
            logical_operation_id=logical_operation_id,
            payload=payload,
            signer_key_id=signer.key_id,
            sign=signer.sign,
        )
        transaction.append_event(event)
        transaction.put_run(
            OperationRunState(
                identity=run.identity,
                phase=run.phase,
                event_count=event.sequence,
                head_event_sha256=event.event_sha256,
            )
        )


def test_crash_resume_replays_only_idempotent_and_quarantines_unknown(tmp_path) -> None:
    service, _, identity, manifest, operations, verifier, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    assert service.prepare_dispatch(operations[0], _A).should_dispatch
    assert service.prepare_dispatch(operations[1], _B).should_dispatch

    resumed = service.resume(identity.run_id)

    assert resumed.replayable_count == 1
    assert resumed.outcome_unknown_count == 1
    assert resumed.run.phase is OperationRunPhase.RECONCILIATION_REQUIRED
    snapshot = service.snapshot(identity.run_id)
    assert (snapshot.pending_count, snapshot.outcome_unknown_count) == (1, 1)
    assert service.prepare_dispatch(operations[0], _A).should_dispatch
    with pytest.raises(OperationJournalError, match="outcome_unknown_quarantined"):
        service.prepare_dispatch(operations[1], _B)

    service.commit(operations[1], _receipt(operations[1], _B, "provider-1"))
    service.commit(operations[0], _receipt(operations[0], _A, "ingest-1"))
    sealed = service.seal(identity.run_id)

    assert sealed.phase is OperationRunPhase.SEALED
    assert service.snapshot(identity.run_id).committed_count == 2
    assert verifier.calls == 2


def test_request_binding_is_write_once_and_dispatch_is_idempotent(tmp_path) -> None:
    service, _, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    first = service.prepare_dispatch(operations[0], _A)
    second = service.prepare_dispatch(operations[0], _A)
    assert first.should_dispatch
    assert not second.should_dispatch
    assert second.state.phase is OperationPhase.DISPATCHED
    with pytest.raises(OperationJournalError, match="request_binding_immutable"):
        service.prepare_dispatch(operations[0], _B)


def test_snapshot_detects_signed_chain_tampering(tmp_path) -> None:
    service, journal, identity, manifest, _, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    connection = sqlite3.connect(journal.database_path)
    connection.execute(
        "UPDATE operation_events SET signature = ? WHERE run_id = ? AND sequence = 1",
        ("tampered", identity.run_id),
    )
    connection.commit()
    connection.close()

    with pytest.raises(OperationJournalError, match="event_chain_invalid"):
        service.snapshot(identity.run_id)


def test_crash_reopen_preserves_exact_v4_schema_and_snapshot(tmp_path) -> None:
    service, journal, identity, manifest, operations, verifier, sink = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)

    reopened = SQLiteOperationJournal(
        journal.database_path, private_directory=journal.private_directory
    )
    recovered = ResumableOperationJournalService(
        journal=reopened,
        signer=HmacSha256OperationJournalSigner(key_id="signer-v1", secret=_SECRET),
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=verifier,
        notifications=sink,
    )

    assert recovered.snapshot(identity.run_id).dispatched_count == 1
    assert recovered.resume(identity.run_id).replayable_count == 1


def test_notification_failure_is_durable_and_retryable(tmp_path) -> None:
    failing = _Notifications(fail=True)
    service, journal, identity, manifest, _, verifier, _ = _fixture(tmp_path, notifications=failing)
    with pytest.raises(RuntimeError, match="offline"):
        service.initialize(identity, manifest)

    healthy = _Notifications()
    recovered = ResumableOperationJournalService(
        journal=journal,
        signer=HmacSha256OperationJournalSigner(key_id="signer-v1", secret=_SECRET),
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=verifier,
        notifications=healthy,
    )
    assert recovered.retry_pending_notifications(identity.run_id) == 1
    assert recovered.retry_pending_notifications(identity.run_id) == 0
    assert len(healthy.events) == 1


def test_v4_adapter_refuses_non_v4_schema_without_migration(tmp_path) -> None:
    private = tmp_path / "journal"
    private.mkdir(mode=0o700)
    database = private / "operations.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '3')")
    connection.commit()
    connection.close()
    database.chmod(0o600)

    with pytest.raises(OperationJournalError, match="schema_layout_invalid"):
        SQLiteOperationJournal(database, private_directory=private)


@pytest.mark.parametrize(
    ("event_type", "logical_index", "payload", "error"),
    (
        (
            "run_initialized",
            None,
            lambda identity, operation: identity.commitment_payload(),
            "initialize_replay_invalid",
        ),
        (
            "operation_dispatched",
            0,
            lambda identity, operation: {
                "ordinal": operation.ordinal,
                "request_commitment_sha256": _A,
                "retry_disposition": operation.retry_disposition.value,
                "unexpected": True,
            },
            "dispatch_replay_invalid",
        ),
        (
            "operation_replay_scheduled",
            1,
            lambda identity, operation: {
                "ordinal": operation.ordinal,
                "reason": "restart_without_verified_receipt",
            },
            "replay_schedule_invalid",
        ),
        (
            "reconciliation_cleared",
            None,
            lambda identity, operation: {
                "resolved_logical_operation_id": operation.logical_operation_id
            },
            "reconciliation_replay_invalid",
        ),
    ),
)
def test_signed_but_semantically_invalid_events_fail_closed(
    tmp_path, event_type, logical_index, payload, error
) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    operation = operations[logical_index or 0]
    if event_type == "operation_replay_scheduled":
        service.prepare_dispatch(operation, _B)
    _append_signed_event(
        journal,
        identity,
        event_type=event_type,
        logical_operation_id=(
            operation.logical_operation_id if logical_index is not None else None
        ),
        payload=payload(identity, operation),
    )

    with pytest.raises(OperationJournalError, match=error):
        service.snapshot(identity.run_id)


def test_replay_rejects_request_rebinding_and_incomplete_seal(tmp_path) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    _append_signed_event(
        journal,
        identity,
        event_type="operation_dispatched",
        logical_operation_id=operations[0].logical_operation_id,
        payload={
            "ordinal": 0,
            "request_commitment_sha256": _B,
            "retry_disposition": RetryDisposition.IDEMPOTENT_REPLAY.value,
        },
    )
    with pytest.raises(OperationJournalError, match="dispatch_replay_invalid"):
        service.snapshot(identity.run_id)

    second = tmp_path / "second"
    second.mkdir()
    service2, journal2, identity2, manifest2, _, _, _ = _fixture(second)
    service2.initialize(identity2, manifest2)
    with journal2.write_transaction() as transaction:
        commitment = transaction.state_commitment(run_id=identity2.run_id)
    _append_signed_event(
        journal2,
        identity2,
        event_type="run_sealed",
        logical_operation_id=None,
        payload={"committed_count": 2, "state_commitment_sha256": commitment},
    )
    with pytest.raises(OperationJournalError, match="seal_replay_invalid"):
        service2.snapshot(identity2.run_id)


def test_replay_rejects_post_seal_events(tmp_path) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    for index, operation in enumerate(operations):
        request_hash = (_A, _B)[index]
        service.prepare_dispatch(operation, request_hash)
        service.commit(operation, _receipt(operation, request_hash, f"receipt-{index}"))
    service.seal(identity.run_id)
    _append_signed_event(
        journal,
        identity,
        event_type="run_initialized",
        logical_operation_id=None,
        payload=identity.commitment_payload(),
    )
    with pytest.raises(OperationJournalError, match="post_seal_event"):
        service.snapshot(identity.run_id)


def test_replay_rejects_commit_of_unknown_before_reconciliation_fence(tmp_path) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    operation = operations[1]
    service.initialize(identity, manifest)
    service.prepare_dispatch(operation, _B)
    _append_signed_event(
        journal,
        identity,
        event_type="operation_outcome_unknown",
        logical_operation_id=operation.logical_operation_id,
        payload={
            "ordinal": operation.ordinal,
            "reason": "restart_without_verified_receipt",
        },
    )
    _append_signed_event(
        journal,
        identity,
        event_type="operation_committed",
        logical_operation_id=operation.logical_operation_id,
        payload={
            "ordinal": operation.ordinal,
            "receipt_id": "too-early",
            "request_commitment_sha256": _B,
            "result_commitment_sha256": _B,
            "verification_commitment_sha256": _C,
            "verifier_key_id": "verifier-v1",
        },
    )
    with pytest.raises(OperationJournalError, match="commit_replay_invalid"):
        service.snapshot(identity.run_id)


@pytest.mark.parametrize("tamper", ("delete", "authority"))
def test_manifest_deletion_or_tamper_fails_closed(tmp_path, tamper) -> None:
    service, journal, identity, manifest, _, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    connection = sqlite3.connect(journal.database_path)
    if tamper == "delete":
        connection.execute(
            "DELETE FROM operation_manifest WHERE run_id = ? AND ordinal = 1",
            (identity.run_id,),
        )
    else:
        connection.execute(
            """UPDATE operation_manifest SET authority_commitment_sha256 = ?
               WHERE run_id = ? AND ordinal = 1""",
            (_A, identity.run_id),
        )
    connection.commit()
    connection.close()
    with pytest.raises(OperationJournalError):
        service.snapshot(identity.run_id)


@pytest.mark.parametrize("tamper", ("delete", "commitment", "verification"))
def test_receipt_deletion_or_tamper_fails_closed(tmp_path, tamper) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    service.commit(operations[0], _receipt(operations[0], _A, "receipt-1"))
    connection = sqlite3.connect(journal.database_path)
    if tamper == "delete":
        connection.execute("DELETE FROM operation_receipts WHERE run_id = ?", (identity.run_id,))
    elif tamper == "commitment":
        connection.execute(
            "UPDATE operation_receipts SET receipt_commitment_sha256 = ? WHERE run_id = ?",
            (_A, identity.run_id),
        )
    else:
        connection.execute(
            "UPDATE operation_receipts SET verification_commitment_sha256 = ? WHERE run_id = ?",
            (_A, identity.run_id),
        )
    connection.commit()
    connection.close()
    with pytest.raises(OperationJournalError):
        service.snapshot(identity.run_id)


def test_late_idempotent_commit_wins_before_redispatch_without_second_call(tmp_path) -> None:
    service, _, identity, manifest, operations, verifier, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    service.resume(identity.run_id)

    receipt = _receipt(operations[0], _A, "late-receipt")
    assert service.commit(operations[0], receipt).phase is OperationPhase.COMMITTED
    assert not service.prepare_dispatch(operations[0], _A).should_dispatch
    assert service.commit(operations[0], receipt).phase is OperationPhase.COMMITTED
    assert verifier.calls == 2
    with pytest.raises(OperationJournalError, match="receipt_replay_divergent"):
        service.commit(operations[0], _receipt(operations[0], _A, "other-receipt"))


def test_late_idempotent_commit_is_accepted_after_redispatch(tmp_path) -> None:
    service, _, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    service.resume(identity.run_id)
    assert service.prepare_dispatch(operations[0], _A).should_dispatch
    assert (
        service.commit(operations[0], _receipt(operations[0], _A, "late-after-redispatch")).phase
        is OperationPhase.COMMITTED
    )
    assert service.snapshot(identity.run_id).committed_count == 1


def test_signed_late_commit_is_fenced_while_run_requires_reconciliation(tmp_path) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    service.prepare_dispatch(operations[1], _B)

    resumed = service.resume(identity.run_id)
    assert resumed.run.phase is OperationRunPhase.RECONCILIATION_REQUIRED
    _append_signed_event(
        journal,
        identity,
        event_type="operation_committed",
        logical_operation_id=operations[0].logical_operation_id,
        payload={
            "ordinal": operations[0].ordinal,
            "receipt_id": "late-while-quarantined",
            "request_commitment_sha256": _A,
            "result_commitment_sha256": _B,
            "verification_commitment_sha256": _C,
            "verifier_key_id": "verifier-v1",
        },
    )

    with pytest.raises(OperationJournalError, match="commit_replay_invalid"):
        service.snapshot(identity.run_id)


def test_idempotent_commit_drains_durable_notification_outbox(tmp_path) -> None:
    sink = _Notifications()
    service, _, identity, manifest, operations, _, _ = _fixture(tmp_path, notifications=sink)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[1], _B)
    sink.fail = True
    with pytest.raises(RuntimeError, match="offline"):
        service.resume(identity.run_id)
    receipt = _receipt(operations[1], _B, "reconciled")
    with pytest.raises(RuntimeError, match="offline"):
        service.commit(operations[1], receipt)

    sink.fail = False
    assert service.commit(operations[1], receipt).phase is OperationPhase.COMMITTED
    assert service.retry_pending_notifications(identity.run_id) == 0
    assert len(sink.events) == 3


def test_notification_batches_are_bounded_and_materialized_before_delivery(tmp_path) -> None:
    sink = _Notifications()
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path, notifications=sink)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[1], _B)
    sink.fail = True
    with pytest.raises(RuntimeError, match="offline"):
        service.resume(identity.run_id)
    sink.fail = False

    pending = journal.iter_pending_notifications(run_id=identity.run_id, batch_size=1)
    assert type(pending) is type(iter(()))
    first = tuple(pending)
    assert len(first) == 1
    assert len(tuple(journal.iter_pending_notifications(run_id=identity.run_id, batch_size=1))) == 1


def test_hmac_verifier_rejects_non_ascii_signature_without_raising() -> None:
    signer = HmacSha256OperationJournalSigner(key_id="signer-v1", secret=_SECRET)

    assert signer.verify(b"message", "snowman-\u2603") is False


def test_resume_of_sealed_run_still_drains_pending_notification(tmp_path) -> None:
    sink = _Notifications()
    service, _, identity, manifest, operations, _, _ = _fixture(tmp_path, notifications=sink)
    service.initialize(identity, manifest)
    for operation, request_hash in zip(operations, (_A, _B), strict=True):
        service.prepare_dispatch(operation, request_hash)
        service.commit(
            operation,
            _receipt(operation, request_hash, f"receipt-{operation.ordinal}"),
        )
    sink.fail = True
    with pytest.raises(RuntimeError, match="offline"):
        service.seal(identity.run_id)

    sink.fail = False
    resumed = service.resume(identity.run_id)
    assert resumed.run.phase is OperationRunPhase.SEALED
    assert service.retry_pending_notifications(identity.run_id) == 0
    assert len(sink.events) == 2


def test_invalid_notification_batch_is_rejected_before_connection(tmp_path, monkeypatch) -> None:
    _, journal, _, _, _, _, _ = _fixture(tmp_path)

    def unexpected_connect():
        raise AssertionError("invalid batch must not open SQLite")

    monkeypatch.setattr(journal, "_connect", unexpected_connect)
    with pytest.raises(ValueError, match="batch_size"):
        journal.iter_pending_notifications(run_id="run-1", batch_size=0)


@pytest.mark.parametrize(
    "method_name",
    ("iter_manifest", "iter_operations", "iter_events", "iter_verified_receipts"),
)
def test_invalid_transaction_batch_is_rejected_before_query(method_name) -> None:
    class _QueryTrap:
        def execute(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("invalid batch must not query SQLite")

    transaction = SQLiteOperationJournalTransaction(_QueryTrap())
    iterator = getattr(transaction, method_name)(run_id="run-1", batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(iterator)


class _ConnectionProbe:
    def __init__(self, connection) -> None:
        self._connection = connection
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def test_connect_closes_handle_when_file_security_check_fails(tmp_path, monkeypatch) -> None:
    _, journal, _, _, _, _, _ = _fixture(tmp_path)
    probe = _ConnectionProbe(journal._open_connection())
    monkeypatch.setattr(journal, "_open_connection", lambda: probe)

    def fail_security() -> None:
        raise OperationJournalError("injected_file_security_failure")

    monkeypatch.setattr(journal, "_secure_files", fail_security)
    with pytest.raises(OperationJournalError, match="injected_file_security_failure"):
        journal._connect()
    assert probe.closed


@pytest.mark.parametrize("flow", ("write", "notifications", "initialize"))
def test_connection_is_closed_before_post_operation_security_check(
    tmp_path, monkeypatch, flow
) -> None:
    _, journal, _, _, _, _, _ = _fixture(tmp_path)
    probe = _ConnectionProbe(journal._open_connection())
    if flow == "initialize":
        monkeypatch.setattr(journal, "_open_connection", lambda: probe)
    else:
        monkeypatch.setattr(journal, "_connect", lambda: probe)

    def assert_closed_then_fail() -> None:
        assert probe.closed
        raise OperationJournalError("injected_post_close_security_failure")

    monkeypatch.setattr(journal, "_secure_files", assert_closed_then_fail)
    with pytest.raises(OperationJournalError, match="injected_post_close_security_failure"):
        if flow == "write":
            with journal.write_transaction():
                pass
        elif flow == "notifications":
            journal.iter_pending_notifications(run_id="run-1")
        else:
            journal._initialize_schema()


@pytest.mark.parametrize(
    "column",
    (
        "request_commitment_sha256",
        "receipt_id",
        "result_commitment_sha256",
        "verifier_key_id",
        "verification_commitment_sha256",
    ),
)
def test_committed_state_with_null_receipt_column_fails_closed(tmp_path, column) -> None:
    service, journal, identity, manifest, operations, _, _ = _fixture(tmp_path)
    service.initialize(identity, manifest)
    service.prepare_dispatch(operations[0], _A)
    service.commit(operations[0], _receipt(operations[0], _A, "receipt-1"))
    connection = sqlite3.connect(journal.database_path)
    connection.execute(
        f"UPDATE operation_states SET {column} = NULL WHERE run_id = ?",
        (identity.run_id,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(OperationJournalError, match="state_row_tampered"):
        service.snapshot(identity.run_id)
