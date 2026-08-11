from __future__ import annotations

import asyncio
import hashlib
import json
import pickle
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
)
from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as run_composition,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as suite_composition,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionAdvance,
    PublishableExtractionAdvancePhase,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBackendAuthority,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    build_scheduler_manifest,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
)
from infinity_context_server.publishable_input_preparation import (
    PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT,
    OpenedPublishableInputPreparationSession,
    PublishableExtractionTerminalFileStore,
    PublishableInputPreparationError,
    PublishableInputPreparationPhase,
    PublishableStrictV4RecoveryCapabilities,
    open_publishable_input_preparation,
)
from infinity_context_server.publishable_input_preparation import (
    composition as input_composition,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationJournalSnapshot,
)
from publishable_mem0_v5.run_provider_extraction import open_sealed_extraction_suite
from publishable_run_outer_test_support import (
    SyntheticOfficialCaseProjection,
    private_run_files,
)
from scheduler_subscription_bridge_composition_test_support import (
    bridge_fleet_readiness,
    official_suite_and_manifests,
    run_store_specs,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
    synthetic_extraction_suite_readback,
)

PublishableFullExtractionRunConfiguration = (
    run_composition.PublishableFullExtractionRunConfiguration
)
PublishableFullExtractionSuiteConfiguration = (
    suite_composition.PublishableFullExtractionSuiteConfiguration
)

_INFINITY_URL = "http://127.0.0.1:31771"
_MEM0_URL = "http://127.0.0.1:31772"
_RETRIEVAL_KEY = b"publishable-input-retrieval-test-key-v1"
_EXPECTED_RETRIEVAL_ROOT = "68b34a99dce1434443d278156dfbdb7b98f862d093def6a7bd96319e60614a97"
_TERMINAL_KEYS = (
    b"publishable-input-locomo-terminal-key-v1",
    b"publishable-input-longmemeval-terminal-key-v1",
)


def test_extraction_state_paths_accept_concrete_platform_path(tmp_path: Path) -> None:
    state_directory = tmp_path / "extraction"

    assert run_composition.publishable_full_extraction_state_paths(state_directory) == (
        state_directory / "publishable-extraction-journal-v4.sqlite3",
        state_directory / "publishable-extraction-ledger-v1.sqlite3",
    )


def test_one_step_budget_reconciles_outcome_unknown_without_reopen_spin() -> None:
    class RecoveringWorker:
        committed = 0
        advance_calls = 0
        reconcile_calls = 0
        outcome_unknown = True

        def read_terminal(self):
            return None

        def advance_one(self) -> PublishableExtractionAdvance:
            self.advance_calls += 1
            snapshot = object.__new__(OperationJournalSnapshot)
            object.__setattr__(snapshot, "committed_count", self.committed)
            if self.outcome_unknown:
                return PublishableExtractionAdvance(
                    phase=PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED,
                    journal_snapshot=snapshot,
                )
            self.committed += 1
            object.__setattr__(snapshot, "committed_count", self.committed)
            return PublishableExtractionAdvance(
                phase=PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
                journal_snapshot=snapshot,
                operation_ordinal=self.committed - 1,
            )

        def reconcile_one(self) -> PublishableExtractionAdvance:
            self.reconcile_calls += 1
            self.outcome_unknown = False
            self.committed += 1
            snapshot = object.__new__(OperationJournalSnapshot)
            object.__setattr__(snapshot, "committed_count", self.committed)
            return PublishableExtractionAdvance(
                phase=PublishableExtractionAdvancePhase.OPERATION_COMMITTED,
                journal_snapshot=snapshot,
                operation_ordinal=self.committed - 1,
            )

    class UnreachedWorker:
        def read_terminal(self):
            return None

        def advance_one(self):
            raise AssertionError("second worker must not be reached")

        def reconcile_one(self):
            raise AssertionError("second worker must not be reached")

    worker = RecoveringWorker()
    suite = SimpleNamespace(locomo=worker, longmemeval=UnreachedWorker())

    first = input_composition._drive_extraction(suite, max_steps=1)
    assert first[1:] == (1, 1, False)
    assert worker.advance_calls == worker.reconcile_calls == 1

    reopened = input_composition._drive_extraction(suite, max_steps=1)
    assert reopened[1:] == (2, 1, False)
    assert worker.advance_calls == 2
    assert worker.reconcile_calls == 1


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _Authorities:
    suite: SchedulerSuiteAuthority
    readback: PublishableExtractionSuiteReadback


