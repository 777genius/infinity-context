from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import infinity_context_core.features.memory_facts.public as memory_facts
import pytest
from infinity_context_contracts.features.memory_facts import (
    MemoryFactSourceRefDto,
    RememberFactRequestDto,
)
from infinity_context_core import application as legacy_application
from infinity_context_core.domain import entities as legacy_entities
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_server.features.memory_facts import public as server_public

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "memory_facts"
)
API_FACTS_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "facts.py"
)
API_SUGGESTIONS_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "suggestions.py"
)


class RecordingRememberFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.RememberFactCommand] = []

    async def execute(
        self,
        command: memory_facts.RememberFactCommand,
    ) -> memory_facts.RememberFactResult:
        self.commands.append(command)
        return memory_facts.RememberFactResult(
            fact=_snapshot(
                fact_id="fact_1",
                scope=command.scope,
                text=command.text,
                source_refs=command.source_refs,
                category=command.category,
                tags=command.tags,
            ),
            outbox_message_ids=("outbox_1",),
        )


class RecordingUpdateFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.UpdateFactCommand] = []

    async def execute(
        self,
        command: memory_facts.UpdateFactCommand,
    ) -> memory_facts.UpdateFactResult:
        self.commands.append(command)
        return memory_facts.UpdateFactResult(
            fact=_snapshot(
                fact_id=command.identity.fact_id,
                scope=command.identity.scope,
                text=command.text,
                source_refs=command.source_refs,
                version=command.expected_version + 1,
                category=command.category,
                tags=command.tags,
            ),
            outbox_message_ids=("outbox_2",),
        )


class RecordingForgetFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.ForgetFactCommand] = []

    async def execute(
        self,
        command: memory_facts.ForgetFactCommand,
    ) -> memory_facts.ForgetFactResult:
        self.commands.append(command)
        return memory_facts.ForgetFactResult(
            fact=_snapshot(
                fact_id=command.identity.fact_id,
                scope=command.identity.scope,
                text="Postgres owns canonical lifecycle.",
                source_refs=(_source_ref(),),
                status="deleted",
                version=(command.expected_version or 1) + 1,
            ),
            tombstone_id="tombstone_1",
            outbox_message_ids=("outbox_3",),
        )


def test_memory_facts_server_feature_public_surface_composes_router() -> None:
    use_cases = _use_cases()
    feature = server_public.build_memory_facts_server_feature(
        use_cases,
        route_prefix="/memory-facts-feature",
    )

    assert feature.feature_id == "memory_facts"
    assert server_public.FEATURE_ID == "memory_facts"
    assert server_public.__all__ == tuple(
        (  # noqa: SIM905 - keep the exact ordered public surface compact.
            "CreateSuggestionBatchItemRequest CreateSuggestionRequest CreateSuggestionsBatchRequest "  # noqa: E501
            "ForgetFactHttpRequest LinkFactRequest MemoryFactSourceRefHttpRequest "
            "MemoryFactsServerComposition MemoryFactsServerFeature RememberFactRequest "
            "RememberFactHttpRequest ResolveDuplicateMergeRequest "
            "ResolveSuggestionConflictRequest ReviewSuggestionBatchItemRequest "
            "ReviewSuggestionRequest ReviewSuggestionsBatchRequest SourceRefRequest "
            "UpdateFactRequest UpdateFactHttpRequest FEATURE_ID "
            "build_memory_facts_server_composition build_memory_facts_server_feature "
            "create_memory_facts_router create_suggestion_command_from_v1_request "
            "create_suggestions_batch_to_response create_suggestions_batch_command_from_v1_request "
            "evidence_ref_request_to_public evidence_ref_to_response fact_relation_item_to_response "  # noqa: E501
            "fact_relation_to_response fact_result_to_response fact_to_response "
            "forget_fact_command_from_v1_path forget_fact_command_from_http "
            "forget_fact_request_to_command forget_fact_result_to_contract legacy_interview_kind "
            "legacy_interview_source legacy_interview_speaker legacy_interview_trust "
            "legacy_memory_fact_to_response link_fact_relation_command_from_v1_request "
            "memory_kind_from_v1_request memory_fact_result_to_response "
            "memory_fact_scope_from_contract memory_fact_scope_from_ids "
            "memory_fact_snapshot_to_contract memory_fact_snapshot_to_response "
            "normalize_suggestion_tag_filter related_fact_to_response "
            "remember_fact_command_from_v1_request remember_fact_command_from_contract "
            "remember_fact_request_to_command remember_fact_result_to_contract "
            "review_suggestions_batch_command_from_v1_request review_suggestions_batch_to_response "
            "source_ref_from_v1_request source_ref_request_to_public source_ref_to_contract "
            "source_ref_to_response suggestion_result_to_response suggestion_to_response "
            "unlink_fact_relation_command_from_v1_path update_fact_command_from_v1_request "
            "update_fact_command_from_http update_fact_request_to_command update_fact_result_to_contract "  # noqa: E501
            "validate_fact_status_filter validate_fact_relation_status_filter "
            "validate_suggestion_confidence_and_trust validate_suggestion_operation "
            "validate_suggestion_review_action validate_suggestion_status_filter"
        ).split()
    )
    assert {route.path for route in feature.create_router().routes} == {
        "/memory-facts-feature/facts",
        "/memory-facts-feature/facts/{fact_id}",
    }


