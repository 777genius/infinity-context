from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError, replace
from functools import cache
from hashlib import sha256
from pathlib import Path

import pytest
from infinity_context_server.publishable_checkpoint_journal.crypto import (
    HmacSha256JournalSigner,
)
from infinity_context_server.publishable_checkpoint_journal.domain import (
    CHECKPOINT_JOURNAL_SCHEMA_VERSION,
    PUBLISHABLE_ANSWER_CALL_COUNT,
    PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT,
    PUBLISHABLE_CASE_COUNT,
    PUBLISHABLE_EXTRACTION_CALL_COUNT,
    PUBLISHABLE_JUDGE_CALL_COUNT,
    PUBLISHABLE_MESSAGE_COUNT,
    PUBLISHABLE_TOTAL_CALL_COUNT,
    BackendTargetAuthority,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    LogicalCallIdentity,
    ManifestAuthority,
    ManifestCaseAuthority,
    PublishableEvaluationManifest,
    PublishableRunIdentity,
    RunPhase,
    RuntimeReceipt,
    VerifiedRuntimeReceipt,
    canonical_json,
    create_journal_event,
    sha256_commitment,
)
from infinity_context_server.publishable_checkpoint_journal.manifest_persistence import (
    verify_manifest_authority_stream,
)
from infinity_context_server.publishable_checkpoint_journal.replay import (
    verify_journal_event_chain,
)
from infinity_context_server.publishable_checkpoint_journal.service import (
    PublishableCheckpointJournalService,
)
from infinity_context_server.publishable_checkpoint_journal.sqlite_adapter import (
    SQLiteCheckpointJournal,
)


class _ReceiptVerifier:
    def verify(
        self,
        *,
        identity: LogicalCallIdentity,
        receipt: RuntimeReceipt,
    ) -> VerifiedRuntimeReceipt:
        assert identity.run_id == receipt.run_id
        assert identity.logical_call_id == receipt.logical_call_id
        return VerifiedRuntimeReceipt(
            receipt=receipt,
            verifier_key_id="receipt-verifier-1",
            verification_commitment_sha256=_digest("verification"),
        )


class _Lifecycle:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.delivered: list[str] = []

    def deliver(self, event) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("delivery failed")
        self.delivered.append(event.event_sha256)


def test_run_identity_is_immutable_and_binds_all_authority_inputs() -> None:
    run = _run()

    assert run.expected_case_count == PUBLISHABLE_CASE_COUNT == 1540
    assert run.expected_message_count == PUBLISHABLE_MESSAGE_COUNT == 5882
    assert run.expected_extraction_call_count == PUBLISHABLE_EXTRACTION_CALL_COUNT == 5882
    assert run.expected_answer_judge_call_count == PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT == 6160
    assert run.expected_total_call_count == PUBLISHABLE_TOTAL_CALL_COUNT == 12042
    assert {
        "methodology_commitment_sha256",
        "source_commit_sha256",
        "runtime_pin_sha256",
        "case_manifest_sha256",
        "evaluation_manifest_commitment_sha256",
        "signer_key_id",
        "journal_schema_version",
    } <= set(run.commitment_payload())
    with pytest.raises(FrozenInstanceError):
        run.run_id = "different-run"
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_publishable_commitment_drift",
    ):
        replace(run, expected_case_count=1)


def test_chain_verification_rejects_tamper_gap_reorder_cross_run_and_wrong_key() -> None:
    signer = HmacSha256JournalSigner(key_id="journal-key-1", secret=b"journal-secret")
    events = _events(signer)

    assert _verify(events, signer).head_event_sha256 == events[-1].event_sha256
    assert _verify(events, signer).event_count == 2

    tampered = (
        events[0],
        replace(events[1], payload_json=canonical_json({"state": "tampered"})),
    )
    with pytest.raises(CheckpointJournalError, match="checkpoint_journal_chain_hash_mismatch"):
        _verify(tampered, signer)

    gap = (events[0], replace(events[1], sequence=3))
    with pytest.raises(CheckpointJournalError, match="checkpoint_journal_chain_sequence_gap"):
        _verify(gap, signer)

    with pytest.raises(CheckpointJournalError, match="checkpoint_journal_chain_sequence_gap"):
        _verify(tuple(reversed(events)), signer)

    cross_run = (replace(events[0], run_id="run-2"), events[1])
    with pytest.raises(CheckpointJournalError, match="checkpoint_journal_chain_cross_run"):
        _verify(cross_run, signer)

    wrong_key_id = HmacSha256JournalSigner(key_id="journal-key-2", secret=b"journal-secret")
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_signer_key_mismatch",
    ):
        _verify(events, wrong_key_id)

    wrong_secret = HmacSha256JournalSigner(key_id="journal-key-1", secret=b"wrong-secret")
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_signature_invalid",
    ):
        _verify(events, wrong_secret)