@pytest.fixture(scope="module")
def authorities(tmp_path_factory: pytest.TempPathFactory) -> _Authorities:
    readiness = bridge_fleet_readiness()
    base, _runs, _manifests, case_groups = official_suite_and_manifests(readiness)
    backends = (
        SchedulerBackendAuthority(
            "infinity-context",
            managed_backend_target_identity_sha256(
                backend_role="infinity-context",
                base_url=_INFINITY_URL,
            ),
        ),
        SchedulerBackendAuthority(
            "mem0",
            managed_backend_target_identity_sha256(
                backend_role="mem0",
                base_url=_MEM0_URL,
            ),
        ),
    )
    suite = SchedulerSuiteAuthority(
        suite_id=base.suite_id,
        publication_bundle_sha256=base.publication_bundle_sha256,
        methodology_sha256=base.methodology_sha256,
        source_commit_sha256=base.source_commit_sha256,
        bridge_boot=base.bridge_boot,
        ordered_runs=tuple(replace(binding, backends=backends) for binding in base.ordered_runs),
    )
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=cases)
        for run, cases in zip(runs, case_groups, strict=True)
    )
    specs = run_store_specs(
        tmp_path_factory.mktemp("publishable-input-authorities"),
        suite,
        runs,
        manifests,
    )
    return _Authorities(
        suite=suite,
        readback=synthetic_extraction_suite_readback(suite, specs),
    )


@dataclass(slots=True)
class _HttpCalls:
    infinity: int = 0
    mem0: int = 0
    mem0_run_ids: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.infinity + self.mem0


class _TestManagedMem0Retrieval:
    def __init__(self, *, target: str, calls: _HttpCalls) -> None:
        self._target = target
        self._calls = calls

    @property
    def backend_role(self) -> str:
        return "mem0"

    @property
    def target_identity_sha256(self) -> str:
        return self._target

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult:
        assert request.backend_index == 1
        assert request.backend_role == "mem0"
        assert request.target_identity_sha256 == self._target
        self._calls.mem0 += 1
        self._calls.mem0_run_ids.append(request.case_key.run_id)
        return SchedulerBackendRetrievalResult.bind(request=request, memories=())


@dataclass(slots=True)
class _ExtractionState:
    readback: PublishableExtractionSuiteReadback
    committed: list[int]
    advance_call_count: int = 0

    @classmethod
    def empty(cls, readback: PublishableExtractionSuiteReadback) -> _ExtractionState:
        return cls(readback=readback, committed=[0, 0])

    def build(self, *, configuration: object) -> _FakeExtractionSuite:
        if type(configuration) is not PublishableFullExtractionSuiteConfiguration:
            raise AssertionError("fake_extraction_configuration_invalid")
        return _FakeExtractionSuite(self)


class _FakeExtractionWorker:
    def __init__(self, state: _ExtractionState, index: int) -> None:
        self._state = state
        self._index = index
        self._terminal = (
            state.readback.locomo_terminal if index == 0 else state.readback.longmemeval_terminal
        )
        self._expected = self._terminal.expected_receipt_count

    def advance_one(self) -> PublishableExtractionAdvance:
        committed = self._state.committed[self._index]
        if committed >= self._expected:
            raise AssertionError("fake_extraction_replayed_sealed_worker")
        committed += 1
        self._state.committed[self._index] = committed
        self._state.advance_call_count += 1
        sealed = committed == self._expected
        snapshot = object.__new__(OperationJournalSnapshot)
        object.__setattr__(snapshot, "committed_count", committed)
        return PublishableExtractionAdvance(
            phase=(
                PublishableExtractionAdvancePhase.SEALED
                if sealed
                else PublishableExtractionAdvancePhase.OPERATION_COMMITTED
            ),
            journal_snapshot=snapshot,
            operation_ordinal=committed - 1,
            terminal=self._terminal if sealed else None,
        )

    def reconcile_one(self) -> PublishableExtractionAdvance:
        raise AssertionError("fake_extraction_reconciliation_not_expected")

    def read_terminal(self):
        if self._state.committed[self._index] == self._expected:
            return self._terminal
        return None


