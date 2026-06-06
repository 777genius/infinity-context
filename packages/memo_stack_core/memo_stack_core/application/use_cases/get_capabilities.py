"""Capability discovery use case."""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_core.ports.adapters import AdapterCapabilities, MemoryAdapterPort
from memo_stack_core.ports.capabilities import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityStatus,
    MemoryCapability,
)


@dataclass(frozen=True)
class CapabilitiesResult:
    service_name: str
    deploy_profile: str
    policy_mode: str
    adapters: tuple[AdapterCapabilities, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    supported_policy_modes: tuple[str, ...]
    limits: dict[str, int]


class GetCapabilitiesUseCase:
    def __init__(
        self,
        *,
        service_name: str,
        deploy_profile: str,
        policy_mode: str,
        adapters: tuple[MemoryAdapterPort, ...],
        supported_policy_modes: tuple[str, ...],
        limits: dict[str, int],
    ) -> None:
        self._service_name = service_name
        self._deploy_profile = deploy_profile
        self._policy_mode = policy_mode
        self._adapters = adapters
        self._supported_policy_modes = supported_policy_modes
        self._limits = limits

    async def execute(self) -> CapabilitiesResult:
        adapters = []
        for adapter in self._adapters:
            adapters.append(await adapter.capabilities())
        return CapabilitiesResult(
            service_name=self._service_name,
            deploy_profile=self._deploy_profile,
            policy_mode=self._policy_mode,
            adapters=tuple(adapters),
            capabilities=tuple(_adapter_capability_descriptors(tuple(adapters))),
            supported_policy_modes=self._supported_policy_modes,
            limits=dict(self._limits),
        )


def _adapter_capability_descriptors(
    adapters: tuple[AdapterCapabilities, ...],
) -> tuple[CapabilityDescriptor, ...]:
    descriptors: list[CapabilityDescriptor] = []
    for adapter in adapters:
        if adapter.name == "qdrant":
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.VECTOR_RECALL,
                    supported=adapter.supports_search,
                    supports_scope_filter=adapter.supports_filters,
                )
            )
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.PROJECTION_FORGET,
                    supported=adapter.supports_delete,
                    supports_scope_filter=True,
                    supports_delete=adapter.supports_delete,
                )
            )
        elif adapter.name == "graphiti":
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.TEMPORAL_FACT_GRAPH,
                    supported=adapter.supports_search and adapter.supports_temporal_queries,
                    supports_scope_filter=adapter.supports_filters,
                    supports_update=adapter.supports_upsert,
                    supports_delete=adapter.supports_delete,
                )
            )
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.FACT_PROJECTION,
                    supported=adapter.supports_upsert,
                    supports_scope_filter=adapter.supports_filters,
                    supports_update=adapter.supports_upsert,
                )
            )
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.PROJECTION_FORGET,
                    supported=adapter.supports_delete,
                    supports_scope_filter=True,
                    supports_delete=adapter.supports_delete,
                )
            )
        elif adapter.name == "embeddings":
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.ENGINE_HEALTH,
                    supported=True,
                    supports_scope_filter=False,
                    external_ai_allowed=adapter.enabled,
                )
            )
        elif adapter.name == "cognee":
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.DOCUMENT_MEMORY,
                    supported=adapter.supports_upsert,
                    supports_scope_filter=adapter.supports_filters,
                    supports_source_refs=adapter.supports_upsert,
                    supports_delete=adapter.supports_delete,
                    external_ai_allowed=adapter.enabled,
                )
            )
            descriptors.append(
                _descriptor(
                    adapter,
                    MemoryCapability.RAG_RECALL,
                    supported=adapter.supports_search,
                    supports_scope_filter=adapter.supports_filters,
                    supports_source_refs=adapter.supports_search,
                    external_ai_allowed=adapter.enabled,
                )
            )
    return tuple(descriptors)


def _descriptor(
    adapter: AdapterCapabilities,
    capability: MemoryCapability,
    *,
    supported: bool,
    supports_scope_filter: bool,
    supports_source_refs: bool = False,
    supports_update: bool = False,
    supports_delete: bool = False,
    external_ai_allowed: bool = False,
) -> CapabilityDescriptor:
    status = _status_for(adapter, supported=supported)
    return CapabilityDescriptor(
        capability=capability,
        adapter_name=adapter.name,
        mode=(
            CapabilityMode.DISABLED
            if status == CapabilityStatus.DISABLED
            else CapabilityMode.PRIMARY
        ),
        status=status,
        enabled=adapter.enabled and supported,
        supports_scope_filter=supports_scope_filter,
        supports_source_refs=supports_source_refs,
        supports_update=supports_update,
        supports_delete=supports_delete,
        external_ai_allowed=external_ai_allowed,
        degraded_reason=_degraded_reason(adapter, status=status, supported=supported),
    )


def _status_for(adapter: AdapterCapabilities, *, supported: bool) -> CapabilityStatus:
    if not adapter.enabled:
        return CapabilityStatus.DISABLED
    if not adapter.healthy:
        return CapabilityStatus.UNAVAILABLE
    if not supported:
        return CapabilityStatus.DEGRADED
    return CapabilityStatus.OK


def _degraded_reason(
    adapter: AdapterCapabilities,
    *,
    status: CapabilityStatus,
    supported: bool,
) -> str | None:
    if status == CapabilityStatus.OK:
        return None
    if status == CapabilityStatus.DISABLED:
        return adapter.degraded_reason or "disabled"
    if not supported:
        return "unsupported_by_adapter"
    return adapter.degraded_reason or "adapter_unhealthy"
