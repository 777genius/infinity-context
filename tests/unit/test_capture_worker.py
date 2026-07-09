import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.application import ConsolidateCaptureCommand, ConsolidateCaptureUseCase
from infinity_context_core.domain.entities import Confidence, MemoryKind, SourceRef
from infinity_context_core.domain.errors import MemoryInfrastructureError
from infinity_context_core.ports.auto_memory import (
    CandidateOperation,
    MemoryCandidate,
    SourceProvenance,
)
from infinity_context_server.config import CaptureMode, DeployProfile, MemoryPolicyMode, Settings
from infinity_context_server.main import create_app
from infinity_context_server.processes import build_outbox_event_dispatcher
from infinity_context_server.worker import OutboxWorker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class StaticExtractor:
    version = "static-test-extractor-v1"
    prompt_version = "static-test-prompt-v1"

    def __init__(
        self,
        candidates: tuple[MemoryCandidate, ...],
        *,
        requires_external_ai: bool = False,
    ) -> None:
        self._candidates = candidates
        self.requires_external_ai = requires_external_ai
        self.calls = 0

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        self.calls += 1
        return self._candidates


class FailingInfrastructureExtractor:
    version = "failing-infra-test-extractor-v1"
    prompt_version = "failing-infra-test-prompt-v1"
    requires_external_ai = True

    def __init__(self, message: str = "provider unavailable") -> None:
        self._message = message
        self.calls = 0

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        self.calls += 1
        raise MemoryInfrastructureError(self._message)


def test_outbox_event_dispatcher_registry_is_owned_by_process_boundary() -> None:
    dispatcher = build_outbox_event_dispatcher(object())

    assert dispatcher.event_types == (
        "vector.upsert_chunk",
        "vector.upsert_chunks",
        "vector.delete_chunks",
        "graph.upsert_fact",
        "graph.delete_fact",
        "cognee.ingest_document",
        "cognee.forget_document",
        "capture.consolidate",
        "asset.extract",
    )


def test_capture_outbox_worker_creates_suggestion(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/captures",
            json={
                "space_slug": "capture-worker",
                "memory_scope_external_ref": "default",
                "source_agent": "codex",
                "source_kind": "hook",
                "event_type": "UserPromptSubmit",
                "actor_role": "user",
                "source_event_id": "worker-event",
                "text": "Remember: CAPTURE_WORKER_MARKER worker should create suggestion.",
                "source_authority": "user_statement",
            },
            headers=headers,
        )
        assert created.status_code == 201
        processed = asyncio.run(OutboxWorker(app.state.container).run_once(limit=10))
        suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-worker",
                "memory_scope_external_ref": "default",
                "status": "pending",
            },
            headers=headers,
        )

    assert processed >= 1
    assert suggestions.status_code == 200
    assert "CAPTURE_WORKER_MARKER" in suggestions.text


def test_capture_outbox_retry_recovers_stuck_running_capture(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker-retry-running.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/captures",
            json={
                "space_slug": "capture-worker-retry",
                "memory_scope_external_ref": "default",
                "source_agent": "codex",
                "source_kind": "hook",
                "event_type": "UserPromptSubmit",
                "actor_role": "user",
                "source_event_id": "worker-retry-event",
                "text": "Remember: CAPTURE_WORKER_RETRY_MARKER retry should drain.",
                "source_authority": "user_statement",
            },
            headers=headers,
        )
        capture_id = created.json()["data"]["id"]

        async def simulate_recovered_outbox_retry() -> None:
            now = client.app.state.container.clock.now()
            async with client.app.state.container.uow_factory() as uow:
                capture = await uow.captures.get_for_update(capture_id)
                assert capture is not None
                await uow.captures.save(capture.mark_running(now=now))
                await uow.commit()
            async with AsyncSession(client.app.state.container.engine) as session:
                row = (
                    await session.execute(
                        select(MemoryOutboxRow).where(
                            MemoryOutboxRow.event_type == "capture.consolidate",
                            MemoryOutboxRow.aggregate_id == capture_id,
                        )
                    )
                ).scalar_one()
                row.attempt_count = 1
                await session.commit()

        asyncio.run(simulate_recovered_outbox_retry())
        processed = asyncio.run(OutboxWorker(app.state.container).run_once(limit=10))
        suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-worker-retry",
                "memory_scope_external_ref": "default",
                "status": "pending",
            },
            headers=headers,
        )

    assert processed >= 1
    assert suggestions.status_code == 200
    assert "CAPTURE_WORKER_RETRY_MARKER" in suggestions.text


