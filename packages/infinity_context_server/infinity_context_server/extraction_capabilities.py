"""Safe extraction capability payloads for public diagnostics."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from infinity_context_adapters.extraction.openai_vision import (
    OPENAI_VISION_DOCS_URL,
    OPENAI_VISION_ENDPOINT_FAMILY,
    OPENAI_VISION_MAX_IMAGES_PER_REQUEST,
    OPENAI_VISION_MAX_PROVIDER_BINARY_BYTES,
    OPENAI_VISION_MAX_PROVIDER_PAYLOAD_BYTES,
    OPENAI_VISION_SUPPORTED_CONTENT_TYPES,
    OPENAI_VISION_SUPPORTED_FILE_SUFFIXES,
    openai_vision_supported_detail_levels,
)
from infinity_context_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_DOCS_URL,
    OPENAI_TRANSCRIPTION_ENDPOINT,
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    OPENAI_TRANSCRIPTION_SUPPORTED_CONTENT_TYPES,
    OPENAI_TRANSCRIPTION_SUPPORTED_FILE_SUFFIXES,
)
from infinity_context_core.application.asset_upload_policy import BLOCKED_UPLOAD_EXTENSIONS
from infinity_context_core.application.extraction_resource_policy import (
    EXTRACTION_ARCHIVE_RESOURCE_POLICY_VERSION,
    EXTRACTION_RESOURCE_LIMIT_CAPS,
    EXTRACTION_RESOURCE_POLICY_VERSION,
    EXTRACTION_RESULT_RESOURCE_POLICY_VERSION,
)
from infinity_context_core.application.multimodal_manifest import (
    multimodal_manifest_contract_payload,
)

from infinity_context_server.config import Settings

_PROFILE_ORDER = (
    "standard_local",
    "standard_docling",
    "standard_vision",
    "media_api",
    "media_local_asr",
    "standard_asr",
    "standard_full",
)

FILE_TYPE_DETECTION_RECOGNIZED_CONTENT_TYPES = (
    "application/json",
    "application/msword",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/x-subrip",
    "application/zip",
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/mpga",
    "audio/ogg",
    "audio/wav",
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/heic",
    "image/heif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
    "message/rfc822",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/vtt",
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
)
FILE_TYPE_DETECTION_RECOGNIZED_FILE_SUFFIXES = (
    ".avif",
    ".bmp",
    ".csv",
    ".doc",
    ".docx",
    ".eml",
    ".epub",
    ".flac",
    ".gif",
    ".heic",
    ".heif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".m4a",
    ".m4v",
    ".md",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".oga",
    ".ogg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".srt",
    ".tif",
    ".tiff",
    ".txt",
    ".vtt",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
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
        payload.update(_recovery_policy(status=self.status, reason=self.reason))
        payload.update(self.metadata)
        return payload


def build_extraction_capability_payload(settings: Settings) -> dict[str, object]:
    providers = _provider_states(settings)
    profiles = _profile_states(settings, providers)
    modality_actions = _modality_action_matrix(profiles)
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
        "provider_contract": _provider_contract_payload(settings),
        "manifest_contract": multimodal_manifest_contract_payload(),
        "file_type_detection": _file_type_detection_contract_payload(),
        "resource_policy": _resource_policy_payload(),
        "modality_actions": modality_actions,
        "degraded_components": _degraded_components(
            providers=providers,
            profiles=profiles,
            modality_actions=modality_actions,
        ),
        "external_provider_egress": settings.extraction_external_ai_enabled,
        "limits": _limits_payload(settings),
    }


def _provider_states(settings: Settings) -> dict[str, _ProviderState]:
    external_ready = settings.extraction_external_ai_enabled and bool(settings.openai_api_key)
    # OpenAI extraction adapters are bundled here and load provider clients lazily on
    # execution, so capabilities should expose config readiness without importing
    # optional provider SDKs at diagnostics time.
    openai_installed = True
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
    payload.update(_recovery_policy(status=status, reason=reason))
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
        "schema_version": "infinity_context.extraction_evidence_contract.v1",
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
        "schema_version": "infinity_context.extraction_feature_contract.v1",
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


def _provider_contract_payload(settings: Settings) -> dict[str, object]:
    return {
        "schema_version": "infinity_context.extraction_provider_contract.v1",
        "provider_output_policy": "evidence_not_truth",
        "raw_provider_payloads_in_public_api": False,
        "external_ai_requires_explicit_profile": True,
        "local_media_subprocess_policy": {
            "parser_family": "ffmpeg_ffprobe",
            "protocol_whitelist": ["file"],
            "network_protocols_allowed": False,
            "stdin_policy": "closed",
            "timeout_field": "limits.subprocess_timeout_seconds",
        },
        "vision": {
            "provider": "openai",
            "provider_name": "openai_vision",
            "endpoint_family": OPENAI_VISION_ENDPOINT_FAMILY,
            "model": settings.extraction_vision_model,
            "detail": settings.extraction_vision_detail,
            "supported_file_types": list(OPENAI_VISION_SUPPORTED_FILE_SUFFIXES),
            "supported_content_types": list(OPENAI_VISION_SUPPORTED_CONTENT_TYPES),
            "docs_url": OPENAI_VISION_DOCS_URL,
            "max_provider_payload_bytes": OPENAI_VISION_MAX_PROVIDER_PAYLOAD_BYTES,
            "max_provider_binary_upload_bytes": OPENAI_VISION_MAX_PROVIDER_BINARY_BYTES,
            "max_images_per_request": OPENAI_VISION_MAX_IMAGES_PER_REQUEST,
            "effective_max_upload_bytes": min(
                settings.max_asset_upload_bytes,
                settings.extraction_max_bytes,
                OPENAI_VISION_MAX_PROVIDER_BINARY_BYTES,
            ),
            "detail_levels": list(
                openai_vision_supported_detail_levels(settings.extraction_vision_model)
            ),
        },
        "transcription": {
            "provider": "openai",
            "provider_name": "transcription_api",
            "endpoint": OPENAI_TRANSCRIPTION_ENDPOINT,
            "model": settings.transcription_openai_model,
            "supported_file_types": list(OPENAI_TRANSCRIPTION_SUPPORTED_FILE_SUFFIXES),
            "supported_content_types": list(OPENAI_TRANSCRIPTION_SUPPORTED_CONTENT_TYPES),
            "docs_url": OPENAI_TRANSCRIPTION_DOCS_URL,
            "max_provider_upload_bytes": OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
            "effective_max_upload_bytes": min(
                settings.max_asset_upload_bytes,
                settings.transcription_openai_max_upload_bytes,
                OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
            ),
            "request_timeout_seconds": settings.extraction_provider_timeout_seconds,
            "diarization_model_configured": _transcription_model_supports_diarization(
                settings.transcription_openai_model
            ),
            "timestamp_policy": (
                "segments_when_provider_returns_them; fallback whole transcript uses full range"
            ),
        },
    }


def _file_type_detection_contract_payload() -> dict[str, object]:
    return {
        "schema_version": "infinity_context.file_type_detection_contract.v1",
        "declared_content_type_trusted": False,
        "filename_extension_trusted": False,
        "magic_bytes_preferred_for_binary_mismatch": True,
        "recognized_content_types": list(FILE_TYPE_DETECTION_RECOGNIZED_CONTENT_TYPES),
        "recognized_file_suffixes": list(FILE_TYPE_DETECTION_RECOGNIZED_FILE_SUFFIXES),
        "recognized_content_types_are_extraction_hints_not_guarantees": True,
        "textual_subtype_overrides_supported": True,
        "empty_upload_policy": "reject_at_upload",
        "upload_body_stream_limited": True,
        "mismatch_diagnostics_persisted": True,
        "archive_policy": {
            "inspect_zip_metadata": True,
            "reject_unsafe_paths": True,
            "reject_entry_count_limit": True,
            "reject_uncompressed_size_limit": True,
            "reject_single_entry_size_limit": True,
            "reject_compression_ratio_limit": True,
            "reject_symlink_entries": True,
            "reject_special_file_entries": True,
            "review_nested_archives": True,
            "review_encrypted_entries": True,
            "review_duplicate_paths": True,
            "raw_archive_defaults_to_review": True,
        },
        "binary_executable_policy": {
            "reject_magic_signatures": True,
            "reject_blocked_filename_extensions": True,
            "blocked_filename_extensions": list(BLOCKED_UPLOAD_EXTENSIONS),
            "blocked_magic_content_types": [
                "application/x-elf",
                "application/x-mach-binary",
                "application/x-msdownload",
            ],
        },
        "image_policy": {
            "inspect_dimensions_from_headers": True,
            "supported_dimension_content_types": [
                "image/gif",
                "image/jpeg",
                "image/png",
                "image/webp",
            ],
            "reject_corrupted_supported_image_headers": True,
            "review_unsupported_dimension_content_types": True,
            "reject_pixel_count_limit": True,
            "max_image_pixels_field": "limits.max_image_pixels",
            "declared_mime_does_not_trigger_image_limits_without_magic": True,
        },
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
            "mime_archive_detected",
            "mime_archive_review_required",
            "mime_archive_review_reason",
            "upload_archive_inspection_status",
            "upload_archive_entry_count",
            "upload_archive_file_count",
            "upload_archive_directory_count",
            "upload_archive_uncompressed_bytes",
            "upload_archive_compressed_bytes",
            "upload_archive_max_entry_uncompressed_bytes",
            "upload_archive_max_compression_ratio",
            "upload_archive_encrypted_entry_count",
            "upload_archive_nested_archive_count",
            "upload_archive_duplicate_path_count",
            "upload_archive_symlink_entry_count",
            "upload_archive_special_entry_count",
            "upload_archive_unsafe_path_count",
            "upload_archive_limits",
            "upload_image_detected",
            "upload_image_inspection_status",
            "upload_image_review_required",
            "upload_image_review_reason",
            "upload_image_width",
            "upload_image_height",
            "upload_image_pixels",
            "upload_image_max_pixels",
            "upload_active_content_script_signal_count",
            "upload_active_content_external_reference_count",
            "extraction_upload_policy_revalidated",
            "extraction_upload_policy_status",
            "extraction_upload_policy_rejection",
            "extraction_upload_magic_content_type",
            "mime_detector_reason",
            "asset_empty_content",
        ],
        "public_api_policy": "bounded_metadata_without_raw_bytes",
    }


def _resource_policy_payload() -> dict[str, object]:
    return {
        "schema_version": "infinity_context.extraction_resource_policy.v1",
        "policy_version": EXTRACTION_RESOURCE_POLICY_VERSION,
        "limits_normalized_before_provider": True,
        "rejects_oversized_asset_before_blob_read": True,
        "rejects_blob_content_length_overflow_before_provider": True,
        "revalidates_upload_policy_after_blob_read": True,
        "inspects_zip_central_directory_before_provider": True,
        "validates_extractor_result_before_ingest": True,
        "result_policy_version": EXTRACTION_RESULT_RESOURCE_POLICY_VERSION,
        "result_rejection_policy": {
            "reject_media_duration_limit_breach": True,
            "reject_image_pixel_limit_breach": True,
            "reject_page_processing_limit_breach": True,
            "reject_table_processing_limit_breach": True,
            "mark_page_count_truncation": True,
            "mark_table_count_truncation": True,
            "mark_output_char_truncation": True,
        },
        "result_rejection_error_codes": [
            "asset_extraction.media_too_long",
            "asset_extraction.image_too_large",
            "asset_extraction.page_limit_breach",
            "asset_extraction.table_limit_breach",
        ],
        "archive_policy_version": EXTRACTION_ARCHIVE_RESOURCE_POLICY_VERSION,
        "archive_rejection_policy": {
            "reject_unsafe_paths": True,
            "reject_symlink_entries": True,
            "reject_special_file_entries": True,
            "reject_duplicate_paths": True,
            "reject_nested_archives": True,
            "reject_encrypted_entries": True,
            "reject_entry_count_limit": True,
            "reject_single_entry_size_limit": True,
            "reject_uncompressed_size_limit": True,
            "reject_compression_ratio_limit": True,
        },
        "archive_rejection_error_codes": [
            "asset_extraction.archive_unsafe_path",
            "asset_extraction.archive_symlink_entry",
            "asset_extraction.archive_special_file_entry",
            "asset_extraction.archive_duplicate_path",
            "asset_extraction.archive_nested_archive",
            "asset_extraction.archive_encrypted",
            "asset_extraction.archive_too_many_entries",
            "asset_extraction.archive_entry_too_large",
            "asset_extraction.archive_uncompressed_too_large",
            "asset_extraction.archive_compression_ratio_too_high",
        ],
        "upload_policy_rejection_status": "unsupported",
        "upload_policy_rejection_error_code": "asset_extraction.upload_policy_rejected",
        "oversized_asset_status": "unsupported",
        "oversized_asset_error_code": "asset_extraction.file_too_large",
        "diagnostic_fields": [
            "extraction_resource_policy_version",
            "extraction_limits_normalized",
            "extraction_limits_clamped_fields",
            "extraction_asset_byte_size",
            "extraction_asset_byte_size_source",
            "extraction_resource_limit_exceeded",
            "extraction_result_resource_policy_version",
            "extraction_result_resource_checked",
            "extraction_result_media_seconds",
            "extraction_result_page_count",
            "extraction_result_pages_processed",
            "extraction_result_pages_truncated",
            "extraction_result_table_count",
            "extraction_result_tables_processed",
            "extraction_result_tables_truncated",
            "extraction_result_image_pixels",
            "extraction_result_output_chars",
            "extraction_result_output_truncation_required",
            "extraction_upload_policy_revalidated",
            "extraction_upload_policy_status",
            "extraction_upload_policy_rejection",
            "extraction_upload_magic_content_type",
            "extraction_archive_resource_policy_version",
            "extraction_archive_resource_checked",
            "extraction_archive_entries",
            "extraction_archive_file_entries",
            "extraction_archive_uncompressed_bytes",
            "extraction_archive_compressed_bytes",
            "extraction_archive_max_entry_uncompressed_bytes",
            "extraction_archive_compression_ratio",
            "extraction_archive_unsafe_path_count",
            "extraction_archive_symlink_entry_count",
            "extraction_archive_special_entry_count",
            "extraction_archive_duplicate_path_count",
            "extraction_archive_nested_archive_count",
            "extraction_archive_encrypted_entry_count",
            "extraction_max_archive_entries",
            "extraction_max_archive_uncompressed_bytes",
            "extraction_max_archive_single_entry_bytes",
            "extraction_max_archive_compression_ratio",
        ],
        "hard_caps": dict(EXTRACTION_RESOURCE_LIMIT_CAPS),
        "public_api_policy": "bounded_metadata_without_raw_bytes_or_provider_payloads",
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
        "requires_explicit_external_ai": bool(profile.get("requires_explicit_external_ai", False)),
        "fallback_profiles": list(_safe_string_tuple(profile.get("fallback_profiles"))),
        "memory_promotion": str(profile.get("memory_promotion") or "review_required"),
        "source_text_policy": str(profile.get("source_text_policy") or "untrusted_evidence"),
        "artifact_payloads_bounded": bool(profile.get("artifact_payloads_bounded", True)),
    }
    reason = profile.get("reason")
    if isinstance(reason, str) and reason:
        payload["reason"] = reason
    payload.update(
        _recovery_policy(
            status=str(profile.get("status") or "unknown"),
            reason=reason if isinstance(reason, str) else None,
        )
    )
    return payload


def _degraded_components(
    *,
    providers: dict[str, _ProviderState],
    profiles: dict[str, dict[str, object]],
    modality_actions: dict[str, dict[str, dict[str, object]]],
) -> list[dict[str, object]]:
    components: list[dict[str, object]] = []
    for name, provider in sorted(providers.items(), key=lambda item: item[0]):
        _append_degraded_component(
            components,
            component_type="provider",
            name=name,
            status=provider.status,
            reason=provider.reason,
        )
    for name in _PROFILE_ORDER:
        profile = profiles[name]
        _append_degraded_component(
            components,
            component_type="profile",
            name=name,
            status=str(profile.get("status") or "unknown"),
            reason=_optional_reason(profile.get("reason")),
        )
    for modality, actions in sorted(modality_actions.items(), key=lambda item: item[0]):
        for action, payload in sorted(actions.items(), key=lambda item: item[0]):
            _append_degraded_component(
                components,
                component_type="modality_action",
                name=f"{modality}.{action}",
                status=str(payload.get("status") or "unknown"),
                reason=_optional_reason(payload.get("reason")),
            )
    return components


def _append_degraded_component(
    components: list[dict[str, object]],
    *,
    component_type: str,
    name: str,
    status: str,
    reason: str | None,
) -> None:
    if status == "ok":
        return
    item: dict[str, object] = {
        "component_type": component_type,
        "name": name,
        "status": status,
    }
    if reason is not None:
        item["reason"] = reason
    item.update(_recovery_policy(status=status, reason=reason))
    components.append(item)


def _recovery_policy(*, status: str, reason: str | None) -> dict[str, object]:
    if status == "ok":
        return {}
    normalized = (reason or status).strip().lower()
    action = {
        "extraction_disabled": "enable_extraction",
        "external_ai_disabled": "enable_external_ai",
        "provider_credential_missing": "configure_provider_credential",
        "provider_disabled": "enable_provider",
        "provider_package_missing": "install_provider_package",
    }.get(normalized)
    if action is None:
        action = {
            "blocked": "fix_configuration",
            "disabled": "enable_component",
            "unavailable": "check_provider_runtime",
        }.get(status, "check_component")
    retryable = any(
        marker in normalized
        for marker in (
            "connection",
            "rate_limited",
            "timeout",
            "transient",
            "unavailable",
        )
    )
    return {
        "user_retryable": retryable,
        "operator_action": action,
    }


def _optional_reason(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


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
        "max_archive_entries": settings.extraction_max_archive_entries,
        "max_archive_uncompressed_bytes": (
            settings.extraction_max_archive_uncompressed_bytes
        ),
        "max_archive_single_entry_bytes": (
            settings.extraction_max_archive_single_entry_bytes
        ),
        "max_archive_compression_ratio": (
            settings.extraction_max_archive_compression_ratio
        ),
        "parser_timeout_seconds": settings.extraction_parser_timeout_seconds,
        "subprocess_timeout_seconds": settings.extraction_subprocess_timeout_seconds,
        "provider_timeout_seconds": settings.extraction_provider_timeout_seconds,
        "execution_lease_seconds": settings.extraction_execution_lease_seconds,
        "cancellation_poll_seconds": settings.extraction_cancellation_poll_seconds,
        "heartbeat_seconds": settings.extraction_heartbeat_seconds,
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