def test_hmac_verifier_rejects_non_ascii_signature_without_raising() -> None:
    signer = HmacSha256JournalSigner(key_id="journal-key-1", secret=b"journal-secret")

    assert signer.verify(b"message", "é" * 64) is False


def test_persisted_manifest_authority_digest_matches_in_memory_authority() -> None:
    authority = _authority()

    persisted = verify_manifest_authority_stream(
        enumerate(authority.ordered_cases),
        enumerate(authority.backend_targets),
    )

    assert persisted.case_manifest_sha256 == authority.case_manifest_sha256
    assert persisted.manifest_authority_commitment_sha256 == authority.commitment_sha256


def test_exact_evaluation_manifest_rejects_out_of_range_and_dependency_drift() -> None:
    manifest = _manifest()

    assert len(manifest.calls) == PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
    assert manifest.commitment_sha256 == sha256_commitment(
        {
            "calls": tuple(call.identity_payload() for call in manifest.calls),
            "case_manifest_sha256": manifest.case_manifest_sha256,
            "manifest_authority_commitment_sha256": (manifest.manifest_authority_commitment_sha256),
            "schema_version": CHECKPOINT_JOURNAL_SCHEMA_VERSION,
        }
    )
    assert tuple(call.ordinal for call in manifest.calls) == tuple(
        range(PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT)
    )
    assert (
        sum(call.stage is CallStage.ANSWER for call in manifest.calls)
        == PUBLISHABLE_ANSWER_CALL_COUNT
    )
    assert (
        sum(call.stage is CallStage.JUDGE for call in manifest.calls)
        == PUBLISHABLE_JUDGE_CALL_COUNT
    )
    assert "EXTRACTION" not in CallStage.__members__
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_call_ordinal_out_of_range",
    ):
        _identity(
            stage=CallStage.ANSWER,
            ordinal=PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT,
        )
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_call_stage_ordinal_invalid",
    ):
        _identity(
            stage=CallStage.JUDGE,
            ordinal=0,
            depends_on_logical_call_id="a" * 64,
        )

    changed = list(manifest.calls)
    changed[0] = replace(changed[0], case_alias="alias-drift")
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_evaluation_manifest_authority_drift",
    ):
        PublishableEvaluationManifest(
            authority=manifest.authority,
            calls=tuple(changed),
        )


def test_identical_replay_is_idempotent_but_manifest_drift_fails_closed(
    tmp_path: Path,
) -> None:
    _, service, _ = _service(tmp_path)
    run = _run()
    answer = _manifest().calls[0]
    service.initialize(run, _manifest())

    reserved = service.reserve(answer)
    assert service.reserve(answer) == reserved
    assert service.verify_chain(run.run_id).event_count == 2

    divergent = replace(answer, case_alias="alias-divergent")
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_manifest_identity_divergent",
    ):
        service.reserve(divergent)


def test_judge_is_blocked_until_the_exact_answer_is_committed(tmp_path: Path) -> None:
    _, service, _ = _service(tmp_path)
    run = _run()
    answer = _manifest().calls[0]
    judge = _manifest().calls[PUBLISHABLE_ANSWER_CALL_COUNT]
    service.initialize(run, _manifest())
    service.reserve(answer)

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_judge_answer_not_committed",
    ):
        service.reserve(judge)

    service.bind_request(answer, _digest("request-0"))
    service.mark_dispatched(answer)
    service.commit(answer, _receipt(answer))
    assert service.reserve(judge).phase is CallPhase.RESERVED
    assert service.bind_request(
        judge,
        _digest(f"request-{judge.ordinal}"),
    ).request_commitment_sha256 == _digest(f"request-{judge.ordinal}")