class _FakeExtractionSuite:
    def __init__(self, state: _ExtractionState) -> None:
        self._state = state
        self.locomo = _FakeExtractionWorker(state, 0)
        self.longmemeval = _FakeExtractionWorker(state, 1)
        self.closed = False

    def readback(self) -> PublishableExtractionSuiteReadback:
        if any(
            observed != expected
            for observed, (_profile, expected) in zip(
                self._state.committed,
                PUBLISHABLE_EXTRACTION_BENCHMARKS,
                strict=True,
            )
        ):
            raise AssertionError("fake_extraction_readback_before_seal")
        return self._state.readback

    def close(self) -> None:
        self.closed = True


class _ReceiptStore:
    def __init__(self, receipt: StrictV4PreparationReceipt) -> None:
        self.receipt = receipt

    def read(self) -> StrictV4PreparationReceipt:
        return self.receipt


class _RegistrationPort:
    async def register_and_readback(self, **_kwargs: object) -> object:
        raise AssertionError("fake_registration_must_not_be_called_directly")


async def _recover_strict_v4(*, receipt_store: _ReceiptStore, **_kwargs: object):
    return receipt_store.read()


def _receipt(
    *,
    root: Path,
    suite: SchedulerSuiteAuthority,
    index: int,
    readback: PublishableExtractionSuiteReadback,
) -> StrictV4PreparationReceipt:
    binding = suite.ordered_runs[index]
    profile_id, operation_count = PUBLISHABLE_EXTRACTION_BENCHMARKS[index]
    terminal = readback.locomo_terminal if index == 0 else readback.longmemeval_terminal
    receipt = object.__new__(StrictV4PreparationReceipt)
    values = {
        "profile_id": profile_id,
        "dataset_sha256": binding.dataset_sha256,
        "run_id_sha256": hashlib.sha256(binding.run_id.encode()).hexdigest(),
        "binding_commitment_sha256": binding.binding_commitment_sha256,
        "methodology_commitment_sha256": suite.methodology_sha256,
        "a1_context": SimpleNamespace(manifest_context_sha256=terminal.a1_manifest_context_sha256),
        "a1_authority": SimpleNamespace(operation_count=operation_count),
        "a2_context": SimpleNamespace(
            case_manifest_sha256=binding.case_manifest_sha256,
            infinity_target_identity_sha256=(binding.backends[0].target_identity_sha256),
        ),
        "a1_path": str(root / f"strict-v4-{index}" / "a1.sqlite3"),
        "a2_path": str(root / f"strict-v4-{index}" / "a2.sqlite3"),
        "expected_index_path": str(root / f"strict-v4-{index}" / "expected-index.sqlite3"),
        "receipt_sha256": terminal.preparation_receipt_sha256,
    }
    for name, value in values.items():
        object.__setattr__(receipt, name, value)
    return receipt


def _run_configuration(
    *,
    root: Path,
    suite: SchedulerSuiteAuthority,
    index: int,
    receipt: StrictV4PreparationReceipt,
) -> PublishableFullExtractionRunConfiguration:
    _profile, operation_count = PUBLISHABLE_EXTRACTION_BENCHMARKS[index]
    configuration = object.__new__(PublishableFullExtractionRunConfiguration)
    mem0_target = suite.ordered_runs[index].backends[1].target_identity_sha256
    values = {
        "preparation_receipt": receipt,
        "preparation_authenticator": object(),
        "preparation_key_authority": object(),
        "manifest_authority": SimpleNamespace(operation_count=operation_count),
        "admission": SimpleNamespace(
            request=SimpleNamespace(expected_operation_count=operation_count)
        ),
        "runtime_receipt_authority": SimpleNamespace(operations=range(operation_count)),
        "expected_runtime": SimpleNamespace(
            subscription_runtime_binding_commitment_sha256=(
                _sha(f"phase-c-runtime-binding:{index}")
            ),
        ),
        "scheduler_bridge_runtime_authority_sha256": (suite.bridge_boot.runtime_authority_sha256),
        "runtime_target_identity_sha256": mem0_target,
        "state_directory": root / f"extraction-{index}",
        "journal_hmac_key": bytes([20 + index * 3]) * 32,
        "operation_receipt_hmac_key": bytes([21 + index * 3]) * 32,
        "ledger_hmac_key": bytes([22 + index * 3]) * 32,
    }
    for name, value in values.items():
        object.__setattr__(configuration, name, value)
    return configuration


