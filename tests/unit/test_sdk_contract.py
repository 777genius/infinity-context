import json

import httpx
import pytest
from infinity_context_sdk import (
    ContextBundle,
    InfinityContextClient,
    InfinityContextError,
    MemoryScope,
    ReadScope,
)


def test_sdk_sends_auth_and_params() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    response = client.list_suggestions(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        status="pending",
    )

    assert response == {"data": {"ok": True}}
    assert seen["authorization"] == "Bearer test-token"
    assert (
        seen["url"]
        == "http://memory.test/v1/suggestions?space_id=space_client_app&memory_scope_id=memory_scope_default&limit=100&status=pending"
    )


def test_sdk_exposes_process_and_diagnostics_facade_methods() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url}")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.list_facts(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        limit=10,
        cursor="fact_cursor",
    )
    client.get_fact("fact_1")
    client.get_related_facts("fact_1", limit=7, include_other_threads=True)
    client.link_facts(
        "fact_1",
        target_fact_id="fact_2",
        relation_type="supports",
        reason="fact_2 supports fact_1",
    )
    client.list_fact_relations("fact_1", limit=3)
    client.unlink_fact_relation("relation_1")
    client.list_fact_versions("fact_1")
    client.list_document_chunks("doc_1", limit=5, cursor="chunk_cursor")
    client.process_document("doc_1")
    client.diagnostics_outbox(limit=10, cursor="outbox_cursor")
    client.diagnostics_memory_scope("memory_scope_1")

    assert seen == [
        "GET http://memory.test/v1/facts?space_id=space_client_app&memory_scope_id=memory_scope_default&limit=10&status=active&cursor=fact_cursor",
        "GET http://memory.test/v1/facts/fact_1",
        "GET http://memory.test/v1/facts/fact_1/related?limit=7&include_other_threads=true",
        "POST http://memory.test/v1/facts/fact_1/relations",
        "GET http://memory.test/v1/facts/fact_1/relations?limit=3&status=active",
        "DELETE http://memory.test/v1/facts/relations/relation_1",
        "GET http://memory.test/v1/facts/fact_1/versions",
        "GET http://memory.test/v1/documents/doc_1/chunks?limit=5&cursor=chunk_cursor",
        "POST http://memory.test/v1/documents/doc_1/process",
        "GET http://memory.test/v1/diagnostics/outbox?limit=10&cursor=outbox_cursor",
        "GET http://memory.test/v1/diagnostics/memory-scope/memory_scope_1",
    ]


