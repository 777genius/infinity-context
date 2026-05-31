"""HTTP DTO scope resolution helpers for v1 routes."""

from __future__ import annotations

from dataclasses import dataclass

from memory_core.application import EnsureScopeCommand
from memory_core.domain.entities import ProfileId, SpaceId, ThreadId
from memory_core.domain.errors import MemoryValidationError
from memory_core.ports.auth import MemoryScope, ReadScope

from memory_server.auth_scope import canonical_scope_matches
from memory_server.composition import Container


@dataclass(frozen=True)
class SingleResolvedScope:
    space_id: SpaceId
    profile_id: ProfileId
    thread_id: ThreadId | None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        self.to_memory_scope()

    def to_memory_scope(self) -> MemoryScope:
        return MemoryScope(
            space_id=str(self.space_id),
            profile_id=str(self.profile_id),
            thread_id=str(self.thread_id) if self.thread_id else None,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )


@dataclass(frozen=True)
class ContextResolvedScope:
    space_id: SpaceId
    profile_ids: tuple[ProfileId, ...]
    thread_id: ThreadId | None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        self.to_read_scope()

    def to_read_scope(self) -> ReadScope:
        return ReadScope(
            space_id=str(self.space_id),
            profile_ids=tuple(str(profile_id) for profile_id in self.profile_ids),
            thread_id=str(self.thread_id) if self.thread_id else None,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )


async def resolve_single_scope(
    container: Container,
    *,
    space_id: str | None,
    profile_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    thread_external_ref: str | None,
    thread_required: bool,
) -> SingleResolvedScope:
    """Resolve either canonical IDs or human/external refs into a single scope."""

    using_ids = bool(space_id or profile_id or thread_id)
    using_external_refs = bool(space_slug or profile_external_ref or thread_external_ref)

    if using_ids and using_external_refs:
        raise MemoryValidationError("Use either canonical ids or external scope refs, not both")

    if using_ids:
        if not space_id or not profile_id:
            raise MemoryValidationError("space_id and profile_id are required with canonical scope")
        if thread_required and not thread_id:
            raise MemoryValidationError("thread_id is required for this operation")
        if not await canonical_scope_matches(
            container,
            space_id=space_id,
            profile_ids=(profile_id,),
            thread_id=thread_id,
        ):
            raise MemoryValidationError("Canonical scope ids do not belong together")
        return SingleResolvedScope(
            space_id=SpaceId(space_id),
            profile_id=ProfileId(profile_id),
            thread_id=ThreadId(thread_id) if thread_id else None,
        )

    if thread_required and not thread_external_ref:
        raise MemoryValidationError("thread_external_ref is required for this operation")

    scope = await container.ensure_scope.execute(
        EnsureScopeCommand(
            space_slug=space_slug or container.settings.default_space_slug,
            profile_external_ref=(
                profile_external_ref or container.settings.default_profile_external_ref
            ),
            thread_external_ref=thread_external_ref,
        )
    )
    if thread_required and scope.thread_id is None:
        raise MemoryValidationError("thread scope could not be resolved")
    return SingleResolvedScope(
        space_id=scope.space_id,
        profile_id=scope.profile_id,
        thread_id=scope.thread_id,
    )


async def resolve_context_scope(
    container: Container,
    *,
    space_id: str | None,
    profile_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    profile_external_ref: str | None,
    profile_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> ContextResolvedScope:
    """Resolve context scope while preserving the existing ID-based contract."""

    using_id_profiles = bool(profile_ids)
    using_external_scope = bool(space_slug or profile_external_ref or profile_external_refs)

    if using_id_profiles and (using_external_scope or thread_external_ref):
        raise MemoryValidationError(
            "Use profile_ids/thread_id or external profile refs/thread_external_ref, not both"
        )
    if using_id_profiles:
        if not space_id:
            raise MemoryValidationError("space_id is required with profile_ids")
        resolved_profile_ids = tuple(profile_ids or [])
        if len(set(resolved_profile_ids)) != len(resolved_profile_ids):
            raise MemoryValidationError("profile_ids cannot contain duplicates")
        if not await canonical_scope_matches(
            container,
            space_id=space_id,
            profile_ids=resolved_profile_ids,
            thread_id=thread_id,
        ):
            raise MemoryValidationError("Canonical scope ids do not belong together")
        return ContextResolvedScope(
            space_id=SpaceId(space_id),
            profile_ids=tuple(ProfileId(profile_id) for profile_id in resolved_profile_ids),
            thread_id=ThreadId(thread_id) if thread_id else None,
        )
    if space_id or thread_id:
        raise MemoryValidationError(
            "Canonical space_id/thread_id requires profile_ids; external scope uses space_slug"
        )

    refs = tuple(profile_external_refs or [])
    if profile_external_ref:
        refs = (profile_external_ref, *refs)
    if not refs:
        refs = (container.settings.default_profile_external_ref,)
    if len(set(refs)) != len(refs):
        raise MemoryValidationError("profile_external_refs must be unique")
    if len(refs) > 1 and thread_external_ref:
        raise MemoryValidationError("thread_external_ref supports a single profile for context")

    resolved = [
        await resolve_single_scope(
            container,
            space_id=None,
            profile_id=None,
            thread_id=None,
            space_slug=space_slug,
            profile_external_ref=ref,
            thread_external_ref=thread_external_ref,
            thread_required=False,
        )
        for ref in refs
    ]
    space_ids = {scope.space_id for scope in resolved}
    if len(space_ids) != 1:
        raise MemoryValidationError("Resolved profiles must belong to one space")
    return ContextResolvedScope(
        space_id=resolved[0].space_id,
        profile_ids=tuple(scope.profile_id for scope in resolved),
        thread_id=resolved[0].thread_id,
    )
