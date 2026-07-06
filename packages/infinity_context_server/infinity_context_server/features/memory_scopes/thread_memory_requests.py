"""Thread-memory request and response seams for memory_scopes routes."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ThreadMemoryScopeRequest(BaseModel):
    """Scope selector accepted by the v1 thread-memory compatibility API."""

    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)


class _ThreadMemoryStatusResult(Protocol):
    chunks: int
    facts: int
    jobs: int
    pending_jobs: int


class _DeleteThreadMemoryResult(Protocol):
    deleted_chunks: int
    deleted_facts: int
    deleted_jobs: int


def thread_memory_scope_resolution_kwargs(
    request: ThreadMemoryScopeRequest,
) -> dict[str, Any]:
    """Return kwargs for resolving the existing single thread scope."""

    return {
        "space_id": request.space_id,
        "memory_scope_id": request.memory_scope_id,
        "thread_id": request.thread_id,
        "space_slug": request.space_slug,
        "memory_scope_external_ref": request.memory_scope_external_ref,
        "thread_external_ref": request.thread_external_ref,
        "thread_required": True,
    }


def empty_thread_memory_status_response() -> dict[str, Any]:
    """Return the v1 status response for an unresolved thread scope."""

    return {"data": empty_thread_memory_status_counts()}


def thread_memory_status_response(
    result: _ThreadMemoryStatusResult,
) -> dict[str, Any]:
    """Return the v1 status response for a resolved thread scope."""

    return {
        "data": {
            "chunks": result.chunks,
            "facts": result.facts,
            "jobs": result.jobs,
            "pending_jobs": result.pending_jobs,
        }
    }


def empty_thread_memory_delete_response() -> dict[str, Any]:
    """Return the v1 delete response for an unresolved thread scope."""

    return {"data": empty_thread_memory_delete_counts()}


def thread_memory_delete_response(
    result: _DeleteThreadMemoryResult,
) -> dict[str, Any]:
    """Return the v1 delete response for a resolved thread scope."""

    return {
        "data": {
            "deleted_chunks": result.deleted_chunks,
            "deleted_facts": result.deleted_facts,
            "deleted_jobs": result.deleted_jobs,
        }
    }


def empty_thread_memory_status_counts() -> dict[str, int]:
    """Return the empty v1 status count payload."""

    return {
        "chunks": 0,
        "facts": 0,
        "jobs": 0,
        "pending_jobs": 0,
    }


def empty_thread_memory_delete_counts() -> dict[str, int]:
    """Return the empty v1 delete count payload."""

    return {
        "deleted_chunks": 0,
        "deleted_facts": 0,
        "deleted_jobs": 0,
    }


__all__ = (
    "ThreadMemoryScopeRequest",
    "empty_thread_memory_delete_counts",
    "empty_thread_memory_delete_response",
    "empty_thread_memory_status_counts",
    "empty_thread_memory_status_response",
    "thread_memory_delete_response",
    "thread_memory_scope_resolution_kwargs",
    "thread_memory_status_response",
)