def test_memory_facts_public_seam_maps_legacy_interview_ingest_fields() -> None:
    assert server_public.legacy_interview_source("  microphone  ") == "microphone"
    assert server_public.legacy_interview_source("  ") == "unknown"

    assert server_public.legacy_interview_kind(None) is None
    assert server_public.legacy_interview_kind("") is None
    assert (
        server_public.legacy_interview_kind("constraint")
        == legacy_entities.MemoryChunkKind.CONSTRAINT
    )
    assert (
        server_public.legacy_interview_kind("unknown_kind")
        == legacy_entities.MemoryChunkKind.RAW_TRANSCRIPT_CHUNK
    )

    assert (
        server_public.legacy_interview_speaker("assistant", "microphone")
        == legacy_entities.SpeakerRole.ASSISTANT
    )
    assert (
        server_public.legacy_interview_speaker("unknown_speaker", "system_audio")
        == legacy_entities.SpeakerRole.INTERVIEWER
    )
    assert (
        server_public.legacy_interview_speaker(None, "signal")
        == legacy_entities.SpeakerRole.INTERVIEWER
    )
    assert (
        server_public.legacy_interview_speaker(None, "manual_prompt")
        == legacy_entities.SpeakerRole.USER
    )
    assert (
        server_public.legacy_interview_speaker(None, "ai_response")
        == legacy_entities.SpeakerRole.ASSISTANT
    )
    assert (
        server_public.legacy_interview_speaker(None, "unknown_screen_scraper")
        == legacy_entities.SpeakerRole.UNKNOWN
    )
    assert (
        server_public.legacy_interview_speaker(None, " microphone ")
        == legacy_entities.SpeakerRole.UNKNOWN
    )

    assert server_public.legacy_interview_trust("ai_response") == legacy_entities.TrustLevel.LOW
    assert server_public.legacy_interview_trust("focus_copy") == legacy_entities.TrustLevel.HIGH
    assert (
        server_public.legacy_interview_trust("browser_selection")
        == legacy_entities.TrustLevel.MEDIUM
    )
    assert (
        server_public.legacy_interview_trust("unknown_screen_scraper")
        == legacy_entities.TrustLevel.LOW
    )
    assert server_public.legacy_interview_trust(" microphone ") == legacy_entities.TrustLevel.LOW


