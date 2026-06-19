from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.extraction.openai_vision import (
    OPENAI_VISION_DOCS_URL,
    OPENAI_VISION_ENDPOINT_FAMILY,
    OPENAI_VISION_MAX_IMAGES_PER_REQUEST,
    OPENAI_VISION_MAX_PROVIDER_BINARY_BYTES,
    OPENAI_VISION_MAX_PROVIDER_PAYLOAD_BYTES,
    OPENAI_VISION_SUPPORTED_CONTENT_TYPES,
    OPENAI_VISION_SUPPORTED_FILE_SUFFIXES,
)
from infinity_context_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_DOCS_URL,
    OPENAI_TRANSCRIPTION_ENDPOINT,
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    OPENAI_TRANSCRIPTION_SUPPORTED_CONTENT_TYPES,
    OPENAI_TRANSCRIPTION_SUPPORTED_FILE_SUFFIXES,
)
from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.errors import MemoryInfrastructureError, MemoryInvariantError
from infinity_context_core.ports import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityStatus,
    ConsistencyMode,
    DocumentMemoryPort,
    EngineHealthSnapshot,
    FactProjectionPort,
    MemoryCapability,
    MemoryScopeFilter,
    ProjectionFreshness,
    RagRecallPort,
    TemporalFactGraphPort,
    VectorRecallPort,
)
from infinity_context_server.config import CaptureMode, DeployProfile, MemoryPolicyMode, Settings
from infinity_context_server.diagnostics import storage_diagnostics
from infinity_context_server.extraction_capabilities import (
    FILE_TYPE_DETECTION_RECOGNIZED_CONTENT_TYPES,
    FILE_TYPE_DETECTION_RECOGNIZED_FILE_SUFFIXES,
)
from infinity_context_server.main import create_app


def build_test_client() -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def test_health_returns_ok() -> None:
    response = build_test_client().get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "infinity-context",
        "deploy_profile": "test",
    }


