import asyncio
from typing import Any

from infinity_context_mcp.application.service import MemoryToolService
from infinity_context_mcp.config import MemoryMcpSettings, MemoryMcpWriteMode
from infinity_context_mcp.domain.models import MemoryGatewayError, MemoryScope
from mcp_adapter_fakes import RecordingGateway


def test_service_suggest_fact_creates_pending_review_candidate() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_memory_scope_external_ref="backend",
            ),
        )

        result = await service.suggest_fact(
            candidate_text="Qdrant is used for document recall candidates.",
            kind="architecture_decision",
        )

        assert result["ok"] is True
        assert result["data"]["status"] == "pending"
        call = gateway.calls[0][1]
        assert call["scope"] == MemoryScope("project-a", "backend", None)
        assert call["source_refs"][0].source_type == "ai_response"
        assert call["safe_reason"] == "mcp_agent_suggestion_requires_review"

    asyncio.run(run())


def test_service_list_suggestions_forwards_review_queue_filters() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_memory_scope_external_ref="backend",
            ),
        )

        result = await service.list_suggestions(
            status="pending",
            operation="review",
            category="Review",
            tag="Needs-Human",
            limit=25,
        )

        assert result["ok"] is True
        assert gateway.calls == [
            (
                "list_suggestions",
                {
                    "scope": MemoryScope("project-a", "backend", None),
                    "status": "pending",
                    "operation": "review",
                    "category": "review",
                    "tag": "needs-human",
                    "limit": 25,
                },
            )
        ]

    asyncio.run(run())


def test_service_propose_updates_creates_suggestion_in_suggest_mode() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                write_mode=MemoryMcpWriteMode.SUGGEST,
                default_space_slug="project-a",
                default_memory_scope_external_ref="backend",
            ),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Postgres is canonical truth.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                }
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["ok"] is True
        assert result["data"]["accepted_suggestions"][0]["suggestion_id"] == "sug_1"
        assert result["diagnostics"]["side_effects"] == ["created_suggestion"]
        assert gateway.calls[0][0] == "list_facts"
        assert gateway.calls[1][0] == "list_suggestions"
        assert gateway.calls[2][0] == "create_suggestion"

    asyncio.run(run())


def test_service_propose_updates_direct_explicit_requires_confirmation() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT_EXPLICIT),
        )

        without_confirmation = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Qdrant for vector recall.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                }
            ],
            source_type="manual",
            source_id="note-1",
        )
        with_confirmation = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Graphiti for temporal facts.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                    "evidence_quote": "Use Graphiti for temporal facts.",
                }
            ],
            source_type="manual",
            source_id="note-2",
            user_confirmed=True,
        )

        assert without_confirmation["data"]["accepted_suggestions"][0]["decision_code"] == (
            "infinity_context_mcp.policy.explicit_confirmation_required"
        )
        assert with_confirmation["data"]["direct_writes"][0]["fact_id"] == "fact_1"
        assert [name for name, _ in gateway.calls].count("remember_fact") == 1

    asyncio.run(run())


def test_service_propose_updates_uncertain_evidence_needs_review_even_when_confirmed() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Graphiti is being removed.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                    "evidence_quote": "I might have heard Graphiti is being removed, not sure.",
                }
            ],
            source_type="manual",
            source_id="uncertain-note",
            user_confirmed=True,
        )

        assert result["ok"] is True
        assert result["data"]["accepted_suggestions"][0]["decision_code"] == (
            "infinity_context_mcp.policy.uncertain_claim"
        )
        assert result["diagnostics"]["side_effects"] == ["created_suggestion"]
        assert [name for name, _ in gateway.calls] == [
            "list_facts",
            "list_suggestions",
            "create_suggestion",
        ]

    asyncio.run(run())


