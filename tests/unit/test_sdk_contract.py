import json

import httpx
import pytest
from memo_stack_sdk import MemoryScope, MemoStackClient, MemoStackError, ReadScope


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
        profile_id="profile_default",
        status="pending",
    )

    assert response == {"data": {"ok": True}}
    assert seen["authorization"] == "Bearer test-token"
    assert (
        seen["url"]
        == "http://memory.test/v1/suggestions?space_id=space_client_app&profile_id=profile_default&limit=100&status=pending"
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
        profile_id="profile_default",
        limit=10,
        cursor="fact_cursor",
    )
    client.get_fact("fact_1")
    client.list_fact_versions("fact_1")
    client.list_document_chunks("doc_1", limit=5, cursor="chunk_cursor")
    client.process_document("doc_1")
    client.diagnostics_outbox(limit=10, cursor="outbox_cursor")
    client.diagnostics_profile("profile_1")

    assert seen == [
        "GET http://memory.test/v1/facts?space_id=space_client_app&profile_id=profile_default&limit=10&status=active&cursor=fact_cursor",
        "GET http://memory.test/v1/facts/fact_1",
        "GET http://memory.test/v1/facts/fact_1/versions",
        "GET http://memory.test/v1/documents/doc_1/chunks?limit=5&cursor=chunk_cursor",
        "POST http://memory.test/v1/documents/doc_1/process",
        "GET http://memory.test/v1/diagnostics/outbox?limit=10&cursor=outbox_cursor",
        "GET http://memory.test/v1/diagnostics/profile/profile_1",
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
        profile_id="profile_default",
        text="Use taxonomy for canonical facts.",
        kind="architecture_decision",
        source_refs=[{"source_type": "manual", "source_id": "taxonomy"}],
        category="architecture",
        tags=["memory", "graph"],
        ttl_policy="durable",
    )
    client.list_facts(
        space_id="space_client_app",
        profile_id="profile_default",
        category="architecture",
        tag="memory",
    )

    assert seen[0] == (
        "POST",
        "http://memory.test/v1/facts",
        {
            "space_id": "space_client_app",
            "profile_id": "profile_default",
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
        "http://memory.test/v1/facts?space_id=space_client_app&profile_id=profile_default&category=architecture&tag=memory&limit=100&status=active",
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
    }


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
        profile_external_refs=["engineering", "product"],
        max_facts=50,
        max_suggestions=25,
    )

    assert response == {"data": {"insights_id": "ins_1"}}
    assert seen == {
        "method": "POST",
        "url": "http://memory.test/v1/insights",
        "body": {
            "space_slug": "atlas",
            "profile_external_refs": ["engineering", "product"],
            "max_facts": 50,
            "max_documents": 100,
            "max_suggestions": 25,
            "max_captures": 100,
        },
    }


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
        profile_ids=["profile_default"],
        query="additive fields",
    )

    assert response["data"]["rendered_text"] == "Known memory evidence."
    assert response["data"]["new_optional_server_field"] == {"safe": True}


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
            profile_external_refs=("engineering", "product"),
        ),
        include_superseded=True,
        include_related=False,
    )

    assert response == {"data": {"digest_id": "dig_1"}}
    assert seen["method"] == "POST"
    assert seen["url"] == "http://memory.test/v1/digest"
    assert seen["body"] == {
        "space_slug": "default",
        "profile_external_refs": ["engineering", "product"],
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
        profile_external_ref="default",
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
        profile_external_ref="default",
        thread_external_ref="session-1",
    )
    client.delete_thread_memory(
        space_slug="client-app",
        profile_external_ref="default",
        thread_external_ref="session-1",
    )

    assert [f"{method} {path}" for method, path, _body in seen] == [
        "POST /v1/episodes",
        "POST /v1/thread-memory/status",
        "DELETE /v1/thread-memory",
    ]
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["profile_external_ref"] == "default"
    assert seen[0][2]["thread_external_ref"] == "session-1"
    assert seen[0][2]["idempotency_key"] == "event-1"
    assert "space_id" not in seen[0][2]
    assert seen[2][2] == {
        "space_slug": "client-app",
        "profile_external_ref": "default",
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
        profile_external_ref="default",
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
        profile_external_ref="default",
        status="accepted",
        consolidation_status="pending",
        limit=25,
    )
    client.consolidate_capture("cap_1", force=True)
    client.purge_capture("cap_1", reason="sdk privacy purge")
    client.capture_diagnostics(
        space_slug="client-app",
        profile_external_ref="default",
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
    assert create_body["profile_external_ref"] == "default"
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
        == "http://memory.test/v1/captures?space_slug=client-app&profile_external_ref=default&status=accepted&consolidation_status=pending&limit=25"
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
        == "http://memory.test/v1/diagnostics/captures?space_slug=client-app&profile_external_ref=default&consolidation_status=dead&limit=10"
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
        profile_external_ref="default",
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
        profile_external_ref="default",
        status="pending",
        operation="review",
        category="review",
        tag="queue",
        limit=25,
    )

    assert seen[0][0] == "POST"
    assert seen[0][1] == "http://memory.test/v1/suggestions"
    assert seen[0][2]["space_slug"] == "client-app"
    assert seen[0][2]["profile_external_ref"] == "default"
    assert seen[0][2]["operation"] == "review"
    assert seen[0][2]["category"] == "review"
    assert seen[0][2]["tags"] == ["queue"]
    assert seen[0][2]["ttl_policy"] == "review"
    assert seen[0][2]["review_payload"] == {"target_resolution": {"status": "not_required"}}
    assert "space_id" not in seen[0][2]
    assert (
        seen[1][1]
        == "http://memory.test/v1/suggestions?space_slug=client-app&profile_external_ref=default&operation=review&category=review&tag=queue&limit=25&status=pending"
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
        profile_external_ref="default",
        thread_external_ref="session-docs",
        title="Architecture notes",
        text="Postgres is canonical truth.",
        source_external_id="doc-1",
    )
    client.build_context(
        space_slug="client-app",
        profile_external_ref="default",
        thread_external_ref="session-docs",
        query="canonical truth",
        token_budget=512,
        max_facts=4,
        max_chunks=6,
    )
    client.search(
        space_slug="client-app",
        profile_external_refs=["default", "candidate"],
        query="memo stack",
        token_budget=1024,
        max_facts=8,
        max_chunks=10,
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
    assert seen[2][2]["profile_external_refs"] == ["default", "candidate"]
    assert "profile_ids" not in seen[2][2]


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
            profile_external_ref="default",
            thread_external_ref="session-1",
        ),
        text="Typed scope fact.",
        kind="note",
        source_refs=[{"source_type": "manual", "source_id": "sdk-scope"}],
    )
    client.search(
        read_scope=ReadScope(
            space_slug="client-app",
            profile_external_refs=("default", "candidate"),
        ),
        query="typed read scope",
    )

    assert seen[0] == (
        "/v1/facts",
        {
            "space_slug": "client-app",
            "profile_external_ref": "default",
            "thread_external_ref": "session-1",
            "text": "Typed scope fact.",
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": "sdk-scope"}],
            "classification": "internal",
        },
    )
    assert seen[1][0] == "/v1/search"
    assert seen[1][1]["profile_external_refs"] == ["default", "candidate"]
    assert "profile_external_ref" not in seen[1][1]