@dataclass(slots=True)
class _OpenedTestSession:
    session: OpenedPublishableInputPreparationSession
    projection: SyntheticOfficialCaseProjection
    receipts: tuple[StrictV4PreparationReceipt, StrictV4PreparationReceipt]
    terminal_paths: tuple[Path, Path]
    mem0_retrieval: _TestManagedMem0Retrieval


def _open_test_session(
    *,
    files,
    authorities: _Authorities,
    calls: _HttpCalls,
    expected_retrieval_root: str = _EXPECTED_RETRIEVAL_ROOT,
) -> _OpenedTestSession:
    input_root = files.root / "input-provider"
    input_root.mkdir(mode=0o700, exist_ok=True)
    input_root.chmod(0o700)
    terminal_paths = (
        input_root / "locomo-extraction-terminal.json",
        input_root / "longmemeval-extraction-terminal.json",
    )
    infinity = InfinityContextHttpComparisonBackend(
        base_url=_INFINITY_URL,
        auth_token="provider-free-test-token",
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        mirror_memories_as_documents=False,
        transport=httpx.MockTransport(lambda request: _infinity_response(request, calls)),
    )
    mem0_retrieval = _TestManagedMem0Retrieval(
        target=authorities.suite.ordered_backend_identities[1].target_identity_sha256,
        calls=calls,
    )
    receipts = tuple(
        _receipt(
            root=input_root,
            suite=authorities.suite,
            index=index,
            readback=authorities.readback,
        )
        for index in (0, 1)
    )
    configurations = tuple(
        _run_configuration(
            root=input_root,
            suite=authorities.suite,
            index=index,
            receipt=receipts[index],
        )
        for index in (0, 1)
    )
    extraction = PublishableFullExtractionSuiteConfiguration(
        locomo=configurations[0],
        longmemeval=configurations[1],
    )
    recovery = tuple(
        PublishableStrictV4RecoveryCapabilities(
            receipt_store=_ReceiptStore(receipt),
            registration_port=_RegistrationPort(),
        )
        for receipt in receipts
    )
    projection = SyntheticOfficialCaseProjection()
    session = OpenedPublishableInputPreparationSession(
        suite=authorities.suite,
        official_case_projection=projection,
        strict_v4_recovery=recovery,
        extraction_configuration=extraction,
        extraction_terminal_store=PublishableExtractionTerminalFileStore(
            paths=terminal_paths,
            authentication_keys=_TERMINAL_KEYS,
        ),
        process_lock_path=input_root / "producer.lock",
        retrieval_database_path=input_root / "retrieval.sqlite3",
        retrieval_authentication_key=_RETRIEVAL_KEY,
        expected_retrieval_authority_root_sha256=expected_retrieval_root,
        infinity_backend=infinity,
        close_callbacks=(infinity.close,),
    )
    return _OpenedTestSession(
        session,
        projection,
        receipts,
        terminal_paths,
        mem0_retrieval,
    )


def _infinity_response(request: httpx.Request, calls: _HttpCalls) -> httpx.Response:
    assert request.url.path == "/v1/context/benchmark-search"
    calls.infinity += 1
    return httpx.Response(200, json={"data": {"items": []}})


def _open_composition(files, opened: _OpenedTestSession, state: _ExtractionState):
    return asyncio.run(
        open_publishable_input_preparation(
            config=files.config,
            secrets=files.secrets,
            session=opened.session,
            strict_v4_recoverer=_recover_strict_v4,
            extraction_suite_builder=state.build,
            managed_mem0_retrieval_builder=(lambda **_kwargs: opened.mem0_retrieval),
        )
    )


