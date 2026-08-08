"""Server-owned authorization of dynamic CodeScope identities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from infinity_context_core.features.code_identity.domain.scope import CodeScopeLevel

_CODE_SCOPE_ID_RE = re.compile(r"code-scope-v1-[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CodeScopeAuthorizationStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class WorkspaceBindingStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class WorkspaceBindingSnapshot:
    binding_id: str
    repository_id: str
    space_id: str
    version: int
    grant_hash: str
    status: WorkspaceBindingStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", WorkspaceBindingStatus(self.status))
        for field_name in ("binding_id", "repository_id", "space_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Workspace binding {field_name} cannot be blank")
        if self.version < 1:
            raise ValueError("Workspace binding version must be positive")
        if not _SHA256_RE.fullmatch(self.grant_hash):
            raise ValueError("Workspace binding grant_hash must be lowercase sha256")


@dataclass(frozen=True, slots=True)
class CodeScopeAuthorization:
    """An admin-attested CodeScope accepted for one repository and space."""

    authorization_id: str
    repository_id: str
    space_id: str
    code_scope_id: str
    scope_level: CodeScopeLevel
    evidence_digest: str
    status: CodeScopeAuthorizationStatus
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_level", CodeScopeLevel(self.scope_level))
        object.__setattr__(self, "status", CodeScopeAuthorizationStatus(self.status))
        for field_name in ("authorization_id", "repository_id", "space_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"CodeScope authorization {field_name} cannot be blank")
        if not _CODE_SCOPE_ID_RE.fullmatch(self.code_scope_id):
            raise ValueError("CodeScope authorization requires a canonical code_scope_id")
        if not _SHA256_RE.fullmatch(self.evidence_digest):
            raise ValueError("CodeScope authorization evidence_digest must be lowercase sha256")
        if self.version < 1:
            raise ValueError("CodeScope authorization version must be positive")
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"CodeScope authorization {field_name} must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("CodeScope authorization updated_at cannot precede created_at")

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        repository_id: str,
        space_id: str,
        code_scope_id: str,
        scope_level: CodeScopeLevel,
        evidence_digest: str,
        now: datetime,
    ) -> CodeScopeAuthorization:
        return cls(
            authorization_id=authorization_id,
            repository_id=repository_id,
            space_id=space_id,
            code_scope_id=code_scope_id,
            scope_level=scope_level,
            evidence_digest=evidence_digest,
            status=CodeScopeAuthorizationStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        )


__all__ = (
    "CodeScopeAuthorization",
    "CodeScopeAuthorizationStatus",
    "WorkspaceBindingSnapshot",
    "WorkspaceBindingStatus",
)
