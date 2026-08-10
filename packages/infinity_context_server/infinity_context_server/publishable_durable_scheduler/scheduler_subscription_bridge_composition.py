"""Dependency-injected production composition for the scheduler bridge seam."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeJournal,
    BridgeSecretCapability,
    BridgeTransportPort,
    OutputCipherPort,
    SubscriptionRuntimeBridgeAdapter,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_production import (
    PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256,
    PublishablePairedOutcomeSealBinder,
)
from infinity_context_server.publishable_durable_scheduler.resumable_runner import (
    PublishableResumableEvaluationRunner,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerExtractionTerminalReadPort,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerSuiteSealStoreSpec,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP,
    PublishableOfficialRequestRenderer,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
    SchedulerOfficialCaseReaderPort,
    SchedulerOfficialRendererComposition,
    SchedulerPrivateOutputDecryptPort,
    SchedulerRetrievalEvidenceReaderPort,
)

from .scheduler_subscription_bridge_adapter import (
    SchedulerSubscriptionBridgeAdapter,
    verify_fleet_launch_receipts,
)
from .scheduler_subscription_bridge_private_output import (
    SchedulerSubscriptionBridgePrivateOutputDecryptor,
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerSubscriptionBridgeComposition:
    """The three reviewed ports and runner produced by one composition root."""

    runner: PublishableResumableEvaluationRunner = field(repr=False)
    renderer: PublishableOfficialRequestRenderer = field(repr=False)
    scheduler_bridge: SchedulerSubscriptionBridgeAdapter = field(repr=False)
    subscription_bridge: SubscriptionRuntimeBridgeAdapter = field(repr=False)
    suite_seal_binding_policy_sha256: str | None

    def __post_init__(self) -> None:
        if (
            type(self.runner) is not PublishableResumableEvaluationRunner
            or type(self.renderer) is not PublishableOfficialRequestRenderer
            or type(self.scheduler_bridge) is not SchedulerSubscriptionBridgeAdapter
            or type(self.subscription_bridge) is not SubscriptionRuntimeBridgeAdapter
            or self.suite_seal_binding_policy_sha256
            not in (None, PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256)
        ):
            _fail("scheduler_subscription_bridge_composition_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerSubscriptionBridgeComposition("
            f"suite_authority_sha256={self.scheduler_bridge.suite_authority_sha256!r}, "
            "private_capabilities=<bound>)"
        )


def open_scheduler_subscription_bridge_composition(
    *,
    suite: SchedulerSuiteAuthority,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    case_reader: SchedulerOfficialCaseReaderPort,
    retrieval_reader: SchedulerRetrievalEvidenceReaderPort,
    output_cipher: OutputCipherPort,
    bridge_keys: BridgeSecretCapability,
    bridge_fleet_readiness: BridgeFleetReadinessReceipt,
    bridge_transport: BridgeTransportPort,
    bridge_journal: BridgeJournal,
    extraction_terminal_reader: SchedulerExtractionTerminalReadPort,
    clock: Callable[[], int],
    lease_id_factory: Callable[[], str],
    private_output_decryptor: SchedulerPrivateOutputDecryptPort | None = None,
    suite_seal_store: SchedulerSuiteSealStoreSpec | None = None,
    paired_outcome_sealing: bool = False,
    lease_duration_ms: int = 60_000,
    maximum_request_bytes: int = SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP,
    maximum_response_bytes: int = SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
) -> SchedulerSubscriptionBridgeComposition:
    """Compose official rendering, atomic bridge ports, and the finalized runner.

    Every secret-bearing or private-material capability is supplied explicitly.
    Opening performs no provider or transport call.
    """

    if (
        type(suite) is not SchedulerSuiteAuthority
        or type(bridge_fleet_readiness) is not BridgeFleetReadinessReceipt
        or type(bridge_journal) is not BridgeJournal
        or type(paired_outcome_sealing) is not bool
        or not callable(clock)
        or not callable(lease_id_factory)
        or type(maximum_request_bytes) is not int
        or not SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP <= maximum_request_bytes <= 16 * 1024 * 1024
        or type(maximum_response_bytes) is not int
        or not 1 <= maximum_response_bytes <= SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP
    ):
        _fail("scheduler_subscription_bridge_composition_invalid")
    bridge_pool = verify_fleet_launch_receipts(bridge_fleet_readiness, bridge_keys)

    subscription_bridge = SubscriptionRuntimeBridgeAdapter(
        pool=bridge_pool,
        secrets=bridge_keys,
        transport=bridge_transport,
        journal=bridge_journal,
        output_cipher=output_cipher,
        maximum_request_bytes=maximum_request_bytes,
        maximum_response_bytes=maximum_response_bytes,
    )
    decryptor = private_output_decryptor
    if decryptor is None:
        decryptor = SchedulerSubscriptionBridgePrivateOutputDecryptor(
            suite=suite,
            bridge=subscription_bridge,
        )
    renderer_composition = SchedulerOfficialRendererComposition(
        case_reader=case_reader,
        retrieval_reader=retrieval_reader,
        private_output_decryptor=decryptor,
        case_authority_root_sha256=case_reader.authority_root_sha256,
        retrieval_authority_root_sha256=retrieval_reader.authority_root_sha256,
        private_output_decrypt_policy_sha256=decryptor.policy_sha256,
    )
    renderer = PublishableOfficialRequestRenderer(
        suite=suite,
        composition=renderer_composition,
    )
    scheduler_bridge = SchedulerSubscriptionBridgeAdapter(
        suite=suite,
        fleet_readiness=bridge_fleet_readiness,
        bridge=subscription_bridge,
        keys=bridge_keys,
    )
    if (
        type(run_stores) is not tuple
        or len(run_stores) != 2
        or any(type(item) is not SchedulerRunStoreSpec for item in run_stores)
        or suite_seal_store is not None
        and type(suite_seal_store) is not SchedulerSuiteSealStoreSpec
    ):
        _fail("scheduler_subscription_bridge_composition_invalid")
    selected_seal_store = suite_seal_store or SchedulerSuiteSealStoreSpec(
        database_path=run_stores[0].private_directory / "suite-seal.sqlite3",
        private_directory=run_stores[0].private_directory,
        authentication_secret=run_stores[0].authentication_secret,
    )
    seal_binding = (
        PublishablePairedOutcomeSealBinder(
            suite=suite,
            run_stores=run_stores,
            case_reader=case_reader,
            bridge=subscription_bridge,
            terminal_authentication_secret=selected_seal_store.authentication_secret,
        )
        if paired_outcome_sealing
        else None
    )
    runner = PublishableResumableEvaluationRunner.open(
        suite=suite,
        run_stores=run_stores,
        request_renderer=renderer,
        boundary=scheduler_bridge,
        receipt_verifier=scheduler_bridge,
        extraction_terminal_reader=extraction_terminal_reader,
        reconciliation=scheduler_bridge,
        suite_seal_store=selected_seal_store,
        suite_seal_binding=seal_binding,
        clock=clock,
        lease_id_factory=lease_id_factory,
        lease_duration_ms=lease_duration_ms,
    )
    return SchedulerSubscriptionBridgeComposition(
        runner=runner,
        renderer=renderer,
        scheduler_bridge=scheduler_bridge,
        subscription_bridge=subscription_bridge,
        suite_seal_binding_policy_sha256=(
            PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256 if paired_outcome_sealing else None
        ),
    )


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "SchedulerSubscriptionBridgeComposition",
    "open_scheduler_subscription_bridge_composition",
)
