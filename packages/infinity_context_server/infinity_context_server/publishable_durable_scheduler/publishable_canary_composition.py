"""Same-lane production composition for the fixed one-case activation canary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    BridgeSecretCapability,
    BridgeTransportPort,
    TerminalBridgeCall,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_authority import (
    PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_canary_authority import (
    PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
    PublishableCanaryAuthority,
    bind_publishable_canary_authority,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_PAGE_SIZE,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerStepDisposition,
    SchedulerSuiteSealStoreSpec,
)
from infinity_context_server.publishable_durable_scheduler.runner_dispatch_authority import (
    SchedulerDispatchAuthority,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerOfficialCaseReaderPort,
    SchedulerRetrievalEvidenceReaderPort,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
    SchedulerRunPhase,
)

from .publishable_extraction_terminal_adapter import (
    PublishableExtractionSuiteTerminalAdapter,
)
from .publishable_production_composition import (
    PublishableProductionOpenMode,
    PublishableProductionRuntimeProvenance,
    _require_call_journal_binding,
    build_publishable_production_runtime_provenance,
)
from .scheduler_subscription_bridge_composition import (
    SchedulerSubscriptionBridgeComposition,
    open_scheduler_subscription_bridge_composition,
)

PUBLISHABLE_CANARY_COMPOSITION_SCHEMA = (
    "memory-comparison-publishable-one-case-canary-composition.v1"
)
PUBLISHABLE_CANARY_PAIRED_PATH_SCHEMA = (
    "memory-comparison-publishable-one-case-canary-paired-path.v1"
)


@final
@dataclass(frozen=True, slots=True)
class PublishableCanaryMeasurement:
    """Authenticated durable accounting for only the statically selected calls."""

    committed_call_count: int
    provider_intent_count: int
    provider_result_count: int
    ordered_receipt_sha256: tuple[str, ...]
    paired_path_evidence_sha256: str | None

    def __post_init__(self) -> None:
        complete = self.committed_call_count == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
        if (
            type(self.committed_call_count) is not int
            or not 0 <= self.committed_call_count <= PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            or type(self.provider_intent_count) is not int
            or type(self.provider_result_count) is not int
            or not 0
            <= self.provider_result_count
            <= self.provider_intent_count
            <= PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            or type(self.ordered_receipt_sha256) is not tuple
            or len(self.ordered_receipt_sha256) != self.committed_call_count
            or any(not _sha256(value) for value in self.ordered_receipt_sha256)
            or len(set(self.ordered_receipt_sha256)) != len(self.ordered_receipt_sha256)
            or complete
            and (
                self.provider_intent_count != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
                or self.provider_result_count != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            )
            or complete != (self.paired_path_evidence_sha256 is not None)
            or self.paired_path_evidence_sha256 is not None
            and not _sha256(self.paired_path_evidence_sha256)
        ):
            _fail("publishable_canary_measurement_invalid")

    @property
    def complete(self) -> bool:
        return self.committed_call_count == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableCanaryComposition:
    """Narrow wrapper which cannot dispatch beyond the frozen four-call prefix."""

    _scheduler: SchedulerSubscriptionBridgeComposition = field(repr=False)
    _dispatch_authority: SchedulerDispatchAuthority = field(repr=False)
    _run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec] = field(repr=False)
    _suite: SchedulerSuiteAuthority = field(repr=False)
    _journal: BridgeJournal = field(repr=False)
    authority: PublishableCanaryAuthority
    runtime_provenance: PublishableProductionRuntimeProvenance
    selected_extraction_terminal_sha256: str
    paired_path_authority_sha256: str
    open_mode: PublishableProductionOpenMode
    authority_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self._scheduler) is not SchedulerSubscriptionBridgeComposition
            or type(self._dispatch_authority) is not SchedulerDispatchAuthority
            or type(self._run_stores) is not tuple
            or len(self._run_stores) != 2
            or any(type(item) is not SchedulerRunStoreSpec for item in self._run_stores)
            or type(self._suite) is not SchedulerSuiteAuthority
            or type(self._journal) is not BridgeJournal
            or type(self.authority) is not PublishableCanaryAuthority
            or type(self.runtime_provenance) is not PublishableProductionRuntimeProvenance
            or not _sha256(self.selected_extraction_terminal_sha256)
            or not _sha256(self.paired_path_authority_sha256)
            or type(self.open_mode) is not PublishableProductionOpenMode
            or not _sha256(self.authority_sha256)
            or self._scheduler.suite_seal_binding_policy_sha256 is not None
            or self._dispatch_authority.ordered_calls != self.authority.ordered_calls
            or self._scheduler.runner.dispatch_authority_sha256
            != self._dispatch_authority.commitment_sha256
            or self._scheduler.scheduler_bridge.dispatch_authority_sha256
            != self._dispatch_authority.commitment_sha256
            or self.runtime_provenance.scheduler_runtime_provenance_sha256
            != self._scheduler.scheduler_bridge.scheduler_runtime_provenance_sha256
        ):
            _fail("publishable_canary_composition_invalid")

    @property
    def ordered_logical_call_ids(self) -> tuple[str, str, str, str]:
        return self.authority.ordered_logical_call_ids

    @property
    def dispatch_authority_sha256(self) -> str:
        return self._dispatch_authority.commitment_sha256

    def measure(self) -> PublishableCanaryMeasurement:
        """Authenticate the selected rows and exact bridge-journal accounting."""

        _audit_scope_heads(
            run_stores=self._run_stores,
            suite=self._suite,
            ordered_calls=self.authority.ordered_calls,
        )
        selected_states, intent_count, result_count = _measure_canary_state(
            scheduler=self._scheduler,
            run_stores=self._run_stores,
            suite=self._suite,
            journal=self._journal,
            ordered_calls=self.authority.ordered_calls,
        )
        receipts = tuple(
            state.terminal_evidence_sha256
            for state in selected_states
            if state.phase is SchedulerCallPhase.COMMITTED
        )
        if any(value is None for value in receipts):
            _fail("publishable_canary_terminal_receipt_missing")
        exact_receipts = tuple(value for value in receipts if value is not None)
        paired = (
            _paired_path_evidence(
                self.authority.ordered_calls,
                exact_receipts,
                paired_path_authority_sha256=self.paired_path_authority_sha256,
            )
            if len(exact_receipts) == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            else None
        )
        return PublishableCanaryMeasurement(
            committed_call_count=len(exact_receipts),
            provider_intent_count=intent_count,
            provider_result_count=result_count,
            ordered_receipt_sha256=exact_receipts,
            paired_path_evidence_sha256=paired,
        )

    def advance_one(self) -> PublishableCanaryMeasurement:
        """Make at most one provider attempt, or replay one durable result with zero calls."""

        before = self.measure()
        if before.complete:
            return before
        result = self._scheduler.runner.run_bounded(max_dispatches=1)
        if result.disposition not in {SchedulerStepDisposition.COMMITTED}:
            _fail("publishable_canary_execution_not_complete")
        after = self.measure()
        if (
            after.committed_call_count != before.committed_call_count + 1
            or after.provider_intent_count - before.provider_intent_count not in (0, 1)
            or after.provider_result_count < before.provider_result_count
        ):
            _fail("publishable_canary_execution_accounting_invalid")
        return after

    def __repr__(self) -> str:
        return (
            "PublishableCanaryComposition("
            f"open_mode={self.open_mode.value!r}, "
            f"authority_sha256={self.authority_sha256!r}, "
            "private_capabilities=<bound>)"
        )


def open_publishable_canary_composition(
    *,
    mode: PublishableProductionOpenMode,
    suite: SchedulerSuiteAuthority,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    extraction_suite: PublishableExtractionSuiteReadback,
    official_case_authority: SchedulerOfficialCaseReaderPort,
    retrieval_capture_authority: SchedulerRetrievalEvidenceReaderPort,
    output_cipher: Aes256GcmOutputCipher,
    bridge_keys: BridgeSecretCapability,
    bridge_fleet_readiness: BridgeFleetReadinessReceipt,
    bridge_transport: BridgeTransportPort,
    bridge_journal: BridgeJournal,
    clock,
    lease_id_factory,
    suite_seal_store: SchedulerSuiteSealStoreSpec,
    lease_duration_ms: int = 60_000,
) -> PublishableCanaryComposition:
    """Authenticate production authorities and open without performing a provider call."""

    if (
        type(mode) is not PublishableProductionOpenMode
        or type(suite) is not SchedulerSuiteAuthority
        or type(run_stores) is not tuple
        or len(run_stores) != 2
        or any(type(item) is not SchedulerRunStoreSpec for item in run_stores)
        or type(extraction_suite) is not PublishableExtractionSuiteReadback
        or type(output_cipher) is not Aes256GcmOutputCipher
        or type(bridge_fleet_readiness) is not BridgeFleetReadinessReceipt
        or type(bridge_journal) is not BridgeJournal
        or type(suite_seal_store) is not SchedulerSuiteSealStoreSpec
        or not callable(clock)
        or not callable(lease_id_factory)
        or type(lease_duration_ms) is not int
        or lease_duration_ms < 1
    ):
        _fail("publishable_canary_composition_inputs_invalid")
    try:
        canary_authority = bind_publishable_canary_authority(
            suite=suite,
            manifest=run_stores[0].manifest,
        )
    except Exception:
        _fail("publishable_canary_authority_invalid")
    _require_store_generation(mode, run_stores, suite_seal_store)
    bridge_journal.audit()
    if mode is PublishableProductionOpenMode.CREATE:
        statistics = bridge_journal.statistics()
        if statistics.event_count != 0:
            _fail("publishable_canary_create_journal_not_empty")

    extraction_terminals = PublishableExtractionSuiteTerminalAdapter(
        suite=suite,
        run_stores=run_stores,
        readback=extraction_suite,
    )
    selected_extraction = extraction_terminals.read_terminal(run=run_stores[0].run)
    runtime_provenance = build_publishable_production_runtime_provenance(
        suite=suite,
        bridge_fleet_readiness=bridge_fleet_readiness,
    )
    dispatch_authority = SchedulerDispatchAuthority(
        suite_authority_sha256=suite.commitment_sha256,
        ordered_calls=canary_authority.ordered_calls,
    )
    scheduler = open_scheduler_subscription_bridge_composition(
        suite=suite,
        run_stores=run_stores,
        case_reader=official_case_authority,
        retrieval_reader=retrieval_capture_authority,
        output_cipher=output_cipher,
        bridge_keys=bridge_keys,
        bridge_fleet_readiness=bridge_fleet_readiness,
        bridge_transport=bridge_transport,
        bridge_journal=bridge_journal,
        extraction_terminal_reader=extraction_terminals,
        clock=clock,
        lease_id_factory=lease_id_factory,
        suite_seal_store=suite_seal_store,
        dispatch_authority=dispatch_authority,
        paired_outcome_sealing=False,
        lease_duration_ms=lease_duration_ms,
    )
    paired_path_authority_sha256 = _paired_path_authority(canary_authority.ordered_calls)
    composition_sha256 = commitment(
        "publishable-one-case-canary-composition",
        {
            "activation_only": True,
            "canary_authority_sha256": canary_authority.commitment_sha256,
            "case_authority_root_sha256": official_case_authority.authority_root_sha256,
            "dispatch_authority_sha256": dispatch_authority.commitment_sha256,
            "extraction_suite_readback_sha256": (extraction_suite.suite_readback_commitment_sha256),
            "ordered_run_authority_sha256": [item.run.commitment_sha256 for item in run_stores],
            "paired_outcome_sealing": False,
            "paired_path_authority_sha256": paired_path_authority_sha256,
            "private_output_policy_sha256": scheduler.renderer.private_answer_policy_sha256,
            "renderer_policy_sha256": scheduler.renderer.renderer_policy_sha256,
            "retrieval_authority_root_sha256": retrieval_capture_authority.authority_root_sha256,
            "runtime_provenance": runtime_provenance.material(),
            "runtime_provenance_sha256": runtime_provenance.commitment_sha256,
            "schema_version": PUBLISHABLE_CANARY_COMPOSITION_SCHEMA,
            "selected_extraction_terminal_sha256": selected_extraction.commitment_sha256,
            "suite_authority_sha256": suite.commitment_sha256,
        },
    )
    composition = PublishableCanaryComposition(
        _scheduler=scheduler,
        _dispatch_authority=dispatch_authority,
        _run_stores=run_stores,
        _suite=suite,
        _journal=bridge_journal,
        authority=canary_authority,
        runtime_provenance=runtime_provenance,
        selected_extraction_terminal_sha256=selected_extraction.commitment_sha256,
        paired_path_authority_sha256=paired_path_authority_sha256,
        open_mode=mode,
        authority_sha256=composition_sha256,
    )
    measurement = composition.measure()
    if mode is PublishableProductionOpenMode.CREATE and (
        measurement.committed_call_count != 0
        or measurement.provider_intent_count != 0
        or measurement.provider_result_count != 0
    ):
        _fail("publishable_canary_create_state_invalid")
    return composition


def _measure_canary_state(
    *,
    scheduler: SchedulerSubscriptionBridgeComposition,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    suite: SchedulerSuiteAuthority,
    journal: BridgeJournal,
    ordered_calls: tuple[
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
    ],
) -> tuple[tuple[SchedulerCallState, ...], int, int]:
    selected_ids = tuple(item.logical_call_id for item in ordered_calls)
    spec = run_stores[0]
    store = SQLiteDurableSchedulerStore(
        spec.database_path,
        private_directory=spec.private_directory,
        authentication_secret=spec.authentication_secret,
        suite=suite,
        run=spec.run,
        manifest=spec.manifest,
    )
    states = tuple(store.read_call(logical_call_id) for logical_call_id in selected_ids)
    observed_intents = 0
    observed_results = 0
    for ordinal, state in enumerate(states):
        if state.logical_call_id != selected_ids[ordinal] or state.ordinal != ordinal:
            _fail("publishable_canary_selected_call_crosswire")
        outcome = scheduler.subscription_bridge.lookup_logical_call(state.logical_call_id)
        observed_intents += outcome is not None
        observed_results += type(outcome) is TerminalBridgeCall
        _require_call_journal_binding(store=store, state=state, outcome=outcome)
    committed = 0
    noncommitted_seen = False
    for state in states:
        if state.phase is SchedulerCallPhase.COMMITTED:
            if noncommitted_seen:
                _fail("publishable_canary_committed_prefix_invalid")
            committed += 1
        else:
            noncommitted_seen = True
        if state.phase in {
            SchedulerCallPhase.FAILED_KNOWN,
            SchedulerCallPhase.OUTCOME_UNKNOWN,
        }:
            _fail("publishable_canary_terminal_failure")
    statistics = journal.statistics()
    if (
        statistics.intent_count != observed_intents
        or statistics.result_count != observed_results
        or statistics.event_count != observed_intents + observed_results
        or not 0
        <= committed
        <= observed_results
        <= observed_intents
        <= PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
    ):
        _fail("publishable_canary_journal_accounting_invalid")
    return states, observed_intents, observed_results


def _audit_scope_heads(
    *,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    suite: SchedulerSuiteAuthority,
    ordered_calls: tuple[
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
    ],
) -> None:
    """Reject any durable transition not accounted for by the four selected rows."""

    selected_ids = tuple(item.logical_call_id for item in ordered_calls)
    for run_index, spec in enumerate(run_stores):
        store = SQLiteDurableSchedulerStore(
            spec.database_path,
            private_directory=spec.private_directory,
            authentication_secret=spec.authentication_secret,
            suite=suite,
            run=spec.run,
            manifest=spec.manifest,
        )
        run = store.read_run()
        if run.phase is not SchedulerRunPhase.ACTIVE:
            _fail("publishable_canary_scope_exceeded")

        allowed_ids = frozenset(selected_ids) if run_index == 0 else frozenset()
        latest_call_versions: dict[str, int] = {}
        event_id = 0
        last_run_version = 0
        previous_event_sha256: str | None = None
        while True:
            page = store.read_events(after_event_id=event_id, limit=RUNNER_PAGE_SIZE)
            for observed in page:
                event_id += 1
                if (
                    observed.event_id != event_id
                    or observed.run_id != spec.run.binding.run_id
                    or previous_event_sha256 is not None
                    and observed.previous_event_sha256 != previous_event_sha256
                ):
                    _fail("publishable_canary_scope_exceeded")
                if observed.event_id == 1:
                    if (
                        observed.logical_call_id is not None
                        or observed.event_kind != "manifest_initialized"
                        or observed.run_version != 0
                        or observed.call_version is not None
                    ):
                        _fail("publishable_canary_scope_exceeded")
                elif observed.logical_call_id not in allowed_ids or observed.call_version is None:
                    _fail("publishable_canary_scope_exceeded")
                else:
                    latest_call_versions[observed.logical_call_id] = observed.call_version
                last_run_version = observed.run_version
                previous_event_sha256 = observed.event_sha256
            if len(page) < RUNNER_PAGE_SIZE:
                break
        if event_id < 1 or last_run_version != run.version:
            _fail("publishable_canary_scope_exceeded")

        if run_index == 1:
            if (
                event_id != 1
                or run.version != 0
                or run.reserved_tokens != 0
                or run.consumed_tokens != 0
                or run.burned_tokens != 0
                or run.inflight_logical_call_id is not None
            ):
                _fail("publishable_canary_scope_exceeded")
            continue

        states = tuple(store.read_call(logical_call_id) for logical_call_id in selected_ids)
        inflight = tuple(
            state
            for state in states
            if state.phase
            in {
                SchedulerCallPhase.LEASED,
                SchedulerCallPhase.REQUEST_BOUND,
                SchedulerCallPhase.DISPATCH_INTENT,
            }
        )
        if (
            any(
                latest_call_versions.get(state.logical_call_id, 0) != state.version
                for state in states
            )
            or run.reserved_tokens
            != sum(
                state.token_ceiling
                for state in inflight
                if state.phase
                in {
                    SchedulerCallPhase.REQUEST_BOUND,
                    SchedulerCallPhase.DISPATCH_INTENT,
                }
            )
            or not 0 <= run.consumed_tokens <= sum(state.charged_tokens for state in states)
            or run.burned_tokens != 0
            or len(inflight) > 1
            or run.inflight_logical_call_id
            != (None if not inflight else inflight[0].logical_call_id)
        ):
            _fail("publishable_canary_scope_exceeded")


def _paired_path_evidence(
    calls: tuple[
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
    ],
    receipts: tuple[str, ...],
    *,
    paired_path_authority_sha256: str,
) -> str:
    if len(receipts) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT or tuple(
        item.stage for item in calls
    ) != (
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
    ):
        _fail("publishable_canary_paired_path_invalid")
    return commitment(
        "publishable-one-case-canary-paired-path",
        {
            "judgment_interpretation": "not-performed-activation-only",
            "paired_path_authority_sha256": paired_path_authority_sha256,
            "ordered_receipt_sha256": list(receipts),
            "quality_claimed": False,
            "schema_version": PUBLISHABLE_CANARY_PAIRED_PATH_SCHEMA,
        },
    )


def _paired_path_authority(
    calls: tuple[
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
    ],
) -> str:
    if tuple(item.stage for item in calls) != (
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
        SchedulerCallStage.ANSWER,
        SchedulerCallStage.JUDGE,
    ):
        _fail("publishable_canary_paired_path_invalid")
    return commitment(
        "publishable-one-case-canary-paired-path-authority",
        {
            "judgment_interpretation": "not-performed-activation-only",
            "normalization_policy_sha256": PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
            "ordered_answer_logical_call_ids": [
                calls[0].logical_call_id,
                calls[2].logical_call_id,
            ],
            "ordered_backend_roles": [calls[0].backend_role, calls[2].backend_role],
            "ordered_judge_logical_call_ids": [
                calls[1].logical_call_id,
                calls[3].logical_call_id,
            ],
            "quality_claimed": False,
            "schema_version": PUBLISHABLE_CANARY_PAIRED_PATH_SCHEMA,
        },
    )


def _require_store_generation(
    mode: PublishableProductionOpenMode,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    seal_store: SchedulerSuiteSealStoreSpec,
) -> None:
    existing = tuple(
        path.exists()
        for path in (*tuple(item.database_path for item in run_stores), seal_store.database_path)
    )
    if mode is PublishableProductionOpenMode.CREATE and any(existing):
        _fail("publishable_canary_create_store_exists")
    if mode is PublishableProductionOpenMode.RESUME and not all(existing):
        _fail("publishable_canary_resume_store_missing")


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = (
    "PUBLISHABLE_CANARY_COMPOSITION_SCHEMA",
    "PUBLISHABLE_CANARY_PAIRED_PATH_SCHEMA",
    "PublishableCanaryComposition",
    "PublishableCanaryMeasurement",
    "open_publishable_canary_composition",
)
