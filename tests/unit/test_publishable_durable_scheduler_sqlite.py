from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_server.publishable_durable_scheduler import (
    LOCOMO_EXTRACTION_OPERATION_COUNT,
    LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PublishableResumableEvaluationRunner,
    SchedulerCallStage,
    SchedulerDispatchOutcome,
    SchedulerDispatchReadback,
    SchedulerDispatchReadbackDisposition,
    SchedulerDispatchReceipt,
    SchedulerExtractionTerminalEvidence,
    SchedulerRenderedRequest,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerStepDisposition,
    authenticate_extraction_terminal,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    bound_request_sha256,
    dispatch_intent_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteError,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_rows import (
    call_values,
    run_values,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerRunPhase,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)
from publishable_durable_scheduler_test_support import built_runs, sha

_SECRET = b"s" * 32
_RUNNER_SECRET = b"resumable-runner-test-secret-key!"
_RENDERER_POLICY = sha("runner-renderer-policy")
_PRIVATE_ANSWER_POLICY = sha("runner-private-answer-policy")
_EXTRACTION_READ_POLICY = sha("runner-extraction-read-policy")
_READBACK_POLICY = sha("runner-outcome-readback-policy")
_DEFAULT_READER = object()


@pytest.fixture(scope="module")
def prepared():
    suite, locomo, _ = built_runs()
    return suite, *locomo


def _store(tmp_path: Path, prepared, *, secret: bytes = _SECRET):
    suite, run, manifest = prepared
    private = tmp_path / "private"
    return SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=secret,
        suite=suite,
        run=run,
        manifest=manifest,
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


class _RunnerClock:
    def __init__(self, value: int = 2_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class _RunnerRenderer:
    def __init__(
        self,
        *,
        dependency_mode: str = "exact",
        renderer_policy_sha256: str = _RENDERER_POLICY,
    ) -> None:
        self.contexts = []
        self.dependency_mode = dependency_mode
        self._renderer_policy_sha256 = renderer_policy_sha256

    @property
    def renderer_policy_sha256(self) -> str:
        return self._renderer_policy_sha256

    @property
    def private_answer_policy_sha256(self) -> str:
        return _PRIVATE_ANSWER_POLICY

    def render(self, context) -> SchedulerRenderedRequest:
        self.contexts.append(context)
        dependency_sha256 = None
        if context.call.stage is SchedulerCallStage.JUDGE:
            expected = _runner_ciphertext(context.call.depends_on_logical_call_id or "")
            if self.dependency_mode == "ignored":
                dependency_sha256 = context.dependency_answer_ciphertext_sha256
            elif self.dependency_mode == "substituted":
                assert context.dependency_answer_ciphertext == expected
                dependency_sha256 = hashlib.sha256(b"substituted-ciphertext").hexdigest()
            else:
                assert context.dependency_answer_ciphertext == expected
                dependency_sha256 = hashlib.sha256(expected).hexdigest()
        else:
            assert context.dependency_answer_ciphertext is None
        return SchedulerRenderedRequest(
            renderer_policy_sha256=self.renderer_policy_sha256,
            private_answer_policy_sha256=self.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=dependency_sha256,
            payload=(
                f"request:{context.call.logical_call_id}:dependency:{dependency_sha256}"
            ).encode(),
        )


class _RunnerVerifier:
    def __init__(self, policy_sha256: str) -> None:
        self._policy_sha256 = policy_sha256
        self.calls = 0

    @property
    def policy_sha256(self) -> str:
        return self._policy_sha256

    def verify(self, *, receipt, envelope) -> bool:
        self.calls += 1
        assert receipt.intent_sha256 == envelope.intent_sha256
        return True


class _RunnerBoundary:
    def __init__(
        self,
        bridge_boot_authority_sha256: str,
        *,
        request_mismatch: bool = False,
        token_overage: bool = False,
        crash: bool = False,
    ) -> None:
        self._bridge = bridge_boot_authority_sha256
        self.request_mismatch = request_mismatch
        self.token_overage = token_overage
        self.crash = crash
        self.calls = 0
        self.envelopes = []

    @property
    def bridge_boot_authority_sha256(self) -> str:
        return self._bridge

    def preflight(self, *, payload: bytes, token_ceiling: int) -> None:
        assert payload
        assert token_ceiling > 0

    def invoke_once(self, envelope) -> SchedulerDispatchOutcome:
        self.calls += 1
        self.envelopes.append(envelope)
        if self.crash:
            raise KeyboardInterrupt
        return _runner_outcome(
            envelope,
            request_mismatch=self.request_mismatch,
            token_overage=self.token_overage,
        )


def _runner_outcome(
    envelope,
    *,
    request_mismatch: bool = False,
    token_overage: bool = False,
) -> SchedulerDispatchOutcome:
    ciphertext = (
        _runner_ciphertext(envelope.logical_call_id)
        if envelope.stage is SchedulerCallStage.ANSWER
        else None
    )
    return SchedulerDispatchOutcome(
        receipt=SchedulerDispatchReceipt(
            suite_authority_sha256=envelope.suite_authority_sha256,
            run_authority_sha256=envelope.run_authority_sha256,
            bridge_boot_authority_sha256=envelope.bridge_boot_authority_sha256,
            logical_call_id=envelope.logical_call_id,
            stage=envelope.stage,
            renderer_policy_sha256=envelope.renderer_policy_sha256,
            private_answer_policy_sha256=envelope.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=(envelope.dependency_answer_ciphertext_sha256),
            request_sha256=(
                sha("mismatched-request") if request_mismatch else envelope.request_sha256
            ),
            intent_sha256=envelope.intent_sha256,
            private_output_ciphertext_sha256=(
                hashlib.sha256(ciphertext).hexdigest() if ciphertext is not None else None
            ),
            completion_tokens=(envelope.token_ceiling + 1 if token_overage else 1),
            charged_tokens=(envelope.token_ceiling + 1 if token_overage else 1),
            attestation=f"receipt:{envelope.logical_call_id}".encode(),
        ),
        private_output_ciphertext=ciphertext,
    )


def _runner_ciphertext(logical_call_id: str) -> bytes:
    return f"encrypted:{logical_call_id}".encode()


class _RunnerExtractionReader:
    def __init__(self, terminals, *, policy_sha256: str = _EXTRACTION_READ_POLICY) -> None:
        self.terminals = terminals
        self._policy_sha256 = policy_sha256

    @property
    def read_policy_sha256(self) -> str:
        return self._policy_sha256

    def read_terminal(self, *, run):
        return next(
            (
                item
                for item in self.terminals
                if getattr(item, "run_authority_sha256", None) == run.commitment_sha256
            ),
            None,
        )


class _RawExtractionReader:
    read_policy_sha256 = _EXTRACTION_READ_POLICY

    def __init__(self, evidence) -> None:
        self.evidence = evidence

    def read_terminal(self, *, run):
        return self.evidence[run.run_index]


class _RunnerReconciliation:
    readback_policy_sha256 = _READBACK_POLICY

    def __init__(
        self,
        disposition: SchedulerDispatchReadbackDisposition,
        *,
        authenticated: bool = True,
    ) -> None:
        self.disposition = disposition
        self.authenticated = authenticated
        self.calls = 0

    def lookup(self, envelope) -> SchedulerDispatchReadback:
        self.calls += 1
        outcome = (
            _runner_outcome(envelope)
            if self.disposition is SchedulerDispatchReadbackDisposition.FOUND
            else None
        )
        return SchedulerDispatchReadback(
            disposition=self.disposition,
            readback_policy_sha256=self.readback_policy_sha256,
            request_sha256=envelope.request_sha256,
            intent_sha256=envelope.intent_sha256,
            outcome=outcome,
            attestation=f"readback:{envelope.intent_sha256}".encode(),
        )

    def authenticate(self, *, readback, envelope) -> bool:
        return self.authenticated and readback.intent_sha256 == envelope.intent_sha256


def _runner_specs(tmp_path: Path, prepared):
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    suite, locomo, longmemeval = prepared
    return suite, tuple(
        SchedulerRunStoreSpec(
            run=run,
            manifest=manifest,
            database_path=tmp_path / name / "scheduler.sqlite3",
            private_directory=tmp_path / name,
            authentication_secret=_RUNNER_SECRET,
        )
        for name, (run, manifest) in (
            ("locomo", locomo),
            ("longmemeval", longmemeval),
        )
    )


def _runner_open(
    tmp_path: Path,
    prepared,
    *,
    boundary=None,
    clock=None,
    renderer=None,
    extraction_reader=_DEFAULT_READER,
    reconciliation=None,
):
    suite, specs = _runner_specs(tmp_path, prepared)
    selected = boundary or _RunnerBoundary(suite.bridge_boot.commitment_sha256)
    selected_renderer = renderer or _RunnerRenderer()
    selected_reader = (
        _RunnerExtractionReader(_runner_authenticated_terminals(suite, specs))
        if extraction_reader is _DEFAULT_READER
        else extraction_reader
    )
    verifier = _RunnerVerifier(suite.bridge_boot.receipt_verifier_policy_sha256)
    runner = PublishableResumableEvaluationRunner.open(
        suite=suite,
        run_stores=specs,
        request_renderer=selected_renderer,
        boundary=selected,
        receipt_verifier=verifier,
        extraction_terminal_reader=selected_reader,
        reconciliation=reconciliation,
        clock=clock or _RunnerClock(),
        lease_id_factory=lambda: "lease-fixed",
        lease_duration_ms=1_000,
    )
    return runner, selected, selected_renderer, verifier


def _seed_runner_intent(
    runner: PublishableResumableEvaluationRunner,
    *,
    lease_id: str = "foreign-worker",
    lease_expires_unix_ms: int = 3_000,
):
    entry = runner._entries[0]
    call = entry.manifest.shards[0].calls[0]
    rendered = runner._render_request(entry, call)
    request_sha256 = bound_request_sha256(
        suite_authority_sha256=runner._suite.commitment_sha256,
        run_authority_sha256=entry.run.commitment_sha256,
        bridge_boot_authority_sha256=runner._suite.bridge_boot.commitment_sha256,
        renderer_policy_sha256=rendered.renderer_policy_sha256,
        private_answer_policy_sha256=rendered.private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=rendered.dependency_answer_ciphertext_sha256,
        call=call,
        payload=rendered.payload,
    )
    leased = entry.store.acquire_lease(
        call.logical_call_id,
        now_unix_ms=2_000,
        lease_id=lease_id,
        lease_expires_unix_ms=lease_expires_unix_ms,
    )
    entry.store.bind_request(
        call.logical_call_id,
        lease_id=lease_id,
        request_sha256=request_sha256,
    )
    intent_sha256 = dispatch_intent_sha256(
        envelope_binding={
            "attempt_count": leased.attempt_count,
            "bridge_boot_authority_sha256": runner._suite.bridge_boot.commitment_sha256,
            "dispatch_deadline_unix_ms": entry.run.binding.limits.dispatch_deadline_unix_ms,
            "dependency_answer_ciphertext_sha256": (rendered.dependency_answer_ciphertext_sha256),
            "lease_id": lease_id,
            "logical_call_id": call.logical_call_id,
            "private_answer_policy_sha256": rendered.private_answer_policy_sha256,
            "renderer_policy_sha256": rendered.renderer_policy_sha256,
            "request_sha256": request_sha256,
            "run_authority_sha256": entry.run.commitment_sha256,
            "suite_authority_sha256": runner._suite.commitment_sha256,
            "token_ceiling": call.token_ceiling,
        }
    )
    entry.store.record_dispatch_intent(
        call.logical_call_id,
        lease_id=lease_id,
        now_unix_ms=2_100,
        bridge_boot_authority_sha256=runner._suite.bridge_boot.commitment_sha256,
        intent_sha256=intent_sha256,
    )
    return call


def test_initial_manifest_reopen_and_bounded_queries(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    database = tmp_path / "private" / "scheduler.sqlite3"
    assert store.paid_go_ready is False
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert len(store.read_calls(after_ordinal=-1, limit=257)) == 257
    assert tuple(item.event_kind for item in store.read_events(after_event_id=-1, limit=257)) == (
        "manifest_initialized",
    )
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run() == store.read_run()
    with pytest.raises(SchedulerSQLiteError, match="query_invalid"):
        store.read_calls(after_ordinal=-1, limit=258)
    with pytest.raises(SchedulerSQLiteError, match="authentication"):
        _store(tmp_path, prepared, secret=b"x" * 32)


def test_longmemeval_exact_run_reopens_and_cross_run_is_rejected(tmp_path: Path) -> None:
    suite, locomo, longmemeval = built_runs()
    run, manifest = longmemeval
    private = tmp_path / "private"
    store = SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )
    observed = []
    after = -1
    while True:
        page = store.read_calls(after_ordinal=after, limit=257)
        observed.extend(page)
        if len(page) < 257:
            break
        after = page[-1].ordinal
    assert len(observed) == 2_000
    assert observed[-1].ordinal == 1_999
    reopened = SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )
    assert reopened.read_run().expected_call_count == 2_000
    with pytest.raises(SchedulerSQLiteError, match="manifest_drift"):
        SQLiteDurableSchedulerStore(
            private / "scheduler.sqlite3",
            private_directory=private,
            authentication_secret=_SECRET,
            suite=suite,
            run=locomo[0],
            manifest=locomo[1],
        )


def test_atomic_answer_commit_persists_only_opaque_ciphertext(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    first = store.read_calls(after_ordinal=-1, limit=1)[0]
    _intent(store, first.logical_call_id)
    ciphertext = os.urandom(96)
    committed = store.commit_outcome(
        first.logical_call_id,
        intent_sha256=sha("intent"),
        receipt_sha256=sha("receipt"),
        completion_tokens=7,
        charged_tokens=17,
        answer_ciphertext=ciphertext,
    )
    assert committed.phase is SchedulerCallPhase.COMMITTED
    assert store.read_private_answer_ciphertext(first.logical_call_id) == ciphertext
    assert store.read_run().consumed_tokens == 7
    assert tuple(item.event_kind for item in store.read_events(after_event_id=-1, limit=257)) == (
        "manifest_initialized",
        "lease_acquired",
        "request_bound",
        "dispatch_intent_recorded",
        "outcome_committed",
    )
    reopened = _store(tmp_path, prepared)
    assert reopened.read_private_answer_ciphertext(first.logical_call_id) == ciphertext

    connection = sqlite3.connect(tmp_path / "private" / "scheduler.sqlite3")
    try:
        event_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(scheduler_events)")
        )
        assert not {"body", "payload", "plaintext", "ciphertext"}.intersection(event_columns)
    finally:
        connection.close()


def test_outcome_unknown_freeze_survives_restart(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    first, _, second = store.read_calls(after_ordinal=-1, limit=3)
    _intent(store, first.logical_call_id)
    unknown = store.record_ambiguous_outcome(
        first.logical_call_id,
        intent_sha256=sha("intent"),
        ambiguity_sha256=sha("ambiguous"),
    )
    assert unknown.phase is SchedulerCallPhase.OUTCOME_UNKNOWN
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    assert reopened.read_run().inflight_logical_call_id is None
    assert reopened.read_run().burned_tokens == first.token_ceiling
    with pytest.raises(SchedulerSQLiteError, match="lease_acquire"):
        reopened.acquire_lease(
            second.logical_call_id,
            now_unix_ms=2_500,
            lease_id="forbidden",
            lease_expires_unix_ms=3_500,
        )


def test_no_intent_reclaim_is_durable_and_releases_single_inflight(
    tmp_path: Path, prepared
) -> None:
    store = _store(tmp_path, prepared)
    first = store.read_calls(after_ordinal=-1, limit=1)[0]
    store.acquire_lease(
        first.logical_call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    store.bind_request(
        first.logical_call_id,
        lease_id="lease-1",
        request_sha256=sha("request"),
    )
    reclaimed = store.reclaim_expired_no_intent_lease(
        first.logical_call_id,
        now_unix_ms=3_000,
        lease_id="lease-1",
    )
    assert reclaimed.phase is SchedulerCallPhase.PLANNED
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().reserved_tokens == 0
    assert reopened.read_run().inflight_logical_call_id is None
    assert reopened.read_call(first.logical_call_id).attempt_count == 1


def test_concurrent_stores_preserve_exact_single_inflight(tmp_path: Path, prepared) -> None:
    first_store = _store(tmp_path, prepared)
    second_store = _store(tmp_path, prepared)
    first, _, second = first_store.read_calls(after_ordinal=-1, limit=3)
    barrier = Barrier(2)

    def acquire(store: SQLiteDurableSchedulerStore, logical_call_id: str, lease_id: str) -> str:
        barrier.wait()
        try:
            store.acquire_lease(
                logical_call_id,
                now_unix_ms=2_000,
                lease_id=lease_id,
                lease_expires_unix_ms=3_000,
            )
        except SchedulerSQLiteError as error:
            return error.code
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(acquire, first_store, first.logical_call_id, "first"),
                executor.submit(acquire, second_store, second.logical_call_id, "second"),
            )
        )
    assert results.count("ok") == 1
    assert sum("lease_acquire_invalid" in item for item in results) == 1
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().inflight_logical_call_id in {
        first.logical_call_id,
        second.logical_call_id,
    }


def test_runner_answer_before_judge_and_resume_never_redispatches(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    runner, first_boundary, renderer, _ = _runner_open(tmp_path, prepared)
    first = runner.run_next()
    second = runner.run_next()
    assert first.disposition is second.disposition is SchedulerStepDisposition.COMMITTED
    assert [item.stage for item in first_boundary.envelopes] == [
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
    ]
    assert renderer.contexts[1].dependency_answer_ciphertext == _runner_ciphertext(
        first.logical_call_id or ""
    )

    replay = _RunnerBoundary(runner._suite.bridge_boot.commitment_sha256)
    resumed, _, _, _ = _runner_open(tmp_path, prepared, boundary=replay)
    third = resumed.run_next()
    assert third.logical_call_id not in {first.logical_call_id, second.logical_call_id}
    assert replay.calls == 1

    _seed_runner_committed(resumed._entries[0].store)
    cross_boundary = _RunnerBoundary(runner._suite.bridge_boot.commitment_sha256)
    cross_run, _, _, _ = _runner_open(tmp_path, prepared, boundary=cross_boundary)
    result = cross_run.run_next()
    assert result.run_id == prepared[2][0].binding.run_id
    assert cross_boundary.calls == 1


def test_runner_committed_replay_makes_zero_extra_provider_calls(tmp_path: Path) -> None:
    prepared = built_runs()
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    for entry in runner._entries:
        _seed_runner_committed(entry.store)
    replay = _RunnerBoundary(runner._suite.bridge_boot.commitment_sha256)
    resumed, _, _, _ = _runner_open(tmp_path, prepared, boundary=replay)
    assert resumed.run_next().disposition is SchedulerStepDisposition.EVALUATION_COMPLETE
    assert resumed.committed_call_count() == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    assert replay.calls == 0


def test_runner_unexpired_foreign_lease_blocks_without_status_or_dispatch(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    suite = prepared[0]
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    call = _seed_runner_intent(runner)
    reconciliation = _RunnerReconciliation(SchedulerDispatchReadbackDisposition.FOUND)
    boundary = _RunnerBoundary(suite.bridge_boot.commitment_sha256)
    resumed, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        boundary=boundary,
        clock=_RunnerClock(2_999),
        reconciliation=reconciliation,
    )
    result = resumed.run_next()
    assert result.disposition is SchedulerStepDisposition.BLOCKED
    assert result.logical_call_id == call.logical_call_id
    assert reconciliation.calls == boundary.calls == 0


def test_runner_expired_known_outcome_commits_from_status_without_dispatch(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    suite = prepared[0]
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    call = _seed_runner_intent(runner)
    reconciliation = _RunnerReconciliation(SchedulerDispatchReadbackDisposition.FOUND)
    boundary = _RunnerBoundary(suite.bridge_boot.commitment_sha256)
    resumed, _, _, verifier = _runner_open(
        tmp_path,
        prepared,
        boundary=boundary,
        clock=_RunnerClock(3_000),
        reconciliation=reconciliation,
    )
    committed = resumed._entries[0].store.read_call(call.logical_call_id)
    assert committed.phase is SchedulerCallPhase.COMMITTED
    assert committed.charged_tokens == 1
    assert reconciliation.calls == verifier.calls == 1
    assert boundary.calls == 0

    replay = _RunnerReconciliation(SchedulerDispatchReadbackDisposition.AMBIGUOUS)
    reopened, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        boundary=boundary,
        clock=_RunnerClock(3_001),
        reconciliation=replay,
    )
    assert reopened._entries[0].store.read_call(call.logical_call_id) == committed
    assert replay.calls == boundary.calls == 0


def test_runner_expired_unknown_freezes_and_reopen_never_redispatches(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    suite = prepared[0]
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    _seed_runner_intent(runner)
    reconciliation = _RunnerReconciliation(SchedulerDispatchReadbackDisposition.AMBIGUOUS)

    replay = _RunnerBoundary(suite.bridge_boot.commitment_sha256)
    resumed, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        boundary=replay,
        clock=_RunnerClock(3_000),
        reconciliation=reconciliation,
    )
    assert resumed._entries[0].store.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    assert resumed.run_next().disposition is SchedulerStepDisposition.FROZEN_OUTCOME_UNKNOWN
    assert reconciliation.calls == 1
    assert replay.calls == 0


def test_runner_receipt_request_mismatch_is_rejected_and_frozen(tmp_path: Path) -> None:
    prepared = built_runs()
    suite = prepared[0]
    boundary = _RunnerBoundary(suite.bridge_boot.commitment_sha256, request_mismatch=True)
    runner, _, _, verifier = _runner_open(tmp_path, prepared, boundary=boundary)
    with pytest.raises(SchedulerRunnerError, match="receipt_binding_invalid"):
        runner.run_next()
    assert boundary.calls == 1
    assert verifier.calls == 0
    assert runner._entries[0].store.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN


def test_runner_token_overage_and_deadline_enforcement(tmp_path: Path) -> None:
    prepared = built_runs()
    suite = prepared[0]
    overage = _RunnerBoundary(suite.bridge_boot.commitment_sha256, token_overage=True)
    runner, _, _, _ = _runner_open(tmp_path / "tokens", prepared, boundary=overage)
    with pytest.raises(SchedulerRunnerError, match="receipt_binding_invalid"):
        runner.run_next()
    assert overage.calls == 1
    assert runner._entries[0].store.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN

    late = _RunnerBoundary(suite.bridge_boot.commitment_sha256)
    deadline = suite.ordered_runs[0].limits.dispatch_deadline_unix_ms
    expired, _, _, _ = _runner_open(
        tmp_path / "deadline",
        prepared,
        boundary=late,
        clock=_RunnerClock(deadline),
    )
    assert expired.run_next().disposition is SchedulerStepDisposition.DEADLINE_EXHAUSTED
    assert late.calls == 0


def test_runner_seal_rejects_missing_raw_forged_or_divergent_extraction(
    tmp_path: Path,
) -> None:
    prepared = built_runs()
    runner, _, _, _ = _runner_open(tmp_path, prepared, extraction_reader=None)
    for entry in runner._entries:
        _seed_runner_committed(entry.store)
    with pytest.raises(SchedulerRunnerError, match="extraction_evidence_missing"):
        runner.seal()

    evidence = _runner_extraction_evidence(runner)
    raw, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        extraction_reader=_RawExtractionReader(evidence),
    )
    with pytest.raises(SchedulerRunnerError, match="extraction_evidence_unauthenticated"):
        raw.seal()

    suite, specs = _runner_specs(tmp_path, prepared)
    authenticated = _runner_authenticated_terminals(suite, specs)
    object.__setattr__(authenticated[0], "commitment_sha256", sha("forged-capability"))
    forged, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        extraction_reader=_RunnerExtractionReader(authenticated),
    )
    with pytest.raises(SchedulerRunnerError, match="extraction_evidence_unauthenticated"):
        forged.seal()

    divergent_context = replace(
        evidence[1].context,
        binding_commitment_sha256=sha("divergent-binding"),
    )
    divergent_evidence = SchedulerExtractionTerminalEvidence(
        divergent_context,
        _runner_terminal(divergent_context),
    )
    valid = _runner_authenticated_terminals(suite, specs)
    divergent_reader = _RunnerExtractionReader(
        (
            valid[0],
            authenticate_extraction_terminal(
                run_authority_sha256=specs[1].run.commitment_sha256,
                read_policy_sha256=_EXTRACTION_READ_POLICY,
                evidence=divergent_evidence,
                authentication_secret=specs[1].authentication_secret,
            ),
        )
    )
    divergent, _, _, _ = _runner_open(
        tmp_path,
        prepared,
        extraction_reader=divergent_reader,
    )
    with pytest.raises(SchedulerRunnerError, match="extraction_evidence_divergent"):
        divergent.seal()
    assert all(
        entry.store.read_run().phase is SchedulerRunPhase.ACTIVE for entry in divergent._entries
    )


