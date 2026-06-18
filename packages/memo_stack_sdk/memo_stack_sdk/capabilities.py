"""Typed capability diagnostics for Memo Stack SDK clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionProfileCapability:
    name: str
    enabled: bool
    status: str
    providers: tuple[str, ...]
    input_modalities: tuple[str, ...]
    evidence_coordinates: tuple[str, ...]
    primary_artifact_types: tuple[str, ...]
    document_features: tuple[str, ...]
    vision_features: tuple[str, ...]
    transcript_features: tuple[str, ...]
    video_features: tuple[str, ...]
    external_provider_egress: bool
    requires_explicit_external_ai: bool
    fallback_profiles: tuple[str, ...]
    memory_promotion: str
    source_text_policy: str
    artifact_payloads_bounded: bool
    may_run_local_asr: bool = False
    reason: str | None = None
    deprecated: bool = False
    replacement_profiles: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ExtractionProfileCapability:
        return cls(
            name=str(payload.get("name") or ""),
            enabled=bool(payload.get("enabled", False)),
            status=str(payload.get("status") or "unknown"),
            providers=_strings(payload.get("providers")),
            input_modalities=_strings(payload.get("input_modalities")),
            evidence_coordinates=_strings(payload.get("evidence_coordinates")),
            primary_artifact_types=_strings(payload.get("primary_artifact_types")),
            document_features=_strings(payload.get("document_features")),
            vision_features=_strings(payload.get("vision_features")),
            transcript_features=_strings(payload.get("transcript_features")),
            video_features=_strings(payload.get("video_features")),
            external_provider_egress=bool(payload.get("external_provider_egress", False)),
            requires_explicit_external_ai=bool(
                payload.get("requires_explicit_external_ai", False)
            ),
            fallback_profiles=_strings(payload.get("fallback_profiles")),
            memory_promotion=str(payload.get("memory_promotion") or ""),
            source_text_policy=str(payload.get("source_text_policy") or ""),
            artifact_payloads_bounded=bool(payload.get("artifact_payloads_bounded", False)),
            may_run_local_asr=bool(payload.get("may_run_local_asr", False)),
            reason=_optional_string(payload.get("reason")),
            deprecated=bool(payload.get("deprecated", False)),
            replacement_profiles=_strings(payload.get("replacement_profiles")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ExtractionCapabilityDiagnostics:
    enabled: bool
    default_profile: str | None
    profiles: dict[str, ExtractionProfileCapability]
    providers: dict[str, dict[str, Any]]
    policy: dict[str, Any]
    evidence_contract: dict[str, Any]
    feature_contract: dict[str, Any]
    limits: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ExtractionCapabilityDiagnostics:
        profiles = {
            profile.name: profile
            for profile in (
                ExtractionProfileCapability.from_payload(item)
                for item in _dict_items(payload.get("profiles_v2"))
            )
            if profile.name
        }
        return cls(
            enabled=bool(payload.get("enabled", False)),
            default_profile=_optional_string(payload.get("default_profile")),
            profiles=profiles,
            providers={
                key: dict(value)
                for key, value in (payload.get("providers") or {}).items()
                if isinstance(key, str) and isinstance(value, dict)
            },
            policy=dict(payload.get("policy") or {}),
            evidence_contract=dict(payload.get("evidence_contract") or {}),
            feature_contract=dict(payload.get("feature_contract") or {}),
            limits=dict(payload.get("limits") or {}),
            raw=dict(payload),
        )

    def profile(self, name: str) -> ExtractionProfileCapability | None:
        return self.profiles.get(name)

    def provider_status(self, name: str) -> str | None:
        provider = self.providers.get(name)
        if provider is None:
            return None
        status = provider.get("status")
        return str(status) if status is not None else None


def _dict_items(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
