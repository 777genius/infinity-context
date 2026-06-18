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

_PROFILE_CONTRACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "standard_local": {
        "input_modalities": (
            "text",
            "document",
            "image",
            "timed_text",
            "audio_metadata",
            "video_metadata",
        ),
        "evidence_coordinates": (
            "char_range",
            "page_number",
            "bbox",
            "time_range_ms",
        ),
        "primary_artifact_types": (
            "image_regions",
            "transcript",
            "media_manifest",
            "keyframe",
            "video_frame_timeline",
        ),
        "document_features": ("plain_text", "pdf_text", "basic_metadata"),
        "vision_features": ("image_metadata", "ocr_regions_when_available"),
        "transcript_features": ("timed_text_segments", "time_ranges"),
        "video_features": ("ffprobe_metadata", "sampled_keyframes", "frame_timeline"),
    },
    "standard_docling": {
        "input_modalities": ("document",),
        "evidence_coordinates": ("char_range", "page_number", "bbox"),
        "primary_artifact_types": ("normalized_json", "table_html"),
        "document_features": (
            "layout",
            "reading_order",
            "tables",
            "ocr_when_enabled",
            "normalized_json",
        ),
    },
    "standard_vision": {
        "input_modalities": ("image",),
        "evidence_coordinates": ("bbox",),
        "primary_artifact_types": ("vision_json", "image_regions"),
        "vision_features": (
            "structured_image_summary",
            "detected_text",
            "region_coordinates",
            "provider_payload_bounding",
        ),
    },
    "media_api": {
        "input_modalities": ("audio", "video"),
        "evidence_coordinates": ("time_range_ms", "bbox"),
        "primary_artifact_types": (
            "transcript",
            "transcript_json",
            "keyframe",
            "video_frame_timeline",
        ),
        "transcript_features": (
            "segments",
            "time_ranges",
            "transcript_json",
            "optional_speaker_labels",
            "optional_word_timestamps",
        ),
        "video_features": ("ffprobe_metadata", "sampled_keyframes", "frame_timeline"),
    },
    "media_local_asr": {
        "input_modalities": ("audio", "video"),
        "evidence_coordinates": ("time_range_ms",),
        "primary_artifact_types": (
            "media_manifest",
            "transcript",
            "transcript_json",
        ),
        "transcript_features": ("segments", "time_ranges", "transcript_json"),
        "video_features": ("ffprobe_metadata",),
    },
    "standard_asr": {
        "input_modalities": ("audio", "video"),
        "evidence_coordinates": ("time_range_ms", "bbox"),
        "primary_artifact_types": (
            "transcript",
            "transcript_json",
            "keyframe",
            "video_frame_timeline",
        ),
        "transcript_features": (
            "segments",
            "time_ranges",
            "transcript_json",
            "optional_speaker_labels",
            "optional_word_timestamps",
        ),
        "video_features": ("ffprobe_metadata", "sampled_keyframes", "frame_timeline"),
    },
    "standard_full": {
        "input_modalities": ("document", "image", "audio", "video"),
        "evidence_coordinates": (
            "char_range",
            "page_number",
            "bbox",
            "time_range_ms",
        ),
        "primary_artifact_types": (
            "normalized_json",
            "table_html",
            "vision_json",
            "image_regions",
            "transcript",
            "transcript_json",
            "keyframe",
            "video_frame_timeline",
        ),
        "document_features": (
            "layout",
            "reading_order",
            "tables",
            "ocr_when_enabled",
            "normalized_json",
        ),
        "vision_features": (
            "structured_image_summary",
            "detected_text",
            "region_coordinates",
            "provider_payload_bounding",
        ),
        "transcript_features": (
            "segments",
            "time_ranges",
            "transcript_json",
            "optional_speaker_labels",
            "optional_word_timestamps",
        ),
        "video_features": ("ffprobe_metadata", "sampled_keyframes", "frame_timeline"),
    },
}


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
        "evidence_contract": _evidence_contract_payload(),
        "feature_contract": _feature_contract_payload(),
        "file_type_detection": _file_type_detection_contract_payload(),
        "modality_actions": _modality_action_matrix(profiles),
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
                "request_timeout_seconds": settings.extraction_provider_timeout_seconds,
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
                "request_timeout_seconds": settings.extraction_provider_timeout_seconds,
                "diarization_model_configured": _transcription_model_supports_diarization(
                    settings.transcription_openai_model
                ),
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
            may_run_local_asr=True,
        ),
        "standard_asr": _profile_from_providers(
            name="standard_asr",
            providers=(providers["transcription_api"],),
            fallback_profiles=("standard_local",),
            requires_explicit_external_ai=True,
            deprecated=True,
            replacement_profiles=("media_api", "media_local_asr"),
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
    may_run_local_asr: bool = False,
    replacement_profiles: tuple[str, ...] = (),
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
        may_run_local_asr=may_run_local_asr,
        replacement_profiles=replacement_profiles,
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
    may_run_local_asr: bool = False,
    replacement_profiles: tuple[str, ...] = (),
) -> dict[str, object]:
    contract = _PROFILE_CONTRACTS.get(
        name,
        {
            "input_modalities": (),
            "evidence_coordinates": (),
            "primary_artifact_types": (),
            "document_features": (),
            "vision_features": (),
            "transcript_features": (),
            "video_features": (),
        },
    )
    payload: dict[str, object] = {
        "name": name,
        "enabled": enabled,
        "status": status,
        "providers": list(provider_names),
        "input_modalities": list(contract["input_modalities"]),
        "evidence_coordinates": list(contract["evidence_coordinates"]),
        "primary_artifact_types": list(contract["primary_artifact_types"]),
        "document_features": list(contract.get("document_features", ())),
        "vision_features": list(contract.get("vision_features", ())),
        "transcript_features": list(contract.get("transcript_features", ())),
        "video_features": list(contract.get("video_features", ())),
        "external_provider_egress": external_provider_egress,
        "requires_explicit_external_ai": requires_explicit_external_ai,
        "fallback_profiles": list(fallback_profiles),
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "artifact_payloads_bounded": True,
        "may_run_local_asr": may_run_local_asr,
    }
    if reason is not None:
        payload["reason"] = reason
    if deprecated:
        payload["deprecated"] = True
    if replacement_profiles:
        payload["replacement_profiles"] = list(replacement_profiles)
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
            "request_timeout_seconds": settings.extraction_provider_timeout_seconds,
        },
        "transcription_api": {
            "installed": providers["transcription_api"].installed,
            "configured": providers["transcription_api"].configured,
            "provider": settings.transcription_provider,
            "profiles": ["media_api", "standard_asr", "standard_full"],
            "model": settings.transcription_openai_model,
            "max_provider_upload_bytes": settings.transcription_openai_max_upload_bytes,
            "request_timeout_seconds": settings.extraction_provider_timeout_seconds,
            "diarization_model_configured": _transcription_model_supports_diarization(
                settings.transcription_openai_model
            ),
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
        "local_asr_requires_explicit_profile": True,
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "provider_payloads_bounded": True,
        "sensitive_data_in_diagnostics": False,
        "canonical_store": "postgres",
        "derived_indexes": ["qdrant", "graphiti"],
    }