def test_memory_facts_mapper_builds_feature_public_application_commands() -> None:
    remember_request = RememberFactRequestDto(
        text="  Postgres owns canonical lifecycle.  ",
        source_refs=(
            MemoryFactSourceRefDto(
                source_type="document",
                source_id="doc_1",
                chunk_id="chunk_1",
                char_start=0,
                char_end=37,
                quote_preview="Postgres owns canonical lifecycle.",
            ),
        ),
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        kind="note",
        category="architecture",
        tags=("postgres", " "),
    )

    remember_command = server_public.remember_fact_command_from_contract(
        remember_request,
        idempotency_key="remember_1",
    )

    assert isinstance(remember_command, memory_facts.RememberFactCommand)
    assert remember_command.scope == memory_facts.MemoryFactScope(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
    )
    assert remember_command.text == "  Postgres owns canonical lifecycle.  "
    assert remember_command.source_refs[0].source_id == "doc_1"
    assert remember_command.tags == ("postgres",)
    assert remember_command.idempotency_key == "remember_1"

    update_request = server_public.UpdateFactHttpRequest(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        expected_version=1,
        text="Postgres remains the canonical lifecycle store.",
        reason="clarify owner",
        source_refs=[server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())],
    )

    update_command = server_public.update_fact_command_from_http(
        "fact_1",
        update_request,
        idempotency_key="update_1",
    )

    assert isinstance(update_command, memory_facts.UpdateFactCommand)
    assert update_command.identity == memory_facts.MemoryFactIdentity(
        fact_id="fact_1",
        scope=remember_command.scope,
    )
    assert update_command.expected_version == 1
    assert update_command.reason == "clarify owner"
    assert update_command.idempotency_key == "update_1"

    forget_request = server_public.ForgetFactHttpRequest(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        expected_version=2,
        reason="obsolete",
    )

    forget_command = server_public.forget_fact_command_from_http(
        "fact_1",
        forget_request,
        idempotency_key="forget_1",
    )

    assert isinstance(forget_command, memory_facts.ForgetFactCommand)
    assert forget_command.identity == update_command.identity
    assert forget_command.expected_version == 2
    assert forget_command.reason == "obsolete"
    assert forget_command.idempotency_key == "forget_1"


def test_memory_facts_mapper_requires_resolved_scope_ids() -> None:
    request = RememberFactRequestDto(
        text="Postgres owns canonical lifecycle.",
        source_refs=(MemoryFactSourceRefDto(source_type="document", source_id="doc_1"),),
        space_slug="client-app",
        memory_scope_external_ref="default",
    )

    with pytest.raises(ValueError, match="space_id is required"):
        server_public.remember_fact_command_from_contract(request)


def test_memory_facts_mapper_builds_legacy_v1_write_commands() -> None:
    scope = SimpleNamespace(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
    )
    remember_request = server_public.RememberFactRequest(
        space_id="space_slug_is_resolved_before_mapping",
        memory_scope_id="scope_slug_is_resolved_before_mapping",
        thread_id=None,
        text="Postgres owns canonical lifecycle.",
        kind="architecture_decision",
        classification="internal",
        category="architecture",
        tags=["postgres"],
        ttl_policy="retain",
        source_refs=[server_public.SourceRefRequest(**_source_ref_json())],
    )

    remember_command = server_public.remember_fact_command_from_v1_request(
        remember_request,
        resolved_scope=scope,
        idempotency_key="remember_1",
    )

    assert isinstance(remember_command, legacy_application.RememberFactCommand)
    assert remember_command.space_id == "space_1"
    assert remember_command.memory_scope_id == "scope_1"
    assert remember_command.thread_id == "thread_1"
    assert remember_command.kind is legacy_entities.MemoryKind.ARCHITECTURE_DECISION
    assert isinstance(remember_command.source_refs[0], legacy_entities.SourceRef)
    assert remember_command.source_refs[0].source_id == "doc_1"
    assert remember_command.category == "architecture"
    assert remember_command.tags == ("postgres",)
    assert remember_command.ttl_policy == "retain"
    assert remember_command.idempotency_key == "remember_1"

    update_request = server_public.UpdateFactRequest(
        expected_version=1,
        text="Postgres remains the canonical lifecycle store.",
        reason="clarify owner",
        source_refs=[server_public.SourceRefRequest(**_source_ref_json())],
    )
    update_command = server_public.update_fact_command_from_v1_request(
        "fact_1",
        update_request,
    )

    assert isinstance(update_command, legacy_application.UpdateFactCommand)
    assert update_command.fact_id == "fact_1"
    assert update_command.expected_version == 1
    assert update_command.reason == "clarify owner"

    link_request = server_public.LinkFactRequest(
        target_fact_id="fact_2",
        relation_type="supports",
        reason="ADR support",
    )
    link_command = server_public.link_fact_relation_command_from_v1_request(
        "fact_1",
        link_request,
    )

    assert isinstance(link_command, legacy_application.LinkFactsCommand)
    assert link_command.source_fact_id == "fact_1"
    assert link_command.target_fact_id == "fact_2"
    assert link_command.relation_type == "supports"

    forget_command = server_public.forget_fact_command_from_v1_path("fact_1")
    unlink_command = server_public.unlink_fact_relation_command_from_v1_path("relation_1")

    assert isinstance(forget_command, legacy_application.ForgetFactCommand)
    assert forget_command.fact_id == "fact_1"
    assert isinstance(unlink_command, legacy_application.UnlinkFactRelationCommand)
    assert unlink_command.relation_id == "relation_1"

    with pytest.raises(MemoryValidationError, match="Unknown memory kind"):
        server_public.remember_fact_command_from_v1_request(
            server_public.RememberFactRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                text="Unknown kind should stay a validation error.",
                kind="unknown_kind",
                source_refs=[server_public.SourceRefRequest(**_source_ref_json())],
            ),
            resolved_scope=scope,
        )