def test_sdk_sends_fact_taxonomy_fields_and_filters() -> None:
    seen: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen.append((request.method, str(request.url), body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.remember_fact(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        text="Use taxonomy for canonical facts.",
        kind="architecture_decision",
        source_refs=[{"source_type": "manual", "source_id": "taxonomy"}],
        category="architecture",
        tags=["memory", "graph"],
        ttl_policy="durable",
    )
    client.list_facts(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        category="architecture",
        tag="memory",
    )

    assert seen[0] == (
        "POST",
        "http://memory.test/v1/facts",
        {
            "space_id": "space_client_app",
            "memory_scope_id": "memory_scope_default",
            "text": "Use taxonomy for canonical facts.",
            "kind": "architecture_decision",
            "source_refs": [{"source_type": "manual", "source_id": "taxonomy"}],
            "classification": "internal",
            "category": "architecture",
            "tags": ["memory", "graph"],
            "ttl_policy": "durable",
        },
    )
    assert seen[1] == (
        "GET",
        "http://memory.test/v1/facts?space_id=space_client_app&memory_scope_id=memory_scope_default&category=architecture&tag=memory&limit=100&status=active",
        None,
    )


def test_sdk_exposes_capability_diagnostics_facade() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://memory.test/v1/capabilities"
        return httpx.Response(
            200,
            json={
                "policy_mode": "active_context",
                "adapters": {"qdrant": {"enabled": False}},
                "enabled_adapters": [],
                "limits": {
                    "max_asset_upload_bytes": 12345,
                    "max_capture_text_chars": 20000,
                },
                "captures": {"enabled": True},
                "suggestions": {"review_tool_supported": True},
                "extraction": {
                    "enabled": True,
                    "default_profile": "standard_vision",
                    "profiles_v2": [
                        {
                            "name": "standard_vision",
                            "enabled": True,
                            "status": "ok",
                            "providers": ["openai_vision"],
                            "external_provider_egress": True,
                            "requires_explicit_external_ai": True,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                        }
                    ],
                    "providers": {
                        "openai_vision": {
                            "status": "ok",
                            "enabled": True,
                            "configured": True,
                        }
                    },
                    "policy": {
                        "schema_version": 2,
                        "external_ai_allowed": True,
                    },
                    "limits": {"max_bytes": 12345},
                },
                "plans": {
                    "current": "free",
                    "resources": {
                        "media_analysis_seconds": {"limit_per_month": 36000},
                    },
                },
                "capabilities": [
                    {
                        "adapter_name": "qdrant",
                        "capability": "vector_recall",
                        "enabled": False,
                        "healthy": False,
                        "status": "disabled",
                    }
                ],
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.capability_diagnostics() == {
        "capabilities": [
            {
                "adapter_name": "qdrant",
                "capability": "vector_recall",
                "enabled": False,
                "healthy": False,
                "status": "disabled",
            }
        ],
        "adapters": {"qdrant": {"enabled": False}},
        "enabled_adapters": [],
        "policy_mode": "active_context",
        "limits": {
            "max_asset_upload_bytes": 12345,
            "max_capture_text_chars": 20000,
        },
        "captures": {"enabled": True},
        "suggestions": {"review_tool_supported": True},
        "extraction": {
            "enabled": True,
            "default_profile": "standard_vision",
            "profiles_v2": [
                {
                    "name": "standard_vision",
                    "enabled": True,
                    "status": "ok",
                    "providers": ["openai_vision"],
                    "external_provider_egress": True,
                    "requires_explicit_external_ai": True,
                    "fallback_profiles": ["standard_local"],
                    "memory_promotion": "review_required",
                    "source_text_policy": "untrusted_evidence",
                    "artifact_payloads_bounded": True,
                }
            ],
            "providers": {
                "openai_vision": {
                    "status": "ok",
                    "enabled": True,
                    "configured": True,
                }
            },
            "policy": {
                "schema_version": 2,
                "external_ai_allowed": True,
            },
            "limits": {"max_bytes": 12345},
        },
        "plans": {
            "current": "free",
            "resources": {
                "media_analysis_seconds": {"limit_per_month": 36000},
            },
        },
    }


def test_sdk_exposes_typed_extraction_capability_diagnostics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://memory.test/v1/capabilities"
        return httpx.Response(
            200,
            json={
                "extraction": {
                    "enabled": True,
                    "default_profile": "media_api",
                    "profiles_v2": [
                        {
                            "name": "media_api",
                            "enabled": True,
                            "status": "ok",
                            "providers": ["transcription_api"],
                            "input_modalities": ["audio", "video"],
                            "evidence_coordinates": ["time_range_ms", "bbox"],
                            "primary_artifact_types": [
                                "transcript",
                                "transcript_json",
                                "keyframe",
                                "video_frame_timeline",
                            ],
                            "transcript_features": [
                                "segments",
                                "time_ranges",
                                "transcript_json",
                                "optional_speaker_labels",
                            ],
                            "video_features": [
                                "ffprobe_metadata",
                                "sampled_keyframes",
                                "frame_timeline",
                            ],
                            "external_provider_egress": True,
                            "requires_explicit_external_ai": True,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                            "may_run_local_asr": False,
                        },
                        {
                            "name": "media_local_asr",
                            "enabled": False,
                            "status": "unavailable",
                            "reason": "provider_package_missing",
                            "providers": ["transcription_local"],
                            "input_modalities": ["audio", "video"],
                            "evidence_coordinates": ["time_range_ms"],
                            "primary_artifact_types": [
                                "media_manifest",
                                "transcript",
                                "transcript_json",
                            ],
                            "transcript_features": [
                                "segments",
                                "time_ranges",
                                "transcript_json",
                            ],
                            "video_features": ["ffprobe_metadata"],
                            "external_provider_egress": False,
                            "requires_explicit_external_ai": False,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                            "may_run_local_asr": True,
                            "replacement_profiles": [],
                        },
                        {
                            "name": "standard_asr",
                            "enabled": True,
                            "status": "ok",
                            "providers": ["transcription_api"],
                            "input_modalities": ["audio", "video"],
                            "evidence_coordinates": ["time_range_ms", "bbox"],
                            "primary_artifact_types": [
                                "transcript",
                                "transcript_json",
                                "keyframe",
                                "video_frame_timeline",
                            ],
                            "transcript_features": [
                                "segments",
                                "time_ranges",
                                "transcript_json",
                                "optional_speaker_labels",
                            ],
                            "video_features": [
                                "ffprobe_metadata",
                                "sampled_keyframes",
                                "frame_timeline",
                            ],
                            "external_provider_egress": True,
                            "requires_explicit_external_ai": True,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                            "may_run_local_asr": False,
                            "deprecated": True,
                            "replacement_profiles": ["media_api", "media_local_asr"],
                        },
                    ],
                    "providers": {
                        "transcription_api": {"status": "ok", "configured": True},
                        "openai_vision": {
                            "status": "blocked",
                            "configured": False,
                            "reason": "provider_credential_missing",
                            "user_retryable": False,
                            "operator_action": "configure_provider_credential",
                        },
                    },
                    "policy": {"schema_version": 2, "external_ai_allowed": True},
                    "evidence_contract": {
                        "schema_version": "infinity_context.extraction_evidence_contract.v1",
                        "source_ref_coordinate_fields": [
                            "char_start",
                            "char_end",
                            "page_number",
                            "bbox",
                            "time_start_ms",
                            "time_end_ms",
                        ],
                    },
                    "feature_contract": {
                        "schema_version": "infinity_context.extraction_feature_contract.v1",
                        "profile_feature_fields": [
                            "document_features",
                            "vision_features",
                            "transcript_features",
                            "video_features",
                        ],
                    },
                    "provider_contract": {
                        "schema_version": "infinity_context.extraction_provider_contract.v1",
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
                            "endpoint_family": "responses",
                            "supported_file_types": [
                                ".gif",
                                ".jpeg",
                                ".jpg",
                                ".png",
                                ".webp",
                            ],
                            "effective_max_upload_bytes": 12345,
                        },
                        "transcription": {
                            "provider": "openai",
                            "provider_name": "transcription_api",
                            "endpoint": "/v1/audio/transcriptions",
                            "supported_file_types": [
                                ".flac",
                                ".m4a",
                                ".mp3",
                                ".mp4",
                                ".mpeg",
                                ".mpga",
                                ".ogg",
                                ".wav",
                                ".webm",
                            ],
                            "max_provider_upload_bytes": 26214400,
                            "effective_max_upload_bytes": 12345,
                        },
                    },
                    "manifest_contract": {
                        "schema_version": "infinity_context.multimodal_manifest_contract.v1",
                        "manifest_schema_version": "infinity_context.multimodal_manifest.v1",
                        "artifact_type": "media_manifest",
                        "coordinate_fields": ["page_number", "bbox", "time_range"],
                        "raw_provider_payloads_in_public_api": False,
                    },
                    "file_type_detection": {
                        "schema_version": "infinity_context.file_type_detection_contract.v1",
                        "declared_content_type_trusted": False,
                        "recognized_content_types": [
                            "image/webp",
                            "audio/ogg",
                            "video/webm",
                        ],
                        "recognized_file_suffixes": [".webp", ".ogg", ".webm"],
                        "recognized_content_types_are_extraction_hints_not_guarantees": True,
                        "diagnostic_fields": [
                            "detected_content_type",
                            "mime_content_type_mismatch",
                        ],
                    },
                    "modality_actions": {
                        "audio": {
                            "transcription_api": {
                                "profile": "media_api",
                                "enabled": True,
                                "status": "ok",
                                "providers": ["transcription_api"],
                                "artifact_types": ["transcript", "transcript_json"],
                                "evidence_coordinates": ["time_range_ms"],
                                "external_provider_egress": True,
                                "requires_explicit_external_ai": True,
                                "fallback_profiles": ["standard_local"],
                                "memory_promotion": "review_required",
                                "source_text_policy": "untrusted_evidence",
                                "artifact_payloads_bounded": True,
                            }
                        },
                        "image": {
                            "vision": {
                                "profile": "standard_vision",
                                "enabled": False,
                                "status": "blocked",
                                "reason": "provider_credential_missing",
                                "providers": ["openai_vision"],
                                "artifact_types": ["vision_json", "image_regions"],
                                "evidence_coordinates": ["bbox"],
                                "external_provider_egress": True,
                                "requires_explicit_external_ai": True,
                                "fallback_profiles": ["standard_local"],
                                "memory_promotion": "review_required",
                                "source_text_policy": "untrusted_evidence",
                                "artifact_payloads_bounded": True,
                            }
                        },
                    },
                    "degraded_components": [
                        {
                            "component_type": "provider",
                            "name": "openai_vision",
                            "status": "blocked",
                            "reason": "provider_credential_missing",
                            "user_retryable": False,
                            "operator_action": "configure_provider_credential",
                        },
                        {
                            "component_type": "modality_action",
                            "name": "image.vision",
                            "status": "blocked",
                            "reason": "provider_credential_missing",
                            "user_retryable": False,
                            "operator_action": "configure_provider_credential",
                        },
                    ],
                    "limits": {"max_media_seconds": 600},
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        transport=httpx.MockTransport(handler),
    )

    diagnostics = client.extraction_capability_diagnostics()
    assert diagnostics.enabled is True
    assert diagnostics.default_profile == "media_api"
    assert diagnostics.policy["schema_version"] == 2
    assert diagnostics.evidence_contract["schema_version"] == (
        "infinity_context.extraction_evidence_contract.v1"
    )
    assert diagnostics.evidence_contract["source_ref_coordinate_fields"] == [
        "char_start",
        "char_end",
        "page_number",
        "bbox",
        "time_start_ms",
        "time_end_ms",
    ]
    assert diagnostics.feature_contract["schema_version"] == (
        "infinity_context.extraction_feature_contract.v1"
    )
    assert diagnostics.provider_contract["schema_version"] == (
        "infinity_context.extraction_provider_contract.v1"
    )
    assert diagnostics.provider_contract["local_media_subprocess_policy"] == {
        "parser_family": "ffmpeg_ffprobe",
        "protocol_whitelist": ["file"],
        "network_protocols_allowed": False,
        "stdin_policy": "closed",
        "timeout_field": "limits.subprocess_timeout_seconds",
    }
    assert diagnostics.provider_contract["vision"]["supported_file_types"] == [
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    ]
    assert diagnostics.provider_contract["transcription"]["supported_file_types"] == [
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpga",
        ".ogg",
        ".wav",
        ".webm",
    ]
    assert (
        diagnostics.provider_contract["transcription"]["endpoint"]
        == "/v1/audio/transcriptions"
    )
    assert diagnostics.manifest_contract["schema_version"] == (
        "infinity_context.multimodal_manifest_contract.v1"
    )
    assert diagnostics.manifest_contract["artifact_type"] == "media_manifest"
    assert diagnostics.manifest_contract["coordinate_fields"] == [
        "page_number",
        "bbox",
        "time_range",
    ]
    assert diagnostics.manifest_contract["raw_provider_payloads_in_public_api"] is False
    assert diagnostics.file_type_detection["schema_version"] == (
        "infinity_context.file_type_detection_contract.v1"
    )
    assert diagnostics.file_type_detection["declared_content_type_trusted"] is False
    assert diagnostics.file_type_detection["recognized_content_types"] == [
        "image/webp",
        "audio/ogg",
        "video/webm",
    ]
    assert diagnostics.file_type_detection["recognized_file_suffixes"] == [
        ".webp",
        ".ogg",
        ".webm",
    ]
    assert (
        diagnostics.file_type_detection[
            "recognized_content_types_are_extraction_hints_not_guarantees"
        ]
        is True
    )
    assert diagnostics.file_type_detection["diagnostic_fields"] == [
        "detected_content_type",
        "mime_content_type_mismatch",
    ]
    assert diagnostics.modality_action("audio", "transcription_api") == {
        "profile": "media_api",
        "enabled": True,
        "status": "ok",
        "providers": ["transcription_api"],
        "artifact_types": ["transcript", "transcript_json"],
        "evidence_coordinates": ["time_range_ms"],
        "external_provider_egress": True,
        "requires_explicit_external_ai": True,
        "fallback_profiles": ["standard_local"],
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "artifact_payloads_bounded": True,
    }
    assert diagnostics.modality_action("image", "vision")["reason"] == (
        "provider_credential_missing"
    )
    assert diagnostics.modality_action("video", "transcription_api") is None
    assert diagnostics.degraded_components == (
        {
            "component_type": "provider",
            "name": "openai_vision",
            "status": "blocked",
            "reason": "provider_credential_missing",
            "user_retryable": False,
            "operator_action": "configure_provider_credential",
        },
        {
            "component_type": "modality_action",
            "name": "image.vision",
            "status": "blocked",
            "reason": "provider_credential_missing",
            "user_retryable": False,
            "operator_action": "configure_provider_credential",
        },
    )
    assert diagnostics.limits["max_media_seconds"] == 600
    assert diagnostics.provider_status("transcription_api") == "ok"
    assert diagnostics.provider_action("openai_vision") == "configure_provider_credential"
    assert diagnostics.provider_user_retryable("openai_vision") is False
    assert diagnostics.degraded_component("provider", "openai_vision") == {
        "component_type": "provider",
        "name": "openai_vision",
        "status": "blocked",
        "reason": "provider_credential_missing",
        "user_retryable": False,
        "operator_action": "configure_provider_credential",
    }
    assert diagnostics.degraded_component("provider", "missing") is None
    media_api = diagnostics.profile("media_api")
    assert media_api is not None
    assert media_api.status == "ok"
    assert media_api.providers == ("transcription_api",)
    assert media_api.input_modalities == ("audio", "video")
    assert media_api.evidence_coordinates == ("time_range_ms", "bbox")
    assert media_api.primary_artifact_types == (
        "transcript",
        "transcript_json",
        "keyframe",
        "video_frame_timeline",
    )
    assert media_api.transcript_features == (
        "segments",
        "time_ranges",
        "transcript_json",
        "optional_speaker_labels",
    )
    assert media_api.video_features == (
        "ffprobe_metadata",
        "sampled_keyframes",
        "frame_timeline",
    )
    assert media_api.external_provider_egress is True
    assert media_api.memory_promotion == "review_required"
    assert media_api.may_run_local_asr is False
    local_asr = diagnostics.profile("media_local_asr")
    assert local_asr is not None
    assert local_asr.reason == "provider_package_missing"
    assert local_asr.evidence_coordinates == ("time_range_ms",)
    assert local_asr.transcript_features == ("segments", "time_ranges", "transcript_json")
    assert "optional_speaker_labels" not in local_asr.transcript_features
    assert local_asr.may_run_local_asr is True
    standard_asr = diagnostics.profile("standard_asr")
    assert standard_asr is not None
    assert standard_asr.deprecated is True
    assert standard_asr.may_run_local_asr is False
    assert standard_asr.replacement_profiles == ("media_api", "media_local_asr")
    assert diagnostics.profile("missing") is None


def test_sdk_defaults_legacy_extraction_capability_contract_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://memory.test/v1/capabilities"
        return httpx.Response(
            200,
            json={
                "extraction": {
                    "enabled": True,
                    "default_profile": "standard_local",
                    "profiles_v2": [
                        {
                            "name": "standard_local",
                            "enabled": True,
                            "status": "ok",
                            "providers": ["local_text"],
                            "external_provider_egress": False,
                            "requires_explicit_external_ai": False,
                            "fallback_profiles": [],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                        },
                    ],
                    "providers": {},
                    "policy": {"schema_version": 1},
                    "limits": {},
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        transport=httpx.MockTransport(handler),
    )

    diagnostics = client.extraction_capability_diagnostics()
    standard_local = diagnostics.profile("standard_local")

    assert diagnostics.evidence_contract == {}
    assert diagnostics.provider_contract == {}
    assert diagnostics.manifest_contract == {}
    assert diagnostics.file_type_detection == {}
    assert diagnostics.degraded_components == ()
    assert standard_local is not None
    assert standard_local.input_modalities == ()
    assert standard_local.evidence_coordinates == ()
    assert standard_local.primary_artifact_types == ()
    assert standard_local.document_features == ()
    assert standard_local.vision_features == ()
    assert standard_local.transcript_features == ()
    assert standard_local.video_features == ()
    assert standard_local.raw is not None
    assert "input_modalities" not in standard_local.raw


def test_sdk_sends_memory_insights_scope_and_limits() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"insights_id": "ins_1"}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    response = client.build_insights(
        space_slug="atlas",
        memory_scope_external_refs=["engineering", "product"],
        max_facts=50,
        max_suggestions=25,
        max_activity=12,
    )

    assert response == {"data": {"insights_id": "ins_1"}}
    assert seen == {
        "method": "POST",
        "url": "http://memory.test/v1/insights",
        "body": {
            "space_slug": "atlas",
            "memory_scope_external_refs": ["engineering", "product"],
            "max_facts": 50,
            "max_documents": 100,
            "max_episodes": 100,
            "max_suggestions": 25,
            "max_captures": 100,
            "max_activity": 12,
        },
    }


def test_sdk_exports_graph_with_episode_limit() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"data": {"schema_version": "infinity_context.graph_export.v1"}},
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    response = client.export_graph(
        space_slug="atlas",
        memory_scope_external_ref="engineering",
        thread_external_ref="meeting-1",
        max_documents=7,
        max_episodes=9,
        max_chunks=11,
    )

    assert response == {"data": {"schema_version": "infinity_context.graph_export.v1"}}
    assert seen["method"] == "GET"
    assert (
        seen["url"]
        == "http://memory.test/v1/export/graph.json?space_slug=atlas&memory_scope_external_ref=engineering&thread_external_ref=meeting-1&include_deleted=false&include_restricted=false&max_facts=250&max_documents=7&max_episodes=9&max_chunks=11"
    )


def test_sdk_facade_accepts_additive_response_fields() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "rendered_text": "Known memory evidence.",
                    "items": [],
                    "new_optional_server_field": {"safe": True},
                },
                "meta": {
                    "request_id": "ctx_1",
                    "new_optional_meta_field": "ignored-by-callers",
                },
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    response = client.build_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="additive fields",
    )

    assert response["data"]["rendered_text"] == "Known memory evidence."
    assert response["data"]["new_optional_server_field"] == {"safe": True}


def test_sdk_build_typed_context_returns_bounded_safe_diagnostics() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "meta": {"request_id": "req_1"},
                "data": {
                    "bundle_id": "ctx_1",
                    "rendered_text": "Known memory evidence.",
                    "diagnostics": {
                        "context_assembly_version": "context-v2-hybrid-explainable",
                        "consistency_mode": "best_effort",
                        "vector_status": "ok",
                        "graph_status": "degraded",
                        "rag_status": "skipped",
                        "artifact_evidence_status": "ok",
                        "retrieval_sources_used": [f"source_{index}" for index in range(12)],
                        "retrieval_sources_total": 12,
                        "retrieval_sources_returned": 8,
                        "retrieval_sources_truncated": True,
                        "facts_considered": 5,
                        "keyword_chunks_considered": 6,
                        "vector_candidate_count": 9,
                        "vector_hydrated_count": 8,
                        "graph_candidate_count": 7,
                        "graph_hydrated_count": 6,
                        "artifact_evidence_jobs_considered": 4,
                        "artifact_evidence_manifests_considered": 3,
                        "artifact_evidence_manifests_used": 2,
                        "artifact_evidence_items_considered": 5,
                        "artifact_evidence_items_used": 4,
                        "artifact_evidence_ranked_candidate_count": 8,
                        "artifact_evidence_candidate_cap_reached_count": 1,
                        "artifact_evidence_confidence_signal_count": 6,
                        "artifact_evidence_coordinate_signal_count": 3,
                        "artifact_evidence_query_drop_count": 1,
                        "artifact_evidence_sensitive_drop_count": 2,
                        "artifact_evidence_prompt_injection_drop_count": 1,
                        "artifact_evidence_manifest_too_large_count": 1,
                        "artifact_evidence_read_error_count": 1,
                        "artifact_evidence_parse_error_count": 1,
                        "artifact_evidence_schema_skip_count": 1,
                        "artifact_evidence_stale_asset_drop_count": 1,
                        "stale_vector_drop_count": 1,
                        "stale_graph_drop_count": 2,
                        "stale_rag_drop_count": 3,
                        "stale_facts_considered": 6,
                        "stale_facts_used": 3,
                        "superseded_facts_considered": 4,
                        "superseded_facts_used": 2,
                        "hybrid_items_used": 2,
                        "temporal_relations_considered": 4,
                        "temporal_replacements_applied": 1,
                        "temporal_contradictions_considered": 2,
                        "temporal_relations_skipped_by_validity": 3,
                        "pending_conflict_suggestions_considered": 11,
                        "pending_duplicate_merge_suggestions_considered": 5,
                        "items_considered": 14,
                        "items_used": 7,
                        "dropped_by_instruction_flag": 1,
                        "dropped_by_budget": 2,
                        "dropped_by_source_cap": 3,
                        "dropped_by_char_cap": 4,
                        "multimodal_source_ref_count": 5,
                        "items_with_multimodal_source_refs": 2,
                        "source_refs_with_page_count": 3,
                        "source_refs_with_bbox_count": 1,
                        "source_refs_with_time_range_count": 2,
                        "source_refs_total": 25,
                        "source_refs_returned": 20,
                        "source_refs_truncated": True,
                        "citations_total": 25,
                        "citations_returned": 20,
                        "citations_truncated": True,
                        "items_with_citations": 1,
                        "citation_quote_previews_rendered": 9,
                        "sensitive_citation_quote_previews_skipped": 1,
                        "api_key": raw_secret,
                    },
                    "items": [
                        {
                            "item_id": "chunk_1",
                            "item_type": "chunk",
                            "memory_scope_id": "memory_scope_default",
                            "text": "Chunk evidence.",
                            "score": 0.91,
                            "is_instruction": False,
                            "source_refs": [
                                {
                                    "source_type": "document",
                                    "source_id": f"doc_{index}",
                                    "chunk_id": f"chunk_{index}",
                                    "quote_preview": f"preview {index}",
                                    "page_number": index + 1,
                                    "time_start_ms": index * 1000,
                                    "time_end_ms": index * 1000 + 500,
                                    "bbox": [0, 1, 120, 40],
                                }
                                for index in range(25)
                            ],
                            "citations": [
                                {
                                    "citation_id": f"chunk:chunk_1:citation:{index + 1}",
                                    "label": f"[{index + 1}] document doc_{index} p.{index + 1}",
                                    "source_type": "document",
                                    "source_id": f"doc_{index}",
                                    "chunk_id": f"chunk_{index}",
                                    "quote_preview": f"preview {index}",
                                    "char_range": {"start": index, "end": index + 10},
                                    "page_number": index + 1,
                                    "time_range_ms": {
                                        "start": index * 1000,
                                        "end": index * 1000 + 500,
                                    },
                                    "bbox": [0, 1, 120, 40],
                                }
                                for index in range(25)
                            ],
                            "diagnostics": {
                                "retrieval_source": "vector_chunks",
                                "retrieval_sources": [
                                    "vector_chunks",
                                    "keyword_chunks",
                                ],
                                "retrieval_sources_total": 12,
                                "retrieval_sources_returned": 8,
                                "retrieval_sources_truncated": True,
                                "citations_total": 25,
                                "citations_returned": 20,
                                "citations_truncated": True,
                                "review_only": True,
                                "stale_reason": "fact_status_superseded",
                                "score_signals": {
                                    "base_score": 0.91,
                                    "provider_note": f"Bearer {raw_secret}",
                                    "nested": {"unsafe": "skip"},
                                },
                                "provenance": {
                                    "source_ref_count": 25,
                                    "token": raw_secret,
                                },
                            },
                        },
                        {
                            "item_id": "fact_1",
                            "item_type": "fact",
                            "memory_scope_id": "memory_scope_default",
                            "text": "Current fact evidence.",
                            "score": 0.72,
                            "is_instruction": False,
                            "diagnostics": {
                                "retrieval_sources": ["facts"],
                                "review_only": "false",
                            },
                        },
                    ],
                },
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="typed context",
        consistency_mode="best_effort",
        max_evidence_items=9,
        include_superseded=True,
        include_stale=True,
    )

    assert isinstance(bundle, ContextBundle)
    assert seen["url"] == "http://memory.test/v1/context"
    assert seen["body"]["consistency_mode"] == "best_effort"
    assert seen["body"]["max_evidence_items"] == 9
    assert seen["body"]["include_superseded"] is True
    assert seen["body"]["include_stale"] is True
    assert bundle.bundle_id == "ctx_1"
    assert bundle.meta["request_id"] == "req_1"
    assert bundle.diagnostics.context_assembly_version == "context-v2-hybrid-explainable"
    assert bundle.diagnostics.vector_status == "ok"
    assert bundle.diagnostics.graph_status == "degraded"
    assert bundle.diagnostics.rag_status == "skipped"
    assert bundle.diagnostics.artifact_evidence_status == "ok"
    assert bundle.diagnostics.retrieval_sources_used == tuple(
        f"source_{index}" for index in range(8)
    )
    assert bundle.diagnostics.retrieval_sources_total == 12
    assert bundle.diagnostics.retrieval_sources_returned == 8
    assert bundle.diagnostics.retrieval_sources_truncated is True
    assert bundle.diagnostics.facts_considered == 5
    assert bundle.diagnostics.keyword_chunks_considered == 6
    assert bundle.diagnostics.vector_candidate_count == 9
    assert bundle.diagnostics.vector_hydrated_count == 8
    assert bundle.diagnostics.graph_candidate_count == 7
    assert bundle.diagnostics.graph_hydrated_count == 6
    assert bundle.diagnostics.artifact_evidence_jobs_considered == 4
    assert bundle.diagnostics.artifact_evidence_manifests_considered == 3
    assert bundle.diagnostics.artifact_evidence_manifests_used == 2
    assert bundle.diagnostics.artifact_evidence_items_considered == 5
    assert bundle.diagnostics.artifact_evidence_items_used == 4
    assert bundle.diagnostics.artifact_evidence_ranked_candidate_count == 8
    assert bundle.diagnostics.artifact_evidence_candidate_cap_reached_count == 1
    assert bundle.diagnostics.artifact_evidence_confidence_signal_count == 6
    assert bundle.diagnostics.artifact_evidence_coordinate_signal_count == 3
    assert bundle.diagnostics.artifact_evidence_query_drop_count == 1
    assert bundle.diagnostics.artifact_evidence_sensitive_drop_count == 2
    assert bundle.diagnostics.artifact_evidence_prompt_injection_drop_count == 1
    assert bundle.diagnostics.artifact_evidence_manifest_too_large_count == 1
    assert bundle.diagnostics.artifact_evidence_read_error_count == 1
    assert bundle.diagnostics.artifact_evidence_parse_error_count == 1
    assert bundle.diagnostics.artifact_evidence_schema_skip_count == 1
    assert bundle.diagnostics.artifact_evidence_stale_asset_drop_count == 1
    assert bundle.diagnostics.stale_vector_drop_count == 1
    assert bundle.diagnostics.stale_graph_drop_count == 2
    assert bundle.diagnostics.stale_rag_drop_count == 3
    assert bundle.diagnostics.stale_facts_considered == 6
    assert bundle.diagnostics.stale_facts_used == 3
    assert bundle.diagnostics.superseded_facts_considered == 4
    assert bundle.diagnostics.superseded_facts_used == 2
    assert bundle.diagnostics.hybrid_items_used == 2
    assert bundle.diagnostics.temporal_relations_considered == 4
    assert bundle.diagnostics.temporal_replacements_applied == 1
    assert bundle.diagnostics.temporal_contradictions_considered == 2
    assert bundle.diagnostics.temporal_relations_skipped_by_validity == 3
    assert bundle.diagnostics.pending_conflict_suggestions_considered == 11
    assert bundle.diagnostics.pending_duplicate_merge_suggestions_considered == 5
    assert bundle.diagnostics.items_considered == 14
    assert bundle.diagnostics.items_used == 7
    assert bundle.diagnostics.dropped_by_instruction_flag == 1
    assert bundle.diagnostics.dropped_by_budget == 2
    assert bundle.diagnostics.dropped_by_source_cap == 3
    assert bundle.diagnostics.dropped_by_char_cap == 4
    assert bundle.diagnostics.multimodal_source_ref_count == 5
    assert bundle.diagnostics.items_with_multimodal_source_refs == 2
    assert bundle.diagnostics.source_refs_with_page_count == 3
    assert bundle.diagnostics.source_refs_with_bbox_count == 1
    assert bundle.diagnostics.source_refs_with_time_range_count == 2
    assert bundle.diagnostics.source_refs_total == 25
    assert bundle.diagnostics.source_refs_returned == 20
    assert bundle.diagnostics.source_refs_truncated is True
    assert bundle.diagnostics.citations_total == 25
    assert bundle.diagnostics.citations_returned == 20
    assert bundle.diagnostics.citations_truncated is True
    assert bundle.diagnostics.items_with_citations == 1
    assert bundle.diagnostics.citation_quote_previews_rendered == 9
    assert bundle.diagnostics.sensitive_citation_quote_previews_skipped == 1
    assert "api_key" not in bundle.diagnostics.raw

    item = bundle.items[0]
    assert item.memory_scope_id == "memory_scope_default"
    assert len(item.source_refs) == 20
    assert len(item.citations) == 20
    assert item.source_refs[0].source_id == "doc_0"
    assert item.source_refs[0].page_number == 1
    assert item.source_refs[0].time_start_ms == 0
    assert item.source_refs[0].time_end_ms == 500
    assert item.source_refs[0].bbox == (0.0, 1.0, 120.0, 40.0)
    assert item.citations[0].citation_id == "chunk:chunk_1:citation:1"
    assert item.citations[0].source_id == "doc_0"
    assert item.citations[0].char_start == 0
    assert item.citations[0].char_end == 10
    assert item.citations[0].page_number == 1
    assert item.citations[0].time_start_ms == 0
    assert item.citations[0].time_end_ms == 500
    assert item.citations[0].bbox == (0.0, 1.0, 120.0, 40.0)
    assert item.diagnostics.retrieval_source == "vector_chunks"
    assert item.diagnostics.retrieval_sources == ("vector_chunks", "keyword_chunks")
    assert item.diagnostics.retrieval_sources_total == 12
    assert item.diagnostics.retrieval_sources_returned == 8
    assert item.diagnostics.retrieval_sources_truncated is True
    assert item.diagnostics.citations_total == 25
    assert item.diagnostics.citations_returned == 20
    assert item.diagnostics.citations_truncated is True
    assert item.diagnostics.ranking_reason == "hybrid match via vector_chunks, keyword_chunks"
    assert item.diagnostics.review_only is True
    assert item.diagnostics.stale_reason == "fact_status_superseded"
    assert item.diagnostics.raw["review_only"] is True
    assert item.diagnostics.score_signals["base_score"] == 0.91
    assert item.diagnostics.score_signals["provider_note"] == "[redacted]"
    assert "nested" not in item.diagnostics.score_signals
    assert "token" not in item.diagnostics.provenance
    active_item = bundle.items[1]
    assert active_item.diagnostics.review_only is False
    assert active_item.diagnostics.stale_reason is None
    assert raw_secret not in str(bundle)


def test_sdk_typed_context_defaults_missing_diagnostic_counters() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "bundle_id": "ctx_legacy",
                    "rendered_text": "",
                    "diagnostics": {
                        "context_assembly_version": "context-v2-hybrid-explainable",
                        "consistency_mode": "best_effort",
                    },
                    "items": [],
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="legacy diagnostics",
    )

    assert bundle.diagnostics.vector_status == "unknown"
    assert bundle.diagnostics.graph_status == "unknown"
    assert bundle.diagnostics.rag_status == "unknown"
    assert bundle.diagnostics.retrieval_sources_total == 0
    assert bundle.diagnostics.retrieval_sources_returned == 0
    assert bundle.diagnostics.retrieval_sources_truncated is False
    assert bundle.diagnostics.facts_considered == 0
    assert bundle.diagnostics.keyword_chunks_considered == 0
    assert bundle.diagnostics.vector_candidate_count == 0
    assert bundle.diagnostics.vector_hydrated_count == 0
    assert bundle.diagnostics.graph_candidate_count == 0
    assert bundle.diagnostics.graph_hydrated_count == 0
    assert bundle.diagnostics.stale_vector_drop_count == 0
    assert bundle.diagnostics.stale_graph_drop_count == 0
    assert bundle.diagnostics.stale_rag_drop_count == 0
    assert bundle.diagnostics.hybrid_items_used == 0
    assert bundle.diagnostics.temporal_relations_considered == 0
    assert bundle.diagnostics.temporal_replacements_applied == 0
    assert bundle.diagnostics.temporal_contradictions_considered == 0
    assert bundle.diagnostics.temporal_relations_skipped_by_validity == 0
    assert bundle.diagnostics.pending_conflict_suggestions_considered == 0
    assert bundle.diagnostics.items_considered == 0
    assert bundle.diagnostics.items_used == 0
    assert bundle.diagnostics.dropped_by_instruction_flag == 0
    assert bundle.diagnostics.dropped_by_budget == 0
    assert bundle.diagnostics.dropped_by_source_cap == 0
    assert bundle.diagnostics.dropped_by_char_cap == 0
    assert bundle.diagnostics.source_refs_total == 0
    assert bundle.diagnostics.source_refs_returned == 0
    assert bundle.diagnostics.source_refs_truncated is False


def test_sdk_typed_context_defaults_legacy_item_diagnostics() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "bundle_id": "ctx_legacy_item",
                    "rendered_text": "Legacy evidence.",
                    "diagnostics": {},
                    "items": [
                        {
                            "item_id": "fact_legacy",
                            "item_type": "fact",
                            "text": "Legacy fact evidence.",
                            "score": 0.5,
                        }
                    ],
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="legacy item diagnostics",
    )

    item = bundle.items[0]
    assert item.memory_scope_id is None
    assert item.source_refs == ()
    assert item.is_instruction is False
    assert item.diagnostics.retrieval_source is None
    assert item.diagnostics.retrieval_sources == ()
    assert item.diagnostics.retrieval_sources_total == 0
    assert item.diagnostics.retrieval_sources_returned == 0
    assert item.diagnostics.retrieval_sources_truncated is False
    assert item.diagnostics.ranking_reason == "matched without retrieval channel diagnostics"
    assert item.diagnostics.score_signals == {}
    assert item.diagnostics.provenance == {}
    assert item.diagnostics.review_only is False
    assert item.diagnostics.stale_reason is None
    assert item.diagnostics.raw["retrieval_sources"] == []
    assert item.diagnostics.raw["ranking_reason"] == (
        "matched without retrieval channel diagnostics"
    )