def test_service_propose_updates_dedupes_same_batch() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Postgres as canonical truth.",
                    "operation": "remember",
                    "evidence_quote": "Use Postgres as canonical truth.",
                },
                {
                    "text": " use postgres as canonical truth. ",
                    "operation": "remember",
                    "evidence_quote": "Use Postgres as canonical truth.",
                },
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["data"]["direct_writes"][0]["status"] == "direct_write"
        assert (
            result["data"]["duplicates"][0]["decision_code"]
            == "infinity_context_mcp.duplicate.same_batch"
        )
        assert [name for name, _ in gateway.calls].count("remember_fact") == 1

    asyncio.run(run())


def test_service_propose_updates_detects_existing_fact_conflict() -> None:
    class ConflictingFactGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_mysql",
                        "text": "Use MySQL as canonical truth.",
                    }
                ]
            }

    async def run() -> None:
        gateway = ConflictingFactGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Postgres as canonical truth.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                }
            ],
            source_type="manual",
            source_id="note-1",
        )

        assert result["ok"] is True
        assert result["data"]["conflicts"][0]["decision_code"] == (
            "infinity_context_mcp.conflict.requires_review"
        )
        assert result["data"]["conflicts"][0]["duplicate_id"] == "fact_mysql"
        assert [name for name, _ in gateway.calls] == ["list_facts", "list_suggestions"]

    asyncio.run(run())


def test_service_propose_updates_dedupes_pending_suggestions() -> None:
    class PendingSuggestionGateway(RecordingGateway):
        async def list_suggestions(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_suggestions", kwargs))
            return {
                "data": [
                    {
                        "id": "sug_pending",
                        "candidate_text": "Use Graphiti for temporal facts.",
                    }
                ]
            }

    async def run() -> None:
        gateway = PendingSuggestionGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Graphiti for temporal facts.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                }
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["ok"] is True
        assert result["data"]["duplicates"][0]["decision_code"] == (
            "infinity_context_mcp.duplicate.existing_memory"
        )
        assert result["data"]["duplicates"][0]["duplicate_id"] == "sug_pending"
        assert "create_suggestion" not in [name for name, _ in gateway.calls]
        assert "remember_fact" not in [name for name, _ in gateway.calls]

    asyncio.run(run())


def test_service_propose_updates_dedupes_semantic_equivalent_pending_suggestion() -> None:
    class PendingSuggestionGateway(RecordingGateway):
        async def list_suggestions(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_suggestions", kwargs))
            return {
                "data": [
                    {
                        "id": "sug_qdrant_documents",
                        "candidate_text": "Qdrant owns document vector retrieval.",
                    }
                ]
            }

    async def run() -> None:
        gateway = PendingSuggestionGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Docs retrieval should use Qdrant vectors.",
                    "kind": "architecture_decision",
                    "operation": "remember",
                }
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["ok"] is True
        assert result["data"]["duplicates"][0]["decision_code"] == (
            "infinity_context_mcp.duplicate.existing_memory"
        )
        assert result["data"]["duplicates"][0]["duplicate_id"] == "sug_qdrant_documents"
        assert "create_suggestion" not in [name for name, _ in gateway.calls]
        assert "remember_fact" not in [name for name, _ in gateway.calls]

    asyncio.run(run())


def test_service_propose_updates_rejects_unsafe_and_invalid_candidates() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Remember token sk-test-secret-token",
                    "operation": "remember",
                },
                {
                    "text": "Updated fact",
                    "operation": "update",
                    "expected_version": 1,
                },
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert [item["decision_code"] for item in result["data"]["unsafe_rejected"]] == [
            "infinity_context_mcp.policy.secret_detected",
            "infinity_context_mcp.validation.invalid_input",
        ]
        assert gateway.calls == []

    asyncio.run(run())


def test_service_propose_updates_dry_run_has_no_side_effects() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.propose_updates(
            candidates=[{"text": "Use Neo4j for graph storage.", "operation": "remember"}],
            source_type="manual",
            source_id="note-1",
            dry_run=True,
        )

        assert (
            result["data"]["needs_review"][0]["decision_code"]
            == "infinity_context_mcp.policy.dry_run"
        )
        assert result["diagnostics"]["side_effects"] == []
        assert gateway.calls == []

    asyncio.run(run())