def test_worker_expires_pending_suggestions_even_without_outbox_jobs(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "worker-expire-suggestions.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    expired_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with TestClient(app) as client:
        created = client.post(
            "/v1/suggestions",
            json={
                "space_slug": "worker-expiry",
                "memory_scope_external_ref": "default",
                "candidate_text": "WORKER_EXPIRED_SUGGESTION_MARKER should expire.",
                "kind": "note",
                "source_refs": [
                    {
                        "source_type": "capture:hook",
                        "source_id": "cap_expired",
                        "quote_preview": "WORKER_EXPIRED_SUGGESTION_MARKER should expire.",
                    }
                ],
                "confidence": "medium",
                "trust_level": "medium",
                "safe_reason": "expired suggestion regression",
                "expires_at": expired_at,
                "expiry_reason": "ttl_elapsed",
            },
            headers=headers,
        )
        assert created.status_code == 201
        processed = asyncio.run(OutboxWorker(app.state.container).run_once(limit=10))
        pending = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "worker-expiry",
                "memory_scope_external_ref": "default",
                "status": "pending",
            },
            headers=headers,
        )
        expired = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "worker-expiry",
                "memory_scope_external_ref": "default",
                "status": "expired",
            },
            headers=headers,
        )

    assert processed == 0
    assert pending.json()["data"] == []
    assert expired.json()["data"][0]["candidate_text"] == (
        "WORKER_EXPIRED_SUGGESTION_MARKER should expire."
    )
    assert expired.json()["data"][0]["expiry_reason"] == "ttl_elapsed"


def test_consolidation_external_extractor_requires_policy_consent(tmp_path: Path) -> None:
    extractor = StaticExtractor((_candidate("EXTERNAL_EGRESS_MARKER"),), requires_external_ai=True)
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'external-gate.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
            capture_external_ai_enabled=False,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-external-gate",
            marker="EXTERNAL_EGRESS_MARKER",
        )
        capture_id = created.json()["data"]["id"]
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
            external_ai_enabled=container.settings.capture_external_ai_enabled,
        )
        result = asyncio.run(use_case.execute(ConsolidateCaptureCommand(capture_id=capture_id)))
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-external-gate")

    assert extractor.calls == 0
    assert result.capture.consolidation_status.value == "skipped"
    assert result.capture.last_error_code == "external_ai_disabled"
    assert suggestions.json()["data"] == []


def test_consolidation_skips_pending_capture_after_policy_downgrade(tmp_path: Path) -> None:
    marker = "POLICY_DOWNGRADE_MARKER"
    extractor = StaticExtractor((_candidate(marker),))
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'policy-downgrade.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            policy_mode=MemoryPolicyMode.SUGGESTIONS,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-policy-downgrade",
            marker=marker,
        )
        capture_id = created.json()["data"]["id"]
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
            capture_consolidation_enabled=False,
        )
        result = asyncio.run(use_case.execute(ConsolidateCaptureCommand(capture_id=capture_id)))
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-policy-downgrade",
        )

    assert extractor.calls == 0
    assert result.capture.consolidation_status.value == "skipped"
    assert result.capture.last_error_code == "capture_policy_disabled"
    assert suggestions.json()["data"] == []