def test_runner_suite_seal_crash_reopen_exact_replay_and_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = built_runs()
    runner, _, _, _ = _runner_open(tmp_path, prepared)
    for entry in runner._entries:
        _seed_runner_committed(entry.store)

    def crash_before_sidecar(_store, _seal):
        raise KeyboardInterrupt

    with monkeypatch.context() as patcher:
        patcher.setattr(SQLiteSchedulerSuiteSealStore, "persist_exact", crash_before_sidecar)
        with pytest.raises(KeyboardInterrupt):
            runner.seal()
    assert all(
        entry.store.read_run().phase is SchedulerRunPhase.SEALED for entry in runner._entries
    )

    reopened, replay, _, _ = _runner_open(
        tmp_path,
        prepared,
        boundary=_RunnerBoundary(runner._suite.bridge_boot.commitment_sha256),
    )
    assert reopened.run_next().disposition is SchedulerStepDisposition.EVALUATION_COMPLETE
    seal = reopened.seal()
    assert seal.case_count == 2_040
    assert seal.evaluation_call_count == 8_160
    assert seal.extraction_operation_count == 5_882 + 124_344
    assert reopened.run_next().disposition is SchedulerStepDisposition.SEALED
    assert replay.calls == 0

    durable, _, _, _ = _runner_open(tmp_path, prepared, extraction_reader=None)
    assert durable.seal() == seal
    divergent_seal = replace(seal, charged_tokens=seal.charged_tokens + 1)
    with pytest.raises(SchedulerRunnerError, match="suite_seal_divergent"):
        durable._seal_store.persist_exact(divergent_seal)
    with pytest.raises(SchedulerSQLiteError, match="suite_seal_evidence_invalid"):
        durable._entries[0].store.verify_suite_seal_binding(suite_seal_sha256=sha("divergent-seal"))