def test_memory_facts_public_seam_maps_relation_responses() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5)
    valid_to = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    relation = SimpleNamespace(
        id="relation_1",
        space_id="space_1",
        memory_scope_id="scope_1",
        source_fact_id="fact_1",
        target_fact_id="fact_2",
        relation_type=SimpleNamespace(value="supports"),
        reason="relation checked with Bearer " + "sk-" + "proj-secretvalue1234567890",
        status=SimpleNamespace(value="active"),
        valid_from=None,
        valid_to=valid_to,
        created_at=created_at,
        updated_at=created_at,
    )
    related_fact = _snapshot(
        fact_id="fact_2",
        scope=memory_facts.MemoryFactScope(
            space_id="space_1",
            memory_scope_id="scope_1",
        ),
        text="Graphiti remains a derived index.",
        source_refs=(_source_ref(),),
    )

    relation_body = server_public.fact_relation_to_response(relation)
    item_body = server_public.fact_relation_item_to_response(
        SimpleNamespace(
            relation=relation,
            related_fact=related_fact,
            direction="outgoing",
        )
    )
    related_body = server_public.related_fact_to_response(
        SimpleNamespace(
            fact=related_fact,
            score=0.75,
            relation_reasons=("ADR support",),
        )
    )

    assert relation_body == {
        "id": "relation_1",
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "source_fact_id": "fact_1",
        "target_fact_id": "fact_2",
        "relation_type": "supports",
        "reason": "relation checked with [redacted]",
        "status": "active",
        "observed_at": "2026-01-02T03:04:05+00:00",
        "valid_from": None,
        "valid_to": "2026-02-01T00:00:00+00:00",
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:04:05+00:00",
    }
    assert item_body["relation"] == relation_body
    assert item_body["related_fact"]["id"] == "fact_2"
    assert item_body["direction"] == "outgoing"
    assert related_body["id"] == "fact_2"
    assert related_body["score"] == 0.75
    assert related_body["relation_reasons"] == ["ADR support"]


