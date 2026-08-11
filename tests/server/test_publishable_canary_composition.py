"""Provider-free production-order coverage for the one-case canary wrapper."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    HmacJournalIntegrity,
)
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_CASE_ID,
)
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_canary_composition import (
    open_publishable_canary_composition,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
    SchedulerSuiteSealStoreSpec,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from scheduler_subscription_bridge_composition_test_support import (
    BRIDGE_JOURNAL_KEY,
    bridge_fleet_readiness,
    official_suite_and_manifests,
    run_store_specs,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
    BoundedAttestedFakeTransport,
    CountingOfficialCaseReader,
    CountingRetrievalEvidenceReader,
    DeterministicNonceSource,
    DeterministicOutputKeyResolver,
    synthetic_extraction_suite_readback,
)
from subscription_runtime_bridge_test_support import FakeSecrets


def test_canary_crash_reopens_exact_prefix_then_terminal_replay_calls_provider_zero_times(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    created = fixture.open(PublishableProductionOpenMode.CREATE)

    assert created.measure().committed_call_count == 0
    assert fixture.transport.call_count == 0
    assert tuple(call.backend_role for call in created.authority.ordered_calls) == (
        "infinity-context",
        "infinity-context",
        "mem0",
        "mem0",
    )
    assert tuple(call.stage for call in created.authority.ordered_calls) == (
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
    )
    assert all(
        call.case_id == PUBLISHABLE_CANARY_CASE_ID for call in created.authority.ordered_calls
    )
    assert all(
        call.case_alias == PUBLISHABLE_CANARY_CASE_ALIAS for call in created.authority.ordered_calls
    )

    assert created.advance_one().committed_call_count == 1
    original_commit = SQLiteDurableSchedulerStore.commit_outcome
    interrupted = False

    def interrupt_first_commit(
        store: SQLiteDurableSchedulerStore,
        *arguments: object,
        **keyword_arguments: object,
    ):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("provider-free hard crash after terminal journal persistence")
        return original_commit(store, *arguments, **keyword_arguments)  # type: ignore[arg-type]

    monkeypatch.setattr(SQLiteDurableSchedulerStore, "commit_outcome", interrupt_first_commit)
    with pytest.raises(KeyboardInterrupt, match="provider-free hard crash"):
        created.advance_one()
    monkeypatch.setattr(SQLiteDurableSchedulerStore, "commit_outcome", original_commit)
    assert interrupted is True
    assert fixture.transport.call_count == 2
    fixture.reopen_journal()

    resumed = fixture.open(PublishableProductionOpenMode.RESUME)
    recovered = resumed.measure()
    assert recovered.committed_call_count == 2
    assert recovered.provider_intent_count == recovered.provider_result_count == 2
    assert fixture.transport.call_count == 2
    assert resumed.advance_one().committed_call_count == 3
    complete = resumed.advance_one()
    assert complete.complete is True
    assert complete.committed_call_count == 4
    assert complete.provider_intent_count == complete.provider_result_count == 4
    assert len(complete.ordered_receipt_sha256) == 4
    assert complete.paired_path_evidence_sha256 is not None
    assert fixture.transport.call_count == 4
    assert fixture.case_reader.read_count == 4
    assert fixture.retrieval_reader.read_count == 2

    before_replay = complete
    assert resumed.advance_one() == before_replay
    assert fixture.transport.call_count == 4
    fixture.reopen_journal()
    replayed = fixture.open(PublishableProductionOpenMode.RESUME)
    assert replayed.measure() == before_replay
    assert replayed.advance_one() == before_replay
    assert fixture.transport.call_count == 4


def test_canary_rejects_missing_or_crosswired_authority_before_provider(
    tmp_path: Path,
) -> None:
    missing = _fixture(tmp_path / "missing")
    with pytest.raises(SchedulerRunnerError, match="resume_store_missing"):
        missing.open(PublishableProductionOpenMode.RESUME)
    assert missing.transport.call_count == 0

    crossed = _fixture(tmp_path / "crossed", exact_first_case=False)
    with pytest.raises(
        SchedulerRunnerError,
        match="publishable_canary_authority_invalid",
    ):
        crossed.open(PublishableProductionOpenMode.CREATE)
    assert crossed.transport.call_count == 0


class _CompositionFixture:
    def __init__(self, tmp_path: Path, *, exact_first_case: bool) -> None:
        tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.readiness = bridge_fleet_readiness()
        self.suite, self.runs, self.manifests = _suite(self.readiness, exact_first_case)
        self.specs = run_store_specs(
            tmp_path / "scheduler",
            self.suite,
            self.runs,
            self.manifests,
        )
        self.extraction = synthetic_extraction_suite_readback(self.suite, self.specs)
        self.seal = SchedulerSuiteSealStoreSpec(
            database_path=tmp_path / "scheduler" / "suite-seal.sqlite3",
            private_directory=tmp_path / "scheduler",
            authentication_secret=b"canary-suite-seal-authentication-key",
        )
        self.secrets = FakeSecrets(self.readiness.pool)
        self.transport = BoundedAttestedFakeTransport(self.readiness.pool, self.secrets)
        self.case_reader = CountingOfficialCaseReader()
        self.retrieval_reader = CountingRetrievalEvidenceReader()
        self.resolver = DeterministicOutputKeyResolver()
        self.nonce = DeterministicNonceSource()
        self.cipher = Aes256GcmOutputCipher(
            key_resolver=self.resolver,
            maximum_ciphertext_bytes=16 * 1024 * 1024,
            nonce_source=self.nonce,
        )
        self.journal_path = tmp_path / "bridge" / "journal.sqlite3"
        self.journal_path.parent.mkdir(mode=0o700)
        self.journal = BridgeJournal.create(
            self.journal_path,
            integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
        )
        self.lease = 0

    def next_lease_id(self) -> str:
        self.lease += 1
        return f"publishable-canary-lease-{self.lease}"

    def open(self, mode: PublishableProductionOpenMode):
        return open_publishable_canary_composition(
            mode=mode,
            suite=self.suite,
            run_stores=self.specs,
            extraction_suite=self.extraction,
            official_case_authority=self.case_reader,
            retrieval_capture_authority=self.retrieval_reader,
            output_cipher=self.cipher,
            bridge_keys=self.secrets,
            bridge_fleet_readiness=self.readiness,
            bridge_transport=self.transport,
            bridge_journal=self.journal,
            clock=lambda: 2_000,
            lease_id_factory=self.next_lease_id,
            suite_seal_store=self.seal,
            lease_duration_ms=1_000,
        )

    def reopen_journal(self) -> None:
        self.journal.close()
        self.journal = BridgeJournal.open(
            self.journal_path,
            integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
        )


def _fixture(tmp_path: Path, *, exact_first_case: bool = True) -> _CompositionFixture:
    return _CompositionFixture(tmp_path, exact_first_case=exact_first_case)


def _suite(readiness, exact_first_case: bool):
    original, _, _, groups = official_suite_and_manifests(readiness)
    first = (
        SchedulerCaseAuthority(
            case_id=PUBLISHABLE_CANARY_CASE_ID,
            case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
        )
        if exact_first_case
        else SchedulerCaseAuthority(case_id="crosswired-case", case_alias="crosswired-alias")
    )
    locomo_cases = (first, *groups[0][1:])
    locomo_binding = replace(
        original.ordered_runs[0],
        case_manifest_sha256=case_manifest_sha256(locomo_cases),
    )
    suite = replace(
        original,
        ordered_runs=(locomo_binding, original.ordered_runs[1]),
    )
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    manifests = (
        build_scheduler_manifest(runs[0], suite=suite, ordered_cases=locomo_cases),
        build_scheduler_manifest(runs[1], suite=suite, ordered_cases=groups[1]),
    )
    return suite, runs, manifests