def test_live_request_binding_is_write_once_and_required_before_dispatch(
    tmp_path: Path,
) -> None:
    _, service, _ = _service(tmp_path)
    run = _run()
    answer = _manifest().calls[0]
    service.initialize(run, _manifest())

    assert not hasattr(answer, "request_commitment_sha256")
    assert service.reserve(answer).request_commitment_sha256 is None
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_dispatch_request_unbound",
    ):
        service.mark_dispatched(answer)

    request_commitment = _digest("request-0")
    bound = service.bind_request(answer, request_commitment)
    assert bound.request_commitment_sha256 == request_commitment
    assert service.bind_request(answer, request_commitment) == bound
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_request_binding_immutable",
    ):
        service.bind_request(answer, _digest("mutated-request"))
    assert service.mark_dispatched(answer).request_commitment_sha256 == request_commitment


def test_commit_rejects_receipt_identity_before_external_verification(tmp_path: Path) -> None:
    _, service, _ = _service(tmp_path)
    call = _manifest().calls[0]
    mismatched = replace(_receipt(call), run_id="other-run")

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_receipt_identity_mismatch",
    ):
        service.commit(call, mismatched)


def test_manifest_rejects_per_case_backend_role_drift() -> None:
    manifest = _manifest()
    changed = list(manifest.calls)
    changed[0] = replace(
        changed[0],
        backend_role="backend-varying",
        backend_target_id="target-varying",
        backend_target_commitment_sha256=_digest("target-varying"),
    )

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_evaluation_manifest_authority_drift",
    ):
        PublishableEvaluationManifest(
            authority=manifest.authority,
            calls=tuple(changed),
        )


def test_provider_receipt_id_cannot_be_reused_across_slots(tmp_path: Path) -> None:
    _, service, _ = _service(tmp_path)
    manifest = _manifest()
    first, second = manifest.calls[:2]
    service.initialize(_run(), manifest)
    for call in (first, second):
        service.reserve(
            call,
            request_commitment_sha256=_digest(f"request-{call.ordinal}"),
        )
        service.mark_dispatched(call)

    first_receipt = _receipt(first)
    service.commit(first, first_receipt)
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_provider_receipt_reused",
    ):
        service.commit(
            second,
            replace(
                _receipt(second),
                provider_receipt_id=first_receipt.provider_receipt_id,
            ),
        )


def test_resume_turns_durable_dispatched_work_into_unknown_and_blocks_retry(
    tmp_path: Path,
) -> None:
    journal, service, _ = _service(tmp_path)
    run = _run()
    call = _manifest().calls[0]
    service.initialize(run, _manifest())
    service.reserve(call)
    service.bind_request(call, _digest("request-0"))
    service.mark_dispatched(call)

    resumed = service.resume(run.run_id)

    assert resumed.run.phase is RunPhase.RECONCILIATION_REQUIRED
    assert resumed.outcome_unknown_count == 1
    assert resumed.newly_outcome_unknown_count == 1
    calls = tuple(journal.iter_calls(run_id=run.run_id))  # Exhaustion closes SQLite.
    assert calls[0].phase is CallPhase.OUTCOME_UNKNOWN
    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_outcome_unknown_retry_blocked",
    ):
        service.mark_dispatched(call)

    assert service.commit(call, _receipt(call)).phase is CallPhase.COMMITTED
    durable_run = journal.load_run(run.run_id)
    assert durable_run is not None
    assert durable_run.phase is RunPhase.ACTIVE
    assert service.resume(run.run_id).outcome_unknown_count == 0


def test_evaluation_seal_rejects_partial_manifest_and_never_claims_whole_run(
    tmp_path: Path,
) -> None:
    _, service, _ = _service(tmp_path)
    run = _run()
    service.initialize(run, _manifest())

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_evaluation_seal_manifest_incomplete",
    ):
        service.seal_evaluation(run.run_id)
    assert not hasattr(service, "seal")