def test_memory_facts_public_seam_maps_suggestion_responses_and_batches() -> None:
    raw_secret = "sk-redacted1234"
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    suggestion = SimpleNamespace(
        id="sug_1",
        space_id="space_1",
        memory_scope_id="scope_1",
        candidate_text="Duplicate merge candidate.",
        kind=SimpleNamespace(value="note"),
        operation=SimpleNamespace(value="add"),
        status=SimpleNamespace(value="pending"),
        source_refs=(
            SimpleNamespace(
                source_type="manual",
                source_id="source_1",
                quote_preview=f"Bearer {raw_secret}",
            ),
        ),
        confidence=SimpleNamespace(value="medium"),
        trust_level=SimpleNamespace(value="medium"),
        safe_reason=f"reviewed with Bearer {raw_secret}",
        target_fact_id="fact_1",
        target_fact_version=1,
        category="architecture",
        tags=("duplicates",),
        ttl_policy=None,
        expires_at=None,
        expiry_reason=None,
        created_from_capture_id="capture_1",
        candidate_fingerprint="fingerprint_1",
        review_payload={
            "review_kind": "duplicate_fact_merge",
            "review_events": [
                {
                    "event_type": "memory_suggestion_reviewed",
                    "suggestion_id": "sug_1",
                    "action": "approve",
                    "new_status": "approved",
                    "reason": f"approved with Bearer {raw_secret}",
                    "authorization": f"Bearer {raw_secret}",
                }
            ],
        },
        review_reason=f"approved with Bearer {raw_secret}",
        created_at=now,
        updated_at=now,
        reviewed_at=None,
    )
    fact = _snapshot(
        fact_id="fact_1",
        scope=memory_facts.MemoryFactScope(
            space_id="space_1",
            memory_scope_id="scope_1",
        ),
        text="Duplicate merge candidate.",
        source_refs=(_source_ref(),),
    )

    body = server_public.suggestion_to_response(suggestion)
    result_body = server_public.suggestion_result_to_response(
        SimpleNamespace(suggestion=suggestion, fact=fact, indexing_status="pending")
    )
    review_batch = server_public.review_suggestions_batch_to_response(
        SimpleNamespace(
            applied=1,
            failed=1,
            stopped=False,
            results=(
                SimpleNamespace(
                    suggestion_id="sug_1",
                    action="approve",
                    status="applied",
                    result=SimpleNamespace(
                        suggestion=suggestion,
                        fact=fact,
                        indexing_status="pending",
                    ),
                ),
                SimpleNamespace(
                    suggestion_id="sug_2",
                    action="reject",
                    status="failed",
                    result=None,
                    error_code="memory.conflict",
                    error_message="already reviewed",
                ),
            ),
        )
    )
    create_batch = server_public.create_suggestions_batch_to_response(
        SimpleNamespace(
            created=1,
            existing=0,
            failed=0,
            stopped=False,
            results=(
                SimpleNamespace(
                    index=0,
                    status="created",
                    result=SimpleNamespace(suggestion=suggestion),
                ),
            ),
        )
    )

    assert body["review_kind"] == "duplicate_fact_merge"
    assert "resolve_duplicate" in body["available_review_actions"]
    assert body["review_payload"]["duplicate_merge_policy_version"] == (
        "duplicate-merge-review-v1"
    )
    assert body["review_resolution_options"][0]["id"] == "merge_source_refs"
    assert body["safe_reason"] == "[redacted]"
    assert body["review_reason"] == "[redacted]"
    assert body["review_audit"]["events"][0]["reason"] == "[redacted]"
    assert "authorization" not in body["review_audit"]["events"][0]
    assert raw_secret not in str(body)
    assert result_body["suggestion"]["id"] == "sug_1"
    assert result_body["fact"]["id"] == "fact_1"
    assert result_body["fact"]["indexing_status"] == "pending"
    assert review_batch["results"][0]["fact"]["id"] == "fact_1"
    assert review_batch["results"][1]["error_code"] == "memory.conflict"
    assert create_batch["results"][0]["suggestion"]["id"] == "sug_1"


def test_memory_facts_public_seam_maps_suggestion_requests_to_commands() -> None:
    source_ref = server_public.SourceRefRequest(**_source_ref_json())
    request = server_public.CreateSuggestionRequest(
        candidate_text="  Batch suggest routes through the feature seam.  ",
        kind="note", source_refs=[source_ref],
        confidence="high", trust_level="medium",
        safe_reason="human reviewed",
        operation="add", category="architecture",
        tags=["RAG", "cognee", "rag", " "],
        review_payload={"review_kind": "candidate_review"},
    )
    command = server_public.create_suggestion_command_from_v1_request(
        request,
        space_id="space_1",
        memory_scope_id="scope_1",
    )

    assert isinstance(command, legacy_application.CreateSuggestionCommand)
    assert command.space_id == "space_1"
    assert command.memory_scope_id == "scope_1"
    assert (command.confidence, command.trust_level) == ("high", "medium")
    assert command.tags == ("rag", "cognee")
    assert command.review_payload == {"review_kind": "candidate_review"}
    assert command.kind is legacy_entities.MemoryKind.NOTE
    assert isinstance(command.source_refs[0], legacy_entities.SourceRef)
    assert command.source_refs[0].source_id == "doc_1"

    batch_command = server_public.create_suggestions_batch_command_from_v1_request(
        server_public.CreateSuggestionsBatchRequest(
            items=[
                server_public.CreateSuggestionBatchItemRequest(
                    candidate_text="Batch suggestion one.", source_refs=[source_ref],
                    safe_reason="human reviewed", tags=["Queue"],
                )
            ],
            continue_on_error=True,
        ),
        space_id="space_1",
        memory_scope_id="scope_1",
    )

    assert isinstance(batch_command, legacy_application.CreateSuggestionsBatchCommand)
    assert batch_command.continue_on_error is True
    assert batch_command.items[0].tags == ("queue",)

    review_command = server_public.review_suggestions_batch_command_from_v1_request(
        server_public.ReviewSuggestionsBatchRequest(
            items=[
                server_public.ReviewSuggestionBatchItemRequest(
                    suggestion_id="sug_1", action="approve", reason="accurate", force=True,
                )
            ],
            continue_on_error=True,
        ),
    )

    assert isinstance(review_command, legacy_application.ReviewSuggestionsBatchCommand)
    assert review_command.continue_on_error is True
    review_item_command = review_command.items[0]
    assert (
        review_item_command.suggestion_id,
        review_item_command.action,
        review_item_command.reason,
        review_item_command.force,
    ) == ("sug_1", "approve", "accurate", True)
    assert isinstance(review_item_command, legacy_application.ReviewSuggestionBatchItemCommand)

    assert server_public.normalize_suggestion_tag_filter(" Queue ") == "queue"
    server_public.validate_suggestion_status_filter("pending")

    with pytest.raises(MemoryValidationError, match="Unknown suggestion operation"):
        server_public.validate_suggestion_operation("unknown")
    with pytest.raises(MemoryValidationError, match="Unknown suggestion review action"):
        server_public.validate_suggestion_review_action("resolve_duplicate")


