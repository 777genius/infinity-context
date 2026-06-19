"""Visibility checks for context-link endpoints."""

from __future__ import annotations

from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.unit_of_work import UnitOfWorkPort

_ALLOWED_ENDPOINT_STATUSES: dict[str, set[str]] = {
    "anchor": {"active"},
    "asset": {"stored"},
    "asset_extraction": {"succeeded"},
    "capture": {"accepted"},
    "chunk": {"active"},
    "document": {"active"},
    "episode": {"active"},
    "fact": {"active", "disputed", "superseded"},
    "suggestion": {"pending", "approved", "rejected"},
    "thread": {"active"},
}


async def assert_context_link_endpoint_visible(
    uow: UnitOfWorkPort,
    *,
    endpoint_type: str,
    endpoint_id: str,
    space_id: str,
    memory_scope_id: str,
    role: str,
) -> None:
    normalized_type = endpoint_type.strip().lower()
    if normalized_type == "extraction_artifact":
        await _assert_extraction_artifact_visible(
            uow,
            endpoint_id=endpoint_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            role=role,
        )
        return
    allowed_statuses = _ALLOWED_ENDPOINT_STATUSES.get(normalized_type)
    if allowed_statuses is None:
        return

    entity = await _load_endpoint(uow, endpoint_type=normalized_type, endpoint_id=endpoint_id)
    if entity is None:
        raise MemoryValidationError(f"Context link {role} does not exist or is not visible")
    if str(entity.space_id) != space_id or str(entity.memory_scope_id) != memory_scope_id:
        raise MemoryValidationError(f"Context link {role} does not belong to scope")
    status = _status_value(getattr(entity, "status", None))
    if status not in allowed_statuses:
        raise MemoryValidationError(f"Context link {role} status is not linkable")


async def _load_endpoint(
    uow: UnitOfWorkPort,
    *,
    endpoint_type: str,
    endpoint_id: str,
) -> object | None:
    if endpoint_type == "anchor":
        return await uow.anchors.get_by_id(endpoint_id)
    if endpoint_type == "asset":
        return await uow.assets.get_by_id(endpoint_id)
    if endpoint_type == "asset_extraction":
        return await uow.asset_extractions.get_by_id(endpoint_id)
    if endpoint_type == "capture":
        return await uow.captures.get_by_id(endpoint_id)
    if endpoint_type == "chunk":
        return await uow.chunks.get_by_id(endpoint_id)
    if endpoint_type == "document":
        return await uow.documents.get_by_id(endpoint_id)
    if endpoint_type == "episode":
        return await uow.episodes.get_by_id(endpoint_id)
    if endpoint_type == "fact":
        return await uow.facts.get_by_id(endpoint_id)
    if endpoint_type == "suggestion":
        return await uow.suggestions.get_by_id(endpoint_id)
    if endpoint_type == "thread":
        return await uow.scope.get_thread(endpoint_id)
    return None


async def _assert_extraction_artifact_visible(
    uow: UnitOfWorkPort,
    *,
    endpoint_id: str,
    space_id: str,
    memory_scope_id: str,
    role: str,
) -> None:
    artifact = await uow.asset_extractions.get_artifact_by_id(endpoint_id)
    if artifact is None:
        raise MemoryValidationError(f"Context link {role} does not exist or is not visible")
    job = await uow.asset_extractions.get_by_id(str(artifact.job_id))
    if job is None:
        raise MemoryValidationError(f"Context link {role} does not exist or is not visible")
    if str(job.space_id) != space_id or str(job.memory_scope_id) != memory_scope_id:
        raise MemoryValidationError(f"Context link {role} does not belong to scope")
    if _status_value(job.status) != "succeeded":
        raise MemoryValidationError(f"Context link {role} status is not linkable")


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value)
