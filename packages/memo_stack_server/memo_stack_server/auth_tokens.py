"""Service token storage helpers.

Raw tokens are only returned on creation. Persistent state stores hashes only.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from memo_stack_adapters.postgres.models import (
    MemoryProfileRow,
    MemoryServiceTokenRow,
    MemorySpaceRow,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from memo_stack_server.composition import Container

MEMORY_PERMISSION_READ = "memory:read"
MEMORY_PERMISSION_WRITE = "memory:write"
MEMORY_PERMISSION_DELETE = "memory:delete"
MEMORY_PERMISSION_DIAGNOSTICS = "memory:diagnostics"
MEMORY_PERMISSION_ADMIN = "memory:admin"
ALL_MEMORY_PERMISSIONS = frozenset(
    {
        MEMORY_PERMISSION_READ,
        MEMORY_PERMISSION_WRITE,
        MEMORY_PERMISSION_DELETE,
        MEMORY_PERMISSION_DIAGNOSTICS,
        MEMORY_PERMISSION_ADMIN,
    }
)


@dataclass(frozen=True)
class CreatedServiceToken:
    token_id: str
    token: str
    space_id: str | None
    profile_ids: tuple[str, ...] | None
    description: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class ActiveServiceToken:
    token_id: str
    space_id: str | None
    profile_ids: frozenset[str] | None
    permissions: frozenset[str]


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
        token_id = row.id
        space_id = row.space_id
        profile_ids = _profile_ids_from_row(row.profile_ids_json)
        permissions = _permissions_from_row(row.permissions_json)
        row.last_used_at = now
        await session.commit()
        return ActiveServiceToken(
            token_id=token_id,
            space_id=space_id,
            profile_ids=profile_ids,
            permissions=permissions,
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
    profile_ids: tuple[str, ...] | None = None,
    expires_at: datetime | None = None,
    permissions: tuple[str, ...] | None = None,
) -> CreatedServiceToken:
    raw_token = f"mp_{secrets.token_urlsafe(32)}"
    normalized_permissions = _normalize_permissions(permissions)
    normalized_profile_ids = _normalize_profile_ids(profile_ids)
    if normalized_profile_ids is not None and space_id is None:
        raise ValueError("Profile scoped service token requires a space scope")
    async with AsyncSession(engine) as session:
        space_row = await _load_active_space(session, space_id) if space_id else None
        if space_id is not None and space_row is None:
            raise ValueError("Scoped service token space must exist and be active")
        if normalized_profile_ids is not None:
            for profile_id in normalized_profile_ids:
                if not await _profile_ref_exists_in_space(
                    session,
                    space_id=space_row.id,
                    profile_ref=profile_id,
                ):
                    raise ValueError(
                        "Profile scoped service token profiles must exist and be active"
                    )
        session.add(
            MemoryServiceTokenRow(
                id=token_id,
                space_id=space_id,
                profile_ids_json=(
                    list(normalized_profile_ids) if normalized_profile_ids is not None else None
                ),
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
        profile_ids=normalized_profile_ids,
        description=description,
        permissions=normalized_permissions,
    )


async def _load_active_space(
    session: AsyncSession,
    value: str,
) -> MemorySpaceRow | None:
    return (
        await session.execute(
            select(MemorySpaceRow).where(
                or_(MemorySpaceRow.id == value, MemorySpaceRow.slug == value),
                MemorySpaceRow.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _profile_ref_exists_in_space(
    session: AsyncSession,
    *,
    space_id: str,
    profile_ref: str,
) -> bool:
    profile = (
        await session.execute(
            select(MemoryProfileRow.id).where(
                MemoryProfileRow.space_id == space_id,
                or_(
                    MemoryProfileRow.id == profile_ref, MemoryProfileRow.external_ref == profile_ref
                ),
                MemoryProfileRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    return profile is not None


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
            "profile_ids": (
                sorted(profile_ids)
                if (profile_ids := _profile_ids_from_row(row.profile_ids_json)) is not None
                else None
            ),
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


def _normalize_profile_ids(profile_ids: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if profile_ids is None:
        return None
    deduped = tuple(sorted({profile_id for profile_id in profile_ids if profile_id}))
    if not deduped:
        raise ValueError("Profile scoped token must include at least one profile")
    return deduped


def _profile_ids_from_row(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return frozenset()
    return frozenset(profile_id for profile_id in value if isinstance(profile_id, str))