def test_root_health_alias_supports_client_canary() -> None:
    response = build_test_client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_healthz_alias_supports_frontend_liveness() -> None:
    response = build_test_client().get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities_return_noop_adapters() -> None:
    response = build_test_client().get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["service_name"] == "infinity-context"
    assert body["deploy_profile"] == "test"
    assert body["policy_mode"] == "active_context"
    assert set(body["adapters"]) == {"qdrant", "graphiti", "embeddings", "cognee"}
    assert body["adapters"]["qdrant"]["enabled"] is False
    assert body["adapters"]["graphiti"]["enabled"] is False
    assert body["adapters"]["embeddings"]["enabled"] is False
    assert body["adapters"]["cognee"]["enabled"] is False
    capability_pairs = {(item["adapter_name"], item["capability"]) for item in body["capabilities"]}
    assert capability_pairs == {
        ("qdrant", "vector_recall"),
        ("qdrant", "projection_forget"),
        ("graphiti", "temporal_fact_graph"),
        ("graphiti", "fact_projection"),
        ("graphiti", "projection_forget"),
        ("embeddings", "engine_health"),
        ("cognee", "document_memory"),
        ("cognee", "rag_recall"),
    }
    assert all(item["status"] == "disabled" for item in body["capabilities"])
    assert all(item["healthy"] is False for item in body["capabilities"])
    assert "bearer" not in response.text.lower()
    assert "api_key" not in response.text.lower()
    assert "secret" not in response.text.lower()
    assert body["limits"]["max_context_tokens"] == 1800
    assert body["limits"]["max_capture_text_chars"] == 20_000
    assert body["limits"]["max_pending_captures_per_memory_scope"] == 5_000
    assert body["limits"]["max_pending_suggestions_per_memory_scope"] == 500
    assert body["limits"]["max_asset_upload_bytes"] == 25 * 1024 * 1024
    assert body["limits"]["media_analysis_seconds_per_month"] == 10 * 60 * 60
    assert body["storage"] == {
        "asset_backend": "local",
        "asset_backend_configured": True,
        "asset_external": False,
        "s3": {
            "bucket_configured": False,
            "prefix_configured": False,
            "endpoint_configured": False,
            "region_configured": False,
            "force_path_style": False,
        },
    }
    assert body["plans"]["current"] == "free"
    assert body["plans"]["resources"]["media_analysis_seconds"]["limit_per_month"] == (10 * 60 * 60)
    assert body["extraction"]["enabled"] is True
    assert body["extraction"]["default_profile"] == "standard_local"
    assert body["extraction"]["profiles"] == [
        "standard_local",
        "standard_docling",
        "standard_vision",
        "media_api",
        "media_local_asr",
        "standard_asr",
        "standard_full",
    ]
    profile_states = {profile["name"]: profile for profile in body["extraction"]["profiles_v2"]}
    assert set(profile_states) == set(body["extraction"]["profiles"])
    assert profile_states["standard_local"]["status"] == "ok"
    assert profile_states["standard_local"]["enabled"] is True
    assert profile_states["standard_local"]["input_modalities"] == [
        "text",
        "document",
        "image",
        "timed_text",
        "audio_metadata",
        "video_metadata",
    ]
    assert profile_states["standard_local"]["evidence_coordinates"] == [
        "char_range",
        "page_number",
        "bbox",
        "time_range_ms",
    ]
    assert profile_states["standard_local"]["document_features"] == [
        "plain_text",
        "pdf_text",
        "basic_metadata",
    ]
    assert profile_states["standard_local"]["transcript_features"] == [
        "timed_text_segments",
        "time_ranges",
    ]
    assert profile_states["standard_local"]["external_provider_egress"] is False
    assert profile_states["standard_local"]["may_run_local_asr"] is False
    assert profile_states["standard_docling"]["primary_artifact_types"] == [
        "normalized_json",
        "table_html",
    ]
    assert profile_states["standard_docling"]["document_features"] == [
        "layout",
        "reading_order",
        "tables",
        "ocr_when_enabled",
        "normalized_json",
    ]
    assert profile_states["standard_vision"]["requires_explicit_external_ai"] is True
    assert profile_states["standard_vision"]["input_modalities"] == ["image"]
    assert profile_states["standard_vision"]["evidence_coordinates"] == ["bbox"]
    assert profile_states["standard_vision"]["vision_features"] == [
        "structured_image_summary",
        "detected_text",
        "region_coordinates",
        "provider_payload_bounding",
    ]
    assert profile_states["standard_vision"]["memory_promotion"] == "review_required"
    assert profile_states["standard_vision"]["source_text_policy"] == "untrusted_evidence"
    assert profile_states["standard_vision"]["artifact_payloads_bounded"] is True
    assert profile_states["media_api"]["input_modalities"] == ["audio", "video"]
    assert profile_states["media_api"]["evidence_coordinates"] == ["time_range_ms", "bbox"]
    assert profile_states["media_api"]["primary_artifact_types"] == [
        "transcript",
        "transcript_json",
        "keyframe",
        "video_frame_timeline",
    ]
    assert profile_states["media_api"]["transcript_features"] == [
        "segments",
        "time_ranges",
        "transcript_json",
        "optional_speaker_labels",
        "optional_word_timestamps",
    ]
    assert profile_states["media_api"]["video_features"] == [
        "ffprobe_metadata",
        "sampled_keyframes",
        "frame_timeline",
    ]
    assert profile_states["media_api"]["may_run_local_asr"] is False
    assert profile_states["media_local_asr"]["may_run_local_asr"] is True
    assert profile_states["media_local_asr"]["external_provider_egress"] is False
    assert profile_states["media_local_asr"]["evidence_coordinates"] == ["time_range_ms"]
    assert profile_states["media_local_asr"]["transcript_features"] == [
        "segments",
        "time_ranges",
        "transcript_json",
    ]
    assert "optional_speaker_labels" not in profile_states["media_local_asr"]["transcript_features"]
    assert profile_states["standard_asr"]["deprecated"] is True
    assert profile_states["standard_asr"]["may_run_local_asr"] is False
    assert profile_states["standard_asr"]["fallback_profiles"] == ["standard_local"]
    assert profile_states["standard_asr"]["replacement_profiles"] == [
        "media_api",
        "media_local_asr",
    ]
    assert profile_states["standard_full"]["may_run_local_asr"] is False
    assert body["extraction"]["providers"]["openai_vision"]["status"] in {
        "blocked",
        "unavailable",
    }
    assert body["extraction"]["providers"]["transcription_api"]["status"] in {
        "blocked",
        "unavailable",
    }
    assert body["extraction"]["policy"] == {
        "schema_version": 2,
        "external_ai_allowed": False,
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
    assert body["extraction"]["evidence_contract"] == {
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
    assert body["extraction"]["feature_contract"] == {
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
    assert body["extraction"]["provider_contract"] == {
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
            "model": "gpt-4.1-mini",
            "detail": "high",
            "supported_file_types": list(OPENAI_VISION_SUPPORTED_FILE_SUFFIXES),
            "supported_content_types": list(OPENAI_VISION_SUPPORTED_CONTENT_TYPES),
            "docs_url": OPENAI_VISION_DOCS_URL,
            "max_provider_payload_bytes": OPENAI_VISION_MAX_PROVIDER_PAYLOAD_BYTES,
            "max_provider_binary_upload_bytes": OPENAI_VISION_MAX_PROVIDER_BINARY_BYTES,
            "max_images_per_request": OPENAI_VISION_MAX_IMAGES_PER_REQUEST,
            "effective_max_upload_bytes": 25 * 1024 * 1024,
            "detail_levels": ["low", "high", "auto"],
        },
        "transcription": {
            "provider": "openai",
            "provider_name": "transcription_api",
            "endpoint": OPENAI_TRANSCRIPTION_ENDPOINT,
            "model": "gpt-4o-mini-transcribe",
            "supported_file_types": list(OPENAI_TRANSCRIPTION_SUPPORTED_FILE_SUFFIXES),
            "supported_content_types": list(OPENAI_TRANSCRIPTION_SUPPORTED_CONTENT_TYPES),
            "docs_url": OPENAI_TRANSCRIPTION_DOCS_URL,
            "max_provider_upload_bytes": OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
            "effective_max_upload_bytes": OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
            "request_timeout_seconds": 60,
            "diarization_model_configured": False,
            "timestamp_policy": (
                "segments_when_provider_returns_them; fallback whole transcript uses full range"
            ),
        },
    }
    assert body["extraction"]["manifest_contract"]["schema_version"] == (
        "infinity_context.multimodal_manifest_contract.v1"
    )
    assert body["extraction"]["manifest_contract"]["manifest_schema_version"] == (
        "infinity_context.multimodal_manifest.v1"
    )
    assert body["extraction"]["manifest_contract"]["artifact_type"] == "media_manifest"
    assert body["extraction"]["manifest_contract"]["coordinate_fields"] == [
        "page_number",
        "bbox",
        "time_range",
    ]
    assert body["extraction"]["manifest_contract"]["provider_output_policy"] == (
        "evidence_not_truth"
    )
    assert body["extraction"]["manifest_contract"]["raw_provider_payloads_in_public_api"] is False
    assert body["extraction"]["file_type_detection"] == {
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
            "upload_image_width",
            "upload_image_height",
            "upload_image_pixels",
            "upload_image_max_pixels",
            "extraction_upload_policy_revalidated",
            "extraction_upload_policy_status",
            "extraction_upload_policy_rejection",
            "extraction_upload_magic_content_type",
            "mime_detector_reason",
            "asset_empty_content",
        ],
        "public_api_policy": "bounded_metadata_without_raw_bytes",
    }
    modality_actions = body["extraction"]["modality_actions"]
    assert modality_actions["image"]["metadata"] == {
        "profile": "standard_local",
        "enabled": True,
        "status": "ok",
        "providers": ["local_text", "pdf_text", "image_metadata", "media_metadata"],
        "artifact_types": ["image_regions", "media_manifest"],
        "evidence_coordinates": ["bbox"],
        "external_provider_egress": False,
        "requires_explicit_external_ai": False,
        "fallback_profiles": [],
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "artifact_payloads_bounded": True,
    }
    assert modality_actions["image"]["vision"]["profile"] == "standard_vision"
    assert modality_actions["image"]["vision"]["status"] in {"blocked", "unavailable"}
    assert modality_actions["image"]["vision"]["requires_explicit_external_ai"] is True
    assert modality_actions["image"]["vision"]["fallback_profiles"] == ["standard_local"]
    assert modality_actions["audio"]["transcription_api"]["profile"] == "media_api"
    assert modality_actions["audio"]["transcription_api"]["status"] in {
        "blocked",
        "unavailable",
    }
    assert modality_actions["audio"]["transcription_local"]["profile"] == "media_local_asr"
    assert modality_actions["video"]["metadata_keyframes"]["artifact_types"] == [
        "media_manifest",
        "keyframe",
        "video_frame_timeline",
    ]
    assert modality_actions["video"]["transcription_api"]["source_text_policy"] == (
        "untrusted_evidence"
    )
    degraded_components = {
        (item["component_type"], item["name"]): item
        for item in body["extraction"]["degraded_components"]
    }
    openai_vision = body["extraction"]["providers"]["openai_vision"]
    standard_vision = profile_states["standard_vision"]
    image_vision = modality_actions["image"]["vision"]
    assert degraded_components[("provider", "openai_vision")] == {
        "component_type": "provider",
        "name": "openai_vision",
        "status": openai_vision["status"],
        "reason": openai_vision["reason"],
        "user_retryable": openai_vision["user_retryable"],
        "operator_action": openai_vision["operator_action"],
    }
    assert degraded_components[("profile", "standard_vision")] == {
        "component_type": "profile",
        "name": "standard_vision",
        "status": standard_vision["status"],
        "reason": standard_vision["reason"],
        "user_retryable": standard_vision["user_retryable"],
        "operator_action": standard_vision["operator_action"],
    }
    assert degraded_components[("modality_action", "image.vision")] == {
        "component_type": "modality_action",
        "name": "image.vision",
        "status": image_vision["status"],
        "reason": image_vision["reason"],
        "user_retryable": image_vision["user_retryable"],
        "operator_action": image_vision["operator_action"],
    }
    assert ("profile", "standard_local") not in degraded_components
    assert ("modality_action", "image.metadata") not in degraded_components
    assert isinstance(body["extraction"]["optional_extras"]["docling"]["installed"], bool)
    assert isinstance(body["extraction"]["optional_extras"]["vision"]["installed"], bool)
    assert body["extraction"]["optional_extras"]["vision"]["configured"] is False
    assert body["extraction"]["optional_extras"]["vision"]["model"] == "gpt-4.1-mini"
    assert body["extraction"]["optional_extras"]["vision"]["detail"] == "high"
    assert body["extraction"]["optional_extras"]["vision"]["request_timeout_seconds"] == 60
    assert body["extraction"]["providers"]["openai_vision"]["request_timeout_seconds"] == 60
    assert isinstance(body["extraction"]["optional_extras"]["transcription_api"]["installed"], bool)
    assert body["extraction"]["optional_extras"]["transcription_api"]["configured"] is False
    assert body["extraction"]["optional_extras"]["transcription_api"]["provider"] == "openai"
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["model"]
        == "gpt-4o-mini-transcribe"
    )
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["max_provider_upload_bytes"]
        == OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES
    )
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["request_timeout_seconds"] == 60
    )
    assert body["extraction"]["providers"]["transcription_api"]["request_timeout_seconds"] == 60
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["diarization_model_configured"]
        is False
    )
    assert (
        body["extraction"]["providers"]["transcription_api"]["diarization_model_configured"]
        is False
    )
    assert isinstance(
        body["extraction"]["optional_extras"]["transcription_local"]["installed"], bool
    )
    assert body["extraction"]["optional_extras"]["transcription_local"]["model"] == "base"
    assert body["extraction"]["optional_extras"]["transcription_local"]["default"] is False
    assert body["extraction"]["optional_extras"]["asr"]["deprecated"] is True
    assert body["extraction"]["optional_extras"]["asr"]["replacement_profiles"] == [
        "media_api",
        "media_local_asr",
    ]
    assert body["extraction"]["limits"]["max_media_seconds"] == 600
    assert body["extraction"]["limits"]["provider_timeout_seconds"] == 60
    assert body["extraction"]["limits"]["execution_lease_seconds"] == 15 * 60
    assert body["extraction"]["limits"]["cancellation_poll_seconds"] == 1.0
    assert body["extraction"]["limits"]["heartbeat_seconds"] == 15.0
    assert body["extraction"]["resource_policy"]["limits_normalized_before_provider"] is True
    assert body["extraction"]["resource_policy"]["rejects_oversized_asset_before_blob_read"] is True
    assert (
        body["extraction"]["resource_policy"]["revalidates_upload_policy_after_blob_read"]
        is True
    )
    assert (
        body["extraction"]["resource_policy"]["upload_policy_rejection_error_code"]
        == "asset_extraction.upload_policy_rejected"
    )
    assert (
        body["extraction"]["resource_policy"]["oversized_asset_error_code"]
        == "asset_extraction.file_too_large"
    )
    assert body["captures"]["max_pending_per_memory_scope"] == 5_000
    assert body["captures"]["ingress_limit_code"] == "memory.capture.ingress_limited"
    assert body["supports_legacy_client_routes"] is False


