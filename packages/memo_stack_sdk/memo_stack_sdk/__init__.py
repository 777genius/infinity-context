"""Small HTTP SDK for Memo Stack Core Lite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from memo_stack_sdk._payloads import (
    context_body as _context_body,
)
from memo_stack_sdk._payloads import (
    context_scope_payload as _context_scope_payload,
)
from memo_stack_sdk._payloads import (
    single_scope_body as _single_scope_body,
)
from memo_stack_sdk._payloads import (
    validate_read_scope_payload as _validate_read_scope_payload,
)
from memo_stack_sdk._payloads import (
    without_none as _without_none,
)
from memo_stack_sdk.scopes import MemoryScope, ReadScope


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
class MemoStackClient:
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

    def create_profile(
        self,
        *,
        space_id: str,
        external_ref: str,
        name: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/profiles",
            json={
                "space_id": space_id,
                "external_ref": external_ref,
                "name": name,
            },
        )

    def list_profiles(self, *, space_id: str) -> dict[str, Any]:
        return self._request("GET", "/v1/profiles", params={"space_id": space_id})

    def remember_fact(
        self,
        *,
        scope: MemoryScope | None = None,
        space_id: str | None = None,
        profile_id: str | None = None,
        text: str,
        source_refs: list[dict[str, Any]],
        kind: str = "note",
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
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
            else _single_scope_body(
                space_id=space_id,
                profile_id=profile_id,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
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
            json=_without_none(payload),
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
        profile_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_id: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "active",
        category: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = _without_none(
            {
                "space_id": space_id,
                "profile_id": profile_id,
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
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

    def diagnostics_profile(self, profile_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/diagnostics/profile/{profile_id}")

    def build_insights(
        self,
        *,
        scope: ReadScope | None = None,
        space_id: str | None = None,
        profile_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        max_facts: int = 200,
        max_documents: int = 100,
        max_suggestions: int = 100,
        max_captures: int = 100,
    ) -> dict[str, Any]:
        scope_payload = (
            scope.to_payload()
            if scope is not None
            else _context_scope_payload(
                space_id=space_id,
                profile_ids=profile_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
                thread_external_ref=thread_external_ref,
            )
        )
        _validate_read_scope_payload(scope_payload)
        return self._request(
            "POST",
            "/v1/insights",
            json={
                **scope_payload,
                "max_facts": max_facts,
                "max_documents": max_documents,
                "max_suggestions": max_suggestions,
                "max_captures": max_captures,
            },
        )

    def export_profile_snapshot(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
        redacted: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/export/profile-snapshot",
            params={
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
                "redacted": redacted,
            },
        )

    def import_profile_snapshot(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        dry_run: bool = True,
        merge_strategy: str = "fail_on_conflict",
        confirmed: bool = False,
        source_name: str = "sdk-profile-snapshot",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
                "snapshot": snapshot,
                "manifest": manifest,
                "dry_run": dry_run,
                "merge_strategy": merge_strategy,
                "confirmed": confirmed,
                "source_name": source_name,
            },
        )

    def preview_profile_snapshot_import(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        merge_strategy: str = "fail_on_conflict",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/export/profile-snapshot/preview",
            json={
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
                "snapshot": snapshot,
                "manifest": manifest,
                "merge_strategy": merge_strategy,
            },
        )

    def ingest_document(
        self,
        *,
        space_id: str | None = None,
        profile_id: str | None = None,
        title: str,
        text: str,
        source_external_id: str,
        source_type: str = "document",
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        idempotency_key: str | None = None,
        classification: str = "unknown",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/documents",
            json=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
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
        profile_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
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
            json=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
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
        profile_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
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
            json=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "thread_id": thread_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
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
        profile_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        status: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/captures",
            params=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
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
        profile_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/diagnostics/captures",
            params=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
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
        profile_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
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
            json=_context_body(
                scope_payload=scope_payload,
                space_id=space_id,
                profile_ids=profile_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
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
        profile_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
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
            json=_context_body(
                scope_payload=scope_payload,
                space_id=space_id,
                profile_ids=profile_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
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
        profile_ids: list[str] | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
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
        payload = scope_payload or _context_scope_payload(
            space_id=space_id,
            profile_ids=profile_ids,
            thread_id=thread_id,
            space_slug=space_slug,
            profile_external_ref=profile_external_ref,
            profile_external_refs=profile_external_refs,
            thread_external_ref=thread_external_ref,
        )
        return self._request(
            "POST",
            "/v1/digest",
            json=_without_none(
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

    def thread_memory_status(
        self,
        *,
        space_id: str | None = None,
        profile_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/thread-memory/status",
            json=_single_scope_body(
                space_id=space_id,
                profile_id=profile_id,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                thread_external_ref=thread_external_ref,
            ),
        )

    def delete_thread_memory(
        self,
        *,
        space_id: str | None = None,
        profile_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "DELETE",
            "/v1/thread-memory",
            json=_single_scope_body(
                space_id=space_id,
                profile_id=profile_id,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                thread_external_ref=thread_external_ref,
            ),
        )

    def create_suggestion(
        self,
        *,
        space_id: str | None = None,
        profile_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
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
        review_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/suggestions",
            json=_without_none(
                {
                    "space_id": space_id,
                    "profile_id": profile_id,
                    "space_slug": space_slug,
                    "profile_external_ref": profile_external_ref,
                    "candidate_text": candidate_text,
                    "safe_reason": safe_reason,
                    "kind": kind,
                    "source_refs": source_refs or [],
                    "trust_level": trust_level,
                    "confidence": confidence,
                    "target_fact_id": target_fact_id,
                    "target_fact_version": target_fact_version,
                    "operation": operation,
                    "category": category,
                    "tags": tags or [],
                    "ttl_policy": ttl_policy,
                    "review_payload": review_payload,
                }
            ),
        )

    def list_suggestions(
        self,
        *,
        space_id: str | None = None,
        profile_id: str | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        status: str | None = None,
        operation: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params = _without_none(
            {
                "space_id": space_id,
                "profile_id": profile_id,
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
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
    ) -> dict[str, Any]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers=headers,
            transport=self.transport,
        ) as client:
            try:
                response = client.request(method, path, json=json, params=params)
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


def _to_error(response: httpx.Response) -> MemoStackError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    code = str(error.get("code") or detail.get("code") or "memory.http_error")
    message = str(error.get("message") or response.text or code)
    retryable = bool(error.get("retryable", response.status_code >= 500))
    return MemoStackError(
        status_code=response.status_code,
        code=code,
        message=message,
        retryable=retryable,
    )


__all__ = ["MemoStackClient", "MemoStackError", "MemoryScope", "ReadScope"]