def test_sdk_typed_context_ignores_redacted_retrieval_sources() -> None:
    raw_secret = "Bearer sk-proj-secretvalue1234567890"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "bundle_id": "ctx_noisy_sources",
                    "rendered_text": "",
                    "diagnostics": {
                        "context_assembly_version": "context-v2-hybrid-explainable",
                        "consistency_mode": "best_effort",
                        "retrieval_sources_used": [
                            raw_secret,
                            *(f"provider_noise_{index}" for index in range(12)),
                        ],
                    },
                    "items": [
                        {
                            "item_id": "chunk_1",
                            "item_type": "chunk",
                            "text": "Noisy retrieval source evidence.",
                            "score": 0.9,
                            "diagnostics": {
                                "retrieval_source": "keyword_chunks",
                                "retrieval_sources": [
                                    raw_secret,
                                    *(f"provider_noise_{index}" for index in range(12)),
                                ],
                            },
                        }
                    ],
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="noisy retrieval sources",
    )

    assert bundle.diagnostics.retrieval_sources_used == tuple(
        f"provider_noise_{index}" for index in range(7)
    )
    assert len(bundle.diagnostics.retrieval_sources_used) <= 8
    item_diagnostics = bundle.items[0].diagnostics
    assert item_diagnostics.retrieval_source == "keyword_chunks"
    assert item_diagnostics.retrieval_sources[0] == "keyword_chunks"
    assert "[redacted]" not in repr(bundle)
    assert raw_secret not in repr(bundle)