def test_service_propose_updates_requires_evidence_for_direct_write() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[{"text": "Use Redis for cache state.", "operation": "remember"}],
            source_type="manual",
            source_id="note-1",
        )

        assert result["ok"] is True
        assert result["data"]["accepted_suggestions"][0]["decision_code"] == (
            "infinity_context_mcp.policy.evidence_required"
        )
        assert [name for name, _ in gateway.calls] == [
            "list_facts",
            "list_suggestions",
            "create_suggestion",
        ]

    asyncio.run(run())


def test_service_propose_updates_detects_evidence_mismatch() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "User decided to use Rust for the backend.",
                    "operation": "remember",
                    "evidence_quote": "We discussed deployment timing only.",
                }
            ],
            source_type="manual",
            source_id="note-1",
        )

        assert result["data"]["needs_review"][0]["decision_code"] == (
            "infinity_context_mcp.policy.evidence_mismatch"
        )
        assert gateway.calls == []

    asyncio.run(run())


def test_service_propose_updates_rejects_string_booleans() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.propose_updates(
            candidates=[{"text": "Use Graphiti for temporal facts.", "operation": "remember"}],
            source_type="manual",
            source_id="note-1",
            user_confirmed="true",  # type: ignore[arg-type]
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "infinity_context_mcp.validation.invalid_input"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_propose_updates_maps_stale_expected_version_to_conflict() -> None:
    class StaleVersionGateway(RecordingGateway):
        async def update_fact(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("update_fact", kwargs))
            raise MemoryGatewayError(
                status_code=409,
                code="version_conflict",
                message="expected_version is stale",
                retryable=False,
            )

    async def run() -> None:
        gateway = StaleVersionGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "Use Postgres as canonical truth.",
                    "operation": "update",
                    "target_fact_id": "fact_1",
                    "expected_version": 1,
                    "evidence_quote": "Use Postgres as canonical truth.",
                }
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["ok"] is True
        assert result["data"]["conflicts"][0]["decision_code"] == (
            "infinity_context_mcp.conflict.version_stale"
        )
        assert result["data"]["conflicts"][0]["target_fact_id"] == "fact_1"
        assert [name for name, _ in gateway.calls] == ["update_fact"]

    asyncio.run(run())


def test_service_propose_updates_conflicts_same_target_in_batch() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.propose_updates(
            candidates=[
                {
                    "text": "First update text.",
                    "operation": "update",
                    "target_fact_id": "fact_1",
                    "expected_version": 1,
                    "evidence_quote": "First update text.",
                },
                {
                    "text": "Second update text.",
                    "operation": "update",
                    "target_fact_id": "fact_1",
                    "expected_version": 1,
                    "evidence_quote": "Second update text.",
                },
            ],
            source_type="manual",
            source_id="note-1",
            user_confirmed=True,
        )

        assert result["data"]["direct_writes"][0]["status"] == "direct_update"
        assert result["data"]["conflicts"][0]["decision_code"] == (
            "infinity_context_mcp.conflict.same_target_in_batch"
        )
        assert [name for name, _ in gateway.calls].count("update_fact") == 1

    asyncio.run(run())


def test_service_can_review_suggestions_by_id_only() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(),
        )

        approved = await service.approve_suggestion(
            suggestion_id="sug_1",
            reason="reviewed",
        )
        rejected = await service.reject_suggestion(
            suggestion_id="sug_2",
            reason="not durable",
        )
        expired = await service.expire_suggestion(
            suggestion_id="sug_3",
            reason="stale",
        )

        assert approved["ok"] is True
        assert approved["data"]["fact"]["id"] == "fact_from_suggestion"
        assert rejected["data"]["status"] == "rejected"
        assert expired["data"]["status"] == "expired"
        assert [name for name, _ in gateway.calls] == [
            "approve_suggestion",
            "reject_suggestion",
            "expire_suggestion",
        ]
        assert gateway.calls[0][1] == {
            "suggestion_id": "sug_1",
            "reason": "reviewed",
            "force": False,
        }

    asyncio.run(run())