def test_memory_facts_public_seam_validates_relation_status_filter() -> None:
    server_public.validate_fact_status_filter(None)
    server_public.validate_fact_status_filter("active")
    server_public.validate_fact_status_filter("deleted")

    with pytest.raises(ValueError, match="Unknown fact status"):
        server_public.validate_fact_status_filter("archived")

    server_public.validate_fact_relation_status_filter(None)
    server_public.validate_fact_relation_status_filter("active")
    server_public.validate_fact_relation_status_filter("deleted")

    with pytest.raises(ValueError, match="Unknown fact relation status"):
        server_public.validate_fact_relation_status_filter("archived")


def test_memory_facts_routes_map_http_contracts_to_feature_use_cases() -> None:
    remember_recorder = RecordingRememberFact()
    update_recorder = RecordingUpdateFact()
    forget_recorder = RecordingForgetFact()
    use_cases = memory_facts.MemoryFactLifecycleUseCases(
        remember_fact=remember_recorder,
        update_fact=update_recorder,
        forget_fact=forget_recorder,
    )
    router = server_public.create_memory_facts_router(use_cases)
    create_route = next(
        route for route in router.routes if route.path == "/facts" and "POST" in route.methods
    )
    update_route = next(
        route
        for route in router.routes
        if route.path == "/facts/{fact_id}" and "PATCH" in route.methods
    )
    forget_route = next(
        route
        for route in router.routes
        if route.path == "/facts/{fact_id}" and "DELETE" in route.methods
    )

    create_body = asyncio.run(
        create_route.endpoint(
            server_public.RememberFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                text="Postgres owns canonical lifecycle.",
                kind="note",
                category="architecture",
                tags=["postgres"],
                source_refs=[
                    server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())
                ],
            ),
            idempotency_key="remember_1",
        )
    )

    assert create_route.status_code == 201
    assert len(remember_recorder.commands) == 1
    assert remember_recorder.commands[0].scope.memory_scope_id == "scope_1"
    assert remember_recorder.commands[0].idempotency_key == "remember_1"
    assert create_body["data"]["id"] == "fact_1"
    assert create_body["data"]["space_id"] == "space_1"
    assert create_body["data"]["memory_scope_id"] == "scope_1"
    assert create_body["data"]["thread_id"] == "thread_1"
    assert create_body["data"]["text"] == "Postgres owns canonical lifecycle."
    assert create_body["data"]["status"] == "active"
    assert create_body["data"]["version"] == 1
    assert create_body["data"]["category"] == "architecture"
    assert create_body["data"]["tags"] == ["postgres"]
    assert create_body["data"]["source_refs"][0]["source_id"] == "doc_1"
    assert create_body["data"]["created_at"] == "2026-01-02T03:04:05"

    update_body = asyncio.run(
        update_route.endpoint(
            "fact_1",
            server_public.UpdateFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                expected_version=1,
                text="Postgres remains the canonical lifecycle store.",
                reason="clarify owner",
                source_refs=[
                    server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())
                ],
            ),
            idempotency_key="update_1",
        )
    )

    assert len(update_recorder.commands) == 1
    update_command = update_recorder.commands[0]
    assert update_command.identity.fact_id == "fact_1"
    assert update_command.identity.scope.memory_scope_id == "scope_1"
    assert update_command.expected_version == 1
    assert update_command.idempotency_key == "update_1"
    assert update_body["data"]["version"] == 2

    forget_body = asyncio.run(
        forget_route.endpoint(
            "fact_1",
            server_public.ForgetFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                expected_version=2,
                reason="obsolete",
            ),
            idempotency_key="forget_1",
        )
    )

    assert len(forget_recorder.commands) == 1
    forget_command = forget_recorder.commands[0]
    assert forget_command.identity.fact_id == "fact_1"
    assert forget_command.expected_version == 2
    assert forget_command.reason == "obsolete"
    assert forget_command.idempotency_key == "forget_1"
    assert forget_body["data"]["status"] == "deleted"
    assert forget_body["data"]["version"] == 3