def test_sdk_build_digest_posts_stable_contract() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"data": {"digest_id": "dig_1"}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    response = client.build_digest(
        topic="Graphiti decisions",
        read_scope=ReadScope(
            space_slug="default",
            memory_scope_external_refs=("engineering", "product"),
        ),
        include_superseded=True,
        include_related=False,
    )

    assert response == {"data": {"digest_id": "dig_1"}}
    assert seen["method"] == "POST"
    assert seen["url"] == "http://memory.test/v1/digest"
    assert seen["body"] == {
        "space_slug": "default",
        "memory_scope_external_refs": ["engineering", "product"],
        "topic": "Graphiti decisions",
        "token_budget": 2400,
        "max_facts": 20,
        "max_chunks": 20,
        "max_suggestions": 10,
        "include_pending_suggestions": True,
        "include_superseded": True,
        "include_related": False,
        "format": "markdown",
    }


def test_sdk_process_document_sends_idempotency_key() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.process_document("doc_1", idempotency_key="process-doc-1")

    assert seen["idempotency_key"] == "process-doc-1"


def test_sdk_exposes_platform_episode_and_thread_memory_methods() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.ingest_episode(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-1",
        source_type="system_audio",
        source_external_id="event-1",
        text="Need FIFO, not LIFO.",
        speaker="interviewer",
        trust_level="medium",
        kind_hint="constraint",
        metadata={"route": "desktop_companion"},
        idempotency_key="event-1",
    )
    client.thread_memory_status(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-1",
    )
    client.delete_thread_memory(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-1",
    )

    assert [f"{method} {path}" for method, path, _body in seen] == [
        "POST /v1/episodes",
        "POST /v1/thread-memory/status",
        "DELETE /v1/thread-memory",
    ]
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["memory_scope_external_ref"] == "default"
    assert seen[0][2]["thread_external_ref"] == "session-1"
    assert seen[0][2]["idempotency_key"] == "event-1"
    assert "space_id" not in seen[0][2]
    assert seen[2][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "thread_external_ref": "session-1",
    }


