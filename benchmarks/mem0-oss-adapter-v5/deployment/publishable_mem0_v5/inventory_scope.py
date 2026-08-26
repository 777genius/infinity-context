"""Explicit Docker inventory authority for publishable lane operations."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

GLOBAL_INVENTORY_SCOPE: Final = "global"
PROJECT_INVENTORY_SCOPE: Final = "project"
INVENTORY_SCOPES: Final = (GLOBAL_INVENTORY_SCOPE, PROJECT_INVENTORY_SCOPE)

InventoryScope: TypeAlias = Literal["global", "project"]


def require_inventory_scope(value: str) -> InventoryScope:
    if value not in INVENTORY_SCOPES:
        raise ValueError("publishable_docker_inventory_scope_invalid")
    return value  # type: ignore[return-value]


__all__ = (
    "GLOBAL_INVENTORY_SCOPE",
    "INVENTORY_SCOPES",
    "PROJECT_INVENTORY_SCOPE",
    "InventoryScope",
    "require_inventory_scope",
)
