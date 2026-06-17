"""Small HTTP SDK for Memo Stack Core Lite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from memo_stack_core.application.sensitive_text import redact_sensitive_text

import memo_stack_sdk._payloads as _payloads
from memo_stack_sdk.anchors import MemoStackAnchorsMixin
from memo_stack_sdk.assets import MemoStackAssetsMixin
from memo_stack_sdk.export import MemoStackExportMixin
from memo_stack_sdk.scopes import MemoryScope, ReadScope
from memo_stack_sdk.thread_memory import MemoStackThreadMemoryMixin


class MemoStackError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MemoStackClient(
    MemoStackAnchorsMixin,
    MemoStackAssetsMixin,
    MemoStackExportMixin,
    MemoStackThreadMemoryMixin,
):
    base_url: str = "http://127.0.0.1:7788"
    token: str | None = None
    timeout: float = 10.0
    transport: httpx.BaseTransport | None = None

    def create_space(self, *, slug: str, name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/spaces",
            json={"slug": slug, "name": name},
        )

    def list_spaces(self) -> dict[str, Any]:
        return self._request("GET", "/v1/spaces")

    def create_memory_scope(
        self,
        *,
        space_id: str,
        external_ref: str,
        name: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memory-scopes",
            json={
                "space_id": space_id,
                "external_ref": external_ref,
                "name": name,
            },
        )

    def list_memory_scopes(self, *, space_id: str) -> dict[str, Any]:
        return self._request("GET", "/v1/memory-scopes", params={"space_id": space_id})

    def remember_fact(
        self,
        *,
        scope: MemoryScope | None = None,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        text: str,
        source_refs: list[dict[str, Any]],
        kind: str = "note",
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        idempotency_key: str | None = None,
        classification: str = "internal",
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
    ) -> dict[str, Any]:
        scope_payload = (
            scope.to_payload()
            if scope is not None
                else _payloads.single_scope_body(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=thread_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
            )
        )
        payload = {
            **scope_payload,
            "text": text,
            "kind": kind,
            "source_refs": source_refs,
            "classification": classification,
            "category": category,
            "ttl_policy": ttl_policy,
        }
        if tags is not None:
            payload["tags"] = tags

        return self._request(
            "POST",
            "/v1/facts",
            json=_payloads.without_none(payload),
            idempotency_key=idempotency_key,
        )

    def update_fact(
        self,
        fact_id: str,
        *,
        expected_version: int,
        text: str,
        reason: str,
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": expected_version,
                "text": text,
                "reason": reason,
                "source_refs": source_refs,
            },
        )

    def forget_fact(self, fact_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/facts/{fact_id}")

    def get_fact(self, fact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/facts/{fact_id}")

    def get_related_facts(
        self,
        fact_id: str,
        *,
        limit: int = 10,
        include_other_threads: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/facts/{fact_id}/related",
            params={
                "limit": limit,
                "include_other_threads": include_other_threads,
            },
        )

    def link_facts(
        self,
        source_fact_id: str,
        *,
        target_fact_id: str,
        relation_type: str = "related_to",
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/facts/{source_fact_id}/relations",
            json={
                "target_fact_id": target_fact_id,
                "relation_type": relation_type,
                "reason": reason,
            },
        )

    def list_fact_relations(
        self,
        fact_id: str,
        *,
        status: str | None = "active",
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        return self._request("GET", f"/v1/facts/{fact_id}/relations", params=params)

    def unlink_fact_relation(self, relation_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/facts/relations/{relation_id}")

    def list_fact_versions(self, fact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/facts/{fact_id}/versions")

    def list_facts(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_id: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "active",
        category: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = _payloads.without_none(
            {
                "space_id": space_id,
                "memory_scope_id": memory_scope_id,
                "space_slug": space_slug,
                "memory_scope_external_ref": memory_scope_external_ref,
                "thread_id": thread_id,
                "thread_external_ref": thread_external_ref,
                "category": category,
                "tag": tag,
                "limit": limit,
            }
        )
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/v1/facts", params=params)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def capability_diagnostics(self) -> dict[str, Any]:
        payload = self.capabilities()
        return {
            "capabilities": payload.get("capabilities", []),
            "adapters": payload.get("adapters", {}),
            "enabled_adapters": payload.get("enabled_adapters", []),
            "policy_mode": payload.get("policy_mode"),
            "limits": payload.get("limits", {}),
            "captures": payload.get("captures", {}),
            "suggestions": payload.get("suggestions", {}),
            "extraction": payload.get("extraction", {}),
            "plans": payload.get("plans", {}),
        }

    def diagnostics_adapters(self) -> dict[str, Any]:
        return self._request("GET", "/v1/diagnostics/adapters")

    def diagnostics_outbox(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/v1/diagnostics/outbox", params=params)

    def diagnostics_memory_scope(self, memory_scope_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/diagnostics/memory-scope/{memory_scope_id}")

    def build_insights(
        self,
        *,
        scope: ReadScope | None = None,
        space_id: str | None = None,
        memory_scope_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        max_facts: int = 200,
        max_documents: int = 100,
        max_episodes: int = 100,
        max_suggestions: int = 100,
        max_captures: int = 100,
        max_activity: int = 50,
    ) -> dict[str, Any]:
        scope_payload = (
            scope.to_payload()
            if scope is not None
            else _payloads.context_scope_payload(
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
                thread_external_ref=thread_external_ref,
            )
        )
        _payloads.validate_read_scope_payload(scope_payload)
        return self._request(
            "POST",
            "/v1/insights",
            json={
                **scope_payload,
                "max_facts": max_facts,
                "max_documents": max_documents,
                "max_episodes": max_episodes,
                "max_suggestions": max_suggestions,
                "max_captures": max_captures,
                "max_activity": max_activity,
            },
        )

    def ingest_document(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        title: str,
        text: str,
        source_external_id: str,
        source_type: str = "document",
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        idempotency_key: str | None = None,
        classification: str = "unknown",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/documents",
            json=_payloads.without_none(
                {
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "memory_scope_external_ref": memory_scope_external_ref,
                    "thread_external_ref": thread_external_ref,
                    "title": title,
                    "text": text,
                    "source_type": source_type,
                    "source_external_id": source_external_id,
                    "classification": classification,
                }
            ),
            idempotency_key=idempotency_key,
        )

    def ingest_episode(
        self,
        *,
        source_external_id: str,
        text: str,
        source_type: str = "unknown",
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        occurred_at: str | None = None,
        speaker: str | None = None,
        trust_level: str = "medium",
        kind_hint: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/episodes",
            json=_payloads.without_none(
                {
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "memory_scope_external_ref": memory_scope_external_ref,
                    "thread_external_ref": thread_external_ref,
                    "source_type": source_type,
                    "source_external_id": source_external_id,
                    "text": text,
                    "occurred_at": occurred_at,
                    "speaker": speaker,
                    "trust_level": trust_level,
                    "kind_hint": kind_hint,
                    "language": language,
                    "metadata": metadata,
                    "idempotency_key": idempotency_key,
                }
            ),
        )

    def create_capture(
        self,
        *,
        source_agent: str,
        event_type: str,
        text: str,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_kind: str = "hook",
        actor_role: str = "unknown",
        source_event_id: str | None = None,
        client_instance_id: str | None = None,
        source_actor_external_ref: str | None = None,
        agent_session_external_ref: str | None = None,
        turn_external_ref: str | None = None,
        parent_capture_id: str | None = None,
        sequence_index: int | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        trust_level: str = "medium",
        source_authority: str = "unknown",
        sensitivity: str = "medium",
        data_classification: str = "internal",
        occurred_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        consolidate: bool | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/captures",
            json=_payloads.without_none(
                {
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "memory_scope_external_ref": memory_scope_external_ref,
                    "thread_external_ref": thread_external_ref,
                    "source_agent": source_agent,
                    "source_kind": source_kind,
                    "event_type": event_type,
                    "actor_role": actor_role,
                    "text": text,
                    "source_event_id": source_event_id,
                    "source_actor_external_ref": source_actor_external_ref,
                    "client_instance_id": client_instance_id,
                    "agent_session_external_ref": agent_session_external_ref,
                    "turn_external_ref": turn_external_ref,
                    "parent_capture_id": parent_capture_id,
                    "sequence_index": sequence_index,
                    "evidence_refs": evidence_refs or [],
                    "trust_level": trust_level,
                    "source_authority": source_authority,
                    "sensitivity": sensitivity,
                    "data_classification": data_classification,
                    "occurred_at": occurred_at,
                    "metadata": metadata,
                    "trace_id": trace_id,
                    "idempotency_key": idempotency_key,
                    "consolidate": consolidate,
                }
            ),
        )

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/captures/{capture_id}")

    def list_captures(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        status: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/captures",
            params=_payloads.without_none(
                {
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "space_slug": space_slug,
                    "memory_scope_external_ref": memory_scope_external_ref,
                    "status": status,
                    "consolidation_status": consolidation_status,
                    "limit": limit,
                }
            ),
        )

    def consolidate_capture(self, capture_id: str, *, force: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/captures/{capture_id}/consolidate",
            json={"force": force},
        )

    def purge_capture(
        self,
        capture_id: str,
        *,
        reason: str = "privacy_purge",
    ) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/v1/captures/{capture_id}",
            json={"reason": reason},
        )

    def capture_diagnostics(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/diagnostics/captures",
            params=_payloads.without_none(
                {
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "space_slug": space_slug,
                    "memory_scope_external_ref": memory_scope_external_ref,
                    "consolidation_status": consolidation_status,
                    "limit": limit,
                }
            ),
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/documents/{document_id}")

    def list_document_chunks(
        self,
        document_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", f"/v1/documents/{document_id}/chunks", params=params)

    def process_document(
        self,
        document_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/documents/{document_id}/process",
            idempotency_key=idempotency_key,
        )

    def delete_document(self, document_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/documents/{document_id}")

    def build_context(
        self,
        *,
        query: str,
        read_scope: ReadScope | None = None,
        space_id: str | None = None,
        memory_scope_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        token_budget: int = 1800,
        max_facts: int = 20,
        max_chunks: int = 30,
        category: str | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        tags_none: list[str] | None = None,
    ) -> dict[str, Any]:
        scope_payload = read_scope.to_payload() if read_scope is not None else None
        return self._request(
            "POST",
            "/v1/context",
            json=_payloads.context_body(
                scope_payload=scope_payload,
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
                thread_external_ref=thread_external_ref,
                query=query,
                token_budget=token_budget,
                max_facts=max_facts,
                max_chunks=max_chunks,
                category=category,
                tags_any=tags_any,
                tags_all=tags_all,
                tags_none=tags_none,
            ),
        )

    def search(
        self,
        *,
        query: str,
        read_scope: ReadScope | None = None,
        space_id: str | None = None,
        memory_scope_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        token_budget: int = 1800,
        max_facts: int = 20,
        max_chunks: int = 30,
        category: str | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        tags_none: list[str] | None = None,
    ) -> dict[str, Any]:
        scope_payload = read_scope.to_payload() if read_scope is not None else None
        return self._request(
            "POST",
            "/v1/search",
            json=_payloads.context_body(
                scope_payload=scope_payload,
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
                thread_external_ref=thread_external_ref,
                query=query,
                token_budget=token_budget,
                max_facts=max_facts,
                max_chunks=max_chunks,
                category=category,
                tags_any=tags_any,
                tags_all=tags_all,
                tags_none=tags_none,
            ),
        )

    def build_digest(
        self,
        *,
        topic: str,
        read_scope: ReadScope | None = None,
        space_id: str | None = None,
        memory_scope_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        token_budget: int = 2400,
        max_facts: int = 20,
        max_chunks: int = 20,
        max_suggestions: int = 10,
        include_pending_suggestions: bool = True,
        include_superseded: bool = False,
        include_related: bool = True,
        format: str = "markdown",
    ) -> dict[str, Any]:
        scope_payload = read_scope.to_payload() if read_scope is not None else None
        payload = scope_payload or _payloads.context_scope_payload(
            space_id=space_id,
            memory_scope_ids=memory_scope_ids,
            thread_id=thread_id,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            memory_scope_external_refs=memory_scope_external_refs,
            thread_external_ref=thread_external_ref,
        )
        return self._request(
            "POST",
            "/v1/digest",
            json=_payloads.without_none(
                {
                    **payload,
                    "topic": topic,
                    "token_budget": token_budget,
                    "max_facts": max_facts,
                    "max_chunks": max_chunks,
                    "max_suggestions": max_suggestions,
                    "include_pending_suggestions": include_pending_suggestions,
                    "include_superseded": include_superseded,
                    "include_related": include_related,
                    "format": format,
                }
            ),
        )

    def create_suggestion(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        candidate_text: str,
        safe_reason: str,
        kind: str = "note",
        source_refs: list[dict[str, Any]] | None = None,
        trust_level: str = "medium",
        confidence: str = "medium",
        target_fact_id: str | None = None,
        target_fact_version: int | None = None,
        operation: str = "add",
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
        candidate_fingerprint: str | None = None,
        review_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/suggestions",
            json=_payloads.suggestion_body(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                candidate_text=candidate_text,
                safe_reason=safe_reason,
                kind=kind,
                source_refs=source_refs,
                trust_level=trust_level,
                confidence=confidence,
                target_fact_id=target_fact_id,
                target_fact_version=target_fact_version,
                operation=operation,
                category=category,
                tags=tags,
                ttl_policy=ttl_policy,
                candidate_fingerprint=candidate_fingerprint,
                review_payload=review_payload,
            ),
        )

    def create_suggestions_batch(
        self, *, items: list[dict[str, Any]], space_id: str | None = None,
        memory_scope_id: str | None = None, space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/suggestions/batch",
            json=_payloads.suggestions_batch_body(
                items=items,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                continue_on_error=continue_on_error,
            ),
        )

    def list_suggestions(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        status: str | None = None,
        operation: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params = _payloads.without_none(
            {
                "space_id": space_id,
                "memory_scope_id": memory_scope_id,
                "space_slug": space_slug,
                "memory_scope_external_ref": memory_scope_external_ref,
                "operation": operation,
                "category": category,
                "tag": tag,
                "limit": limit,
            }
        )
        if status is not None:
            params["status"] = status
        return self._request("GET", "/v1/suggestions", params=params)

    def approve_suggestion(
        self,
        suggestion_id: str,
        *,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": reason, "force": force},
        )

    def review_suggestions_batch(
        self,
        items: list[dict[str, Any]],
        *,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/suggestions/review-batch",
            json={"items": items, "continue_on_error": continue_on_error},
        )

    def reject_suggestion(self, suggestion_id: str, *, reason: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/reject",
            json={"reason": reason},
        )

    def expire_suggestion(self, suggestion_id: str, *, reason: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/expire",
            json={"reason": reason},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {}
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
        if headers:
            request_headers.update(headers)
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers=request_headers,
            transport=self.transport,
        ) as client:
            try:
                response = client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    content=content,
                )
            except httpx.TransportError as exc:
                raise MemoStackError(
                    status_code=0,
                    code="memory.network_error",
                    message="Memo Stack request failed",
                    retryable=True,
                ) from exc
            if response.is_error:
                raise _to_error(response)
            return response.json()

    def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers=headers,
            transport=self.transport,
        ) as client:
            try:
                response = client.request(method, path, params=params)
            except httpx.TransportError as exc:
                raise MemoStackError(
                    status_code=0,
                    code="memory.network_error",
                    message="Memo Stack request failed",
                    retryable=True,
                ) from exc
            if response.is_error:
                raise _to_error(response)
            return response.content


def _to_error(response: httpx.Response) -> MemoStackError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    code = str(error.get("code") or detail.get("code") or "memory.http_error")
    message = _safe_error_message(str(error.get("message") or response.text or code))
    retryable = bool(error.get("retryable", response.status_code >= 500))
    return MemoStackError(
        status_code=response.status_code,
        code=code,
        message=message,
        retryable=retryable,
    )


def _safe_error_message(value: str) -> str:
    return redact_sensitive_text(value.strip() or "Memo Stack request failed")[:500]


__all__ = ["MemoStackClient", "MemoStackError", "MemoryScope", "ReadScope"]