def test_sdk_exposes_full_capture_facade_methods() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, str(request.url), body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.create_capture(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-1",
        source_agent="codex",
        source_kind="hook",
        event_type="UserPromptSubmit",
        actor_role="user",
        text="Remember: SDK capture facade is complete.",
        source_event_id="event-1",
        source_actor_external_ref="user-1",
        client_instance_id="client-1",
        agent_session_external_ref="session-ext-1",
        turn_external_ref="turn-1",
        parent_capture_id="cap_parent",
        sequence_index=2,
        evidence_refs=[{"source_type": "hook", "source_id": "event-1"}],
        trust_level="high",
        source_authority="explicit_user_command",
        sensitivity="low",
        data_classification="internal",
        occurred_at="2026-06-05T12:00:00+00:00",
        metadata={"client_minimization_version": "sdk-test"},
        trace_id="trace-1",
        idempotency_key="capture-idempotency-1",
        consolidate=True,
    )
    client.get_capture("cap_1")
    client.list_captures(
        space_slug="client-app",
        memory_scope_external_ref="default",
        status="accepted",
        consolidation_status="pending",
        limit=25,
    )
    client.consolidate_capture("cap_1", force=True)
    client.purge_capture("cap_1", reason="sdk privacy purge")
    client.capture_diagnostics(
        space_slug="client-app",
        memory_scope_external_ref="default",
        consolidation_status="dead",
        limit=10,
    )

    assert [method for method, _url, _body in seen] == [
        "POST",
        "GET",
        "GET",
        "POST",
        "DELETE",
        "GET",
    ]
    create_body = seen[0][2]
    assert create_body["space_slug"] == "client-app"
    assert create_body["memory_scope_external_ref"] == "default"
    assert create_body["thread_external_ref"] == "session-1"
    assert create_body["source_actor_external_ref"] == "user-1"
    assert create_body["agent_session_external_ref"] == "session-ext-1"
    assert create_body["turn_external_ref"] == "turn-1"
    assert create_body["parent_capture_id"] == "cap_parent"
    assert create_body["sequence_index"] == 2
    assert create_body["evidence_refs"] == [{"source_type": "hook", "source_id": "event-1"}]
    assert create_body["source_authority"] == "explicit_user_command"
    assert create_body["sensitivity"] == "low"
    assert create_body["data_classification"] == "internal"
    assert create_body["trace_id"] == "trace-1"
    assert create_body["idempotency_key"] == "capture-idempotency-1"
    assert create_body["consolidate"] is True
    assert seen[1][1] == "http://memory.test/v1/captures/cap_1"
    assert (
        seen[2][1]
        == "http://memory.test/v1/captures?space_slug=client-app&memory_scope_external_ref=default&status=accepted&consolidation_status=pending&limit=25"
    )
    assert seen[3] == (
        "POST",
        "http://memory.test/v1/captures/cap_1/consolidate",
        {"force": True},
    )
    assert seen[4] == (
        "DELETE",
        "http://memory.test/v1/captures/cap_1",
        {"reason": "sdk privacy purge"},
    )
    assert (
        seen[5][1]
        == "http://memory.test/v1/diagnostics/captures?space_slug=client-app&memory_scope_external_ref=default&consolidation_status=dead&limit=10"
    )


def test_sdk_suggestions_support_external_scope() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, str(request.url), body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.create_suggestion(
        space_slug="client-app",
        memory_scope_external_ref="default",
        candidate_text="Pending external scope suggestion.",
        kind="note",
        safe_reason="sdk_test",
        source_refs=[{"source_type": "manual", "source_id": "sdk-suggestion"}],
        operation="review",
        category="review",
        tags=["queue"],
        ttl_policy="review",
        review_payload={"target_resolution": {"status": "not_required"}},
    )
    client.list_suggestions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        status="pending",
        operation="review",
        category="review",
        tag="queue",
        limit=25,
    )

    assert seen[0][0] == "POST"
    assert seen[0][1] == "http://memory.test/v1/suggestions"
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["memory_scope_external_ref"] == "default"
    assert seen[0][2]["operation"] == "review"
    assert seen[0][2]["category"] == "review"
    assert seen[0][2]["tags"] == ["queue"]
    assert seen[0][2]["ttl_policy"] == "review"
    assert seen[0][2]["review_payload"] == {"target_resolution": {"status": "not_required"}}
    assert "space_id" not in seen[0][2]
    assert (
        seen[1][1]
        == "http://memory.test/v1/suggestions?space_slug=client-app&memory_scope_external_ref=default&operation=review&category=review&tag=queue&limit=25&status=pending"
    )