def test_consolidation_provider_outage_leaves_capture_retryable(tmp_path: Path) -> None:
    secret = "sk" + "-proj-capture-provider-" + "dummy-value"
    extractor = FailingInfrastructureExtractor(
        f"provider unavailable Authorization: Bearer {secret}"
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'provider-retry.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
            capture_external_ai_enabled=True,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-provider-retry",
            marker="PROVIDER_RETRY_MARKER",
        )
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
            external_ai_enabled=container.settings.capture_external_ai_enabled,
        )
        result = asyncio.run(
            use_case.execute(
                ConsolidateCaptureCommand(capture_id=created.json()["data"]["id"])
            )
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-provider-retry",
        )

    assert extractor.calls == 1
    assert result.capture.consolidation_status.value == "retry_pending"
    assert result.capture.last_error_code == "extractor_infrastructure_unavailable"
    assert secret not in (result.capture.last_error_message or "")
    assert "[redacted]" in (result.capture.last_error_message or "")
    assert suggestions.json()["data"] == []


def test_consolidation_rejects_over_limit_extractor_output(tmp_path: Path) -> None:
    extractor = StaticExtractor(
        tuple(_candidate(f"TOO_MANY_CANDIDATE_{index}") for index in range(21))
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'over-limit.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-over-limit",
            marker="TOO_MANY_CANDIDATE_0",
        )
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
        )
        result = asyncio.run(
            use_case.execute(
                ConsolidateCaptureCommand(capture_id=created.json()["data"]["id"])
            )
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-over-limit")

    assert extractor.calls == 1
    assert result.capture.consolidation_status.value == "dead"
    assert result.capture.last_error_code == "extractor_invalid_output"
    assert suggestions.json()["data"] == []


def test_consolidation_rejects_hallucinated_evidence_quote(tmp_path: Path) -> None:
    extractor = StaticExtractor(
        (
            _candidate(
                "EVIDENCE_HALLUCINATION_MARKER should not persist.",
                quote="quote not present in capture text",
            ),
        )
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'bad-evidence.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-bad-evidence",
            marker="EVIDENCE_HALLUCINATION_MARKER",
        )
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
        )
        result = asyncio.run(
            use_case.execute(
                ConsolidateCaptureCommand(capture_id=created.json()["data"]["id"])
            )
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-bad-evidence")

    assert result.capture.consolidation_status.value == "skipped"
    assert result.capture.last_error_code == "no_valid_candidates"
    assert suggestions.json()["data"] == []


def test_consolidation_rejects_candidate_without_source_refs(tmp_path: Path) -> None:
    extractor = StaticExtractor(
        (
            MemoryCandidate(
                text="MISSING_SOURCE_REF_MARKER should not persist.",
                kind=MemoryKind.NOTE,
                confidence=Confidence.MEDIUM,
                source_refs=(),
                safe_reason="static extractor missing source refs",
            ),
        )
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'missing-source-ref.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-missing-source-ref",
            marker="MISSING_SOURCE_REF_MARKER",
        )
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
        )
        result = asyncio.run(
            use_case.execute(
                ConsolidateCaptureCommand(capture_id=created.json()["data"]["id"])
            )
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-missing-source-ref",
        )

    assert result.capture.consolidation_status.value == "skipped"
    assert result.capture.last_error_code == "no_valid_candidates"
    assert suggestions.json()["data"] == []