def _evidence_contract_payload() -> dict[str, object]:
    return {
        "schema_version": "memo_stack.extraction_evidence_contract.v1",
        "source_ref_coordinate_fields": [
            "char_start",
            "char_end",
            "page_number",
            "bbox",
            "time_start_ms",
            "time_end_ms",
        ],
        "profile_contract_fields": [
            "input_modalities",
            "evidence_coordinates",
            "primary_artifact_types",
        ],
        "coordinates_are_optional_per_item": True,
        "source_refs_are_bounded": True,
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
    }


def _feature_contract_payload() -> dict[str, object]:
    return {
        "schema_version": "memo_stack.extraction_feature_contract.v1",
        "profile_feature_fields": [
            "document_features",
            "vision_features",
            "transcript_features",
            "video_features",
        ],
        "feature_values_are_capabilities_not_guarantees": True,
        "actual_artifact_metadata_is_authoritative": True,
        "external_ai_features_require_explicit_profile": True,
        "local_asr_does_not_provide_speaker_labels": True,
    }


def _file_type_detection_contract_payload() -> dict[str, object]:
    return {
        "schema_version": "memo_stack.file_type_detection_contract.v1",
        "declared_content_type_trusted": False,
        "filename_extension_trusted": False,
        "magic_bytes_preferred_for_binary_mismatch": True,
        "textual_subtype_overrides_supported": True,
        "empty_upload_policy": "reject_at_upload",
        "mismatch_diagnostics_persisted": True,
        "diagnostic_fields": [
            "detected_content_type",
            "detector_confidence",
            "mime_declared_content_type",
            "mime_detected_content_type",
            "mime_magic_content_type",
            "mime_extension_content_type",
            "mime_content_type_mismatch",
            "mime_magic_mismatch",
            "mime_extension_mismatch",
            "mime_detector_reason",
            "asset_empty_content",
        ],
        "public_api_policy": "bounded_metadata_without_raw_bytes",
    }


