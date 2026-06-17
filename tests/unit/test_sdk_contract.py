import json

import httpx
import pytest
from memo_stack_sdk import ContextBundle, MemoryScope, MemoStackClient, MemoStackError, ReadScope


def test_sdk_sends_auth_and_params() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": {"ok": True}})

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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
                            "external_provider_egress": True,
                            "requires_explicit_external_ai": True,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                        },
                        {
                            "name": "media_local_asr",
                            "enabled": False,
                            "status": "unavailable",
                            "reason": "provider_package_missing",
                            "providers": ["transcription_local"],
                            "external_provider_egress": False,
                            "requires_explicit_external_ai": False,
                            "fallback_profiles": ["standard_local"],
                            "memory_promotion": "review_required",
                            "source_text_policy": "untrusted_evidence",
                            "artifact_payloads_bounded": True,
                        },
                    ],
                    "providers": {
                        "transcription_api": {"status": "ok", "configured": True},
                    },
                    "policy": {"schema_version": 2, "external_ai_allowed": True},
                    "limits": {"max_media_seconds": 600},
                }
            },
        )

    client = MemoStackClient(
        base_url="http://memory.test",
        transport=httpx.MockTransport(handler),
    )

    diagnostics = client.extraction_capability_diagnostics()
    assert diagnostics.enabled is True
    assert diagnostics.default_profile == "media_api"
    assert diagnostics.policy["schema_version"] == 2
    assert diagnostics.limits["max_media_seconds"] == 600
    assert diagnostics.provider_status("transcription_api") == "ok"
    media_api = diagnostics.profile("media_api")
    assert media_api is not None
    assert media_api.status == "ok"
    assert media_api.providers == ("transcription_api",)
    assert media_api.external_provider_egress is True
    assert media_api.memory_promotion == "review_required"
    local_asr = diagnostics.profile("media_local_asr")
    assert local_asr is not None
    assert local_asr.reason == "provider_package_missing"
    assert diagnostics.profile("missing") is None


def test_sdk_sends_memory_insights_scope_and_limits() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"insights_id": "ins_1"}})

    client = MemoStackClient(
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
        return httpx.Response(200, json={"data": {"schema_version": "memo_stack.graph_export.v1"}})

    client = MemoStackClient(
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

    assert response == {"data": {"schema_version": "memo_stack.graph_export.v1"}}
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

    client = MemoStackClient(
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
                        "retrieval_sources_used": [
                            f"source_{index}" for index in range(12)
                        ],
                        "hybrid_items_used": 2,
                        "temporal_replacements_applied": 1,
                        "temporal_relations_skipped_by_validity": 3,
                        "items_considered": 14,
                        "items_used": 7,
                        "dropped_by_instruction_flag": 1,
                        "dropped_by_budget": 2,
                        "dropped_by_source_cap": 3,
                        "dropped_by_char_cap": 4,
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
                                }
                                for index in range(25)
                            ],
                            "diagnostics": {
                                "retrieval_source": "vector_chunks",
                                "retrieval_sources": [
                                    "vector_chunks",
                                    "keyword_chunks",
                                ],
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
                        }
                    ],
                },
            },
        )

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="typed context",
        consistency_mode="best_effort",
    )

    assert isinstance(bundle, ContextBundle)
    assert seen["url"] == "http://memory.test/v1/context"
    assert seen["body"]["consistency_mode"] == "best_effort"
    assert bundle.bundle_id == "ctx_1"
    assert bundle.meta["request_id"] == "req_1"
    assert bundle.diagnostics.context_assembly_version == "context-v2-hybrid-explainable"
    assert bundle.diagnostics.retrieval_sources_used == tuple(
        f"source_{index}" for index in range(8)
    )
    assert bundle.diagnostics.hybrid_items_used == 2
    assert bundle.diagnostics.temporal_replacements_applied == 1
    assert bundle.diagnostics.temporal_relations_skipped_by_validity == 3
    assert bundle.diagnostics.items_considered == 14
    assert bundle.diagnostics.items_used == 7
    assert bundle.diagnostics.dropped_by_instruction_flag == 1
    assert bundle.diagnostics.dropped_by_budget == 2
    assert bundle.diagnostics.dropped_by_source_cap == 3
    assert bundle.diagnostics.dropped_by_char_cap == 4
    assert "api_key" not in bundle.diagnostics.raw

    item = bundle.items[0]
    assert item.memory_scope_id == "memory_scope_default"
    assert len(item.source_refs) == 20
    assert item.source_refs[0].source_id == "doc_0"
    assert item.diagnostics.retrieval_source == "vector_chunks"
    assert item.diagnostics.retrieval_sources == ("vector_chunks", "keyword_chunks")
    assert item.diagnostics.ranking_reason == "hybrid match via vector_chunks, keyword_chunks"
    assert item.diagnostics.score_signals["base_score"] == 0.91
    assert item.diagnostics.score_signals["provider_note"] == "[redacted]"
    assert "nested" not in item.diagnostics.score_signals
    assert "token" not in item.diagnostics.provenance
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

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    bundle = client.build_typed_context(
        space_id="space_client_app",
        memory_scope_ids=["memory_scope_default"],
        query="legacy diagnostics",
    )

    assert bundle.diagnostics.hybrid_items_used == 0
    assert bundle.diagnostics.temporal_replacements_applied == 0
    assert bundle.diagnostics.temporal_relations_skipped_by_validity == 0
    assert bundle.diagnostics.items_considered == 0
    assert bundle.diagnostics.items_used == 0
    assert bundle.diagnostics.dropped_by_instruction_flag == 0
    assert bundle.diagnostics.dropped_by_budget == 0
    assert bundle.diagnostics.dropped_by_source_cap == 0
    assert bundle.diagnostics.dropped_by_char_cap == 0


