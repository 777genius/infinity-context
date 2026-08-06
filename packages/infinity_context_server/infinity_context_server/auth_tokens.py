"""Service token storage helpers.

Raw tokens are only returned on creation. Persistent state stores hashes only.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from infinity_context_adapters.postgres.feature_models import CodeRepositoryRow
from infinity_context_adapters.postgres.models import (
    MemoryScopeRow,
    MemoryServiceTokenRow,
    MemorySpaceRow,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from infinity_context_server.composition import Container

MEMORY_PERMISSION_READ = "memory:read"
MEMORY_PERMISSION_WRITE = "memory:write"
MEMORY_PERMISSION_DELETE = "memory:delete"
MEMORY_PERMISSION_DIAGNOSTICS = "memory:diagnostics"
MEMORY_PERMISSION_ADMIN = "memory:admin"
MEMORY_PERMISSION_CAPTURE = "memory:capture"
MEMORY_PERMISSION_FACT_WRITE = "memory:fact_write"
MEMORY_PERMISSION_GOVERN = "memory:govern"
ALL_MEMORY_PERMISSIONS = frozenset(
    {
        MEMORY_PERMISSION_READ,
        MEMORY_PERMISSION_WRITE,
        MEMORY_PERMISSION_DELETE,
        MEMORY_PERMISSION_DIAGNOSTICS,
        MEMORY_PERMISSION_ADMIN,
        MEMORY_PERMISSION_CAPTURE,
        MEMORY_PERMISSION_FACT_WRITE,
        MEMORY_PERMISSION_GOVERN,
    }
)


@dataclass(frozen=True)
class CreatedServiceToken:
    token_id: str
    token: str
    space_id: str | None
    memory_scope_ids: tuple[str, ...] | None
    description: str
    permissions: tuple[str, ...]
    repository_id: str | None = None
    code_scope_id: str | None = None


@dataclass(frozen=True)
class ActiveServiceToken:
    token_id: str
    space_id: str | None
    memory_scope_ids: frozenset[str] | None
    permissions: frozenset[str]
    repository_id: str | None = None
    code_scope_id: str | None = None
    binding_active: bool = True


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


async def get_active_db_token(container: Container, token: str) -> ActiveServiceToken | None:
    now = container.clock.now()
    async with AsyncSession(container.engine) as session:
        row = (
            await session.execute(
                select(MemoryServiceTokenRow).where(
                    MemoryServiceTokenRow.token_hash == token_hash(token),
                    MemoryServiceTokenRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if _is_expired(row.expires_at, now):
            return None
        space_row = await _load_space(session, row.space_id) if row.space_id else None
        binding_active = row.space_id is None or (
            space_row is not None and space_row.status == "active"
        )
        token_id = row.id
        space_id = space_row.id if space_row is not None else None
        stored_memory_scope_ids = _memory_scope_ids_from_row(row.memory_scope_ids_json)
        memory_scope_ids = await _canonical_memory_scope_ids(
            session,
            space_id=space_id,
            memory_scope_refs=stored_memory_scope_ids,
            active_only=False,
        )
        if stored_memory_scope_ids is not None and memory_scope_ids is None:
            memory_scope_ids = stored_memory_scope_ids
            binding_active = False
        elif memory_scope_ids is not None:
            binding_active = binding_active and await _memory_scopes_are_active(
                session,
                memory_scope_ids,
            )
        if row.repository_id is not None:
            repository = await session.get(CodeRepositoryRow, row.repository_id)
            if (
                repository is None
                or repository.status != "active"
                or repository.space_id != space_id
                or memory_scope_ids is None
            ):
                binding_active = False
        permissions = _permissions_from_row(row.permissions_json)
        repository_id = row.repository_id
        code_scope_id = row.code_scope_id
        row.last_used_at = now
        await session.commit()
        return ActiveServiceToken(
            token_id=token_id,
            space_id=space_id,
            memory_scope_ids=memory_scope_ids,
            repository_id=repository_id,
            code_scope_id=code_scope_id,
            permissions=permissions,
            binding_active=binding_active,
        )


async def is_active_db_token(container: Container, token: str) -> bool:
    return await get_active_db_token(container, token) is not None


async def create_service_token(
    *,
    engine: AsyncEngine,
    now,
    token_id: str,
    description: str,
    space_id: str | None,
    memory_scope_ids: tuple[str, ...] | None = None,
    repository_id: str | None = None,
    code_scope_id: str | None = None,
    expires_at: datetime | None = None,
    permissions: tuple[str, ...] | None = None,
) -> CreatedServiceToken:
    raw_token = f"mp_{secrets.token_urlsafe(32)}"
    normalized_permissions = _normalize_permissions(permissions)
    normalized_memory_scope_ids = _normalize_memory_scope_ids(memory_scope_ids)
    if normalized_memory_scope_ids is not None and space_id is None:
        raise ValueError("MemoryScope scoped service token requires a space scope")
    if repository_id is not None and (space_id is None or normalized_memory_scope_ids is None):
        raise ValueError("Repository-scoped service token requires Space and MemoryScope scope")
    if code_scope_id is not None and repository_id is None:
        raise ValueError("CodeScope-scoped service token requires a repository scope")
    if code_scope_id is not None and (
        not code_scope_id.strip()
        or len(code_scope_id) > 96
        or any(marker in code_scope_id for marker in ("/", "\\", "://", "@"))
    ):
        raise ValueError("Service token code_scope_id must be an opaque identifier")
    async with AsyncSession(engine) as session:
        space_row = await _load_active_space(session, space_id) if space_id else None
        if space_id is not None and space_row is None:
            raise ValueError("Scoped service token space must exist and be active")
        canonical_memory_scope_ids = await _canonical_memory_scope_ids(
            session,
            space_id=space_row.id if space_row is not None else None,
            memory_scope_refs=(
                frozenset(normalized_memory_scope_ids)
                if normalized_memory_scope_ids is not None
                else None
            ),
        )
        if normalized_memory_scope_ids is not None and canonical_memory_scope_ids is None:
            raise ValueError(
                "MemoryScope scoped service token memory_scopes must exist and be active"
            )
        if repository_id is not None:
            repository = await session.get(CodeRepositoryRow, repository_id)
            if (
                repository is None
                or repository.space_id != space_row.id
                or repository.status != "active"
            ):
                raise ValueError(
                    "Repository-scoped service token repository must be active in its space"
                )
        canonical_space_id = space_row.id if space_row is not None else None
        session.add(
            MemoryServiceTokenRow(
                id=token_id,
                space_id=canonical_space_id,
                memory_scope_ids_json=(
                    sorted(canonical_memory_scope_ids)
                    if canonical_memory_scope_ids is not None
                    else None
                ),
                repository_id=repository_id,
                code_scope_id=code_scope_id,
                description=description,
                token_hash=token_hash(raw_token),
                permissions_json=list(normalized_permissions),
                status="active",
                created_at=now,
                last_used_at=None,
                expires_at=expires_at,
                revoked_at=None,
            )
        )
        await session.commit()
    return CreatedServiceToken(
        token_id=token_id,
        token=raw_token,
        space_id=space_id,
        memory_scope_ids=(
            normalized_memory_scope_ids if normalized_memory_scope_ids is not None else None
        ),
        repository_id=repository_id,
        code_scope_id=code_scope_id,
        description=description,
        permissions=normalized_permissions,
    )


async def _load_active_space(
    session: AsyncSession,
    value: str | None,
) -> MemorySpaceRow | None:
    if value is None:
        return None
    return (
        await session.execute(
            select(MemorySpaceRow).where(
                or_(MemorySpaceRow.id == value, MemorySpaceRow.slug == value),
                MemorySpaceRow.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _load_space(
    session: AsyncSession,
    value: str | None,
) -> MemorySpaceRow | None:
    if value is None:
        return None
    return (
        await session.execute(
            select(MemorySpaceRow).where(
                or_(MemorySpaceRow.id == value, MemorySpaceRow.slug == value),
            )
        )
    ).scalar_one_or_none()


async def _canonical_memory_scope_ids(
    session: AsyncSession,
    *,
    space_id: str | None,
    memory_scope_refs: frozenset[str] | None,
    active_only: bool = True,
) -> frozenset[str] | None:
    if memory_scope_refs is None:
        return None
    if space_id is None:
        return None
    conditions = [
        MemoryScopeRow.space_id == space_id,
        or_(
            MemoryScopeRow.id.in_(memory_scope_refs),
            MemoryScopeRow.external_ref.in_(memory_scope_refs),
        ),
    ]
    if active_only:
        conditions.append(MemoryScopeRow.status == "active")
    rows = (await session.execute(select(MemoryScopeRow.id).where(*conditions))).scalars()
    canonical_ids = frozenset(rows)
    return canonical_ids if len(canonical_ids) == len(memory_scope_refs) else None


async def _memory_scopes_are_active(
    session: AsyncSession,
    memory_scope_ids: frozenset[str],
) -> bool:
    active_ids = frozenset(
        (
            await session.execute(
                select(MemoryScopeRow.id).where(
                    MemoryScopeRow.id.in_(memory_scope_ids),
                    MemoryScopeRow.status == "active",
                )
            )
        ).scalars()
    )
    return active_ids == memory_scope_ids


async def list_service_tokens(
    *,
    engine: AsyncEngine,
    space_id: str | None,
) -> list[dict[str, object]]:
    async with AsyncSession(engine) as session:
        query = select(MemoryServiceTokenRow).order_by(MemoryServiceTokenRow.created_at.desc())
        if space_id is not None:
            query = query.where(MemoryServiceTokenRow.space_id == space_id)
        rows = list((await session.execute(query)).scalars())
    return [
        {
            "id": row.id,
            "space_id": row.space_id,
            "memory_scope_ids": (
                sorted(memory_scope_ids)
                if (memory_scope_ids := _memory_scope_ids_from_row(row.memory_scope_ids_json))
                is not None
                else None
            ),
            "repository_id": row.repository_id,
            "code_scope_id": row.code_scope_id,
            "description": row.description,
            "permissions": sorted(_permissions_from_row(row.permissions_json)),
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }
        for row in rows
    ]


async def revoke_service_token(*, engine: AsyncEngine, now, token_id: str) -> dict[str, object]:
    async with AsyncSession(engine) as session:
        row = await session.get(MemoryServiceTokenRow, token_id)
        if row is None:
            return {"status": "not_found", "token_id": token_id}
        if row.status != "revoked":
            row.status = "revoked"
            row.revoked_at = now
        await session.commit()
    return {"status": "revoked", "token_id": token_id}


def _is_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    comparable_now = now
    comparable_expires_at = expires_at
    if comparable_expires_at.tzinfo is None and comparable_now.tzinfo is not None:
        comparable_now = comparable_now.replace(tzinfo=None)
    elif comparable_expires_at.tzinfo is not None and comparable_now.tzinfo is None:
        comparable_expires_at = comparable_expires_at.replace(tzinfo=None)
    return comparable_expires_at <= comparable_now


def _normalize_permissions(permissions: tuple[str, ...] | None) -> tuple[str, ...]:
    if permissions is None:
        return tuple(sorted(ALL_MEMORY_PERMISSIONS))
    unknown = sorted(set(permissions) - ALL_MEMORY_PERMISSIONS)
    if unknown:
        raise ValueError(f"Unknown memory permissions: {', '.join(unknown)}")
    deduped = tuple(sorted(set(permissions)))
    if not deduped:
        raise ValueError("Service token must have at least one permission")
    return deduped


def _permissions_from_row(value: object) -> frozenset[str]:
    if value is None:
        return ALL_MEMORY_PERMISSIONS
    if not isinstance(value, list):
        return frozenset()
    return frozenset(permission for permission in value if isinstance(permission, str))


def _normalize_memory_scope_ids(memory_scope_ids: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if memory_scope_ids is None:
        return None
    deduped = tuple(
        sorted({memory_scope_id for memory_scope_id in memory_scope_ids if memory_scope_id})
    )
    if not deduped:
        raise ValueError("MemoryScope scoped token must include at least one memory_scope")
    return deduped


def _memory_scope_ids_from_row(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        memory_scope_id for memory_scope_id in value if isinstance(memory_scope_id, str)
    )
