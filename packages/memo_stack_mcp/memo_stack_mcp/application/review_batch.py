"""Review batch input normalization for MCP tools."""

from __future__ import annotations

from typing import Any

from memo_stack_mcp.domain.models import MemoryGatewayError


def normalize_review_batch_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise _invalid("items must be a non-empty list")
    if len(items) > 50:
        raise MemoryGatewayError(
            status_code=400,
            code="memo_stack_mcp.validation.input_too_large",
            message="items supports at most 50 entries",
            retryable=False,
        )
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise _invalid("each item must be an object")
        suggestion_id = str(item.get("suggestion_id") or "").strip()
        if not suggestion_id or len(suggestion_id) > 160:
            raise _invalid("suggestion_id is required and must be <=160 chars")
        if suggestion_id in seen_ids:
            raise MemoryGatewayError(
                status_code=409,
                code="memo_stack_mcp.conflict.duplicate_batch_item",
                message="duplicate suggestion_id in review batch",
                retryable=False,
            )
        seen_ids.add(suggestion_id)
        action = str(item.get("action") or "").strip()
        if action not in {"approve", "reject", "expire"}:
            raise _invalid(f"Invalid action: {action}")
        force = item.get("force", False)
        if not isinstance(force, bool):
            raise _invalid("force must be a boolean")
        reason = item.get("reason")
        if reason is not None and len(str(reason)) > 320:
            raise _invalid("reason must be <=320 chars")
        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "action": action,
                "reason": str(reason) if reason is not None else None,
                "force": force,
            }
        )
    return normalized


def _invalid(message: str) -> MemoryGatewayError:
    return MemoryGatewayError(
        status_code=400,
        code="memo_stack_mcp.validation.invalid_input",
        message=message,
        retryable=False,
    )