def test_exact_official_input_preparation_resumes_replays_and_detects_sqlite_tamper(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)

    first = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, first, state)
    assert calls.total == 0
    assert first.projection.emitted_case_count == PUBLISHABLE_SUITE_CASE_COUNT == 2_040
    progress = composition.dispatch_subscription_phase(max_subscription_steps=17)
    assert progress.phase is PublishableInputPreparationPhase.EXTRACTION_PENDING
    assert progress.extraction_committed_receipt_count == 17
    assert progress.subscription_step_count == 17
    assert calls.total == 0
    composition.close()

    resumed = _open_test_session(
        files=files,
        authorities=authorities,
        calls=calls,
        expected_retrieval_root=_sha("wrong-expected-retrieval-root"),
    )
    composition = _open_composition(files, resumed, state)
    assert calls.total == 0
    switch = composition.dispatch_subscription_phase(
        max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
    )
    assert switch.phase is PublishableInputPreparationPhase.RUNTIME_SWITCH_REQUIRED
    assert PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT == 3_080
    assert switch.retrieval_group_count == 3_080
    assert switch.extraction_committed_receipt_count == 5_882
    assert calls.total == 3_080
    assert len(calls.mem0_run_ids) == 1_540
    assert set(calls.mem0_run_ids) == {authorities.suite.ordered_runs[0].run_id}
    with pytest.raises(PublishableInputPreparationError) as same_runtime:
        composition.dispatch_subscription_phase(
            max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
        )
    assert same_runtime.value.code == "publishable_input_runtime_switch_reopen_required"
    assert calls.total == 3_080
    composition.close()

    resumed_after_switch = _open_test_session(
        files=files,
        authorities=authorities,
        calls=calls,
        expected_retrieval_root=_sha("wrong-expected-retrieval-root"),
    )
    composition = _open_composition(files, resumed_after_switch, state)
    assert calls.total == 3_080
    longmemeval_progress = composition.dispatch_subscription_phase(max_subscription_steps=19)
    assert longmemeval_progress.phase is PublishableInputPreparationPhase.EXTRACTION_PENDING
    assert longmemeval_progress.extraction_committed_receipt_count == 5_882 + 19
    assert longmemeval_progress.retrieval_group_count == 3_080
    assert calls.total == 3_080
    composition.close()

    resumed_after_crash = _open_test_session(
        files=files,
        authorities=authorities,
        calls=calls,
        expected_retrieval_root=_sha("wrong-expected-retrieval-root"),
    )
    composition = _open_composition(files, resumed_after_crash, state)
    with pytest.raises(PublishableInputPreparationError) as mismatch:
        composition.dispatch_subscription_phase(
            max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
        )
    assert mismatch.value.code == "publishable_input_retrieval_terminal_invalid"
    assert calls.total == SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
    assert not any(path.exists() for path in resumed_after_crash.terminal_paths)
    composition.close()

    authenticated = _open_test_session(
        files=files,
        authorities=authorities,
        calls=calls,
    )
    composition = _open_composition(files, authenticated, state)
    complete = composition.dispatch_subscription_phase(
        max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
    )
    assert complete.phase is PublishableInputPreparationPhase.COMPLETE
    assert complete.complete is True
    assert complete.paid_go_ready is False
    assert complete.extraction_committed_receipt_count == 130_226
    assert complete.retrieval_group_count == 4_080
    assert complete.subscription_step_count == 0
    assert state.advance_call_count == 130_226
    assert calls.infinity == calls.mem0 == PUBLISHABLE_SUITE_CASE_COUNT
    assert calls.total == SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT == 4_080
    assert calls.mem0_run_ids[1_540:] == [authorities.suite.ordered_runs[1].run_id] * 500
    consumer_readback = open_sealed_extraction_suite(
        authenticated.terminal_paths,
        authentication_keys=_TERMINAL_KEYS,
    )
    assert (
        consumer_readback.suite_readback_commitment_sha256
        == authorities.readback.suite_readback_commitment_sha256
    )
    with sqlite3.connect(authenticated.session.retrieval_database_path) as connection:
        assert connection.execute("SELECT count(*) FROM retrieval_groups").fetchone() == (4_080,)
    composition.close()

    before_replay_calls = calls.total
    before_replay_steps = state.advance_call_count
    replayed = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, replayed, state)
    replay = composition.dispatch_subscription_phase(
        max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
    )
    assert replay.complete is True
    assert replay.subscription_step_count == 0
    assert replay.commitment_sha256 == complete.commitment_sha256
    assert replay.retrieval_authority_root_sha256 == complete.retrieval_authority_root_sha256
    assert replay.ordered_extraction_authentication_hmac_sha256 == (
        complete.ordered_extraction_authentication_hmac_sha256
    )
    assert calls.total == before_replay_calls
    assert state.advance_call_count == before_replay_steps
    composition.close()

    with sqlite3.connect(replayed.session.retrieval_database_path) as connection:
        connection.execute(
            "UPDATE retrieval_groups SET group_commitment_sha256=? WHERE sequence=0",
            ("0" * 64,),
        )
    tampered = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, tampered, state)
    with pytest.raises(SchedulerOfficialAuthorityError):
        composition.dispatch_subscription_phase(
            max_subscription_steps=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
        )
    assert calls.total == before_replay_calls
    assert state.advance_call_count == before_replay_steps
    composition.close()