def _modality_action_matrix(
    profiles: dict[str, dict[str, object]],
) -> dict[str, dict[str, dict[str, object]]]:
    return {
        "document": {
            "text_extraction": _modality_action_payload(
                profiles,
                profile_name="standard_local",
                artifact_types=("markdown", "extracted_json"),
                evidence_coordinates=("char_range", "page_number"),
            ),
            "layout_extraction": _modality_action_payload(
                profiles,
                profile_name="standard_docling",
                artifact_types=("normalized_json", "table_html"),
                evidence_coordinates=("page_number", "bbox", "char_range"),
            ),
        },
        "image": {
            "metadata": _modality_action_payload(
                profiles,
                profile_name="standard_local",
                artifact_types=("image_regions", "media_manifest"),
                evidence_coordinates=("bbox",),
            ),
            "vision": _modality_action_payload(
                profiles,
                profile_name="standard_vision",
                artifact_types=("vision_json", "image_regions"),
                evidence_coordinates=("bbox",),
            ),
        },
        "audio": {
            "metadata": _modality_action_payload(
                profiles,
                profile_name="standard_local",
                artifact_types=("media_manifest",),
                evidence_coordinates=("time_range_ms",),
            ),
            "transcription_api": _modality_action_payload(
                profiles,
                profile_name="media_api",
                artifact_types=("transcript", "transcript_json"),
                evidence_coordinates=("time_range_ms",),
            ),
            "transcription_local": _modality_action_payload(
                profiles,
                profile_name="media_local_asr",
                artifact_types=("transcript", "transcript_json"),
                evidence_coordinates=("time_range_ms",),
            ),
        },
        "video": {
            "metadata_keyframes": _modality_action_payload(
                profiles,
                profile_name="standard_local",
                artifact_types=("media_manifest", "keyframe", "video_frame_timeline"),
                evidence_coordinates=("time_range_ms", "bbox"),
            ),
            "transcription_api": _modality_action_payload(
                profiles,
                profile_name="media_api",
                artifact_types=("transcript", "transcript_json"),
                evidence_coordinates=("time_range_ms",),
            ),
        },
    }


def _modality_action_payload(
    profiles: dict[str, dict[str, object]],
    *,
    profile_name: str,
    artifact_types: tuple[str, ...],
    evidence_coordinates: tuple[str, ...],
) -> dict[str, object]:
    profile = profiles[profile_name]
    payload = {
        "profile": profile_name,
        "enabled": bool(profile.get("enabled", False)),
        "status": str(profile.get("status") or "unknown"),
        "providers": list(_safe_string_tuple(profile.get("providers"))),
        "artifact_types": list(artifact_types),
        "evidence_coordinates": list(evidence_coordinates),
        "external_provider_egress": bool(profile.get("external_provider_egress", False)),
        "requires_explicit_external_ai": bool(
            profile.get("requires_explicit_external_ai", False)
        ),
        "fallback_profiles": list(_safe_string_tuple(profile.get("fallback_profiles"))),
        "memory_promotion": str(profile.get("memory_promotion") or "review_required"),
        "source_text_policy": str(profile.get("source_text_policy") or "untrusted_evidence"),
        "artifact_payloads_bounded": bool(profile.get("artifact_payloads_bounded", True)),
    }
    reason = profile.get("reason")
    if isinstance(reason, str) and reason:
        payload["reason"] = reason
    return payload


def _safe_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


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
        "provider_timeout_seconds": settings.extraction_provider_timeout_seconds,
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


def _transcription_model_supports_diarization(model: str) -> bool:
    return "diarize" in model.strip().lower()


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