def test_resolver_coalesces_conflicting_update_delete_candidates(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'resolver.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        fact_response = client.post(
            "/v1/facts",
            json={
                "space_slug": "capture-resolver",
                "memory_scope_external_ref": "default",
                "text": "TARGET_FACT_MARKER old canonical decision.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "resolver-fact"}],
            },
            headers=headers,
        )
        fact = fact_response.json()["data"]
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-resolver",
            marker="TARGET_FACT_MARKER new canonical decision",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    "TARGET_FACT_MARKER new canonical decision.",
                    operation=CandidateOperation.UPDATE,
                    target_fact_id=fact["id"],
                    target_fact_version=fact["version"],
                    quote="TARGET_FACT_MARKER new canonical decision",
                ),
                _candidate(
                    "Delete TARGET_FACT_MARKER old canonical decision.",
                    operation=CandidateOperation.DELETE,
                    target_fact_id=fact["id"],
                    target_fact_version=fact["version"],
                    quote="TARGET_FACT_MARKER new canonical decision",
                ),
            )
        )
        container = client.app.state.container
        use_case = ConsolidateCaptureUseCase(
            uow_factory=container.uow_factory,
            clock=container.clock,
            ids=container.ids,
            extractor=extractor,
        )
        result = asyncio.run(
            use_case.execute(
                ConsolidateCaptureCommand(capture_id=created.json()["data"]["id"])
            )
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-resolver")

    assert result.created_suggestions == 1
    assert suggestions.status_code == 200
    suggestion = suggestions.json()["data"][0]
    assert suggestion["operation"] == "update"
    assert suggestion["target_fact_id"] == fact["id"]
    assert suggestion["target_fact_version"] == fact["version"]
    diff_preview = suggestion["review_payload"]["diff_preview"]
    assert diff_preview["before"].startswith("TARGET_FACT_MARKER old")
    assert diff_preview["after"].startswith("TARGET_FACT_MARKER new")


def test_resolver_finds_update_target_from_hint(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "resolver-target-hint.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        fact_response = client.post(
            "/v1/facts",
            json={
                "space_slug": "capture-target-hint",
                "memory_scope_external_ref": "default",
                "text": "TARGET_HINT_MARKER provider is REST.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "target-hint-fact"}],
            },
            headers=headers,
        )
        fact = fact_response.json()["data"]
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-target-hint",
            marker="TARGET_HINT_MARKER provider is GraphQL",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    "TARGET_HINT_MARKER provider is GraphQL.",
                    operation=CandidateOperation.UPDATE,
                    target_hint="provider is REST",
                    quote="TARGET_HINT_MARKER provider is GraphQL",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=False,
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-target-hint")

    assert result.created_suggestions == 1
    suggestion = suggestions.json()["data"][0]
    assert suggestion["operation"] == "update"
    assert suggestion["target_fact_id"] == fact["id"]
    assert suggestion["target_fact_version"] == fact["version"]
    assert suggestion["review_payload"]["target_hint"] == "provider is REST"
    assert suggestion["review_payload"]["target_resolution"]["status"] == "resolved"
    assert suggestion["review_payload"]["diff_preview"]["before"].startswith("TARGET_HINT_MARKER")


def test_resolver_finds_delete_target_from_hint(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "resolver-delete-hint.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        fact_response = client.post(
            "/v1/facts",
            json={
                "space_slug": "capture-delete-hint",
                "memory_scope_external_ref": "default",
                "text": "DELETE_HINT_MARKER legacy Angular frontend.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "delete-hint-fact"}],
            },
            headers=headers,
        )
        fact = fact_response.json()["data"]
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-delete-hint",
            marker="DELETE_HINT_MARKER legacy Angular frontend",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    "legacy Angular frontend",
                    operation=CandidateOperation.DELETE,
                    target_hint="legacy Angular frontend",
                    quote="DELETE_HINT_MARKER legacy Angular frontend",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=False,
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-delete-hint")

    assert result.created_suggestions == 1
    suggestion = suggestions.json()["data"][0]
    assert suggestion["operation"] == "delete"
    assert suggestion["target_fact_id"] == fact["id"]
    assert suggestion["target_fact_version"] == fact["version"]
    assert suggestion["review_payload"]["target_resolution"]["status"] == "resolved"


def test_resolver_rejects_ambiguous_target_hint(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "resolver-ambiguous-hint.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        for index in (1, 2):
            response = client.post(
                "/v1/facts",
                json={
                    "space_slug": "capture-ambiguous-hint",
                    "memory_scope_external_ref": "default",
                    "text": f"AMBIGUOUS_HINT_MARKER provider option {index}.",
                    "kind": "note",
                    "source_refs": [
                        {"source_type": "manual", "source_id": f"ambiguous-hint-{index}"}
                    ],
                },
                headers=headers,
            )
            assert response.status_code == 201
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-ambiguous-hint",
            marker="AMBIGUOUS_HINT_MARKER provider changed",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    "AMBIGUOUS_HINT_MARKER provider changed.",
                    operation=CandidateOperation.UPDATE,
                    target_hint="AMBIGUOUS_HINT_MARKER provider",
                    quote="AMBIGUOUS_HINT_MARKER provider changed",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=False,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-ambiguous-hint",
        )

    assert result.created_suggestions == 0
    assert result.capture.consolidation_status.value == "consolidated"
    assert suggestions.json()["data"] == []


def test_auto_apply_safe_applies_only_strict_explicit_add(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "auto-apply.db", capture_mode=CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    marker = "AUTO_APPLY_SAFE_MARKER durable project fact"
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-auto-apply",
            marker=marker,
            trust_level="high",
            source_authority="explicit_user_command",
            sensitivity="low",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    f"{marker}.",
                    confidence=Confidence.HIGH,
                    ttl_policy="durable",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=True,
        )
        suggestions = _list_suggestions(client, headers=headers, space_slug="capture-auto-apply")
        facts = _list_facts(client, headers=headers, space_slug="capture-auto-apply")

    assert result.created_suggestions == 0
    assert result.auto_applied_facts == 1
    assert result.auto_applied_fact_ids
    assert suggestions.json()["data"] == []
    assert len(facts.json()["data"]) == 1
    assert marker in facts.json()["data"][0]["text"]


def test_auto_apply_safe_disabled_downgrades_to_suggestion(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "auto-apply-disabled.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    marker = "AUTO_APPLY_DISABLED_MARKER durable project fact"
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-auto-apply-disabled",
            marker=marker,
            trust_level="high",
            source_authority="explicit_user_command",
            sensitivity="low",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    f"{marker}.",
                    confidence=Confidence.HIGH,
                    ttl_policy="durable",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=False,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-auto-apply-disabled",
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-auto-apply-disabled")

    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert len(suggestions.json()["data"]) == 1
    assert facts.json()["data"] == []


def test_auto_apply_safe_medium_confidence_remains_suggestion(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "auto-apply-medium.db", capture_mode=CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    marker = "AUTO_APPLY_MEDIUM_MARKER needs review"
    with TestClient(app) as client:
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-auto-apply-medium",
            marker=marker,
            trust_level="high",
            source_authority="explicit_user_command",
            sensitivity="low",
        )
        extractor = StaticExtractor((_candidate(f"{marker}.", ttl_policy="durable"),))
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=True,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-auto-apply-medium",
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-auto-apply-medium")

    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert suggestions.json()["data"][0]["review_payload"]["rejected_resolver_codes"] == [
        "auto_apply_requires_high_confidence"
    ]
    assert facts.json()["data"] == []


def test_auto_apply_safe_active_duplicate_creates_merge_review_suggestion(
    tmp_path: Path,
) -> None:
    app = _capture_app(
        tmp_path,
        "auto-apply-duplicate.db",
        capture_mode=CaptureMode.AUTO_APPLY_SAFE,
    )
    headers = {"Authorization": "Bearer test-token"}
    marker = "AUTO_APPLY_DUPLICATE_MARKER already exists."
    with TestClient(app) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "capture-auto-apply-duplicate",
                "memory_scope_external_ref": "default",
                "text": marker,
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "duplicate-fact"}],
            },
            headers=headers,
        )
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-auto-apply-duplicate",
            marker=marker,
            trust_level="high",
            source_authority="explicit_user_command",
            sensitivity="low",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    marker,
                    confidence=Confidence.HIGH,
                    ttl_policy="durable",
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=True,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-auto-apply-duplicate",
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-auto-apply-duplicate")

    assert fact.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    suggestion = suggestions.json()["data"][0]
    assert suggestion["operation"] == "review"
    assert suggestion["target_fact_id"] == fact.json()["data"]["id"]
    assert suggestion["review_payload"]["review_kind"] == "duplicate_fact_merge"
    assert suggestion["review_payload"]["dedupe_match_type"] == "exact_normalized_text"
    assert suggestion["review_payload"]["review_risk"] == "low"
    assert suggestion["review_payload"]["recommendation_confidence"] == "high"
    assert suggestion["review_payload"]["requires_review"] is True
    assert suggestion["review_payload"]["auto_merge_eligible"] is False
    assert len(facts.json()["data"]) == 1
    assert facts.json()["data"][0]["text"] == marker