def _seed_runner_committed(store) -> None:
    """Provider-free authenticated bulk fixture; production has no bulk bypass."""

    repository = store._repository
    with repository.immediate() as connection:
        before_run, event_head = repository.load_run(connection)
        states = repository.load_calls_bounded(connection)
        final_states = []
        for state in states:
            if state.phase is SchedulerCallPhase.COMMITTED:
                final_states.append(state)
                continue
            ciphertext = (
                _runner_ciphertext(state.logical_call_id)
                if state.stage is SchedulerCallStage.ANSWER
                else None
            )
            terminal = replace(
                state,
                phase=SchedulerCallPhase.COMMITTED,
                attempt_count=1,
                lease_id="provider-free-seed",
                lease_expires_unix_ms=3_000,
                request_sha256=sha(f"request:{state.logical_call_id}"),
                intent_sha256=sha(f"intent:{state.logical_call_id}"),
                terminal_evidence_sha256=sha(f"receipt:{state.logical_call_id}"),
                charged_tokens=1,
                version=4,
            )
            expected = repository._calls[state.logical_call_id]
            repository._update_call(
                connection,
                call_values(
                    terminal,
                    shard_index=expected.shard_index,
                    answer_ciphertext=ciphertext,
                ),
                answer_ciphertext=ciphertext,
                before_version=state.version,
            )
            final_states.append(terminal)
        updated_run = replace(
            before_run,
            reserved_tokens=0,
            consumed_tokens=sum(item.charged_tokens for item in final_states),
            burned_tokens=0,
            inflight_logical_call_id=None,
        )
        repository._update_run(
            connection,
            run_values(updated_run, event_head_sha256=event_head),
            before_version=before_run.version,
        )


