"""Strict production root for the exact publishable two-benchmark evaluation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import final

from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    BridgeSecretCapability,
    BridgeTransportPort,
    OutcomeUnknown,
    TerminalBridgeCall,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.memory_comparison_publishable_go_readiness import (
    PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION,
    PublishableExecutionAuthority,
    PublishableExecutionOrchestrationAuthority,
    PublishableExecutionPolicyError,
    require_active_publishable_execution_authority,
    require_publishable_execution_authority_binding,
    reviewed_publishable_execution_binding,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SCHEDULER_ORDERED_BACKEND_ROLES,
    SCHEDULER_PAID_GO_READY,
    SchedulerBackendAuthority,
    SchedulerCallStage,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_PAGE_SIZE,
    SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY,
    SCHEDULER_RUNNER_PAID_GO_READY,
    SCHEDULER_RUNNER_PUBLISHABLE,
    SCHEDULER_RUNNER_READINESS_BLOCKERS,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerSuiteSealStoreSpec,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerOfficialCaseReaderPort,
    SchedulerRetrievalEvidenceReaderPort,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SQLITE_SCHEDULER_PAID_GO_READY,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
)

from .paired_outcome_production import (
    PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256,
)
from .publishable_extraction_terminal_adapter import (
    PublishableExtractionSuiteTerminalAdapter,
)
from .scheduler_subscription_bridge_adapter import (
    bridge_pool_authority_from_fleet_readiness,
    build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness,
    verify_fleet_launch_receipts,
)
from .scheduler_subscription_bridge_composition import (
    SchedulerSubscriptionBridgeComposition,
    open_scheduler_subscription_bridge_composition,
)

PUBLISHABLE_PRODUCTION_COMPOSITION_SCHEMA = (
    "memory-comparison-publishable-production-composition.v3"
)
PUBLISHABLE_PRODUCTION_RUNTIME_PROVENANCE_SCHEMA = (
    "memory-comparison-publishable-production-runtime-provenance.v1"
)


def publishable_production_execution_orchestration_authority() -> (
    PublishableExecutionOrchestrationAuthority
):
    """Commit every static paid-execution fact exposed by this composition."""

    return PublishableExecutionOrchestrationAuthority(
        schema_version=PUBLISHABLE_PRODUCTION_COMPOSITION_SCHEMA,
        profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        profile_commitment_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_id=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
        methodology_commitment_sha256=(PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256),
        scheduler_paid_go_ready=SCHEDULER_PAID_GO_READY,
        runner_paid_go_ready=SCHEDULER_RUNNER_PAID_GO_READY,
        durable_store_paid_go_ready=SQLITE_SCHEDULER_PAID_GO_READY,
        production_bridge_adapter_ready=SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY,
        paired_outcome_sealing_policy_sha256=(PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256),
        publishable=SCHEDULER_RUNNER_PUBLISHABLE,
        readiness_blockers=SCHEDULER_RUNNER_READINESS_BLOCKERS,
    )


def require_publishable_production_execution_authority(
    authority: PublishableExecutionAuthority,
    *,
    suite: SchedulerSuiteAuthority,
) -> None:
    """Recompute and bind one static admission to the exact production suite."""

    try:
        if (
            PUBLISHABLE_PRODUCTION_COMPOSITION_SCHEMA
            != PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION
            or type(suite) is not SchedulerSuiteAuthority
        ):
            raise TypeError
        orchestration = publishable_production_execution_orchestration_authority()
        active_authority = require_active_publishable_execution_authority(orchestration)
        require_publishable_execution_authority_binding(
            authority,
            orchestration=orchestration,
            review=reviewed_publishable_execution_binding(),
            suite_methodology_sha256=suite.methodology_sha256,
        )
        if authority.commitment_sha256 != active_authority.commitment_sha256:
            raise TypeError
    except PublishableExecutionPolicyError:
        _fail("publishable_production_execution_authority_invalid")
    except Exception:
        _fail("publishable_production_execution_authority_invalid")


def _require_active_publishable_production_execution(
    suite: SchedulerSuiteAuthority,
) -> None:
    """Recompute static readiness at the non-bypassable composition root."""

    try:
        orchestration = publishable_production_execution_orchestration_authority()
        authority = require_active_publishable_execution_authority(orchestration)
        require_publishable_execution_authority_binding(
            authority,
            orchestration=orchestration,
            review=reviewed_publishable_execution_binding(),
            suite_methodology_sha256=suite.methodology_sha256,
        )
    except Exception:
        _fail("publishable_production_execution_authority_invalid")


class PublishableProductionOpenMode(StrEnum):
    CREATE = "create"
    RESUME = "resume"


@final
@dataclass(frozen=True, slots=True)
class PublishableProductionBridgeProvenance:
    """One ordered fleet member admitted to the production scheduler."""

    bridge_index: int
    bridge_id: str
    account_name: str
    bridge_authority_sha256: str
    runtime_authority_sha256: str
    readiness_receipt_sha256: str
    public_model: str
    reasoning_effort: str
    service_tier: str
    base_instructions_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.bridge_index) is not int
            or self.bridge_index not in (0, 1, 2)
            or type(self.bridge_id) is not str
            or not self.bridge_id
            or type(self.account_name) is not str
            or not self.account_name
            or any(
                not is_sha256(value)
                for value in (
                    self.bridge_authority_sha256,
                    self.runtime_authority_sha256,
                    self.readiness_receipt_sha256,
                    self.base_instructions_sha256,
                )
            )
            or self.public_model != "gpt-5.6-sol"
            or self.reasoning_effort != "high"
            or self.service_tier != "priority"
        ):
            _fail("publishable_production_runtime_provenance_invalid")

    def material(self) -> dict[str, object]:
        return {
            "account_name": self.account_name,
            "base_instructions_sha256": self.base_instructions_sha256,
            "bridge_authority_sha256": self.bridge_authority_sha256,
            "bridge_id": self.bridge_id,
            "bridge_index": self.bridge_index,
            "public_model": self.public_model,
            "readiness_receipt_sha256": self.readiness_receipt_sha256,
            "reasoning_effort": self.reasoning_effort,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "service_tier": self.service_tier,
        }


@final
@dataclass(frozen=True, slots=True)
class PublishableProductionRuntimeProvenance:
    """Exact backend and launched-fleet admission material carried to terminal."""

    scheduler_runtime_provenance_sha256: str
    ordered_backend_identities: tuple[SchedulerBackendAuthority, SchedulerBackendAuthority]
    bridge_pool_authority_sha256: str
    bridge_fleet_readiness_sha256: str
    bridge_boot_nonce_sha256: str
    bridge_boot_authority_sha256: str
    ordered_bridges: tuple[
        PublishableProductionBridgeProvenance,
        PublishableProductionBridgeProvenance,
        PublishableProductionBridgeProvenance,
    ]
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.scheduler_runtime_provenance_sha256,
                    self.bridge_pool_authority_sha256,
                    self.bridge_fleet_readiness_sha256,
                    self.bridge_boot_nonce_sha256,
                    self.bridge_boot_authority_sha256,
                )
            )
            or self.bridge_boot_nonce_sha256 != self.bridge_fleet_readiness_sha256
            or type(self.ordered_backend_identities) is not tuple
            or len(self.ordered_backend_identities) != 2
            or any(
                type(item) is not SchedulerBackendAuthority
                for item in self.ordered_backend_identities
            )
            or tuple(item.backend_role for item in self.ordered_backend_identities)
            != SCHEDULER_ORDERED_BACKEND_ROLES
            or type(self.ordered_bridges) is not tuple
            or len(self.ordered_bridges) != 3
            or any(
                type(item) is not PublishableProductionBridgeProvenance
                for item in self.ordered_bridges
            )
            or tuple(item.bridge_index for item in self.ordered_bridges) != (0, 1, 2)
            or len({item.bridge_id for item in self.ordered_bridges}) != 3
            or len({item.account_name for item in self.ordered_bridges}) != 3
            or len({item.runtime_authority_sha256 for item in self.ordered_bridges}) != 3
        ):
            _fail("publishable_production_runtime_provenance_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("publishable-production-runtime-provenance", self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "bridge_boot_authority_sha256": self.bridge_boot_authority_sha256,
            "bridge_boot_nonce_sha256": self.bridge_boot_nonce_sha256,
            "bridge_fleet_readiness_sha256": self.bridge_fleet_readiness_sha256,
            "bridge_pool_authority_sha256": self.bridge_pool_authority_sha256,
            "ordered_backend_identities": [
                item.material() for item in self.ordered_backend_identities
            ],
            "ordered_bridges": [item.material() for item in self.ordered_bridges],
            "scheduler_runtime_provenance_sha256": (self.scheduler_runtime_provenance_sha256),
            "schema_version": PUBLISHABLE_PRODUCTION_RUNTIME_PROVENANCE_SCHEMA,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableProductionComposition:
    """Exact production capabilities; the only dispatch path is the bridge."""

    scheduler: SchedulerSubscriptionBridgeComposition = field(repr=False)
    extraction_terminals: PublishableExtractionSuiteTerminalAdapter = field(repr=False)
    runtime_provenance: PublishableProductionRuntimeProvenance
    open_mode: PublishableProductionOpenMode
    authority_sha256: str

    def __post_init__(self) -> None:
        try:
            PublishableProductionRuntimeProvenance.__post_init__(self.runtime_provenance)
        except Exception:
            _fail("publishable_production_composition_invalid")
        if (
            type(self.scheduler) is not SchedulerSubscriptionBridgeComposition
            or type(self.extraction_terminals) is not PublishableExtractionSuiteTerminalAdapter
            or type(self.runtime_provenance) is not PublishableProductionRuntimeProvenance
            or type(self.open_mode) is not PublishableProductionOpenMode
            or not is_sha256(self.authority_sha256)
            or self.runtime_provenance.scheduler_runtime_provenance_sha256
            != self.scheduler.scheduler_bridge.scheduler_runtime_provenance_sha256
            or self.runtime_provenance.bridge_fleet_readiness_sha256
            != self.scheduler.scheduler_bridge.fleet_readiness_sha256
            or self.runtime_provenance.bridge_boot_authority_sha256
            != self.scheduler.scheduler_bridge.bridge_boot_authority_sha256
            or self.runtime_provenance.bridge_pool_authority_sha256
            != self.scheduler.scheduler_bridge.pool_authority_sha256
            or self.scheduler.suite_seal_binding_policy_sha256
            != PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256
        ):
            _fail("publishable_production_composition_invalid")

    @property
    def runner(self):
        return self.scheduler.runner

    @property
    def fleet_readiness_sha256(self) -> str:
        return self.scheduler.scheduler_bridge.fleet_readiness_sha256

    @property
    def bridge_boot_authority_sha256(self) -> str:
        return self.scheduler.scheduler_bridge.bridge_boot_authority_sha256

    @property
    def bridge_pool_authority_sha256(self) -> str:
        return self.scheduler.scheduler_bridge.pool_authority_sha256

    @property
    def runtime_provenance_sha256(self) -> str:
        return self.runtime_provenance.commitment_sha256

    @property
    def admission_commitment_sha256(self) -> str:
        """The production composition authority admitted before any dispatch."""

        return self.authority_sha256

    def __repr__(self) -> str:
        return (
            "PublishableProductionComposition("
            f"open_mode={self.open_mode.value!r}, "
            f"authority_sha256={self.authority_sha256!r}, "
            f"runtime_provenance_sha256={self.runtime_provenance_sha256!r}, "
            f"fleet_readiness_sha256={self.fleet_readiness_sha256!r}, "
            "private_capabilities=<bound>)"
        )


def open_publishable_production_composition(
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
    clock: Callable[[], int],
    lease_id_factory: Callable[[], str],
    suite_seal_store: SchedulerSuiteSealStoreSpec | None = None,
    lease_duration_ms: int = 60_000,
) -> PublishableProductionComposition:
    """Open one exact durable bundle without performing a transport call.

    ``CREATE`` refuses any scheduler residue. ``RESUME`` refuses a missing store;
    after opening, every scheduler call is reconciled against the authenticated
    bridge journal in pages capped by ``RUNNER_PAGE_SIZE``.
    """

    _require_active_publishable_production_execution(suite)
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
        or suite_seal_store is not None
        and type(suite_seal_store) is not SchedulerSuiteSealStoreSpec
        or not callable(clock)
        or not callable(lease_id_factory)
        or type(lease_duration_ms) is not int
        or lease_duration_ms < 1
    ):
        _fail("publishable_production_composition_invalid")

    bridge_pool = verify_fleet_launch_receipts(bridge_fleet_readiness, bridge_keys)
    runtime_provenance = build_publishable_production_runtime_provenance(
        suite=suite,
        bridge_fleet_readiness=bridge_fleet_readiness,
    )
    expected_boot = suite.bridge_boot

    seal_spec = suite_seal_store or SchedulerSuiteSealStoreSpec(
        database_path=run_stores[0].private_directory / "suite-seal.sqlite3",
        private_directory=run_stores[0].private_directory,
        authentication_secret=run_stores[0].authentication_secret,
    )
    _require_store_generation(mode=mode, run_stores=run_stores, seal_store=seal_spec)
    bridge_journal.audit()
    before = bridge_journal.statistics()
    if mode is PublishableProductionOpenMode.CREATE and before.event_count != 0:
        _fail("publishable_production_create_journal_not_empty")

    extraction_terminals = PublishableExtractionSuiteTerminalAdapter(
        suite=suite,
        run_stores=run_stores,
        readback=extraction_suite,
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
        suite_seal_store=seal_spec,
        paired_outcome_sealing=True,
        lease_duration_ms=lease_duration_ms,
    )
    _audit_bundle(
        mode=mode,
        suite=suite,
        run_stores=run_stores,
        journal=bridge_journal,
        scheduler=scheduler,
    )
    authority_sha256 = commitment(
        "publishable-production-composition",
        {
            "bridge_boot_authority_sha256": expected_boot.commitment_sha256,
            "bridge_fleet_readiness_sha256": bridge_fleet_readiness.commitment_sha256,
            "bridge_pool_authority_sha256": bridge_pool.commitment_sha256,
            "case_authority_root_sha256": official_case_authority.authority_root_sha256,
            "cipher": "aes-256-gcm-envelope-v1",
            "extraction_suite_readback_sha256": (extraction_suite.suite_readback_commitment_sha256),
            "ordered_run_authority_sha256": [item.run.commitment_sha256 for item in run_stores],
            "paired_outcome_sealing_policy_sha256": (
                PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256
            ),
            "private_output_policy_sha256": scheduler.renderer.private_answer_policy_sha256,
            "renderer_policy_sha256": scheduler.renderer.renderer_policy_sha256,
            "retrieval_authority_root_sha256": (retrieval_capture_authority.authority_root_sha256),
            "runtime_provenance": runtime_provenance.material(),
            "runtime_provenance_sha256": runtime_provenance.commitment_sha256,
            "schema_version": PUBLISHABLE_PRODUCTION_COMPOSITION_SCHEMA,
            "suite_authority_sha256": suite.commitment_sha256,
        },
    )
    return PublishableProductionComposition(
        scheduler=scheduler,
        extraction_terminals=extraction_terminals,
        runtime_provenance=runtime_provenance,
        open_mode=mode,
        authority_sha256=authority_sha256,
    )


def build_publishable_production_runtime_provenance(
    *,
    suite: SchedulerSuiteAuthority,
    bridge_fleet_readiness: BridgeFleetReadinessReceipt,
) -> PublishableProductionRuntimeProvenance:
    """Authenticate exact production runtime material before opening durable state."""

    if (
        type(suite) is not SchedulerSuiteAuthority
        or type(bridge_fleet_readiness) is not BridgeFleetReadinessReceipt
    ):
        _fail("publishable_production_runtime_provenance_mismatch")
    bridge_pool = bridge_pool_authority_from_fleet_readiness(bridge_fleet_readiness)
    expected_boot = build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
        bridge_fleet_readiness
    )
    if (
        suite.bridge_boot != expected_boot
        or suite.commitment_sha256 != commitment("suite", suite.material())
        or suite.ordered_runs[0].backends != suite.ordered_runs[1].backends
    ):
        _fail("publishable_production_runtime_provenance_mismatch")
    ordered_bridges = tuple(
        PublishableProductionBridgeProvenance(
            bridge_index=index,
            bridge_id=bridge.bridge_id,
            account_name=launch.pending.account_name,
            bridge_authority_sha256=bridge.commitment_sha256,
            runtime_authority_sha256=launch.runtime_authority_sha256,
            readiness_receipt_sha256=launch.commitment_sha256,
            public_model=bridge.public_model,
            reasoning_effort=bridge.REASONING_EFFORT,
            service_tier=bridge.SERVICE_TIER,
            base_instructions_sha256=bridge.base_instructions_sha256,
        )
        for index, (bridge, launch) in enumerate(
            zip(bridge_pool.bridges, bridge_fleet_readiness.launches, strict=True)
        )
    )
    return PublishableProductionRuntimeProvenance(
        scheduler_runtime_provenance_sha256=suite.runtime_provenance_sha256,
        ordered_backend_identities=suite.ordered_backend_identities,
        bridge_pool_authority_sha256=bridge_pool.commitment_sha256,
        bridge_fleet_readiness_sha256=bridge_fleet_readiness.commitment_sha256,
        bridge_boot_nonce_sha256=expected_boot.boot_nonce_sha256,
        bridge_boot_authority_sha256=expected_boot.commitment_sha256,
        ordered_bridges=ordered_bridges,
    )


def _require_store_generation(
    *,
    mode: PublishableProductionOpenMode,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    seal_store: SchedulerSuiteSealStoreSpec,
) -> None:
    paths = tuple(item.database_path for item in run_stores) + (seal_store.database_path,)
    existing = tuple(path.exists() for path in paths)
    if mode is PublishableProductionOpenMode.CREATE and any(existing):
        _fail("publishable_production_create_store_exists")
    if mode is PublishableProductionOpenMode.RESUME and not all(existing):
        _fail("publishable_production_resume_store_missing")


def _audit_bundle(
    *,
    mode: PublishableProductionOpenMode,
    suite: SchedulerSuiteAuthority,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    journal: BridgeJournal,
    scheduler: SchedulerSubscriptionBridgeComposition,
) -> None:
    if mode is PublishableProductionOpenMode.CREATE:
        statistics = journal.statistics()
        if statistics.event_count != 0 or scheduler.runner.committed_call_count() != 0:
            _fail("publishable_production_create_state_invalid")
        return
    observed_intents = 0
    observed_results = 0
    for spec in run_stores:
        store = SQLiteDurableSchedulerStore(
            spec.database_path,
            private_directory=spec.private_directory,
            authentication_secret=spec.authentication_secret,
            suite=suite,
            run=spec.run,
            manifest=spec.manifest,
        )
        after = -1
        while True:
            page = store.read_calls(after_ordinal=after, limit=RUNNER_PAGE_SIZE)
            for state in page:
                outcome = scheduler.subscription_bridge.lookup_logical_call(state.logical_call_id)
                if outcome is not None:
                    observed_intents += 1
                if type(outcome) is TerminalBridgeCall:
                    observed_results += 1
                _require_call_journal_binding(store=store, state=state, outcome=outcome)
            if len(page) < RUNNER_PAGE_SIZE:
                break
            after = page[-1].ordinal
    statistics = journal.statistics()
    if observed_intents != statistics.intent_count or observed_results != statistics.result_count:
        _fail("publishable_production_bundle_journal_divergent")


def _require_call_journal_binding(*, store, state, outcome: object) -> None:
    no_bridge_state = state.phase in {
        SchedulerCallPhase.PLANNED,
        SchedulerCallPhase.LEASED,
        SchedulerCallPhase.REQUEST_BOUND,
        SchedulerCallPhase.FAILED_KNOWN,
    }
    if no_bridge_state:
        if outcome is not None:
            _fail("publishable_production_bundle_journal_divergent")
        return
    if state.phase is SchedulerCallPhase.DISPATCH_INTENT and outcome is None:
        # A hard death may occur after the scheduler fsync and before the bridge
        # observes the call.  The runner's generation-bound reconciliation will
        # authenticate this exact absence after lease expiry.
        return
    if state.phase not in {
        SchedulerCallPhase.DISPATCH_INTENT,
        SchedulerCallPhase.COMMITTED,
        SchedulerCallPhase.OUTCOME_UNKNOWN,
    }:
        _fail("publishable_production_bundle_state_invalid")
    if outcome is None:
        _fail("publishable_production_bundle_journal_missing")
    if type(outcome) is TerminalBridgeCall:
        intent = outcome.readback.intent
        result = outcome.readback.result
        if outcome.transport_dispatched is not False:
            _fail("publishable_production_bundle_readback_invalid")
    elif type(outcome) is OutcomeUnknown:
        intent = outcome.intent
        result = None
    else:
        _fail("publishable_production_bundle_readback_invalid")
    if (
        intent.binding.logical_call_id != state.logical_call_id
        or intent.binding.intent_id != state.intent_sha256
    ):
        _fail("publishable_production_bundle_intent_divergent")
    if state.stage is SchedulerCallStage.ANSWER:
        if intent.binding.logical_operation != "scheduler-answer:no-dependency":
            _fail("publishable_production_bundle_intent_divergent")
    else:
        dependency = store.read_private_answer_ciphertext(state.depends_on_logical_call_id or "")
        expected = f"scheduler-judge:{hashlib.sha256(dependency).hexdigest()}"
        if intent.binding.logical_operation != expected:
            _fail("publishable_production_bundle_intent_divergent")
    if state.phase is SchedulerCallPhase.COMMITTED:
        if type(outcome) is not TerminalBridgeCall or result is None:
            _fail("publishable_production_bundle_terminal_missing")
        if state.stage is SchedulerCallStage.ANSWER:
            persisted = store.read_private_answer_ciphertext(state.logical_call_id)
            if persisted != result.encrypted_output:
                _fail("publishable_production_bundle_ciphertext_divergent")


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = (
    "PUBLISHABLE_PRODUCTION_COMPOSITION_SCHEMA",
    "PUBLISHABLE_PRODUCTION_RUNTIME_PROVENANCE_SCHEMA",
    "PublishableProductionBridgeProvenance",
    "PublishableProductionComposition",
    "PublishableProductionOpenMode",
    "PublishableProductionRuntimeProvenance",
    "build_publishable_production_runtime_provenance",
    "open_publishable_production_composition",
    "publishable_production_execution_orchestration_authority",
    "require_publishable_production_execution_authority",
)
