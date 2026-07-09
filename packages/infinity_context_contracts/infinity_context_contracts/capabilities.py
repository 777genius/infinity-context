"""Capability response public contract DTO stubs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ._json import JsonObject, JsonValue, json_compatible


@dataclass(frozen=True, slots=True)
class CapabilitiesResponseDto:
    """Top-level `/v1/capabilities` response shape.

    Nested sections stay as extension maps because their internals are still evolving.
    """

    service_name: str
    deploy_profile: str
    policy_mode: str
    api_version: str = "v1"
    server_version: str = "0.1.0"
    adapters: Mapping[str, Mapping[str, JsonValue]] = field(default_factory=dict)
    capabilities: Sequence[Mapping[str, JsonValue]] = field(default_factory=tuple)
    enabled_adapters: Sequence[str] = field(default_factory=tuple)
    supports_qdrant: bool = False
    supports_graphiti: bool = False
    supports_cognee: bool = False
    supports_legacy_client_routes: bool = False
    captures: Mapping[str, JsonValue] = field(default_factory=dict)
    suggestions: Mapping[str, JsonValue] = field(default_factory=dict)
    context: Mapping[str, JsonValue] = field(default_factory=dict)
    storage: Mapping[str, JsonValue] = field(default_factory=dict)
    extraction: Mapping[str, JsonValue] = field(default_factory=dict)
    plans: Mapping[str, JsonValue] = field(default_factory=dict)
    supported_policy_modes: Sequence[str] = field(default_factory=tuple)
    supported_embedding_models: Sequence[str] = field(default_factory=tuple)
    limits: Mapping[str, JsonValue] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "api_version": self.api_version,
            "server_version": self.server_version,
            "service_name": self.service_name,
            "deploy_profile": self.deploy_profile,
            "policy_mode": self.policy_mode,
            "adapters": json_compatible(self.adapters),
            "capabilities": json_compatible(self.capabilities),
            "enabled_adapters": json_compatible(self.enabled_adapters),
            "supports_qdrant": self.supports_qdrant,
            "supports_graphiti": self.supports_graphiti,
            "supports_cognee": self.supports_cognee,
            "supports_legacy_client_routes": self.supports_legacy_client_routes,
            "captures": json_compatible(self.captures),
            "suggestions": json_compatible(self.suggestions),
            "context": json_compatible(self.context),
            "storage": json_compatible(self.storage),
            "extraction": json_compatible(self.extraction),
            "plans": json_compatible(self.plans),
            "supported_policy_modes": json_compatible(self.supported_policy_modes),
            "supported_embedding_models": json_compatible(self.supported_embedding_models),
            "limits": json_compatible(self.limits),
        }
        for key, value in self.extensions.items():
            payload[str(key)] = json_compatible(value)
        return payload
