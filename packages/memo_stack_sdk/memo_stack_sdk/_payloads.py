"""Payload helpers for the public Memo Stack SDK."""

from __future__ import annotations

from typing import Any


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def single_scope_body(
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return without_none(
        {
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "thread_id": thread_id,
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_external_ref,
            "thread_external_ref": thread_external_ref,
        }
    )


def context_scope_payload(
    *,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return without_none(
        {
            "space_id": space_id,
            "memory_scope_ids": memory_scope_ids,
            "thread_id": thread_id,
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_external_ref,
            "memory_scope_external_refs": memory_scope_external_refs,
            "thread_external_ref": thread_external_ref,
        }
    )


def context_body(
    *,
    scope_payload: dict[str, Any] | None,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
    query: str,
    token_budget: int,
    max_facts: int,
    max_chunks: int,
    consistency_mode: str | None = None,
    max_conflicting_suggestions: int | None = None,
    include_superseded: bool = False,
    include_stale: bool = False,
    category: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    tags_none: list[str] | None = None,
) -> dict[str, Any]:
    payload = scope_payload or context_scope_payload(
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        memory_scope_external_refs=memory_scope_external_refs,
        thread_external_ref=thread_external_ref,
    )
    return without_none(
        {
            **payload,
            "query": query,
            "consistency_mode": consistency_mode,
            "token_budget": token_budget,
            "max_facts": max_facts,
            "max_chunks": max_chunks,
            "max_conflicting_suggestions": max_conflicting_suggestions,
            "include_superseded": include_superseded if include_superseded else None,
            "include_stale": include_stale if include_stale else None,
            "category": category,
            "tags_any": tags_any or None,
            "tags_all": tags_all or None,
            "tags_none": tags_none or None,
        }
    )


def context_scope_body(
    *,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
    query: str,
    token_budget: int,
    max_facts: int,
    max_chunks: int,
    consistency_mode: str | None = None,
    max_conflicting_suggestions: int | None = None,
) -> dict[str, Any]:
    return without_none(
        {
            **context_scope_payload(
                space_id=space_id,
                memory_scope_ids=memory_scope_ids,
                thread_id=thread_id,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
                thread_external_ref=thread_external_ref,
            ),
            "query": query,
            "consistency_mode": consistency_mode,
            "token_budget": token_budget,
            "max_facts": max_facts,
            "max_chunks": max_chunks,
            "max_conflicting_suggestions": max_conflicting_suggestions,
        }
    )


def suggestions_batch_body(
    *,
    items: list[dict[str, Any]],
    space_id: str | None,
    memory_scope_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    continue_on_error: bool,
) -> dict[str, Any]:
    return without_none(
        {
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_external_ref,
            "items": items,
            "continue_on_error": continue_on_error,
        }
    )


def suggestion_body(
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    candidate_text: str,
    safe_reason: str,
    kind: str,
    source_refs: list[dict[str, Any]] | None,
    trust_level: str,
    confidence: str,
    target_fact_id: str | None,
    target_fact_version: int | None,
    operation: str,
    category: str | None,
    tags: list[str] | None,
    ttl_policy: str | None,
    review_payload: dict[str, Any] | None,
    candidate_fingerprint: str | None = None,
) -> dict[str, Any]:
    return without_none(
        {
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_external_ref,
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
            "candidate_fingerprint": candidate_fingerprint,
            "review_payload": review_payload,
        }
    )


def validate_single_scope_payload(payload: dict[str, Any]) -> None:
    canonical = any(payload.get(key) for key in ("space_id", "memory_scope_id", "thread_id"))
    external = any(
        payload.get(key)
        for key in ("space_slug", "memory_scope_external_ref", "thread_external_ref")
    )
    if canonical and external:
        raise ValueError("Use either canonical ids or external refs, not both")
    if canonical and (not payload.get("space_id") or not payload.get("memory_scope_id")):
        raise ValueError("space_id and memory_scope_id are required with canonical scope")


def validate_read_scope_payload(payload: dict[str, Any]) -> None:
    memory_scope_ids = payload.get("memory_scope_ids")
    raw_external_refs = []
    if payload.get("memory_scope_external_ref"):
        raw_external_refs.append(payload["memory_scope_external_ref"])
    raw_external_refs.extend(payload.get("memory_scope_external_refs") or ())
    external_refs = tuple(ref for ref in raw_external_refs if isinstance(ref, str))
    canonical = any(payload.get(key) for key in ("space_id", "memory_scope_ids", "thread_id"))
    external = any(
        payload.get(key)
        for key in (
            "space_slug",
            "memory_scope_external_ref",
            "memory_scope_external_refs",
            "thread_external_ref",
        )
    )
    if canonical and external:
        raise ValueError("Use memory_scope_ids/thread_id or external memory_scope refs, not both")
    if memory_scope_ids is not None:
        if not isinstance(memory_scope_ids, list) or not memory_scope_ids:
            raise ValueError("memory_scope_ids must be a non-empty list")
        if len(set(memory_scope_ids)) != len(memory_scope_ids):
            raise ValueError("memory_scope_ids must be unique")
        if not payload.get("space_id"):
            raise ValueError("space_id is required with memory_scope_ids")
    if external_refs and len(set(external_refs)) != len(external_refs):
        raise ValueError("memory_scope_external_refs must be unique")
    if payload.get("thread_external_ref") and len(external_refs) > 1:
        raise ValueError("thread_external_ref supports a single memory_scope for context")