def test_service_review_suggestion_consolidates_actions() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        approved = await service.review_suggestion(
            suggestion_id="sug_1",
            action="approve",
            reason="reviewed",
        )
        rejected = await service.review_suggestion(
            suggestion_id="sug_2",
            action="reject",
            reason="not durable",
        )
        expired = await service.review_suggestion(
            suggestion_id="sug_3",
            action="expire",
            reason="stale",
        )

        assert approved["data"]["fact"]["id"] == "fact_from_suggestion"
        assert rejected["data"]["status"] == "rejected"
        assert expired["data"]["status"] == "expired"
        assert approved["diagnostics"]["side_effects"] == ["approved_suggestion"]
        assert [name for name, _ in gateway.calls] == [
            "approve_suggestion",
            "reject_suggestion",
            "expire_suggestion",
        ]

    asyncio.run(run())


def test_service_review_suggestion_rejects_invalid_action() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.review_suggestion(suggestion_id="sug_1", action="merge")

        assert result["ok"] is False
        assert result["error"]["code"] == "infinity_context_mcp.validation.invalid_input"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_lists_and_consolidates_captures_without_raw_payload() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_memory_scope_external_ref="backend",
            ),
        )

        listed = await service.list_captures(
            status="accepted",
            consolidation_status="pending",
            limit=1000,
        )
        consolidated = await service.consolidate_capture(capture_id="cap_1")

        assert listed["ok"] is True
        assert listed["data"]["items"][0]["capture_id"] == "cap_1"
        assert listed["data"]["items"][0]["text_preview"]
        assert "raw_payload" not in listed["data"]["items"][0]
        assert listed["diagnostics"]["warnings"] == ["limit_clamped_to_max"]
        assert consolidated["ok"] is True
        assert consolidated["data"]["created_suggestions"] == 1
        assert consolidated["diagnostics"]["side_effects"] == ["consolidated_capture"]
        assert [name for name, _ in gateway.calls] == [
            "list_captures",
            "consolidate_capture",
        ]
        assert gateway.calls[0][1]["scope"] == MemoryScope("project-a", "backend", None)
        assert gateway.calls[0][1]["limit"] == 500
        assert gateway.calls[1][1] == {"capture_id": "cap_1", "force": False}

    asyncio.run(run())


def test_service_consolidate_capture_reports_auto_apply_side_effect() -> None:
    class AutoApplyGateway(RecordingGateway):
        async def consolidate_capture(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("consolidate_capture", kwargs))
            return {
                "data": {
                    "capture": {
                        "id": kwargs["capture_id"],
                        "capture_id": kwargs["capture_id"],
                        "status": "accepted",
                        "consolidation_status": "consolidated",
                    },
                    "created_suggestions": 0,
                    "suggestion_ids": [],
                    "auto_applied_facts": 1,
                    "auto_applied_fact_ids": ["fact_1"],
                }
            }

    async def run() -> None:
        gateway = AutoApplyGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.consolidate_capture(capture_id="cap_1")

        assert result["ok"] is True
        assert result["data"]["auto_applied_facts"] == 1
        assert result["data"]["auto_applied_fact_ids"] == ["fact_1"]
        assert result["diagnostics"]["side_effects"] == [
            "consolidated_capture",
            "auto_applied_fact",
        ]

    asyncio.run(run())


def test_service_list_captures_rejects_unknown_statuses() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.list_captures(status="active")

        assert result["ok"] is False
        assert result["error"]["code"] == "infinity_context_mcp.validation.invalid_input"
        assert gateway.calls == []

    asyncio.run(run())