def test_sdk_build_digest_posts_stable_contract() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"data": {"digest_id": "dig_1"}})

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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
        query="memo stack",
        token_budget=1024,
        max_facts=8,
        max_chunks=10,
        consistency_mode="best_effort",
        max_conflicting_suggestions=3,
    )

    assert [f"{method} {path}" for method, path, _body in seen] == [
        "POST /v1/documents",
        "POST /v1/context",
        "POST /v1/search",
    ]
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["thread_external_ref"] == "session-docs"
    assert "space_id" not in seen[0][2]
    assert seen[1][2]["max_facts"] == 4
    assert seen[1][2]["max_chunks"] == 6
    assert seen[1][2]["consistency_mode"] == "canonical_only"
    assert seen[1][2]["max_conflicting_suggestions"] == 2
    assert seen[2][2]["memory_scope_external_refs"] == ["default", "candidate"]
    assert seen[2][2]["consistency_mode"] == "best_effort"
    assert seen[2][2]["max_conflicting_suggestions"] == 3
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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


def test_sdk_rejects_oversized_context_link_batch_review() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = MemoStackClient(
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


def test_sdk_rejects_duplicate_context_link_batch_review_ids() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"ok": True}})

    client = MemoStackClient(
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


def test_sdk_supports_context_link_statuses_filters() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"data": []})

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    client.list_context_links(
        space_slug="client-app",
        memory_scope_external_ref="default",
        statuses="active,deleted",
        limit=20,
    )
    client.list_context_link_suggestions(
        space_slug="client-app",
        memory_scope_external_ref="default",
        statuses="approved,rejected",
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

    client = MemoStackClient(
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


def test_sdk_supports_typed_scope_dtos() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, body))
        return httpx.Response(200, json={"data": {"ok": True}})

    client = MemoStackClient(
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

    client = MemoStackClient(
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

    client = MemoStackClient(
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


def test_sdk_supports_create_suggestions_batch() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"data": {"created": 2, "failed": 0}})

    client = MemoStackClient(
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
        return httpx.Response(200, json={"data": {"status": "ok"}})

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    snapshot = {"schema_version": 1, "facts": [], "documents": [], "chunks": []}
    manifest = {
        "schema_version": "memo_stack.memory_scope_snapshot_manifest.v1",
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
    client.preview_memory_scope_snapshot_import(
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


def test_sdk_sends_search_taxonomy_filters() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"items": []}})

    client = MemoStackClient(
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

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MemoStackError) as raised:
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

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MemoStackError) as raised:
        client.forget_fact("fact_1")

    assert raw_secret not in str(raised.value)
    assert "[redacted]" in str(raised.value)
    assert raised.value.code == "memory.provider_error"


def test_sdk_redacts_sensitive_non_json_error_body() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=f"gateway leaked {raw_secret}")

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MemoStackError) as raised:
        client.forget_fact("fact_1")

    assert raw_secret not in str(raised.value)
    assert "[redacted]" in str(raised.value)
    assert raised.value.code == "memory.http_error"


def test_sdk_maps_transport_error_to_retryable_memory_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = MemoStackClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MemoStackError) as raised:
        client.build_context(
            space_id="space_client_app",
            memory_scope_ids=["memory_scope_default"],
            query="safe fallback",
        )

    assert raised.value.status_code == 0
    assert raised.value.code == "memory.network_error"
    assert raised.value.retryable is True