def test_delete_candidate_is_not_suppressed_by_active_duplicate_check(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "delete-duplicate-check.db", capture_mode=CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    marker = "DELETE_DUPLICATE_CHECK_MARKER obsolete fact."
    with TestClient(app) as client:
        fact_response = client.post(
            "/v1/facts",
            json={
                "space_slug": "capture-delete-duplicate-check",
                "memory_scope_external_ref": "default",
                "text": marker,
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "delete-target"}],
            },
            headers=headers,
        )
        fact = fact_response.json()["data"]
        created = _create_capture(
            client,
            headers=headers,
            space_slug="capture-delete-duplicate-check",
            marker=marker,
            trust_level="high",
            source_authority="explicit_user_command",
            sensitivity="low",
        )
        extractor = StaticExtractor(
            (
                _candidate(
                    marker,
                    operation=CandidateOperation.DELETE,
                    target_fact_id=fact["id"],
                    target_fact_version=fact["version"],
                ),
            )
        )
        result = _consolidate_with_extractor(
            client,
            capture_id=created.json()["data"]["id"],
            extractor=extractor,
            auto_apply_safe_enabled=True,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-delete-duplicate-check",
        )

    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert suggestions.json()["data"][0]["operation"] == "delete"
    assert suggestions.json()["data"][0]["target_fact_id"] == fact["id"]