def test_sdk_context_search_and_documents_support_external_scope() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.ingest_document(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-docs",
        title="Architecture notes",
        text="Postgres is canonical truth.",
        source_external_id="doc-1",
        source_refs=[
            {
                "source_type": "asset_extraction",
                "source_id": "extract-doc-1",
                "page_number": 1,
                "time_start_ms": 1000,
                "time_end_ms": 2500,
                "bbox": [12, 20, 120, 40],
            }
        ],
    )
    client.build_context(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-docs",
        query="canonical truth",
        token_budget=512,
        max_facts=4,
        max_chunks=6,
        consistency_mode="canonical_only",
        max_conflicting_suggestions=2,
    )
    client.search(
        space_slug="client-app",
        memory_scope_external_refs=["default", "candidate"],
        query="infinity context",
        token_budget=1024,
        max_facts=8,
        max_chunks=10,
        consistency_mode="best_effort",
        max_conflicting_suggestions=3,
        include_stale=True,
    )

    assert [f"{method} {path}" for method, path, _body in seen] == [
        "POST /v1/documents",
        "POST /v1/context",
        "POST /v1/search",
    ]
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["thread_external_ref"] == "session-docs"
    assert seen[0][2]["source_refs"][0]["source_id"] == "extract-doc-1"
    assert seen[0][2]["source_refs"][0]["bbox"] == [12, 20, 120, 40]
    assert "space_id" not in seen[0][2]
    assert seen[1][2]["max_facts"] == 4
    assert seen[1][2]["max_chunks"] == 6
    assert seen[1][2]["consistency_mode"] == "canonical_only"
    assert seen[1][2]["max_conflicting_suggestions"] == 2
    assert seen[2][2]["memory_scope_external_refs"] == ["default", "candidate"]
    assert seen[2][2]["consistency_mode"] == "best_effort"
    assert seen[2][2]["max_conflicting_suggestions"] == 3
    assert seen[2][2]["include_stale"] is True
    assert "memory_scope_ids" not in seen[2][2]


def test_sdk_supports_assets_and_extraction_contract() -> None:
    seen: list[tuple[str, str, dict[str, str], bytes, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params),
                request.content,
                request.headers.get("content-type"),
            )
        )
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=b"downloaded-bytes")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.upload_asset(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-assets",
        filename="note.txt",
        content=b"asset bytes",
        content_type="text/plain",
        extract=True,
    )
    client.list_assets(space_slug="client-app", memory_scope_external_ref="default")
    client.delete_asset("asset_1")
    assert client.download_asset("asset_1") == b"downloaded-bytes"
    client.request_asset_extraction("asset_1", parser_profile="standard_local")
    client.list_asset_extractions("asset_1", status="succeeded", limit=5)
    client.list_scope_asset_extractions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-assets",
        limit=10,
    )
    client.get_asset_extraction("extract_1")
    client.retry_asset_extraction("extract_1")
    client.cancel_asset_extraction("extract_1")
    client.get_operations_console(
        space_slug="client-app",
        memory_scope_external_ref="default",
        limit=20,
    )
    client.get_memory_browser(
        space_slug="client-app",
        memory_scope_external_ref="default",
        limit=30,
        link_status="active",
        extraction_status="pending",
        suggestion_status="approved",
    )
    assert client.download_extraction_artifact("artifact_1") == b"downloaded-bytes"

    assert [f"{method} {path}" for method, path, _params, _body, _content_type in seen] == [
        "POST /v1/assets",
        "GET /v1/assets",
        "DELETE /v1/assets/asset_1",
        "GET /v1/assets/asset_1/download",
        "POST /v1/assets/asset_1/extractions",
        "GET /v1/assets/asset_1/extractions",
        "GET /v1/asset-extractions",
        "GET /v1/asset-extractions/extract_1",
        "POST /v1/asset-extractions/extract_1/retry",
        "POST /v1/asset-extractions/extract_1/cancel",
        "GET /v1/operations-console",
        "GET /v1/memory-browser",
        "GET /v1/extraction-artifacts/artifact_1/download",
    ]
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["memory_scope_external_ref"] == "default"
    assert seen[0][2]["thread_external_ref"] == "session-assets"
    assert seen[0][2]["filename"] == "note.txt"
    assert seen[0][2]["content_type"] == "text/plain"
    assert seen[0][2]["extract"] == "true"
    assert seen[0][3] == b"asset bytes"
    assert seen[0][4] == "text/plain"
    assert seen[5][2] == {"status": "succeeded", "limit": "5"}
    assert seen[6][2]["limit"] == "10"
    assert seen[10][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "limit": "20",
    }
    assert seen[11][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "limit": "30",
        "fact_status": "active",
        "episode_status": "active",
        "document_status": "active",
        "chunk_status": "active",
        "extraction_status": "pending",
        "thread_status": "active",
        "asset_status": "stored",
        "anchor_status": "active",
        "link_status": "active",
        "suggestion_status": "approved",
    }


def test_sdk_supports_context_link_suggestion_review_contract() -> None:
    seen: list[tuple[str, str, dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, dict(request.url.params), body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.suggest_context_links(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-assets",
        source_type="capture",
        source_id="cap_1",
        text="alex screenshot memory",
        persist=True,
    )
    client.list_context_link_suggestions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        source_type="capture",
        source_id="cap_1",
    )
    client.create_context_link(
        space_slug="client-app",
        memory_scope_external_ref="default",
        source_type="capture",
        source_id="cap_1",
        target_type="fact",
        target_id="fact_2",
        relation_type="supports",
        confidence="high",
        reason="manual reviewer link",
        metadata={"created_from": "memory_browser_manual"},
    )
    client.list_context_links(
        space_slug="client-app",
        memory_scope_external_ref="default",
        status="active",
        limit=25,
    )
    client.update_context_link(
        "ctxlink_1",
        target_type="fact",
        target_id="fact_3",
        relation_type="supports",
        confidence="medium",
        reason="manual reviewer corrected link",
        metadata={"updated_from": "sdk_contract"},
    )
    client.delete_context_link("ctxlink_1")
    client.review_context_link_suggestion(
        "ctxlinksug_1",
        action="approve",
        reason="user accepted",
        target_type="fact",
        target_id="fact_2",
        relation_type="supports",
        confidence="high",
        link_reason="corrected target",
    )
    client.approve_context_link_suggestion(
        "ctxlinksug_approve_alias",
        reason="alias accepted",
        target_type="fact",
        target_id="fact_5",
        relation_type="supports",
        confidence="high",
        link_reason="alias target override",
    )
    client.reject_context_link_suggestion(
        "ctxlinksug_reject_alias",
        reason="alias rejected",
    )
    client.review_context_link_suggestions_batch(
        [
            {
                "suggestion_id": "ctxlinksug_2",
                "action": "approve",
                "target_type": "fact",
                "target_id": "fact_4",
                "relation_type": "supports",
                "confidence": "medium",
                "link_reason": "batch corrected target",
            },
            {
                "suggestion_id": "ctxlinksug_3",
                "action": "reject",
                "reason": "not related",
            },
        ],
        continue_on_error=True,
        visible_filter={
            "space_slug": "client-app",
            "memory_scope_external_ref": "default",
            "source_type": "capture",
            "source_id": "cap_1",
            "status": "pending",
            "limit": 20,
        },
    )

    assert [f"{method} {path}" for method, path, _params, _body in seen] == [
        "POST /v1/link-suggestions",
        "GET /v1/context-link-suggestions",
        "POST /v1/context-links",
        "GET /v1/context-links",
        "PATCH /v1/context-links/ctxlink_1",
        "DELETE /v1/context-links/ctxlink_1",
        "POST /v1/context-link-suggestions/ctxlinksug_1/review",
        "POST /v1/context-link-suggestions/ctxlinksug_approve_alias/review",
        "POST /v1/context-link-suggestions/ctxlinksug_reject_alias/review",
        "POST /v1/context-link-suggestions/review-batch",
    ]
    assert seen[0][3] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "thread_external_ref": "session-assets",
        "text": "alex screenshot memory",
        "source_type": "capture",
        "source_id": "cap_1",
        "limit": 10,
        "persist": True,
    }
    assert seen[1][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "source_type": "capture",
        "source_id": "cap_1",
        "status": "pending",
        "limit": "50",
    }
    assert seen[2][3] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "source_type": "capture",
        "source_id": "cap_1",
        "target_type": "fact",
        "target_id": "fact_2",
        "relation_type": "supports",
        "confidence": "high",
        "reason": "manual reviewer link",
        "metadata": {"created_from": "memory_browser_manual"},
    }
    assert seen[3][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "status": "active",
        "limit": "25",
    }
    assert seen[4][3] == {
        "target_type": "fact",
        "target_id": "fact_3",
        "relation_type": "supports",
        "confidence": "medium",
        "reason": "manual reviewer corrected link",
        "metadata": {"updated_from": "sdk_contract"},
    }
    assert seen[5][3] == {}
    assert seen[6][3] == {
        "action": "approve",
        "reason": "user accepted",
        "target_type": "fact",
        "target_id": "fact_2",
        "relation_type": "supports",
        "confidence": "high",
        "link_reason": "corrected target",
    }
    assert seen[7][3] == {
        "action": "approve",
        "reason": "alias accepted",
        "target_type": "fact",
        "target_id": "fact_5",
        "relation_type": "supports",
        "confidence": "high",
        "link_reason": "alias target override",
    }
    assert seen[8][3] == {
        "action": "reject",
        "reason": "alias rejected",
    }
    assert seen[9][3] == {
        "items": [
            {
                "suggestion_id": "ctxlinksug_2",
                "action": "approve",
                "target_type": "fact",
                "target_id": "fact_4",
                "relation_type": "supports",
                "confidence": "medium",
                "link_reason": "batch corrected target",
            },
            {
                "suggestion_id": "ctxlinksug_3",
                "action": "reject",
                "reason": "not related",
            },
        ],
        "continue_on_error": True,
        "visible_filter": {
            "space_slug": "client-app",
            "memory_scope_external_ref": "default",
            "source_type": "capture",
            "source_id": "cap_1",
            "status": "pending",
            "limit": 20,
        },
    }