def test_terminal_store_is_consumer_compatible_and_fails_closed(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    root = tmp_path / "terminals"
    root.mkdir(mode=0o700)
    paths = (root / "locomo.json", root / "longmemeval.json")
    with pytest.raises(PublishableInputPreparationError) as reused:
        PublishableExtractionTerminalFileStore(
            paths=paths,
            authentication_keys=(_TERMINAL_KEYS[0], _TERMINAL_KEYS[0]),
        )
    assert reused.value.code == "publishable_input_terminal_store_key_reuse"
    store = PublishableExtractionTerminalFileStore(
        paths=paths,
        authentication_keys=_TERMINAL_KEYS,
    )
    assert repr(store) == "PublishableExtractionTerminalFileStore(private_files=<bound>)"
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(store)
    created = store.seal_exact(authorities.readback)
    assert created.created_file_count == 2
    assert (
        open_sealed_extraction_suite(paths, authentication_keys=_TERMINAL_KEYS)
        == authorities.readback
    )

    paths[1].unlink()
    with pytest.raises(PublishableRunError):
        open_sealed_extraction_suite(paths, authentication_keys=_TERMINAL_KEYS)
    recovered = store.seal_exact(authorities.readback)
    assert recovered.created_file_count == 1
    assert (
        open_sealed_extraction_suite(paths, authentication_keys=_TERMINAL_KEYS)
        == authorities.readback
    )

    cross_wired = PublishableExtractionTerminalFileStore(
        paths=(paths[1], paths[0]),
        authentication_keys=_TERMINAL_KEYS,
    )
    with pytest.raises(PublishableInputPreparationError) as error:
        cross_wired.seal_exact(authorities.readback)
    assert error.value.code == "publishable_input_terminal_store_divergent"

    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["authentication_hmac_sha256"] = "0" * 64
    paths[0].write_bytes(canonical_json_bytes(payload))
    with pytest.raises(PublishableInputPreparationError) as error:
        store.seal_exact(authorities.readback)
    assert error.value.code == "publishable_input_terminal_store_divergent"
    with pytest.raises(PublishableRunError):
        open_sealed_extraction_suite(paths, authentication_keys=_TERMINAL_KEYS)


def test_missing_strict_v4_receipt_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)

    async def missing(**_kwargs: object):
        return None

    with pytest.raises(PublishableInputPreparationError) as error:
        asyncio.run(
            open_publishable_input_preparation(
                config=files.config,
                secrets=files.secrets,
                session=opened.session,
                strict_v4_recoverer=missing,
                extraction_suite_builder=state.build,
            )
        )
    assert error.value.code == "publishable_input_strict_v4_recovery_divergent"
    assert calls.total == 0
    assert state.advance_call_count == 0


