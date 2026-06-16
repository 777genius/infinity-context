"""Asset and extraction helpers for the public Memo Stack SDK."""

from __future__ import annotations

from typing import Any

import memo_stack_sdk._payloads as _payloads


class MemoStackAssetsMixin:
    def upload_asset(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        classification: str = "unknown",
        extract: bool = False,
        parser_profile: str | None = None,
    ) -> dict[str, Any]:
        params = _payloads.without_none(
            {
                **_payloads.single_scope_body(
                    space_id=space_id,
                    memory_scope_id=memory_scope_id,
                    thread_id=thread_id,
                    space_slug=space_slug,
                    memory_scope_external_ref=memory_scope_external_ref,
                    thread_external_ref=thread_external_ref,
                ),
                "filename": filename,
                "content_type": content_type,
                "classification": classification,
                "extract": extract,
                "parser_profile": parser_profile,
            }
        )
        headers = {"Content-Type": content_type} if content_type else None
        return self._request(
            "POST",
            "/v1/assets",
            params=params,
            content=content,
            headers=headers,
        )

    def list_assets(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "stored",
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/assets",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=thread_id,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=thread_external_ref,
                    ),
                    "status": status,
                    "limit": limit,
                }
            ),
        )

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/assets/{asset_id}")

    def delete_asset(self, asset_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/assets/{asset_id}")

    def download_asset(self, asset_id: str) -> bytes:
        return self._request_bytes("GET", f"/v1/assets/{asset_id}/download")

    def request_asset_extraction(
        self,
        asset_id: str,
        *,
        parser_profile: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/assets/{asset_id}/extractions",
            params=_payloads.without_none({"parser_profile": parser_profile}),
        )

    def list_asset_extractions(
        self,
        asset_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/assets/{asset_id}/extractions",
            params=_payloads.without_none({"status": status, "limit": limit}),
        )

    def list_scope_asset_extractions(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/asset-extractions",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=thread_id,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=thread_external_ref,
                    ),
                    "status": status,
                    "limit": limit,
                }
            ),
        )

    def get_asset_extraction(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/asset-extractions/{job_id}")

    def retry_asset_extraction(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/asset-extractions/{job_id}/retry")

    def cancel_asset_extraction(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/asset-extractions/{job_id}/cancel")

    def get_operations_console(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/operations-console",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=thread_id,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=thread_external_ref,
                    ),
                    "limit": limit,
                }
            ),
        )

    def get_memory_browser(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        limit: int = 50,
        fact_status: str | None = "active",
        episode_status: str | None = "active",
        document_status: str | None = "active",
        chunk_status: str | None = "active",
        extraction_status: str | None = None,
        thread_status: str | None = "active",
        capture_status: str | None = None,
        asset_status: str | None = "stored",
        anchor_status: str | None = "active",
        link_status: str | None = None,
        suggestion_status: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/memory-browser",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=None,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=None,
                    ),
                    "limit": limit,
                    "fact_status": fact_status,
                    "episode_status": episode_status,
                    "document_status": document_status,
                    "chunk_status": chunk_status,
                    "extraction_status": extraction_status,
                    "thread_status": thread_status,
                    "capture_status": capture_status,
                    "asset_status": asset_status,
                    "anchor_status": anchor_status,
                    "link_status": link_status,
                    "suggestion_status": suggestion_status,
                }
            ),
        )

    def download_extraction_artifact(self, artifact_id: str) -> bytes:
        return self._request_bytes(
            "GET",
            f"/v1/extraction-artifacts/{artifact_id}/download",
        )

    def suggest_context_links(
        self,
        *,
        text: str = "",
        source_type: str | None = None,
        source_id: str | None = None,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        thread_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        limit: int = 10,
        persist: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/link-suggestions",
            json=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=thread_id,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=thread_external_ref,
                    ),
                    "text": text,
                    "source_type": source_type,
                    "source_id": source_id,
                    "limit": limit,
                    "persist": persist,
                }
            ),
        )

    def list_context_links(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = "active",
        statuses: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        status_param = status if statuses is None else None
        return self._request(
            "GET",
            "/v1/context-links",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=None,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=None,
                    ),
                    "source_type": source_type,
                    "source_id": source_id,
                    "status": status_param,
                    "statuses": statuses,
                    "limit": limit,
                }
            ),
        )

    def create_context_link(
        self,
        *,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        reason: str,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        relation_type: str = "related_to",
        confidence: str = "medium",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/context-links",
            json=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=None,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=None,
                    ),
                    "source_type": source_type,
                    "source_id": source_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "confidence": confidence,
                    "reason": reason,
                    "metadata": metadata,
                }
            ),
        )

    def delete_context_link(self, context_link_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/context-links/{context_link_id}")

    def update_context_link(
        self,
        context_link_id: str,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        confidence: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/context-links/{context_link_id}",
            json=_payloads.without_none(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "confidence": confidence,
                    "reason": reason,
                    "metadata": metadata,
                }
            ),
        )

    def list_context_link_suggestions(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = "pending",
        statuses: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        status_param = status if statuses is None else None
        return self._request(
            "GET",
            "/v1/context-link-suggestions",
            params=_payloads.without_none(
                {
                    **_payloads.single_scope_body(
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        thread_id=None,
                        space_slug=space_slug,
                        memory_scope_external_ref=memory_scope_external_ref,
                        thread_external_ref=None,
                    ),
                    "source_type": source_type,
                    "source_id": source_id,
                    "status": status_param,
                    "statuses": statuses,
                    "limit": limit,
                }
            ),
        )

    def review_context_link_suggestion(
        self,
        suggestion_id: str,
        *,
        action: str,
        reason: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        confidence: str | None = None,
        link_reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/context-link-suggestions/{suggestion_id}/review",
            json=_payloads.without_none(
                {
                    "action": action,
                    "reason": reason,
                    "target_type": target_type,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "confidence": confidence,
                    "link_reason": link_reason,
                }
            ),
        )

    def review_context_link_suggestions_batch(
        self,
        items: list[dict[str, Any]],
        *,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/context-link-suggestions/review-batch",
            json={"items": items, "continue_on_error": continue_on_error},
        )
