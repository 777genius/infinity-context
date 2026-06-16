"""Semantic anchor helpers for the public Memo Stack SDK."""

from __future__ import annotations

from typing import Any

import memo_stack_sdk._payloads as _payloads


class MemoStackAnchorsMixin:
    def create_anchor(
        self,
        *,
        kind: str,
        label: str,
        aliases: list[str] | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/anchors",
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
                    "kind": kind,
                    "label": label,
                    "aliases": aliases or [],
                    "description": description,
                    "metadata": metadata or {},
                }
            ),
        )

    def list_anchors(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        kind: str | None = None,
        status: str | None = "active",
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/anchors",
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
                    "kind": kind,
                    "status": status,
                    "limit": limit,
                }
            ),
        )

    def update_anchor(
        self,
        anchor_id: str,
        *,
        label: str | None = None,
        aliases: list[str] | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/anchors/{anchor_id}",
            json=_payloads.without_none(
                {
                    "label": label,
                    "aliases": aliases or [],
                    "description": description,
                    "metadata": metadata or {},
                }
            ),
        )

    def delete_anchor(
        self,
        anchor_id: str,
        *,
        reason: str = "manual delete",
    ) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/v1/anchors/{anchor_id}",
            json={"reason": reason},
        )

    def backfill_anchors(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        limit_per_source: int = 100,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/anchors/backfill",
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
                    "limit_per_source": limit_per_source,
                }
            ),
        )

    def list_anchor_merge_suggestions(
        self,
        *,
        space_id: str | None = None,
        memory_scope_id: str | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/anchors/merge-suggestions",
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
                    "kind": kind,
                    "limit": limit,
                }
            ),
        )

    def merge_anchor(
        self,
        source_anchor_id: str,
        *,
        target_anchor_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/anchors/{source_anchor_id}/merge",
            json={"target_anchor_id": target_anchor_id, "reason": reason},
        )

    def split_anchor(
        self,
        anchor_id: str,
        *,
        alias: str,
        new_label: str | None = None,
        reason: str = "manual split",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/anchors/{anchor_id}/split",
            json=_payloads.without_none(
                {
                    "alias": alias,
                    "new_label": new_label,
                    "reason": reason,
                }
            ),
        )
