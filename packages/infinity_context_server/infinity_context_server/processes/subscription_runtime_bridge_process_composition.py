"""Production process composition for the attested three-bridge scheduler pool."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.features.subscription_runtime_bridge.contracts import (
    BridgePoolAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
    BridgeFleetSpec,
    GracefulStopMetadata,
)
from infinity_context_server.features.subscription_runtime_bridge.process_control import (
    ProcessControlPort,
)
from infinity_context_server.features.subscription_runtime_bridge.process_launcher import (
    ProductionBridgeFleet,
)
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter as scheduler_bridge,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBridgeBootAuthority,
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class SubscriptionRuntimeBridgeProcessComposition:
    """A live pool whose scheduler boot nonce is its exact fleet readiness receipt."""

    fleet: ProductionBridgeFleet = field(repr=False)
    bridge_boot: SchedulerBridgeBootAuthority

    def __post_init__(self) -> None:
        if type(self.fleet) is not ProductionBridgeFleet:
            raise TypeError("subscription_runtime_process_fleet_invalid")
        expected_pool = scheduler_bridge.bridge_pool_authority_from_fleet_readiness(
            self.fleet.readiness
        )
        expected = scheduler_bridge.scheduler_bridge_boot_authority_from_fleet_readiness(
            self.fleet.readiness
        )
        if self.fleet.readiness.pool != expected_pool or self.bridge_boot != expected:
            raise ValueError("subscription_runtime_process_boot_authority_mismatch")

    @property
    def readiness(self) -> BridgeFleetReadinessReceipt:
        return self.fleet.readiness

    @property
    def bridge_pool(self) -> BridgePoolAuthority:
        """The exact ordered pool adapted from this launched fleet receipt."""

        return scheduler_bridge.bridge_pool_authority_from_fleet_readiness(self.readiness)

    @property
    def fleet_readiness_sha256(self) -> str:
        return self.readiness.commitment_sha256

    @property
    def bridge_pool_authority_sha256(self) -> str:
        return self.bridge_pool.commitment_sha256

    @property
    def bridge_boot_nonce_sha256(self) -> str:
        return self.bridge_boot.boot_nonce_sha256

    def stop_all(
        self, *, reason: str = "operator-shutdown"
    ) -> tuple[GracefulStopMetadata, GracefulStopMetadata, GracefulStopMetadata]:
        return self.fleet.stop_all(reason=reason)

    def close_controller(self) -> None:
        self.fleet.close_controller()

    def __repr__(self) -> str:
        return (
            "SubscriptionRuntimeBridgeProcessComposition("
            f"pool_authority_sha256={self.bridge_pool_authority_sha256!r}, "
            f"fleet_readiness_sha256={self.fleet_readiness_sha256!r}, "
            f"bridge_boot_authority_sha256={self.bridge_boot.commitment_sha256!r}, "
            "private_material=<bound>)"
        )


def create_new_subscription_runtime_bridge_processes(
    spec: BridgeFleetSpec,
    *,
    control: ProcessControlPort | None = None,
) -> SubscriptionRuntimeBridgeProcessComposition:
    """Launch three new processes and bind their exact readiness into scheduler boot."""

    return _compose(ProductionBridgeFleet.create_new(spec, control=control))


def reopen_subscription_runtime_bridge_processes(
    spec: BridgeFleetSpec,
    *,
    control: ProcessControlPort | None = None,
) -> SubscriptionRuntimeBridgeProcessComposition:
    """Reattach/restart the same durable roots without a provider readiness call."""

    return _compose(ProductionBridgeFleet.reopen(spec, control=control))


def _compose(fleet: ProductionBridgeFleet) -> SubscriptionRuntimeBridgeProcessComposition:
    try:
        bridge_boot = scheduler_bridge.scheduler_bridge_boot_authority_from_fleet_readiness(
            fleet.readiness
        )
        return SubscriptionRuntimeBridgeProcessComposition(
            fleet=fleet,
            bridge_boot=bridge_boot,
        )
    except BaseException:
        with suppress(Exception):
            fleet.stop_all(reason="composition-failure")
        raise


__all__ = (
    "SubscriptionRuntimeBridgeProcessComposition",
    "create_new_subscription_runtime_bridge_processes",
    "reopen_subscription_runtime_bridge_processes",
)