def test_capabilities_expose_configured_external_media_extraction(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'media-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="media_api",
            extraction_external_ai_enabled=True,
            max_asset_upload_bytes=77_777,
            extraction_max_bytes=123_456,
            extraction_max_pages=7,
            extraction_max_media_seconds=42,
            extraction_max_output_chars=10_000,
            extraction_max_tables=3,
            extraction_ocr_enabled=False,
            extraction_vision_model="gpt-5.5",
            extraction_vision_detail="low",
            transcription_provider="openai",
            transcription_openai_model="gpt-4o-transcribe",
            transcription_openai_max_upload_bytes=12_345,
            extraction_provider_timeout_seconds=17,
            extraction_execution_lease_seconds=45,
            extraction_cancellation_poll_seconds=0.25,
            extraction_heartbeat_seconds=2.5,
            openai_api_key="sk-capabilities-secret",
            plan_media_analysis_seconds_per_month=3_600,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    extraction = body["extraction"]
    assert extraction["default_profile"] == "media_api"
    assert extraction["external_provider_egress"] is True
    assert extraction["optional_extras"]["vision"]["configured"] is True
    assert extraction["optional_extras"]["vision"]["model"] == "gpt-5.5"
    assert extraction["optional_extras"]["vision"]["detail"] == "low"
    assert extraction["optional_extras"]["vision"]["request_timeout_seconds"] == 17
    assert extraction["providers"]["openai_vision"]["request_timeout_seconds"] == 17
    assert extraction["optional_extras"]["transcription_api"]["configured"] is True
    assert extraction["optional_extras"]["transcription_api"]["provider"] == "openai"
    assert extraction["optional_extras"]["transcription_api"]["model"] == "gpt-4o-transcribe"
    assert (
        extraction["optional_extras"]["transcription_api"]["diarization_model_configured"] is False
    )
    assert extraction["providers"]["transcription_api"]["diarization_model_configured"] is False
    assert extraction["optional_extras"]["transcription_api"]["max_provider_upload_bytes"] == 12_345
    assert extraction["optional_extras"]["transcription_api"]["request_timeout_seconds"] == 17
    assert extraction["providers"]["transcription_api"]["request_timeout_seconds"] == 17
    assert extraction["provider_contract"]["vision"]["detail"] == "low"
    assert extraction["provider_contract"]["vision"]["detail_levels"] == [
        "low",
        "high",
        "original",
        "auto",
    ]
    assert extraction["provider_contract"]["vision"]["effective_max_upload_bytes"] == 77_777
    assert extraction["provider_contract"]["transcription"]["model"] == "gpt-4o-transcribe"
    assert extraction["provider_contract"]["transcription"]["effective_max_upload_bytes"] == 12_345
    assert extraction["provider_contract"]["transcription"]["diarization_model_configured"] is False
    assert extraction["limits"]["max_bytes"] == 123_456
    assert extraction["limits"]["max_pages"] == 7
    assert extraction["limits"]["max_media_seconds"] == 42
    assert extraction["limits"]["max_output_chars"] == 10_000
    assert extraction["limits"]["max_tables"] == 3
    assert extraction["limits"]["ocr_enabled"] is False
    assert extraction["limits"]["max_image_pixels"] == 50_000_000
    assert extraction["limits"]["parser_timeout_seconds"] == 5 * 60
    assert extraction["limits"]["subprocess_timeout_seconds"] == 60
    assert extraction["limits"]["provider_timeout_seconds"] == 17
    assert extraction["limits"]["execution_lease_seconds"] == 45
    assert extraction["limits"]["cancellation_poll_seconds"] == 0.25
    assert extraction["limits"]["heartbeat_seconds"] == 2.5
    assert extraction["providers"]["openai_vision"]["enabled"] is True
    assert extraction["providers"]["openai_vision"]["status"] == "ok"
    assert extraction["providers"]["transcription_api"]["enabled"] is True
    assert extraction["providers"]["transcription_api"]["status"] == "ok"
    assert extraction["modality_actions"]["image"]["vision"]["status"] == "ok"
    assert extraction["modality_actions"]["image"]["vision"]["enabled"] is True
    assert extraction["modality_actions"]["image"]["vision"]["external_provider_egress"] is True
    assert extraction["modality_actions"]["audio"]["transcription_api"]["status"] == "ok"
    assert extraction["modality_actions"]["video"]["transcription_api"]["status"] == "ok"
    assert extraction["policy"]["external_ai_allowed"] is True
    profile_states = {profile["name"]: profile for profile in extraction["profiles_v2"]}
    assert profile_states["media_api"]["status"] == "ok"
    assert profile_states["standard_vision"]["status"] == "ok"
    degraded_keys = {
        (item["component_type"], item["name"]) for item in extraction["degraded_components"]
    }
    assert ("provider", "openai_vision") not in degraded_keys
    assert ("provider", "transcription_api") not in degraded_keys
    assert ("profile", "media_api") not in degraded_keys
    assert ("profile", "standard_vision") not in degraded_keys
    assert ("modality_action", "image.vision") not in degraded_keys
    assert ("modality_action", "audio.transcription_api") not in degraded_keys
    assert ("modality_action", "video.transcription_api") not in degraded_keys
    assert body["limits"]["max_asset_upload_bytes"] == 77_777
    assert body["storage"]["asset_backend"] == "local"
    assert body["plans"]["resources"]["media_analysis_seconds"]["limit_per_month"] == 3_600
    assert "sk-capabilities-secret" not in response.text


def test_s3_asset_storage_requires_bucket() -> None:
    settings = Settings(
        deploy_profile=DeployProfile.LOCAL,
        asset_storage_backend="s3",
    )

    with pytest.raises(RuntimeError, match="MEMORY_ASSET_STORAGE_S3_BUCKET"):
        settings.validate_for_startup()


def test_capabilities_expose_configured_diarization_transcription_model(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'diarize-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="media_api",
            extraction_external_ai_enabled=True,
            transcription_provider="openai",
            transcription_openai_model="gpt-4o-transcribe-diarize",
            openai_api_key="sk-diarize-capabilities-secret",
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert (
        extraction["optional_extras"]["transcription_api"]["diarization_model_configured"] is True
    )
    assert extraction["providers"]["transcription_api"]["diarization_model_configured"] is True
    assert "sk-diarize-capabilities-secret" not in response.text


def test_adapter_diagnostics_include_extraction_policy_without_credentials(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'diagnostic-extraction.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="standard_vision",
            extraction_external_ai_enabled=True,
            openai_api_key="sk-diagnostics-secret",
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/diagnostics/adapters")

    assert response.status_code == 200
    extraction = response.json()["data"]["extraction"]
    assert extraction["default_profile"] == "standard_vision"
    assert extraction["policy"]["schema_version"] == 2
    assert extraction["policy"]["external_ai_allowed"] is True
    assert extraction["providers"]["openai_vision"]["configured"] is True
    profile_states = {profile["name"]: profile for profile in extraction["profiles_v2"]}
    assert profile_states["standard_vision"]["memory_promotion"] == "review_required"
    assert "sk-diagnostics-secret" not in response.text


def test_storage_diagnostics_endpoint_exposes_local_readiness_without_path(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'diagnostic-storage.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(asset_root),
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/diagnostics/storage")

    assert response.status_code == 200
    storage = response.json()["data"]
    assert storage["asset_backend"] == "local"
    assert storage["asset_external"] is False
    assert storage["configured"] is True
    assert storage["ready"] is True
    assert storage["readiness"]["root_exists"] is False
    assert storage["readiness"]["parent_exists"] is True
    assert storage["readiness"]["parent_writable"] is True
    assert str(asset_root) not in response.text
    assert str(tmp_path) not in response.text


def test_storage_diagnostics_redacts_s3_configuration_values() -> None:
    payload = storage_diagnostics(
        SimpleNamespace(
            settings=SimpleNamespace(
                asset_storage_backend="s3",
                asset_storage_s3_bucket="private-memory-bucket",
                asset_storage_s3_prefix="tenant-a/private",
                asset_storage_s3_endpoint_url="https://minio.internal.example",
                asset_storage_s3_region="eu-secret-1",
                asset_storage_s3_access_key_id="AKIA-DIAGNOSTIC-SECRET",
                asset_storage_s3_secret_access_key="s3-diagnostic-secret",
                asset_storage_s3_session_token="s3-diagnostic-session-secret",
                asset_storage_s3_force_path_style=True,
            )
        )
    )

    assert payload == {
        "asset_backend": "s3",
        "asset_external": True,
        "configured": True,
        "ready": True,
        "readiness": {
            "bucket_configured": True,
            "prefix_configured": True,
            "endpoint_configured": True,
            "region_configured": True,
            "explicit_credentials_configured": True,
            "session_token_configured": True,
            "force_path_style": True,
            "network_probe": "not_performed",
        },
        "maintenance": {
            "enabled": False,
            "interval_seconds": 3600,
            "limit": 100,
            "prefix_configured": False,
            "cleanup_apply_enabled": False,
            "cleanup_max_deletions": 100,
            "cleanup_grace_period_seconds": 86_400,
            "integrity_max_blob_read_bytes": 8 * 1024 * 1024,
        },
    }
    serialized = repr(payload)
    assert "private-memory-bucket" not in serialized
    assert "tenant-a/private" not in serialized
    assert "minio.internal.example" not in serialized
    assert "eu-secret-1" not in serialized
    assert "AKIA-DIAGNOSTIC-SECRET" not in serialized
    assert "s3-diagnostic-secret" not in serialized


def test_operational_metrics_alert_when_local_asset_storage_path_is_not_directory(
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "asset-root-file"
    asset_root.write_text("not a directory")
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'diagnostic-storage-alert.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(asset_root),
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/diagnostics/metrics")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["storage"]["asset_backend"] == "local"
    assert body["storage"]["ready"] is False
    assert body["storage"]["readiness"]["root_exists"] is True
    assert body["storage"]["readiness"]["root_is_dir"] is False
    assert {
        "name": "asset_storage_not_ready",
        "severity": "critical",
        "status": "firing",
        "value": 1,
        "threshold": 0,
        "playbook_command": "python -m infinity_context_server.doctor",
    } in body["alerts"]
    assert str(asset_root) not in response.text


def test_capabilities_keep_transcription_disabled_when_provider_is_disabled(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'disabled-asr-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="media_api",
            extraction_external_ai_enabled=True,
            transcription_provider="disabled",
            openai_api_key="sk-unused-transcription-secret",
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["external_provider_egress"] is True
    assert extraction["optional_extras"]["vision"]["configured"] is True
    assert extraction["optional_extras"]["transcription_api"]["configured"] is False
    assert extraction["optional_extras"]["transcription_api"]["provider"] == "disabled"
    assert extraction["providers"]["transcription_api"]["status"] == "blocked"
    assert extraction["providers"]["transcription_api"]["reason"] == "provider_disabled"
    assert extraction["providers"]["transcription_api"]["user_retryable"] is False
    assert extraction["providers"]["transcription_api"]["operator_action"] == "enable_provider"
    profile_states = {profile["name"]: profile for profile in extraction["profiles_v2"]}
    assert profile_states["media_api"]["status"] == "blocked"
    assert profile_states["media_api"]["reason"] == "provider_disabled"
    assert profile_states["media_api"]["user_retryable"] is False
    assert profile_states["media_api"]["operator_action"] == "enable_provider"
    assert "sk-unused-transcription-secret" not in response.text


def test_capabilities_show_capture_disabled_when_policy_is_manual_only(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'manual-capture-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            policy_mode=MemoryPolicyMode.MANUAL_ONLY,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["policy_mode"] == "manual_only"
    assert response.json()["captures"]["mode"] == "suggest"
    assert response.json()["captures"]["enabled"] is False


def test_capabilities_require_explicit_auto_apply_safe_switch(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'auto-apply-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            policy_mode=MemoryPolicyMode.SUGGESTIONS,
            capture_mode=CaptureMode.AUTO_APPLY_SAFE,
            auto_apply_safe_enabled=False,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["captures"]["mode"] == "auto_apply_safe"
    assert response.json()["captures"]["enabled"] is True
    assert response.json()["captures"]["auto_apply_safe_enabled"] is False


def test_settings_auto_memory_mode_alias_wins_over_capture_mode(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_CAPTURE_MODE", "retrieve_only")
    monkeypatch.setenv("MEMORY_AUTO_MEMORY_MODE", "suggest")

    settings = Settings(
        _env_file=None,
        deploy_profile=DeployProfile.TEST,
        qdrant_enabled=False,
        graphiti_enabled=False,
        embeddings_enabled=False,
    )

    assert settings.capture_mode == CaptureMode.SUGGEST


def test_legacy_client_routes_are_opt_in() -> None:
    client = build_test_client()
    capabilities = client.get("/v1/capabilities")
    legacy_context = client.post(
        "/api/v1/interview-memory/context",
        json={
            "session_id": "disabled-legacy",
            "current_request": {"id": "req-1", "label": "request", "text": "hello"},
        },
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["supports_legacy_client_routes"] is False
    assert legacy_context.status_code == 404


def test_legacy_client_route_flag_enables_compatibility_routes(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'legacy-routes.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    with TestClient(app) as client:
        capabilities = client.get("/v1/capabilities")
        legacy_context = client.post(
            "/api/v1/interview-memory/context",
            json={
                "session_id": "enabled-legacy",
                "current_request": {"id": "req-1", "label": "request", "text": "hello"},
            },
        )

    assert capabilities.status_code == 200
    assert capabilities.json()["supports_legacy_client_routes"] is True
    assert legacy_context.status_code != 404


def test_capability_descriptor_contract_defaults_are_safe() -> None:
    descriptor = CapabilityDescriptor(
        capability=MemoryCapability.TEMPORAL_FACT_GRAPH,
        adapter_name="graphiti",
        mode=CapabilityMode.PRIMARY,
        status=CapabilityStatus.OK,
        enabled=True,
        supports_scope_filter=True,
        supports_source_refs=True,
        supports_update=True,
        supports_delete=True,
    )

    assert descriptor.projection_freshness == ProjectionFreshness.NOT_APPLICABLE
    assert descriptor.external_ai_allowed is False
    assert descriptor.metadata == {}


def test_capability_recall_contract_validates_scope_and_score() -> None:
    scope = MemoryScopeFilter(space_id="space-1", memory_scope_ids=("memory_scope-1",))
    query = CapabilityRecallQuery(
        scope=scope,
        query="architecture decision",
        limit=5,
        consistency_mode=ConsistencyMode.REQUIRE_FRESH_PROJECTION,
        min_score=0.75,
    )
    candidate = CapabilityRecallCandidate(
        item_id="fact-1",
        item_type="fact",
        text="Use Infinity Context Core as canonical source of truth.",
        score=0.91,
        source_refs=(SourceRef(source_type="manual", source_id="note-1"),),
        capability=MemoryCapability.FACT_PROJECTION,
        adapter_name="postgres",
    )

    assert query.consistency_mode == ConsistencyMode.REQUIRE_FRESH_PROJECTION
    assert candidate.source_refs[0].source_id == "note-1"


def test_capability_ports_are_role_specific_protocols() -> None:
    assert "ingest_document" in DocumentMemoryPort.__dict__
    assert "recall" in RagRecallPort.__dict__
    assert "upsert_fact" in TemporalFactGraphPort.__dict__
    assert "upsert_fact_projection" in FactProjectionPort.__dict__
    assert "recall_vectors" in VectorRecallPort.__dict__


def test_engine_health_snapshot_uses_capability_descriptors() -> None:
    descriptor = CapabilityDescriptor(
        capability=MemoryCapability.RAG_RECALL,
        adapter_name="cognee",
        mode=CapabilityMode.SECONDARY,
        status=CapabilityStatus.DISABLED,
        enabled=False,
        supports_scope_filter=True,
        supports_source_refs=True,
    )
    snapshot = EngineHealthSnapshot(
        adapter_name="cognee",
        status=CapabilityStatus.DISABLED,
        capabilities=(descriptor,),
    )

    assert snapshot.capabilities[0].capability == MemoryCapability.RAG_RECALL


def test_unexpected_exception_maps_to_safe_internal_error() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-raw-secret")
    async def raise_raw_secret() -> None:
        raise RuntimeError("RAW_INTERNAL_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-raw-secret")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "memory.internal",
            "message": "Internal error",
            "retryable": True,
        }
    }
    assert "RAW_INTERNAL_SECRET_MARKER" not in response.text


def test_invariant_error_maps_to_safe_internal_error() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-invariant-secret")
    async def raise_invariant_secret() -> None:
        raise MemoryInvariantError("RAW_INVARIANT_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-invariant-secret")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "memory.internal",
            "message": "Internal error",
            "retryable": True,
        }
    }
    assert "RAW_INVARIANT_SECRET_MARKER" not in response.text


def test_infrastructure_error_maps_to_safe_provider_unavailable() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-provider-secret")
    async def raise_provider_secret() -> None:
        raise MemoryInfrastructureError("RAW_PROVIDER_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-provider-secret")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "memory.provider_unavailable",
            "message": "Provider unavailable",
            "retryable": True,
        }
    }
    assert "RAW_PROVIDER_SECRET_MARKER" not in response.text