def test_sdk_preserves_context_link_review_audit_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/context-link-suggestions/ctxlinksug_1/review"
        return httpx.Response(
            200,
            json={
                "data": {
                    "suggestion": {
                        "id": "ctxlinksug_1",
                        "status": "approved",
                        "review_audit": {
                            "event_count": 1,
                            "truncated": False,
                            "events": [
                                {
                                    "event_type": "context_link_suggestion_reviewed",
                                    "action": "approve",
                                    "new_status": "approved",
                                    "reason": "confirmed",
                                }
                            ],
                        },
                    },
                    "link": {"id": "ctxlink_1"},
                    "duplicate_link": False,
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    result = client.review_context_link_suggestion(
        "ctxlinksug_1",
        action="approve",
        reason="confirmed",
    )

    audit = result["data"]["suggestion"]["review_audit"]
    assert audit["event_count"] == 1
    assert audit["events"][0]["action"] == "approve"


def test_sdk_normalizes_context_link_review_ids_and_actions() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.review_context_link_suggestion(
        " ctxlinksug_1 ",
        action=" approve ",
        reason="confirmed",
    )
    client.review_context_link_suggestions_batch(
        [
            {
                "suggestion_id": " ctxlinksug_2 ",
                "action": " reject ",
                "reason": "not related",
            }
        ]
    )

    assert seen == [
        (
            "POST",
            "/v1/context-link-suggestions/ctxlinksug_1/review",
            {"action": "approve", "reason": "confirmed"},
        ),
        (
            "POST",
            "/v1/context-link-suggestions/review-batch",
            {
                "items": [
                    {
                        "suggestion_id": "ctxlinksug_2",
                        "action": "reject",
                        "reason": "not related",
                    }
                ],
                "continue_on_error": False,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("suggestion_id", "action", "message"),
    [
        ("  ", "approve", "requires suggestion_id"),
        ("ctxlinksug_1", "  ", "requires action"),
    ],
)
def test_sdk_rejects_invalid_single_context_link_review(
    suggestion_id: str,
    action: str,
    message: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match=message):
        client.review_context_link_suggestion(suggestion_id, action=action)

    assert calls == 0


def test_sdk_rejects_oversized_context_link_batch_review() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    try:
        client.review_context_link_suggestions_batch(
            [{"suggestion_id": f"ctxlinksug_{index}", "action": "approve"} for index in range(51)]
        )
    except ValueError as exc:
        assert "at most 50" in str(exc)
    else:
        raise AssertionError("Expected oversized context link batch review to fail")

    assert calls == 0


def test_sdk_rejects_blank_context_link_batch_review_id() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    try:
        client.review_context_link_suggestions_batch([{"suggestion_id": "  ", "action": "approve"}])
    except ValueError as exc:
        assert "requires suggestion_id" in str(exc)
    else:
        raise AssertionError("Expected blank context link batch review id to fail")

    assert calls == 0


def test_sdk_rejects_duplicate_context_link_batch_review_ids() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    try:
        client.review_context_link_suggestions_batch(
            [
                {"suggestion_id": "ctxlinksug_duplicate", "action": "approve"},
                {"suggestion_id": " ctxlinksug_duplicate ", "action": "reject"},
            ]
        )
    except ValueError as exc:
        assert "unique suggestion_id" in str(exc)
    else:
        raise AssertionError("Expected duplicate context link batch review to fail")

    assert calls == 0


def test_sdk_rejects_blank_context_link_batch_review_action() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="requires action"):
        client.review_context_link_suggestions_batch(
            [{"suggestion_id": "ctxlinksug_1", "action": "  "}]
        )

    assert calls == 0


def test_sdk_supports_context_link_statuses_filters() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"data": []})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.list_context_links(
        space_slug="client-app",
        memory_scope_external_ref="default",
        statuses="active,deleted",
        target_type="fact",
        target_id="fact_2",
        relation_type="supports",
        limit=20,
    )
    client.list_context_link_suggestions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        statuses="approved,rejected",
        target_type="document",
        target_id="doc_1",
        relation_type="references",
        limit=30,
    )

    assert seen == [
        (
            "GET",
            "/v1/context-links",
            {
                "space_slug": "client-app",
                "memory_scope_external_ref": "default",
                "statuses": "active,deleted",
                "target_type": "fact",
                "target_id": "fact_2",
                "relation_type": "supports",
                "limit": "20",
            },
        ),
        (
            "GET",
            "/v1/context-link-suggestions",
            {
                "space_slug": "client-app",
                "memory_scope_external_ref": "default",
                "statuses": "approved,rejected",
                "target_type": "document",
                "target_id": "doc_1",
                "relation_type": "references",
                "limit": "30",
            },
        ),
    ]


def test_sdk_supports_anchor_lifecycle_contract() -> None:
    seen: list[tuple[str, str, dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, dict(request.url.params), body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.create_anchor(
        space_slug="client-app",
        memory_scope_external_ref="default",
        kind="person",
        label="Alex",
        aliases=["Alexander"],
        description="Canonical person anchor.",
    )
    client.list_anchors(
        space_slug="client-app",
        memory_scope_external_ref="default",
        kind="person",
        status="active",
        limit=25,
    )
    client.update_anchor(
        "anchor_target",
        label="Alexander",
        aliases=["Alex"],
        description="Edited person anchor.",
    )
    client.delete_anchor("anchor_obsolete", reason="obsolete anchor")
    client.backfill_anchors(
        space_slug="client-app",
        memory_scope_external_ref="default",
        limit_per_source=20,
    )
    client.list_anchor_merge_suggestions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        kind="person",
        limit=10,
    )
    client.merge_anchor("anchor_source", target_anchor_id="anchor_target", reason="same person")
    client.split_anchor("anchor_target", alias="Alex", new_label="Alexander", reason="split alias")

    assert [f"{method} {path}" for method, path, _params, _body in seen] == [
        "POST /v1/anchors",
        "GET /v1/anchors",
        "PATCH /v1/anchors/anchor_target",
        "DELETE /v1/anchors/anchor_obsolete",
        "POST /v1/anchors/backfill",
        "GET /v1/anchors/merge-suggestions",
        "POST /v1/anchors/anchor_source/merge",
        "POST /v1/anchors/anchor_target/split",
    ]
    assert seen[0][3] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "kind": "person",
        "label": "Alex",
        "aliases": ["Alexander"],
        "description": "Canonical person anchor.",
        "metadata": {},
    }
    for optional_key in ("confidence", "evidence_refs", "observed_at", "valid_from", "valid_to"):
        assert optional_key not in seen[0][3]
    assert seen[1][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "kind": "person",
        "status": "active",
        "limit": "25",
    }
    assert seen[2][3] == {
        "label": "Alexander",
        "aliases": ["Alex"],
        "description": "Edited person anchor.",
        "metadata": {},
    }
    for optional_key in ("confidence", "evidence_refs", "observed_at", "valid_from", "valid_to"):
        assert optional_key not in seen[2][3]
    assert seen[3][3] == {"reason": "obsolete anchor"}
    assert seen[4][3] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "limit_per_source": 20,
    }
    assert seen[5][2] == {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "kind": "person",
        "limit": "10",
    }
    assert seen[6][3] == {
        "target_anchor_id": "anchor_target",
        "reason": "same person",
    }
    assert seen[7][3] == {
        "alias": "Alex",
        "new_label": "Alexander",
        "reason": "split alias",
    }


def test_sdk_sends_anchor_evidence_and_temporal_contract_fields() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    evidence_refs = [
        {"source_type": "capture", "source_id": "cap_1"},
        {"source_type": "asset", "source_id": "asset_1"},
    ]

    client.create_anchor(
        space_slug="client-app",
        memory_scope_external_ref="default",
        kind="project",
        label="Atlas",
        confidence="high",
        evidence_refs=evidence_refs,
        observed_at="2026-06-05T12:00:00+00:00",
        valid_from="2026-06-01T00:00:00+00:00",
        valid_to="2026-07-01T00:00:00+00:00",
        metadata={"source": "sdk-contract"},
    )
    client.update_anchor(
        "anchor_project",
        confidence="medium",
        evidence_refs=[],
        observed_at="2026-06-06T12:00:00+00:00",
        valid_from="2026-06-02T00:00:00+00:00",
        valid_to="2026-08-01T00:00:00+00:00",
        metadata={"source": "sdk-contract-update"},
    )

    assert seen == [
        (
            "POST",
            "/v1/anchors",
            {
                "space_slug": "client-app",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": [],
                "confidence": "high",
                "evidence_refs": evidence_refs,
                "observed_at": "2026-06-05T12:00:00+00:00",
                "valid_from": "2026-06-01T00:00:00+00:00",
                "valid_to": "2026-07-01T00:00:00+00:00",
                "metadata": {"source": "sdk-contract"},
            },
        ),
        (
            "PATCH",
            "/v1/anchors/anchor_project",
            {
                "aliases": [],
                "confidence": "medium",
                "evidence_refs": [],
                "observed_at": "2026-06-06T12:00:00+00:00",
                "valid_from": "2026-06-02T00:00:00+00:00",
                "valid_to": "2026-08-01T00:00:00+00:00",
                "metadata": {"source": "sdk-contract-update"},
            },
        ),
    ]


