"""Safe extraction capability payloads for public diagnostics."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from memo_stack_server.config import Settings

_PROFILE_ORDER = (
    "standard_local",
    "standard_docling",
    "standard_vision",
    "media_api",
    "media_local_asr",
    "standard_asr",
    "standard_full",
)


@dataclass(frozen=True)
class _ProviderState:
    name: str
    kind: str
    installed: bool
    configured: bool
    enabled: bool
    status: str
    reason: str | None
    profiles: tuple[str, ...]
    external_provider_egress: bool
    metadata: dict[str, object]

    def as_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "installed": self.installed,
            "configured": self.configured,
            "enabled": self.enabled,
            "status": self.status,
            "profiles": list(self.profiles),
            "external_provider_egress": self.external_provider_egress,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        payload.update(self.metadata)
        return payload


def build_extraction_capability_payload(settings: Settings) -> dict[str, object]:
    providers = _provider_states(settings)
    profiles = _profile_states(settings, providers)
    return {
        "enabled": settings.extraction_enabled,
        "default_profile": settings.extraction_default_profile,
        "profiles": list(_PROFILE_ORDER),
        "profiles_v2": [profiles[name] for name in _PROFILE_ORDER],
        "providers": {
            name: provider.as_public_dict()
            for name, provider in sorted(providers.items(), key=lambda item: item[0])
        },
        "optional_extras": _legacy_optional_extras(settings, providers),
        "policy": _policy_payload(settings),
        "external_provider_egress": settings.extraction_external_ai_enabled,
        "limits": _limits_payload(settings),
    }


def _provider_states(settings: Settings) -> dict[str, _ProviderState]:
    external_ready = settings.extraction_external_ai_enabled and bool(settings.openai_api_key)
    openai_installed = _module_available("openai")
    docling_installed = _module_available("docling")
    local_asr_installed = _module_available("faster_whisper")
    transcription_configured = (
        settings.transcription_provider == "openai" and external_ready and openai_installed
    )
    vision_configured = external_ready and openai_installed
    return {
        "docling": _ProviderState(
            name="docling",
            kind="document_parser",
            installed=docling_installed,
            configured=docling_installed,
            enabled=settings.extraction_enabled and docling_installed,
            status=_status(settings.extraction_enabled, docling_installed, docling_installed),
            reason=None if docling_installed else "provider_package_missing",
            profiles=("standard_docling", "standard_full"),
            external_provider_egress=False,
            metadata={},
        ),
        "openai_vision": _ProviderState(
            name="openai_vision",
            kind="image_vision",
            installed=openai_installed,
            configured=vision_configured,
            enabled=settings.extraction_enabled and vision_configured,
            status=_status(settings.extraction_enabled, openai_installed, vision_configured),
            reason=_external_reason(
                installed=openai_installed,
                external_ai_enabled=settings.extraction_external_ai_enabled,
                credential_present=bool(settings.openai_api_key),
            ),
            profiles=("standard_vision", "standard_full"),
            external_provider_egress=True,
            metadata={
                "model": settings.extraction_vision_model,
                "detail": settings.extraction_vision_detail,
            },
        ),
        "transcription_api": _ProviderState(
            name="transcription_api",
            kind="speech_to_text",
            installed=openai_installed,
            configured=transcription_configured,
            enabled=settings.extraction_enabled and transcription_configured,
            status=_status(settings.extraction_enabled, openai_installed, transcription_configured),
            reason=_transcription_reason(
                installed=openai_installed,
                provider=settings.transcription_provider,
                external_ai_enabled=settings.extraction_external_ai_enabled,
                credential_present=bool(settings.openai_api_key),
            ),
            profiles=("media_api", "standard_asr", "standard_full"),
            external_provider_egress=True,
            metadata={
                "provider": settings.transcription_provider,
                "model": settings.transcription_openai_model,
                "max_provider_upload_bytes": settings.transcription_openai_max_upload_bytes,
            },
        ),
        "transcription_local": _ProviderState(
            name="transcription_local",
            kind="speech_to_text",
            installed=local_asr_installed,
            configured=local_asr_installed,
            enabled=settings.extraction_enabled and local_asr_installed,
            status=_status(settings.extraction_enabled, local_asr_installed, local_asr_installed),
            reason=None if local_asr_installed else "provider_package_missing",
            profiles=("media_local_asr", "asr:<model>", "faster_whisper:<model>"),
            external_provider_egress=False,
            metadata={
                "model": settings.extraction_asr_model,
                "device": settings.extraction_asr_device,
                "compute_type": settings.extraction_asr_compute_type,
                "default": False,
            },
        ),
    }


def _profile_states(
    settings: Settings,
    providers: dict[str, _ProviderState],
) -> dict[str, dict[str, object]]:
    extraction_enabled = settings.extraction_enabled
    return {
        "standard_local": _profile_payload(
            name="standard_local",
            enabled=extraction_enabled,
            status="ok" if extraction_enabled else "disabled",
            reason=None if extraction_enabled else "extraction_disabled",
            provider_names=("local_text", "pdf_text", "image_metadata", "media_metadata"),
            external_provider_egress=False,
            requires_explicit_external_ai=False,
            fallback_profiles=(),
        ),
        "standard_docling": _profile_from_providers(
            name="standard_docling",
            providers=(providers["docling"],),
            fallback_profiles=("standard_local",),
            requires_explicit_external_ai=False,
        ),
        "standard_vision": _profile_from_providers(
            name="standard_vision",
            providers=(providers["openai_vision"],),
            fallback_profiles=("standard_local",),
            requires_explicit_external_ai=True,
        ),
        "media_api": _profile_from_providers(
            name="media_api",
            providers=(providers["transcription_api"],),
            fallback_profiles=("standard_local",),
            requires_explicit_external_ai=True,
        ),
        "media_local_asr": _profile_from_providers(
            name="media_local_asr",
            providers=(providers["transcription_local"],),
            fallback_profiles=("standard_local",),
            requires_explicit_external_ai=False,
        ),
        "standard_asr": _profile_from_providers(
            name="standard_asr",
            providers=(providers["transcription_api"],),
            fallback_profiles=("media_api", "media_local_asr"),
            requires_explicit_external_ai=True,
            deprecated=True,
        ),
        "standard_full": _profile_from_providers(
            name="standard_full",
            providers=(
                providers["docling"],
                providers["openai_vision"],
                providers["transcription_api"],
            ),
            fallback_profiles=(
                "standard_docling",
                "standard_vision",
                "media_api",
                "standard_local",
            ),
            requires_explicit_external_ai=True,
        ),
    }


def _profile_from_providers(
    *,
    name: str,
    providers: tuple[_ProviderState, ...],
    fallback_profiles: tuple[str, ...],
    requires_explicit_external_ai: bool,
    deprecated: bool = False,
) -> dict[str, object]:
    enabled_providers = tuple(provider for provider in providers if provider.enabled)
    status = _combined_status(providers)
    reason = _combined_reason(providers, status)
    return _profile_payload(
        name=name,
        enabled=bool(enabled_providers),
        status=status,
        reason=reason,
        provider_names=tuple(provider.name for provider in providers),
        external_provider_egress=any(provider.external_provider_egress for provider in providers),
        requires_explicit_external_ai=requires_explicit_external_ai,
        fallback_profiles=fallback_profiles,
        deprecated=deprecated,
    )


def _profile_payload(
    *,
    name: str,
    enabled: bool,
    status: str,
    reason: str | None,
    provider_names: tuple[str, ...],
    external_provider_egress: bool,
    requires_explicit_external_ai: bool,
    fallback_profiles: tuple[str, ...],
    deprecated: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "enabled": enabled,
        "status": status,
        "providers": list(provider_names),
        "external_provider_egress": external_provider_egress,
        "requires_explicit_external_ai": requires_explicit_external_ai,
        "fallback_profiles": list(fallback_profiles),
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "artifact_payloads_bounded": True,
    }
    if reason is not None:
        payload["reason"] = reason
    if deprecated:
        payload["deprecated"] = True
    return payload


def _legacy_optional_extras(
    settings: Settings,
    providers: dict[str, _ProviderState],
) -> dict[str, dict[str, object]]:
    return {
        "docling": {
            "installed": providers["docling"].installed,
            "profiles": ["standard_docling", "standard_full"],
        },
        "vision": {
            "installed": providers["openai_vision"].installed,
            "configured": providers["openai_vision"].configured,
            "profiles": ["standard_vision", "standard_full"],
            "model": settings.extraction_vision_model,
            "detail": settings.extraction_vision_detail,
        },
        "transcription_api": {
            "installed": providers["transcription_api"].installed,
            "configured": providers["transcription_api"].configured,
            "provider": settings.transcription_provider,
            "profiles": ["media_api", "standard_asr", "standard_full"],
            "model": settings.transcription_openai_model,
            "max_provider_upload_bytes": settings.transcription_openai_max_upload_bytes,
        },
        "transcription_local": {
            "installed": providers["transcription_local"].installed,
            "profiles": ["media_local_asr", "asr:<model>", "faster_whisper:<model>"],
            "model": settings.extraction_asr_model,
            "device": settings.extraction_asr_device,
            "compute_type": settings.extraction_asr_compute_type,
            "default": False,
        },
        "asr": {
            "deprecated": True,
            "replacement_profiles": ["media_api", "media_local_asr"],
        },
    }


def _policy_payload(settings: Settings) -> dict[str, object]:
    return {
        "schema_version": 2,
        "external_ai_allowed": settings.extraction_external_ai_enabled,
        "external_ai_requires_explicit_profile": True,
        "local_asr_default": False,
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "provider_payloads_bounded": True,
        "sensitive_data_in_diagnostics": False,
        "canonical_store": "postgres",
        "derived_indexes": ["qdrant", "graphiti"],
    }


def _limits_payload(settings: Settings) -> dict[str, object]:
    return {
        "max_bytes": settings.extraction_max_bytes,
        "max_pages": settings.extraction_max_pages,
        "max_media_seconds": settings.extraction_max_media_seconds,
        "max_output_chars": settings.extraction_max_output_chars,
        "max_tables": settings.extraction_max_tables,
        "ocr_enabled": settings.extraction_ocr_enabled,
        "max_image_pixels": settings.extraction_max_image_pixels,
        "parser_timeout_seconds": settings.extraction_parser_timeout_seconds,
        "subprocess_timeout_seconds": settings.extraction_subprocess_timeout_seconds,
    }


def _status(extraction_enabled: bool, installed: bool, configured: bool) -> str:
    if not extraction_enabled:
        return "disabled"
    if not installed:
        return "unavailable"
    if not configured:
        return "blocked"
    return "ok"


def _combined_status(providers: tuple[_ProviderState, ...]) -> str:
    statuses = {provider.status for provider in providers}
    if "ok" in statuses:
        return "ok" if statuses == {"ok"} else "degraded"
    if "blocked" in statuses:
        return "blocked"
    if "unavailable" in statuses:
        return "unavailable"
    return "disabled"


def _combined_reason(providers: tuple[_ProviderState, ...], status: str) -> str | None:
    if status == "ok":
        return None
    reasons = tuple(provider.reason for provider in providers if provider.reason)
    if not reasons:
        return status
    return reasons[0]


def _external_reason(
    *,
    installed: bool,
    external_ai_enabled: bool,
    credential_present: bool,
) -> str | None:
    if not installed:
        return "provider_package_missing"
    if not external_ai_enabled:
        return "external_ai_disabled"
    if not credential_present:
        return "provider_credential_missing"
    return None


def _transcription_reason(
    *,
    installed: bool,
    provider: str,
    external_ai_enabled: bool,
    credential_present: bool,
) -> str | None:
    if provider == "disabled":
        return "provider_disabled"
    return _external_reason(
        installed=installed,
        external_ai_enabled=external_ai_enabled,
        credential_present=credential_present,
    )


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