def test_v1_facts_route_delegates_write_mapping_to_feature_public_seam() -> None:
    source = API_FACTS_PATH.read_text(encoding="utf-8")

    assert "class RememberFactRequest" not in source
    assert "class UpdateFactRequest" not in source
    assert "class LinkFactRequest" not in source
    assert "def map_memory_kind" not in source
    assert "RememberFactCommand(" not in source
    assert "UpdateFactCommand(" not in source
    assert "ForgetFactCommand(" not in source
    assert "LinkFactsCommand(" not in source
    assert "UnlinkFactRelationCommand(" not in source
    assert "map_source_ref" not in source
    assert "def related_fact_to_response" not in source
    assert "def fact_relation_to_response" not in source
    assert "def fact_relation_item_to_response" not in source
    assert "infinity_context_server.api.public_payload" not in _imports(API_FACTS_PATH)
    assert "memory_facts_feature.remember_fact_command_from_v1_request" in source
    assert "memory_facts_feature.update_fact_command_from_v1_request" in source
    assert "memory_facts_feature.forget_fact_command_from_v1_path" in source
    assert "memory_facts_feature.link_fact_relation_command_from_v1_request" in source
    assert "memory_facts_feature.unlink_fact_relation_command_from_v1_path" in source
    assert "memory_facts_feature.memory_kind_from_v1_request" in source
    assert "memory_facts_feature.fact_relation_to_response" in source
    assert "memory_facts_feature.related_fact_to_response" in source


