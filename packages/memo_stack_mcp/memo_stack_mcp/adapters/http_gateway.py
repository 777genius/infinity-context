"""HTTP adapter from MCP tools to the Memo Stack API."""

from __future__ import annotations

from typing import Any

import httpx

from memo_stack_mcp.domain.models import (
    MemoryGatewayError,
    MemoryReadScope,
    MemoryScope,
    SourceRef,
    public_error_code,
    safe_message,
)


class HttpMemoryGateway:
    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/health")

    async def capabilities(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/capabilities")

    async def build_context(
        self,
        *,
        scope: MemoryReadScope,
        query: str,
        token_budget: int,
        max_facts: int,
        max_chunks: int,
        category: str | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        tags_none: list[str] | None = None,
    ) -> dict[str, Any]:
        profile_payload = _read_scope_profile_payload(scope)
        return await self._request(
            "POST",
            "/v1/context",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    **profile_payload,
                    "thread_external_ref": scope.thread_external_ref,
                    "query": query,
                    "token_budget": token_budget,
                    "max_facts": max_facts,
                    "max_chunks": max_chunks,
                    "category": category,
                    "tags_any": tags_any or None,
                    "tags_all": tags_all or None,
                    "tags_none": tags_none or None,
                }
            ),
        )

    async def build_digest(
        self,
        *,
        scope: MemoryReadScope,
        topic: str,
        token_budget: int,
        max_facts: int,
        max_chunks: int,
        max_suggestions: int,
        include_pending_suggestions: bool,
        include_superseded: bool,
        include_related: bool,
    ) -> dict[str, Any]:
        profile_payload = _read_scope_profile_payload(scope)
        return await self._request(
            "POST",
            "/v1/digest",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    **profile_payload,
                    "thread_external_ref": scope.thread_external_ref,
                    "topic": topic,
                    "token_budget": token_budget,
                    "max_facts": max_facts,
                    "max_chunks": max_chunks,
                    "max_suggestions": max_suggestions,
                    "include_pending_suggestions": include_pending_suggestions,
                    "include_superseded": include_superseded,
                    "include_related": include_related,
                }
            ),
        )

    async def build_insights(
        self,
        *,
        scope: MemoryReadScope,
        max_facts: int,
        max_documents: int,
        max_suggestions: int,
        max_captures: int,
    ) -> dict[str, Any]:
        profile_payload = _read_scope_profile_payload(scope)
        return await self._request(
            "POST",
            "/v1/insights",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    **profile_payload,
                    "thread_external_ref": scope.thread_external_ref,
                    "max_facts": max_facts,
                    "max_documents": max_documents,
                    "max_suggestions": max_suggestions,
                    "max_captures": max_captures,
                }
            ),
        )

    async def export_graph(
        self,
        *,
        scope: MemoryScope,
        include_deleted: bool,
        include_restricted: bool,
        max_facts: int,
        max_documents: int,
        max_chunks: int,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/export/graph.json",
            params=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "thread_external_ref": scope.thread_external_ref,
                    "include_deleted": include_deleted,
                    "include_restricted": include_restricted,
                    "max_facts": max_facts,
                    "max_documents": max_documents,
                    "max_chunks": max_chunks,
                }
            ),
        )

    async def export_profile_snapshot(
        self,
        *,
        scope: MemoryScope,
        redacted: bool,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/export/profile-snapshot",
            params={
                "space_slug": scope.space_slug,
                "profile_external_ref": scope.profile_external_ref,
                "redacted": redacted,
            },
        )

    async def import_profile_snapshot(
        self,
        *,
        scope: MemoryScope,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None,
        dry_run: bool,
        merge_strategy: str,
        confirmed: bool,
        source_name: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": scope.space_slug,
                "profile_external_ref": scope.profile_external_ref,
                "snapshot": snapshot,
                "manifest": manifest,
                "dry_run": dry_run,
                "merge_strategy": merge_strategy,
                "confirmed": confirmed,
                "source_name": source_name,
            },
        )

    async def remember_fact(
        self,
        *,
        scope: MemoryScope,
        text: str,
        kind: str,
        source_refs: list[SourceRef],
        classification: str,
        idempotency_key: str,
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/facts",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "thread_external_ref": scope.thread_external_ref,
                    "text": text,
                    "kind": kind,
                    "source_refs": [source.to_payload() for source in source_refs],
                    "classification": classification,
                    "category": category,
                    "tags": tags,
                    "ttl_policy": ttl_policy,
                }
            ),
            idempotency_key=idempotency_key,
        )

    async def list_facts(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        limit: int,
        cursor: str | None,
        category: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/facts",
            params=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "status": status,
                    "category": category,
                    "tag": tag,
                    "limit": limit,
                    "cursor": cursor,
                }
            ),
        )

    async def get_fact(self, *, fact_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/facts/{fact_id}")

    async def list_fact_versions(self, *, fact_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/facts/{fact_id}/versions")

    async def update_fact(
        self,
        *,
        fact_id: str,
        expected_version: int,
        text: str,
        reason: str,
        source_refs: list[SourceRef],
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            f"/v1/facts/{fact_id}",
            json={
                "expected_version": expected_version,
                "text": text,
                "reason": reason,
                "source_refs": [source.to_payload() for source in source_refs],
            },
        )

    async def forget_fact(self, *, fact_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/v1/facts/{fact_id}")

    async def create_suggestion(
        self,
        *,
        scope: MemoryScope,
        candidate_text: str,
        kind: str,
        source_refs: list[SourceRef],
        confidence: str,
        trust_level: str,
        safe_reason: str,
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/suggestions",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "candidate_text": candidate_text,
                    "kind": kind,
                    "source_refs": [source.to_payload() for source in source_refs],
                    "confidence": confidence,
                    "trust_level": trust_level,
                    "safe_reason": safe_reason,
                    "category": category,
                    "tags": tags or [],
                    "ttl_policy": ttl_policy,
                }
            ),
        )

    async def list_suggestions(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/suggestions",
            params=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "status": status,
                    "operation": operation,
                    "category": category,
                    "tag": tag,
                    "limit": limit,
                }
            ),
        )

    async def approve_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
        force: bool,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/approve",
            json=_without_none({"reason": reason, "force": force}),
        )

    async def reject_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/reject",
            json=_without_none({"reason": reason}),
        )

    async def expire_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/suggestions/{suggestion_id}/expire",
            json=_without_none({"reason": reason}),
        )

    async def list_captures(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/captures",
            params=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "status": status,
                    "consolidation_status": consolidation_status,
                    "limit": limit,
                }
            ),
        )

    async def consolidate_capture(
        self,
        *,
        capture_id: str,
        force: bool,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/captures/{capture_id}/consolidate",
            json={"force": force},
        )

    async def ingest_document(
        self,
        *,
        scope: MemoryScope,
        title: str,
        text: str,
        source_type: str,
        source_external_id: str,
        classification: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/documents",
            json=_without_none(
                {
                    "space_slug": scope.space_slug,
                    "profile_external_ref": scope.profile_external_ref,
                    "thread_external_ref": scope.thread_external_ref,
                    "title": title,
                    "text": text,
                    "source_type": source_type,
                    "source_external_id": source_external_id,
                    "classification": classification,
                }
            ),
            idempotency_key=idempotency_key,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            headers=headers,
            transport=self._transport,
        ) as client:
            try:
                response = await client.request(method, path, json=json, params=params)
            except httpx.ConnectTimeout as exc:
                raise MemoryGatewayError(
                    status_code=0,
                    code="memo_stack_mcp.gateway.connect_timeout",
                    message="Memo Stack connection timed out",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            except httpx.ReadTimeout as exc:
                raise MemoryGatewayError(
                    status_code=0,
                    code="memo_stack_mcp.gateway.read_timeout",
                    message="Memo Stack response timed out",
                    retryable=True,
                    unknown_commit_state=method.upper() in {"POST", "PUT", "PATCH", "DELETE"},
                ) from exc
            except httpx.WriteTimeout as exc:
                raise MemoryGatewayError(
                    status_code=0,
                    code="memo_stack_mcp.gateway.write_timeout",
                    message="Memo Stack request body timed out",
                    retryable=True,
                    unknown_commit_state=method.upper() in {"POST", "PUT", "PATCH", "DELETE"},
                ) from exc
            except httpx.TransportError as exc:
                raise MemoryGatewayError(
                    status_code=0,
                    code="memo_stack_mcp.gateway.network_error",
                    message="Memo Stack HTTP request failed",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
        if response.is_error:
            raise _to_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise MemoryGatewayError(
                status_code=response.status_code,
                code="memo_stack_mcp.gateway.invalid_json",
                message="Memo Stack returned invalid JSON",
                retryable=False,
            ) from exc


def _to_error(response: httpx.Response) -> MemoryGatewayError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    raw_code = str(error.get("code") or detail.get("code") or "memo_stack_mcp.gateway.http_error")
    code = public_error_code(raw_code, status_code=response.status_code)
    raw_message = str(error.get("message") or detail.get("message") or response.text or code)
    message = safe_message(raw_message)
    retryable = bool(
        error.get(
            "retryable",
            response.status_code == 429
            or response.status_code >= 500
            or code == "memo_stack_mcp.degraded.backpressure",
        )
    )
    return MemoryGatewayError(
        status_code=response.status_code,
        code=code,
        message=message,
        retryable=retryable,
    )


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _read_scope_profile_payload(scope: MemoryReadScope) -> dict[str, Any]:
    if len(scope.profile_external_refs) == 1:
        return {"profile_external_ref": scope.profile_external_refs[0]}
    return {"profile_external_refs": list(scope.profile_external_refs)}