def _runner_extraction_evidence(runner):
    return _runner_extraction_evidence_for(
        runner._suite,
        tuple(entry.run for entry in runner._entries),
    )


def _runner_authenticated_terminals(suite, specs):
    evidence = _runner_extraction_evidence_for(
        suite,
        tuple(spec.run for spec in specs),
    )
    return tuple(
        authenticate_extraction_terminal(
            run_authority_sha256=spec.run.commitment_sha256,
            read_policy_sha256=_EXTRACTION_READ_POLICY,
            evidence=item,
            authentication_secret=spec.authentication_secret,
        )
        for spec, item in zip(specs, evidence, strict=True)
    )


def _runner_extraction_evidence_for(suite, runs):
    evidence = []
    for index, run in enumerate(runs):
        context = ManagedFullRunExtractionContext(
            profile_id=run.binding.profile.profile_id,
            run_id_sha256=hashlib.sha256(run.binding.run_id.encode()).hexdigest(),
            binding_commitment_sha256=run.binding.binding_commitment_sha256,
            methodology_commitment_sha256=suite.methodology_sha256,
            admission_commitment_sha256=sha(f"admission:{index}"),
            ingestion_root_sha256=sha(f"ingestion:{index}"),
            a1_terminal_commitment_sha256=sha(f"a1-terminal:{index}"),
            a1_manifest_context_sha256=sha(f"a1-context:{index}"),
            runtime_binding_commitment_sha256=suite.bridge_boot.runtime_authority_sha256,
            expected_receipt_count=(
                LOCOMO_EXTRACTION_OPERATION_COUNT
                if index == 0
                else LONGMEMEVAL_EXTRACTION_OPERATION_COUNT
            ),
        )
        evidence.append(SchedulerExtractionTerminalEvidence(context, _runner_terminal(context)))
    return tuple(evidence)


def _runner_terminal(
    context: ManagedFullRunExtractionContext,
) -> ManagedFullRunExtractionTerminal:
    count = context.expected_receipt_count
    page_count = (count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1) // FULL_RUN_EXTRACTION_PAGE_SIZE
    pages_root = sha(f"pages:{context.commitment_sha256}")
    body = {
        "schema_version": "managed-full-run-extraction-ledger.v1",
        "context_commitment_sha256": context.commitment_sha256,
        "receipt_count": count,
        "page_count": page_count,
        "receipt_pages_root_sha256": pages_root,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=count,
        page_count=page_count,
        receipt_pages_root_sha256=pages_root,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        terminal_commitment_sha256=canonical_sha256(body),
    )