def test_sdk_supports_typed_scope_dtos() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.remember_fact(
        scope=MemoryScope(
            space_slug="client-app",
            memory_scope_external_ref="default",
            thread_external_ref="session-1",
        ),
        text="Typed scope fact.",
        kind="note",
        source_refs=[{"source_type": "manual", "source_id": "sdk-scope"}],
    )
    client.search(
        read_scope=ReadScope(
            space_slug="client-app",
            memory_scope_external_refs=("default", "candidate"),
        ),
        query="typed read scope",
    )

    assert seen[0] == (
        "/v1/facts",
        {
            "space_slug": "client-app",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "session-1",
            "text": "Typed scope fact.",
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": "sdk-scope"}],
            "classification": "internal",
        },
    )
    assert seen[1][0] == "/v1/search"
    assert seen[1][1]["memory_scope_external_refs"] == ["default", "candidate"]
    assert "memory_scope_external_ref" not in seen[1][1]


def test_sdk_read_scope_rejects_ambiguous_thread_multi_memory_scope() -> None:
    with pytest.raises(ValueError, match="single memory_scope"):
        ReadScope(
            space_slug="client-app",
            memory_scope_external_refs=("default", "candidate"),
            thread_external_ref="session-1",
        ).to_payload()


def test_sdk_remember_fact_sends_classification() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"data": {"id": "fact_1"}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.remember_fact(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        text="Restricted fact",
        kind="note",
        source_refs=[{"source_type": "manual", "source_id": "sdk-test"}],
        classification="restricted",
    )

    assert seen["body"]["classification"] == "restricted"


def test_sdk_supports_review_suggestions_batch() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"applied": 2, "failed": 0}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.review_suggestions_batch(
        [
            {"suggestion_id": "sug_1", "action": "approve", "reason": "reviewed"},
            {"suggestion_id": "sug_2", "action": "reject"},
        ],
        continue_on_error=True,
    )

    assert seen == {
        "path": "/v1/suggestions/review-batch",
        "body": {
            "items": [
                {"suggestion_id": "sug_1", "action": "approve", "reason": "reviewed"},
                {"suggestion_id": "sug_2", "action": "reject"},
            ],
            "continue_on_error": True,
        },
    }


def test_sdk_preserves_suggestion_review_audit_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/suggestions/sug_1/approve"
        return httpx.Response(
            200,
            json={
                "data": {
                    "suggestion": {
                        "id": "sug_1",
                        "status": "approved",
                        "review_audit": {
                            "events": [
                                {
                                    "event_type": "memory_suggestion_reviewed",
                                    "suggestion_id": "sug_1",
                                    "action": "approve",
                                    "new_status": "approved",
                                    "reason": "reviewed",
                                }
                            ],
                            "event_count": 1,
                            "truncated": False,
                        },
                    }
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    result = client.approve_suggestion("sug_1", reason="reviewed")
    audit = result["data"]["suggestion"]["review_audit"]

    assert audit["event_count"] == 1
    assert audit["events"][0]["event_type"] == "memory_suggestion_reviewed"
    assert audit["events"][0]["action"] == "approve"


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "at least one item"),
        (
            [{"suggestion_id": f"sug_{index}", "action": "approve"} for index in range(51)],
            "at most 50",
        ),
        ([{"suggestion_id": "   ", "action": "approve"}], "non-empty suggestion_id"),
        (
            [
                {"suggestion_id": "sug_duplicate", "action": "approve"},
                {"suggestion_id": " sug_duplicate ", "action": "reject"},
            ],
            "unique suggestion_id",
        ),
    ],
)
def test_sdk_rejects_invalid_review_suggestions_batch(
    items: list[dict[str, object]],
    message: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match=message):
        client.review_suggestions_batch(items)

    assert calls == 0


def test_sdk_supports_create_suggestions_batch() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"data": {"created": 2, "failed": 0}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.create_suggestions_batch(
        space_slug="client-app",
        memory_scope_external_ref="default",
        items=[
            {"candidate_text": "Batch SDK fact A.", "safe_reason": "review"},
            {"candidate_text": "Batch SDK fact B.", "safe_reason": "review"},
        ],
        continue_on_error=True,
    )

    assert seen == {
        "path": "/v1/suggestions/batch",
        "body": {
            "space_slug": "client-app",
            "memory_scope_external_ref": "default",
            "items": [
                {"candidate_text": "Batch SDK fact A.", "safe_reason": "review"},
                {"candidate_text": "Batch SDK fact B.", "safe_reason": "review"},
            ],
            "continue_on_error": True,
        },
    }


def test_sdk_supports_memory_scope_snapshot_export_import() -> None:
    seen: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, dict(request.url.params), body))
        if request.url.path.endswith("/preview"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "ok",
                        "preview": {
                            "diagnostics": {
                                "migration_defaults_applied": {
                                    "anchor_confidence": 1,
                                },
                                "migration_defaults_applied_count": 1,
                            },
                            "warnings": [
                                "migration_defaults_applied.anchor_confidence",
                            ],
                        },
                    }
                },
            )
        return httpx.Response(200, json={"data": {"status": "ok"}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    snapshot = {"schema_version": 1, "facts": [], "documents": [], "chunks": []}
    manifest = {
        "schema_version": "infinity_context.memory_scope_snapshot_manifest.v1",
        "snapshot_sha256": "abc",
    }

    client.export_memory_scope_snapshot(
        space_slug="agents",
        memory_scope_external_ref="default",
        redacted=True,
    )
    client.import_memory_scope_snapshot(
        space_slug="agents",
        memory_scope_external_ref="restore",
        snapshot=snapshot,
        manifest=manifest,
        dry_run=False,
        merge_strategy="create_new_memory_scope",
        confirmed=True,
        source_name="sdk-test",
    )
    preview = client.preview_memory_scope_snapshot_import(
        space_slug="agents",
        memory_scope_external_ref="restore",
        snapshot=snapshot,
        manifest=manifest,
        merge_strategy="skip_existing",
    )

    assert seen[0] == (
        "/v1/export/memory_scope-snapshot",
        {
            "space_slug": "agents",
            "memory_scope_external_ref": "default",
            "redacted": "true",
        },
        {},
    )
    assert seen[1] == (
        "/v1/export/memory_scope-snapshot/import",
        {},
        {
            "space_slug": "agents",
            "memory_scope_external_ref": "restore",
            "snapshot": snapshot,
            "manifest": manifest,
            "dry_run": False,
            "merge_strategy": "create_new_memory_scope",
            "confirmed": True,
            "source_name": "sdk-test",
        },
    )
    assert seen[2] == (
        "/v1/export/memory_scope-snapshot/preview",
        {},
        {
            "space_slug": "agents",
            "memory_scope_external_ref": "restore",
            "snapshot": snapshot,
            "manifest": manifest,
            "merge_strategy": "skip_existing",
        },
    )
    assert preview["data"]["preview"]["diagnostics"] == {
        "migration_defaults_applied": {"anchor_confidence": 1},
        "migration_defaults_applied_count": 1,
    }


def test_sdk_sends_search_taxonomy_filters() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"items": []}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.search(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="Graphiti memory",
        category="architecture",
        tags_any=["graphiti"],
        tags_all=["memory"],
        tags_none=["redis"],
    )

    assert seen["path"] == "/v1/search"
    assert seen["body"]["category"] == "architecture"
    assert seen["body"]["tags_any"] == ["graphiti"]
    assert seen["body"]["tags_all"] == ["memory"]
    assert seen["body"]["tags_none"] == ["redis"]


def test_sdk_raises_typed_server_error_envelope() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "memory.conflict",
                    "message": "Version conflict",
                    "retryable": False,
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        client.forget_fact("fact_1")

    assert raised.value.status_code == 409
    assert raised.value.code == "memory.conflict"
    assert raised.value.retryable is False


def test_sdk_redacts_sensitive_server_error_message() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "error": {
                    "code": "memory.provider_error",
                    "message": f"upstream leaked Bearer {raw_secret}",
                    "retryable": True,
                }
            },
        )

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        client.forget_fact("fact_1")

    assert raw_secret not in str(raised.value)
    assert "[redacted]" in str(raised.value)
    assert raised.value.code == "memory.provider_error"


def test_sdk_redacts_sensitive_non_json_error_body() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=f"gateway leaked {raw_secret}")

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        client.forget_fact("fact_1")

    assert raw_secret not in str(raised.value)
    assert "[redacted]" in str(raised.value)
    assert raised.value.code == "memory.http_error"


def test_sdk_maps_transport_error_to_retryable_memory_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        client.build_context(
            space_id="space_client_app",
            memory_scope_ids=["memory_scope_default"],
            query="safe fallback",
        )

    assert raised.value.status_code == 0
    assert raised.value.code == "memory.network_error"
    assert raised.value.retryable is True
