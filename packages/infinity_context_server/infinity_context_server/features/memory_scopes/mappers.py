"""Mappers between HTTP contracts and memory_scopes application DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import infinity_context_core.features.memory_scopes.public as memory_scopes
from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
    CreateMemoryScopeResultDto,
    MemoryScopeDescriptorDto,
    ScopeIdentityDto,
)

from infinity_context_server.features.memory_scopes.compatibility import (
    create_memory_scope_contract_from_http_request,
    memory_scope_to_response,
)
from infinity_context_server.features.memory_scopes.contracts import (
    ArchiveMemoryScopeHttpRequest,
    MemoryScopeActorHttpRequest,
    MemoryScopeLifecycleHttpRequest,
    MemoryScopeOwnerHttpRequest,
    RestoreMemoryScopeHttpRequest,
    TransferMemoryScopeOwnershipHttpRequest,
)

DEFAULT_POLICY_MODE = "manual_only"


def create_memory_scope_command_from_contract(
    request: CreateMemoryScopeRequestDto,
    *,
    owner: MemoryScopeOwnerHttpRequest | Mapping[str, object],
) -> memory_scopes.CreateMemoryScopeCommand:
    """Map a public HTTP contract into the feature application command."""

    return memory_scopes.CreateMemoryScopeCommand(
        space_id=_required_text(request.space_id, "space_id"),
        name=_required_text(request.name, "name"),
        owner=memory_scope_owner_from_http(owner),
        external_ref=_required_text(request.external_ref, "external_ref"),
        description=_optional_text(request.description),
        idempotency_key=_optional_text(request.idempotency_key),
    )


def transfer_memory_scope_ownership_command_from_http(
    memory_scope_id: str,
    request: TransferMemoryScopeOwnershipHttpRequest | Mapping[str, object],
) -> memory_scopes.TransferMemoryScopeOwnershipCommand:
    """Map an HTTP ownership request into the feature application command."""

    return memory_scopes.TransferMemoryScopeOwnershipCommand(
        identity=memory_scopes.MemoryScopeIdentity(
            space_id=_required_text(_value(request, "space_id", None), "space_id"),
            memory_scope_id=_required_text(memory_scope_id, "memory_scope_id"),
        ),
        new_owner=memory_scope_owner_from_http(
            _required_value(request, "new_owner")
        ),
        initiated_by=memory_scope_actor_from_http(
            _required_value(request, "initiated_by")
        ),
        expected_current_owner=_optional_owner(
            _value(request, "expected_current_owner", None)
        ),
        reason=_optional_text(_value(request, "reason", None)),
        idempotency_key=_optional_text(_value(request, "idempotency_key", None)),
    )


def archive_memory_scope_command_from_http(
    memory_scope_id: str,
    request: ArchiveMemoryScopeHttpRequest | Mapping[str, object],
) -> memory_scopes.ArchiveMemoryScopeCommand:
    """Map an HTTP archive request into the feature application command."""

    return memory_scopes.ArchiveMemoryScopeCommand(
        identity=_memory_scope_identity_from_http(memory_scope_id, request),
        initiated_by=memory_scope_actor_from_http(
            _required_value(request, "initiated_by")
        ),
        expected_status=_optional_text(_value(request, "expected_status", None)),
        reason=_optional_text(_value(request, "reason", None)),
        idempotency_key=_optional_text(_value(request, "idempotency_key", None)),
    )


def restore_memory_scope_command_from_http(
    memory_scope_id: str,
    request: RestoreMemoryScopeHttpRequest | Mapping[str, object],
) -> memory_scopes.RestoreMemoryScopeCommand:
    """Map an HTTP restore request into the feature application command."""

    return memory_scopes.RestoreMemoryScopeCommand(
        identity=_memory_scope_identity_from_http(memory_scope_id, request),
        initiated_by=memory_scope_actor_from_http(
            _required_value(request, "initiated_by")
        ),
        expected_status=_optional_text(_value(request, "expected_status", None)),
        reason=_optional_text(_value(request, "reason", None)),
        idempotency_key=_optional_text(_value(request, "idempotency_key", None)),
    )


def memory_scope_owner_from_http(
    owner: MemoryScopeOwnerHttpRequest | Mapping[str, object],
) -> memory_scopes.MemoryScopeOwner:
    return memory_scopes.MemoryScopeOwner(
        principal_id=_required_text(_value(owner, "principal_id", None), "principal_id"),
        principal_kind=_required_text(
            _value(owner, "principal_kind", "user"),
            "principal_kind",
        ),
    )


def memory_scope_actor_from_http(
    actor: MemoryScopeActorHttpRequest | Mapping[str, object],
) -> memory_scopes.MemoryScopeActor:
    return memory_scopes.MemoryScopeActor(
        principal_id=_required_text(_value(actor, "principal_id", None), "principal_id"),
        principal_kind=_required_text(
            _value(actor, "principal_kind", "user"),
            "principal_kind",
        ),
        capabilities=_string_tuple(_value(actor, "capabilities", ())),
    )


def memory_scope_snapshot_to_contract(
    scope: memory_scopes.MemoryScopeSnapshot,
) -> MemoryScopeDescriptorDto:
    """Map a feature snapshot to the public HTTP descriptor contract."""

    return MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id=scope.identity.memory_scope_id,
            space_id=scope.identity.space_id,
            external_ref=scope.external_ref or "",
        ),
        name=scope.name,
        description=scope.description,
        status=scope.status,
        policy_mode=DEFAULT_POLICY_MODE,
        created_at=_datetime_to_string(scope.created_at),
        updated_at=_datetime_to_string(scope.updated_at),
        metadata={"owner": _owner_to_response(scope.owner)},
    )


def create_memory_scope_result_to_contract(
    result: memory_scopes.CreateMemoryScopeResult,
) -> CreateMemoryScopeResultDto:
    return CreateMemoryScopeResultDto(
        scope=memory_scope_snapshot_to_contract(result.scope),
        created=True,
    )


def transfer_memory_scope_ownership_result_to_response(
    result: memory_scopes.TransferMemoryScopeOwnershipResult,
) -> dict[str, Any]:
    return {
        "data": {
            "scope": memory_scope_snapshot_to_contract(result.scope).to_dict(),
            "previous_owner": _owner_to_response(result.previous_owner),
            "transferred": True,
        }
    }


def archive_memory_scope_result_to_response(
    result: memory_scopes.ArchiveMemoryScopeResult,
) -> dict[str, Any]:
    return _lifecycle_result_to_response(
        scope=result.scope,
        previous_status=result.previous_status,
        flag_name="archived",
    )


def restore_memory_scope_result_to_response(
    result: memory_scopes.RestoreMemoryScopeResult,
) -> dict[str, Any]:
    return _lifecycle_result_to_response(
        scope=result.scope,
        previous_status=result.previous_status,
        flag_name="restored",
    )


def _memory_scope_identity_from_http(
    memory_scope_id: str,
    request: MemoryScopeLifecycleHttpRequest | Mapping[str, object],
) -> memory_scopes.MemoryScopeIdentity:
    return memory_scopes.MemoryScopeIdentity(
        space_id=_required_text(_value(request, "space_id", None), "space_id"),
        memory_scope_id=_required_text(memory_scope_id, "memory_scope_id"),
    )


def _lifecycle_result_to_response(
    *,
    scope: memory_scopes.MemoryScopeSnapshot,
    previous_status: str,
    flag_name: str,
) -> dict[str, Any]:
    return {
        "data": {
            "scope": memory_scope_snapshot_to_contract(scope).to_dict(),
            "previous_status": previous_status,
            flag_name: True,
        }
    }


def _optional_owner(value: object) -> memory_scopes.MemoryScopeOwner | None:
    if value is None:
        return None
    if isinstance(value, Mapping) and not value:
        return None
    return memory_scope_owner_from_http(value)


def _owner_to_response(owner: memory_scopes.MemoryScopeOwner) -> dict[str, str]:
    return {
        "principal_id": owner.principal_id,
        "principal_kind": owner.principal_kind,
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


def _string_tuple(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ValueError("capabilities must be a sequence")
    return tuple(text for value in values if (text := str(value).strip()))


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


__all__ = (
    "DEFAULT_POLICY_MODE",
    "archive_memory_scope_command_from_http",
    "archive_memory_scope_result_to_response",
    "create_memory_scope_contract_from_http_request",
    "create_memory_scope_command_from_contract",
    "create_memory_scope_result_to_contract",
    "memory_scope_actor_from_http",
    "memory_scope_owner_from_http",
    "memory_scope_snapshot_to_contract",
    "memory_scope_to_response",
    "restore_memory_scope_command_from_http",
    "restore_memory_scope_result_to_response",
    "transfer_memory_scope_ownership_command_from_http",
    "transfer_memory_scope_ownership_result_to_response",
)