@pytest.mark.parametrize(
    ("table", "column", "value"),
    (
        ("provider_calls", "provider_receipt_id", "tampered-receipt"),
        ("provider_calls", "result_commitment_sha256", "a" * 64),
        ("provider_calls", "verifier_key_id", "tampered-verifier"),
        ("provider_calls", "verification_commitment_sha256", "b" * 64),
        ("private_provider_results", "receipt_identity_json", "{}"),
        ("private_provider_results", "request_commitment_sha256", "c" * 64),
        ("private_provider_results", "receipt_commitment_sha256", "d" * 64),
        ("private_provider_results", "verifier_key_id", "tampered-private-verifier"),
        (
            "private_provider_results",
            "verification_commitment_sha256",
            "e" * 64,
        ),
    ),
)
def test_semantic_replay_rejects_receipt_and_private_binding_tamper(
    tmp_path: Path,
    table: str,
    column: str,
    value: str,
) -> None:
    journal, service, _ = _service(tmp_path)
    run = _run()
    manifest = _manifest()
    call = manifest.calls[0]
    service.initialize(run, manifest)
    service.reserve(
        call,
        request_commitment_sha256=_digest(f"request-{call.ordinal}"),
    )
    service.mark_dispatched(call)
    service.commit(call, _receipt(call))
    connection = sqlite3.connect(journal.database_path)
    try:
        connection.execute(
            f"UPDATE {table} SET {column} = ? WHERE run_id = ?",
            (value, run.run_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        CheckpointJournalError,
        match="checkpoint_journal_chain_run_state_mismatch",
    ):
        service.verify_chain(run.run_id)


def test_lifecycle_outbox_retries_durable_authority_event_after_delivery_failure(
    tmp_path: Path,
) -> None:
    lifecycle = _Lifecycle(failures=1)
    journal, service, _ = _service(tmp_path, lifecycle=lifecycle)
    run = _run()

    with pytest.raises(RuntimeError, match="delivery failed"):
        service.initialize(run, _manifest())

    pending = tuple(journal.iter_pending_lifecycle_events(run_id=run.run_id))
    assert len(pending) == 1
    assert pending[0].event_type == "run_initialized"
    assert journal.load_run(run.run_id) is not None

    service.initialize(run, _manifest())

    assert lifecycle.delivered == [pending[0].event_sha256]
    assert tuple(journal.iter_pending_lifecycle_events(run_id=run.run_id)) == ()
    assert service.retry_pending_notifications(run.run_id) == 0


def _service(
    tmp_path: Path,
    *,
    lifecycle: _Lifecycle | None = None,
) -> tuple[SQLiteCheckpointJournal, PublishableCheckpointJournalService, _Lifecycle]:
    private_directory = tmp_path / "private-journal"
    journal = SQLiteCheckpointJournal(
        private_directory / "checkpoint.db",
        private_directory=private_directory,
    )
    selected_lifecycle = lifecycle or _Lifecycle()
    service = PublishableCheckpointJournalService(
        journal=journal,
        signer=HmacSha256JournalSigner(key_id="journal-key-1", secret=b"journal-secret"),
        receipt_verifier=_ReceiptVerifier(),
        external_lifecycle=selected_lifecycle,
    )
    return journal, service, selected_lifecycle


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


def _events(signer: HmacSha256JournalSigner):
    first = create_journal_event(
        run_id="run-1",
        sequence=1,
        event_type="run_initialized",
        logical_call_id=None,
        payload={"state": "active"},
        predecessor_event_sha256=None,
        signer_key_id=signer.key_id,
        sign=signer.sign,
    )
    second = create_journal_event(
        run_id="run-1",
        sequence=2,
        event_type="call_reserved",
        logical_call_id="a" * 64,
        payload={"state": "reserved"},
        predecessor_event_sha256=first.event_sha256,
        signer_key_id=signer.key_id,
        sign=signer.sign,
    )
    return first, second


def _verify(events, signer: HmacSha256JournalSigner):
    return verify_journal_event_chain(
        events,
        run_id="run-1",
        signer_key_id=signer.key_id,
        verify=signer.verify,
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