def test_sdk_read_scope_rejects_ambiguous_thread_multi_profile() -> None:
    with pytest.raises(ValueError, match="single profile"):
        ReadScope(
            space_slug="client-app",
            profile_external_refs=("default", "candidate"),
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
        profile_id="profile_default",
        text="Restricted fact",
        kind="note",
        source_refs=[{"source_type": "manual", "source_id": "sdk-test"}],
        classification="restricted",
    )

    assert seen["body"]["classification"] == "restricted"


def test_sdk_supports_profile_snapshot_export_import() -> None:
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
        "schema_version": "memo_stack.profile_snapshot_manifest.v1",
        "snapshot_sha256": "abc",
    }

    client.export_profile_snapshot(
        space_slug="agents",
        profile_external_ref="default",
        redacted=True,
    )
    client.import_profile_snapshot(
        space_slug="agents",
        profile_external_ref="restore",
        snapshot=snapshot,
        manifest=manifest,
        dry_run=False,
        merge_strategy="create_new_profile",
        confirmed=True,
        source_name="sdk-test",
    )

    assert seen[0] == (
        "/v1/export/profile-snapshot",
        {
            "space_slug": "agents",
            "profile_external_ref": "default",
            "redacted": "true",
        },
        {},
    )
    assert seen[1] == (
        "/v1/export/profile-snapshot/import",
        {},
        {
            "space_slug": "agents",
            "profile_external_ref": "restore",
            "snapshot": snapshot,
            "manifest": manifest,
            "dry_run": False,
            "merge_strategy": "create_new_profile",
            "confirmed": True,
            "source_name": "sdk-test",
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
        profile_ids=["profile_default"],
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
            profile_ids=["profile_default"],
            query="safe fallback",
        )

    assert raised.value.status_code == 0
    assert raised.value.code == "memory.network_error"
    assert raised.value.retryable is True
