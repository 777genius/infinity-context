"""Production composition for exact publishable extraction and retrieval inputs."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol, final

from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
)

from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as extraction_composition,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionAdvance,
    PublishableExtractionAdvancePhase,
    PublishableExtractionRunTerminal,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_extraction_terminal_adapter,
    publishable_run_orchestrator,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_official_cases import (
    PreparedPublishableOfficialCases,
    prepare_publishable_official_cases,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_composition import (
    SchedulerRetrievalCaptureComposition,
    compose_scheduler_retrieval_capture,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
    SchedulerRetrievalBackendPort,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
)

from .contracts import (
    PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT,
    OpenedPublishableInputPreparationSession,
    PublishableExtractionTerminalSealReceipt,
    PublishableInputPreparationError,
    PublishableInputPreparationPhase,
    PublishableInputPreparationResult,
    authentication_key_fingerprint,
)
from .managed_mem0_v5_retrieval import ManagedMem0V5SchedulerRetrievalAdapter
from .process_lock import PublishableInputPreparationProcessLock

PUBLISHABLE_INPUT_MAX_SUBSCRIPTION_STEPS = PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
PUBLISHABLE_INPUT_MAX_RECOVERY_STATUS_READS = PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
_SQLITE_SIDECAR_SUFFIXES = ("", "-journal", "-shm", "-wal")
PublishableFullExtractionSuite = extraction_composition.PublishableFullExtractionSuite
build_publishable_full_extraction_suite = (
    extraction_composition.build_publishable_full_extraction_suite
)


class _ExtractionWorkerPort(Protocol):
    def advance_one(self) -> PublishableExtractionAdvance: ...

    def reconcile_one(self) -> PublishableExtractionAdvance: ...

    def read_terminal(self) -> PublishableExtractionRunTerminal | None: ...


class _ExtractionSuitePort(Protocol):
    locomo: _ExtractionWorkerPort
    longmemeval: _ExtractionWorkerPort

    def readback(self) -> PublishableExtractionSuiteReadback: ...

    def close(self) -> None: ...


StrictV4Recoverer = Callable[..., Awaitable[StrictV4PreparationReceipt]]
ExtractionSuiteBuilder = Callable[..., PublishableFullExtractionSuite]
ManagedMem0RetrievalBuilder = Callable[..., SchedulerRetrievalBackendPort]


@final
class PublishableInputPreparationComposition:
    """Own provider-free prepared capabilities until explicit bounded dispatch."""

    __slots__ = (
        "_closed",
        "_expected_retrieval_root",
        "_extraction",
        "_lock",
        "_official_cases",
        "_process_lock",
        "_retrieval",
        "_runtime_switch_required",
        "_session",
        "_suite",
        "_suite_commitment",
        "_terminal_key_fingerprints",
        "_terminal_paths",
        "_terminal_store",
    )

    def __init__(
        self,
        *,
        session: OpenedPublishableInputPreparationSession,
        official_cases: PreparedPublishableOfficialCases,
        extraction: _ExtractionSuitePort,
        retrieval: SchedulerRetrievalCaptureComposition,
        process_lock: PublishableInputPreparationProcessLock,
    ) -> None:
        if (
            type(session) is not OpenedPublishableInputPreparationSession
            or type(official_cases) is not PreparedPublishableOfficialCases
            or type(retrieval) is not SchedulerRetrievalCaptureComposition
            or type(process_lock) is not PublishableInputPreparationProcessLock
            or not _is_extraction_suite(extraction)
        ):
            _fail("publishable_input_composition_invalid")
        self._session = session
        self._suite = session.suite
        self._suite_commitment = session.suite.commitment_sha256
        self._official_cases = official_cases
        self._extraction = extraction
        self._retrieval = retrieval
        self._process_lock = process_lock
        self._expected_retrieval_root = session.expected_retrieval_authority_root_sha256
        self._terminal_store = session.extraction_terminal_store
        self._terminal_paths = session.extraction_terminal_store.paths
        self._terminal_key_fingerprints = (
            session.extraction_terminal_store.authentication_key_fingerprints
        )
        self._runtime_switch_required = False
        self._closed = False
        self._lock = threading.RLock()

    @property
    def suite(self) -> SchedulerSuiteAuthority:
        self._require_open()
        return self._suite

    @property
    def official_case_authority_root_sha256(self) -> str:
        self._require_open()
        return self._official_cases.terminal.authority_root_sha256

    def dispatch_subscription_phase(
        self, *, max_subscription_steps: int
    ) -> PublishableInputPreparationResult:
        """Advance at most the stated number of extraction worker steps.

        A fresh step dispatches at most one operation. Reopening may also status-read
        committed operations while rebuilding a lagging authenticated ledger; that work
        is hard-capped by the exact 130,226-operation suite. Each single-admission runtime
        is closed out with its ordered retrieval range before an explicit reopen/switch.
        """

        if (
            type(max_subscription_steps) is not int
            or not 1 <= max_subscription_steps <= PUBLISHABLE_INPUT_MAX_SUBSCRIPTION_STEPS
        ):
            _fail("publishable_input_subscription_step_bound_invalid")
        with self._lock:
            self._require_open()
            self._require_capability_bindings()
            if self._runtime_switch_required:
                _fail("publishable_input_runtime_switch_reopen_required")
            retrieval_progress = self._retrieval.read_progress()
            retrieval_count = retrieval_progress.next_sequence
            workers = (self._extraction.locomo, self._extraction.longmemeval)
            terminals = [worker.read_terminal() for worker in workers]
            counts = [
                terminal.expected_receipt_count if terminal is not None else 0
                for terminal in terminals
            ]
            steps = 0
            if retrieval_count < PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT:
                if terminals[0] is None:
                    terminals[0], counts[0], steps, reconciliation = _drive_worker(
                        workers[0],
                        max_steps=max_subscription_steps,
                    )
                    if terminals[0] is None:
                        return self._progress(
                            committed=sum(counts),
                            steps=steps,
                            reconciliation=reconciliation,
                            retrieval_groups=retrieval_count,
                        )
                progress = self._retrieval.capture_through(
                    PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT
                )
                if (
                    progress.next_sequence != PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT
                    or progress.complete
                ):
                    _fail("publishable_input_retrieval_progress_invalid")
                self._runtime_switch_required = True
                return PublishableInputPreparationResult(
                    phase=PublishableInputPreparationPhase.RUNTIME_SWITCH_REQUIRED,
                    suite_authority_sha256=self._suite_commitment,
                    official_case_authority_root_sha256=(
                        self._official_cases.terminal.authority_root_sha256
                    ),
                    extraction_committed_receipt_count=sum(counts),
                    subscription_step_count=steps,
                    retrieval_group_count=progress.next_sequence,
                )
            if terminals[0] is None:
                _fail("publishable_input_retrieval_extraction_cross_wire")
            if retrieval_count > PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT:
                if terminals[1] is None:
                    _fail("publishable_input_retrieval_extraction_cross_wire")
            elif terminals[1] is None:
                terminals[1], counts[1], steps, reconciliation = _drive_worker(
                    workers[1],
                    max_steps=max_subscription_steps,
                )
                if terminals[1] is None:
                    return self._progress(
                        committed=sum(counts),
                        steps=steps,
                        reconciliation=reconciliation,
                        retrieval_groups=retrieval_count,
                    )
            if any(type(item) is not PublishableExtractionRunTerminal for item in terminals):
                _fail("publishable_input_extraction_terminal_invalid")
            if sum(item.expected_receipt_count for item in terminals) != (  # type: ignore[union-attr]
                PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
            ):
                _fail("publishable_input_extraction_terminal_invalid")
            exact_terminals = (terminals[0], terminals[1])
            if any(item is None for item in exact_terminals):  # pragma: no cover - guarded above
                _fail("publishable_input_extraction_terminal_invalid")
            readback = self._extraction.readback()
            if (
                readback.locomo_terminal != exact_terminals[0]
                or readback.longmemeval_terminal != exact_terminals[1]
            ):
                _fail("publishable_input_extraction_readback_divergent")
            _authenticate_extraction_suite(
                suite=self._suite,
                official_cases=self._official_cases,
                readback=readback,
            )
            self._require_capability_bindings()
            sealed_retrieval = self._retrieval.capture()
            try:
                terminal = sealed_retrieval.terminal
                if (
                    terminal.group_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                    or terminal.authority_root_sha256 != self._expected_retrieval_root
                    or sealed_retrieval.plan.case_authority_root_sha256
                    != self._official_cases.terminal.authority_root_sha256
                ):
                    _fail("publishable_input_retrieval_terminal_invalid")
                self._require_capability_bindings()
                seal_receipt = self._terminal_store.seal_exact(readback)
                self._terminal_store.seal_exact(readback)
                return _complete_result(
                    suite=self._suite,
                    official_cases=self._official_cases,
                    readback=readback,
                    seal_receipt=seal_receipt,
                    retrieval_root=terminal.authority_root_sha256,
                    steps=steps,
                )
            finally:
                sealed_retrieval.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            first: BaseException | None = None
            for callback in (
                self._extraction.close,
                self._official_cases.close,
                self._session.close,
                self._process_lock.close,
            ):
                try:
                    callback()
                except BaseException as error:
                    if first is None:
                        first = error
            if first is not None:
                raise first

    def __enter__(self) -> PublishableInputPreparationComposition:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "PublishableInputPreparationComposition("
            f"suite_authority_sha256={self._suite_commitment!r}, "
            f"official_case_authority_root_sha256="
            f"{self._official_cases.terminal.authority_root_sha256!r}, "
            "private_capabilities=<bound>)"
        )

    def _progress(
        self,
        *,
        committed: int,
        steps: int,
        reconciliation: bool,
        retrieval_groups: int = 0,
    ) -> PublishableInputPreparationResult:
        return PublishableInputPreparationResult(
            phase=(
                PublishableInputPreparationPhase.RECONCILIATION_REQUIRED
                if reconciliation
                else PublishableInputPreparationPhase.EXTRACTION_PENDING
            ),
            suite_authority_sha256=self._suite_commitment,
            official_case_authority_root_sha256=(
                self._official_cases.terminal.authority_root_sha256
            ),
            extraction_committed_receipt_count=committed,
            subscription_step_count=steps,
            retrieval_group_count=retrieval_groups,
        )

    def _require_open(self) -> None:
        if self._closed:
            _fail("publishable_input_composition_closed")

    def _require_capability_bindings(self) -> None:
        try:
            store = self._session.extraction_terminal_store
            valid = (
                store is self._terminal_store
                and store.paths == self._terminal_paths
                and store.authentication_key_fingerprints == self._terminal_key_fingerprints
                and self._session.suite is self._suite
                and hmac.compare_digest(
                    self._suite.commitment_sha256,
                    self._suite_commitment,
                )
                and hmac.compare_digest(
                    commitment("suite", self._suite.material()),
                    self._suite_commitment,
                )
                and hmac.compare_digest(
                    self._session.expected_retrieval_authority_root_sha256,
                    self._expected_retrieval_root,
                )
            )
        except Exception:
            valid = False
        if not valid:
            _fail("publishable_input_session_capability_divergent")


async def open_publishable_input_preparation(
    *,
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
    session: OpenedPublishableInputPreparationSession,
    strict_v4_recoverer: StrictV4Recoverer = recover_strict_v4_full_run,
    extraction_suite_builder: ExtractionSuiteBuilder = build_publishable_full_extraction_suite,
    managed_mem0_retrieval_builder: ManagedMem0RetrievalBuilder = (
        ManagedMem0V5SchedulerRetrievalAdapter
    ),
) -> PublishableInputPreparationComposition:
    """Authenticate and compose every input capability without provider dispatch."""

    if (
        type(config) is not PublishableRunConfig
        or type(secrets) is not PublishableRunSecrets
        or type(session) is not OpenedPublishableInputPreparationSession
        or not callable(strict_v4_recoverer)
        or not callable(extraction_suite_builder)
        or not callable(managed_mem0_retrieval_builder)
    ):
        _close_session(session)
        _fail("publishable_input_open_invalid")
    official_cases: PreparedPublishableOfficialCases | None = None
    extraction: _ExtractionSuitePort | None = None
    process_lock: PublishableInputPreparationProcessLock | None = None
    try:
        session.__post_init__()
        _validate_authentication_keys(secrets=secrets, session=session)
        _validate_paths(config=config, session=session)
        process_lock = PublishableInputPreparationProcessLock.acquire(session.process_lock_path)
        await _recover_strict_v4(session, recoverer=strict_v4_recoverer)
        _validate_pre_dispatch_bindings(session)
        official_cases = prepare_publishable_official_cases(
            suite=session.suite,
            projection=session.official_case_projection,
            config=config,
            secrets=secrets,
        )
        extraction = extraction_suite_builder(
            configuration=session.extraction_configuration,
        )
        if not _is_extraction_suite(extraction):
            _fail("publishable_input_extraction_suite_invalid")
        try:
            mem0_retrieval = managed_mem0_retrieval_builder(
                suite=session.suite,
                configuration=session.extraction_configuration,
            )
        except Exception:
            _fail("publishable_input_mem0_retrieval_composition_failed")
        retrieval = compose_scheduler_retrieval_capture(
            session.retrieval_database_path,
            suite=session.suite,
            official_cases=official_cases,
            infinity_backend=session.infinity_backend,
            mem0_retrieval_backend=mem0_retrieval,
            authentication_key=session.retrieval_authentication_key,
        )
        return PublishableInputPreparationComposition(
            session=session,
            official_cases=official_cases,
            extraction=extraction,
            retrieval=retrieval,
            process_lock=process_lock,
        )
    except BaseException:
        if extraction is not None:
            with suppress(BaseException):
                extraction.close()
        if official_cases is not None:
            with suppress(BaseException):
                official_cases.close()
        _close_session(session)
        if process_lock is not None:
            with suppress(BaseException):
                process_lock.close()
        raise


async def _recover_strict_v4(
    session: OpenedPublishableInputPreparationSession,
    *,
    recoverer: StrictV4Recoverer,
) -> None:
    configurations = (
        session.extraction_configuration.locomo,
        session.extraction_configuration.longmemeval,
    )
    for capabilities, configuration in zip(
        session.strict_v4_recovery,
        configurations,
        strict=True,
    ):
        try:
            recovered = await recoverer(
                receipt_store=capabilities.receipt_store,
                registration_port=capabilities.registration_port,
                authenticator=configuration.preparation_authenticator,
                key_identity_authority=configuration.preparation_key_authority,
            )
        except PublishableInputPreparationError:
            raise
        except Exception:
            _fail("publishable_input_strict_v4_recovery_failed")
        if (
            type(recovered) is not StrictV4PreparationReceipt
            or recovered is not configuration.preparation_receipt
            and recovered != configuration.preparation_receipt
        ):
            _fail("publishable_input_strict_v4_recovery_divergent")


def _validate_authentication_keys(
    *,
    secrets: PublishableRunSecrets,
    session: OpenedPublishableInputPreparationSession,
) -> None:
    try:
        publishable_run_orchestrator._require_cross_layer_secret_distinctness(secrets)
        outer = (
            secrets.official_case_authentication_key,
            *secrets.scheduler_authentication_keys,
            secrets.suite_seal_authentication_key,
            secrets.publication_receipt_authentication_key,
        )
        outer_fingerprints = {authentication_key_fingerprint(key) for key in outer}
        producer_fingerprints = [
            *session.extraction_terminal_store.authentication_key_fingerprints,
            authentication_key_fingerprint(session.retrieval_authentication_key),
        ]
        for configuration in (
            session.extraction_configuration.locomo,
            session.extraction_configuration.longmemeval,
        ):
            producer_fingerprints.extend(
                authentication_key_fingerprint(getattr(configuration, name))
                for name in (
                    "journal_hmac_key",
                    "operation_receipt_hmac_key",
                    "ledger_hmac_key",
                )
            )
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_authentication_keys_invalid")
    if len(producer_fingerprints) != len(set(producer_fingerprints)) or outer_fingerprints & set(
        producer_fingerprints
    ):
        _fail("publishable_input_authentication_key_cross_wire")


def _validate_pre_dispatch_bindings(session: OpenedPublishableInputPreparationSession) -> None:
    try:
        session.extraction_configuration.__post_init__()
        suite = session.suite
        if suite.commitment_sha256 != commitment("suite", suite.material()):
            _fail("publishable_input_suite_invalid")
        configurations = (
            session.extraction_configuration.locomo,
            session.extraction_configuration.longmemeval,
        )
        expected_profiles = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
        infinity_target = suite.ordered_backend_identities[0].target_identity_sha256
        mem0_target = suite.ordered_backend_identities[1].target_identity_sha256
        for binding, configuration, profile, (extraction_profile, operation_count) in zip(
            suite.ordered_runs,
            configurations,
            expected_profiles,
            PUBLISHABLE_EXTRACTION_BENCHMARKS,
            strict=True,
        ):
            receipt = configuration.preparation_receipt
            if (
                binding.profile != profile
                or binding.profile.profile_id != extraction_profile
                or hashlib.sha256(binding.run_id.encode()).hexdigest() != receipt.run_id_sha256
                or binding.binding_commitment_sha256 != receipt.binding_commitment_sha256
                or binding.dataset_sha256 != receipt.dataset_sha256
                or receipt.a2_context.infinity_target_identity_sha256 != infinity_target
                or suite.methodology_sha256 != receipt.methodology_commitment_sha256
                or receipt.a1_authority.operation_count != operation_count
                or configuration.scheduler_bridge_runtime_authority_sha256
                != suite.bridge_boot.runtime_authority_sha256
                or configuration.runtime_target_identity_sha256 != mem0_target
            ):
                _fail("publishable_input_suite_cross_wire")
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_suite_invalid")


def _drive_extraction(
    suite: _ExtractionSuitePort,
    *,
    max_steps: int,
) -> tuple[
    tuple[PublishableExtractionRunTerminal, PublishableExtractionRunTerminal] | None,
    int,
    int,
    bool,
]:
    workers = (suite.locomo, suite.longmemeval)
    terminals: list[PublishableExtractionRunTerminal | None] = [
        worker.read_terminal() for worker in workers
    ]
    counts = [
        terminal.expected_receipt_count if terminal is not None else 0 for terminal in terminals
    ]
    steps = 0
    reconciliation = False
    for index, worker in enumerate(workers):
        if terminals[index] is not None:
            continue
        if steps >= max_steps:
            return None, sum(counts), steps, reconciliation
        terminal, count, used, reconciliation = _drive_worker(
            worker,
            max_steps=max_steps - steps,
        )
        terminals[index] = terminal
        counts[index] = count
        steps += used
        if terminals[index] is None:
            return None, sum(counts), steps, reconciliation
    exact = tuple(terminals)
    if (
        len(exact) != 2
        or any(type(item) is not PublishableExtractionRunTerminal for item in exact)
        or sum(item.expected_receipt_count for item in exact)  # type: ignore[union-attr]
        != PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
    ):
        _fail("publishable_input_extraction_terminal_invalid")
    return (exact[0], exact[1]), sum(counts), steps, False  # type: ignore[return-value]


def _drive_worker(
    worker: _ExtractionWorkerPort,
    *,
    max_steps: int,
) -> tuple[PublishableExtractionRunTerminal | None, int, int, bool]:
    if type(max_steps) is not int or max_steps < 1:
        _fail("publishable_input_subscription_step_bound_invalid")
    terminal = worker.read_terminal()
    if terminal is not None:
        return terminal, terminal.expected_receipt_count, 0, False
    count = 0
    steps = 0
    reconciliation = False
    while steps < max_steps:
        advance = _advance(worker)
        count = advance.journal_snapshot.committed_count
        if advance.phase is PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED:
            reconciliation = True
            advance = _reconcile(worker)
            steps += 1
            count = advance.journal_snapshot.committed_count
            reconciliation = (
                advance.phase is PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED
            )
        else:
            steps += 1
        if advance.terminal is not None:
            return advance.terminal, advance.terminal.expected_receipt_count, steps, False
        if reconciliation:
            break
    return None, count, steps, reconciliation


def _advance(worker: _ExtractionWorkerPort) -> PublishableExtractionAdvance:
    try:
        result = worker.advance_one()
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_extraction_advance_failed")
    if type(result) is not PublishableExtractionAdvance:
        _fail("publishable_input_extraction_advance_invalid")
    return result


def _reconcile(worker: _ExtractionWorkerPort) -> PublishableExtractionAdvance:
    try:
        result = worker.reconcile_one()
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_extraction_reconciliation_failed")
    if type(result) is not PublishableExtractionAdvance:
        _fail("publishable_input_extraction_reconciliation_invalid")
    return result


def _authenticate_extraction_suite(
    *,
    suite: SchedulerSuiteAuthority,
    official_cases: PreparedPublishableOfficialCases,
    readback: PublishableExtractionSuiteReadback,
) -> None:
    try:
        reader = publishable_extraction_terminal_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=official_cases.run_stores,
            readback=readback,
        )
        authenticated = tuple(reader.read_terminal(run=run) for run in official_cases.runs)
        if len(authenticated) != 2:
            _fail("publishable_input_extraction_authentication_failed")
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_extraction_authentication_failed")


def _complete_result(
    *,
    suite: SchedulerSuiteAuthority,
    official_cases: PreparedPublishableOfficialCases,
    readback: PublishableExtractionSuiteReadback,
    seal_receipt: PublishableExtractionTerminalSealReceipt,
    retrieval_root: str,
    steps: int,
) -> PublishableInputPreparationResult:
    if (
        official_cases.terminal.case_count != PUBLISHABLE_SUITE_CASE_COUNT
        or seal_receipt.suite_readback_commitment_sha256
        != readback.suite_readback_commitment_sha256
    ):
        _fail("publishable_input_terminal_binding_invalid")
    return PublishableInputPreparationResult(
        phase=PublishableInputPreparationPhase.COMPLETE,
        suite_authority_sha256=suite.commitment_sha256,
        official_case_authority_root_sha256=(official_cases.terminal.authority_root_sha256),
        extraction_committed_receipt_count=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
        subscription_step_count=steps,
        extraction_suite_readback_sha256=readback.suite_readback_commitment_sha256,
        ordered_extraction_terminal_sha256=(seal_receipt.ordered_terminal_commitment_sha256),
        ordered_extraction_authentication_hmac_sha256=(
            seal_receipt.ordered_authentication_hmac_sha256
        ),
        retrieval_authority_root_sha256=retrieval_root,
        retrieval_group_count=SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
    )


def _validate_paths(
    *,
    config: PublishableRunConfig,
    session: OpenedPublishableInputPreparationSession,
) -> None:
    sqlite_paths = [
        config.official_case_authority_path,
        *config.scheduler_database_paths,
        config.suite_seal_database_path,
        session.retrieval_database_path,
    ]
    terminal_paths = getattr(session.extraction_terminal_store, "paths", ())
    if type(terminal_paths) is not tuple or len(terminal_paths) != 2:
        _fail("publishable_input_state_path_cross_wire")
    plain_paths = [
        config.publication_receipt_path,
        session.process_lock_path,
        *terminal_paths,
    ]
    extraction_directories: list[Path] = []
    for configuration in (
        session.extraction_configuration.locomo,
        session.extraction_configuration.longmemeval,
    ):
        try:
            receipt = configuration.preparation_receipt
            sqlite_paths.extend(
                (Path(receipt.a1_path), Path(receipt.a2_path), Path(receipt.expected_index_path))
            )
            directory = configuration.state_directory
        except Exception:
            _fail("publishable_input_state_path_invalid")
        extraction_directories.append(directory)
        sqlite_paths.extend(
            extraction_composition.publishable_full_extraction_state_paths(directory)
        )
    candidates = [
        *(candidate for path in sqlite_paths for candidate in _sqlite_footprint(path)),
        *plain_paths,
        *extraction_directories,
    ]
    try:
        normalized = tuple(_canonical_state_path(path) for path in candidates)
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_state_path_invalid")
    if len(normalized) != len(set(normalized)):
        _fail("publishable_input_state_path_cross_wire")
    existing_identities: list[tuple[int, int]] = []
    for path in candidates:
        if not os.path.lexists(path):
            continue
        try:
            value = path.lstat()
        except OSError:
            _fail("publishable_input_state_path_invalid")
        if stat.S_ISLNK(value.st_mode) or (stat.S_ISREG(value.st_mode) and value.st_nlink != 1):
            _fail("publishable_input_state_path_invalid")
        existing_identities.append((value.st_dev, value.st_ino))
    if len(existing_identities) != len(set(existing_identities)):
        _fail("publishable_input_state_path_cross_wire")


def _sqlite_footprint(path: Path) -> tuple[Path, ...]:
    if not isinstance(path, Path):
        _fail("publishable_input_state_path_invalid")
    return tuple(Path(f"{path}{suffix}") for suffix in _SQLITE_SIDECAR_SUFFIXES)


def _canonical_state_path(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path == Path(path.anchor)
    ):
        _fail("publishable_input_state_path_invalid")
    resolved = path.resolve(strict=False)
    if resolved != path:
        _fail("publishable_input_state_path_invalid")
    return resolved


def _is_extraction_suite(value: object) -> bool:
    try:
        workers = (value.locomo, value.longmemeval)
        return all(
            all(
                callable(getattr(worker, name, None))
                for name in ("advance_one", "reconcile_one", "read_terminal")
            )
            for worker in workers
        ) and all(callable(getattr(value, name, None)) for name in ("readback", "close"))
    except Exception:
        return False


def _close_session(session: object) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        with suppress(BaseException):
            close()


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "PUBLISHABLE_INPUT_MAX_RECOVERY_STATUS_READS",
    "PUBLISHABLE_INPUT_MAX_SUBSCRIPTION_STEPS",
    "ExtractionSuiteBuilder",
    "PublishableInputPreparationComposition",
    "StrictV4Recoverer",
    "open_publishable_input_preparation",
)