def _candidate(
    text: str,
    *,
    operation: CandidateOperation = CandidateOperation.ADD,
    target_fact_id: str | None = None,
    target_fact_version: int | None = None,
    target_hint: str | None = None,
    quote: str | None = None,
    confidence: Confidence = Confidence.MEDIUM,
    ttl_policy: str = "review",
) -> MemoryCandidate:
    return MemoryCandidate(
        text=text,
        kind=MemoryKind.NOTE,
        confidence=confidence,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id="static-extractor-test",
                quote_preview=quote if quote is not None else text,
            ),
        ),
        safe_reason="static extractor test",
        operation_hint=operation,
        target_fact_id=target_fact_id,
        target_fact_version=target_fact_version,
        target_hint=target_hint,
        tags=("test",),
        ttl_policy=ttl_policy,
    )


def _create_capture(
    client: TestClient,
    *,
    headers: dict[str, str],
    space_slug: str,
    marker: str,
    trust_level: str = "medium",
    source_authority: str = "user_statement",
    sensitivity: str = "medium",
):
    return client.post(
        "/v1/captures",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "source_agent": "codex",
            "source_kind": "hook",
            "event_type": "UserPromptSubmit",
            "actor_role": "user",
            "source_event_id": marker,
            "text": f"Remember: {marker}.",
            "trust_level": trust_level,
            "source_authority": source_authority,
            "sensitivity": sensitivity,
            "consolidate": True,
        },
        headers=headers,
    )


def _list_suggestions(
    client: TestClient,
    *,
    headers: dict[str, str],
    space_slug: str,
):
    return client.get(
        "/v1/suggestions",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": "pending",
        },
        headers=headers,
    )


def _list_facts(
    client: TestClient,
    *,
    headers: dict[str, str],
    space_slug: str,
):
    return client.get(
        "/v1/facts",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": "active",
        },
        headers=headers,
    )


def _capture_app(tmp_path: Path, database_name: str, *, capture_mode: CaptureMode):
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / database_name}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=capture_mode,
        )
    )


def _consolidate_with_extractor(
    client: TestClient,
    *,
    capture_id: str,
    extractor,
    auto_apply_safe_enabled: bool,
):
    container = client.app.state.container
    use_case = ConsolidateCaptureUseCase(
        uow_factory=container.uow_factory,
        clock=container.clock,
        ids=container.ids,
        extractor=extractor,
        auto_apply_safe_enabled=auto_apply_safe_enabled,
    )
    return asyncio.run(use_case.execute(ConsolidateCaptureCommand(capture_id=capture_id)))