def test_v1_suggestions_route_delegates_feature_helpers_to_public_seam() -> None:
    source = API_SUGGESTIONS_PATH.read_text(encoding="utf-8")
    imports = _imports(API_SUGGESTIONS_PATH)
    tree = ast.parse(source)
    memory_facts_imports = [
        (node.module, tuple(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("infinity_context_server.features.memory_facts")
    ]

    assert "from infinity_context_server.features.memory_facts import public as " in source
    assert memory_facts_imports == [
        ("infinity_context_server.features.memory_facts", ("public",))
    ]
    for removed in (
        "class CreateSuggestionRequest",
        "class CreateSuggestionBatchItemRequest",
        "class CreateSuggestionsBatchRequest",
        "class ReviewSuggestionRequest",
        "class ResolveSuggestionConflictRequest",
        "class ResolveDuplicateMergeRequest",
        "class ReviewSuggestionBatchItemRequest",
        "class ReviewSuggestionsBatchRequest",
        "def suggestion_to_response",
        "def _review_batch_to_response",
        "def _create_batch_to_response",
        "def _create_suggestion_command",
        "def _validate_confidence_and_trust",
        "def _validate_suggestion_status",
        "def _validate_operation",
        "def _validate_review_action",
        "def _normalize_tags",
        "CreateSuggestionCommand(",
        "CreateSuggestionsBatchCommand(",
        "ReviewSuggestionBatchItemCommand(",
        "ReviewSuggestionsBatchCommand(",
        "review_payload_with_default_contract",
        "memory_facts_feature.memory_kind_from_v1_request",
        "memory_facts_feature.source_ref_from_v1_request",
    ):
        assert removed not in source
    assert "infinity_context_server.api.public_payload" not in imports
    assert "infinity_context_server.api.v1.facts" not in imports
    assert "infinity_context_server.api.v1.source_refs" not in imports
    assert "infinity_context_core.application.review_payloads" not in imports
    for delegated in (
        "memory_facts_feature.suggestion_to_response",
        "memory_facts_feature.suggestion_result_to_response",
        "memory_facts_feature.create_suggestions_batch_to_response",
        "memory_facts_feature.review_suggestions_batch_to_response",
        "memory_facts_feature.CreateSuggestionRequest",
        "memory_facts_feature.CreateSuggestionsBatchRequest",
        "memory_facts_feature.ReviewSuggestionRequest",
        "memory_facts_feature.ReviewSuggestionsBatchRequest",
        "memory_facts_feature.create_suggestion_command_from_v1_request",
        "memory_facts_feature.create_suggestions_batch_command_from_v1_request",
        "memory_facts_feature.review_suggestions_batch_command_from_v1_request",
        "memory_facts_feature.validate_suggestion_status_filter",
        "memory_facts_feature.validate_suggestion_operation",
        "memory_facts_feature.normalize_suggestion_tag_filter",
    ):
        assert delegated in source


def test_memory_facts_server_slice_uses_only_public_feature_boundaries() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "infinity_context_adapters",
        "infinity_context_core.application",
        "infinity_context_core.domain",
        "infinity_context_core.ports",
        "infinity_context_server.api",
        "infinity_context_server.composition",
        "graphiti",
        "openai",
        "qdrant_client",
        "sqlalchemy",
    )
    legacy_v1_memory_facts_seam_imports = {
        "infinity_context_core.application",
        "infinity_context_core.domain.entities",
        "infinity_context_core.domain.errors",
    }

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            rel = path.relative_to(REPO_ROOT)
            if path.name in {
                "compatibility.py",
                "suggestion_requests.py",
            } and imported in legacy_v1_memory_facts_seam_imports:
                continue
            if imported.startswith(
                "infinity_context_core.features."
            ) and not imported.endswith(".public"):
                violations.append(f"{rel}: imports {imported}")
            if imported == "infinity_context_core" or any(
                imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes
            ) or imported in forbidden_prefixes:
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def _use_cases() -> memory_facts.MemoryFactLifecycleUseCases:
    return memory_facts.MemoryFactLifecycleUseCases(
        remember_fact=RecordingRememberFact(),
        update_fact=RecordingUpdateFact(),
        forget_fact=RecordingForgetFact(),
    )


def _snapshot(
    *,
    fact_id: str,
    scope: memory_facts.MemoryFactScope,
    text: str,
    source_refs: tuple[memory_facts.MemoryFactSourceRef, ...],
    status: str = "active",
    version: int = 1,
    category: str | None = None,
    tags: tuple[str, ...] = (),
) -> memory_facts.MemoryFactSnapshot:
    now = datetime(2026, 1, 2, 3, 4, 5)
    return memory_facts.MemoryFactSnapshot(
        identity=memory_facts.MemoryFactIdentity(fact_id=fact_id, scope=scope),
        text=text,
        source_refs=source_refs,
        visibility=memory_facts.MemoryFactVisibility(
            status=status,
            version=version,
            confidence="medium",
            trust_level="medium",
            classification="internal",
        ),
        kind="note",
        category=category,
        tags=tags,
        created_at=now,
        updated_at=now,
    )


def _source_ref() -> memory_facts.MemoryFactSourceRef:
    return memory_facts.MemoryFactSourceRef(
        source_type="document",
        source_id="doc_1",
        chunk_id="chunk_1",
        char_start=0,
        char_end=37,
        quote_preview="Postgres owns canonical lifecycle.",
    )


def _source_ref_json() -> dict[str, object]:
    return {
        "source_type": "document",
        "source_id": "doc_1",
        "chunk_id": "chunk_1",
        "char_start": 0,
        "char_end": 37,
        "quote_preview": "Postgres owns canonical lifecycle.",
    }


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
