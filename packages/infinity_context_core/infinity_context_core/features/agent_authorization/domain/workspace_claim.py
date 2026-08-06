"""Authenticated request-scoped workspace identity claim."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from infinity_context_core.features.agent_authorization.domain.context import (
    AgentScopeResolutionMethod,
)

WORKSPACE_SCOPE_CLAIM_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorkspaceScopeClaim:
    """Short-lived repository/code scope asserted by a trusted local adapter."""

    issued_at_epoch_seconds: int
    repository_id: str
    code_scope_id: str
    resolution_method: AgentScopeResolutionMethod
    binding_id: str | None = None
    binding_version: int | None = None
    drift_status: str = "stable"
    version: int = WORKSPACE_SCOPE_CLAIM_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolution_method",
            AgentScopeResolutionMethod(self.resolution_method),
        )
        if self.version != WORKSPACE_SCOPE_CLAIM_VERSION:
            raise ValueError("Unsupported workspace scope claim version")
        if self.issued_at_epoch_seconds < 1:
            raise ValueError("Workspace scope claim issued_at must be positive")
        _require_opaque("repository_id", self.repository_id)
        _require_opaque("code_scope_id", self.code_scope_id)
        if self.binding_id is not None:
            _require_opaque("binding_id", self.binding_id)
        if self.binding_version is not None and self.binding_version < 1:
            raise ValueError("Workspace scope claim binding_version must be positive")
        if not self.drift_status.strip():
            raise ValueError("Workspace scope claim drift_status cannot be blank")

    def to_payload(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "code_scope_id": self.code_scope_id,
            "drift_status": self.drift_status,
            "issued_at": self.issued_at_epoch_seconds,
            "repository_id": self.repository_id,
            "resolution_method": self.resolution_method.value,
            "version": self.version,
        }


def encode_workspace_scope_claim(claim: WorkspaceScopeClaim) -> str:
    raw = json.dumps(
        claim.to_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_workspace_scope_claim(encoded: str) -> WorkspaceScopeClaim:
    if not encoded or len(encoded) > 2048:
        raise ValueError("Invalid workspace scope claim payload")
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("Invalid workspace scope claim payload") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "binding_id",
        "binding_version",
        "code_scope_id",
        "drift_status",
        "issued_at",
        "repository_id",
        "resolution_method",
        "version",
    }:
        raise ValueError("Invalid workspace scope claim fields")
    return _claim_from_payload(payload)


def _claim_from_payload(payload: dict[str, Any]) -> WorkspaceScopeClaim:
    try:
        return WorkspaceScopeClaim(
            issued_at_epoch_seconds=_strict_int(payload["issued_at"]),
            repository_id=_strict_str(payload["repository_id"]),
            code_scope_id=_strict_str(payload["code_scope_id"]),
            resolution_method=AgentScopeResolutionMethod(_strict_str(payload["resolution_method"])),
            binding_id=_optional_str(payload["binding_id"]),
            binding_version=_optional_int(payload["binding_version"]),
            drift_status=_strict_str(payload["drift_status"]),
            version=_strict_int(payload["version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid workspace scope claim values") from exc


def _strict_str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected string")
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _strict_str(value)


def _strict_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Expected integer")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _strict_int(value)


def _require_opaque(field_name: str, value: str) -> None:
    if not value.strip() or any(marker in value for marker in ("/", "\\", "://", "@")):
        raise ValueError(f"{field_name} must be an opaque identifier")


__all__ = (
    "WORKSPACE_SCOPE_CLAIM_VERSION",
    "WorkspaceScopeClaim",
    "decode_workspace_scope_claim",
    "encode_workspace_scope_claim",
)
