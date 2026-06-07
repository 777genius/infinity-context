"""Payload helpers for the public Memo Stack SDK."""

from __future__ import annotations

from typing import Any


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def single_scope_body(
    *,
    space_id: str | None,
    profile_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return without_none(
        {
            "space_id": space_id,
            "profile_id": profile_id,
            "thread_id": thread_id,
            "space_slug": space_slug,
            "profile_external_ref": profile_external_ref,
            "thread_external_ref": thread_external_ref,
        }
    )


def context_scope_payload(
    *,
    space_id: str | None,
    profile_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    profile_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> dict[str, Any]:
    return without_none(
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


def context_body(
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
    category: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    tags_none: list[str] | None = None,
) -> dict[str, Any]:
    payload = scope_payload or context_scope_payload(
        space_id=space_id,
        profile_ids=profile_ids,
        thread_id=thread_id,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        profile_external_refs=profile_external_refs,
        thread_external_ref=thread_external_ref,
    )
    return without_none(
        {
            **payload,
            "query": query,
            "token_budget": token_budget,
            "max_facts": max_facts,
            "max_chunks": max_chunks,
            "category": category,
            "tags_any": tags_any or None,
            "tags_all": tags_all or None,
            "tags_none": tags_none or None,
        }
    )


def context_scope_body(
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
    return without_none(
        {
            **context_scope_payload(
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


def validate_single_scope_payload(payload: dict[str, Any]) -> None:
    canonical = any(payload.get(key) for key in ("space_id", "profile_id", "thread_id"))
    external = any(
        payload.get(key) for key in ("space_slug", "profile_external_ref", "thread_external_ref")
    )
    if canonical and external:
        raise ValueError("Use either canonical ids or external refs, not both")
    if canonical and (not payload.get("space_id") or not payload.get("profile_id")):
        raise ValueError("space_id and profile_id are required with canonical scope")


def validate_read_scope_payload(payload: dict[str, Any]) -> None:
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