def test_strict_v4_suite_cross_wire_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    object.__setattr__(
        opened.receipts[0],
        "binding_commitment_sha256",
        _sha("cross-wired-strict-v4-binding"),
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        _open_composition(files, opened, state)
    assert error.value.code == "publishable_input_suite_cross_wire"
    assert calls.total == 0
    assert state.advance_call_count == 0


def test_runtime_target_cross_wire_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    object.__setattr__(
        opened.session.extraction_configuration.longmemeval,
        "runtime_target_identity_sha256",
        _sha("cross-wired-runtime-target"),
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        _open_composition(files, opened, state)
    assert error.value.code == "publishable_input_suite_cross_wire"
    assert calls.total == 0
    assert state.advance_call_count == 0


def test_infinity_target_cross_wire_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    opened.receipts[0].a2_context.infinity_target_identity_sha256 = _sha(
        "cross-wired-infinity-target"
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        _open_composition(files, opened, state)
    assert error.value.code == "publishable_input_suite_cross_wire"
    assert calls.total == 0
    assert state.advance_call_count == 0


def test_sqlite_sidecar_path_cross_wire_fails_before_recovery_or_provider(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    object.__setattr__(
        opened.session,
        "retrieval_database_path",
        Path(f"{files.config.official_case_authority_path}-wal"),
    )
    recovery_calls = 0

    async def counting_recoverer(**_kwargs: object):
        nonlocal recovery_calls
        recovery_calls += 1
        raise AssertionError("sidecar cross-wire reached strict-v4 recovery")

    with pytest.raises(PublishableInputPreparationError) as error:
        asyncio.run(
            open_publishable_input_preparation(
                config=files.config,
                secrets=files.secrets,
                session=opened.session,
                strict_v4_recoverer=counting_recoverer,
                extraction_suite_builder=state.build,
            )
        )
    assert error.value.code == "publishable_input_state_path_cross_wire"
    assert recovery_calls == calls.total == state.advance_call_count == 0


@pytest.mark.parametrize("cross_wire", ["outer", "between-runs"])
def test_reused_authentication_key_fails_before_recovery_or_provider(
    tmp_path: Path,
    authorities: _Authorities,
    cross_wire: str,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    if cross_wire == "outer":
        object.__setattr__(
            opened.session,
            "retrieval_authentication_key",
            files.secrets.official_case_authentication_key,
        )
    else:
        object.__setattr__(
            opened.session.extraction_configuration.longmemeval,
            "journal_hmac_key",
            opened.session.extraction_configuration.locomo.journal_hmac_key,
        )
    recovery_calls = 0

    async def counting_recoverer(**_kwargs: object):
        nonlocal recovery_calls
        recovery_calls += 1
        raise AssertionError("cross-wired key reached strict-v4 recovery")

    with pytest.raises(PublishableInputPreparationError) as error:
        asyncio.run(
            open_publishable_input_preparation(
                config=files.config,
                secrets=files.secrets,
                session=opened.session,
                strict_v4_recoverer=counting_recoverer,
                extraction_suite_builder=state.build,
            )
        )
    assert error.value.code == "publishable_input_authentication_key_cross_wire"
    assert recovery_calls == calls.total == state.advance_call_count == 0


def test_process_lock_rejects_second_owner_before_recovery_or_provider(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    first = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, first, state)
    second = _open_test_session(files=files, authorities=authorities, calls=calls)
    recovery_calls = 0

    async def counting_recoverer(**_kwargs: object):
        nonlocal recovery_calls
        recovery_calls += 1
        raise AssertionError("second process owner reached strict-v4 recovery")

    try:
        with pytest.raises(PublishableInputPreparationError) as error:
            asyncio.run(
                open_publishable_input_preparation(
                    config=files.config,
                    secrets=files.secrets,
                    session=second.session,
                    strict_v4_recoverer=counting_recoverer,
                    extraction_suite_builder=state.build,
                )
            )
        assert error.value.code == "publishable_input_process_already_active"
        assert second.projection.emitted_case_count == 0
        assert recovery_calls == calls.total == state.advance_call_count == 0
    finally:
        composition.close()


def test_open_session_capability_substitution_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, opened, state)
    object.__setattr__(
        opened.session,
        "expected_retrieval_authority_root_sha256",
        _sha("substituted-retrieval-authority"),
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        composition.dispatch_subscription_phase(max_subscription_steps=1)

    assert error.value.code == "publishable_input_session_capability_divergent"
    assert calls.total == state.advance_call_count == 0
    composition.close()


def test_open_session_suite_substitution_fails_before_provider_or_extraction(
    tmp_path: Path,
    authorities: _Authorities,
) -> None:
    files = private_run_files(tmp_path)
    calls = _HttpCalls()
    state = _ExtractionState.empty(authorities.readback)
    opened = _open_test_session(files=files, authorities=authorities, calls=calls)
    composition = _open_composition(files, opened, state)
    object.__setattr__(
        opened.session,
        "suite",
        replace(authorities.suite, suite_id="cross-wired-suite"),
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        composition.dispatch_subscription_phase(max_subscription_steps=1)

    assert error.value.code == "publishable_input_session_capability_divergent"
    assert calls.total == state.advance_call_count == 0
    composition.close()
