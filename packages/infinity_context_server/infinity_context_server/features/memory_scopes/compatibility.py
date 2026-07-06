"""Compatibility HTTP mapping for the legacy /v1/memory-scopes API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
)
from pydantic import BaseModel, ConfigDict, Field


class CreateMemoryScopeRequest(BaseModel):
    """Legacy-compatible request body for creating a memory scope."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    external_ref: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=240)


class UpdateMemoryScopeRequest(BaseModel):
    """Legacy-compatible request body for updating a memory scope."""

    model_config = ConfigDict(extra="forbid")

    external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=240)


@dataclass(frozen=True, slots=True)
class CreateMemoryScopeCompatibilityCommand:
    """Core-agnostic command payload for legacy scope creation."""

    space_id: str
    external_ref: str
    name: str


@dataclass(frozen=True, slots=True)
class UpdateMemoryScopeCompatibilityCommand:
    """Core-agnostic command payload for legacy scope updates."""

    memory_scope_id: str
    external_ref: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteMemoryScopeCompatibilityCommand:
    """Core-agnostic command payload for legacy scope deletion."""

    memory_scope_id: str


def create_memory_scope_contract_from_http_request(
    request: object,
) -> CreateMemoryScopeRequestDto:
    """Map a legacy-compatible HTTP request into the public scope contract."""

    return CreateMemoryScopeRequestDto(
        space_id=_required_text(_value(request, "space_id", None), "space_id"),
        external_ref=_required_text(
            _value(request, "external_ref", None),
            "external_ref",
        ),
        name=_required_text(_value(request, "name", None), "name"),
    )


def create_memory_scope_compatibility_command_from_request(
    request: CreateMemoryScopeRequest | Mapping[str, object],
) -> CreateMemoryScopeCompatibilityCommand:
    """Map a legacy create request into a core-agnostic command payload."""

    contract = create_memory_scope_contract_from_http_request(request)
    return CreateMemoryScopeCompatibilityCommand(
        space_id=_required_text(contract.space_id, "space_id"),
        external_ref=_required_text(contract.external_ref, "external_ref"),
        name=_required_text(contract.name, "name"),
    )


def update_memory_scope_compatibility_command_from_request(
    memory_scope_id: str,
    request: UpdateMemoryScopeRequest | Mapping[str, object],
) -> UpdateMemoryScopeCompatibilityCommand:
    """Map a legacy update request into a core-agnostic command payload."""

    external_ref = _optional_text(_value(request, "external_ref", None))
    name = _optional_text(_value(request, "name", None))
    if external_ref is None and name is None:
        raise ValueError("At least one memory_scope field is required")
    return UpdateMemoryScopeCompatibilityCommand(
        memory_scope_id=_required_text(memory_scope_id, "memory_scope_id"),
        external_ref=external_ref,
        name=name,
    )


def delete_memory_scope_compatibility_command_from_path(
    memory_scope_id: str,
) -> DeleteMemoryScopeCompatibilityCommand:
    """Map a legacy delete path parameter into a core-agnostic command payload."""

    return DeleteMemoryScopeCompatibilityCommand(
        memory_scope_id=_required_text(memory_scope_id, "memory_scope_id"),
    )


def memory_scope_compatibility_response(memory_scope: object) -> dict[str, Any]:
    """Return the legacy response envelope for one memory scope."""

    return {"data": memory_scope_to_response(memory_scope)}


def memory_scope_collection_compatibility_response(
    memory_scopes: Iterable[object],
) -> dict[str, Any]:
    """Return the legacy response envelope for a memory scope collection."""

    return {"data": [memory_scope_to_response(memory_scope) for memory_scope in memory_scopes]}


def memory_scope_to_response(memory_scope: object) -> dict[str, Any]:
    """Map a memory scope entity-like object to the legacy response body."""

    return {
        "id": str(_required_value(memory_scope, "id")),
        "space_id": str(_required_value(memory_scope, "space_id")),
        "external_ref": _required_text(
            _value(memory_scope, "external_ref", None),
            "external_ref",
        ),
        "name": _required_text(_value(memory_scope, "name", None), "name"),
        "status": _enum_or_text(_value(memory_scope, "status", "active")),
        "created_at": _datetime_to_string(_required_value(memory_scope, "created_at")),
        "updated_at": _datetime_to_string(_required_value(memory_scope, "updated_at")),
    }


def thread_to_response(thread: object) -> dict[str, Any]:
    """Map a memory thread entity-like object to the legacy browser response body."""

    return {
        "id": str(_required_value(thread, "id")),
        "space_id": str(_required_value(thread, "space_id")),
        "memory_scope_id": str(_required_value(thread, "memory_scope_id")),
        "external_ref": _value(thread, "external_ref", None),
        "status": _enum_or_text(_required_value(thread, "status")),
        "created_at": _datetime_to_string(_required_value(thread, "created_at")),
        "updated_at": _datetime_to_string(_required_value(thread, "updated_at")),
    }


def _required_value(source: object, name: str) -> object:
    value = _value(source, name, None)
    if value is None:
        raise ValueError(f"{name} is required")
    return value


def _value(source: object, name: str, default: object) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _enum_or_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


__all__ = (
    "CreateMemoryScopeCompatibilityCommand",
    "CreateMemoryScopeRequest",
    "DeleteMemoryScopeCompatibilityCommand",
    "UpdateMemoryScopeCompatibilityCommand",
    "UpdateMemoryScopeRequest",
    "create_memory_scope_compatibility_command_from_request",
    "create_memory_scope_contract_from_http_request",
    "delete_memory_scope_compatibility_command_from_path",
    "memory_scope_collection_compatibility_response",
    "memory_scope_compatibility_response",
    "memory_scope_to_response",
    "thread_to_response",
    "update_memory_scope_compatibility_command_from_request",
)
