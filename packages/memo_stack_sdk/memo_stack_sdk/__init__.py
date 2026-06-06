"""Small HTTP SDK for Memo Stack Core Lite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


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
class MemoryScope:
    space_id: str | None = None
    profile_id: str | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    profile_external_ref: str | None = None
    thread_external_ref: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = _single_scope_body(
            space_id=self.space_id,
            profile_id=self.profile_id,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            profile_external_ref=self.profile_external_ref,
            thread_external_ref=self.thread_external_ref,
        )
        _validate_single_scope_payload(payload)
        return payload


@dataclass(frozen=True)
class ReadScope:
    space_id: str | None = None
    profile_ids: tuple[str, ...] | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    profile_external_ref: str | None = None
    profile_external_refs: tuple[str, ...] | None = None
    thread_external_ref: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = _context_scope_payload(
            space_id=self.space_id,
            profile_ids=list(self.profile_ids) if self.profile_ids is not None else None,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            profile_external_ref=self.profile_external_ref,
            profile_external_refs=(
                list(self.profile_external_refs)
                if self.profile_external_refs is not None
                else None
            ),
            thread_external_ref=self.thread_external_ref,
        )
        _validate_read_scope_payload(payload)
        return payload


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
        return self._request(
            "POST",
            "/v1/facts",
            json=_without_none(
                {
                    **scope_payload,
                    "text": text,
                    "kind": kind,
                    "source_refs": source_refs,
                    "classification": classification,
                }
            ),
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
        limit: int = 100,
    ) -> dict[str, Any]:
        params = _without_none(
            {
                "space_id": space_id,
                "profile_id": profile_id,
                "space_slug": space_slug,
                "profile_external_ref": profile_external_ref,
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


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _single_scope_body(
    *,
    space_id: str | None,
    profile_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return _without_none(
        {
            "space_id": space_id,
            "profile_id": profile_id,
            "thread_id": thread_id,
            "space_slug": space_slug,
            "profile_external_ref": profile_external_ref,
            "thread_external_ref": thread_external_ref,
        }
    )


def _context_scope_payload(
    *,
    space_id: str | None,
    profile_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    profile_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return _without_none(
        {
            "space_id": space_id,
            "profile_ids": profile_ids,
            "thread_id": thread_id,
            "space_slug": space_slug,
            "profile_external_ref": profile_external_ref,
            "profile_external_refs": profile_external_refs,
            "thread_external_ref": thread_external_ref,
        }
    )


def _context_body(
    *,
    scope_payload: dict[str, Any] | None,
    space_id: str | None,
    profile_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    profile_external_refs: list[str] | None,
    thread_external_ref: str | None,
    query: str,
    token_budget: int,
    max_facts: int,
    max_chunks: int,
) -> dict[str, Any]:
    payload = scope_payload or _context_scope_payload(
        space_id=space_id,
        profile_ids=profile_ids,
        thread_id=thread_id,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        profile_external_refs=profile_external_refs,
        thread_external_ref=thread_external_ref,
    )
    return {
        **payload,
        "query": query,
        "token_budget": token_budget,
        "max_facts": max_facts,
        "max_chunks": max_chunks,
    }


def _context_scope_body(
    *,
    space_id: str | None,
    profile_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    profile_external_refs: list[str] | None,
    thread_external_ref: str | None,
    query: str,
    token_budget: int,
    max_facts: int,
    max_chunks: int,
) -> dict[str, Any]:
    return _without_none(
        {
            **_context_scope_payload(
                space_id=space_id,
                profile_ids=profile_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
                thread_external_ref=thread_external_ref,
            ),
            "query": query,
            "token_budget": token_budget,
            "max_facts": max_facts,
            "max_chunks": max_chunks,
        }
    )


def _validate_single_scope_payload(payload: dict[str, Any]) -> None:
    canonical = any(payload.get(key) for key in ("space_id", "profile_id", "thread_id"))
    external = any(
        payload.get(key) for key in ("space_slug", "profile_external_ref", "thread_external_ref")
    )
    if canonical and external:
        raise ValueError("Use either canonical ids or external refs, not both")
    if canonical and (not payload.get("space_id") or not payload.get("profile_id")):
        raise ValueError("space_id and profile_id are required with canonical scope")


def _validate_read_scope_payload(payload: dict[str, Any]) -> None:
    profile_ids = payload.get("profile_ids")
    raw_external_refs = []
    if payload.get("profile_external_ref"):
        raw_external_refs.append(payload["profile_external_ref"])
    raw_external_refs.extend(payload.get("profile_external_refs") or ())
    external_refs = tuple(ref for ref in raw_external_refs if isinstance(ref, str))
    canonical = any(payload.get(key) for key in ("space_id", "profile_ids", "thread_id"))
    external = any(
        payload.get(key)
        for key in (
            "space_slug",
            "profile_external_ref",
            "profile_external_refs",
            "thread_external_ref",
        )
    )
    if canonical and external:
        raise ValueError("Use profile_ids/thread_id or external profile refs, not both")
    if profile_ids is not None:
        if not isinstance(profile_ids, list) or not profile_ids:
            raise ValueError("profile_ids must be a non-empty list")
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("profile_ids must be unique")
        if not payload.get("space_id"):
            raise ValueError("space_id is required with profile_ids")
    if external_refs and len(set(external_refs)) != len(external_refs):
        raise ValueError("profile_external_refs must be unique")
    if payload.get("thread_external_ref") and len(external_refs) > 1:
        raise ValueError("thread_external_ref supports a single profile for context")


__all__ = ["MemoStackClient", "MemoStackError", "MemoryScope", "ReadScope"]
